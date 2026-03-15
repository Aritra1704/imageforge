from pathlib import Path

from PIL import Image

from app.services.storage.filesystem import FilesystemStorage


def make_png_bytes() -> bytes:
    import io

    image = Image.new("RGB", (64, 96), color=(120, 90, 180))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_storage_path_building_and_save(tmp_path: Path):
    storage = FilesystemStorage(
        root=tmp_path / "assets",
        public_base_url="http://localhost:8090/assets",
    )
    storage.ensure_ready()

    relative_path = storage.build_candidate_relative_path(
        request_id="req_123",
        candidate_id="cand_456",
        original_filename="preview.png",
    )
    assert relative_path == "candidates/req_123/cand_456.png"

    stored = storage.save_candidate(
        request_id="req_123",
        provider_run_id="prun_1",
        candidate_id="cand_456",
        original_filename="preview.png",
        content=make_png_bytes(),
    )
    assert stored.relative_path == relative_path
    assert stored.public_url.endswith(relative_path)
    assert Path(stored.absolute_path).exists()
    assert stored.width == 64
    assert stored.height == 96
