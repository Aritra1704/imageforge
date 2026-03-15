from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas import ErrorDetails, ErrorEnvelope


logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ServiceBusyError(AppError):
    status_code = 503
    code = "service_busy"


class DependencyUnavailableError(AppError):
    status_code = 503
    code = "dependency_unavailable"


class ProviderNotImplementedError(AppError):
    status_code = 501
    code = "provider_not_implemented"


def _request_id_from(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def build_error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any | None = None,
) -> JSONResponse:
    request_id = _request_id_from(request)
    payload = ErrorEnvelope(
        error=ErrorDetails(code=code, message=message, details=details),
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers={"X-Request-Id": request_id},
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return build_error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return build_error_response(
        request,
        status_code=422,
        code="validation_error",
        message="Request validation failed.",
        details=exc.errors(),
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception", exc_info=exc)
    return build_error_response(
        request,
        status_code=500,
        code="internal_error",
        message="An unexpected error occurred.",
    )
