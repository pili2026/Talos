"""
Request Logging Middleware

Logs all API requests and responses.
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import time
import logging

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Request logging middleware.

    Logs:
    - Request method and path
    - Processing time
    - Response status code
    """

    async def dispatch(self, request: Request, call_next):
        """
        Process the request and log details.

        Args:
            request: Incoming HTTP request.
            call_next: The next handler in the middleware chain.

        Returns:
            Response: HTTP response.
        """
        start_time = time.time()

        # Log the incoming request
        logger.info(f"→ {request.method} {request.url.path}")

        # Process the request
        response: Response = await call_next(request)

        # Calculate processing time
        process_time = time.time() - start_time

        # Log the outgoing response
        logger.info(f"← {request.method} {request.url.path} [{response.status_code}] {process_time:.3f}s")

        # Add processing time to response headers
        response.headers["X-Process-Time"] = str(process_time)

        return response
