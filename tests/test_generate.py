from fastapi.testclient import TestClient

from app.main import create_app
from app.services.prompts.image_prompt_builder import ImagePromptBuilder
from app.services.providers.base import ImageProvider, ProviderRequestContext, ProviderRunResult
from app.services.providers.openai_dalle import OpenAIDalleProvider


class FailingProvider(ImageProvider):
    name = "comfyui"

    async def generate_candidates(
        self, request: ProviderRequestContext, prompt_bundle
    ) -> ProviderRunResult:
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
        )

    async def health_check(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return ["sd_xl_base_1.0"]


def test_request_validation(client, sample_generate_payload):
    invalid_payload = dict(sample_generate_payload)
    invalid_payload["selected_text"] = ""
    response = client.post("/api/images/generate", json=invalid_payload)
    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "validation_error"


def test_prompt_builder_output_shape(sample_generate_payload):
    builder = ImagePromptBuilder()
    bundle = builder.build(sample_generate_payload)
    assert "clear central text area" in bundle.positive_prompt
    assert "Ugadi theme" in bundle.positive_prompt
    assert "text" in bundle.negative_prompt
    assert "watermark" in bundle.negative_prompt


def test_generate_route_with_mocked_provider(client, sample_generate_payload):
    response = client.post("/api/images/generate", json=sample_generate_payload)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["trace_id"] == "ecard-job-001"
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["provider"] == "comfyui"
    assert result["workflow_name"] == "ecard_sdxl_basic.json"
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
            "image_candidates_per_run": 2,
            "trace_id": "ecard-job-regen-001",
        },
    )
    assert regenerate_response.status_code == 200
    regenerated = regenerate_response.json()
    assert regenerated["ok"] is True
    assert regenerated["request_id"] == request_id
    assert regenerated["trace_id"] == "ecard-job-regen-001"
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
