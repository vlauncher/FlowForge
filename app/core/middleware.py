"""ASGI middleware components."""

from __future__ import annotations

import json
import re

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.ids import new_id
from app.core.request_context import request_id_var

REQUEST_ID_REGEX = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestIdMiddleware:
    """Ensure every HTTP request has an X-Request-ID in context and response headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming_id: str | None = None
        for name, value in scope.get("headers", []):
            if name.lower() == b"x-request-id":
                try:
                    decoded = value.decode("utf-8").strip()
                    if REQUEST_ID_REGEX.match(decoded):
                        incoming_id = decoded
                except UnicodeDecodeError:
                    pass
                break

        req_id = incoming_id if incoming_id else str(new_id())
        token = request_id_var.set(req_id)

        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = req_id

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                # Add X-Request-ID header if not already present
                has_req_id = any(h[0].lower() == b"x-request-id" for h in headers)
                if not has_req_id:
                    headers.append((b"x-request-id", req_id.encode("utf-8")))
                    message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_var.reset(token)


class BodySizeLimitMiddleware:
    """Enforce a maximum body size on incoming HTTP requests."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length: int | None = None
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    content_length = int(value.decode("ascii"))
                except (ValueError, UnicodeDecodeError):
                    pass
                break

        path = scope.get("path", "")
        req_id = scope.get("state", {}).get("request_id", "")

        # If header declares content exceeding limit, reject immediately
        if content_length is not None and content_length > self.max_bytes:
            await self._send_413(send, path, req_id)
            return

        received_bytes = 0
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        async def receive_wrapper() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                received_bytes += len(body)
                if received_bytes > self.max_bytes:
                    if not response_started:
                        await self._send_413(send, path, req_id)
                    raise RuntimeError("Payload too large")
            return message

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        except RuntimeError as exc:
            if str(exc) == "Payload too large":
                return
            raise

    async def _send_413(self, send: Send, path: str, req_id: str) -> None:
        detail_msg = f"Request body exceeds maximum allowed size of {self.max_bytes} bytes."
        payload = json.dumps(
            {
                "type": "https://flowforge.dev/errors/PAYLOAD_TOO_LARGE",
                "title": "Payload Too Large",
                "status": 413,
                "detail": detail_msg,
                "instance": path,
                "code": "PAYLOAD_TOO_LARGE",
                "request_id": req_id,
            }
        ).encode("utf-8")

        headers = [
            (b"content-type", b"application/problem+json"),
            (b"content-length", str(len(payload)).encode("ascii")),
        ]
        if req_id:
            headers.append((b"x-request-id", req_id.encode("utf-8")))

        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": headers,
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": payload,
            }
        )
