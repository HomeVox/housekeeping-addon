"""Housekeeping API - Main application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .dependencies import init_components
from .routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Housekeeping v2.0.19")
    try:
        init_components()
        logger.info("Components initialized")
    except Exception as e:
        logger.error("Init failed: %s", e)
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="Housekeeping",
    description="Automated Home Assistant housekeeping",
    version="2.0.19",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

# Add CORS middleware - restricted to same origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Required for ingress - HA handles auth
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router, prefix="/api")

# Static files for UI
app.mount("/", StaticFiles(directory="www", html=True), name="www")


@app.get("/health", include_in_schema=False)
async def root_health():
    """Root health check for ingress."""
    from .dependencies import get_engine

    try:
        engine = get_engine()
        return {"ok": True, "detail": "API running", "ha_connected": bool(engine.ha.token)}
    except Exception:
        return {"ok": True, "detail": "API running", "ha_connected": False}
