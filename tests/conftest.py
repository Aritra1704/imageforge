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
            "selected_text": payload.get("selected_text"),
            "workflow_type": payload["workflow_type"],
            "asset_role": payload.get("asset_role"),
            "asset_type": payload["asset_type"],
            "style_profile": payload["style_profile"],
            "scene_spec": payload.get("scene_spec"),
            "render_spec": payload.get("render_spec"),
            "creative_direction": payload.get("creative_direction"),
            "tone_style": payload.get("tone_style"),
            "visual_style": payload.get("visual_style"),
            "candidate_count": payload["candidate_count"],
            "notes": payload.get("notes"),
            "recommended_candidate_id": None,
            "status": "queued",
            "stage": "accepted",
            "progress_pct": 0,
            "started_at": None,
            "finished_at": None,
            "request_payload_json": payload,
            "created_at": _utcnow(),
        }
        self.requests[request_id] = row
        return row

    def update_request_progress(
        self,
        request_id: str,
        *,
        status: str,
        stage: str,
        progress_pct: int,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> dict[str, Any]:
        row = self.requests[request_id]
        row["status"] = status
        row["stage"] = stage
        row["progress_pct"] = progress_pct
        row["started_at"] = started_at or row.get("started_at")
        row["finished_at"] = finished_at
        return row

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        return self.requests.get(request_id)

    def update_request_recommendation(
        self,
        request_id: str,
        *,
        recommended_candidate_id: str | None,
    ) -> dict[str, Any]:
        row = self.requests[request_id]
        row["recommended_candidate_id"] = recommended_candidate_id
        return row

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
                    "workflow_type": row.get("workflow_type"),
                    "asset_role": row.get("asset_role"),
                    "asset_type": row.get("asset_type"),
                    "style_profile": row.get("style_profile"),
                    "requested_candidate_count": row.get("candidate_count"),
                    "status": row.get("status", "queued"),
                    "stage": row.get("stage", "accepted"),
                    "progress_pct": row.get("progress_pct", 0),
                    "started_at": row.get("started_at"),
                    "finished_at": row.get("finished_at"),
                    "created_at": row["created_at"],
                    "generated_candidate_count": len(candidates),
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

    def update_provider_run(
        self,
        provider_run_id: str,
        *,
        provider: str,
        model: str | None,
        workflow_name: str | None,
        prompt_used: str,
        negative_prompt_used: str,
        latency_ms: int | None,
        ok: bool,
        error_type: str | None,
        error_message: str | None,
        raw_response_json: dict[str, Any] | None,
        status: str,
        stage: str,
        progress_pct: int,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> dict[str, Any]:
        row = self.provider_runs[provider_run_id]
        row.update(
            {
                "provider": provider,
                "model": model,
                "workflow_name": workflow_name,
                "prompt_used": prompt_used,
                "negative_prompt_used": negative_prompt_used,
                "latency_ms": latency_ms,
                "ok": ok,
                "error_type": error_type,
                "error_message": error_message,
                "raw_response_json": raw_response_json,
                "status": status,
                "stage": stage,
                "progress_pct": progress_pct,
                "started_at": started_at or row.get("started_at"),
                "finished_at": finished_at,
            }
        )
        return row

    def list_provider_runs(self, request_id: str) -> list[dict[str, Any]]:
        rows = [row for row in self.provider_runs.values() if row["request_id"] == request_id]
        rows.sort(key=lambda row: row["created_at"])
        return rows

    def create_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {
            **payload,
            "quality_score": payload.get("quality_score"),
            "relevance_score": payload.get("relevance_score"),
            "reason_codes": list(payload.get("reason_codes") or []),
            "rank": payload.get("rank"),
            "selected_at": None,
            "created_at": _utcnow(),
        }
        self.candidates[payload["candidate_id"]] = row
        return row

    def update_candidate_analysis(
        self,
        candidate_id: str,
        *,
        quality_score: float | None,
        relevance_score: float | None,
        reason_codes: list[str],
        rank: int | None,
    ) -> dict[str, Any]:
        row = self.candidates[candidate_id]
        row["quality_score"] = quality_score
        row["relevance_score"] = relevance_score
        row["reason_codes"] = list(reason_codes)
        row["rank"] = rank
        return row

    def list_candidates(self, request_id: str) -> list[dict[str, Any]]:
        rows = [row for row in self.candidates.values() if row["request_id"] == request_id]
        rows.sort(
            key=lambda row: (
                row["rank"] is None,
                row["rank"] if row["rank"] is not None else 10**9,
                row["created_at"],
                row["candidate_index"],
            )
        )
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
        started_at = _utcnow()
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
            status="completed",
            stage="completed",
            progress_pct=100,
            started_at=started_at,
            finished_at=_utcnow(),
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
        "workflow_type": "ecard_spot_illustration_v1",
        "asset_role": "spot_illustration",
        "asset_type": "hero_illustration",
        "style_profile": "soft_color_illustration",
        "scene_spec": {
            "subject": "banyan tree courtyard illustration",
            "composition": "single subject with negative space",
            "background_intent": "soft festive South Indian details",
        },
        "creative_direction": {
            "subject_hint": "banyan tree",
            "visual_keywords": ["ornamental roots", "warm natural light"],
            "avoid_keywords": ["busy scene", "poster"],
        },
        "render_spec": {
            "width": 768,
            "height": 1152,
            "orientation": "portrait",
            "quality_profile": "draft",
        },
        "tone_style": "warm",
        "visual_style": "festive",
        "candidate_count": 3,
        "provider_targets": [{"provider": "comfyui", "model": "sd_xl_base_1.0"}],
        "trace_id": "ecard-job-001",
    }
