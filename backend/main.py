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
from backend.database import Document, init_db
from backend.database import db as db_module
from backend.schemas.report import HealthResponse


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate_production_security()
    settings.ensure_directories()
    init_db()

    # Stale background job recovery on server startup
    try:
        with db_module.SessionLocal() as db:
            stale_jobs = db.query(Document).filter(
                Document.processing_status.in_(["queued", "processing"])
            ).all()
            if stale_jobs:
                logger.warning(
                    "Detected %d uncompleted contract analysis jobs from prior server session. Resetting to failed.",
                    len(stale_jobs),
                )
                for doc in stale_jobs:
                    doc.processing_status = "failed"
                    doc.current_stage = "interrupted"
                    doc.last_error = "Analysis was interrupted by server restart. Ready to retry."
                db.commit()
    except Exception as exc:
        logger.error("Failed to recover stale background analysis jobs on startup: %s", exc)

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
