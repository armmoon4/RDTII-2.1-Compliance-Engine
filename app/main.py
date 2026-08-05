"""FastAPI application entry point — RDTII 2.1 Compliance Engine."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analysis import router as analysis_router
from app.api.health import router as health_router
from app.config import settings
from app.database import create_all_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables on startup."""
    await create_all_tables()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "AI-powered Regulatory Analysis Engine that automatically discovers, "
        "extracts, and maps digital trade regulations to the RDTII 2.1 framework "
        "covering all 12 pillars. Team SUPERNOVA — UNESCAP Global Hackathon 2026."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(health_router)
app.include_router(analysis_router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["root"])
async def root():
    from starlette.responses import Response
    import os
    content = open("frontend.html", "rb").read()
    return Response(
        content=content,
        media_type="text/html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

@app.get("/api", tags=["root"])
async def api_root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "team": "SUPERNOVA",
        "hackathon": "UNESCAP Global Hackathon 2026",
        "docs": "/docs",
    }
