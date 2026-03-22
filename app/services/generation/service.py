from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any, get_args

from app.busy import BusyGuard
from app.config import Settings
from app.errors import NotFoundError, ProviderNotImplementedError
from app.schemas import (
    CandidateListResponse,
    GenerateImageRequest,
    GenerationResponse,
    ModelsProviderInfo,
    ModelsResponse,
    ProviderErrorResponse,
    ProviderExecutionResponse,
    ProviderTarget,
    RegenerateImageRequest,
    RequestDetailResponse,
    RequestListResponse,
    SelectCandidateResponse,
    StyleProfile,
    WorkflowType,
)
from app.services.persistence.memory import PromptMemoryService
from app.services.persistence.repository import RepositoryProtocol
from app.services.prompts.image_prompt_builder import ImagePromptBuilder
from app.services.providers.base import (
    ImageProvider,
    ProviderRequestContext,
    ProviderRunResult,
)
from app.services.storage.base import StorageBackend


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _spec_payload(value: Any) -> Any:
    if value is None:
        return None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json", exclude_none=True)
    return value


SUPPORTED_WORKFLOW_TYPES = list(get_args(WorkflowType))
SUPPORTED_STYLE_PROFILES = list(get_args(StyleProfile))
_MAX_SCORE = 10.0
_CATASTROPHIC_ASPECT_MISMATCH_TOLERANCE = 0.35


class GenerationService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: RepositoryProtocol,
        storage: StorageBackend,
        providers: dict[str, ImageProvider],
        prompt_builder: ImagePromptBuilder,
        memory_service: PromptMemoryService,
        busy_guard: BusyGuard,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.storage = storage
        self.providers = providers
        self.prompt_builder = prompt_builder
        self.memory_service = memory_service
        self.busy_guard = busy_guard

    async def generate(self, payload: GenerateImageRequest) -> GenerationResponse:
        async with self.busy_guard.acquire():
            self._ensure_supported_targets(
                payload.provider_targets
                or [ProviderTarget(provider=self.settings.image_provider, model=None)]
            )
            request_id = _new_id("imgreq")
            payload_dict = payload.model_dump(mode="json", exclude_none=True)
            self.repository.create_request(request_id=request_id, payload=payload_dict)
            request_started_at = _utcnow()
            self.repository.update_request_progress(
                request_id,
                status="running",
                stage="prompt_building",
                progress_pct=5,
                started_at=request_started_at,
                finished_at=None,
            )
            return await self._execute_generation(
                request_id=request_id,
                payload=payload,
                trace_id=payload.trace_id,
                request_created=True,
                request_started_at=request_started_at,
            )

    async def regenerate(self, payload: RegenerateImageRequest) -> GenerationResponse:
        async with self.busy_guard.acquire():
            existing_request = self.repository.get_request(payload.request_id)
            if existing_request is None:
                raise NotFoundError(f"Request {payload.request_id} was not found.")

            original = self._request_row_to_generate_request(existing_request)
            candidate_count = payload.candidate_count or original.candidate_count
            provider_targets = payload.provider_targets or original.provider_targets
            self._ensure_supported_targets(
                provider_targets
                or [ProviderTarget(provider=self.settings.image_provider, model=None)]
            )
            regenerated = original.model_copy(
                update={
                    "candidate_count": candidate_count,
                    "provider_targets": provider_targets,
                    "trace_id": payload.trace_id or original.trace_id,
                }
            )
            request_started_at = _utcnow()
            self.repository.update_request_progress(
                payload.request_id,
                status="running",
                stage="prompt_building",
                progress_pct=5,
                started_at=request_started_at,
                finished_at=None,
            )
            return await self._execute_generation(
                request_id=payload.request_id,
                payload=regenerated,
                trace_id=regenerated.trace_id,
                request_created=False,
                request_started_at=request_started_at,
            )

    def get_request_detail(self, request_id: str) -> RequestDetailResponse:
        request_row = self.repository.get_request(request_id)
        if request_row is None:
            raise NotFoundError(f"Request {request_id} was not found.")
        candidates = self.repository.list_candidates(request_id)
        selected_candidate = next(
            (candidate for candidate in candidates if candidate.get("is_selected")), None
        )
        return RequestDetailResponse(
            ok=True,
            request=self._public_request(request_row),
            provider_runs=self.repository.list_provider_runs(request_id),
            candidates=[self._public_candidate(candidate) for candidate in candidates],
            selected_candidate=(
                self._public_candidate(selected_candidate)
                if selected_candidate is not None
                else None
            ),
        )

    def list_requests(
        self,
        *,
        limit: int,
        offset: int,
        theme_name: str | None,
        theme_bucket: str | None,
        provider: str | None,
        created_after,
        created_before,
    ) -> RequestListResponse:
        items = self.repository.list_requests(
            limit=limit,
            offset=offset,
            theme_name=theme_name,
            theme_bucket=theme_bucket,
            provider=provider,
            created_after=created_after,
            created_before=created_before,
        )
        return RequestListResponse(ok=True, limit=limit, offset=offset, items=items)

    def list_candidates(self, request_id: str) -> CandidateListResponse:
        request_row = self.repository.get_request(request_id)
        if request_row is None:
            raise NotFoundError(f"Request {request_id} was not found.")
        return CandidateListResponse(
            ok=True,
            request_id=request_id,
            candidates=[
                self._public_candidate(candidate)
                for candidate in self.repository.list_candidates(request_id)
            ],
        )

    def select_candidate(self, candidate_id: str) -> SelectCandidateResponse:
        selected_candidate = self.repository.select_candidate(candidate_id)
        return SelectCandidateResponse(
            ok=True,
            candidate=self._public_candidate(selected_candidate),
        )

    def describe_models(self) -> ModelsResponse:
        current_provider = self.settings.image_provider
        providers = [
            ModelsProviderInfo(
                provider="comfyui",
                status="available",
                enabled=current_provider == "comfyui",
                configured=self.settings.comfyui_workflow_path.exists(),
                workflow_path=str(self.settings.comfyui_workflow_path),
                default_candidate_count=self.settings.default_candidate_count,
                models=self.providers["comfyui"].list_models(),
                supported_workflow_types=SUPPORTED_WORKFLOW_TYPES,
                supported_style_profiles=SUPPORTED_STYLE_PROFILES,
                notes="Active local provider backed by a saved ComfyUI workflow.",
            ),
            ModelsProviderInfo(
                provider="openai_dalle",
                status="not_implemented",
                enabled=False,
                configured=False,
                workflow_path=None,
                default_candidate_count=self.settings.default_candidate_count,
                models=[],
                supported_workflow_types=SUPPORTED_WORKFLOW_TYPES,
                supported_style_profiles=SUPPORTED_STYLE_PROFILES,
                notes="Provider is scaffolded only and is not implemented in v1.",
            ),
        ]
        return ModelsResponse(ok=True, current_provider=current_provider, providers=providers)

    async def _execute_generation(
        self,
        *,
        request_id: str,
        payload: GenerateImageRequest,
        trace_id: str | None,
        request_created: bool,
        request_started_at: datetime,
    ) -> GenerationResponse:
        prompt_bundle = self.prompt_builder.build(payload.model_dump())
        provider_targets = payload.provider_targets or [
            ProviderTarget(provider=self.settings.image_provider, model=None)
        ]
        self.repository.update_request_progress(
            request_id,
            status="running",
            stage="provider_execution",
            progress_pct=15,
            started_at=request_started_at,
            finished_at=None,
        )

        provider_batches: list[dict[str, Any]] = []
        total_candidates = 0
        rejected_candidates = 0
        for index, target in enumerate(provider_targets, start=1):
            provider = self.providers[target.provider]
            provider_request = ProviderRequestContext(
                request_id=request_id,
                trace_id=trace_id,
                theme_name=payload.theme_name,
                theme_bucket=payload.theme_bucket,
                cultural_context=payload.cultural_context,
                selected_text=payload.selected_text,
                workflow_type=payload.workflow_type,
                asset_role=payload.asset_role,
                asset_type=payload.asset_type,
                style_profile=payload.style_profile,
                scene_spec=_spec_payload(payload.scene_spec),
                render_spec=_spec_payload(payload.render_spec),
                creative_direction=_spec_payload(payload.creative_direction),
                tone_style=payload.tone_style,
                visual_style=payload.visual_style,
                candidate_count=payload.candidate_count,
                notes=payload.notes,
                target_model=target.model,
            )

            provider_run_id = _new_id("prun")
            provider_started_at = _utcnow()
            self.repository.create_provider_run(
                {
                    "provider_run_id": provider_run_id,
                    "request_id": request_id,
                    "provider": target.provider,
                    "model": target.model,
                    "workflow_name": None,
                    "prompt_used": prompt_bundle.positive_prompt,
                    "negative_prompt_used": prompt_bundle.negative_prompt,
                    "latency_ms": None,
                    "ok": False,
                    "error_type": None,
                    "error_message": None,
                    "raw_response_json": None,
                    "status": "running",
                    "stage": "provider_running",
                    "progress_pct": 10,
                    "started_at": provider_started_at,
                    "finished_at": None,
                }
            )
            provider_result = await provider.generate_candidates(
                provider_request, prompt_bundle
            )
            self.memory_service.record_prompt_history(
                {
                    "history_id": _new_id("hist"),
                    "request_id": request_id,
                    "theme_name": payload.theme_name,
                    "theme_bucket": payload.theme_bucket,
                    "provider": provider_result.provider,
                    "model": provider_result.model,
                    "prompt_used": provider_result.prompt_used,
                    "negative_prompt_used": provider_result.negative_prompt_used,
                    "selected_candidate_id": None,
                    "quality_label": None,
                }
            )

            stored_candidates, filtered_candidate_count = self._persist_candidates(
                provider_run_id=provider_run_id,
                request_id=request_id,
                payload=payload,
                provider_result=provider_result,
            )
            total_candidates += len(stored_candidates)
            rejected_candidates += filtered_candidate_count
            provider_status = (
                "completed" if provider_result.ok and stored_candidates else "failed"
            )
            provider_finished_at = provider_result.finished_at or _utcnow()
            provider_raw_response = dict(provider_result.raw_response or {})
            provider_raw_response["accepted_candidate_count"] = len(stored_candidates)
            provider_raw_response["rejected_candidate_count"] = filtered_candidate_count
            self.repository.update_provider_run(
                provider_run_id,
                provider=provider_result.provider,
                model=provider_result.model,
                workflow_name=provider_result.workflow_name,
                prompt_used=provider_result.prompt_used,
                negative_prompt_used=provider_result.negative_prompt_used,
                latency_ms=provider_result.latency_ms,
                ok=provider_result.ok,
                error_type=provider_result.error_type,
                error_message=provider_result.error_message,
                raw_response_json=provider_raw_response,
                status=provider_status,
                stage="completed" if provider_status == "completed" else "failed",
                progress_pct=100,
                started_at=provider_result.started_at or provider_started_at,
                finished_at=provider_finished_at,
            )
            request_progress = min(
                95,
                15 + int((index / max(len(provider_targets), 1)) * 80),
            )
            self.repository.update_request_progress(
                request_id,
                status="running",
                stage="provider_execution",
                progress_pct=request_progress,
                started_at=request_started_at,
                finished_at=None,
            )
            provider_batches.append(
                {
                    "provider_result": provider_result,
                    "provider_started_at": provider_result.started_at or provider_started_at,
                    "provider_finished_at": provider_finished_at,
                    "provider_status": provider_status,
                    "candidate_ids": [
                        str(candidate.get("candidate_id") or "")
                        for candidate in stored_candidates
                        if str(candidate.get("candidate_id") or "").strip()
                    ],
                }
            )

        ranked_candidates = self._refresh_request_ranking(request_id=request_id)
        ranked_candidates_by_id = {
            str(candidate.get("candidate_id") or ""): candidate
            for candidate in ranked_candidates
            if str(candidate.get("candidate_id") or "").strip()
        }
        recommended_candidate_id = str(
            (self.repository.get_request(request_id) or {}).get("recommended_candidate_id") or ""
        ).strip() or None
        results = [
            ProviderExecutionResponse(
                provider=batch["provider_result"].provider,
                model=batch["provider_result"].model,
                ok=batch["provider_result"].ok,
                latency_ms=batch["provider_result"].latency_ms,
                prompt_used=batch["provider_result"].prompt_used,
                negative_prompt_used=batch["provider_result"].negative_prompt_used,
                workflow_name=batch["provider_result"].workflow_name,
                candidates=[
                    ranked_candidates_by_id[candidate_id]
                    for candidate_id in sorted(
                        batch["candidate_ids"],
                        key=lambda value: (
                            int(ranked_candidates_by_id.get(value, {}).get("rank") or 10**9),
                            int(ranked_candidates_by_id.get(value, {}).get("candidate_index") or 0),
                        ),
                    )
                    if candidate_id in ranked_candidates_by_id
                ],
                status=batch["provider_status"],
                stage="completed" if batch["provider_status"] == "completed" else "failed",
                progress_pct=100,
                started_at=batch["provider_started_at"],
                finished_at=batch["provider_finished_at"],
                error=(
                    ProviderErrorResponse(
                        type=batch["provider_result"].error_type or "provider_error",
                        message=batch["provider_result"].error_message
                        or "Provider execution failed.",
                    )
                    if not batch["provider_result"].ok
                    else None
                ),
            )
            for batch in provider_batches
        ]

        request_ok = any(
            batch["provider_status"] == "completed" for batch in provider_batches
        ) and total_candidates > 0
        request_finished_at = _utcnow()
        self.repository.update_request_progress(
            request_id,
            status="completed" if request_ok else "failed",
            stage="completed" if request_ok else "failed",
            progress_pct=100,
            started_at=request_started_at,
            finished_at=request_finished_at,
        )
        request_row = self.repository.get_request(request_id) or {}
        return GenerationResponse(
            ok=request_ok,
            request_id=request_id,
            trace_id=trace_id,
            recommended_candidate_id=recommended_candidate_id,
            results=results,
            status=request_row.get("status", "completed" if request_ok else "failed"),
            stage=request_row.get("stage", "completed" if request_ok else "failed"),
            progress_pct=request_row.get("progress_pct", 100),
            started_at=request_row.get("started_at", request_started_at),
            finished_at=request_row.get("finished_at", request_finished_at),
            meta={
                "request_created": request_created,
                "providers_attempted": len(results),
                "providers_succeeded": sum(
                    1 for batch in provider_batches if batch["provider_status"] == "completed"
                ),
                "total_candidates": total_candidates,
                "rejected_candidates": rejected_candidates,
            },
        )

    def _persist_candidates(
        self,
        *,
        provider_run_id: str,
        request_id: str,
        payload: GenerateImageRequest,
        provider_result: ProviderRunResult,
    ) -> tuple[list[dict[str, Any]], int]:
        stored_candidates: list[dict[str, Any]] = []
        filtered_candidate_count = 0
        existing_candidates = self.repository.list_candidates(request_id)
        seen_relative_paths = {
            self._normalized_string(candidate.get("relative_path"))
            for candidate in existing_candidates
            if self._normalized_string(candidate.get("relative_path"))
        }
        seen_public_urls = {
            self._normalized_string(candidate.get("public_url"))
            for candidate in existing_candidates
            if self._normalized_string(candidate.get("public_url"))
        }
        for index, generated_image in enumerate(provider_result.candidates, start=1):
            candidate_id = _new_id("cand")
            stored_image = self.storage.save_candidate(
                request_id=request_id,
                provider_run_id=provider_run_id,
                candidate_id=candidate_id,
                original_filename=generated_image.filename,
                content=generated_image.content,
            )
            candidate_row = {
                "candidate_id": candidate_id,
                "request_id": request_id,
                "provider_run_id": provider_run_id,
                "provider": provider_result.provider,
                "model": provider_result.model,
                "candidate_index": index,
                "prompt_used": provider_result.prompt_used,
                "negative_prompt_used": provider_result.negative_prompt_used,
                "relative_path": stored_image.relative_path,
                "absolute_path": stored_image.absolute_path,
                "public_url": stored_image.public_url,
                "storage_backend": stored_image.storage_backend,
                "file_size_bytes": stored_image.file_size_bytes,
                "width": stored_image.width,
                "height": stored_image.height,
                "quality_score": None,
                "relevance_score": None,
                "reason_codes": [],
                "rank": None,
                "is_selected": False,
            }
            analysis = self._analyze_candidate(
                candidate_row=candidate_row,
                payload=payload,
                provider_ok=provider_result.ok,
                seen_relative_paths=seen_relative_paths,
                seen_public_urls=seen_public_urls,
            )
            if analysis["rejected"]:
                filtered_candidate_count += 1
                continue
            candidate_row.update(
                {
                    "quality_score": analysis["quality_score"],
                    "relevance_score": analysis["relevance_score"],
                    "reason_codes": analysis["reason_codes"],
                }
            )
            seen_relative_paths.add(
                self._normalized_string(candidate_row.get("relative_path"))
            )
            seen_public_urls.add(
                self._normalized_string(candidate_row.get("public_url"))
            )
            stored_candidates.append(self.repository.create_candidate(candidate_row))
        return stored_candidates, filtered_candidate_count

    def _refresh_request_ranking(self, *, request_id: str) -> list[dict[str, Any]]:
        candidates = self.repository.list_candidates(request_id)
        ranked_candidates: list[dict[str, Any]] = []
        ordered_candidates = sorted(candidates, key=self._ranking_sort_key)
        for rank, candidate in enumerate(ordered_candidates, start=1):
            ranked_candidates.append(
                self.repository.update_candidate_analysis(
                    str(candidate["candidate_id"]),
                    quality_score=self._rounded_score(candidate.get("quality_score")),
                    relevance_score=self._rounded_score(candidate.get("relevance_score")),
                    reason_codes=self._normalized_reason_codes(candidate.get("reason_codes")),
                    rank=rank,
                )
            )
        recommended_candidate_id = (
            str(ranked_candidates[0].get("candidate_id") or "").strip()
            if ranked_candidates
            else None
        )
        self.repository.update_request_recommendation(
            request_id,
            recommended_candidate_id=recommended_candidate_id,
        )
        return ranked_candidates

    def _analyze_candidate(
        self,
        *,
        candidate_row: dict[str, Any],
        payload: GenerateImageRequest,
        provider_ok: bool,
        seen_relative_paths: set[str],
        seen_public_urls: set[str],
    ) -> dict[str, Any]:
        reason_codes: list[str] = []
        relative_path = self._normalized_string(candidate_row.get("relative_path"))
        public_url = self._normalized_string(candidate_row.get("public_url"))
        prompt_used = self._normalized_string(candidate_row.get("prompt_used"))
        negative_prompt_used = self._normalized_string(candidate_row.get("negative_prompt_used"))
        storage_backend = self._normalized_string(candidate_row.get("storage_backend"))
        width = self._positive_int(candidate_row.get("width"))
        height = self._positive_int(candidate_row.get("height"))
        file_size_bytes = self._positive_int(candidate_row.get("file_size_bytes"))
        render_width, render_height, expected_orientation = self._render_preferences(
            payload.render_spec
        )
        expects_dimensions = render_width is not None and render_height is not None

        if not provider_ok:
            return self._rejected_analysis()
        reason_codes.append("provider_success")

        if not relative_path or not public_url:
            return self._rejected_analysis()
        if relative_path in seen_relative_paths or public_url in seen_public_urls:
            return self._rejected_analysis()
        reason_codes.append("valid_asset")

        if expects_dimensions and (width is None or height is None):
            return self._rejected_analysis()
        if width is not None and height is not None:
            reason_codes.append("dimensions_present")

        if prompt_used and negative_prompt_used:
            reason_codes.append("prompt_complete")

        quality_score = 0.0
        relevance_score = 0.0

        quality_score += 2.5
        quality_score += 3.0
        if width is not None and height is not None:
            quality_score += 1.5
            relevance_score += 1.0
        if prompt_used and negative_prompt_used:
            quality_score += 1.5
            relevance_score += 1.5
        if storage_backend and file_size_bytes is not None and file_size_bytes > 0:
            quality_score += 1.5

        if self._normalized_string(payload.selected_text):
            reason_codes.append("selected_text_present")
            relevance_score += 1.5

        actual_orientation = self._orientation_for_dimensions(width, height)
        if expected_orientation and actual_orientation:
            if expected_orientation == actual_orientation:
                reason_codes.append("orientation_match")
                relevance_score += 3.0
            else:
                reason_codes.append("weak_request_fit")
                relevance_score += 1.0

        aspect_bonus, catastrophic_mismatch = self._aspect_fit_score(
            width=width,
            height=height,
            expected_width=render_width,
            expected_height=render_height,
        )
        if catastrophic_mismatch:
            return self._rejected_analysis()
        relevance_score += aspect_bonus
        if aspect_bonus <= 1.0 and render_width is not None and render_height is not None:
            if "weak_request_fit" not in reason_codes:
                reason_codes.append("weak_request_fit")

        return {
            "rejected": False,
            "quality_score": self._rounded_score(quality_score),
            "relevance_score": self._rounded_score(relevance_score),
            "reason_codes": self._normalized_reason_codes(reason_codes),
        }

    @staticmethod
    def _render_preferences(render_spec: Any) -> tuple[int | None, int | None, str | None]:
        payload = _spec_payload(render_spec)
        if not isinstance(payload, dict):
            return None, None, None
        width = GenerationService._positive_int(payload.get("width"))
        height = GenerationService._positive_int(payload.get("height"))
        orientation = GenerationService._normalized_orientation(payload.get("orientation"))
        if orientation is None and width is not None and height is not None:
            orientation = GenerationService._orientation_for_dimensions(width, height)
        return width, height, orientation

    @staticmethod
    def _aspect_fit_score(
        *,
        width: int | None,
        height: int | None,
        expected_width: int | None,
        expected_height: int | None,
    ) -> tuple[float, bool]:
        if (
            width is None
            or height is None
            or expected_width is None
            or expected_height is None
        ):
            return 0.0, False
        expected_ratio = expected_width / expected_height
        actual_ratio = width / height
        mismatch_ratio = abs(actual_ratio - expected_ratio) / expected_ratio
        if mismatch_ratio > _CATASTROPHIC_ASPECT_MISMATCH_TOLERANCE:
            return 0.0, True
        if mismatch_ratio <= 0.08:
            return 3.0, False
        if mismatch_ratio <= 0.18:
            return 2.0, False
        return 1.0, False

    @staticmethod
    def _ranking_sort_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
        return (
            -(float(candidate.get("quality_score") or 0.0)),
            -(float(candidate.get("relevance_score") or 0.0)),
            str(candidate.get("provider") or ""),
            str(candidate.get("model") or ""),
            candidate.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
            int(candidate.get("candidate_index") or 0),
            str(candidate.get("relative_path") or ""),
            str(candidate.get("public_url") or ""),
        )

    @staticmethod
    def _normalized_reason_codes(value: Any) -> list[str]:
        seen: set[str] = set()
        reason_codes: list[str] = []
        for item in list(value or []):
            code = str(item or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            reason_codes.append(code)
        return reason_codes

    @staticmethod
    def _normalized_string(value: Any) -> str:
        cleaned = str(value or "").strip()
        return cleaned

    @staticmethod
    def _positive_int(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _normalized_orientation(value: Any) -> str | None:
        normalized = str(value or "").strip().lower()
        if normalized in {"portrait", "landscape", "square"}:
            return normalized
        return None

    @staticmethod
    def _orientation_for_dimensions(width: int | None, height: int | None) -> str | None:
        if width is None or height is None:
            return None
        if width == height:
            return "square"
        return "landscape" if width > height else "portrait"

    @staticmethod
    def _rounded_score(value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return round(max(0.0, min(_MAX_SCORE, parsed)), 1)

    @staticmethod
    def _rejected_analysis() -> dict[str, Any]:
        return {
            "rejected": True,
            "quality_score": None,
            "relevance_score": None,
            "reason_codes": [],
        }

    @staticmethod
    def _public_candidate(candidate_row: dict[str, Any]) -> dict[str, Any]:
        public_candidate = {key: value for key, value in candidate_row.items() if key != "absolute_path"}
        if candidate_row.get("is_selected"):
            public_candidate["selected_asset_relative_path"] = candidate_row["relative_path"]
            public_candidate["selected_asset_public_url"] = candidate_row["public_url"]
        else:
            public_candidate["selected_asset_relative_path"] = None
            public_candidate["selected_asset_public_url"] = None
        return public_candidate

    @staticmethod
    def _public_request(request_row: dict[str, Any]) -> dict[str, Any]:
        public_request = dict(request_row)
        payload = dict(request_row.get("request_payload_json") or {})
        if payload:
            public_request["workflow_type"] = payload.get(
                "workflow_type",
                GenerationService._infer_workflow_type(payload),
            )
            public_request["asset_role"] = payload.get(
                "asset_role",
                GenerationService._infer_asset_role(payload),
            )
            public_request["asset_type"] = payload.get("asset_type")
            public_request["style_profile"] = payload.get(
                "style_profile", "soft_color_illustration"
            )
            public_request["scene_spec"] = payload.get("scene_spec")
            public_request["render_spec"] = payload.get("render_spec")
            public_request["creative_direction"] = payload.get("creative_direction")
            public_request["tone_style"] = payload.get("tone_style")
            public_request["visual_style"] = payload.get("visual_style")
            public_request["candidate_count"] = payload.get("candidate_count") or payload.get(
                "image_candidates_per_run"
            )
            public_request["selected_text"] = payload.get("selected_text")
        if public_request.get("status") is None:
            public_request["status"] = "queued"
        if public_request.get("stage") is None:
            public_request["stage"] = "accepted"
        if public_request.get("progress_pct") is None:
            public_request["progress_pct"] = 0
        return public_request

    @staticmethod
    def _ensure_supported_targets(targets: list[ProviderTarget]) -> None:
        unsupported = [
            target.provider for target in targets if target.provider == "openai_dalle"
        ]
        if unsupported:
            raise ProviderNotImplementedError(
                "Provider openai_dalle is not implemented."
            )

    @staticmethod
    def _request_row_to_generate_request(row: dict[str, Any]) -> GenerateImageRequest:
        payload = dict(row["request_payload_json"])
        if not payload.get("workflow_type"):
            payload["workflow_type"] = GenerationService._infer_workflow_type(payload)
        if not payload.get("asset_role"):
            payload["asset_role"] = GenerationService._infer_asset_role(payload)
        if not payload.get("style_profile"):
            payload["style_profile"] = "soft_color_illustration"
        if not payload.get("candidate_count"):
            payload["candidate_count"] = payload.get("image_candidates_per_run") or 1
        payload["selected_text"] = payload.get("selected_text") or None
        if not payload.get("provider_targets"):
            payload["provider_targets"] = []
        return GenerateImageRequest.model_validate(payload)

    @staticmethod
    def _infer_workflow_type(payload: dict[str, Any]) -> str:
        asset_role = str(payload.get("asset_role") or "").strip()
        asset_type = str(payload.get("asset_type") or "").strip()
        if asset_role == "spot_illustration":
            return "ecard_spot_illustration_v1"
        if asset_role == "background":
            return "ecard_soft_background_v1"
        if asset_role == "motif":
            return "festival_motif_pack"
        if asset_type == "background_full":
            return "ecard_background"
        if asset_type == "border_frame":
            return "ecard_border_frame"
        if asset_type in {"festival_motif", "object_pack"}:
            return "festival_motif_pack"
        if str(payload.get("style_profile") or "").strip() in {
            "draft_sketch",
            "bw_line_art",
        }:
            return "bw_sketch_asset"
        if str(payload.get("composition_role") or "").strip() == "supporting_scene":
            return "supporting_scene"
        return "hero_illustration"

    @staticmethod
    def _infer_asset_role(payload: dict[str, Any]) -> str:
        asset_type = str(payload.get("asset_type") or "").strip()
        workflow_type = str(payload.get("workflow_type") or "").strip()
        if workflow_type == "ecard_soft_background_v1" or asset_type == "background_full":
            return "background"
        if asset_type == "festival_motif":
            return "motif"
        return "spot_illustration"
