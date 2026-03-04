"""Abstract base provider for usage data fetching."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class UsageRecord:
    """Normalised usage record across all providers."""

    provider: str
    model: Optional[str]
    timestamp: str  # ISO 8601
    granularity: str  # "1m" | "1h" | "1d"
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    requests: int = 0
    cost_usd: Optional[float] = None
    raw: Optional[dict] = field(default=None, repr=False)


class BaseProvider(ABC):
    """Abstract base for usage data providers."""

    name: str = "unknown"

    @abstractmethod
    async def fetch_usage(
        self,
        start: datetime,
        end: datetime,
        granularity: str = "1d",
    ) -> list[UsageRecord]:
        """Fetch usage records for the given time range."""
        ...

    @abstractmethod
    async def is_configured(self) -> bool:
        """Check if this provider has valid configuration."""
        ...
