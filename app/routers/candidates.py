from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, Request

from app.schemas import (
    CandidateListResponse,
    RequestDetailResponse,
    RequestListResponse,
    SelectCandidateResponse,
)


router = APIRouter(prefix="/api/images", tags=["candidates"])


@router.get("/requests/{request_id}/candidates", response_model=CandidateListResponse)
async def list_request_candidates(
    request_id: str, request: Request
) -> CandidateListResponse:
    return request.app.state.generation_service.list_candidates(request_id)


@router.get("/requests/{request_id}", response_model=RequestDetailResponse)
async def get_request_detail(
    request_id: str, request: Request
) -> RequestDetailResponse:
    return request.app.state.generation_service.get_request_detail(request_id)


@router.get("/requests", response_model=RequestListResponse)
async def list_requests(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    theme_name: str | None = None,
    theme_bucket: str | None = None,
    provider: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> RequestListResponse:
    return request.app.state.generation_service.list_requests(
        limit=limit,
        offset=offset,
        theme_name=theme_name,
        theme_bucket=theme_bucket,
        provider=provider,
        created_after=created_after,
        created_before=created_before,
    )


@router.post("/candidates/{candidate_id}/select", response_model=SelectCandidateResponse)
async def select_candidate(
    candidate_id: str, request: Request
) -> SelectCandidateResponse:
    return request.app.state.generation_service.select_candidate(candidate_id)
