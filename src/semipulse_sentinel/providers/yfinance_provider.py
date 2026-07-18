"""Yahoo Finance adapter and normalization boundary."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pandas as pd  # type: ignore[import-untyped]
import yfinance as yf  # type: ignore[import-untyped]

from semipulse_sentinel.providers.base import (
    NORMALIZED_COLUMNS,
    MarketData,
    SymbolError,
)

_DOWNLOAD_OPTIONS: dict[str, object] = {
    "period": "2y",
    "interval": "1d",
    "auto_adjust": False,
    "actions": False,
    "group_by": "column",
    "threads": True,
    "repair": True,
    "timeout": 30,
}
_FIELD_NAMES = {
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "adj close": "adj_close",
    "adj_close": "adj_close",
    "volume": "volume",
}
_VALUE_COLUMNS = NORMALIZED_COLUMNS[2:]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _empty_prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="datetime64[ns]"),
            "symbol": pd.Series(dtype="string"),
            "open": pd.Series(dtype="float64"),
            "high": pd.Series(dtype="float64"),
            "low": pd.Series(dtype="float64"),
            "close": pd.Series(dtype="float64"),
            "adj_close": pd.Series(dtype="float64"),
            "volume": pd.Series(dtype="float64"),
        }
    )


def _canonical_field(value: object) -> str | None:
    normalized = " ".join(str(value).strip().lower().split())
    return _FIELD_NAMES.get(normalized)


def _requested_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip())
    )


def _date_index(index: pd.Index) -> pd.DatetimeIndex:
    dates = pd.DatetimeIndex(pd.to_datetime(index, errors="coerce"))
    if dates.tz is not None:
        dates = dates.tz_localize(None)
    return dates.normalize()


def _tidy_symbol_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
) -> tuple[pd.DataFrame | None, SymbolError | None]:
    renamed: dict[object, str] = {}
    for column in frame.columns:
        canonical = _canonical_field(column)
        if canonical is not None and canonical not in renamed.values():
            renamed[column] = canonical
    available = frame.rename(columns=renamed)
    if "adj_close" not in available.columns:
        return None, SymbolError(
            symbol=symbol,
            code="symbol_unavailable",
            detail="adjusted close unavailable",
        )
    adjusted_close = pd.to_numeric(available["adj_close"], errors="coerce")
    if not adjusted_close.notna().any():
        return None, SymbolError(
            symbol=symbol,
            code="symbol_unavailable",
            detail="adjusted close unavailable",
        )

    dates = _date_index(available.index)
    tidy = pd.DataFrame({"date": dates, "symbol": symbol})
    source_has_market_value = pd.Series(False, index=available.index)
    for column in _VALUE_COLUMNS:
        if column in available.columns:
            source_values = available[column]
            source_has_market_value |= source_values.notna()
            values = pd.to_numeric(source_values, errors="coerce")
            tidy[column] = values.to_numpy()
        else:
            tidy[column] = float("nan")
    has_market_value = source_has_market_value.to_numpy(dtype=bool)
    tidy = tidy.loc[
        tidy["date"].notna() & has_market_value,
        list(NORMALIZED_COLUMNS),
    ]
    return tidy, None


def _field_and_symbol_levels(columns: pd.MultiIndex) -> tuple[int, int] | None:
    if columns.nlevels != 2:
        return None
    scores = [
        sum(_canonical_field(value) is not None for value in columns.levels[level])
        for level in range(2)
    ]
    field_level = max(range(2), key=scores.__getitem__)
    if scores[field_level] == 0:
        return None
    return field_level, 1 - field_level


def _normalize_multilevel(
    frame: pd.DataFrame,
    requested: tuple[str, ...],
) -> tuple[list[pd.DataFrame], list[SymbolError]]:
    levels = _field_and_symbol_levels(frame.columns)
    if levels is None:
        return [], [
            SymbolError(symbol, "invalid_response", "unsupported column layout")
            for symbol in requested
        ]
    field_level, symbol_level = levels
    labels = {
        str(value).strip().upper(): value
        for value in frame.columns.get_level_values(symbol_level).unique()
    }
    normalized: list[pd.DataFrame] = []
    errors: list[SymbolError] = []
    for symbol in requested:
        label = labels.get(symbol)
        if label is None:
            errors.append(
                SymbolError(symbol, "symbol_unavailable", "no rows returned")
            )
            continue
        symbol_frame = frame.xs(label, axis="columns", level=symbol_level)
        if isinstance(symbol_frame.columns, pd.MultiIndex):
            symbol_frame.columns = symbol_frame.columns.get_level_values(field_level)
        tidy, error = _tidy_symbol_frame(symbol_frame, symbol=symbol)
        if error is not None:
            errors.append(error)
        elif tidy is not None:
            normalized.append(tidy)
    return normalized, errors


def _normalize_plain(
    frame: pd.DataFrame,
    requested: tuple[str, ...],
) -> tuple[list[pd.DataFrame], list[SymbolError]]:
    if len(requested) != 1:
        return [], [
            SymbolError(symbol, "invalid_response", "ambiguous single-symbol layout")
            for symbol in requested
        ]
    tidy, error = _tidy_symbol_frame(frame, symbol=requested[0])
    if error is not None:
        return [], [error]
    return ([tidy] if tidy is not None else []), []


def _normalize_download(
    frame: object,
    requested: tuple[str, ...],
    start: date,
    end: date,
) -> tuple[pd.DataFrame, tuple[SymbolError, ...]]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return _empty_prices(), tuple(
            SymbolError(symbol, "symbol_unavailable", "no rows returned")
            for symbol in requested
        )

    if isinstance(frame.columns, pd.MultiIndex):
        normalized, errors = _normalize_multilevel(frame, requested)
    else:
        normalized, errors = _normalize_plain(frame, requested)

    if not normalized:
        return _empty_prices(), tuple(errors)

    prices = pd.concat(normalized, ignore_index=True)
    start_timestamp = pd.Timestamp(start)
    end_timestamp = pd.Timestamp(end)
    prices = prices.loc[
        prices["date"].ge(start_timestamp) & prices["date"].lt(end_timestamp)
    ].copy()

    available = set(prices["symbol"])
    existing_error_symbols = {error.symbol for error in errors}
    for symbol in requested:
        if symbol not in available and symbol not in existing_error_symbols:
            errors.append(
                SymbolError(symbol, "symbol_unavailable", "no rows in requested range")
            )

    if prices.empty:
        return _empty_prices(), tuple(errors)
    order = {symbol: position for position, symbol in enumerate(requested)}
    prices["_symbol_order"] = prices["symbol"].map(order)
    prices = prices.sort_values(
        ["_symbol_order", "date"], kind="stable"
    ).drop(columns="_symbol_order")
    return prices.loc[:, list(NORMALIZED_COLUMNS)].reset_index(drop=True), tuple(
        errors
    )


@dataclass(frozen=True, slots=True)
class YFinanceProvider:
    """Fetch and normalize Yahoo Finance daily prices."""

    max_attempts: int = 3
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], datetime] = _utc_now

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")

    def fetch(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
    ) -> MarketData:
        """Fetch one batched response per bounded attempt."""

        clock_value = self.clock()
        if clock_value.tzinfo is None or clock_value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        fetched_at = clock_value.astimezone(UTC)
        requested = _requested_symbols(symbols)
        if not requested:
            return MarketData(_empty_prices(), fetched_at, "yfinance", ())

        for attempt in range(self.max_attempts):
            try:
                response = yf.download(
                    tickers=list(requested),
                    **_DOWNLOAD_OPTIONS,
                )
                prices, errors = _normalize_download(
                    response, requested, start, end
                )
                return MarketData(prices, fetched_at, "yfinance", errors)
            except Exception:
                if attempt + 1 < self.max_attempts:
                    self.sleep(float(2**attempt))

        errors = tuple(
            SymbolError(
                symbol=symbol,
                code="download_failed",
                detail="market-data download failed",
            )
            for symbol in requested
        )
        return MarketData(_empty_prices(), fetched_at, "yfinance", errors)
