import os
from functools import lru_cache
from typing import List, Optional

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

    # Site URL for auth/email callbacks (if later needed)
    site_url: Optional[AnyUrl] = Field(default=None, description="Public site URL for redirects and callbacks")

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
            site_url=cls._get_env("SITE_URL"),
        )


@lru_cache(maxsize=1)
# PUBLIC_INTERFACE
def get_settings() -> Settings:
    """Return cached application settings loaded from environment variables."""
    return Settings.from_env()
