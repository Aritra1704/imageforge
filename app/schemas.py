from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ProviderName = Literal["comfyui", "openai_dalle"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderTarget(StrictModel):
    provider: ProviderName
    model: str | None = None

    @field_validator("model", mode="before")
    @classmethod
    def _strip_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class GenerateImageRequest(StrictModel):
    theme_name: str = Field(min_length=1)
    theme_bucket: str = Field(min_length=1)
    cultural_context: str | None = None
    selected_text: str = Field(min_length=1)
    tone_style: str | None = None
    visual_style: str | None = None
    cards_per_theme: int = Field(ge=1)
    image_candidates_per_run: int = Field(ge=1)
    provider_targets: list[ProviderTarget] = Field(default_factory=list)
    trace_id: str | None = None
    notes: str | None = None

    @field_validator(
        "theme_name",
        "theme_bucket",
        "cultural_context",
        "selected_text",
        "tone_style",
        "visual_style",
        "trace_id",
        "notes",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class RegenerateImageRequest(StrictModel):
    request_id: str = Field(min_length=1)
    provider_targets: list[ProviderTarget] | None = None
    image_candidates_per_run: int | None = Field(default=None, ge=1)
    trace_id: str | None = None

    @field_validator("request_id", "trace_id", mode="before")
    @classmethod
    def _strip_regen_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class PromptBundle(StrictModel):
    positive_prompt: str
    negative_prompt: str


class ErrorDetails(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorEnvelope(BaseModel):
    ok: bool = False
    error: ErrorDetails
    request_id: str


class GeneratedCandidateResponse(BaseModel):
    candidate_id: str
    provider_run_id: str
    provider: str
    model: str | None = None
    candidate_index: int
    relative_path: str
    public_url: str
    is_selected: bool
    width: int | None = None
    height: int | None = None
    created_at: datetime


class ProviderErrorResponse(BaseModel):
    type: str
    message: str


class ProviderExecutionResponse(BaseModel):
    provider: str
    model: str | None = None
    ok: bool
    latency_ms: int | None = None
    prompt_used: str
    negative_prompt_used: str
    workflow_name: str | None = None
    candidates: list[GeneratedCandidateResponse] = Field(default_factory=list)
    error: ProviderErrorResponse | None = None


class GenerationResponse(BaseModel):
    ok: bool
    request_id: str
    trace_id: str | None = None
    results: list[ProviderExecutionResponse]
    meta: dict[str, Any]


class ImageRequestRecord(BaseModel):
    request_id: str
    trace_id: str | None = None
    theme_name: str
    theme_bucket: str
    cultural_context: str | None = None
    selected_text: str
    tone_style: str | None = None
    visual_style: str | None = None
    cards_per_theme: int
    image_candidates_per_run: int
    notes: str | None = None
    request_payload_json: dict[str, Any]
    created_at: datetime


class ImageProviderRunRecord(BaseModel):
    provider_run_id: str
    request_id: str
    provider: str
    model: str | None = None
    workflow_name: str | None = None
    prompt_used: str
    negative_prompt_used: str
    latency_ms: int | None = None
    ok: bool
    error_type: str | None = None
    error_message: str | None = None
    raw_response_json: dict[str, Any] | None = None
    created_at: datetime


class ImageCandidateRecord(BaseModel):
    candidate_id: str
    request_id: str
    provider_run_id: str
    provider: str
    model: str | None = None
    candidate_index: int
    prompt_used: str
    negative_prompt_used: str
    relative_path: str
    public_url: str
    selected_asset_relative_path: str | None = None
    selected_asset_public_url: str | None = None
    storage_backend: str
    file_size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    is_selected: bool
    selected_at: datetime | None = None
    created_at: datetime


class ImagePromptHistoryRecord(BaseModel):
    history_id: str
    request_id: str
    theme_name: str
    theme_bucket: str
    provider: str
    model: str | None = None
    prompt_used: str
    negative_prompt_used: str
    selected_candidate_id: str | None = None
    quality_label: str | None = None
    created_at: datetime


class RequestSummaryRecord(BaseModel):
    request_id: str
    trace_id: str | None = None
    theme_name: str
    theme_bucket: str
    cultural_context: str | None = None
    cards_per_theme: int
    image_candidates_per_run: int
    created_at: datetime
    candidate_count: int = 0
    selected_candidate_id: str | None = None
    selected_candidate_url: str | None = None
    providers: list[str] = Field(default_factory=list)


class RequestDetailResponse(BaseModel):
    ok: bool
    request: ImageRequestRecord
    provider_runs: list[ImageProviderRunRecord]
    candidates: list[ImageCandidateRecord]
    selected_candidate: ImageCandidateRecord | None = None


class RequestListResponse(BaseModel):
    ok: bool
    limit: int
    offset: int
    items: list[RequestSummaryRecord]


class CandidateListResponse(BaseModel):
    ok: bool
    request_id: str
    candidates: list[ImageCandidateRecord]


class SelectCandidateResponse(BaseModel):
    ok: bool
    candidate: ImageCandidateRecord


class QualityHistoryResponse(BaseModel):
    ok: bool
    limit: int
    offset: int
    items: list[ImagePromptHistoryRecord]


class ModelsProviderInfo(BaseModel):
    provider: str
    status: str
    enabled: bool
    configured: bool
    workflow_path: str | None = None
    default_candidate_count: int
    models: list[str] = Field(default_factory=list)
    notes: str | None = None


class ModelsResponse(BaseModel):
    ok: bool
    current_provider: str
    providers: list[ModelsProviderInfo]


class HealthResponse(BaseModel):
    ok: bool
    service: str
    version: str
    busy: bool
    comfyui_reachable: bool
    database_reachable: bool
    storage_reachable: bool
    provider: str
    request_id: str


class ReadyChecks(BaseModel):
    database_reachable: bool
    schema_ready: bool
    storage_reachable: bool
    comfyui_reachable: bool
    workflow_present: bool


class ReadyResponse(BaseModel):
    ok: bool
    service: str
    checks: ReadyChecks
    request_id: str
