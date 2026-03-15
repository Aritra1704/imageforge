from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class StoredImage:
    relative_path: str
    absolute_path: str
    public_url: str
    storage_backend: str
    file_size_bytes: int | None = None
    width: int | None = None
    height: int | None = None


class StorageBackend(ABC):
    backend_name = "base"

    @abstractmethod
    def ensure_ready(self) -> None: ...

    @abstractmethod
    def health_check(self) -> bool: ...

    @abstractmethod
    def build_candidate_relative_path(
        self, request_id: str, candidate_id: str, original_filename: str
    ) -> str: ...

    @abstractmethod
    def save_candidate(
        self,
        *,
        request_id: str,
        provider_run_id: str,
        candidate_id: str,
        original_filename: str,
        content: bytes,
    ) -> StoredImage: ...

    @abstractmethod
    def mirror_selected(self, *, request_id: str, candidate_id: str, absolute_path: str) -> str | None: ...
