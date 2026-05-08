from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["dev", "test", "prod"] = "dev"

    database_url: str = "sqlite+aiosqlite:///./data/app.db"

    google_credentials_path: Path = Path("./secrets/credentials.json")
    google_oauth_scopes: list[str] = Field(
        default_factory=lambda: ["https://www.googleapis.com/auth/calendar"],
    )

    token_encryption_key: str = ""

    app_timezone: str = "Asia/Tokyo"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
