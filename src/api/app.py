"""
FastAPI Application Entry Point

Responsibilities:
- Create FastAPI instance
- Register routes
- Configure middleware
- Set up CORS
"""

from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)


from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api.router import devices, parameters, batch, monitoring, health
from api.lifecycle import startup_event, shutdown_event
from api.middleware.error_handler import add_error_handlers
from api.middleware.logging_middleware import LoggingMiddleware
from api.util.logging_config import setup_logging


# Configure logging
setup_logging(log_level="INFO")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    # Startup
    await startup_event()
    yield
    # Shutdown
    await shutdown_event()


def create_application() -> FastAPI:
    """
    Create and configure a FastAPI application

    Returns:
        FastAPI: Configured FastAPI application instance
    """
    app = FastAPI(
        title="Talos Device Management API",
        description="Point-to-point Modbus device management and monitoring API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Restrict origins in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register middleware
    app.add_middleware(LoggingMiddleware)

    # Register error handlers
    add_error_handlers(app)

    # Register routes
    app.include_router(health.router, prefix="/api", tags=["Health"])
    app.include_router(devices.router, prefix="/api/devices", tags=["Devices"])
    app.include_router(parameters.router, prefix="/api/parameters", tags=["Parameters"])
    app.include_router(batch.router, prefix="/api/batch", tags=["Batch Operations"])
    app.include_router(monitoring.router, prefix="/api/monitoring", tags=["Monitoring"])

    return app


app = create_application()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
