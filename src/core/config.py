"""Application settings loaded from environment variables / `.env` (Pydantic Settings v2)."""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- PostgreSQL ---
    postgres_user: str = "cartpilot"
    postgres_password: SecretStr = SecretStr("cartpilot")
    postgres_db: str = "cartpilot"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    database_url_override: str | None = Field(default=None, alias="CARTPILOT_DATABASE_URL")
    db_echo: bool = False

    # --- Telegram ---
    telegram_bot_token: SecretStr | None = None
    # NoDecode: read the raw string ("1,2,3") instead of expecting JSON ("[1,2,3]").
    admin_telegram_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    # --- LLM ---
    gemini_api_key: SecretStr | None = None
    model_fast: str = "google-gla:gemini-3.8-flash"
    model_reasoning: str = "google-gla:gemini-4-hydrogen"
    model_embedding: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
    embeddings_enabled: bool = True

    # --- Misc ---
    log_level: str = "INFO"

    @field_validator("admin_telegram_ids", mode="before")
    @classmethod
    def _split_admin_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part) for part in value.split(",") if part.strip()]
        if isinstance(value, int):
            return [value]
        return value

    # Plain @property (not @computed_field): computed fields are included in repr()
    # and model_dump(), which would leak the plaintext password into logs.
    @property
    def database_url(self) -> str:
        """Async SQLAlchemy URL (driver: asyncpg)."""
        if self.database_url_override:
            return self.database_url_override
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — the `.env` file is parsed only once per process."""
    return Settings()
