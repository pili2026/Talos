"""
Health Check Configuration Schema

Defines the Pydantic schemas for device health check strategies.
"""

from enum import StrEnum


class HealthCheckStrategyEnum(StrEnum):
    """Health check strategy types"""

    SINGLE_REGISTER = "single_register"  # Read one indicator register
    PARTIAL_BULK = "partial_bulk"  # Read 2-5 contiguous registers
    FULL_READ = "full_read"  # Read all registers (fallback)
