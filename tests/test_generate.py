from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import RenderSpec
from app.services.prompts.image_prompt_builder import ImagePromptBuilder
from app.services.providers.comfyui import ComfyUIProvider
from app.services.providers.base import ImageProvider, ProviderRequestContext, ProviderRunResult
from app.services.providers.openai_dalle import OpenAIDalleProvider


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FailingProvider(ImageProvider):
    name = "comfyui"

    async def generate_candidates(
        self, request: ProviderRequestContext, prompt_bundle
    ) -> ProviderRunResult:
        started_at = _utcnow()
        return ProviderRunResult(
            provider=self.name,
            model=request.target_model or "sd_xl_base_1.0",
            workflow_name="ecard_sdxl_basic.json",
            prompt_used=prompt_bundle.positive_prompt,
            negative_prompt_used=prompt_bundle.negative_prompt,
            latency_ms=10,
            ok=False,
            candidates=[],
            error_type="mock_failure",
            error_message="Mock provider failure.",
            raw_response={"mocked": True, "failed": True},
            status="failed",
            stage="failed",
            progress_pct=100,
            started_at=started_at,
            finished_at=_utcnow(),
        )

    async def health_check(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return ["sd_xl_base_1.0"]


def test_request_validation(client, sample_generate_payload):
    invalid_payload = dict(sample_generate_payload)
    invalid_payload["candidate_count"] = 0
    response = client.post("/api/images/generate", json=invalid_payload)
    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "validation_error"


def test_prompt_builder_output_shape(sample_generate_payload):
    builder = ImagePromptBuilder()
    bundle = builder.build(sample_generate_payload)
    assert "image-only visual asset" in bundle.positive_prompt
    assert "supporting scene workflow asset" in bundle.positive_prompt
    assert "soft color illustration treatment" in bundle.positive_prompt
    assert "Ugadi theme" in bundle.positive_prompt
    assert "warm tone" in bundle.positive_prompt
    assert "festive visual style" in bundle.positive_prompt
    assert "768x1152" in bundle.positive_prompt
    assert "greeting card background" not in bundle.positive_prompt
    assert "clear central text area" not in bundle.positive_prompt
    assert "readable text" in bundle.negative_prompt
    assert "watermark" in bundle.negative_prompt


def test_generate_route_with_mocked_provider(client, sample_generate_payload):
    response = client.post("/api/images/generate", json=sample_generate_payload)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["trace_id"] == "ecard-job-001"
    assert body["status"] == "completed"
    assert body["stage"] == "completed"
    assert body["progress_pct"] == 100
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["provider"] == "comfyui"
    assert result["workflow_name"] == "ecard_sdxl_basic.json"
    assert result["status"] == "completed"
    assert result["progress_pct"] == 100
    assert len(result["candidates"]) == 3
    first_candidate = result["candidates"][0]
    assert first_candidate["provider_run_id"].startswith("prun_")
    assert first_candidate["provider"] == "comfyui"
    assert first_candidate["model"] == "sd_xl_base_1.0"
    assert body["meta"]["total_candidates"] == 3


def test_regenerate_route_with_mocked_provider(client, sample_generate_payload):
    generate_response = client.post("/api/images/generate", json=sample_generate_payload)
    request_id = generate_response.json()["request_id"]

    regenerate_response = client.post(
        "/api/images/regenerate",
        json={
            "request_id": request_id,
            "candidate_count": 2,
            "trace_id": "ecard-job-regen-001",
        },
    )
    assert regenerate_response.status_code == 200
    regenerated = regenerate_response.json()
    assert regenerated["ok"] is True
    assert regenerated["request_id"] == request_id
    assert regenerated["trace_id"] == "ecard-job-regen-001"
    assert regenerated["status"] == "completed"
    assert len(regenerated["results"][0]["candidates"]) == 2

    candidates_response = client.get(f"/api/images/requests/{request_id}/candidates")
    candidates = candidates_response.json()["candidates"]
    assert len(candidates) == 5


def test_generate_returns_non_200_when_all_providers_fail(
    settings, repository, storage, sample_generate_payload
):
    app = create_app(
        settings=settings,
        repository=repository,
        storage=storage,
        providers={
            "comfyui": FailingProvider(),
            "openai_dalle": OpenAIDalleProvider(),
        },
    )
    response = TestClient(app).post("/api/images/generate", json=sample_generate_payload)
    assert response.status_code == 502
    body = response.json()
    assert body["ok"] is False
    assert body["status"] == "failed"
    assert body["meta"]["total_candidates"] == 0
    assert body["results"][0]["ok"] is False
    assert body["results"][0]["error"]["type"] == "mock_failure"


def test_openai_dalle_request_fails_clearly(client, sample_generate_payload):
    payload = dict(sample_generate_payload)
    payload["provider_targets"] = [{"provider": "openai_dalle", "model": "gpt-image-1"}]
    response = client.post("/api/images/generate", json=payload)
    assert response.status_code == 501
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["message"] == "Provider openai_dalle is not implemented."


def test_request_detail_exposes_asset_fields(client, sample_generate_payload):
    generate_response = client.post("/api/images/generate", json=sample_generate_payload)
    request_id = generate_response.json()["request_id"]
    detail_response = client.get(f"/api/images/requests/{request_id}")
    request_payload = detail_response.json()["request"]
    assert request_payload["workflow_type"] == "supporting_scene"
    assert request_payload["asset_type"] == "hero_illustration"
    assert request_payload["style_profile"] == "soft_color_illustration"
    assert request_payload["scene_spec"] == sample_generate_payload["scene_spec"]
    assert request_payload["render_spec"] == sample_generate_payload["render_spec"]
    assert request_payload["status"] == "completed"
    assert request_payload["progress_pct"] == 100


def test_structured_asset_payload_is_accepted(client):
    payload = {
        "workflow_type": "festival_motif_pack",
        "asset_type": "festival_motif",
        "style_profile": "flat_illustration",
        "theme_name": "Ugadi",
        "theme_bucket": "occasion",
        "cultural_context": "indian",
        "selected_text": "Happy Ugadi. Wishing you prosperity and joy.",
        "tone_style": "festive",
        "visual_style": "traditional festive",
        "scene_spec": {
            "subject": "mango leaves, diya, festive fruits",
            "composition": "isolated decorative objects",
            "background_intent": "clean minimal background",
        },
        "render_spec": {
            "width": 768,
            "height": 768,
            "orientation": "square",
            "quality_profile": "draft",
        },
        "candidate_count": 2,
        "provider_targets": [
            {
                "provider": "comfyui",
                "model": "sd_xl_base_1.0",
            }
        ],
        "trace_id": "manual-ugadi-test-001",
        "notes": "manual motif test",
    }
    response = client.post("/api/images/generate", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["results"][0]["ok"] is True
    assert len(body["results"][0]["candidates"]) == 2


def test_comfyui_provider_uses_structured_render_spec_dimensions(tmp_path):
    settings = Settings.model_validate(
        {
            "comfyui_base_url": "http://127.0.0.1:8188",
            "comfyui_workflow_path": tmp_path / "workflow.json",
            "image_storage_root": tmp_path / "assets",
            "image_public_base_url": "http://localhost:8090/assets",
            "database_url": "postgresql://unused",
        }
    )
    provider = ComfyUIProvider(settings)
    width, height = provider._resolve_dimensions(
        "festival_motif_pack",
        RenderSpec(width=768, height=768, orientation="square", quality_profile="draft").model_dump(
            exclude_none=True
        ),
    )
    assert (width, height) == (768, 768)
