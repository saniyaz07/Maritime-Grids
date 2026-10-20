"""
app/api — Phase 10C.9 Application API Transport Boundary
=========================================================
Exposes the FastAPI application factory, dependency providers, and route definitions.
"""

from app.api.app import create_app
from app.api.dependencies import (
    get_engineering_service,
    get_operator_service,
    get_weather_provider,
)
from app.api.errors import APIErrorResponse

__all__ = [
    "create_app",
    "get_engineering_service",
    "get_operator_service",
    "get_weather_provider",
    "APIErrorResponse",
]
