"""
FastAPI Application Entry Point
Responsibilities:
- Create FastAPI instance
- Register routes
- Configure middleware
- Set up CORS
"""

import logging
from pathlib import Path
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles

env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.lifecycle import shutdown_event, startup_event
from api.middleware.error_handler import add_error_handlers
from api.middleware.logging_middleware import LoggingMiddleware
from api.router import batch, devices, health, monitoring, parameters
from api.util.logging_config import setup_logging

logger = logging.getLogger("TalosAPI")

# Obtain the absolute path to the static directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent


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

    # Register static files
    static_dir = BASE_DIR / "static"

    # Ensure static directory exists
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    else:
        logger.warning(f"Warning: Static directory not found at {static_dir}")

    return app


app = create_application()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
