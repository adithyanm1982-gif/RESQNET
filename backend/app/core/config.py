from pathlib import Path

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: SecretStr | None = None
    resqnet_demo_mode: bool = False
    cors_origins: str = (
        "https://resqnet-eight-psi.vercel.app,"
        "http://localhost:5173,http://127.0.0.1:5173"
    )
    google_client_id: str | None = None
    auth_cookie_secure: bool = True
    auth_cookie_samesite: str = "lax"

    @field_validator("auth_cookie_samesite")
    @classmethod
    def validate_auth_cookie_samesite(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"lax", "strict", "none"}:
            raise ValueError("AUTH_COOKIE_SAMESITE must be lax, strict, or none.")
        return normalized

    @model_validator(mode="after")
    def validate_secure_cross_site_cookie(self):
        if self.auth_cookie_samesite == "none" and not self.auth_cookie_secure:
            raise ValueError("AUTH_COOKIE_SECURE must be true when AUTH_COOKIE_SAMESITE is none.")
        return self

    @property
    def effective_database_url(self) -> str | None:
        """Use configured PostgreSQL normally, with an explicit SQLite demo fallback."""
        if self.database_url is not None:
            return self.database_url.get_secret_value()
        if self.resqnet_demo_mode:
            return "sqlite+pysqlite:///./resqnet-demo.sqlite3"
        return None

    @property
    def allowed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
