"""Database engine, session management, and initialization helpers."""

from collections.abc import Generator
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from backend.config import get_settings
from backend.database.models import Base


_MIGRATION_COLUMNS: dict[str, dict[str, str]] = {
    "documents": {
        "gemini_status": "VARCHAR(32)",
        "fallback_used": "BOOLEAN NOT NULL DEFAULT 0",
        "fallback_reason": "TEXT",
        "last_error": "TEXT",
        "embedding_backend": "VARCHAR(64)",
    },
    "clauses": {
        "end_page_number": "INTEGER",
        "location_type": "VARCHAR(32) NOT NULL DEFAULT 'pdf_page'",
        "paragraph_index": "INTEGER",
        "section_title": "VARCHAR(255)",
        "segmentation_confidence": "VARCHAR(16) NOT NULL DEFAULT 'high'",
        "segmentation_uncertain": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "risk_assessments": {
        "location_type": "VARCHAR(32) NOT NULL DEFAULT 'pdf_page'",
        "paragraph_index": "INTEGER",
        "section_title": "VARCHAR(255)",
    },
    "comparisons": {
        "insufficient_evidence": "BOOLEAN NOT NULL DEFAULT 0",
    },
}


def _ensure_sqlite_columns(eng) -> None:
    """Apply additive idempotent column migrations for existing SQLite databases."""
    if not str(eng.url).startswith("sqlite"):
        return
    with eng.begin() as conn:
        for table_name, columns in _MIGRATION_COLUMNS.items():
            rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            if not rows:
                continue
            existing = {row[1] for row in rows}
            for col_name, col_def in columns.items():
                if col_name not in existing:
                    conn.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}")
                    )


def _build_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    eng = create_engine(database_url, connect_args=connect_args, future=True)
    if database_url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return eng


_settings = get_settings()
engine = _build_engine(_settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


def configure_database(database_url: str) -> None:
    """Reconfigure engine and SessionLocal (useful for isolated tests)."""
    global engine, SessionLocal
    engine.dispose()
    engine = _build_engine(database_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns(engine)


def init_db() -> None:
    """Create database tables if they do not exist."""
    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns(engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

