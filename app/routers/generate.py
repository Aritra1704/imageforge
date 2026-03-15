from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.schemas import GenerateImageRequest, GenerationResponse, RegenerateImageRequest


router = APIRouter(prefix="/api/images", tags=["generation"])


def _generation_response(payload: GenerationResponse) -> GenerationResponse | JSONResponse:
    total_candidates = int(payload.meta.get("total_candidates", 0))
    providers_succeeded = int(payload.meta.get("providers_succeeded", 0))
    if providers_succeeded > 0 and total_candidates > 0:
        return payload
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content=payload.model_dump(mode="json"),
    )


@router.post("/generate", response_model=GenerationResponse)
async def generate_images(
    payload: GenerateImageRequest, request: Request
) -> GenerationResponse:
    result = await request.app.state.generation_service.generate(payload)
    return _generation_response(result)


@router.post("/regenerate", response_model=GenerationResponse)
async def regenerate_images(
    payload: RegenerateImageRequest, request: Request
) -> GenerationResponse:
    result = await request.app.state.generation_service.regenerate(payload)
    return _generation_response(result)
