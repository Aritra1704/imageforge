# ImageForge

ImageForge is a standalone FastAPI asset workflow engine for local-first image generation. It accepts structured workflow-oriented asset requests, builds provider-agnostic prompts, executes ComfyUI workflows from disk, stores generated assets on the filesystem, and persists request plus candidate metadata in Postgres.

## How It Differs From ContentForge

ContentForge is the text sibling. ImageForge is the image sibling.

- ContentForge produces text candidates.
- ImageForge produces reusable image asset candidates.
- ContentForge optimizes language prompts.
- ImageForge is prepared to accumulate prompt and selection history for later visual optimization.

ImageForge is intentionally not a monolith. It is a separate service that eCardFactory can call after text selection.

ImageForge now creates image assets only. It is not intended to generate final greeting cards with embedded text. eCardFactory owns final readable text layout and final card composition. n8n can orchestrate higher-level asset workflows around ImageForge, but ImageForge remains the execution service for asset generation itself.

## Current And Future Providers

- Current provider: `ComfyUI`
- Future provider scaffold: `OpenAI DALL-E`

Only ComfyUI is available for real generation in v1. `openai_dalle` is scaffolded structurally, but generation requests using it are rejected as not implemented.

## Folder Structure

```text
app/
  main.py
  config.py
  schemas.py
  observability.py
  errors.py
  busy.py
  routers/
  services/
db/
  schema.sql
  seed.sql
scripts/
  setup_db.sh
  run_local.sh
tests/
workflows/
  comfyui/
    README.md
    ecard_sdxl_basic.json
.env.example
startup.txt
```

## Local Setup

Requirements:

- Python 3.11+
- Local Postgres
- Local ComfyUI on `http://127.0.0.1:8188`
- Writable filesystem root for assets, ideally an external SSD

Install dependencies:

```bash
pip install -e ".[dev]"
```

Create a local `.env` from `.env.example` before running the service. A local-dev `.env` is expected in the repo root and is sourced by the shell scripts; it is not auto-created by the app itself.

The important settings are:

- `DATABASE_URL`
- `COMFYUI_BASE_URL`
- `COMFYUI_WORKFLOW_PATH`
- `IMAGE_STORAGE_ROOT`
- `IMAGE_PUBLIC_BASE_URL`

## Database Setup

Create the schema and tables:

```bash
./scripts/setup_db.sh
```

This applies [`db/schema.sql`](/Users/aritrarpal/Documents/workspace_biz/imageforge/db/schema.sql) and creates the `imageforge` schema if it does not already exist.

[`db/seed.sql`](/Users/aritrarpal/Documents/workspace_biz/imageforge/db/seed.sql) is a small helper query file for local verification.

## How To Run Locally

Run the service on port `8090`:

```bash
./scripts/run_local.sh
```

That launches:

```bash
uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8090 --reload
```

## API Overview

System routes:

- `GET /health`
- `GET /models`
- `GET /ready`

Generation routes:

- `POST /api/images/generate`
- `POST /api/images/regenerate`

Request and candidate routes:

- `GET /api/images/requests`
- `GET /api/images/requests/{request_id}`
- `GET /api/images/requests/{request_id}/candidates`
- `POST /api/images/candidates/{candidate_id}/select`

Quality scaffolding:

- `GET /api/images/quality/history`

### Readiness And Failure Semantics

- `GET /health` is a lightweight service check.
- `GET /ready` is the stronger integration-readiness check. It verifies:
  - database connection
  - `imageforge` schema and required tables
  - writable storage root
  - ComfyUI reachability
  - workflow file presence on disk
- `POST /api/images/generate` and `POST /api/images/regenerate` now return:
  - `200` when at least one provider succeeds and at least one candidate exists
  - `502` when all provider targets fail and no candidates are created
  - `503` for busy/unavailable conditions already enforced by the busy guard

## ComfyUI Workflow Model

ImageForge reads ComfyUI workflow JSON from disk on each provider run. It resolves workflow execution like this:

- if `workflows/comfyui/<workflow_type>.json` exists, that file is used
- otherwise it falls back to [`workflows/comfyui/ecard_sdxl_basic.json`](/Users/aritrarpal/Documents/workspace_biz/imageforge/workflows/comfyui/ecard_sdxl_basic.json)

The provider injects:

- positive prompt
- negative prompt
- filename prefix
- candidate batch size
- low-resolution width and height defaults
- optional checkpoint/model override

The current workflow file is a normal ComfyUI GUI export. ImageForge converts it into the API prompt format before submission to `/prompt`.

Default workflow resolutions are intentionally lower for speed:

- `ecard_background`: `768x1152`
- `ecard_border_frame`: `768x1152`
- `festival_motif_pack`: `768x768`
- `hero_illustration`: `768x1152`
- `supporting_scene`: `768x1152`
- `bw_sketch_asset`: `512x768`

Larger sizes should only be requested explicitly through `render_spec`, for example `render_spec: "premium render, 1024x1536"`.

See [`workflows/comfyui/README.md`](/Users/aritrarpal/Documents/workspace_biz/imageforge/workflows/comfyui/README.md) for the node contract.

## Storage Model

Image bytes are not stored in Postgres. Only metadata is stored there.

Filesystem storage is mounted by FastAPI at `/assets`, backed by `IMAGE_STORAGE_ROOT`. The backend creates and manages:

- `requests/`
- `candidates/`
- `selected/`
- `temp/`

Candidates are persisted under `candidates/<request_id>/...`.

Selected asset behavior is explicit:

- ImageForge does not create a second selected copy anymore.
- The original candidate asset is the canonical selected asset.
- Selection responses expose `selected_asset_relative_path` and `selected_asset_public_url`, which point to the original candidate file when `is_selected=true`.

## eCardFactory Integration

Recommended client flow for eCardFactory:

1. Call ContentForge for text generation if text is needed for the final card.
2. Choose the final text outside ImageForge.
3. Choose an ImageForge workflow based on the asset you need.
4. Supply `creative_direction` from eCardFactory business logic or DB-backed configuration.
5. Call `POST /api/images/generate` with workflow-oriented asset request fields plus caller-owned creative direction.
6. Check the HTTP status and also check `ok`, `results[].ok`, and `meta.total_candidates`.
7. Show returned image asset candidates using their `public_url` values.
8. Call `POST /api/images/candidates/{candidate_id}/select` for the chosen asset.
9. Compose the final card in eCardFactory by overlaying readable text on top of the selected asset.

Recommended default workflow for eCardFactory:

- `workflow_type: "ecard_background"` for reusable card backdrops
- `asset_type: "background_full"`
- `style_profile: "soft_color_illustration"`
- `candidate_count: 3`

ImageForge is intentionally only the image-asset generation and candidate persistence service. It does not implement eCardFactory UI, final rendering, auth, billing, or deployment.

Embedded text generation is not the intended path. If final export/composition later moves into Canva Pro or a similar tool, ImageForge should still remain the asset-generation step.

Creative catalog ownership stays outside ImageForge. Theme motifs, subject hints, keyword packs, and avoid lists are expected to come from eCardFactory or its upstream configuration.

## n8n Workflow-Level Usage

n8n should orchestrate ImageForge at a workflow level, not by micromanaging raw ComfyUI graph operations.

Recommended n8n pattern:

1. Choose `workflow_type`, `asset_type`, `style_profile`, and `creative_direction` from business logic.
2. Call `POST /api/images/generate`.
3. Poll `GET /api/images/requests/{request_id}` if downstream steps need persisted progress state.
4. Branch based on request `status`, provider run `status`, and candidate count.
5. Call `POST /api/images/candidates/{candidate_id}/select` when a preferred asset is chosen.
6. Hand the selected asset URL into eCardFactory or another composition/export step.

## Request Contract

Example `POST /api/images/generate` payload:

```json
{
  "theme_name": "Ugadi",
  "theme_bucket": "occasion",
  "cultural_context": "indian",
  "selected_text": "Happy Ugadi. Wishing you prosperity, joy and new beginnings.",
  "workflow_type": "supporting_scene",
  "asset_type": "hero_illustration",
  "style_profile": "soft_color_illustration",
  "tone_style": "warm",
  "visual_style": "festive",
  "creative_direction": {
    "motif_hint": "single rooted centerpiece with seasonal celebration energy",
    "subject_hint": "banyan tree",
    "visual_keywords": ["ornamental roots", "warm natural light"],
    "avoid_keywords": ["poster", "page design"]
  },
  "scene_spec": {
    "subject": "banyan tree courtyard scene",
    "composition": "supporting scene",
    "background_intent": "South Indian decor"
  },
  "render_spec": {
    "width": 768,
    "height": 1152,
    "orientation": "portrait",
    "quality_profile": "draft"
  },
  "candidate_count": 3,
  "provider_targets": [
    {
      "provider": "comfyui",
      "model": "sd_xl_base_1.0"
    }
  ],
  "trace_id": "ecard-job-001"
}
```

Supported `workflow_type` values:

- `ecard_background`
- `ecard_border_frame`
- `festival_motif_pack`
- `hero_illustration`
- `supporting_scene`
- `bw_sketch_asset`

Supported `asset_type` values:

- `background_full`
- `border_frame`
- `hero_illustration`
- `corner_decoration`
- `object_pack`
- `festival_motif`

Supported `style_profile` values:

- `draft_sketch`
- `bw_line_art`
- `flat_illustration`
- `soft_color_illustration`
- `premium_render`

Request fields used by the prompt builder:

- `creative_direction.motif_hint`
- `creative_direction.subject_hint`
- `creative_direction.visual_keywords`
- `creative_direction.avoid_keywords`
- `theme_name`
- `theme_bucket`
- `cultural_context`
- `selected_text`
- `workflow_type`
- `asset_type`
- `style_profile`
- `scene_spec`
- `render_spec`
- `tone_style`
- `visual_style`

`creative_direction` is the preferred place for eCardFactory to send caller-owned motif and subject guidance. ImageForge does not own a hardcoded theme catalog and falls back only to generic theme phrasing when `creative_direction` is absent.

`scene_spec` and `render_spec` can be either:

- a plain string for quick use
- a structured object for more specific backend-driven generation

Structured objects are the preferred contract for backend callers.

The response returns provider execution metadata plus candidate `public_url` values that eCardFactory can render immediately as reusable assets for later composition.

Request detail responses also echo the original `creative_direction` payload back under `request.creative_direction`.

Actual generate/regenerate candidate objects include:

- `candidate_id`
- `provider_run_id`
- `provider`
- `model`
- `candidate_index`
- `relative_path`
- `public_url`
- `is_selected`
- `width`
- `height`
- `created_at`

### Progress Contract

ImageForge now persists coarse request and provider-run progress fields for polling:

- `status`
- `stage`
- `progress_pct`
- `started_at`
- `finished_at`

These fields are exposed in:

- `POST /api/images/generate`
- `POST /api/images/regenerate`
- `GET /api/images/requests`
- `GET /api/images/requests/{request_id}`

Request detail and candidate list APIs intentionally do not expose absolute filesystem paths.

### Asset-Only Prompt Direction

ImageForge prompts are asset-oriented by default:

- no greeting-card text-space phrasing
- no implied embedded typography
- no expectation that the model renders readable card text

Negative prompts explicitly suppress:

- text
- readable text
- lettering
- typography

### Example Asset Payloads

Ugadi `border_frame`:

```json
{
  "theme_name": "Ugadi",
  "theme_bucket": "occasion",
  "cultural_context": "indian",
  "selected_text": "Happy Ugadi. Wishing you prosperity, joy and new beginnings.",
  "workflow_type": "ecard_border_frame",
  "asset_type": "border_frame",
  "style_profile": "flat_illustration",
  "creative_direction": {
    "motif_hint": "ornamental festive perimeter",
    "visual_keywords": ["leaf ornament", "soft lamp glow", "clean negative space"],
    "avoid_keywords": ["poster", "page design"]
  },
  "scene_spec": "ornamental border perimeter",
  "render_spec": "clean frame geometry, reusable border asset, 768x1152, no embedded typography",
  "candidate_count": 3,
  "provider_targets": [
    {
      "provider": "comfyui",
      "model": "sd_xl_base_1.0"
    }
  ]
}
```

Ugadi `hero_illustration`:

```json
{
  "theme_name": "Ugadi",
  "theme_bucket": "occasion",
  "cultural_context": "indian",
  "selected_text": "Happy Ugadi. Wishing you prosperity, joy and new beginnings.",
  "workflow_type": "hero_illustration",
  "asset_type": "hero_illustration",
  "style_profile": "premium_render",
  "creative_direction": {
    "subject_hint": "banyan tree",
    "visual_keywords": ["rooted centerpiece", "soft festive glow"],
    "avoid_keywords": ["collage", "multiple objects"]
  },
  "scene_spec": "stylized banyan tree centerpiece",
  "render_spec": "isolated hero focus, reusable centerpiece asset, 768x1152, no embedded typography",
  "candidate_count": 3,
  "provider_targets": [
    {
      "provider": "comfyui",
      "model": "sd_xl_base_1.0"
    }
  ]
}
```

Birthday `background_full`:

```json
{
  "theme_name": "Birthday",
  "theme_bucket": "celebration",
  "cultural_context": null,
  "selected_text": "Happy Birthday. Wishing you joy, laughter, and wonderful memories.",
  "workflow_type": "ecard_background",
  "asset_type": "background_full",
  "style_profile": "soft_color_illustration",
  "creative_direction": {
    "motif_hint": "soft celebratory atmosphere",
    "visual_keywords": ["pastel glow", "subtle confetti texture"],
    "avoid_keywords": ["poster", "embedded text"]
  },
  "scene_spec": "soft celebratory background",
  "render_spec": "full-bleed reusable background, layered depth, 768x1152, no embedded typography",
  "candidate_count": 3,
  "provider_targets": [
    {
      "provider": "comfyui",
      "model": "sd_xl_base_1.0"
    }
  ]
}
```

Banyan tree scene via `hero_illustration` plus `supporting_scene` workflow intent:

```json
{
  "theme_name": "Ugadi",
  "theme_bucket": "occasion",
  "cultural_context": "indian",
  "selected_text": "Happy Ugadi. Wishing you prosperity, joy and new beginnings.",
  "workflow_type": "supporting_scene",
  "asset_type": "hero_illustration",
  "style_profile": "soft_color_illustration",
  "creative_direction": {
    "subject_hint": "banyan tree",
    "visual_keywords": ["ornamental roots", "warm natural light"],
    "avoid_keywords": ["greeting card", "object grid"]
  },
  "scene_spec": "banyan tree courtyard scene",
  "render_spec": "illustrative supporting scene asset, layered environment, 768x1152, no embedded typography",
  "candidate_count": 3,
  "provider_targets": [
    {
      "provider": "comfyui",
      "model": "sd_xl_base_1.0"
    }
  ]
}
```

## Future Optimization Memory Direction

v1 already persists prompt and selection history in:

- `imageforge.image_prompt_history`
- `imageforge.image_feedback`

That history can later support:

- candidate judging
- human preference capture
- theme-specific prompt refinement
- provider and workflow comparison

The current `GET /api/images/quality/history` route exposes the historical rows without trying to implement a full judging subsystem yet.

## Limitations Of v1

- Only local ComfyUI is implemented for real generation.
- `openai_dalle` is not implemented and is rejected for active generation requests.
- No authentication, billing, cloud deployment, or queue workers.
- No full visual scoring or feedback workflow yet.
- The included ComfyUI workflow conversion covers the node types used by the bundled workflow.
