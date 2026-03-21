from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
from typing import Any, Iterator, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.errors import NotFoundError


def _spec_column_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class RepositoryProtocol(Protocol):
    def health_check(self) -> bool: ...

    def readiness_check(self) -> dict[str, bool]: ...

    def create_request(self, request_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def update_request_progress(
        self,
        request_id: str,
        *,
        status: str,
        stage: str,
        progress_pct: int,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> dict[str, Any]: ...

    def get_request(self, request_id: str) -> dict[str, Any] | None: ...

    def update_request_recommendation(
        self,
        request_id: str,
        *,
        recommended_candidate_id: str | None,
    ) -> dict[str, Any]: ...

    def list_requests(
        self,
        *,
        limit: int,
        offset: int,
        theme_name: str | None = None,
        theme_bucket: str | None = None,
        provider: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> list[dict[str, Any]]: ...

    def create_provider_run(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def update_provider_run(
        self,
        provider_run_id: str,
        *,
        provider: str,
        model: str | None,
        workflow_name: str | None,
        prompt_used: str,
        negative_prompt_used: str,
        latency_ms: int | None,
        ok: bool,
        error_type: str | None,
        error_message: str | None,
        raw_response_json: dict[str, Any] | None,
        status: str,
        stage: str,
        progress_pct: int,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> dict[str, Any]: ...

    def list_provider_runs(self, request_id: str) -> list[dict[str, Any]]: ...

    def create_candidate(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def update_candidate_analysis(
        self,
        candidate_id: str,
        *,
        quality_score: float | None,
        relevance_score: float | None,
        reason_codes: list[str],
        rank: int | None,
    ) -> dict[str, Any]: ...

    def list_candidates(self, request_id: str) -> list[dict[str, Any]]: ...

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None: ...

    def select_candidate(self, candidate_id: str) -> dict[str, Any]: ...

    def create_prompt_history(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def list_prompt_history(self, *, limit: int, offset: int) -> list[dict[str, Any]]: ...


class PostgresImageRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    @contextmanager
    def _connect(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            yield conn

    def health_check(self) -> bool:
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def readiness_check(self) -> dict[str, bool]:
        required_tables = {
            "image_requests",
            "image_provider_runs",
            "image_candidates",
            "image_feedback",
            "image_prompt_history",
        }
        try:
            with self._connect() as conn:
                schema_exists = conn.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.schemata
                        WHERE schema_name = 'imageforge'
                    ) AS schema_exists
                    """
                ).fetchone()["schema_exists"]
                present_rows = conn.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'imageforge'
                      AND table_name = ANY(%s)
                    """,
                    (list(required_tables),),
                ).fetchall()
                present_tables = {row["table_name"] for row in present_rows}
            return {
                "database_reachable": True,
                "schema_ready": schema_exists and present_tables == required_tables,
            }
        except Exception:
            return {"database_reachable": False, "schema_ready": False}

    def create_request(self, request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        query = """
            INSERT INTO imageforge.image_requests (
                request_id,
                trace_id,
                theme_name,
                theme_bucket,
                cultural_context,
                selected_text,
                workflow_type,
                asset_type,
                style_profile,
                scene_spec,
                render_spec,
                tone_style,
                visual_style,
                cards_per_theme,
                image_candidates_per_run,
                candidate_count,
                notes,
                request_payload_json,
                status,
                stage,
                progress_pct,
                started_at,
                finished_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING *
        """
        with self._connect() as conn:
            return conn.execute(
                query,
                (
                    request_id,
                    payload.get("trace_id"),
                    payload["theme_name"],
                    payload["theme_bucket"],
                    payload.get("cultural_context"),
                    payload.get("selected_text") or "",
                    payload.get("workflow_type"),
                    payload.get("asset_type"),
                    payload.get("style_profile"),
                    _spec_column_value(payload.get("scene_spec")),
                    _spec_column_value(payload.get("render_spec")),
                    payload.get("tone_style"),
                    payload.get("visual_style"),
                    payload.get("cards_per_theme", 1),
                    payload.get("image_candidates_per_run", payload["candidate_count"]),
                    payload["candidate_count"],
                    payload.get("notes"),
                    Jsonb(payload),
                    "queued",
                    "accepted",
                    0,
                    None,
                    None,
                ),
            ).fetchone()

    def update_request_progress(
        self,
        request_id: str,
        *,
        status: str,
        stage: str,
        progress_pct: int,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> dict[str, Any]:
        query = """
            UPDATE imageforge.image_requests
            SET status = %s,
                stage = %s,
                progress_pct = %s,
                started_at = COALESCE(%s, started_at),
                finished_at = %s
            WHERE request_id = %s
            RETURNING *
        """
        with self._connect() as conn:
            return conn.execute(
                query,
                (
                    status,
                    stage,
                    progress_pct,
                    started_at,
                    finished_at,
                    request_id,
                ),
            ).fetchone()

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        query = """
            SELECT *
            FROM imageforge.image_requests
            WHERE request_id = %s
        """
        with self._connect() as conn:
            return conn.execute(query, (request_id,)).fetchone()

    def update_request_recommendation(
        self,
        request_id: str,
        *,
        recommended_candidate_id: str | None,
    ) -> dict[str, Any]:
        query = """
            UPDATE imageforge.image_requests
            SET recommended_candidate_id = %s
            WHERE request_id = %s
            RETURNING *
        """
        with self._connect() as conn:
            return conn.execute(
                query,
                (recommended_candidate_id, request_id),
            ).fetchone()

    def list_requests(
        self,
        *,
        limit: int,
        offset: int,
        theme_name: str | None = None,
        theme_bucket: str | None = None,
        provider: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        values: list[Any] = []

        if theme_name:
            conditions.append("r.theme_name = %s")
            values.append(theme_name)
        if theme_bucket:
            conditions.append("r.theme_bucket = %s")
            values.append(theme_bucket)
        if created_after:
            conditions.append("r.created_at >= %s")
            values.append(created_after)
        if created_before:
            conditions.append("r.created_at <= %s")
            values.append(created_before)
        if provider:
            conditions.append(
                """
                EXISTS (
                    SELECT 1
                    FROM imageforge.image_provider_runs prf
                    WHERE prf.request_id = r.request_id
                      AND prf.provider = %s
                )
                """
            )
            values.append(provider)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = f"""
            SELECT
                r.request_id,
                r.trace_id,
                r.theme_name,
                r.theme_bucket,
                r.cultural_context,
                r.workflow_type,
                r.asset_type,
                r.style_profile,
                r.candidate_count AS requested_candidate_count,
                r.status,
                r.stage,
                r.progress_pct,
                r.started_at,
                r.finished_at,
                r.created_at,
                COALESCE(cand.generated_candidate_count, 0) AS generated_candidate_count,
                cand.selected_candidate_id,
                cand.selected_candidate_url,
                COALESCE(runs.providers, '{{}}') AS providers
            FROM imageforge.image_requests r
            LEFT JOIN (
                SELECT
                    request_id,
                    COUNT(*) AS generated_candidate_count,
                    MAX(CASE WHEN is_selected THEN candidate_id END) AS selected_candidate_id,
                    MAX(CASE WHEN is_selected THEN public_url END) AS selected_candidate_url
                FROM imageforge.image_candidates
                GROUP BY request_id
            ) cand ON cand.request_id = r.request_id
            LEFT JOIN (
                SELECT
                    request_id,
                    ARRAY_AGG(DISTINCT provider ORDER BY provider) AS providers
                FROM imageforge.image_provider_runs
                GROUP BY request_id
            ) runs ON runs.request_id = r.request_id
            {where_clause}
            ORDER BY r.created_at DESC
            LIMIT %s OFFSET %s
        """
        values.extend([limit, offset])

        with self._connect() as conn:
            rows = conn.execute(query, values).fetchall()
            for row in rows:
                row["providers"] = row.get("providers") or []
            return rows

    def create_provider_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = """
            INSERT INTO imageforge.image_provider_runs (
                provider_run_id,
                request_id,
                provider,
                model,
                workflow_name,
                prompt_used,
                negative_prompt_used,
                latency_ms,
                ok,
                error_type,
                error_message,
                raw_response_json,
                status,
                stage,
                progress_pct,
                started_at,
                finished_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING *
        """
        with self._connect() as conn:
            return conn.execute(
                query,
                (
                    payload["provider_run_id"],
                    payload["request_id"],
                    payload["provider"],
                    payload.get("model"),
                    payload.get("workflow_name"),
                    payload["prompt_used"],
                    payload["negative_prompt_used"],
                    payload.get("latency_ms"),
                    payload["ok"],
                    payload.get("error_type"),
                    payload.get("error_message"),
                    Jsonb(payload["raw_response_json"])
                    if payload.get("raw_response_json") is not None
                    else None,
                    payload.get("status", "queued"),
                    payload.get("stage", "queued"),
                    payload.get("progress_pct", 0),
                    payload.get("started_at"),
                    payload.get("finished_at"),
                ),
            ).fetchone()

    def update_provider_run(
        self,
        provider_run_id: str,
        *,
        provider: str,
        model: str | None,
        workflow_name: str | None,
        prompt_used: str,
        negative_prompt_used: str,
        latency_ms: int | None,
        ok: bool,
        error_type: str | None,
        error_message: str | None,
        raw_response_json: dict[str, Any] | None,
        status: str,
        stage: str,
        progress_pct: int,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> dict[str, Any]:
        query = """
            UPDATE imageforge.image_provider_runs
            SET provider = %s,
                model = %s,
                workflow_name = %s,
                prompt_used = %s,
                negative_prompt_used = %s,
                latency_ms = %s,
                ok = %s,
                error_type = %s,
                error_message = %s,
                raw_response_json = %s,
                status = %s,
                stage = %s,
                progress_pct = %s,
                started_at = COALESCE(%s, started_at),
                finished_at = %s
            WHERE provider_run_id = %s
            RETURNING *
        """
        with self._connect() as conn:
            return conn.execute(
                query,
                (
                    provider,
                    model,
                    workflow_name,
                    prompt_used,
                    negative_prompt_used,
                    latency_ms,
                    ok,
                    error_type,
                    error_message,
                    Jsonb(raw_response_json) if raw_response_json is not None else None,
                    status,
                    stage,
                    progress_pct,
                    started_at,
                    finished_at,
                    provider_run_id,
                ),
            ).fetchone()

    def list_provider_runs(self, request_id: str) -> list[dict[str, Any]]:
        query = """
            SELECT *
            FROM imageforge.image_provider_runs
            WHERE request_id = %s
            ORDER BY created_at ASC
        """
        with self._connect() as conn:
            return conn.execute(query, (request_id,)).fetchall()

    def create_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = """
            INSERT INTO imageforge.image_candidates (
                candidate_id,
                request_id,
                provider_run_id,
                provider,
                model,
                candidate_index,
                prompt_used,
                negative_prompt_used,
                relative_path,
                absolute_path,
                public_url,
                storage_backend,
                file_size_bytes,
                width,
                height,
                quality_score,
                relevance_score,
                reason_codes,
                rank,
                is_selected
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING *
        """
        with self._connect() as conn:
            return conn.execute(
                query,
                (
                    payload["candidate_id"],
                    payload["request_id"],
                    payload["provider_run_id"],
                    payload["provider"],
                    payload.get("model"),
                    payload["candidate_index"],
                    payload["prompt_used"],
                    payload["negative_prompt_used"],
                    payload["relative_path"],
                    payload["absolute_path"],
                    payload["public_url"],
                    payload["storage_backend"],
                    payload.get("file_size_bytes"),
                    payload.get("width"),
                    payload.get("height"),
                    payload.get("quality_score"),
                    payload.get("relevance_score"),
                    Jsonb(payload.get("reason_codes") or []),
                    payload.get("rank"),
                    payload.get("is_selected", False),
                ),
            ).fetchone()

    def update_candidate_analysis(
        self,
        candidate_id: str,
        *,
        quality_score: float | None,
        relevance_score: float | None,
        reason_codes: list[str],
        rank: int | None,
    ) -> dict[str, Any]:
        query = """
            UPDATE imageforge.image_candidates
            SET quality_score = %s,
                relevance_score = %s,
                reason_codes = %s,
                rank = %s
            WHERE candidate_id = %s
            RETURNING *
        """
        with self._connect() as conn:
            return conn.execute(
                query,
                (
                    quality_score,
                    relevance_score,
                    Jsonb(reason_codes),
                    rank,
                    candidate_id,
                ),
            ).fetchone()

    def list_candidates(self, request_id: str) -> list[dict[str, Any]]:
        query = """
            SELECT *
            FROM imageforge.image_candidates
            WHERE request_id = %s
            ORDER BY rank ASC NULLS LAST, created_at ASC, candidate_index ASC
        """
        with self._connect() as conn:
            return conn.execute(query, (request_id,)).fetchall()

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        query = """
            SELECT *
            FROM imageforge.image_candidates
            WHERE candidate_id = %s
        """
        with self._connect() as conn:
            return conn.execute(query, (candidate_id,)).fetchone()

    def select_candidate(self, candidate_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            candidate = conn.execute(
                """
                SELECT *
                FROM imageforge.image_candidates
                WHERE candidate_id = %s
                """,
                (candidate_id,),
            ).fetchone()
            if candidate is None:
                raise NotFoundError(f"Candidate {candidate_id} was not found.")

            conn.execute(
                """
                UPDATE imageforge.image_candidates
                SET is_selected = false, selected_at = NULL
                WHERE request_id = %s
                """,
                (candidate["request_id"],),
            )
            conn.execute(
                """
                UPDATE imageforge.image_candidates
                SET is_selected = true, selected_at = NOW()
                WHERE candidate_id = %s
                """,
                (candidate_id,),
            )
            conn.execute(
                """
                UPDATE imageforge.image_prompt_history
                SET selected_candidate_id = %s
                WHERE request_id = %s
                  AND provider = %s
                """,
                (candidate_id, candidate["request_id"], candidate["provider"]),
            )
            return conn.execute(
                """
                SELECT *
                FROM imageforge.image_candidates
                WHERE candidate_id = %s
                """,
                (candidate_id,),
            ).fetchone()

    def create_prompt_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = """
            INSERT INTO imageforge.image_prompt_history (
                history_id,
                request_id,
                theme_name,
                theme_bucket,
                provider,
                model,
                prompt_used,
                negative_prompt_used,
                selected_candidate_id,
                quality_label
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING *
        """
        with self._connect() as conn:
            return conn.execute(
                query,
                (
                    payload["history_id"],
                    payload["request_id"],
                    payload["theme_name"],
                    payload["theme_bucket"],
                    payload["provider"],
                    payload.get("model"),
                    payload["prompt_used"],
                    payload["negative_prompt_used"],
                    payload.get("selected_candidate_id"),
                    payload.get("quality_label"),
                ),
            ).fetchone()

    def list_prompt_history(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        query = """
            SELECT *
            FROM imageforge.image_prompt_history
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        with self._connect() as conn:
            return conn.execute(query, (limit, offset)).fetchall()
