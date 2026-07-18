"""Fail-closed validation for normalized daily market data."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from semipulse_sentinel.config import AppConfig
from semipulse_sentinel.models import QualityReport
from semipulse_sentinel.providers.base import NORMALIZED_COLUMNS, MarketData
from semipulse_sentinel.watchlist import WatchlistEntry

MINIMUM_COVERAGE_SESSIONS = 64
_SESSION_CLOSE_BUFFER = time(16, 15)
_UNIT_MIXUP_RATIO_MIN = 90.0
_UNIT_MIXUP_RATIO_MAX = 110.0


class PublicationBlocked(RuntimeError):
    """Raised when market data is unsafe to publish."""


def _previous_weekday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _expected_session(now: datetime, timezone_name: str) -> date:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    local_now = now.astimezone(ZoneInfo(timezone_name))
    if local_now.weekday() >= 5:
        candidate = local_now.date()
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate
    if local_now.time().replace(tzinfo=None) < _SESSION_CLOSE_BUFFER:
        return _previous_weekday(local_now.date())
    return local_now.date()


def _weekday_session_lag(actual: date, expected: date) -> int:
    """Count expected weekday sessions after ``actual`` through ``expected``."""

    if actual >= expected:
        return 0
    lag = 0
    candidate = actual + timedelta(days=1)
    while candidate <= expected:
        if candidate.weekday() < 5:
            lag += 1
        candidate += timedelta(days=1)
    return lag


def _ordered_universe(
    watchlist: tuple[WatchlistEntry, ...],
    config: AppConfig,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            [
                *(entry.symbol for entry in watchlist),
                *config.required_benchmarks,
                *config.optional_benchmarks,
            ]
        )
    )


def _market_dates(values: pd.Series) -> pd.Series:
    dates = pd.to_datetime(values, errors="coerce")
    if isinstance(dates.dtype, pd.DatetimeTZDtype):
        dates = dates.dt.tz_localize(None)
    return dates.dt.normalize()


def _reason(code: str, symbols: tuple[str, ...]) -> str:
    return f"{code}:{','.join(symbols)}"


def validate_market_data(
    data: MarketData,
    config: AppConfig,
    watchlist: tuple[WatchlistEntry, ...],
    now: datetime,
) -> QualityReport:
    """Validate coverage, price integrity, uniqueness, and freshness.

    Freshness intentionally uses weekdays rather than an exchange-holiday
    calendar. The conservative heuristic expects a same-day bar at 16:15 New
    York time and the prior weekday before then.
    """

    if not watchlist:
        raise ValueError("watchlist must not be empty")
    report_timezone = ZoneInfo(config.timezone)
    local_now = now.astimezone(report_timezone)
    expected_session = _expected_session(now, config.timezone)
    missing_columns = tuple(
        column for column in NORMALIZED_COLUMNS if column not in data.prices
    )
    if missing_columns:
        raise PublicationBlocked(
            f"invalid_market_data_schema:{','.join(missing_columns)}"
        )

    universe = _ordered_universe(watchlist, config)
    rank = {symbol: position for position, symbol in enumerate(universe)}
    prices = data.prices.loc[:, list(NORMALIZED_COLUMNS)].copy()
    prices["symbol"] = prices["symbol"].astype(str).str.strip().str.upper()
    prices = prices.loc[prices["symbol"].isin(universe)].copy()
    prices["date"] = _market_dates(prices["date"])
    prices["adj_close"] = pd.to_numeric(prices["adj_close"], errors="coerce")

    invalid_date_symbols = tuple(
        sorted(
            set(prices.loc[prices["date"].isna(), "symbol"]),
            key=rank.__getitem__,
        )
    )
    valid_dates = prices.loc[prices["date"].notna()].copy()
    duplicate_symbols = tuple(
        sorted(
            set(
                valid_dates.loc[
                    valid_dates.duplicated(["symbol", "date"], keep=False),
                    "symbol",
                ]
            ),
            key=rank.__getitem__,
        )
    )
    invalid_price_mask = ~np.isfinite(valid_dates["adj_close"]) | (
        valid_dates["adj_close"] <= 0
    )
    invalid_price_symbols = tuple(
        sorted(
            set(valid_dates.loc[invalid_price_mask, "symbol"]),
            key=rank.__getitem__,
        )
    )
    eligible_price_rows = valid_dates.loc[
        ~invalid_price_mask, ["symbol", "date", "adj_close"]
    ].sort_values(["symbol", "date"], kind="stable")
    previous_adjusted_close = eligible_price_rows.groupby(
        "symbol", sort=False
    )["adj_close"].shift()
    adjusted_close_ratio = (
        eligible_price_rows["adj_close"] / previous_adjusted_close
    )
    reciprocal_min = 1.0 / _UNIT_MIXUP_RATIO_MAX
    reciprocal_max = 1.0 / _UNIT_MIXUP_RATIO_MIN
    unit_discontinuity_mask = adjusted_close_ratio.between(
        _UNIT_MIXUP_RATIO_MIN,
        _UNIT_MIXUP_RATIO_MAX,
        inclusive="both",
    ) | adjusted_close_ratio.between(
        reciprocal_min,
        reciprocal_max,
        inclusive="both",
    )
    unit_discontinuity_symbols = tuple(
        sorted(
            set(
                eligible_price_rows.loc[unit_discontinuity_mask, "symbol"]
            ),
            key=rank.__getitem__,
        )
    )

    latest_dates = valid_dates.groupby("symbol", sort=False)["date"].max()
    present = set(latest_dates.index)
    stale_symbols = tuple(
        symbol
        for symbol in universe
        if symbol in present
        and latest_dates[symbol].date() < expected_session
    )
    future_symbols = tuple(
        symbol
        for symbol in universe
        if symbol in present
        and latest_dates[symbol].date() > expected_session
    )
    missing_required = tuple(
        symbol for symbol in config.required_benchmarks if symbol not in present
    )
    missing_optional = tuple(
        symbol for symbol in config.optional_benchmarks if symbol not in present
    )

    stale_set = set(stale_symbols)
    invalid_set = set(invalid_price_symbols)
    unit_discontinuity_set = set(unit_discontinuity_symbols)
    future_set = set(future_symbols)
    coverage_counts = (
        eligible_price_rows.groupby("symbol", sort=False)["date"]
        .nunique()
    )
    insufficient_required = tuple(
        symbol
        for symbol in config.required_benchmarks
        if symbol in present
        and coverage_counts.get(symbol, 0) < MINIMUM_COVERAGE_SESSIONS
    )
    watchlist_symbols = tuple(entry.symbol for entry in watchlist)
    covered_symbols = tuple(
        symbol
        for symbol in watchlist_symbols
        if coverage_counts.get(symbol, 0) >= MINIMUM_COVERAGE_SESSIONS
        and symbol not in stale_set
        and symbol not in invalid_set
        and symbol not in unit_discontinuity_set
        and symbol not in future_set
    )
    covered_set = set(covered_symbols)
    missing_symbols = tuple(
        symbol for symbol in watchlist_symbols if symbol not in covered_set
    )
    covered_count = len(covered_symbols)
    watchlist_count = len(watchlist_symbols)
    coverage_ratio = Decimal(covered_count) / Decimal(watchlist_count)

    reason_codes: list[str] = []
    if missing_required:
        reason_codes.append(_reason("required_benchmark_missing", missing_required))
    if insufficient_required:
        reason_codes.append(
            _reason(
                "required_benchmark_insufficient_history",
                insufficient_required,
            )
        )
    if coverage_ratio < Decimal("0.70"):
        reason_codes.append(
            "watchlist_coverage_below_70_percent:"
            f"{covered_count}/{watchlist_count}"
        )
    if duplicate_symbols:
        reason_codes.append(
            _reason("duplicate_symbol_dates", duplicate_symbols)
        )
    if invalid_price_symbols:
        reason_codes.append(
            _reason("invalid_adjusted_prices", invalid_price_symbols)
        )
    if unit_discontinuity_symbols:
        reason_codes.append(
            _reason(
                "adjusted_price_unit_discontinuity",
                unit_discontinuity_symbols,
            )
        )
    stale_required = tuple(
        symbol for symbol in config.required_benchmarks if symbol in stale_set
    )
    if stale_required:
        reason_codes.append(
            _reason("latest_required_bar_is_stale", stale_required)
        )
    if invalid_date_symbols:
        reason_codes.append(
            _reason("invalid_market_data_dates", invalid_date_symbols)
        )
    if future_symbols:
        reason_codes.append(_reason("future_market_data", future_symbols))
    if reason_codes:
        raise PublicationBlocked("; ".join(reason_codes))

    warnings: list[str] = []
    if missing_optional:
        warnings.append(_reason("optional_benchmark_missing", missing_optional))
    stale_nonrequired = tuple(
        symbol for symbol in stale_symbols if symbol not in config.required_benchmarks
    )
    if stale_nonrequired:
        warnings.append(_reason("stale_symbols", stale_nonrequired))
    if missing_symbols:
        warnings.append(_reason("watchlist_symbols_unavailable", missing_symbols))
    warnings.extend(
        f"provider_error:{error.symbol}:{error.code}" for error in data.errors
    )

    latest = valid_dates["date"].max()
    as_of_date = latest.date() if not pd.isna(latest) else expected_session
    return QualityReport(
        as_of=datetime.combine(as_of_date, time.min, tzinfo=report_timezone),
        covered_symbols=covered_symbols,
        missing_symbols=missing_symbols,
        stale_symbols=stale_symbols,
        missing_required=missing_required,
        missing_optional=missing_optional,
        covered_count=covered_count,
        watchlist_count=watchlist_count,
        coverage_ratio=coverage_ratio,
        publishable=True,
        warnings=tuple(warnings),
        evaluated_at=local_now,
        calendar_age_days=max((local_now.date() - as_of_date).days, 0),
        expected_session_lag=_weekday_session_lag(as_of_date, expected_session),
    )
