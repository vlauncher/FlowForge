"""In-memory sliding window rate limiting middleware enforcing §10 security rules."""

from __future__ import annotations

import collections
import json
import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.security import decode_access_token

logger = logging.getLogger("flowforge.rate_limit")

# Global in-memory storage: key -> list of float timestamps
_RATE_LIMIT_BUCKETS: dict[str, list[float]] = collections.defaultdict(list)


def clear_rate_limits() -> None:
    """Clear all rate limiting buckets (useful for test isolation)."""
    _RATE_LIMIT_BUCKETS.clear()


class RateLimitMiddleware:
    """Enforces API rate limits according to FlowForge spec §10:

    - Login: 10/min per IP + email
    - Signup: 5/hour per IP
    - Other API: 300/min per user
    """

    def __init__(self, app: ASGIApp, enabled: bool = True) -> None:
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not self.enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()

        # Extract client IP
        client_ip = "127.0.0.1"
        for name, val in scope.get("headers", []):
            if name.lower() == b"x-forwarded-for":
                try:
                    client_ip = val.decode("latin1").split(",")[0].strip()
                    break
                except Exception:
                    pass
        else:
            client = scope.get("client")
            if client:
                client_ip = client[0]

        rate_key: str | None = None
        limit = 300
        window = 60

        receive_to_pass = receive

        if path == "/v1/auth/login" and method == "POST":
            # Buffer body to extract email
            body_chunks: list[bytes] = []
            messages: list[Message] = []
            more_body = True
            while more_body:
                msg = await receive()
                messages.append(msg)
                if msg["type"] == "http.request":
                    body_chunks.append(msg.get("body", b""))
                    more_body = msg.get("more_body", False)
                else:
                    break

            raw_body = b"".join(body_chunks)
            email = ""
            if raw_body:
                try:
                    payload = json.loads(raw_body.decode("utf-8"))
                    if isinstance(payload, dict):
                        email = str(payload.get("email", "")).lower().strip()
                except Exception:
                    pass

            rate_key = f"login:{client_ip}:{email}"
            limit = 10
            window = 60

            # Create replay receive callable
            msg_iter = iter(messages)

            async def replay_receive() -> Message:
                return next(msg_iter)

            receive_to_pass = replay_receive

        elif path == "/v1/auth/signup" and method == "POST":
            rate_key = f"signup:{client_ip}"
            limit = 5
            window = 3600

        elif path.startswith("/v1/") and not path.startswith("/v1/auth/"):
            # Check user token
            auth_token: str | None = None
            for name, val in scope.get("headers", []):
                if name.lower() == b"authorization":
                    try:
                        header_str = val.decode("latin1").strip()
                        if header_str.lower().startswith("bearer "):
                            auth_token = header_str[7:].strip()
                    except Exception:
                        pass
                    break

            if auth_token:
                try:
                    claims = decode_access_token(auth_token)
                    user_id = claims.get("sub")
                    if user_id:
                        rate_key = f"user:{user_id}"
                        limit = 300
                        window = 60
                except Exception:
                    pass

        if rate_key is not None:
            now = time.time()
            cutoff = now - window
            bucket = _RATE_LIMIT_BUCKETS[rate_key]
            # Prune expired timestamps
            _RATE_LIMIT_BUCKETS[rate_key] = [t for t in bucket if t > cutoff]
            bucket = _RATE_LIMIT_BUCKETS[rate_key]

            if len(bucket) >= limit:
                oldest = bucket[0]
                retry_after = max(1, int(oldest + window - now))
                req_id = scope.get("state", {}).get("request_id", "")
                await self._send_429(send, path, req_id, retry_after)
                return

            bucket.append(now)

        await self.app(scope, receive_to_pass, send)

    async def _send_429(self, send: Send, path: str, req_id: str, retry_after: int) -> None:
        payload = json.dumps(
            {
                "type": "https://flowforge.dev/errors/RATE_LIMITED",
                "title": "Too Many Requests",
                "status": 429,
                "detail": f"Rate limit exceeded. Retry after {retry_after} seconds.",
                "instance": path,
                "code": "RATE_LIMITED",
                "request_id": req_id,
            }
        ).encode("utf-8")

        headers = [
            (b"content-type", b"application/problem+json"),
            (b"content-length", str(len(payload)).encode("ascii")),
            (b"retry-after", str(retry_after).encode("ascii")),
        ]
        if req_id:
            headers.append((b"x-request-id", req_id.encode("utf-8")))

        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": headers,
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": payload,
            }
        )
