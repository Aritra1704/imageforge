from __future__ import annotations

import asyncio
import copy
import json
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.schemas import PromptBundle
from app.services.providers.base import (
    ImageProvider,
    ProviderGeneratedImage,
    ProviderRequestContext,
    ProviderRunResult,
)


class ComfyUIProvider(ImageProvider):
    name = "comfyui"
    CHECKPOINT_SUFFIXES = (".safetensors", ".ckpt", ".pth", ".pt")

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.comfyui_base_url.rstrip("/")
        self.workflow_path = settings.comfyui_workflow_path
        self.positive_node_id = settings.comfyui_positive_node_id
        self.negative_node_id = settings.comfyui_negative_node_id
        self.save_node_id = settings.comfyui_save_node_id
        self.batch_node_id = settings.comfyui_batch_node_id
        self.timeout_seconds = settings.comfyui_timeout_seconds
        self.poll_interval_seconds = settings.comfyui_poll_interval_ms / 1000.0

    async def generate_candidates(
        self, request: ProviderRequestContext, prompt_bundle: PromptBundle
    ) -> ProviderRunResult:
        started_at = time.perf_counter()
        model_name = self._resolved_model_name(request.target_model)
        workflow_name = self.workflow_path.name
        filename_prefix = f"imageforge_{request.request_id}_{uuid.uuid4().hex[:8]}"
        try:
            prompt = self._prepare_prompt(
                prompt_bundle=prompt_bundle,
                filename_prefix=filename_prefix,
                candidate_count=request.candidate_count,
                target_model=request.target_model,
            )
            async with httpx.AsyncClient(timeout=self.timeout_seconds + 10.0) as client:
                submit_response = await client.post(
                    f"{self.base_url}/prompt",
                    json={"prompt": prompt, "client_id": str(uuid.uuid4())},
                )
                submit_response.raise_for_status()
                submit_payload = submit_response.json()
                prompt_id = submit_payload["prompt_id"]

                history = await self._poll_history(client, prompt_id)
                images = await self._download_images(
                    client=client,
                    history_record=history,
                    candidate_count=request.candidate_count,
                )

            return ProviderRunResult(
                provider=self.name,
                model=model_name,
                workflow_name=workflow_name,
                prompt_used=prompt_bundle.positive_prompt,
                negative_prompt_used=prompt_bundle.negative_prompt,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                ok=True,
                candidates=images,
                raw_response={"submit": submit_payload, "history": history},
            )
        except Exception as exc:
            return ProviderRunResult(
                provider=self.name,
                model=model_name,
                workflow_name=workflow_name,
                prompt_used=prompt_bundle.positive_prompt,
                negative_prompt_used=prompt_bundle.negative_prompt,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                ok=False,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
                raw_response={"error": str(exc)},
            )

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/system_stats")
                if response.is_success:
                    return True
                queue_response = await client.get(f"{self.base_url}/queue")
                return queue_response.is_success
        except Exception:
            return False

    def list_models(self) -> list[str]:
        try:
            workflow = self._load_workflow()
        except Exception:
            return []

        checkpoint_name: str | None = None
        if "nodes" in workflow:
            for node in workflow.get("nodes", []):
                if node.get("type") == "CheckpointLoaderSimple":
                    widgets = node.get("widgets_values") or []
                    if widgets:
                        checkpoint_name = widgets[0]
                    break
        else:
            for node in workflow.values():
                if node.get("class_type") == "CheckpointLoaderSimple":
                    checkpoint_name = node.get("inputs", {}).get("ckpt_name")
                    break
        if not checkpoint_name:
            return []
        return [self._display_model_name(checkpoint_name)]

    def _prepare_prompt(
        self,
        *,
        prompt_bundle: PromptBundle,
        filename_prefix: str,
        candidate_count: int,
        target_model: str | None,
    ) -> dict[str, Any]:
        workflow = self._load_workflow()
        if "nodes" in workflow:
            return self._convert_gui_workflow(
                workflow=workflow,
                prompt_bundle=prompt_bundle,
                filename_prefix=filename_prefix,
                candidate_count=candidate_count,
                target_model=target_model,
            )

        prompt = copy.deepcopy(workflow)
        self._inject_api_prompt(
            prompt=prompt,
            prompt_bundle=prompt_bundle,
            filename_prefix=filename_prefix,
            candidate_count=candidate_count,
            target_model=target_model,
        )
        return prompt

    def _load_workflow(self) -> dict[str, Any]:
        return json.loads(self.workflow_path.read_text(encoding="utf-8"))

    def _convert_gui_workflow(
        self,
        *,
        workflow: dict[str, Any],
        prompt_bundle: PromptBundle,
        filename_prefix: str,
        candidate_count: int,
        target_model: str | None,
    ) -> dict[str, Any]:
        nodes_by_id = {node["id"]: copy.deepcopy(node) for node in workflow.get("nodes", [])}
        self._inject_gui_nodes(
            nodes_by_id=nodes_by_id,
            prompt_bundle=prompt_bundle,
            filename_prefix=filename_prefix,
            candidate_count=candidate_count,
            target_model=target_model,
        )

        link_lookup: dict[tuple[int, int], tuple[int, int]] = {}
        for link in workflow.get("links", []):
            _, source_node_id, source_output_index, target_node_id, target_input_index, _ = link
            link_lookup[(target_node_id, target_input_index)] = (
                source_node_id,
                source_output_index,
            )

        prompt: dict[str, Any] = {}
        for node_id, node in nodes_by_id.items():
            prompt[str(node_id)] = self._gui_node_to_api_prompt(node, link_lookup)
        return prompt

    def _inject_gui_nodes(
        self,
        *,
        nodes_by_id: dict[int, dict[str, Any]],
        prompt_bundle: PromptBundle,
        filename_prefix: str,
        candidate_count: int,
        target_model: str | None,
    ) -> None:
        self._set_widget_value(
            nodes_by_id=nodes_by_id,
            node_id=self.positive_node_id,
            index=0,
            value=prompt_bundle.positive_prompt,
        )
        self._set_widget_value(
            nodes_by_id=nodes_by_id,
            node_id=self.negative_node_id,
            index=0,
            value=prompt_bundle.negative_prompt,
        )
        self._set_widget_value(
            nodes_by_id=nodes_by_id,
            node_id=self.save_node_id,
            index=0,
            value=filename_prefix,
        )
        if self.batch_node_id is not None and self.batch_node_id in nodes_by_id:
            self._set_widget_value(
                nodes_by_id=nodes_by_id,
                node_id=self.batch_node_id,
                index=2,
                value=candidate_count,
            )

        checkpoint_name = self._normalize_checkpoint_name(
            target_model=target_model,
            workflow_default=self._find_gui_checkpoint_name(nodes_by_id),
        )
        if checkpoint_name:
            for node in nodes_by_id.values():
                if node.get("type") == "CheckpointLoaderSimple":
                    widgets = node.setdefault("widgets_values", [])
                    if widgets:
                        widgets[0] = checkpoint_name
                    else:
                        widgets.append(checkpoint_name)
                    break

    def _inject_api_prompt(
        self,
        *,
        prompt: dict[str, Any],
        prompt_bundle: PromptBundle,
        filename_prefix: str,
        candidate_count: int,
        target_model: str | None,
    ) -> None:
        positive_node = prompt.get(str(self.positive_node_id))
        negative_node = prompt.get(str(self.negative_node_id))
        save_node = prompt.get(str(self.save_node_id))
        if not positive_node or not negative_node or not save_node:
            raise ValueError("Configured ComfyUI node IDs were not found in the workflow.")

        positive_node.setdefault("inputs", {})["text"] = prompt_bundle.positive_prompt
        negative_node.setdefault("inputs", {})["text"] = prompt_bundle.negative_prompt
        save_node.setdefault("inputs", {})["filename_prefix"] = filename_prefix

        if self.batch_node_id is not None and str(self.batch_node_id) in prompt:
            prompt[str(self.batch_node_id)].setdefault("inputs", {})[
                "batch_size"
            ] = candidate_count

        checkpoint_name = self._normalize_checkpoint_name(
            target_model=target_model,
            workflow_default=self._find_api_checkpoint_name(prompt),
        )
        if checkpoint_name:
            for node in prompt.values():
                if node.get("class_type") == "CheckpointLoaderSimple":
                    node.setdefault("inputs", {})["ckpt_name"] = checkpoint_name
                    break

    async def _poll_history(
        self, client: httpx.AsyncClient, prompt_id: str
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            response = await client.get(f"{self.base_url}/history/{prompt_id}")
            response.raise_for_status()
            payload = response.json()
            history_record = payload.get(prompt_id) if isinstance(payload, dict) else None
            if not history_record and isinstance(payload, dict) and payload.get("outputs"):
                history_record = payload
            if history_record and history_record.get("outputs"):
                return history_record
            await asyncio.sleep(self.poll_interval_seconds)
        raise TimeoutError(
            f"Timed out waiting for ComfyUI prompt {prompt_id} after {self.timeout_seconds}s."
        )

    async def _download_images(
        self,
        *,
        client: httpx.AsyncClient,
        history_record: dict[str, Any],
        candidate_count: int,
    ) -> list[ProviderGeneratedImage]:
        output_images = self._extract_output_images(history_record)
        if not output_images:
            raise RuntimeError("ComfyUI completed without returning any output images.")

        images: list[ProviderGeneratedImage] = []
        for image_descriptor in output_images[:candidate_count]:
            response = await client.get(
                f"{self.base_url}/view",
                params={
                    "filename": image_descriptor["filename"],
                    "subfolder": image_descriptor.get("subfolder", ""),
                    "type": image_descriptor.get("type", "output"),
                },
            )
            response.raise_for_status()
            images.append(
                ProviderGeneratedImage(
                    filename=image_descriptor["filename"],
                    content=response.content,
                )
            )
        return images

    def _extract_output_images(self, history_record: dict[str, Any]) -> list[dict[str, Any]]:
        outputs = history_record.get("outputs", {})
        preferred = outputs.get(str(self.save_node_id), {}).get("images", [])
        if preferred:
            return preferred

        images: list[dict[str, Any]] = []
        for node_output in outputs.values():
            images.extend(node_output.get("images", []))
        return images

    @staticmethod
    def _gui_node_to_api_prompt(
        node: dict[str, Any], link_lookup: dict[tuple[int, int], tuple[int, int]]
    ) -> dict[str, Any]:
        inputs: dict[str, Any] = {}
        for index, input_meta in enumerate(node.get("inputs", [])):
            link_value = link_lookup.get((node["id"], index))
            if link_value is not None:
                source_node_id, source_output_index = link_value
                inputs[input_meta["name"]] = [str(source_node_id), source_output_index]

        widgets = node.get("widgets_values") or []
        node_type = node["type"]
        if node_type == "CheckpointLoaderSimple":
            inputs["ckpt_name"] = widgets[0]
        elif node_type == "CLIPTextEncode":
            inputs["text"] = widgets[0]
        elif node_type == "EmptyLatentImage":
            inputs["width"] = widgets[0]
            inputs["height"] = widgets[1]
            inputs["batch_size"] = widgets[2]
        elif node_type == "KSampler":
            inputs["seed"] = widgets[0]
            inputs["steps"] = widgets[2]
            inputs["cfg"] = widgets[3]
            inputs["sampler_name"] = widgets[4]
            inputs["scheduler"] = widgets[5]
            inputs["denoise"] = widgets[6]
        elif node_type == "SaveImage":
            inputs["filename_prefix"] = widgets[0]
        elif node_type == "VAEDecode":
            pass
        else:
            raise ValueError(f"Unsupported ComfyUI node type: {node_type}")

        return {"class_type": node_type, "inputs": inputs}

    @staticmethod
    def _set_widget_value(
        *, nodes_by_id: dict[int, dict[str, Any]], node_id: int, index: int, value: Any
    ) -> None:
        node = nodes_by_id.get(node_id)
        if node is None:
            raise ValueError(f"Workflow node {node_id} was not found.")
        widgets = node.setdefault("widgets_values", [])
        while len(widgets) <= index:
            widgets.append(None)
        widgets[index] = value

    @staticmethod
    def _find_gui_checkpoint_name(nodes_by_id: dict[int, dict[str, Any]]) -> str | None:
        for node in nodes_by_id.values():
            if node.get("type") == "CheckpointLoaderSimple":
                widgets = node.get("widgets_values") or []
                if widgets:
                    return widgets[0]
        return None

    @staticmethod
    def _find_api_checkpoint_name(prompt: dict[str, Any]) -> str | None:
        for node in prompt.values():
            if node.get("class_type") == "CheckpointLoaderSimple":
                return node.get("inputs", {}).get("ckpt_name")
        return None

    @staticmethod
    def _normalize_checkpoint_name(
        *, target_model: str | None, workflow_default: str | None
    ) -> str | None:
        if not target_model:
            return workflow_default
        lowered = target_model.lower()
        if lowered.endswith(ComfyUIProvider.CHECKPOINT_SUFFIXES):
            return target_model
        suffix = ".safetensors"
        if workflow_default:
            for known_suffix in ComfyUIProvider.CHECKPOINT_SUFFIXES:
                if workflow_default.lower().endswith(known_suffix):
                    suffix = known_suffix
                    break
        return f"{target_model}{suffix}"

    def _resolved_model_name(self, target_model: str | None) -> str | None:
        if target_model:
            return self._display_model_name(target_model)
        models = self.list_models()
        return models[0] if models else None

    @classmethod
    def _display_model_name(cls, model_name: str) -> str:
        lowered = model_name.lower()
        for suffix in cls.CHECKPOINT_SUFFIXES:
            if lowered.endswith(suffix):
                return model_name[: -len(suffix)]
        return model_name
