from functools import lru_cache
from typing import Literal
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
    request_body_max_bytes: int = Field(default=1_000_000, ge=1_024, le=10_000_000)
    rate_limit_per_window: int = Field(default=60, ge=1, le=10_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3_600)

    # LoRaWAN Configuration
    lorawan_enabled: bool = False
    lorawan_mqtt_broker: str = "tcp://127.0.0.1:1883"
    lorawan_mqtt_topic_prefix: str = "application"
    lorawan_chirpstack_api_url: str = ""
    lorawan_chirpstack_api_key: str = ""
    lorawan_webhook_secret: str = ""
    lorawan_device_registry: str = ""

    @model_validator(mode="after")
    def forbid_development_identity_in_production(self) -> "Settings":
        if self.app_environment == "production" and self.dev_identity_enabled:
            raise ValueError("Development identity must be disabled in production")
        if self.app_environment == "production":
            for origin in self.allowed_origins:
                if origin.scheme != "https" or origin.host in {"localhost", "127.0.0.1", "::1"}:
                    raise ValueError("Production allowed_origins must use HTTPS and a non-loopback host")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
