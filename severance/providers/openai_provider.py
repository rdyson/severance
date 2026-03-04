"""OpenAI Usage + Costs API provider."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import httpx

from severance.config import ProviderConfig
from severance.providers.base import BaseProvider, UsageRecord

logger = logging.getLogger(__name__)

USAGE_URL = "https://api.openai.com/v1/organization/usage/completions"
COSTS_URL = "https://api.openai.com/v1/organization/costs"


class OpenAIProvider(BaseProvider):
    """Fetch usage data from the OpenAI Admin API.

    Requires an Admin API key from:
    platform.openai.com → Settings → Organization → Admin Keys

    Uses both the Usage endpoint (token counts) and Costs endpoint (dollar amounts).
    """

    name = "openai"

    def __init__(self, config: ProviderConfig):
        self.api_key = config.admin_api_key

    async def is_configured(self) -> bool:
        return bool(self.api_key)

    async def _paginated_get(
        self, client: httpx.AsyncClient, url: str, params: dict
    ) -> list[dict]:
        """Fetch all pages from a paginated OpenAI endpoint."""
        all_data = []
        page_cursor = None

        while True:
            if page_cursor:
                params["page"] = page_cursor

            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"OpenAI API error {e.response.status_code}: {e.response.text}")
                break
            except httpx.RequestError as e:
                logger.error(f"OpenAI request failed: {e}")
                break

            all_data.extend(data.get("data", []))
            page_cursor = data.get("next_page")
            if not page_cursor:
                break

        return all_data

    async def fetch_usage(
        self,
        start: datetime,
        end: datetime,
        granularity: str = "1d",
    ) -> list[UsageRecord]:
        if not await self.is_configured():
            logger.warning("OpenAI provider not configured, skipping")
            return []

        records: list[UsageRecord] = []
        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            # Fetch token usage (grouped by model)
            usage_params = {
                "start_time": start_ts,
                "end_time": end_ts,
                "bucket_width": granularity,
                "group_by[]": "model",
                "limit": 31,
            }

            usage_buckets = await self._paginated_get(client, USAGE_URL, usage_params)

            for bucket in usage_buckets:
                bucket_ts = bucket.get("start_time", 0)
                ts_str = datetime.utcfromtimestamp(bucket_ts).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

                for result in bucket.get("results", []):
                    model = result.get("model")
                    records.append(
                        UsageRecord(
                            provider="openai",
                            model=model,
                            timestamp=ts_str,
                            granularity=granularity,
                            input_tokens=result.get("input_tokens", 0),
                            output_tokens=result.get("output_tokens", 0),
                            cached_tokens=result.get("input_cached_tokens", 0),
                            requests=result.get("num_model_requests", 0),
                            cost_usd=None,  # Will try to fill from Costs API
                            raw=result,
                        )
                    )

            # Fetch costs (direct dollar amounts)
            costs_params = {
                "start_time": start_ts,
                "end_time": end_ts,
                "bucket_width": "1d",
                "limit": 31,
            }

            cost_buckets = await self._paginated_get(client, COSTS_URL, costs_params)

            # Build a cost lookup by date
            daily_costs: dict[str, float] = {}
            for bucket in cost_buckets:
                bucket_ts = bucket.get("start_time", 0)
                date_key = datetime.utcfromtimestamp(bucket_ts).strftime("%Y-%m-%d")
                for result in bucket.get("results", []):
                    amount = result.get("amount", {})
                    if isinstance(amount, dict):
                        raw_cost = amount.get("value", 0)
                    else:
                        raw_cost = amount or 0
                    try:
                        cost = float(raw_cost)
                    except (TypeError, ValueError):
                        logger.warning(
                            "OpenAI costs payload had non-numeric amount: %r", raw_cost
                        )
                        cost = 0.0
                    daily_costs[date_key] = daily_costs.get(date_key, 0) + cost

            # Distribute official daily cost totals across model records by date.
            # This avoids double counting while still giving per-model visibility.
            records_by_date: dict[str, list[UsageRecord]] = {}
            for record in records:
                records_by_date.setdefault(record.timestamp[:10], []).append(record)

            for date_key, total_cost in daily_costs.items():
                date_records = records_by_date.get(date_key, [])
                if not date_records:
                    records.append(
                        UsageRecord(
                            provider="openai",
                            model="_total",
                            timestamp=f"{date_key}T00:00:00Z",
                            granularity="1d",
                            cost_usd=total_cost,
                        )
                    )
                    continue

                weights = [
                    max(
                        0,
                        r.input_tokens + r.output_tokens + r.cached_tokens,
                    )
                    for r in date_records
                ]
                total_weight = sum(weights)

                if total_weight == 0:
                    weights = [max(0, r.requests) for r in date_records]
                    total_weight = sum(weights)

                if total_weight == 0:
                    share = round(total_cost / len(date_records), 6) if date_records else 0.0
                    for r in date_records:
                        r.cost_usd = share
                    if date_records:
                        assigned = share * len(date_records)
                        date_records[-1].cost_usd = round(
                            (date_records[-1].cost_usd or 0.0) + (total_cost - assigned), 6
                        )
                    continue

                running = 0.0
                for idx, r in enumerate(date_records):
                    if idx == len(date_records) - 1:
                        r.cost_usd = round(total_cost - running, 6)
                    else:
                        portion = total_cost * (weights[idx] / total_weight)
                        r.cost_usd = round(portion, 6)
                        running += r.cost_usd

        logger.info(f"OpenAI: fetched {len(records)} usage records, {len(daily_costs)} cost days")

        return records
