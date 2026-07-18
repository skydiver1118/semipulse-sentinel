"""Provider-neutral market-data contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

import pandas as pd  # type: ignore[import-untyped]

NORMALIZED_COLUMNS: tuple[str, ...] = (
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
)


@dataclass(frozen=True, slots=True)
class SymbolError:
    """A sanitized provider problem associated with one requested symbol."""

    symbol: str
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class MarketData:
    """Normalized daily prices returned by a provider boundary."""

    prices: pd.DataFrame
    fetched_at: datetime
    provider: str
    errors: tuple[SymbolError, ...]


class MarketDataProvider(Protocol):
    """Protocol implemented by runtime market-data adapters."""

    def fetch(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
    ) -> MarketData:
        """Fetch normalized daily prices for a combined symbol set."""
