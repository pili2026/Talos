"""
Health Check Router

Provides system health monitoring endpoints.
"""

from fastapi import APIRouter
from datetime import datetime
import platform

router = APIRouter()


@router.get("/health", summary="Health Check", description="Check if the API service is running normally")
async def health_check():
    """
    System health check.

    Returns:
        dict: System status information.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "Talos Device Management API",
        "version": "1.0.0",
        "python_version": platform.python_version(),
        "platform": platform.system(),
    }


@router.get("/ping", summary="Ping", description="Simple connectivity test")
async def ping():
    """Simple ping endpoint."""
    return {"message": "pong"}
