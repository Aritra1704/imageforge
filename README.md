# ImageForge

ImageForge is a standalone FastAPI service for local-first image generation. It accepts structured card-image requests, builds provider-agnostic prompts, calls ComfyUI through a saved workflow JSON, stores candidate images on the filesystem, and persists request plus candidate metadata in Postgres.

## How It Differs From ContentForge

ContentForge is the text sibling. ImageForge is the image sibling.

- ContentForge produces text candidates.
- ImageForge produces image candidates.
- ContentForge optimizes language prompts.
- ImageForge is prepared to accumulate prompt and selection history for later visual optimization.

ImageForge is intentionally not a monolith. It is a separate service that eCardFactory can call after text selection.

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

ImageForge reads [`workflows/comfyui/ecard_sdxl_basic.json`](/Users/aritrarpal/Documents/workspace_biz/imageforge/workflows/comfyui/ecard_sdxl_basic.json) from disk on each provider run. The provider injects:

- positive prompt
- negative prompt
- filename prefix
- candidate batch size
- optional checkpoint/model override

The current workflow file is a normal ComfyUI GUI export. ImageForge converts it into the API prompt format before submission to `/prompt`.

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

1. Call ContentForge for text generation.
2. Let the user or pipeline choose the final text.
3. Call `POST /api/images/generate` on ImageForge with the chosen text and theme context.
4. Check the HTTP status and also check `ok`, `results[].ok`, and `meta.total_candidates`.
5. Show returned image candidates using their `public_url` values.
6. Call `POST /api/images/candidates/{candidate_id}/select` for the chosen image.
7. For additional variants on the same request context, call `POST /api/images/regenerate`.
8. Render the final composed card in eCardFactory using the selected candidate's canonical asset URL.

ImageForge is intentionally only the image generation and candidate persistence service. It does not implement eCardFactory UI, final rendering, auth, billing, or deployment.

## Request Contract For eCardFactory

Example `POST /api/images/generate` payload:

```json
{
  "theme_name": "Ugadi",
  "theme_bucket": "occasion",
  "cultural_context": "indian",
  "selected_text": "Happy Ugadi. Wishing you prosperity, joy and new beginnings.",
  "tone_style": "warm",
  "visual_style": "festive",
  "cards_per_theme": 10,
  "image_candidates_per_run": 3,
  "provider_targets": [
    {
      "provider": "comfyui",
      "model": "sd_xl_base_1.0"
    }
  ],
  "trace_id": "ecard-job-001"
}
```

The response returns provider execution metadata plus candidate `public_url` values that eCardFactory can render immediately.

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

Request detail and candidate list APIs intentionally do not expose absolute filesystem paths.

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
