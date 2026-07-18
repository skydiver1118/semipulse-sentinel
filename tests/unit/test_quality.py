"""Fail-closed market-data quality tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
import pytest

from semipulse_sentinel.config import AppConfig
from semipulse_sentinel.providers.base import MarketData
from semipulse_sentinel.quality import PublicationBlocked, validate_market_data
from semipulse_sentinel.watchlist import WatchlistEntry
from tests.fixtures import (
    NEW_YORK,
    NOW,
    app_config,
    complete_market_data,
    make_market_data,
    market_data_factory,
    recovered_watchlist,
    without_symbol,
)

_FIXTURES = (
    app_config,
    complete_market_data,
    market_data_factory,
    recovered_watchlist,
)


def _replace_prices(data: MarketData, prices: pd.DataFrame) -> MarketData:
    return replace(data, prices=prices.reset_index(drop=True))


def _shift_symbol(
    data: MarketData,
    symbol: str,
    *,
    business_days: int,
) -> MarketData:
    prices = data.prices.copy()
    mask = prices["symbol"] == symbol
    prices.loc[mask, "date"] = prices.loc[mask, "date"] - pd.offsets.BDay(
        business_days
    )
    return _replace_prices(data, prices)


def test_quality_blocks_below_seventy_percent_coverage(
    market_data_factory: Callable[..., MarketData],
    app_config: AppConfig,
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> None:
    data = market_data_factory(covered_symbols=recovered_watchlist[:16])

    with pytest.raises(PublicationBlocked, match="coverage"):
        validate_market_data(data, app_config, recovered_watchlist, NOW)


def test_quality_names_optional_vix_without_blocking(
    complete_market_data: MarketData,
    app_config: AppConfig,
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> None:
    without_vix = without_symbol(complete_market_data, "^VIX")

    report = validate_market_data(
        without_vix, app_config, recovered_watchlist, NOW
    )

    assert "^VIX" in report.missing_optional
    assert report.publishable is True


def test_quality_exposes_exact_watchlist_denominator_and_ratio(
    market_data_factory: Callable[..., MarketData],
    app_config: AppConfig,
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> None:
    covered = (
        *recovered_watchlist[:15],
        recovered_watchlist[16],
        recovered_watchlist[17],
    )
    data = market_data_factory(
        covered_symbols=covered,
        include_required=True,
    )

    report = validate_market_data(data, app_config, recovered_watchlist, NOW)

    assert report.covered_symbols == tuple(entry.symbol for entry in covered)
    assert report.missing_symbols == tuple(
        entry.symbol for entry in recovered_watchlist if entry not in covered
    )
    assert report.covered_count == 17
    assert report.watchlist_count == 23
    assert report.coverage_ratio == Decimal(17) / Decimal(23)


def test_quality_requires_sixty_four_positive_adjusted_close_sessions(
    complete_market_data: MarketData,
    app_config: AppConfig,
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> None:
    prices = complete_market_data.prices.copy()
    assert len(prices.loc[prices["symbol"] == "AAOI"]) == 64
    aaoi_rows = prices.index[prices["symbol"] == "AAOI"]
    prices = prices.drop(aaoi_rows[0])

    report = validate_market_data(
        _replace_prices(complete_market_data, prices),
        app_config,
        recovered_watchlist,
        NOW,
    )

    assert "AAOI" in report.missing_symbols
    assert report.covered_count == 22


def test_quality_blocks_required_benchmark_with_only_sixty_three_sessions(
    complete_market_data: MarketData,
    app_config: AppConfig,
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> None:
    prices = complete_market_data.prices.copy()
    qqq_rows = prices.index[prices["symbol"] == "QQQ"]
    prices = prices.drop(qqq_rows[0])

    with pytest.raises(
        PublicationBlocked,
        match=r"required_benchmark_insufficient_history:QQQ",
    ):
        validate_market_data(
            _replace_prices(complete_market_data, prices),
            app_config,
            recovered_watchlist,
            NOW,
        )


def test_quality_blocks_when_a_required_benchmark_is_missing(
    complete_market_data: MarketData,
    app_config: AppConfig,
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> None:
    data = without_symbol(complete_market_data, "QQQ")

    with pytest.raises(
        PublicationBlocked, match=r"required_benchmark_missing:QQQ"
    ):
        validate_market_data(data, app_config, recovered_watchlist, NOW)


def test_quality_blocks_duplicate_symbol_dates(
    complete_market_data: MarketData,
    app_config: AppConfig,
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> None:
    duplicate = complete_market_data.prices.iloc[[0]]
    data = _replace_prices(
        complete_market_data,
        pd.concat([complete_market_data.prices, duplicate], ignore_index=True),
    )

    with pytest.raises(
        PublicationBlocked, match=r"duplicate_symbol_dates:AAOI"
    ):
        validate_market_data(data, app_config, recovered_watchlist, NOW)


@pytest.mark.parametrize("bad_value", [0.0, -1.0, float("nan"), float("inf")])
def test_quality_blocks_invalid_adjusted_prices_for_any_symbol(
    bad_value: float,
    complete_market_data: MarketData,
    app_config: AppConfig,
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> None:
    prices = complete_market_data.prices.copy()
    row = prices.index[prices["symbol"] == "AAOI"][0]
    prices.loc[row, "adj_close"] = bad_value

    with pytest.raises(
        PublicationBlocked, match=r"invalid_adjusted_prices:AAOI"
    ):
        validate_market_data(
            _replace_prices(complete_market_data, prices),
            app_config,
            recovered_watchlist,
            NOW,
        )


@pytest.mark.parametrize("unit_scale", [100.0, 0.01])
def test_quality_blocks_adjusted_price_unit_discontinuities(
    unit_scale: float,
    complete_market_data: MarketData,
    app_config: AppConfig,
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> None:
    prices = complete_market_data.prices.copy()
    aaoi_rows = prices.index[prices["symbol"] == "AAOI"]
    previous_row, latest_row = aaoi_rows[-2:]
    prices.loc[latest_row, "adj_close"] = (
        prices.loc[previous_row, "adj_close"] * unit_scale
    )

    with pytest.raises(
        PublicationBlocked,
        match=r"adjusted_price_unit_discontinuity:AAOI",
    ):
        validate_market_data(
            _replace_prices(complete_market_data, prices),
            app_config,
            recovered_watchlist,
            NOW,
        )


def test_quality_blocks_when_any_required_latest_bar_is_stale(
    complete_market_data: MarketData,
    app_config: AppConfig,
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> None:
    data = _shift_symbol(complete_market_data, "QQQ", business_days=1)

    with pytest.raises(
        PublicationBlocked, match=r"latest_required_bar_is_stale:QQQ"
    ):
        validate_market_data(data, app_config, recovered_watchlist, NOW)


def test_quality_excludes_and_names_stale_watchlist_symbols(
    complete_market_data: MarketData,
    app_config: AppConfig,
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> None:
    data = _shift_symbol(complete_market_data, "AAOI", business_days=1)

    report = validate_market_data(data, app_config, recovered_watchlist, NOW)

    assert report.stale_symbols == ("AAOI",)
    assert "AAOI" in report.missing_symbols
    assert "AAOI" not in report.covered_symbols
    assert report.covered_count == 22


@pytest.mark.parametrize(
    ("now", "expected_date"),
    [
        (datetime(2025, 7, 7, 16, 14, tzinfo=NEW_YORK), date(2025, 7, 4)),
        (datetime(2025, 7, 7, 16, 15, tzinfo=NEW_YORK), date(2025, 7, 7)),
        (datetime(2025, 7, 6, 18, 0, tzinfo=NEW_YORK), date(2025, 7, 4)),
    ],
)
def test_quality_uses_new_york_weekday_session_cutoff(
    now: datetime,
    expected_date: date,
    app_config: AppConfig,
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> None:
    data = make_market_data(recovered_watchlist, last_date=expected_date)

    report = validate_market_data(data, app_config, recovered_watchlist, now)

    assert report.publishable is True
    assert report.stale_symbols == ()


def test_quality_records_evaluation_age_and_expected_session_lag(
    app_config: AppConfig,
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> None:
    now = datetime(2025, 7, 6, 18, 0, tzinfo=NEW_YORK)
    data = make_market_data(recovered_watchlist, last_date=date(2025, 7, 4))

    report = validate_market_data(data, app_config, recovered_watchlist, now)

    assert report.evaluated_at == now
    assert report.calendar_age_days == 2
    assert report.expected_session_lag == 0


def test_quality_converts_aware_now_to_new_york(
    app_config: AppConfig,
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> None:
    data = make_market_data(recovered_watchlist, last_date=date(2025, 7, 2))
    now_utc = datetime(2025, 7, 2, 22, 0, tzinfo=UTC)

    report = validate_market_data(data, app_config, recovered_watchlist, now_utc)

    assert report.publishable is True


def test_quality_rejects_a_naive_clock(
    complete_market_data: MarketData,
    app_config: AppConfig,
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_market_data(
            complete_market_data,
            app_config,
            recovered_watchlist,
            datetime(2025, 7, 2, 18, 0),
        )


def test_quality_combines_all_fatal_reason_codes(
    complete_market_data: MarketData,
    app_config: AppConfig,
    recovered_watchlist: tuple[WatchlistEntry, ...],
) -> None:
    data = without_symbol(complete_market_data, "QQQ")
    required_watchlist_symbols = {"SMH", "SOXL", "SOXX"}
    kept_watchlist_symbols = {
        *(entry.symbol for entry in recovered_watchlist[:10]),
        *required_watchlist_symbols,
    }
    prices = data.prices.loc[
        data.prices["symbol"].isin(kept_watchlist_symbols)
    ].copy()
    prices = pd.concat([prices, prices.iloc[[0]]], ignore_index=True)

    with pytest.raises(PublicationBlocked) as error_info:
        validate_market_data(
            _replace_prices(data, prices), app_config, recovered_watchlist, NOW
        )

    assert str(error_info.value).split("; ") == [
        "required_benchmark_missing:QQQ",
        "watchlist_coverage_below_70_percent:13/23",
        "duplicate_symbol_dates:AAOI",
    ]
