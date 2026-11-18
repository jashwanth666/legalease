"""Central configuration for LegalEase backend and shared paths."""

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent

LEGAL_DISCLAIMER = (
    "LegalEase is an AI-assisted document review tool. Its findings are informational "
    "and may be incomplete or inaccurate. It does not provide legal advice or replace "
    "review by a qualified legal professional."
)


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "LegalEase"
    app_version: str = "0.1.0"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    embedding_model: str = "all-MiniLM-L6-v2"

    max_upload_size_mb: int = 15
    allowed_extensions: tuple[str, ...] = (".pdf", ".docx")

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_base_url: str = "http://127.0.0.1:8000"

    database_url: str = f"sqlite:///{(BASE_DIR / 'storage' / 'legalease.db').as_posix()}"

    environment: str = "development"
    cookie_secure: bool = False
    jwt_secret_key: str = "legalease-production-jwt-secret-key-change-in-env-32bytes"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440
    admin_bootstrap_secret: str = ""
    redis_url: str = ""
    require_redis_in_production: bool = True
    allow_inmemory_rate_limiter_in_production: bool = False
    allowed_origins: str = "http://localhost:8501,http://127.0.0.1:8501"

    def validate_production_security(self) -> None:
        """Validate production security posture, failing startup if insecure."""
        if self.environment.lower() == "production":
            insecure_defaults = {
                "insecure-default-secret-key-change-in-production",
                "legalease-production-jwt-secret-key-change-in-env-32bytes",
                "secret",
                "changeme",
            }
            if not self.jwt_secret_key or self.jwt_secret_key in insecure_defaults or len(self.jwt_secret_key) < 32:
                raise ValueError(
                    "CRITICAL SECURITY CONFIGURATION ERROR: Running in production environment with an unconfigured "
                    "or default JWT_SECRET_KEY. Please configure a cryptographically strong secret of at least 32 bytes."
                )
            if not self.admin_bootstrap_secret or len(self.admin_bootstrap_secret) < 16:
                raise ValueError(
                    "CRITICAL SECURITY CONFIGURATION ERROR: Running in production without a configured "
                    "ADMIN_BOOTSTRAP_SECRET of at least 16 characters. Set ADMIN_BOOTSTRAP_SECRET in your environment."
                )
            if self.admin_bootstrap_secret.lower() in {"admin", "secret", "changeme", "bootstrap", "12345678"}:
                raise ValueError(
                    "CRITICAL SECURITY CONFIGURATION ERROR: Running in production with an insecure or trivial ADMIN_BOOTSTRAP_SECRET."
                )
            # CORS validation: wildcard origins forbidden in production
            origins = self.get_allowed_origins()
            if "*" in origins:
                raise ValueError(
                    "CRITICAL SECURITY CONFIGURATION ERROR: Wildcard origin '*' is forbidden in production when credentials are enabled."
                )
            # Distributed rate limiting in production: Redis is required by default
            if not self.allow_inmemory_rate_limiter_in_production and (self.require_redis_in_production or not self.redis_url):
                if not self.redis_url or not self.redis_url.strip():
                    raise ValueError(
                        "CRITICAL SECURITY CONFIGURATION ERROR: Running in production requires REDIS_URL for distributed "
                        "rate limiting across instances. Configure REDIS_URL or explicitly set "
                        "ALLOW_INMEMORY_RATE_LIMITER_IN_PRODUCTION=true for documented single-instance deployments."
                    )
            if self.redis_url:
                try:
                    import redis as redis_lib

                    client = redis_lib.from_url(
                        self.redis_url,
                        socket_connect_timeout=2,
                        socket_timeout=2,
                    )
                    client.ping()
                except Exception as exc:
                    raise RuntimeError(
                        f"CRITICAL SECURITY CONFIGURATION ERROR: Running in production with REDIS_URL configured, "
                        f"but Redis connection test failed: {exc}. Multi-instance production requires a reachable Redis service."
                    ) from exc

    def get_allowed_origins(self) -> list[str]:
        """Return the list of CORS-allowed origins from the comma-separated config value."""
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def upload_dir(self) -> Path:
        return BASE_DIR / "storage" / "uploads"

    @property
    def extracted_dir(self) -> Path:
        return BASE_DIR / "storage" / "extracted"

    @property
    def vectorstore_dir(self) -> Path:
        return BASE_DIR / "storage" / "vectorstore"

    @property
    def reports_dir(self) -> Path:
        return BASE_DIR / "outputs" / "reports"

    @property
    def reference_templates_dir(self) -> Path:
        return BASE_DIR / "data" / "reference_templates"

    @property
    def sample_contracts_dir(self) -> Path:
        return BASE_DIR / "data" / "sample_contracts"

    @property
    def has_gemini_key(self) -> bool:
        key = (self.gemini_api_key or "").strip()
        return bool(key and key != "your_gemini_api_key_here")

    def ensure_directories(self) -> None:
        """Create required runtime directories if missing."""
        for directory in (
            self.upload_dir,
            self.extracted_dir,
            self.vectorstore_dir,
            self.reports_dir,
            self.reference_templates_dir,
            self.sample_contracts_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings

