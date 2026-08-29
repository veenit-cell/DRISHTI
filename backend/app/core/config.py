from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EV2_", extra="forbid")

    app_name: str = "EV2 District Disaster Decision Support"
    app_version: str = "0.1.0"
    app_environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql://postgres@127.0.0.1:5432/ev2"
    dev_identity_enabled: bool = True
    allowed_origins: tuple[AnyHttpUrl, ...] = (AnyHttpUrl("http://127.0.0.1:5173"),)
    max_correlation_id_length: int = Field(default=128, ge=32, le=256)

    @model_validator(mode="after")
    def forbid_development_identity_in_production(self) -> "Settings":
        if self.app_environment == "production" and self.dev_identity_enabled:
            raise ValueError("Development identity must be disabled in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
