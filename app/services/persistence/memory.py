from __future__ import annotations

from typing import Any

from app.services.persistence.repository import RepositoryProtocol


class PromptMemoryService:
    def __init__(self, repository: RepositoryProtocol) -> None:
        self.repository = repository

    def record_prompt_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.repository.create_prompt_history(payload)

    def list_history(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        return self.repository.list_prompt_history(limit=limit, offset=offset)
