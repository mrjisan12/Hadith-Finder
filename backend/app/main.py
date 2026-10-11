"""FastAPI application entry point.

Run locally:  uvicorn app.main:app --reload --port 8000   (from the backend/ folder)
Docs:         http://localhost:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.api.v1 import books, chat, debug, pages, sources
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.core.security import SecurityHeadersMiddleware, limiter

setup_logging(settings.log_level)
log = get_logger("app")

VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info("starting", extra={"fields": {"version": VERSION, "config": settings.safe_dict()}})
    yield


app = FastAPI(
    title="Hadith Finder API",
    version=VERSION,
    description=(
        "Source-grounded question answering over scanned Islamic books. Every answer comes with the "
        "exact original paragraph (from the database, never from the LLM), its printed page number, "
        "its PDF page number and a link to the original scanned page."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    max_age=600,
)


@app.exception_handler(RateLimitExceeded)
async def _rate_limited(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Too many requests. Please wait a moment and try again."})


@app.exception_handler(RequestValidationError)
async def _invalid(request: Request, exc: RequestValidationError):
    errors = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.exception("unhandled error", extra={"fields": {"path": request.url.path}})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


API_PREFIX = "/api/v1"
app.include_router(chat.router, prefix=API_PREFIX)
app.include_router(books.router, prefix=API_PREFIX)
app.include_router(sources.router, prefix=API_PREFIX)
app.include_router(pages.router, prefix=API_PREFIX)
if settings.enable_debug:
    app.include_router(debug.router, prefix=API_PREFIX)


@app.get("/health", tags=["health"])
@limiter.exempt
def health() -> dict:
    db_status = "ok"
    try:
        from app.core.database import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = f"error: {type(exc).__name__}"
    return {"status": "ok" if db_status == "ok" else "degraded", "database": db_status, "version": VERSION}
