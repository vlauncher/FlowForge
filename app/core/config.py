"""Application settings and configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global configuration settings for FlowForge."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    api_cors_origins: list[str] | str = ["http://localhost:5173"]
    max_request_bytes: int = 1_048_576

    # Phase 2 Database & Auth settings
    database_url: str = "postgresql+asyncpg://flowforge:flowforge@localhost:5432/flowforge"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    jwt_secret: str = "change-me-to-a-random-string-of-32-chars-or-more"
    jwt_issuer: str = "flowforge"
    jwt_audience: str = "flowforge-api"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 604800
    password_min_length: int = 12

    # Phase 4 Worker & Messaging settings
    rabbitmq_url: str = "amqp://flowforge:flowforge@localhost:5672//"
    celery_task_queue: str = "runs.execute"
    lease_seconds: int = 60
    heartbeat_seconds: int = 15
    sweeper_interval_seconds: int = 30

    # Phase 5 Egress & Secrets settings
    egress_allowed_hosts: list[str] = []
    egress_block_private: bool = True
    secrets_master_keys: str = "k1:MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="

    # Phase 6 AI & LLM settings
    llm_provider: Literal["fake", "openrouter"] = "fake"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "openrouter/free"
    llm_fallback_models: list[str] = []
    llm_timeout_seconds: int = 30
    llm_free_rpm: int = 20
    llm_free_rpd: int = 50
    llm_price_per_1k_tokens_micro_usd: int = 2000

    # Phase 8 Observability & Metrics settings
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "flowforge-api"
    metrics_enabled: bool = True

    # Phase 9 Security, Webhooks & Rate limiting
    webhook_timestamp_tolerance_seconds: int = 300
    rate_limit_enabled: bool = True

    @field_validator("llm_model")
    @classmethod
    def validate_llm_model(cls, value: str) -> str:
        if value != "openrouter/free" and not value.endswith(":free"):
            raise ValueError("LLM_NON_FREE_MODEL: only :free models or openrouter/free are allowed")
        return value

    @field_validator("llm_fallback_models", mode="before")
    @classmethod
    def validate_fallback_models(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            models = [item.strip() for item in value.split(",") if item.strip()]
        elif isinstance(value, list | tuple | set):
            models = [str(item).strip() for item in value if str(item).strip()]
        else:
            models = []
        for m in models:
            if m != "openrouter/free" and not m.endswith(":free"):
                raise ValueError(
                    "LLM_NON_FREE_MODEL: only :free models or openrouter/free are allowed"
                )
        return models

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("jwt_secret must be at least 32 characters long")
        return value

    @field_validator("api_cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            origins = [item.strip() for item in value.split(",") if item.strip()]
        elif isinstance(value, list | tuple | set):
            origins = [str(item).strip() for item in value if str(item).strip()]
        else:
            raise ValueError("api_cors_origins must be a list or a comma-separated string")

        for origin in origins:
            if origin == "*":
                raise ValueError("Wildcard '*' is forbidden in api_cors_origins")
            if not (origin.startswith("http://") or origin.startswith("https://")):
                raise ValueError(
                    f"Invalid CORS origin '{origin}': must start with http:// or https://"
                )

        return origins

    @field_validator("max_request_bytes")
    @classmethod
    def validate_max_request_bytes(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_request_bytes must be greater than 0")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
