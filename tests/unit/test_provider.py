"""Tests for the only runtime market-data network boundary."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import yfinance as yf

from semipulse_sentinel.providers.base import NORMALIZED_COLUMNS
from semipulse_sentinel.providers.yfinance_provider import YFinanceProvider

START = date(2025, 1, 1)
END = date(2025, 7, 1)


def _field_values(symbol_offset: int) -> dict[str, list[float]]:
    base = 100.0 + symbol_offset * 10
    return {
        "Open": [base, base + 1],
        "High": [base + 2, base + 3],
        "Low": [base - 2, base - 1],
        "Close": [base + 0.5, base + 1.5],
        "Adj Close": [base + 0.25, base + 1.25],
        "Volume": [1_000_000.0, 1_100_000.0],
    }


def multilevel_frame(
    symbols: tuple[str, ...] = ("SMH", "NVDA"),
) -> pd.DataFrame:
    """Mirror yfinance's documented field-first multi-symbol shape."""

    values: dict[tuple[str, str], list[float]] = {}
    for offset, symbol in enumerate(symbols):
        for field, field_values in _field_values(offset).items():
            values[(field, symbol)] = field_values
    columns = pd.MultiIndex.from_tuples(values, names=["Price", "Ticker"])
    return pd.DataFrame(
        values,
        index=pd.DatetimeIndex(["2025-06-27", "2025-06-30"], name="Date"),
        columns=columns,
    )


def fake_multilevel_download(
    tickers: list[str],
    **kwargs: Any,
) -> pd.DataFrame:
    del kwargs
    return multilevel_frame(tuple(tickers))


def test_provider_normalizes_to_tidy_adjusted_ohlcv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(yf, "download", fake_multilevel_download)

    data = YFinanceProvider(max_attempts=1).fetch(
        ["SMH", "NVDA"], START, END
    )

    assert list(data.prices.columns) == list(NORMALIZED_COLUMNS)
    monotonic = data.prices.groupby("symbol")["date"].apply(
        lambda values: values.is_monotonic_increasing
    )
    assert monotonic.all()
    assert data.prices["symbol"].drop_duplicates().tolist() == ["SMH", "NVDA"]
    assert data.prices.loc[0, "adj_close"] == pytest.approx(100.25)
    assert data.provider == "yfinance"
    assert data.errors == ()


def test_provider_uses_one_combined_call_with_exact_download_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def download(tickers: list[str], **kwargs: Any) -> pd.DataFrame:
        calls.append((tickers, kwargs))
        return multilevel_frame(tuple(tickers))

    monkeypatch.setattr(yf, "download", download)

    YFinanceProvider(max_attempts=1).fetch(["smh", "NVDA", "SMH"], START, END)

    assert calls == [
        (
            ["SMH", "NVDA"],
            {
                "period": "2y",
                "interval": "1d",
                "auto_adjust": False,
                "actions": False,
                "group_by": "column",
                "threads": True,
                "repair": True,
                "timeout": 30,
            },
        )
    ]


def test_provider_normalizes_single_level_result_identically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(
        _field_values(0),
        index=pd.DatetimeIndex(["2025-06-27", "2025-06-30"], name="Date"),
    )
    monkeypatch.setattr(yf, "download", lambda *args, **kwargs: frame)

    data = YFinanceProvider(max_attempts=1).fetch(["SMH"], START, END)

    assert list(data.prices.columns) == list(NORMALIZED_COLUMNS)
    assert data.prices["symbol"].tolist() == ["SMH", "SMH"]
    assert data.prices["adj_close"].tolist() == [100.25, 101.25]


def test_provider_accepts_symbol_first_multilevel_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = multilevel_frame().swaplevel(axis="columns")
    frame.columns.names = ["Ticker", "Price"]
    monkeypatch.setattr(yf, "download", lambda *args, **kwargs: frame)

    data = YFinanceProvider(max_attempts=1).fetch(["SMH", "NVDA"], START, END)

    assert data.prices.groupby("symbol").size().to_dict() == {"NVDA": 2, "SMH": 2}
    assert data.errors == ()


def test_provider_drops_union_calendar_rows_with_no_symbol_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = multilevel_frame()
    placeholder = frame.iloc[[0]].copy()
    placeholder.index = pd.DatetimeIndex(["2025-06-26"], name="Date")
    placeholder.loc[:, pd.IndexSlice[:, "SMH"]] = float("nan")
    frame = pd.concat([placeholder, frame]).sort_index()
    monkeypatch.setattr(yf, "download", lambda *args, **kwargs: frame)

    data = YFinanceProvider(max_attempts=1).fetch(
        ["SMH", "NVDA"], START, END
    )

    counts = data.prices.groupby("symbol").size().to_dict()
    assert counts == {"NVDA": 3, "SMH": 2}
    assert data.errors == ()


def test_provider_preserves_partially_populated_missing_adjusted_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = multilevel_frame(("SMH",))
    frame.loc[frame.index[0], ("Adj Close", "SMH")] = float("nan")
    monkeypatch.setattr(yf, "download", lambda *args, **kwargs: frame)

    data = YFinanceProvider(max_attempts=1).fetch(["SMH"], START, END)

    assert len(data.prices) == 2
    assert data.prices["adj_close"].isna().sum() == 1


def test_provider_preserves_nonnull_malformed_rows_for_quality_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = multilevel_frame(("SMH",)).astype(object)
    frame.loc[frame.index[0], :] = "malformed"
    monkeypatch.setattr(yf, "download", lambda *args, **kwargs: frame)

    data = YFinanceProvider(max_attempts=1).fetch(["SMH"], START, END)

    assert len(data.prices) == 2
    malformed = data.prices.loc[data.prices["date"].eq(pd.Timestamp("2025-06-27"))]
    assert len(malformed) == 1
    assert malformed.loc[:, list(NORMALIZED_COLUMNS[2:])].isna().all(axis=None)


def test_provider_trims_start_inclusive_and_end_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = multilevel_frame(("SMH",))
    monkeypatch.setattr(yf, "download", lambda *args, **kwargs: frame)

    data = YFinanceProvider(max_attempts=1).fetch(
        ["SMH"], date(2025, 6, 30), date(2025, 7, 1)
    )

    assert data.prices["date"].dt.date.tolist() == [date(2025, 6, 30)]


def test_provider_preserves_duplicate_symbol_dates_for_quality_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = multilevel_frame(("SMH",))
    frame.index = pd.DatetimeIndex(
        ["2025-06-30", "2025-06-30"], name="Date"
    )
    monkeypatch.setattr(yf, "download", lambda *args, **kwargs: frame)

    data = YFinanceProvider(max_attempts=1).fetch(["SMH"], START, END)

    assert data.prices.duplicated(["symbol", "date"]).any()


def test_provider_reports_missing_adjusted_close_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = multilevel_frame(("SMH",)).drop(columns="Adj Close", level="Price")
    monkeypatch.setattr(yf, "download", lambda *args, **kwargs: frame)

    data = YFinanceProvider(max_attempts=1).fetch(["SMH"], START, END)

    assert data.prices.empty
    assert [(error.symbol, error.code) for error in data.errors] == [
        ("SMH", "symbol_unavailable")
    ]


def test_provider_treats_all_missing_adjusted_close_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = multilevel_frame()
    frame[("Adj Close", "SMH")] = float("nan")
    monkeypatch.setattr(yf, "download", lambda *args, **kwargs: frame)

    data = YFinanceProvider(max_attempts=1).fetch(["SMH", "NVDA"], START, END)

    assert data.prices["symbol"].unique().tolist() == ["NVDA"]
    assert [(error.symbol, error.code) for error in data.errors] == [
        ("SMH", "symbol_unavailable")
    ]


def test_provider_ignores_unexpected_tickers_and_names_missing_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = multilevel_frame(("SMH", "UNEXPECTED"))
    monkeypatch.setattr(yf, "download", lambda *args, **kwargs: frame)

    data = YFinanceProvider(max_attempts=1).fetch(["SMH", "NVDA"], START, END)

    assert data.prices["symbol"].unique().tolist() == ["SMH"]
    assert [(error.symbol, error.code) for error in data.errors] == [
        ("NVDA", "symbol_unavailable")
    ]


def test_provider_retries_with_bounded_backoff_and_sanitized_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    sleeps: list[float] = []

    def failing_download(*args: Any, **kwargs: Any) -> pd.DataFrame:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("cookie=SUPER-SECRET raw response body")

    monkeypatch.setattr(yf, "download", failing_download)

    data = YFinanceProvider(max_attempts=3, sleep=sleeps.append).fetch(
        ["SMH", "NVDA"], START, END
    )

    assert attempts == 3
    assert sleeps == [1.0, 2.0]
    assert data.prices.empty
    assert [error.code for error in data.errors] == [
        "download_failed",
        "download_failed",
    ]
    assert all(error.detail == "market-data download failed" for error in data.errors)
    assert "SECRET" not in repr(data.errors)


@pytest.mark.parametrize("max_attempts", [0, 4])
def test_provider_rejects_attempt_counts_outside_bounded_range(
    max_attempts: int,
) -> None:
    with pytest.raises(ValueError, match="between 1 and 3"):
        YFinanceProvider(max_attempts=max_attempts)


def test_provider_uses_an_injected_aware_utc_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched_at = datetime(2025, 7, 1, 22, 0, tzinfo=UTC)
    monkeypatch.setattr(yf, "download", fake_multilevel_download)

    data = YFinanceProvider(max_attempts=1, clock=lambda: fetched_at).fetch(
        ["SMH"], START, END
    )

    assert data.fetched_at is fetched_at


def test_provider_normalizes_an_injected_non_utc_clock_to_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched_at = datetime(
        2025,
        7,
        1,
        18,
        0,
        tzinfo=ZoneInfo("America/New_York"),
    )
    monkeypatch.setattr(yf, "download", fake_multilevel_download)

    data = YFinanceProvider(max_attempts=1, clock=lambda: fetched_at).fetch(
        ["SMH"], START, END
    )

    assert data.fetched_at == datetime(2025, 7, 1, 22, 0, tzinfo=UTC)
    assert data.fetched_at.tzinfo is UTC


def test_provider_rejects_a_naive_injected_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(yf, "download", fake_multilevel_download)
    provider = YFinanceProvider(
        max_attempts=1,
        clock=lambda: datetime(2025, 7, 1, 22, 0),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        provider.fetch(["SMH"], START, END)
