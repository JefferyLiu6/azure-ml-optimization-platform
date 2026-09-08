from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MFBO_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    environment: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    require_api_key: bool = False
    api_key: SecretStr | None = None

    repository_backend: Literal["filesystem", "azure_blob"] = "filesystem"
    state_path: Path = Path("data/state")
    artifact_backend: Literal["filesystem", "azure_blob"] = "filesystem"
    artifact_path: Path = Path("artifacts")

    queue_backend: Literal["memory", "azure_queue"] = "memory"
    azure_storage_account_url: str | None = None
    azure_storage_connection_string: SecretStr | None = None
    azure_state_container: str = "experiment-state"
    azure_artifact_container: str = "experiment-artifacts"
    azure_queue_name: str = "mfbo-jobs"
    queue_visibility_timeout_seconds: int = Field(default=120, ge=30, le=3600)

    engine_backend: Literal["demo"] = "demo"
    allow_demo_engine: bool = True

    worker_poll_seconds: int = Field(default=5, ge=1, le=30)
    worker_max_attempts: int = Field(default=3, ge=1, le=10)
    worker_id: str = "worker-local"
    worker_metrics_port: int = Field(default=9000, ge=0, le=65535)

    mlflow_tracking_uri: str | None = None
    mlflow_experiment_name: str = "mfbo-platform"
    applicationinsights_connection_string: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
