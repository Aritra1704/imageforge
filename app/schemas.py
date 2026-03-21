from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer


ProviderName = Literal["comfyui", "openai_dalle"]
WorkflowType = Literal[
    "ecard_background",
    "ecard_border_frame",
    "festival_motif_pack",
    "hero_illustration",
    "supporting_scene",
    "bw_sketch_asset",
]
AssetType = Literal[
    "background_full",
    "border_frame",
    "hero_illustration",
    "corner_decoration",
    "object_pack",
    "festival_motif",
]
StyleProfile = Literal[
    "draft_sketch",
    "bw_line_art",
    "flat_illustration",
    "soft_color_illustration",
    "premium_render",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FlexibleSpecModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_serializer(mode="plain")
    def _serialize(self) -> dict[str, Any]:
        data = {key: value for key, value in self.__dict__.items() if value is not None}
        extra = getattr(self, "__pydantic_extra__", None) or {}
        for key, value in extra.items():
            if value is not None:
                data[key] = value
        return data


class SceneSpec(FlexibleSpecModel):
    subject: str | None = None
    composition: str | None = None
    background_intent: str | None = None
    environment: str | None = None
    lighting: str | None = None
    palette: str | None = None

    @field_validator(
        "subject",
        "composition",
        "background_intent",
        "environment",
        "lighting",
        "palette",
        mode="before",
    )
    @classmethod
    def _strip_scene_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        return cleaned or None


class RenderSpec(FlexibleSpecModel):
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    orientation: str | None = None
    quality_profile: str | None = None

    @field_validator("orientation", "quality_profile", mode="before")
    @classmethod
    def _strip_render_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        return cleaned or None


class CreativeDirection(FlexibleSpecModel):
    motif_hint: str | None = None
    subject_hint: str | None = None
    visual_keywords: list[str] | None = None
    avoid_keywords: list[str] | None = None

    @field_validator("motif_hint", "subject_hint", mode="before")
    @classmethod
    def _strip_creative_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        return cleaned or None

    @field_validator("visual_keywords", "avoid_keywords", mode="before")
    @classmethod
    def _strip_keyword_lists(cls, value: Any) -> Any:
        if value is None or not isinstance(value, list):
            return value
        cleaned_items: list[str] = []
        for item in value:
            if item is None:
                continue
            cleaned = item.strip() if isinstance(item, str) else str(item).strip()
            if cleaned:
                cleaned_items.append(cleaned)
        return cleaned_items or None


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
    selected_text: str | None = None
    workflow_type: WorkflowType
    asset_type: AssetType
    style_profile: StyleProfile
    scene_spec: SceneSpec | str | None = None
    render_spec: RenderSpec | str | None = None
    creative_direction: CreativeDirection | None = Field(
        default=None,
        description=(
            "Caller-supplied creative guidance. Theme motifs and catalog knowledge "
            "should come from eCardFactory or upstream configuration, not ImageForge."
        ),
    )
    tone_style: str | None = None
    visual_style: str | None = None
    candidate_count: int = Field(ge=1)
    provider_targets: list[ProviderTarget] = Field(default_factory=list)
    trace_id: str | None = None
    notes: str | None = None

    @field_validator(
        "theme_name",
        "theme_bucket",
        "cultural_context",
        "selected_text",
        "workflow_type",
        "asset_type",
        "style_profile",
        "tone_style",
        "visual_style",
        "trace_id",
        "notes",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        return cleaned or None


class RegenerateImageRequest(StrictModel):
    request_id: str = Field(min_length=1)
    provider_targets: list[ProviderTarget] | None = None
    candidate_count: int | None = Field(default=None, ge=1)
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


class ProgressFields(BaseModel):
    status: str
    stage: str
    progress_pct: int = Field(ge=0, le=100)
    started_at: datetime | None = None
    finished_at: datetime | None = None


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
    request_id: str
    provider_run_id: str
    provider: str
    model: str | None = None
    candidate_index: int = Field(ge=1)
    relative_path: str
    public_url: str
    is_selected: bool
    width: int | None = None
    height: int | None = None
    quality_score: float | None = None
    relevance_score: float | None = None
    reason_codes: list[str] = Field(default_factory=list)
    rank: int | None = None
    created_at: datetime


class ProviderErrorResponse(BaseModel):
    type: str
    message: str


class ProviderExecutionResponse(ProgressFields):
    provider: str
    model: str | None = None
    ok: bool
    latency_ms: int | None = None
    prompt_used: str
    negative_prompt_used: str
    workflow_name: str | None = None
    candidates: list[GeneratedCandidateResponse] = Field(default_factory=list)
    error: ProviderErrorResponse | None = None


class GenerationResponse(ProgressFields):
    ok: bool
    request_id: str
    trace_id: str | None = None
    recommended_candidate_id: str | None = None
    results: list[ProviderExecutionResponse]
    meta: dict[str, Any]


class ImageRequestRecord(ProgressFields):
    request_id: str
    trace_id: str | None = None
    theme_name: str
    theme_bucket: str
    cultural_context: str | None = None
    selected_text: str | None = None
    workflow_type: WorkflowType | None = None
    asset_type: AssetType | None = None
    style_profile: StyleProfile | None = None
    scene_spec: SceneSpec | str | None = None
    render_spec: RenderSpec | str | None = None
    creative_direction: CreativeDirection | None = None
    tone_style: str | None = None
    visual_style: str | None = None
    candidate_count: int | None = None
    notes: str | None = None
    recommended_candidate_id: str | None = None
    request_payload_json: dict[str, Any]
    created_at: datetime


class ImageProviderRunRecord(ProgressFields):
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
    quality_score: float | None = None
    relevance_score: float | None = None
    reason_codes: list[str] = Field(default_factory=list)
    rank: int | None = None
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


class RequestSummaryRecord(ProgressFields):
    request_id: str
    trace_id: str | None = None
    theme_name: str
    theme_bucket: str
    cultural_context: str | None = None
    workflow_type: WorkflowType | None = None
    asset_type: AssetType | None = None
    style_profile: StyleProfile | None = None
    requested_candidate_count: int | None = None
    created_at: datetime
    generated_candidate_count: int = 0
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
    supported_workflow_types: list[str] = Field(default_factory=list)
    supported_style_profiles: list[str] = Field(default_factory=list)
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
