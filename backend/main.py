"""FastAPI application entrypoint for LegalEase."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import (
    analysis_router,
    auth_router,
    comparison_router,
    reports_router,
    upload_router,
)
from backend.config import LEGAL_DISCLAIMER, get_settings
from backend.database import init_db
from backend.schemas.report import HealthResponse


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_directories()
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="AI-Powered Legal Document Intelligence & Risk Assessment Platform",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["System"])
    def health_check() -> HealthResponse:
        current = get_settings()
        return HealthResponse(
            status="ok",
            app=current.app_name,
            version=current.app_version,
            gemini_configured=current.has_gemini_key,
            disclaimer=LEGAL_DISCLAIMER,
        )

    app.include_router(auth_router)
    app.include_router(upload_router)
    app.include_router(analysis_router)
    app.include_router(comparison_router)
    app.include_router(reports_router)
    return app


app = create_app()
