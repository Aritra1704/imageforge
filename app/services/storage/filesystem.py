from __future__ import annotations

import io
import shutil
from pathlib import Path
from urllib.parse import quote

from PIL import Image

from app.services.storage.base import StorageBackend, StoredImage


class FilesystemStorage(StorageBackend):
    backend_name = "filesystem"

    def __init__(self, root: Path, public_base_url: str) -> None:
        self.root = root
        self.public_base_url = public_base_url.rstrip("/")
        self._subdirs = ("requests", "candidates", "selected", "temp")

    def ensure_ready(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for subdir in self._subdirs:
            (self.root / subdir).mkdir(parents=True, exist_ok=True)

        probe = self.root / "temp" / ".write-test"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except Exception as exc:  # pragma: no cover - startup failure path
            raise RuntimeError(
                f"Storage root is not writable: {self.root}"
            ) from exc

    def health_check(self) -> bool:
        try:
            self.ensure_ready()
            return True
        except Exception:
            return False

    def build_candidate_relative_path(
        self, request_id: str, candidate_id: str, original_filename: str
    ) -> str:
        suffix = Path(original_filename).suffix.lower() or ".png"
        return str(Path("candidates") / request_id / f"{candidate_id}{suffix}")

    def save_candidate(
        self,
        *,
        request_id: str,
        provider_run_id: str,
        candidate_id: str,
        original_filename: str,
        content: bytes,
    ) -> StoredImage:
        del provider_run_id
        relative_path = self.build_candidate_relative_path(
            request_id=request_id,
            candidate_id=candidate_id,
            original_filename=original_filename,
        )
        absolute_path = self.root / relative_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = self.root / "temp" / f"{candidate_id}.tmp"
        temp_path.write_bytes(content)
        temp_path.replace(absolute_path)

        width, height = self._image_size(content)
        file_size_bytes = absolute_path.stat().st_size

        return StoredImage(
            relative_path=relative_path.replace("\\", "/"),
            absolute_path=str(absolute_path),
            public_url=self._public_url(relative_path),
            storage_backend=self.backend_name,
            file_size_bytes=file_size_bytes,
            width=width,
            height=height,
        )

    def mirror_selected(
        self, *, request_id: str, candidate_id: str, absolute_path: str
    ) -> str | None:
        source = Path(absolute_path)
        if not source.exists():
            return None
        suffix = source.suffix.lower() or ".png"
        relative_path = Path("selected") / request_id / f"{candidate_id}{suffix}"
        destination = self.root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return str(relative_path).replace("\\", "/")

    def _public_url(self, relative_path: str) -> str:
        return f"{self.public_base_url}/{quote(relative_path.replace('\\', '/'), safe='/')}"

    @staticmethod
    def _image_size(content: bytes) -> tuple[int | None, int | None]:
        try:
            with Image.open(io.BytesIO(content)) as image:
                return image.width, image.height
        except Exception:
            return None, None
