"""Deterministic market-data fixtures shared by unit tests."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from semipulse_sentinel.config import AppConfig
from semipulse_sentinel.providers.base import MarketData
from semipulse_sentinel.watchlist import WatchlistEntry, load_watchlist

NEW_YORK = ZoneInfo("America/New_York")
NOW = datetime(2025, 7, 2, 18, 0, tzinfo=NEW_YORK)
LAST_DATE = NOW.date()


def _symbols(values: Iterable[str | WatchlistEntry]) -> tuple[str, ...]:
    return tuple(
        value.symbol if isinstance(value, WatchlistEntry) else value
        for value in values
    )


def make_market_data(
    covered_symbols: Sequence[str | WatchlistEntry],
    *,
    periods: int = 64,
    last_date: date = LAST_DATE,
    include_required: bool = True,
    include_optional: bool = True,
) -> MarketData:
    """Build valid, complete daily data for the requested symbols."""

    config = AppConfig()
    symbols = list(_symbols(covered_symbols))
    if include_required:
        symbols.extend(config.required_benchmarks)
    if include_optional:
        symbols.extend(config.optional_benchmarks)
    requested = tuple(dict.fromkeys(symbols))
    dates = pd.bdate_range(end=last_date, periods=periods, name="date")

    frames: list[pd.DataFrame] = []
    for offset, symbol in enumerate(requested, start=1):
        base = float(100 + offset)
        sequence = pd.Series(range(periods), dtype="float64")
        close = base + sequence / 10
        frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "symbol": symbol,
                    "open": close - 0.5,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close,
                    "adj_close": close + 0.25,
                    "volume": 1_000_000.0 + sequence,
                }
            )
        )

    prices = pd.concat(frames, ignore_index=True) if frames else empty_prices()
    return MarketData(
        prices=prices,
        fetched_at=NOW,
        provider="fixture",
        errors=(),
    )


def empty_prices() -> pd.DataFrame:
    """Return the stable normalized provider schema with no rows."""

    return pd.DataFrame(
        columns=[
            "date",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "adj_close",
            "volume",
        ]
    )


def without_symbol(data: MarketData, symbol: str) -> MarketData:
    """Return a fixture copy without one symbol."""

    return replace(
        data,
        prices=data.prices.loc[data.prices["symbol"] != symbol].copy(),
    )


@pytest.fixture
def app_config() -> AppConfig:
    return AppConfig()


@pytest.fixture
def recovered_watchlist() -> tuple[WatchlistEntry, ...]:
    path = Path(__file__).parents[1] / "config" / "watchlist.csv"
    return load_watchlist(path)


@pytest.fixture
def market_data_factory() -> Callable[..., MarketData]:
    def factory(
        covered_symbols: Sequence[str | WatchlistEntry],
        *,
        periods: int = 64,
        last_date: date = LAST_DATE,
        include_required: bool = False,
        include_optional: bool = False,
    ) -> MarketData:
        return make_market_data(
            covered_symbols,
            periods=periods,
            last_date=last_date,
            include_required=include_required,
            include_optional=include_optional,
        )

    return factory


@pytest.fixture
def complete_market_data(
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> MarketData:
    return make_market_data(recovered_watchlist)
