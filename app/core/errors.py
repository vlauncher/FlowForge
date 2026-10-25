"""Standardized Problem Details error handling."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import get_request_id

logger = logging.getLogger("flowforge.errors")


class AppError(Exception):
    """Base application exception mapping to RFC 9457 Problem Details."""

    def __init__(
        self,
        code: str,
        status: int,
        title: str,
        detail: str | None = None,
        errors: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail or title
        self.errors = errors
        self.headers = headers


class NotFoundError(AppError):
    def __init__(self, detail: str = "Resource not found") -> None:
        super().__init__(
            code="NOT_FOUND",
            status=404,
            title="Not Found",
            detail=detail,
        )


class ForbiddenError(AppError):
    def __init__(self, detail: str = "Forbidden") -> None:
        super().__init__(
            code="FORBIDDEN",
            status=403,
            title="Forbidden",
            detail=detail,
        )


class UnauthenticatedError(AppError):
    def __init__(
        self,
        detail: str = "Authentication required",
        headers: dict[str, str] | None = None,
    ) -> None:
        hdr = {"WWW-Authenticate": "Bearer"}
        if headers:
            hdr.update(headers)
        super().__init__(
            code="UNAUTHENTICATED",
            status=401,
            title="Unauthorized",
            detail=detail,
            headers=hdr,
        )


class ConflictError(AppError):
    def __init__(self, detail: str = "Resource conflict") -> None:
        super().__init__(
            code="CONFLICT",
            status=409,
            title="Conflict",
            detail=detail,
        )


class EmailTakenError(AppError):
    def __init__(self, detail: str = "Email is already registered") -> None:
        super().__init__(
            code="EMAIL_TAKEN",
            status=409,
            title="Email Taken",
            detail=detail,
        )


class DraftExistsError(AppError):
    def __init__(self, detail: str = "A draft version already exists for this workflow") -> None:
        super().__init__(
            code="DRAFT_EXISTS",
            status=409,
            title="Draft Exists",
            detail=detail,
        )


class InvalidCredentialsError(AppError):
    def __init__(self, detail: str = "Invalid email or password") -> None:
        super().__init__(
            code="INVALID_CREDENTIALS",
            status=401,
            title="Invalid Credentials",
            detail=detail,
        )


class LastOwnerError(AppError):
    def __init__(
        self,
        detail: str = "Cannot demote or remove the last owner of an organization",
    ) -> None:
        super().__init__(
            code="LAST_OWNER",
            status=409,
            title="Last Owner Constraint",
            detail=detail,
        )


class InvalidStateTransitionError(AppError):
    def __init__(self, detail: str = "Invalid state transition") -> None:
        super().__init__(
            code="INVALID_STATE_TRANSITION",
            status=409,
            title="Invalid State Transition",
            detail=detail,
        )


class ValidationError(AppError):
    def __init__(
        self,
        detail: str = "Validation error",
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            code="VALIDATION_ERROR",
            status=422,
            title="Validation Error",
            detail=detail,
            errors=errors,
        )


class BadRequestError(AppError):
    def __init__(self, detail: str = "Bad request") -> None:
        super().__init__(
            code="BAD_REQUEST",
            status=400,
            title="Bad Request",
            detail=detail,
        )


class PayloadTooLargeError(AppError):
    def __init__(self, detail: str = "Payload too large") -> None:
        super().__init__(
            code="PAYLOAD_TOO_LARGE",
            status=413,
            title="Payload Too Large",
            detail=detail,
        )


class RateLimitedError(AppError):
    def __init__(
        self,
        detail: str = "Rate limit exceeded",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            code="RATE_LIMITED",
            status=429,
            title="Too Many Requests",
            detail=detail,
            headers=headers,
        )


class ServiceUnavailableError(AppError):
    def __init__(
        self,
        detail: str = "Service unavailable",
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            code="SERVICE_UNAVAILABLE",
            status=503,
            title="Service Unavailable",
            detail=detail,
            errors=errors,
        )


class VersionNotPublishedError(AppError):
    def __init__(self, detail: str = "Workflow version is not published") -> None:
        super().__init__(
            code="VERSION_NOT_PUBLISHED",
            status=409,
            title="Version Not Published",
            detail=detail,
        )


class IdempotencyKeyReusedError(AppError):
    def __init__(
        self, detail: str = "Idempotency key has already been used with a different request payload"
    ) -> None:
        super().__init__(
            code="IDEMPOTENCY_KEY_REUSED",
            status=409,
            title="Idempotency Key Reused",
            detail=detail,
        )


class ConcurrencyLimitError(AppError):
    def __init__(
        self, detail: str = "Organization concurrency limit exceeded for active runs"
    ) -> None:
        super().__init__(
            code="CONCURRENCY_LIMIT",
            status=429,
            title="Concurrency Limit Exceeded",
            detail=detail,
        )


class BudgetExceededError(AppError):
    def __init__(self, detail: str = "Organization budget limit exceeded") -> None:
        super().__init__(
            code="BUDGET_EXCEEDED",
            status=402,
            title="Budget Exceeded",
            detail=detail,
        )


class WebhookSignatureInvalidError(AppError):
    def __init__(self, detail: str = "Webhook signature verification failed") -> None:
        super().__init__(
            code="WEBHOOK_SIGNATURE_INVALID",
            status=401,
            title="Webhook Signature Invalid",
            detail=detail,
        )


class WebhookReplayError(AppError):
    def __init__(self, detail: str = "Webhook timestamp expired or replay detected") -> None:
        super().__init__(
            code="WEBHOOK_REPLAY",
            status=401,
            title="Webhook Replay Detected",
            detail=detail,
        )


class EgressBlockedError(AppError):
    def __init__(self, detail: str = "Egress request blocked by security policy") -> None:
        super().__init__(
            code="EGRESS_BLOCKED",
            status=400,
            title="Egress Blocked",
            detail=detail,
        )


def problem_response(
    request: Request,
    *,
    code: str,
    status: int,
    title: str,
    detail: str,
    errors: list[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Construct an RFC 9457 application/problem+json response."""
    req_id = get_request_id() or getattr(getattr(request, "state", None), "request_id", "")
    content: dict[str, Any] = {
        "type": f"https://flowforge.dev/errors/{code}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "code": code,
        "request_id": req_id,
    }
    if errors is not None:
        content["errors"] = errors

    response_headers = {"Content-Type": "application/problem+json"}
    if headers:
        response_headers.update(headers)
    if req_id:
        response_headers["X-Request-ID"] = req_id

    return JSONResponse(
        status_code=status,
        content=content,
        headers=response_headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register global exception handlers for the application."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return problem_response(
            request,
            code=exc.code,
            status=exc.status,
            title=exc.title,
            detail=exc.detail,
            errors=exc.errors,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        raw_errors = exc.errors()
        # Check for malformed JSON syntax
        if any(err.get("type") == "json_invalid" for err in raw_errors):
            return problem_response(
                request,
                code="BAD_REQUEST",
                status=400,
                title="Bad Request",
                detail="Malformed JSON in request body.",
            )

        formatted_errors: list[dict[str, Any]] = []
        for err in raw_errors[:50]:
            loc = err.get("loc", ())
            # Filter out top-level markers like 'body', 'query', 'path'
            filtered_parts = [
                str(part) for part in loc if str(part) not in ("body", "query", "path")
            ]
            field_name = ".".join(filtered_parts) if filtered_parts else "body"
            formatted_errors.append(
                {
                    "field": field_name,
                    "message": err.get("msg", "Invalid value"),
                }
            )

        return problem_response(
            request,
            code="VALIDATION_ERROR",
            status=422,
            title="Validation error",
            detail="Request body failed validation.",
            errors=formatted_errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        status = exc.status_code
        if status == 404:
            code = "NOT_FOUND"
            title = "Not Found"
            detail = "The requested resource was not found."
        elif status == 405:
            code = "METHOD_NOT_ALLOWED"
            title = "Method Not Allowed"
            detail = "HTTP method not allowed for this route."
        elif status == 401:
            code = "UNAUTHENTICATED"
            title = "Unauthorized"
            detail = "Authentication required."
        elif status == 403:
            code = "FORBIDDEN"
            title = "Forbidden"
            detail = "Permission denied."
        elif 400 <= status < 500:
            code = "BAD_REQUEST"
            title = "Bad Request"
            detail = "Bad request."
        else:
            code = "INTERNAL_ERROR"
            title = "Internal Server Error"
            detail = "An unexpected error occurred."

        return problem_response(
            request,
            code=code,
            status=status,
            title=title,
            detail=detail,
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        req_id = get_request_id() or getattr(
            getattr(request, "state", None), "request_id", "unknown"
        )
        logger.error(
            "Unhandled server exception",
            exc_info=exc,
            extra={"request_id": req_id, "path": request.url.path},
        )
        return problem_response(
            request,
            code="INTERNAL_ERROR",
            status=500,
            title="Internal Server Error",
            detail="An unexpected error occurred.",
        )
