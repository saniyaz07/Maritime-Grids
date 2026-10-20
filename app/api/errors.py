"""
app/api/errors.py — Phase 10C.9 / 10C.10 Structured API Error Models & Handlers
================================================================================
Defines typed API error responses and exception mapping for the FastAPI boundary.

Key Invariants:
  - Pure transport-level error normalization.
  - Zero raw tracebacks leaked to API clients.
  - Consistent structured JSON error schema across all status codes.
  - Deterministic status code mapping (400, 404, 409, 422, 500, 503).
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.facade.scenario_facade import (
    FacadeError,
    FacadeExecutionError,
    FacadeValidationError,
)
from app.state.contracts import (
    StateConflictError,
    StateNotFoundError,
    StateRepositoryError,
    StateValidationError,
)


class APIErrorResponse(BaseModel):
    """Standard structured error response returned by all API endpoints."""
    status_code: int = Field(..., description="HTTP status code")
    error_type: str = Field(..., min_length=1, description="Classification type of the error")
    message: str = Field(..., min_length=1, description="Human-readable description of the error")
    details: Optional[List[str]] = Field(default=None, description="Specific field or diagnostic error messages")
    timestamp_utc: str = Field(..., description="ISO 8601 UTC timestamp of error occurrence")


def create_error_response(
    status_code: int,
    error_type: str,
    message: str,
    details: Optional[List[str]] = None,
) -> JSONResponse:
    """Helper to construct a standardized JSONResponse with APIErrorResponse schema."""
    payload = APIErrorResponse(
        status_code=status_code,
        error_type=error_type,
        message=message,
        details=details,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )


async def facade_validation_exception_handler(request: Request, exc: FacadeValidationError) -> JSONResponse:
    """Maps FacadeValidationError to HTTP 400 Bad Request."""
    return create_error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        error_type="FACADE_VALIDATION_ERROR",
        message=str(exc),
        details=[str(exc)],
    )


async def facade_execution_exception_handler(request: Request, exc: FacadeExecutionError) -> JSONResponse:
    """Maps FacadeExecutionError to HTTP 500 Internal Server Error."""
    return create_error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_type="FACADE_EXECUTION_ERROR",
        message="Facade simulation execution encountered an unrecoverable failure.",
        details=[str(exc)],
    )


async def facade_generic_exception_handler(request: Request, exc: FacadeError) -> JSONResponse:
    """Maps base FacadeError to HTTP 400 Bad Request."""
    return create_error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        error_type="FACADE_ERROR",
        message=str(exc),
        details=[str(exc)],
    )


async def state_not_found_exception_handler(request: Request, exc: StateNotFoundError) -> JSONResponse:
    """Maps StateNotFoundError to HTTP 404 Not Found."""
    return create_error_response(
        status_code=status.HTTP_404_NOT_FOUND,
        error_type="NOT_FOUND",
        message=str(exc),
        details=[str(exc)],
    )


async def state_conflict_exception_handler(request: Request, exc: StateConflictError) -> JSONResponse:
    """Maps StateConflictError to HTTP 409 Conflict."""
    return create_error_response(
        status_code=status.HTTP_409_CONFLICT,
        error_type="CONFLICT",
        message=str(exc),
        details=[str(exc)],
    )


async def state_validation_exception_handler(request: Request, exc: StateValidationError) -> JSONResponse:
    """Maps StateValidationError to HTTP 400 Bad Request."""
    return create_error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        error_type="VALIDATION_ERROR",
        message=str(exc),
        details=[str(exc)],
    )


async def request_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Maps FastAPI/Pydantic validation errors to HTTP 422 Unprocessable Entity."""
    error_details: List[str] = []
    for err in exc.errors():
        loc = " -> ".join(str(item) for item in err.get("loc", []))
        msg = err.get("msg", "Invalid input")
        error_details.append(f"{loc}: {msg}" if loc else msg)

    return create_error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        error_type="VALIDATION_ERROR",
        message="Request payload failed contract schema validation.",
        details=error_details,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Maps Starlette/FastAPI HTTPExceptions to structured error responses."""
    error_type_map = {
        400: "BAD_REQUEST",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        500: "INTERNAL_SERVER_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }
    error_type = error_type_map.get(exc.status_code, "HTTP_ERROR")
    message = str(exc.detail) if exc.detail else "An HTTP error occurred."

    return create_error_response(
        status_code=exc.status_code,
        error_type=error_type,
        message=message,
        details=[message],
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fallback handler for unhandled Python exceptions; prevents raw traceback leakage."""
    return create_error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_type="INTERNAL_SERVER_ERROR",
        message="An unexpected internal server error occurred. Please consult system logs.",
        details=[exc.__class__.__name__],
    )
