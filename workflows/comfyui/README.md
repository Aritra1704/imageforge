# ComfyUI Workflow Notes

ImageForge loads [`ecard_sdxl_basic.json`](/Users/aritrarpal/Documents/workspace_biz/imageforge/workflows/comfyui/ecard_sdxl_basic.json) from disk and submits it to ComfyUI through the `/prompt` API.

The bundled workflow file is a standard ComfyUI GUI export, not the raw API prompt format. The ImageForge provider converts it at runtime and injects the prompt values before submission.

## Required Node Contract

The current bundled workflow uses:

- Positive prompt node: `CLIPTextEncode`, node id `3`
- Negative prompt node: `CLIPTextEncode`, node id `4`
- Save image node: `SaveImage`, node id `8`
- Batch-size node: `EmptyLatentImage`, node id `5`

Injected values:

- `COMFYUI_POSITIVE_NODE_ID` controls which node receives the positive prompt text
- `COMFYUI_NEGATIVE_NODE_ID` controls which node receives the negative prompt text
- `COMFYUI_SAVE_NODE_ID` controls which node receives the filename prefix
- `COMFYUI_BATCH_NODE_ID` controls which `EmptyLatentImage` node has its `batch_size` changed

## Expectations

- The save node must emit image outputs into ComfyUI history.
- The workflow must remain compatible with the node types currently converted by ImageForge:
  - `CheckpointLoaderSimple`
  - `CLIPTextEncode`
  - `EmptyLatentImage`
  - `KSampler`
  - `VAEDecode`
  - `SaveImage`

If you replace the workflow with a materially different graph, update the provider conversion logic in [`app/services/providers/comfyui.py`](/Users/aritrarpal/Documents/workspace_biz/imageforge/app/services/providers/comfyui.py).
