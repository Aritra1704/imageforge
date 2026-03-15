from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.schemas import PromptBundle


@dataclass(slots=True)
class ProviderRequestContext:
    request_id: str
    trace_id: str | None
    theme_name: str
    theme_bucket: str
    cultural_context: str | None
    selected_text: str | None
    workflow_type: str
    asset_type: str
    style_profile: str
    scene_spec: Mapping[str, Any] | str | None
    render_spec: Mapping[str, Any] | str | None
    tone_style: str | None
    visual_style: str | None
    candidate_count: int
    notes: str | None
    target_model: str | None = None


@dataclass(slots=True)
class ProviderGeneratedImage:
    filename: str
    content: bytes


@dataclass(slots=True)
class ProviderRunResult:
    provider: str
    model: str | None
    workflow_name: str | None
    prompt_used: str
    negative_prompt_used: str
    latency_ms: int | None
    ok: bool
    candidates: list[ProviderGeneratedImage] = field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    raw_response: dict[str, Any] | None = None
    status: str = "completed"
    stage: str = "completed"
    progress_pct: int = 100
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ImageProvider(ABC):
    name = "base"

    @abstractmethod
    async def generate_candidates(
        self, request: ProviderRequestContext, prompt_bundle: PromptBundle
    ) -> ProviderRunResult: ...

    @abstractmethod
    async def health_check(self) -> bool: ...

    @abstractmethod
    def list_models(self) -> list[str]: ...
