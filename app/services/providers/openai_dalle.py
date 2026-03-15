from __future__ import annotations

from datetime import datetime, timezone

from app.schemas import PromptBundle
from app.services.providers.base import (
    ImageProvider,
    ProviderRequestContext,
    ProviderRunResult,
)


class OpenAIDalleProvider(ImageProvider):
    name = "openai_dalle"

    async def generate_candidates(
        self, request: ProviderRequestContext, prompt_bundle: PromptBundle
    ) -> ProviderRunResult:
        now = datetime.now(timezone.utc)
        return ProviderRunResult(
            provider=self.name,
            model=request.target_model or "gpt-image-1",
            workflow_name=None,
            prompt_used=prompt_bundle.positive_prompt,
            negative_prompt_used=prompt_bundle.negative_prompt,
            latency_ms=0,
            ok=False,
            error_type="not_implemented",
            error_message="OpenAI DALL-E provider is scaffolded but not implemented in v1.",
            raw_response={"status": "not_implemented"},
            status="failed",
            stage="failed",
            progress_pct=100,
            started_at=now,
            finished_at=now,
        )

    async def health_check(self) -> bool:
        return False

    def list_models(self) -> list[str]:
        return ["gpt-image-1"]
