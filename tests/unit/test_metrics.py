"""Exact, deterministic contracts for the eight market-metric datasets."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from semipulse_sentinel.metrics import (
    DATASET_NAMES,
    METRICS_VERSION,
    SCALAR_KEYS,
    annualized_realized_volatility,
    compute_metrics,
    max_drawdown,
    recent_moving_average_crossover,
)

BENCHMARKS = ("SMH", "SOXX", "QQQ", "SOXL")
WATCHLIST = ("AAA", "BBB", "CCC", "SMH")


def _frame(
    series: dict[str, np.ndarray | list[float]],
    *,
    dates: pd.DatetimeIndex | None = None,
    close_multiplier: float = 1.1,
    volumes: dict[str, np.ndarray | list[float]] | None = None,
) -> pd.DataFrame:
    """Build normalized provider rows without hiding missing observations."""

    length = len(next(iter(series.values())))
    market_dates = (
        dates
        if dates is not None
        else pd.bdate_range("2024-01-02", periods=length, name="date")
    )
    rows: list[pd.DataFrame] = []
    for symbol, values in series.items():
        adjusted = np.asarray(values, dtype="float64")
        close = adjusted * close_multiplier
        volume_values = (
            np.asarray(volumes[symbol], dtype="float64")
            if volumes is not None and symbol in volumes
            else np.full(length, 1_000_000.0)
        )
        rows.append(
            pd.DataFrame(
                {
                    "date": market_dates,
                    "symbol": symbol,
                    "open": close - 0.5,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close,
                    "adj_close": adjusted,
                    "volume": volume_values,
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


@pytest.fixture
def prices_fixture() -> pd.DataFrame:
    periods = 260
    step = np.arange(periods, dtype="float64")
    return _frame(
        {
            "AAA": 80.0 * np.exp(0.0018 * step),
            "BBB": 140.0 * np.exp(-0.0009 * step),
            "CCC": 60.0 * np.exp(0.0004 * step + 0.015 * np.sin(step / 6)),
            "SMH": 100.0 * np.exp(0.0012 * step + 0.01 * np.sin(step / 8)),
            "SOXX": 105.0 * np.exp(0.0010 * step + 0.008 * np.sin(step / 9)),
            "QQQ": 95.0 * np.exp(0.0007 * step + 0.006 * np.sin(step / 10)),
            "SOXL": 45.0 * np.exp(0.0020 * step + 0.025 * np.sin(step / 5)),
            "^VIX": 20.0 + 2.0 * np.sin(step / 7),
        }
    )


def _as_of(prices: pd.DataFrame) -> date:
    return pd.Timestamp(prices["date"].max()).date()


def test_bundle_exposes_exactly_eight_versioned_named_datasets(
    prices_fixture: pd.DataFrame,
) -> None:
    result = compute_metrics(prices_fixture, WATCHLIST, _as_of(prices_fixture))

    assert result.methodology_version == METRICS_VERSION == "semipulse-metrics-v1"
    assert tuple(result.datasets) == DATASET_NAMES
    assert DATASET_NAMES == (
        "normalized_performance",
        "relative_strength",
        "breadth",
        "participation",
        "momentum",
        "trend_heatmap",
        "risk_regime",
        "risk_reward",
    )
    assert tuple(result.scalars) == SCALAR_KEYS


def test_normalization_rebases_each_benchmark_to_100_and_keeps_126_rows(
    prices_fixture: pd.DataFrame,
) -> None:
    result = compute_metrics(prices_fixture, WATCHLIST, _as_of(prices_fixture))
    first = result.normalized_performance.groupby("symbol")["value"].first()

    assert first.to_dict() == {
        "QQQ": 100.0,
        "SMH": 100.0,
        "SOXL": 100.0,
        "SOXX": 100.0,
    }
    assert result.normalized_performance.groupby("symbol").size().to_dict() == {
        symbol: 126 for symbol in BENCHMARKS
    }


def test_returns_use_adjusted_close_and_ignore_future_rows(
    prices_fixture: pd.DataFrame,
) -> None:
    as_of_timestamp = pd.Timestamp(prices_fixture["date"].iloc[-2])
    result = compute_metrics(prices_fixture, WATCHLIST, as_of_timestamp.date())
    aaa = prices_fixture.loc[
        (prices_fixture["symbol"] == "AAA")
        & (prices_fixture["date"] <= as_of_timestamp),
        "adj_close",
    ]
    expected = aaa.iloc[-1] / aaa.iloc[-21] - 1.0

    actual = result.momentum.set_index("symbol").loc["AAA", "return_20"]
    assert actual == pytest.approx(expected)
    assert result.normalized_performance["date"].max() == as_of_timestamp


def test_breadth_uses_available_denominator_on_each_observed_date() -> None:
    dates = pd.bdate_range("2025-01-02", periods=21, name="date")
    prices = _frame(
        {
            "AAA": np.arange(100.0, 121.0),
            "BBB": np.arange(121.0, 100.0, -1.0),
            "CCC": np.arange(90.0, 111.0),
            "SMH": np.arange(200.0, 221.0),
        },
        dates=dates,
    )
    prices = prices.loc[
        ~((prices["symbol"] == "CCC") & (prices["date"] == dates[-1]))
    ]

    result = compute_metrics(prices, WATCHLIST, dates[-1].date())
    row = result.breadth.loc[result.breadth["date"] == dates[-1]].iloc[0]

    assert row["covered_count"] == 3
    assert row["covered_20_count"] == 3
    assert row["missing_20_count"] == 1
    assert row["above_20_pct"] == pytest.approx(200.0 / 3.0)
    assert row["covered_50_count"] == 0
    assert np.isnan(row["above_50_pct"])


def test_breadth_uses_smh_sessions_without_filling_symbol_gaps() -> None:
    dates = pd.bdate_range("2025-01-02", periods=21, name="date")
    prices = _frame(
        {
            "AAA": np.arange(100.0, 121.0),
            "SMH": np.arange(200.0, 221.0),
        },
        dates=dates,
    )
    symbol_only_date = dates[-1] + pd.offsets.BDay(1)
    extra = prices.loc[prices["symbol"] == "AAA"].iloc[[-1]].copy()
    extra["date"] = symbol_only_date
    prices = pd.concat([prices, extra], ignore_index=True)

    result = compute_metrics(
        prices, ("AAA", "SMH"), symbol_only_date.date()
    )

    assert result.breadth["date"].max() == dates[-1]
    latest = result.breadth.iloc[-1]
    assert latest["covered_20_count"] == 2


def test_all_rolling_calculations_require_full_lookbacks() -> None:
    periods = 19
    prices = _frame(
        {
            "SMH": np.linspace(100.0, 110.0, periods),
            "QQQ": np.linspace(100.0, 105.0, periods),
            "AAA": np.linspace(50.0, 55.0, periods),
        }
    )
    result = compute_metrics(prices, ("AAA", "SMH"), _as_of(prices))

    assert np.isnan(result.scalars["smh_return_20"])
    assert np.isnan(result.scalars["smh_vol_20"])
    assert result.breadth.iloc[-1]["covered_20_count"] == 0
    unsupported = result.trend_heatmap.query(
        "symbol == 'AAA' and metric == 'distance_sma_20'"
    ).iloc[0]
    assert bool(unsupported["supported"]) is False
    assert np.isnan(unsupported["value"])


@pytest.mark.parametrize(
    ("periods", "expected_supported"),
    [(63, False), (64, True)],
)
def test_participation_requires_64_smh_observations_for_t_over_t_minus_63(
    periods: int,
    expected_supported: bool,
) -> None:
    smh = np.linspace(100.0, 163.0, periods)
    aaa = np.linspace(50.0, 113.0, periods)
    prices = _frame({"AAA": aaa, "SMH": smh})

    result = compute_metrics(prices, ("AAA", "SMH"), _as_of(prices))
    latest = result.participation.iloc[-1]

    assert bool(latest["supported"]) is expected_supported
    if expected_supported:
        assert latest["smh_cumulative_return"] == pytest.approx(
            smh[-1] / smh[-64] - 1.0
        )
        assert latest["eligible_count"] == 2
        assert result.scalars["participation_eligible_count"] == 2.0
    else:
        assert np.isnan(latest["smh_cumulative_return"])
        assert np.isnan(latest["spread"])
        assert latest["eligible_count"] == 0
        assert latest["missing_count"] == 2
        assert result.scalars["participation_eligible_count"] == 0.0


@pytest.mark.parametrize("missing_position", [-64, -1])
def test_participation_excludes_symbol_missing_common_baseline_or_current(
    missing_position: int,
) -> None:
    periods = 70
    prices = _frame(
        {
            "AAA": np.linspace(50.0, 100.0, periods),
            "SMH": np.linspace(100.0, 150.0, periods),
        }
    )
    aaa_dates = prices.loc[prices["symbol"] == "AAA", "date"]
    missing_date = aaa_dates.iloc[missing_position]
    prices = prices.loc[
        ~((prices["symbol"] == "AAA") & (prices["date"] == missing_date))
    ]

    result = compute_metrics(prices, ("AAA", "SMH"), _as_of(prices))
    latest = result.participation.iloc[-1]

    assert bool(latest["supported"]) is True
    assert latest["eligible_count"] == 1
    assert latest["missing_count"] == 1
    assert result.scalars["participation_missing_count"] == 1.0


def test_watchlist_metrics_use_canonical_smh_grid_without_shifting_lookbacks() -> None:
    periods = 220
    step = np.arange(periods, dtype="float64")
    prices = _frame(
        {
            "AAA": 50.0 * np.exp(0.001 * step),
            "SMH": 100.0 * np.exp(0.001 * step),
            "QQQ": 90.0 * np.exp(0.0005 * step),
        }
    )
    dates = prices.loc[prices["symbol"] == "SMH", "date"].reset_index(drop=True)
    missing_dates = {dates.iloc[-10], dates.iloc[-21], dates.iloc[-64]}
    prices = prices.loc[
        ~((prices["symbol"] == "AAA") & prices["date"].isin(missing_dates))
    ]

    result = compute_metrics(prices, ("AAA", "SMH"), _as_of(prices))
    momentum_aaa = result.momentum.set_index("symbol").loc["AAA"]
    heatmap_aaa = result.trend_heatmap.query("symbol == 'AAA'").set_index(
        "metric"
    )
    risk_aaa = result.risk_reward.set_index("symbol").loc["AAA"]

    assert np.isnan(momentum_aaa["return_20"])
    assert bool(momentum_aaa["eligible"]) is False
    assert np.isnan(heatmap_aaa.loc["return_20", "value"])
    assert np.isnan(heatmap_aaa.loc["return_63", "value"])
    assert np.isnan(heatmap_aaa.loc["distance_sma_20", "value"])
    assert np.isnan(risk_aaa["return_63"])
    assert np.isnan(risk_aaa["volatility_20"])
    assert bool(risk_aaa["xy_supported"]) is False


@pytest.mark.parametrize(
    ("sessions_after_crossing", "expected"),
    [(0, 1.0), (4, 1.0), (5, 0.0)],
)
def test_recent_crossover_includes_latest_five_sessions_only(
    sessions_after_crossing: int,
    expected: float,
) -> None:
    values = pd.Series(
        [100.0] * 60 + [200.0] + [200.0] * sessions_after_crossing
    )

    assert recent_moving_average_crossover(values) == expected


def test_recent_crossover_returns_latest_direction_after_whipsaw() -> None:
    values = pd.Series([100.0] * 60 + [200.0, 1.0, 1.0])

    assert recent_moving_average_crossover(values) == -1.0


def test_recent_crossover_is_nan_until_both_averages_are_supported() -> None:
    assert np.isnan(recent_moving_average_crossover(pd.Series([100.0] * 49)))


def test_annualized_volatility_uses_adjusted_log_returns_and_constant_is_zero(
    prices_fixture: pd.DataFrame,
) -> None:
    smh = prices_fixture.loc[prices_fixture["symbol"] == "SMH", "adj_close"]
    expected = np.log(smh).diff().tail(20).std(ddof=1) * np.sqrt(252)
    result = compute_metrics(prices_fixture, WATCHLIST, _as_of(prices_fixture))

    assert result.scalars["smh_vol_20"] == pytest.approx(expected)
    constant = pd.Series(np.ones(30) * 100.0)
    assert annualized_realized_volatility(constant).iloc[-1] == 0.0


def test_relative_strength_uses_only_exactly_aligned_dates_without_filling(
    prices_fixture: pd.DataFrame,
) -> None:
    missing_date = prices_fixture.loc[
        prices_fixture["symbol"] == "QQQ", "date"
    ].iloc[-10]
    prices = prices_fixture.loc[
        ~(
            (prices_fixture["symbol"] == "QQQ")
            & (prices_fixture["date"] == missing_date)
        )
    ].copy()
    result = compute_metrics(prices, WATCHLIST, _as_of(prices))
    smh_ratio = result.relative_strength.query("symbol == 'SMH/QQQ'")

    assert missing_date not in set(smh_ratio["date"])
    assert smh_ratio.iloc[0]["value"] == pytest.approx(100.0)
    assert smh_ratio.iloc[-1]["ratio"] == pytest.approx(
        prices.query("symbol == 'SMH'")["adj_close"].iloc[-1]
        / prices.query("symbol == 'QQQ'")["adj_close"].iloc[-1]
    )


def test_drawdown_is_never_positive_and_preserves_peak_to_current_sign() -> None:
    series = pd.Series([100.0] * 62 + [120.0, 90.0])
    result = max_drawdown(series, window=63)

    assert result.iloc[-2] == pytest.approx(0.0)
    assert result.iloc[-1] == pytest.approx(-0.25)
    assert (result.dropna() <= 0.0).all()


def test_volatility_percentile_uses_midrank_for_ties() -> None:
    periods = 300
    prices = _frame(
        {
            "SMH": np.full(periods, 100.0),
            "QQQ": np.full(periods, 100.0),
        }
    )
    result = compute_metrics(prices, ("SMH",), _as_of(prices))

    assert result.scalars["smh_vol_percentile_252"] == pytest.approx(50.0)


def test_missing_volume_preserves_risk_reward_row_and_nan_bubble() -> None:
    periods = 90
    prices = _frame(
        {
            "AAA": np.linspace(50.0, 70.0, periods),
            "SMH": np.linspace(100.0, 120.0, periods),
            "QQQ": np.linspace(90.0, 100.0, periods),
        },
        volumes={
            "AAA": np.full(periods, np.nan),
            "SMH": np.full(periods, 1_000_000.0),
            "QQQ": np.full(periods, 1_000_000.0),
        },
    )
    result = compute_metrics(prices, ("AAA", "SMH"), _as_of(prices))
    aaa = result.risk_reward.set_index("symbol").loc["AAA"]

    assert np.isfinite(aaa["return_63"])
    assert np.isfinite(aaa["volatility_20"])
    assert np.isnan(aaa["dollar_volume_20"])


def test_all_negative_momentum_keeps_least_negative_leader_first() -> None:
    periods = 90
    prices = _frame(
        {
            "AAA": 100.0 * np.power(0.999, np.arange(periods)),
            "BBB": 100.0 * np.power(0.995, np.arange(periods)),
            "SMH": 100.0 * np.power(0.997, np.arange(periods)),
            "QQQ": 100.0 * np.power(0.998, np.arange(periods)),
        }
    )
    result = compute_metrics(prices, ("AAA", "BBB", "SMH"), _as_of(prices))

    assert result.momentum["symbol"].tolist() == ["AAA", "SMH", "BBB"]
    assert (result.momentum["return_20"] < 0).all()
    assert result.scalars["momentum_median_20"] < 0.0


def test_unsupported_momentum_is_not_ranked_as_a_laggard() -> None:
    periods = 70
    prices = _frame(
        {
            "AAA": np.linspace(100.0, 120.0, periods),
            "BBB": np.linspace(100.0, 120.0, periods),
            "CCC": np.linspace(100.0, 80.0, periods),
            "SMH": np.linspace(100.0, 110.0, periods),
            "QQQ": np.linspace(100.0, 105.0, periods),
        }
    )
    canonical = prices.loc[prices["symbol"] == "SMH", "date"].reset_index(
        drop=True
    )
    prices = prices.loc[
        ~(
            (prices["symbol"] == "CCC")
            & (prices["date"] == canonical.iloc[-21])
        )
    ]

    result = compute_metrics(prices, ("BBB", "CCC", "AAA"), _as_of(prices))

    assert result.momentum["symbol"].tolist() == ["AAA", "BBB", "CCC"]
    assert result.momentum["rank"].dtype == "Int64"
    unsupported = result.momentum.iloc[-1]
    assert bool(unsupported["supported"]) is False
    assert bool(unsupported["eligible"]) is False
    assert pd.isna(unsupported["rank"])
    assert result.scalars["momentum_eligible_count"] == 2.0
    assert result.scalars["momentum_missing_count"] == 1.0


def test_risk_reward_reference_medians_use_only_complete_xy_pairs() -> None:
    periods = 90
    step = np.arange(periods, dtype="float64")
    prices = _frame(
        {
            "AAA": 50.0 * np.exp(0.002 * step),
            "BBB": 80.0 * np.exp(-0.001 * step + 0.01 * np.sin(step)),
            "CCC": np.linspace(60.0, 80.0, periods),
            "SMH": np.linspace(100.0, 125.0, periods),
            "QQQ": np.linspace(100.0, 115.0, periods),
        }
    )
    prices = prices.loc[
        ~((prices["symbol"] == "CCC") & (prices["date"] < prices["date"].iloc[40]))
    ]
    result = compute_metrics(prices, WATCHLIST, _as_of(prices))
    complete = result.risk_reward.dropna(subset=["return_63", "volatility_20"])

    assert result.scalars["risk_reward_return_median_63"] == pytest.approx(
        complete["return_63"].median()
    )
    assert result.scalars["risk_reward_vol_median_20"] == pytest.approx(
        complete["volatility_20"].median()
    )
    assert np.isnan(
        result.risk_reward.set_index("symbol").loc["CCC", "return_63"]
    )


def test_participation_and_heatmap_keep_deterministic_watchlist_order(
    prices_fixture: pd.DataFrame,
) -> None:
    result = compute_metrics(prices_fixture, WATCHLIST, _as_of(prices_fixture))

    assert result.trend_heatmap["symbol"].drop_duplicates().tolist() == list(
        WATCHLIST
    )
    assert result.trend_heatmap["metric"].drop_duplicates().tolist() == [
        "return_5",
        "return_20",
        "return_63",
        "distance_sma_20",
        "distance_sma_50",
        "distance_sma_200",
    ]
    latest = result.participation.iloc[-1]
    assert latest["spread"] == pytest.approx(
        latest["watchlist_median_cumulative_return"]
        - latest["smh_cumulative_return"]
    )
    assert 0.0 <= latest["outperforming_smh_pct"] <= 100.0


def test_risk_regime_aligns_optional_vix_without_making_it_required(
    prices_fixture: pd.DataFrame,
) -> None:
    without_vix = prices_fixture.loc[prices_fixture["symbol"] != "^VIX"].copy()
    result = compute_metrics(without_vix, WATCHLIST, _as_of(without_vix))

    assert result.risk_regime["vix"].isna().all()
    assert np.isnan(result.scalars["vix_latest"])
    assert result.risk_regime["volatility_20"].notna().any()


def test_dollar_volume_uses_unadjusted_close_times_volume_median() -> None:
    periods = 90
    volume = np.arange(1_000.0, 1_000.0 + periods)
    adjusted = np.linspace(100.0, 120.0, periods)
    prices = _frame(
        {"AAA": adjusted, "SMH": adjusted, "QQQ": adjusted},
        volumes={"AAA": volume, "SMH": volume, "QQQ": volume},
    )
    result = compute_metrics(prices, ("AAA", "SMH"), _as_of(prices))
    expected = pd.Series(adjusted * 1.1 * volume).tail(20).median()

    actual = result.risk_reward.set_index("symbol").loc[
        "AAA", "dollar_volume_20"
    ]
    assert actual == pytest.approx(expected)


def test_support_counts_and_liquidity_eligibility_are_always_explicit() -> None:
    periods = 90
    prices = _frame(
        {
            "AAA": np.linspace(50.0, 70.0, periods),
            "BBB": np.linspace(80.0, 90.0, periods),
            "SMH": np.linspace(100.0, 120.0, periods),
            "QQQ": np.linspace(90.0, 100.0, periods),
        },
        volumes={
            "AAA": np.full(periods, np.nan),
            "BBB": np.full(periods, 500_000.0),
            "SMH": np.full(periods, 1_000_000.0),
            "QQQ": np.full(periods, 1_000_000.0),
        },
    )
    result = compute_metrics(prices, ("AAA", "BBB", "SMH"), _as_of(prices))
    risk = result.risk_reward.set_index("symbol")

    assert bool(risk.loc["AAA", "xy_supported"]) is True
    assert bool(risk.loc["AAA", "liquidity_supported"]) is False
    assert result.scalars["risk_reward_xy_eligible_count"] == 3.0
    assert result.scalars["risk_reward_xy_missing_count"] == 0.0
    assert result.scalars["risk_reward_liquidity_missing_count"] == 1.0
    assert result.scalars["trend_supported_cells"] > 0.0
    assert result.scalars["trend_missing_cells"] >= 0.0


def test_empty_market_input_keeps_exact_schemas_and_zero_counts() -> None:
    prices = pd.DataFrame(
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

    result = compute_metrics(prices, ("AAA", "SMH"), date(2025, 1, 2))

    assert result.normalized_performance.columns.tolist() == [
        "date",
        "symbol",
        "value",
    ]
    assert result.relative_strength.columns.tolist() == [
        "date",
        "symbol",
        "ratio",
        "value",
        "sma_20",
        "sma_50",
    ]
    assert result.breadth.columns.tolist() == [
        "date",
        "covered_count",
        "missing_count",
        "above_20_pct",
        "above_20_count",
        "covered_20_count",
        "missing_20_count",
        "above_50_pct",
        "above_50_count",
        "covered_50_count",
        "missing_50_count",
        "above_200_pct",
        "above_200_count",
        "covered_200_count",
        "missing_200_count",
    ]
    assert result.participation.columns.tolist() == [
        "date",
        "watchlist_median_cumulative_return",
        "smh_cumulative_return",
        "spread",
        "outperforming_smh_pct",
        "dispersion",
        "covered_count",
        "eligible_count",
        "missing_count",
        "supported",
    ]
    assert result.momentum.columns.tolist() == [
        "symbol",
        "return_20",
        "supported",
        "eligible",
        "rank",
    ]
    assert result.risk_reward.columns.tolist() == [
        "symbol",
        "return_63",
        "volatility_20",
        "dollar_volume_20",
        "xy_supported",
        "liquidity_supported",
        "quadrant",
    ]
    assert result.scalars["participation_eligible_count"] == 0.0
    assert result.scalars["participation_missing_count"] == 2.0
    assert result.scalars["momentum_eligible_count"] == 0.0
    assert result.scalars["momentum_missing_count"] == 2.0
    assert result.scalars["trend_supported_cells"] == 0.0
    assert result.scalars["trend_missing_cells"] == 12.0
    assert result.scalars["risk_reward_xy_eligible_count"] == 0.0
    assert result.scalars["risk_reward_xy_missing_count"] == 2.0
    assert result.scalars["risk_reward_liquidity_eligible_count"] == 0.0
    assert result.scalars["risk_reward_liquidity_missing_count"] == 2.0
