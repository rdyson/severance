"""Anthropic Usage API provider."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import httpx

from severance.config import ProviderConfig
from severance.providers.base import BaseProvider, UsageRecord

logger = logging.getLogger(__name__)

API_BASE = "https://api.anthropic.com/v1/organizations/usage_report/messages"


class AnthropicProvider(BaseProvider):
    """Fetch usage data from the Anthropic Admin API.

    Requires an Admin API key (sk-ant-admin-...).
    Returns token counts only — costs must be calculated from pricing data.
    """

    name = "anthropic"

    def __init__(self, config: ProviderConfig):
        self.api_key = config.admin_api_key

    @staticmethod
    def _normalize_bucket_timestamp(bucket: dict) -> str:
        """Return a normalized UTC timestamp string for a usage bucket."""
        raw = (
            bucket.get("start_time")
            or bucket.get("starting_at")
            or bucket.get("bucket_start")
            or ""
        )
        if not raw:
            return ""
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return str(raw)

    @staticmethod
    def _to_int(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    async def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.startswith("sk-ant-admin"))

    async def fetch_usage(
        self,
        start: datetime,
        end: datetime,
        granularity: str = "1d",
    ) -> list[UsageRecord]:
        if not await self.is_configured():
            logger.warning("Anthropic provider not configured, skipping")
            return []

        records: list[UsageRecord] = []

        params = {
            "starting_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ending_at": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bucket_width": granularity,
            "group_by[]": "model",
        }

        headers = {
            "anthropic-version": "2023-06-01",
            "x-api-key": self.api_key,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(API_BASE, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Anthropic API error {e.response.status_code}: {e.response.text}")
                return []
            except httpx.RequestError as e:
                logger.error(f"Anthropic request failed: {e}")
                return []

        for bucket in data.get("data", []):
            bucket_ts = self._normalize_bucket_timestamp(bucket)
            if not bucket_ts:
                logger.warning("Anthropic bucket missing timestamp: %r", bucket)
                continue
            for result in bucket.get("results", []):
                model = result.get("model")
                # Anthropic Usage API uses uncached/cache fields rather than a single
                # "input_tokens" value.
                input_tokens = self._to_int(result.get("uncached_input_tokens"))
                output_tokens = self._to_int(result.get("output_tokens"))
                cached_read = self._to_int(result.get("cache_read_input_tokens"))

                cache_creation_raw = result.get("cache_creation")
                if isinstance(cache_creation_raw, dict):
                    cache_creation = sum(
                        self._to_int(v) for v in cache_creation_raw.values()
                    )
                else:
                    cache_creation = self._to_int(
                        result.get("cache_creation_input_tokens")
                        or result.get("cache_creation_tokens")
                        or cache_creation_raw
                    )

                records.append(
                    UsageRecord(
                        provider="anthropic",
                        model=model,
                        timestamp=bucket_ts,
                        granularity=granularity,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cached_tokens=cached_read + cache_creation,
                        requests=self._to_int(
                            result.get("num_requests")
                            or result.get("request_count")
                            or result.get("requests")
                        ),
                        cost_usd=None,  # Calculated later from pricing
                        raw=result,
                    )
                )

        logger.info(f"Anthropic: fetched {len(records)} records")
        return records
