CREATE SCHEMA IF NOT EXISTS imageforge;

CREATE TABLE IF NOT EXISTS imageforge.image_requests (
    request_id TEXT PRIMARY KEY,
    trace_id TEXT NULL,
    theme_name TEXT NOT NULL,
    theme_bucket TEXT NOT NULL,
    cultural_context TEXT NULL,
    selected_text TEXT NOT NULL,
    workflow_type TEXT NULL,
    asset_type TEXT NULL,
    style_profile TEXT NULL,
    scene_spec TEXT NULL,
    render_spec TEXT NULL,
    tone_style TEXT NULL,
    visual_style TEXT NULL,
    cards_per_theme INTEGER NOT NULL,
    image_candidates_per_run INTEGER NOT NULL,
    candidate_count INTEGER NULL,
    notes TEXT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'accepted',
    progress_pct INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    request_payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS imageforge.image_provider_runs (
    provider_run_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES imageforge.image_requests(request_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NULL,
    workflow_name TEXT NULL,
    prompt_used TEXT NOT NULL,
    negative_prompt_used TEXT NOT NULL,
    latency_ms INTEGER NULL,
    ok BOOLEAN NOT NULL,
    error_type TEXT NULL,
    error_message TEXT NULL,
    raw_response_json JSONB NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'queued',
    progress_pct INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS imageforge.image_candidates (
    candidate_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES imageforge.image_requests(request_id) ON DELETE CASCADE,
    provider_run_id TEXT NOT NULL REFERENCES imageforge.image_provider_runs(provider_run_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NULL,
    candidate_index INTEGER NOT NULL,
    prompt_used TEXT NOT NULL,
    negative_prompt_used TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    absolute_path TEXT NOT NULL,
    public_url TEXT NOT NULL,
    storage_backend TEXT NOT NULL,
    file_size_bytes BIGINT NULL,
    width INTEGER NULL,
    height INTEGER NULL,
    is_selected BOOLEAN NOT NULL DEFAULT false,
    selected_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS imageforge.image_feedback (
    feedback_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES imageforge.image_candidates(candidate_id) ON DELETE CASCADE,
    feedback_type TEXT NOT NULL,
    notes TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS imageforge.image_prompt_history (
    history_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES imageforge.image_requests(request_id) ON DELETE CASCADE,
    theme_name TEXT NOT NULL,
    theme_bucket TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NULL,
    prompt_used TEXT NOT NULL,
    negative_prompt_used TEXT NOT NULL,
    selected_candidate_id TEXT NULL,
    quality_label TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE imageforge.image_requests
    ADD COLUMN IF NOT EXISTS workflow_type TEXT NULL;
ALTER TABLE imageforge.image_requests
    ADD COLUMN IF NOT EXISTS asset_type TEXT NULL;
ALTER TABLE imageforge.image_requests
    ADD COLUMN IF NOT EXISTS style_profile TEXT NULL;
ALTER TABLE imageforge.image_requests
    ADD COLUMN IF NOT EXISTS scene_spec TEXT NULL;
ALTER TABLE imageforge.image_requests
    ADD COLUMN IF NOT EXISTS render_spec TEXT NULL;
ALTER TABLE imageforge.image_requests
    ADD COLUMN IF NOT EXISTS candidate_count INTEGER NULL;
ALTER TABLE imageforge.image_requests
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'queued';
ALTER TABLE imageforge.image_requests
    ADD COLUMN IF NOT EXISTS stage TEXT NOT NULL DEFAULT 'accepted';
ALTER TABLE imageforge.image_requests
    ADD COLUMN IF NOT EXISTS progress_pct INTEGER NOT NULL DEFAULT 0;
ALTER TABLE imageforge.image_requests
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ NULL;
ALTER TABLE imageforge.image_requests
    ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ NULL;

ALTER TABLE imageforge.image_provider_runs
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'queued';
ALTER TABLE imageforge.image_provider_runs
    ADD COLUMN IF NOT EXISTS stage TEXT NOT NULL DEFAULT 'queued';
ALTER TABLE imageforge.image_provider_runs
    ADD COLUMN IF NOT EXISTS progress_pct INTEGER NOT NULL DEFAULT 0;
ALTER TABLE imageforge.image_provider_runs
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ NULL;
ALTER TABLE imageforge.image_provider_runs
    ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_image_requests_created_at
    ON imageforge.image_requests (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_image_requests_theme_name
    ON imageforge.image_requests (theme_name);
CREATE INDEX IF NOT EXISTS idx_image_requests_theme_bucket
    ON imageforge.image_requests (theme_bucket);

CREATE INDEX IF NOT EXISTS idx_image_provider_runs_request_id
    ON imageforge.image_provider_runs (request_id);
CREATE INDEX IF NOT EXISTS idx_image_provider_runs_provider
    ON imageforge.image_provider_runs (provider);
CREATE INDEX IF NOT EXISTS idx_image_provider_runs_created_at
    ON imageforge.image_provider_runs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_image_candidates_request_id
    ON imageforge.image_candidates (request_id);
CREATE INDEX IF NOT EXISTS idx_image_candidates_provider
    ON imageforge.image_candidates (provider);
CREATE INDEX IF NOT EXISTS idx_image_candidates_is_selected
    ON imageforge.image_candidates (is_selected);
CREATE INDEX IF NOT EXISTS idx_image_candidates_created_at
    ON imageforge.image_candidates (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_image_feedback_candidate_id
    ON imageforge.image_feedback (candidate_id);
CREATE INDEX IF NOT EXISTS idx_image_feedback_created_at
    ON imageforge.image_feedback (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_image_prompt_history_request_id
    ON imageforge.image_prompt_history (request_id);
CREATE INDEX IF NOT EXISTS idx_image_prompt_history_provider
    ON imageforge.image_prompt_history (provider);
CREATE INDEX IF NOT EXISTS idx_image_prompt_history_theme_name
    ON imageforge.image_prompt_history (theme_name);
CREATE INDEX IF NOT EXISTS idx_image_prompt_history_theme_bucket
    ON imageforge.image_prompt_history (theme_bucket);
CREATE INDEX IF NOT EXISTS idx_image_prompt_history_created_at
    ON imageforge.image_prompt_history (created_at DESC);
