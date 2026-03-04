"""SQLite database for caching usage data."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Optional


DB_PATH = Path("severance.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    model TEXT,
    timestamp TEXT NOT NULL,
    granularity TEXT NOT NULL DEFAULT '1d',
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cached_tokens INTEGER DEFAULT 0,
    requests INTEGER DEFAULT 0,
    cost_usd REAL,
    raw_json TEXT,
    fetched_at TEXT NOT NULL,
    UNIQUE(provider, model, timestamp, granularity)
);

CREATE TABLE IF NOT EXISTS pricing (
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_per_mtok REAL NOT NULL,
    output_per_mtok REAL NOT NULL,
    cached_per_mtok REAL,
    effective_from TEXT NOT NULL,
    PRIMARY KEY(provider, model, effective_from)
);

CREATE INDEX IF NOT EXISTS idx_usage_provider_ts
    ON usage(provider, timestamp);

CREATE INDEX IF NOT EXISTS idx_usage_ts
    ON usage(timestamp);
"""


def init_db(path: Path | None = None) -> Path:
    """Create database and tables if they don't exist."""
    db = path or DB_PATH
    with get_conn(db) as conn:
        conn.executescript(SCHEMA)
    return db


@contextmanager
def get_conn(path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    db = path or DB_PATH
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_usage(
    conn: sqlite3.Connection,
    provider: str,
    model: Optional[str],
    timestamp: str,
    granularity: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_tokens: int = 0,
    requests: int = 0,
    cost_usd: Optional[float] = None,
    raw_json: Optional[dict] = None,
) -> None:
    """Insert or update a usage record."""
    conn.execute(
        """
        INSERT INTO usage
            (provider, model, timestamp, granularity,
             input_tokens, output_tokens, cached_tokens,
             requests, cost_usd, raw_json, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, model, timestamp, granularity)
        DO UPDATE SET
            input_tokens = excluded.input_tokens,
            output_tokens = excluded.output_tokens,
            cached_tokens = excluded.cached_tokens,
            requests = excluded.requests,
            cost_usd = excluded.cost_usd,
            raw_json = excluded.raw_json,
            fetched_at = excluded.fetched_at
        """,
        (
            provider,
            model,
            timestamp,
            granularity,
            input_tokens,
            output_tokens,
            cached_tokens,
            requests,
            cost_usd,
            json.dumps(raw_json) if raw_json else None,
            datetime.utcnow().isoformat(),
        ),
    )


def query_usage(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    provider: Optional[str] = None,
    group_by: str = "provider",
) -> list[dict[str, Any]]:
    """Query usage data within a time range."""
    if group_by == "model":
        select = "provider, model, "
        group = "provider, model"
    elif group_by == "provider":
        select = "provider, "
        group = "provider"
    else:
        select = ""
        group = ""

    where = "WHERE timestamp >= ? AND timestamp < ?"
    params: list[Any] = [start, end]

    if provider:
        where += " AND provider = ?"
        params.append(provider)

    sql = f"""
        SELECT
            {select}
            DATE(timestamp) as date,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(cached_tokens) as cached_tokens,
            SUM(requests) as requests,
            SUM(cost_usd) as cost_usd
        FROM usage
        {where}
        GROUP BY {group + ', ' if group else ''}DATE(timestamp)
        ORDER BY DATE(timestamp)
    """

    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_summary(
    conn: sqlite3.Connection,
    start: str,
    end: str,
) -> dict[str, Any]:
    """Get summary totals for a time range."""
    row = conn.execute(
        """
        SELECT
            SUM(input_tokens) as total_input_tokens,
            SUM(output_tokens) as total_output_tokens,
            SUM(cached_tokens) as total_cached_tokens,
            SUM(requests) as total_requests,
            SUM(cost_usd) as total_cost_usd,
            COUNT(DISTINCT provider) as provider_count,
            COUNT(DISTINCT model) as model_count
        FROM usage
        WHERE timestamp >= ? AND timestamp < ?
        """,
        (start, end),
    ).fetchone()
    return dict(row) if row else {}


def load_pricing(conn: sqlite3.Connection) -> dict[str, dict]:
    """Load all pricing data, keyed by provider/model."""
    rows = conn.execute(
        """
        SELECT provider, model, input_per_mtok, output_per_mtok,
               cached_per_mtok, effective_from
        FROM pricing
        ORDER BY effective_from DESC
        """
    ).fetchall()

    pricing = {}
    for r in rows:
        key = f"{r['provider']}/{r['model']}"
        if key not in pricing:  # Most recent first
            pricing[key] = dict(r)
    return pricing


def seed_pricing(conn: sqlite3.Connection, pricing_data: list[dict]) -> None:
    """Seed pricing table from models.json data."""
    for entry in pricing_data:
        conn.execute(
            """
            INSERT OR REPLACE INTO pricing
                (provider, model, input_per_mtok, output_per_mtok,
                 cached_per_mtok, effective_from)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry["provider"],
                entry["model"],
                entry["input_per_mtok"],
                entry["output_per_mtok"],
                entry.get("cached_per_mtok"),
                entry.get("effective_from", "2024-01-01"),
            ),
        )
