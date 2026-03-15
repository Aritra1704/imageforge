from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.schemas import QualityHistoryResponse


router = APIRouter(prefix="/api/images/quality", tags=["quality"])


@router.get("/history", response_model=QualityHistoryResponse)
async def quality_history(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> QualityHistoryResponse:
    items = request.app.state.memory_service.list_history(limit=limit, offset=offset)
    return QualityHistoryResponse(ok=True, limit=limit, offset=offset, items=items)
