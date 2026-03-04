"""FastAPI server for the Severance dashboard."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from severance import __version__
from severance.auth import set_auth_config, verify_credentials
from severance.config import Config
from severance.db import get_conn, get_summary, init_db, query_usage

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Severance",
    description="Track what you pay the things replacing you.",
    version=__version__,
)

# Will be set during startup
_config: Config | None = None
_db_path: Path | None = None


def configure(config: Config) -> None:
    """Set up the app with configuration."""
    global _config, _db_path
    _config = config
    _db_path = init_db()
    set_auth_config(config.auth)


def _default_range() -> tuple[str, str]:
    """Current month start to now."""
    now = datetime.utcnow()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = now + timedelta(days=1)
    return start.strftime("%Y-%m-%dT00:00:00Z"), end.strftime("%Y-%m-%dT00:00:00Z")


def _parse_iso_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _prev_period_range(start: str, end: str) -> tuple[str, str]:
    """Return the previous period with matching duration."""
    start_dt = _parse_iso_utc(start)
    end_dt = _parse_iso_utc(end)
    if end_dt <= start_dt:
        raise ValueError("end must be after start")

    duration = end_dt - start_dt
    prev_end = start_dt
    prev_start = start_dt - duration
    return (
        prev_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        prev_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


# --- API Routes ---


@app.get("/api/summary")
async def api_summary(
    _user: Annotated[str, Depends(verify_credentials)],
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """Get summary totals and compare against the previous equal-length period."""
    if not start or not end:
        start, end = _default_range()

    with get_conn(_db_path) as conn:
        current = get_summary(conn, start, end)

    try:
        prev_start, prev_end = _prev_period_range(start, end)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    with get_conn(_db_path) as conn:
        previous = get_summary(conn, prev_start, prev_end)

    return {
        "period": {"start": start, "end": end},
        "current": current,
        "previous": previous,
    }


@app.get("/api/usage")
async def api_usage(
    _user: Annotated[str, Depends(verify_credentials)],
    start: Optional[str] = None,
    end: Optional[str] = None,
    provider: Optional[str] = None,
    group_by: str = Query(default="provider", pattern="^(provider|model)$"),
):
    """Get usage data grouped by provider or model."""
    if not start or not end:
        start, end = _default_range()

    with get_conn(_db_path) as conn:
        data = query_usage(conn, start, end, provider=provider, group_by=group_by)

    return {
        "period": {"start": start, "end": end},
        "group_by": group_by,
        "data": data,
    }


@app.get("/api/providers")
async def api_providers(
    _user: Annotated[str, Depends(verify_credentials)],
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """Get per-provider summary."""
    if not start or not end:
        start, end = _default_range()

    with get_conn(_db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                provider,
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens,
                SUM(cached_tokens) as cached_tokens,
                SUM(requests) as requests,
                SUM(cost_usd) as cost_usd,
                COUNT(DISTINCT model) as model_count
            FROM usage
            WHERE timestamp >= ? AND timestamp < ?
            GROUP BY provider
            ORDER BY cost_usd DESC
            """,
            (start, end),
        ).fetchall()

    return {
        "period": {"start": start, "end": end},
        "providers": [dict(r) for r in rows],
    }


@app.get("/api/models")
async def api_models(
    _user: Annotated[str, Depends(verify_credentials)],
    start: Optional[str] = None,
    end: Optional[str] = None,
    provider: Optional[str] = None,
):
    """Get per-model breakdown."""
    if not start or not end:
        start, end = _default_range()

    where = "WHERE timestamp >= ? AND timestamp < ? AND model IS NOT NULL AND model != '_total'"
    params = [start, end]
    if provider:
        where += " AND provider = ?"
        params.append(provider)

    with get_conn(_db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                provider,
                model,
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens,
                SUM(cached_tokens) as cached_tokens,
                SUM(requests) as requests,
                SUM(cost_usd) as cost_usd
            FROM usage
            {where}
            GROUP BY provider, model
            ORDER BY cost_usd DESC
            """,
            params,
        ).fetchall()

    return {
        "period": {"start": start, "end": end},
        "models": [dict(r) for r in rows],
    }


@app.post("/api/refresh")
async def api_refresh(
    _user: Annotated[str, Depends(verify_credentials)],
    days: int = Query(default=30, ge=1, le=365),
):
    """Trigger a manual data refresh."""
    from severance.scheduler import refresh_data

    if _config is None:
        return {"error": "Not configured"}

    results = await refresh_data(_config, days_back=days)
    return {"status": "ok", "results": results}


@app.get("/api/health")
async def api_health():
    """Health check (no auth required)."""
    return {"status": "ok", "version": __version__}


# --- Static files (dashboard) ---

STATIC_DIR = Path(__file__).parent.parent / "static"


@app.get("/")
async def index(_user: Annotated[str, Depends(verify_credentials)]):
    """Serve the dashboard."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file, media_type="text/html")
    return HTMLResponse(
        "<h1>Severance</h1><p>Dashboard not built yet. API is running.</p>"
    )


def mount_static():
    """Mount static files if directory exists."""
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
