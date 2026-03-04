"""Background scheduler for periodic usage data refresh."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from severance.config import Config
from severance.db import get_conn, init_db, seed_pricing, upsert_usage, load_pricing
from severance.providers.base import UsageRecord
from severance.providers.anthropic_provider import AnthropicProvider
from severance.providers.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


def calculate_cost(record: UsageRecord, pricing: dict) -> float | None:
    """Calculate cost from token counts and pricing data."""
    if record.cost_usd is not None:
        return record.cost_usd

    if not record.model:
        return None

    key = f"{record.provider}/{record.model}"
    price = pricing.get(key)
    if not price:
        # Try without version suffix (e.g. "claude-sonnet-4-6-20260201" -> "claude-sonnet-4-6")
        for pkey, pval in pricing.items():
            if record.model.startswith(pval["model"]):
                price = pval
                break

    if not price:
        logger.debug(f"No pricing for {key}")
        return None

    input_cost = (record.input_tokens / 1_000_000) * price["input_per_mtok"]
    output_cost = (record.output_tokens / 1_000_000) * price["output_per_mtok"]
    cached_cost = 0
    if record.cached_tokens and price.get("cached_per_mtok"):
        cached_cost = (record.cached_tokens / 1_000_000) * price["cached_per_mtok"]

    return round(input_cost + output_cost + cached_cost, 6)


async def refresh_data(config: Config, days_back: int = 30) -> dict:
    """Fetch fresh data from all configured providers."""
    db_path = init_db()
    results = {"providers": {}, "total_records": 0}

    # Seed pricing data
    pricing_file = Path(__file__).parent / "pricing" / "models.json"
    if pricing_file.exists():
        with open(pricing_file) as f:
            pricing_data = json.load(f)
        with get_conn(db_path) as conn:
            seed_pricing(conn, pricing_data)

    # Load pricing for cost calculation
    with get_conn(db_path) as conn:
        pricing = load_pricing(conn)

    end = datetime.utcnow()
    start = end - timedelta(days=days_back)

    providers = []

    if "anthropic" in config.providers and config.providers["anthropic"].admin_api_key:
        providers.append(AnthropicProvider(config.providers["anthropic"]))

    if "openai" in config.providers and config.providers["openai"].admin_api_key:
        providers.append(OpenAIProvider(config.providers["openai"]))

    for provider in providers:
        if not await provider.is_configured():
            logger.info(f"Skipping {provider.name}: not configured")
            continue

        try:
            records = await provider.fetch_usage(
                start, end, config.refresh.default_granularity
            )

            # Calculate costs where missing
            for record in records:
                if record.cost_usd is None:
                    record.cost_usd = calculate_cost(record, pricing)

            # Store in database
            with get_conn(db_path) as conn:
                for record in records:
                    upsert_usage(
                        conn,
                        provider=record.provider,
                        model=record.model,
                        timestamp=record.timestamp,
                        granularity=record.granularity,
                        input_tokens=record.input_tokens,
                        output_tokens=record.output_tokens,
                        cached_tokens=record.cached_tokens,
                        requests=record.requests,
                        cost_usd=record.cost_usd,
                        raw_json=record.raw,
                    )

            results["providers"][provider.name] = {
                "records": len(records),
                "status": "ok",
            }
            results["total_records"] += len(records)
            logger.info(f"{provider.name}: stored {len(records)} records")

        except Exception as e:
            logger.error(f"{provider.name} refresh failed: {e}")
            results["providers"][provider.name] = {
                "records": 0,
                "status": f"error: {e}",
            }

    return results
