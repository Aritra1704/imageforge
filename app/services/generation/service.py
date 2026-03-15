from __future__ import annotations

import uuid
from typing import Any

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
            payload_dict = payload.model_dump(mode="json")
            self.repository.create_request(request_id=request_id, payload=payload_dict)
            return await self._execute_generation(
                request_id=request_id,
                payload=payload,
                trace_id=payload.trace_id,
                request_created=True,
            )

    async def regenerate(self, payload: RegenerateImageRequest) -> GenerationResponse:
        async with self.busy_guard.acquire():
            existing_request = self.repository.get_request(payload.request_id)
            if existing_request is None:
                raise NotFoundError(f"Request {payload.request_id} was not found.")

            original = self._request_row_to_generate_request(existing_request)
            candidate_count = (
                payload.image_candidates_per_run or original.image_candidates_per_run
            )
            provider_targets = payload.provider_targets or original.provider_targets
            self._ensure_supported_targets(
                provider_targets
                or [ProviderTarget(provider=self.settings.image_provider, model=None)]
            )
            regenerated = original.model_copy(
                update={
                    "image_candidates_per_run": candidate_count,
                    "provider_targets": provider_targets,
                    "trace_id": payload.trace_id or original.trace_id,
                }
            )
            return await self._execute_generation(
                request_id=payload.request_id,
                payload=regenerated,
                trace_id=regenerated.trace_id,
                request_created=False,
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
            request=request_row,
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
    ) -> GenerationResponse:
        prompt_bundle = self.prompt_builder.build(payload.model_dump())
        provider_targets = payload.provider_targets or [
            ProviderTarget(provider=self.settings.image_provider, model=None)
        ]

        results: list[ProviderExecutionResponse] = []
        total_candidates = 0
        for target in provider_targets:
            provider = self.providers[target.provider]
            provider_request = ProviderRequestContext(
                request_id=request_id,
                trace_id=trace_id,
                theme_name=payload.theme_name,
                theme_bucket=payload.theme_bucket,
                cultural_context=payload.cultural_context,
                selected_text=payload.selected_text,
                tone_style=payload.tone_style,
                visual_style=payload.visual_style,
                cards_per_theme=payload.cards_per_theme,
                candidate_count=payload.image_candidates_per_run,
                notes=payload.notes,
                target_model=target.model,
            )

            provider_result = await provider.generate_candidates(
                provider_request, prompt_bundle
            )
            provider_run_id = _new_id("prun")
            self.repository.create_provider_run(
                {
                    "provider_run_id": provider_run_id,
                    "request_id": request_id,
                    "provider": provider_result.provider,
                    "model": provider_result.model,
                    "workflow_name": provider_result.workflow_name,
                    "prompt_used": provider_result.prompt_used,
                    "negative_prompt_used": provider_result.negative_prompt_used,
                    "latency_ms": provider_result.latency_ms,
                    "ok": provider_result.ok,
                    "error_type": provider_result.error_type,
                    "error_message": provider_result.error_message,
                    "raw_response_json": provider_result.raw_response,
                }
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

            stored_candidates = self._persist_candidates(
                provider_run_id=provider_run_id,
                request_id=request_id,
                provider_result=provider_result,
            )
            total_candidates += len(stored_candidates)
            results.append(
                ProviderExecutionResponse(
                    provider=provider_result.provider,
                    model=provider_result.model,
                    ok=provider_result.ok,
                    latency_ms=provider_result.latency_ms,
                    prompt_used=provider_result.prompt_used,
                    negative_prompt_used=provider_result.negative_prompt_used,
                    workflow_name=provider_result.workflow_name,
                    candidates=stored_candidates,
                    error=(
                        ProviderErrorResponse(
                            type=provider_result.error_type or "provider_error",
                            message=provider_result.error_message
                            or "Provider execution failed.",
                        )
                        if not provider_result.ok
                        else None
                    ),
                )
            )

        return GenerationResponse(
            ok=any(result.ok for result in results),
            request_id=request_id,
            trace_id=trace_id,
            results=results,
            meta={
                "request_created": request_created,
                "providers_attempted": len(results),
                "providers_succeeded": sum(1 for result in results if result.ok),
                "total_candidates": total_candidates,
            },
        )

    def _persist_candidates(
        self,
        *,
        provider_run_id: str,
        request_id: str,
        provider_result: ProviderRunResult,
    ) -> list[dict[str, Any]]:
        stored_candidates: list[dict[str, Any]] = []
        for index, generated_image in enumerate(provider_result.candidates):
            candidate_id = _new_id("cand")
            stored_image = self.storage.save_candidate(
                request_id=request_id,
                provider_run_id=provider_run_id,
                candidate_id=candidate_id,
                original_filename=generated_image.filename,
                content=generated_image.content,
            )
            candidate_row = self.repository.create_candidate(
                {
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
                    "is_selected": False,
                }
            )
            stored_candidates.append(candidate_row)
        return stored_candidates

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
        if not payload.get("provider_targets"):
            payload["provider_targets"] = []
        return GenerateImageRequest.model_validate(payload)
