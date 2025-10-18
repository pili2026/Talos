"""
Global Error Handling Middleware

Provides unified handling for all API error responses.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import logging

logger = logging.getLogger(__name__)


def add_error_handlers(app: FastAPI):
    """
    Register error handlers for the FastAPI application.

    Args:
        app: FastAPI application instance.
    """

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Handle request validation errors."""
        errors = []
        for error in exc.errors():
            errors.append(
                {"field": ".".join(str(loc) for loc in error["loc"]), "message": error["msg"], "type": error["type"]}
            )

        logger.warning(f"Validation error on {request.url.path}: {errors}")

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"status": "error", "message": "Request validation failed", "errors": errors},
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        """Handle value-related errors."""
        logger.error(f"ValueError on {request.url.path}: {str(exc)}")

        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"status": "error", "message": str(exc)})

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """Handle unexpected errors."""
        logger.error(f"Unhandled exception on {request.url.path}: {str(exc)}", exc_info=True)

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "error",
                "message": "An unexpected error occurred",
                "detail": str(exc) if logger.level == logging.DEBUG else None,
            },
        )
