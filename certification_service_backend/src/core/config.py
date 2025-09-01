import os
from functools import lru_cache
from typing import List, Optional, Dict

from dotenv import load_dotenv
from pydantic import AnyUrl, BaseModel, Field, field_validator


# Load environment variables from a .env file if present.
# This keeps configuration out of code and allows easy environment-specific overrides.
load_dotenv()


class Settings(BaseModel):
    """Application settings loaded from environment variables."""

    app_name: str = Field(default="Certification Service Backend", description="Human-friendly application name")
    environment: str = Field(default="development", description="Deployment environment (development/staging/production)")
    debug: bool = Field(default=False, description="Enable debug mode")
    host: str = Field(default="0.0.0.0", description="Host interface for the server")
    port: int = Field(default=8000, description="Port for the server")

    # CORS configuration
    cors_allow_origins: List[str] = Field(
        default_factory=lambda: ["*"],
        description="List of allowed origins for CORS",
    )
    cors_allow_credentials: bool = Field(default=True, description="Whether to allow credentials for CORS")
    cors_allow_methods: List[str] = Field(default_factory=lambda: ["*"], description="Allowed HTTP methods for CORS")
    cors_allow_headers: List[str] = Field(default_factory=lambda: ["*"], description="Allowed HTTP headers for CORS")

    # Database configuration - async driver recommended (e.g., asyncpg for PostgreSQL)
    database_url: str = Field(
        default="postgresql+asyncpg://user:password@localhost:5432/certification_db",
        description="SQLAlchemy-style async database URL",
    )

    # External integrations (placeholders to be expanded later)
    gitlab_base_url: Optional[AnyUrl] = Field(default=None, description="Base URL for GitLab API")
    gitlab_token: Optional[str] = Field(default=None, description="Personal access token for GitLab")

    # Airflow configuration
    airflow_base_url: Optional[AnyUrl] = Field(default=None, description="Base URL to reach Airflow API")
    airflow_username: Optional[str] = Field(default=None, description="Basic auth username (if required)")
    airflow_password: Optional[str] = Field(default=None, description="Basic auth password (if required)")
    airflow_timeout: float = Field(default=15.0, description="HTTP timeout for Airflow calls in seconds")
    # Map certification type (enum value string) to DAG IDs
    airflow_dag_map: Dict[str, str] = Field(
        default_factory=lambda: {
            "unit": "cert_unit_tests",
            "extended_unit": "cert_extended_unit_tests",
            "e2e": "cert_e2e_tests",
            "soak": "cert_soak_tests",
            "performance": "cert_performance_tests",
            "code_quality": "cert_code_quality",
            "network_security": "cert_network_security",
            "manual_compliance": "cert_manual_compliance",
        },
        description="Mapping from certification type to Airflow DAG id",
    )

    # Site URL for auth/email callbacks (if later needed)
    site_url: Optional[AnyUrl] = Field(default=None, description="Public site URL for redirects and callbacks")

    # Orchestration polling and retry
    orchestration_poll_interval: float = Field(default=10.0, description="Seconds between polling Airflow run status")
    orchestration_max_poll_seconds: float = Field(default=7200.0, description="Max seconds to poll before timeout")
    orchestration_retry_attempts: int = Field(default=3, description="Retry attempts for transient HTTP failures")
    orchestration_retry_backoff: float = Field(default=1.5, description="Exponential backoff base for retries")

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        # Allow comma-separated string input for convenience
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @staticmethod
    def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
        """Helper to read from environment with default."""
        return os.getenv(name, default)

    @classmethod
    def from_env(cls) -> "Settings":
        """Build Settings from environment variables with sensible defaults."""
        # Parse DAG map if provided as JSON, else fallback to defaults
        import json
        airflow_dag_map_default = None
        dag_map_env = cls._get_env("AIRFLOW_DAG_MAP")
        if dag_map_env:
            try:
                airflow_dag_map_default = json.loads(dag_map_env)
            except Exception:
                airflow_dag_map_default = None

        return cls(
            app_name=cls._get_env("APP_NAME", "Certification Service Backend"),
            environment=cls._get_env("ENVIRONMENT", "development"),
            debug=cls._get_env("DEBUG", "false").lower() in ("1", "true", "yes"),
            host=cls._get_env("HOST", "0.0.0.0"),
            port=int(cls._get_env("PORT", "8000")),
            cors_allow_origins=cls._get_env("CORS_ALLOW_ORIGINS", "*"),
            cors_allow_credentials=cls._get_env("CORS_ALLOW_CREDENTIALS", "true").lower() in ("1", "true", "yes"),
            cors_allow_methods=(cls._get_env("CORS_ALLOW_METHODS", "*")),
            cors_allow_headers=(cls._get_env("CORS_ALLOW_HEADERS", "*")),
            database_url=cls._get_env(
                "DATABASE_URL",
                "postgresql+asyncpg://user:password@localhost:5432/certification_db",
            ),
            gitlab_base_url=cls._get_env("GITLAB_BASE_URL"),
            gitlab_token=cls._get_env("GITLAB_TOKEN"),
            airflow_base_url=cls._get_env("AIRFLOW_BASE_URL"),
            airflow_username=cls._get_env("AIRFLOW_USERNAME"),
            airflow_password=cls._get_env("AIRFLOW_PASSWORD"),
            airflow_timeout=float(cls._get_env("AIRFLOW_TIMEOUT", "15.0")),
            airflow_dag_map=airflow_dag_map_default or None,  # None triggers default factory
            site_url=cls._get_env("SITE_URL"),
            orchestration_poll_interval=float(cls._get_env("ORCH_POLL_INTERVAL", "10.0")),
            orchestration_max_poll_seconds=float(cls._get_env("ORCH_MAX_POLL_SECONDS", "7200.0")),
            orchestration_retry_attempts=int(cls._get_env("ORCH_RETRY_ATTEMPTS", "3")),
            orchestration_retry_backoff=float(cls._get_env("ORCH_RETRY_BACKOFF", "1.5")),
        )


@lru_cache(maxsize=1)
# PUBLIC_INTERFACE
def get_settings() -> Settings:
    """Return cached application settings loaded from environment variables."""
    return Settings.from_env()
