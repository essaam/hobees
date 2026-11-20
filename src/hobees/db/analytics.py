"""Fast SQL aggregations for real-time and historic usage insights (FR-6).

Queries use the configured database. The stats command provides aggregate
tables; the API exposes aggregates and live usage events over SSE.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import text

from hobees.db.session import session_scope

Window = Literal["1h", "24h", "7d", "all"]

_WINDOW_DELTA: dict[Window, timedelta | None] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "all": None,
}


def _get_db_type(engine) -> str:
    """Get database dialect name."""
    return engine.dialect.name


def active_runs() -> list[dict]:
    """Runs currently in progress."""
    with session_scope() as session:
        engine = session.bind
        db_type = _get_db_type(engine)
        
        if db_type == "sqlite":
            sql = """
                SELECT id, thread_id, hive_id, mode, goal, status, started_at
                FROM runs
                WHERE status = 'running'
                ORDER BY started_at DESC
            """
        else:
            sql = """
                SELECT id, thread_id, hive_id, mode, goal, status, started_at
                FROM runs
                WHERE status = 'running'
                ORDER BY started_at DESC
            """
        rows = session.execute(text(sql)).mappings()
        return [dict(r) for r in rows]


def summary(window: Window = "all", group_by: Literal["bee", "hive", "provider", "day"] = "bee") -> list[dict]:
    """Aggregated token/cost/latency insights over a time window."""
    delta = _WINDOW_DELTA[window]
    with session_scope() as session:
        engine = session.bind
        db_type = _get_db_type(engine)
        
        where = ""
        params: dict = {}
        if delta is not None:
            where = "WHERE created_at >= :since"
            params["since"] = datetime.now(timezone.utc) - delta
        
        if group_by == "day":
            if db_type == "sqlite":
                sql = """
                    SELECT date(created_at) AS day,
                           count(*) AS events,
                           sum(input_tokens) AS input_tokens,
                           sum(output_tokens) AS output_tokens,
                           round(sum(estimated_cost_usd), 6) AS estimated_cost_usd,
                           round(avg(latency_ms)) AS avg_latency_ms
                    FROM usage_events
                    {where}
                    GROUP BY day
                    ORDER BY day DESC
                """
            else:
                sql = """
                    SELECT date_trunc('day', created_at) AS day,
                           count(*) AS events,
                           sum(input_tokens) AS input_tokens,
                           sum(output_tokens) AS output_tokens,
                           round(sum(estimated_cost_usd)::numeric, 6) AS estimated_cost_usd,
                           round(avg(latency_ms))::float AS avg_latency_ms
                    FROM usage_events
                    {where}
                    GROUP BY 1
                    ORDER BY 1 DESC
                """
        elif group_by == "bee":
            if db_type == "sqlite":
                sql = """
                    SELECT bee_name AS key,
                           count(*) AS events,
                           sum(input_tokens) AS input_tokens,
                           sum(output_tokens) AS output_tokens,
                           round(sum(estimated_cost_usd), 6) AS estimated_cost_usd,
                           round(avg(latency_ms)) AS avg_latency_ms
                    FROM usage_events
                    {where}
                    GROUP BY bee_name
                    ORDER BY estimated_cost_usd DESC
                """
            else:
                sql = """
                    SELECT bee_name AS key,
                           count(*) AS events,
                           sum(input_tokens) AS input_tokens,
                           sum(output_tokens) AS output_tokens,
                           round(sum(estimated_cost_usd)::numeric, 6) AS estimated_cost_usd,
                           round(avg(latency_ms))::float AS avg_latency_ms
                    FROM usage_events
                    {where}
                    GROUP BY 1
                    ORDER BY estimated_cost_usd DESC NULLS LAST
                """
        elif group_by == "provider":
            if db_type == "sqlite":
                sql = """
                    SELECT provider_alias AS key,
                           count(*) AS events,
                           sum(input_tokens) AS input_tokens,
                           sum(output_tokens) AS output_tokens,
                           round(sum(estimated_cost_usd), 6) AS estimated_cost_usd,
                           round(avg(latency_ms)) AS avg_latency_ms
                    FROM usage_events
                    {where}
                    GROUP BY provider_alias
                    ORDER BY estimated_cost_usd DESC
                """
            else:
                sql = """
                    SELECT provider_alias AS key,
                           count(*) AS events,
                           sum(input_tokens) AS input_tokens,
                           sum(output_tokens) AS output_tokens,
                           round(sum(estimated_cost_usd)::numeric, 6) AS estimated_cost_usd,
                           round(avg(latency_ms))::float AS avg_latency_ms
                    FROM usage_events
                    {where}
                    GROUP BY 1
                    ORDER BY estimated_cost_usd DESC NULLS LAST
                """
        else:  # hive — via runs join
            if db_type == "sqlite":
                sql = """
                    SELECT coalesce(r.hive_id, '(no hive)') AS key,
                           count(*) AS events,
                           sum(input_tokens) AS input_tokens,
                           sum(output_tokens) AS output_tokens,
                           round(sum(estimated_cost_usd), 6) AS estimated_cost_usd,
                           round(avg(latency_ms)) AS avg_latency_ms
                    FROM usage_events ue
                    LEFT JOIN runs r ON r.id = ue.run_id
                    {where}
                    GROUP BY key
                    ORDER BY estimated_cost_usd DESC
                """
            else:
                sql = """
                    SELECT coalesce(r.hive_id::text, '(no hive)') AS key,
                           count(*) AS events,
                           sum(input_tokens) AS input_tokens,
                           sum(output_tokens) AS output_tokens,
                           round(sum(estimated_cost_usd)::numeric, 6) AS estimated_cost_usd,
                           round(avg(latency_ms))::float AS avg_latency_ms
                    FROM usage_events ue
                    LEFT JOIN runs r ON r.id = ue.run_id
                    {where}
                    GROUP BY 1
                    ORDER BY estimated_cost_usd DESC NULLS LAST
                """
        rows = session.execute(text(sql.format(where=where)), params).mappings()
        return [dict(r) for r in rows]


def recent_events(limit: int = 20) -> list[dict]:
    """Most recent usage events (for live tickers)."""
    with session_scope() as session:
        rows = session.execute(
            text(
                """
                SELECT created_at, thread_id, bee_name, provider_alias, model_name,
                       input_tokens, output_tokens, estimated_cost_usd, latency_ms
                FROM usage_events
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings()
        return [dict(r) for r in rows]


def run_thread_usage(thread_id: str) -> dict:
    """Telemetry footer totals for a single session thread."""
    with session_scope() as session:
        engine = session.bind
        db_type = _get_db_type(engine)
        
        if db_type == "sqlite":
            sql = """
                SELECT count(*) AS events,
                       sum(input_tokens) AS input_tokens,
                       sum(output_tokens) AS output_tokens,
                       round(sum(estimated_cost_usd), 6) AS estimated_cost_usd,
                       max(created_at) AS last_event
                FROM usage_events
                WHERE thread_id = :thread_id
            """
        else:
            sql = """
                SELECT count(*) AS events,
                       sum(input_tokens) AS input_tokens,
                       sum(output_tokens) AS output_tokens,
                       round(sum(estimated_cost_usd)::numeric, 6) AS estimated_cost_usd,
                       max(created_at) AS last_event
                FROM usage_events
                WHERE thread_id = :thread_id
            """
        row = session.execute(text(sql), {"thread_id": thread_id}).mappings().first()
        return dict(row) if row else {}


__all__ = ["active_runs", "summary", "recent_events", "run_thread_usage", "Window"]