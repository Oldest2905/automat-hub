"""
main.py - The Automat Hub API Entry Point
Complete production-ready FastAPI application.
"""
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, PlainTextResponse
from contextlib import asynccontextmanager
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from redis import asyncio as aioredis
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend

from backend.core.database import init_db
from backend.routers import (
    dcp, escrow, auth, webhooks,
    fleet, reseller, admin, workshop, tracking
)
from backend.routers.subscription import router as subscription_router
from backend.routers.manufacturer import router as manufacturer_router
from backend.config import settings


def validate_environment():
    # List the exact attributes defined in your Settings class
    # We use getattr to safely check if they have a non-empty value
    missing = []
    
    if not settings.DATABASE_URL:
        missing.append("DATABASE_URL")
    if not settings.SECRET_KEY:
        missing.append("SECRET_KEY")
    if not settings.API_KEY:
        missing.append("API_KEY")

    if missing:
        # This will now only raise if the values are actually empty strings
        raise ValueError(
            f"Missing required env vars: {', '.join(missing)}\n"
            "Check your .env file and ensure values are filled."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_environment()
    await init_db()
    
    # Initialize Redis for caching
    redis_url = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
    redis = aioredis.from_url(redis_url)
    FastAPICache.init(RedisBackend(redis), prefix="tah-cache")
    
    print("=" * 50)
    print("  THE AUTOMAT HUB — TRUST PROTOCOL")
    print(f"  Environment: {settings.ENVIRONMENT}")
    print(f"  API Docs: http://localhost:8000/docs")
    print("=" * 50)
    yield
    print("Shutting down...")


# Rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="The Automat Hub — Trust Protocol API",
    description="Africa's Vehicle Trust Protocol — DCP, Escrow, Fleet Intelligence",
    version="1.0.0",
    contact={"name": "The Automat Hub Ltd", "url": "https://automatcorp.org.ng", "email": "support@automatcorp.org.ng"},
    lifespan=lifespan
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(",") if hasattr(settings, 'CORS_ORIGINS') else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    print(f"{request.method} {request.url.path} → {response.status_code}")
    return response

# All routers
app.include_router(auth.router)
app.include_router(dcp.router)
app.include_router(escrow.router)
app.include_router(webhooks.router)
app.include_router(fleet.router)
app.include_router(reseller.router)
app.include_router(admin.router)
app.include_router(workshop.router)
app.include_router(tracking.router)
app.include_router(manufacturer_router)
app.include_router(subscription_router)

from fastapi.staticfiles import StaticFiles

# This serves your frontend folder at the /frontend path
# Ensure the 'frontend' directory is in the same root folder as main.py
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

@app.get("/app", include_in_schema=False)
async def app_redirect():
    return FileResponse("frontend/index.html")

@app.get("/", include_in_schema=False)
async def serve_frontend():
    """Serves the main application directly at the root URL."""
    return FileResponse("frontend/index.html")

@app.get("/cov", include_in_schema=False)
async def serve_cov():
    """Serves the Connect Vehicle page at the clean /cov URL"""
    return FileResponse("frontend/connect-vehicle.html")

@app.get("/api/health", tags=["Health"])
async def health_check():
    return {
        "name": "The Automat Hub — Trust Protocol",
        "status": "healthy"
    }

@app.get("/ping", tags=["Health"], response_class=PlainTextResponse)
async def ping():
    """
    Ultra-lightweight health check endpoint.
    Perfect for cron-job.org and other uptime monitors.
    """
    return "OK"
