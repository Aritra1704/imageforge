from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.schemas import HealthResponse, ModelsResponse, ReadyChecks, ReadyResponse


router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    busy_guard = request.app.state.busy_guard
    storage = request.app.state.storage
    repository = request.app.state.repository
    comfyui_provider = request.app.state.providers["comfyui"]

    comfyui_reachable = await comfyui_provider.health_check()
    database_reachable = repository.health_check()
    storage_reachable = storage.health_check()

    return HealthResponse(
        ok=comfyui_reachable and database_reachable and storage_reachable,
        service=settings.service_name,
        version=settings.service_version,
        busy=busy_guard.snapshot().busy,
        comfyui_reachable=comfyui_reachable,
        database_reachable=database_reachable,
        storage_reachable=storage_reachable,
        provider=settings.image_provider,
        request_id=request.state.request_id,
    )


@router.get("/models", response_model=ModelsResponse)
async def models(request: Request) -> ModelsResponse:
    return request.app.state.generation_service.describe_models()


@router.get("/ready", response_model=ReadyResponse)
async def ready(request: Request) -> ReadyResponse | JSONResponse:
    settings = request.app.state.settings
    storage = request.app.state.storage
    repository = request.app.state.repository
    comfyui_provider = request.app.state.providers["comfyui"]

    repo_checks = repository.readiness_check()
    checks = ReadyChecks(
        database_reachable=repo_checks["database_reachable"],
        schema_ready=repo_checks["schema_ready"],
        storage_reachable=storage.health_check(),
        comfyui_reachable=await comfyui_provider.health_check(),
        workflow_present=settings.comfyui_workflow_path.exists(),
    )
    payload = ReadyResponse(
        ok=all(checks.model_dump().values()),
        service=settings.service_name,
        checks=checks,
        request_id=request.state.request_id,
    )
    if payload.ok:
        return payload
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=payload.model_dump(mode="json"),
    )
