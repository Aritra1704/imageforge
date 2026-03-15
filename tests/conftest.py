from __future__ import annotations

import io
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.busy import BusyGuard
from app.config import Settings
from app.main import create_app
from app.services.providers.base import (
    ImageProvider,
    ProviderGeneratedImage,
    ProviderRequestContext,
    ProviderRunResult,
)
from app.services.providers.openai_dalle import OpenAIDalleProvider
from app.services.storage.filesystem import FilesystemStorage


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def make_png_bytes(color: tuple[int, int, int] = (120, 90, 180)) -> bytes:
    image = Image.new("RGB", (64, 96), color=color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class InMemoryRepository:
    def __init__(self) -> None:
        self.requests: dict[str, dict[str, Any]] = {}
        self.provider_runs: dict[str, dict[str, Any]] = {}
        self.candidates: dict[str, dict[str, Any]] = {}
        self.prompt_history: dict[str, dict[str, Any]] = {}
        self.database_reachable = True
        self.schema_ready = True

    def health_check(self) -> bool:
        return True

    def readiness_check(self) -> dict[str, bool]:
        return {
            "database_reachable": self.database_reachable,
            "schema_ready": self.schema_ready,
        }

    def create_request(self, request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        row = {
            "request_id": request_id,
            "trace_id": payload.get("trace_id"),
            "theme_name": payload["theme_name"],
            "theme_bucket": payload["theme_bucket"],
            "cultural_context": payload.get("cultural_context"),
            "selected_text": payload["selected_text"],
            "tone_style": payload.get("tone_style"),
            "visual_style": payload.get("visual_style"),
            "cards_per_theme": payload["cards_per_theme"],
            "image_candidates_per_run": payload["image_candidates_per_run"],
            "notes": payload.get("notes"),
            "request_payload_json": payload,
            "created_at": _utcnow(),
        }
        self.requests[request_id] = row
        return row

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        return self.requests.get(request_id)

    def list_requests(
        self,
        *,
        limit: int,
        offset: int,
        theme_name: str | None = None,
        theme_bucket: str | None = None,
        provider: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> list[dict[str, Any]]:
        request_rows = list(self.requests.values())
        request_rows.sort(key=lambda row: row["created_at"], reverse=True)

        items: list[dict[str, Any]] = []
        for row in request_rows:
            if theme_name and row["theme_name"] != theme_name:
                continue
            if theme_bucket and row["theme_bucket"] != theme_bucket:
                continue
            if created_after and row["created_at"] < created_after:
                continue
            if created_before and row["created_at"] > created_before:
                continue

            runs = [run for run in self.provider_runs.values() if run["request_id"] == row["request_id"]]
            if provider and not any(run["provider"] == provider for run in runs):
                continue
            candidates = [
                candidate
                for candidate in self.candidates.values()
                if candidate["request_id"] == row["request_id"]
            ]
            selected = next((candidate for candidate in candidates if candidate["is_selected"]), None)
            items.append(
                {
                    "request_id": row["request_id"],
                    "trace_id": row.get("trace_id"),
                    "theme_name": row["theme_name"],
                    "theme_bucket": row["theme_bucket"],
                    "cultural_context": row.get("cultural_context"),
                    "cards_per_theme": row["cards_per_theme"],
                    "image_candidates_per_run": row["image_candidates_per_run"],
                    "created_at": row["created_at"],
                    "candidate_count": len(candidates),
                    "selected_candidate_id": selected["candidate_id"] if selected else None,
                    "selected_candidate_url": selected["public_url"] if selected else None,
                    "providers": sorted({run["provider"] for run in runs}),
                }
            )
        return items[offset : offset + limit]

    def create_provider_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {**payload, "created_at": _utcnow()}
        self.provider_runs[payload["provider_run_id"]] = row
        return row

    def list_provider_runs(self, request_id: str) -> list[dict[str, Any]]:
        rows = [row for row in self.provider_runs.values() if row["request_id"] == request_id]
        rows.sort(key=lambda row: row["created_at"])
        return rows

    def create_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {
            **payload,
            "selected_at": None,
            "created_at": _utcnow(),
        }
        self.candidates[payload["candidate_id"]] = row
        return row

    def list_candidates(self, request_id: str) -> list[dict[str, Any]]:
        rows = [row for row in self.candidates.values() if row["request_id"] == request_id]
        rows.sort(key=lambda row: (row["created_at"], row["candidate_index"]))
        return rows

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        return self.candidates.get(candidate_id)

    def select_candidate(self, candidate_id: str) -> dict[str, Any]:
        target = self.candidates[candidate_id]
        request_id = target["request_id"]
        for candidate in self.candidates.values():
            if candidate["request_id"] == request_id:
                candidate["is_selected"] = False
                candidate["selected_at"] = None
        target["is_selected"] = True
        target["selected_at"] = _utcnow()

        for row in self.prompt_history.values():
            if row["request_id"] == request_id and row["provider"] == target["provider"]:
                row["selected_candidate_id"] = candidate_id
        return target

    def create_prompt_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {**payload, "created_at": _utcnow()}
        self.prompt_history[payload["history_id"]] = row
        return row

    def list_prompt_history(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        rows = list(self.prompt_history.values())
        rows.sort(key=lambda row: row["created_at"], reverse=True)
        return rows[offset : offset + limit]


class MockProvider(ImageProvider):
    name = "comfyui"

    def __init__(self) -> None:
        self.call_counts = defaultdict(int)

    async def generate_candidates(
        self, request: ProviderRequestContext, prompt_bundle
    ) -> ProviderRunResult:
        self.call_counts[request.request_id] += 1
        batch_index = self.call_counts[request.request_id]
        candidates = [
            ProviderGeneratedImage(
                filename=f"{request.request_id}_{batch_index}_{index}.png",
                content=make_png_bytes(color=(100 + index * 10, 80, 140)),
            )
            for index in range(request.candidate_count)
        ]
        return ProviderRunResult(
            provider=self.name,
            model=request.target_model or "sd_xl_base_1.0",
            workflow_name="ecard_sdxl_basic.json",
            prompt_used=prompt_bundle.positive_prompt,
            negative_prompt_used=prompt_bundle.negative_prompt,
            latency_ms=25,
            ok=True,
            candidates=candidates,
            raw_response={"mocked": True, "candidate_count": len(candidates)},
        )

    async def health_check(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return ["sd_xl_base_1.0"]


@pytest.fixture
def repository() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def storage(tmp_path: Path) -> FilesystemStorage:
    storage = FilesystemStorage(
        root=tmp_path / "imageforge-assets",
        public_base_url="http://localhost:8090/assets",
    )
    storage.ensure_ready()
    return storage


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.model_validate(
        {
            "service_name": "imageforge",
            "service_version": "test",
            "log_level": "INFO",
            "port": 8090,
            "comfyui_base_url": "http://127.0.0.1:8188",
            "comfyui_workflow_path": Path.cwd() / "workflows/comfyui/ecard_sdxl_basic.json",
            "image_provider": "comfyui",
            "image_storage_backend": "filesystem",
            "image_storage_root": tmp_path / "imageforge-assets",
            "image_public_base_url": "http://localhost:8090/assets",
            "database_url": "postgresql://unused",
            "max_concurrent_jobs": 1,
            "max_queue": 0,
            "default_candidate_count": 3,
        }
    )


@pytest.fixture
def providers() -> dict[str, ImageProvider]:
    return {
        "comfyui": MockProvider(),
        "openai_dalle": OpenAIDalleProvider(),
    }


@pytest.fixture
def client(
    settings: Settings,
    repository: InMemoryRepository,
    storage: FilesystemStorage,
    providers: dict[str, ImageProvider],
) -> TestClient:
    app = create_app(
        settings=settings,
        repository=repository,
        storage=storage,
        providers=providers,
        busy_guard=BusyGuard(max_concurrent_jobs=1, max_queue=0),
    )
    return TestClient(app)


@pytest.fixture
def sample_generate_payload() -> dict[str, Any]:
    return {
        "theme_name": "Ugadi",
        "theme_bucket": "occasion",
        "cultural_context": "indian",
        "selected_text": "Happy Ugadi. Wishing you prosperity, joy and new beginnings.",
        "tone_style": "warm",
        "visual_style": "festive",
        "cards_per_theme": 10,
        "image_candidates_per_run": 3,
        "provider_targets": [{"provider": "comfyui", "model": "sd_xl_base_1.0"}],
        "trace_id": "ecard-job-001",
    }
