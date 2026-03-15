from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles

from app.busy import BusyGuard
from app.config import Settings, get_settings
from app.errors import AppError, app_error_handler, unexpected_error_handler, validation_error_handler
from app.observability import (
    configure_logging,
    get_logger,
    reset_request_id,
    reset_trace_id,
    set_request_id,
    set_trace_id,
)
from app.routers import candidates, generate, quality, system
from app.services.generation.service import GenerationService
from app.services.persistence.memory import PromptMemoryService
from app.services.persistence.repository import PostgresImageRepository, RepositoryProtocol
from app.services.prompts.image_prompt_builder import ImagePromptBuilder
from app.services.providers.base import ImageProvider
from app.services.providers.comfyui import ComfyUIProvider
from app.services.providers.openai_dalle import OpenAIDalleProvider
from app.services.storage.base import StorageBackend
from app.services.storage.filesystem import FilesystemStorage


logger = get_logger(__name__)


def build_storage(settings: Settings) -> StorageBackend:
    if settings.image_storage_backend != "filesystem":
        raise ValueError(
            f"Unsupported storage backend {settings.image_storage_backend!r}."
        )
    return FilesystemStorage(
        root=settings.image_storage_root,
        public_base_url=settings.image_public_base_url,
    )


def build_provider_registry(settings: Settings) -> dict[str, ImageProvider]:
    return {
        "comfyui": ComfyUIProvider(settings),
        "openai_dalle": OpenAIDalleProvider(),
    }


def create_app(
    settings: Settings | None = None,
    *,
    repository: RepositoryProtocol | None = None,
    storage: StorageBackend | None = None,
    providers: dict[str, ImageProvider] | None = None,
    busy_guard: BusyGuard | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    storage = storage or build_storage(settings)
    storage.ensure_ready()

    repository = repository or PostgresImageRepository(settings.database_url)
    providers = providers or build_provider_registry(settings)
    busy_guard = busy_guard or BusyGuard(
        max_concurrent_jobs=settings.max_concurrent_jobs,
        max_queue=settings.max_queue,
    )
    prompt_builder = ImagePromptBuilder()
    memory_service = PromptMemoryService(repository)
    generation_service = GenerationService(
        settings=settings,
        repository=repository,
        storage=storage,
        providers=providers,
        prompt_builder=prompt_builder,
        memory_service=memory_service,
        busy_guard=busy_guard,
    )

    app = FastAPI(title=settings.service_name, version=settings.service_version)

    app.state.settings = settings
    app.state.repository = repository
    app.state.storage = storage
    app.state.providers = providers
    app.state.busy_guard = busy_guard
    app.state.memory_service = memory_service
    app.state.generation_service = generation_service

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex}"
        trace_id = request.headers.get("X-Trace-Id")
        request.state.request_id = request_id
        request.state.trace_id = trace_id

        request_token = set_request_id(request_id)
        trace_token = set_trace_id(trace_id)
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = request_id
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "request_completed method=%s path=%s status_code=%s duration_ms=%s",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
            return response
        finally:
            reset_request_id(request_token)
            reset_trace_id(trace_token)

    app.include_router(system.router)
    app.include_router(generate.router)
    app.include_router(candidates.router)
    app.include_router(quality.router)
    app.mount("/assets", StaticFiles(directory=str(settings.image_storage_root)), name="assets")

    return app
