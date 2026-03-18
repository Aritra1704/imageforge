from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _env(name: str, default: Any) -> Any:
    value = os.getenv(name)
    return default if value in (None, "") else value


def _int_env(name: str, default: int) -> int:
    return int(_env(name, default))


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    service_name: str = "imageforge"
    service_version: str = "dev"
    log_level: str = "INFO"
    port: int = 8090

    comfyui_base_url: str = "http://127.0.0.1:8188"
    comfyui_workflow_path: Path = Field(
        default=Path("workflows/comfyui/ecard_sdxl_basic.json")
    )
    image_provider: str = "comfyui"
    comfyui_positive_node_id: int = 3
    comfyui_negative_node_id: int = 4
    comfyui_save_node_id: int = 8
    comfyui_batch_node_id: int | None = 5
    comfyui_timeout_seconds: int = 300
    comfyui_poll_interval_ms: int = 1000

    image_storage_backend: str = "filesystem"
    image_storage_root: Path = Field(default=Path("./.data/imageforge-assets"))
    image_public_base_url: str = "http://localhost:8090/assets"

    database_url: str = "postgresql://postgres:postgres@localhost:5432/postgres"
    max_concurrent_jobs: int = 1
    max_queue: int = 0
    default_candidate_count: int = 3

    @field_validator("comfyui_workflow_path", "image_storage_root", mode="before")
    @classmethod
    def _resolve_path(cls, value: str | Path) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        return (Path.cwd() / path).resolve()

    @field_validator("image_provider", "image_storage_backend", mode="before")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("comfyui_base_url", "image_public_base_url", mode="before")
    @classmethod
    def _strip_url(cls, value: str) -> str:
        return value.rstrip("/")

    @classmethod
    def from_env(cls) -> "Settings":
        data = {
            "service_name": _env("SERVICE_NAME", cls.model_fields["service_name"].default),
            "service_version": _env(
                "SERVICE_VERSION", cls.model_fields["service_version"].default
            ),
            "log_level": _env("LOG_LEVEL", cls.model_fields["log_level"].default),
            "port": _int_env("PORT", cls.model_fields["port"].default),
            "comfyui_base_url": _env(
                "COMFYUI_BASE_URL", cls.model_fields["comfyui_base_url"].default
            ),
            "comfyui_workflow_path": _env(
                "COMFYUI_WORKFLOW_PATH",
                cls.model_fields["comfyui_workflow_path"].default,
            ),
            "image_provider": _env(
                "IMAGE_PROVIDER", cls.model_fields["image_provider"].default
            ),
            "comfyui_positive_node_id": _int_env(
                "COMFYUI_POSITIVE_NODE_ID",
                cls.model_fields["comfyui_positive_node_id"].default,
            ),
            "comfyui_negative_node_id": _int_env(
                "COMFYUI_NEGATIVE_NODE_ID",
                cls.model_fields["comfyui_negative_node_id"].default,
            ),
            "comfyui_save_node_id": _int_env(
                "COMFYUI_SAVE_NODE_ID", cls.model_fields["comfyui_save_node_id"].default
            ),
            "comfyui_batch_node_id": _env(
                "COMFYUI_BATCH_NODE_ID", cls.model_fields["comfyui_batch_node_id"].default
            ),
            "comfyui_timeout_seconds": _int_env(
                "COMFYUI_TIMEOUT_SECONDS",
                cls.model_fields["comfyui_timeout_seconds"].default,
            ),
            "comfyui_poll_interval_ms": _int_env(
                "COMFYUI_POLL_INTERVAL_MS",
                cls.model_fields["comfyui_poll_interval_ms"].default,
            ),
            "image_storage_backend": _env(
                "IMAGE_STORAGE_BACKEND",
                cls.model_fields["image_storage_backend"].default,
            ),
            "image_storage_root": _env(
                "IMAGE_STORAGE_ROOT", cls.model_fields["image_storage_root"].default
            ),
            "image_public_base_url": _env(
                "IMAGE_PUBLIC_BASE_URL",
                cls.model_fields["image_public_base_url"].default,
            ),
            "database_url": _env(
                "DATABASE_URL", cls.model_fields["database_url"].default
            ),
            "max_concurrent_jobs": _int_env(
                "MAX_CONCURRENT_JOBS",
                cls.model_fields["max_concurrent_jobs"].default,
            ),
            "max_queue": _int_env("MAX_QUEUE", cls.model_fields["max_queue"].default),
            "default_candidate_count": _int_env(
                "DEFAULT_IMAGE_CANDIDATE_COUNT",
                cls.model_fields["default_candidate_count"].default,
            ),
        }
        batch_node_id = data["comfyui_batch_node_id"]
        if batch_node_id in (None, ""):
            data["comfyui_batch_node_id"] = None
        else:
            data["comfyui_batch_node_id"] = int(batch_node_id)
        return cls.model_validate(data)

    @property
    def workflow_name(self) -> str:
        return self.comfyui_workflow_path.name


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
