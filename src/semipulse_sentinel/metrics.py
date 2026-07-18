"""Pure, versioned calculations for the eight SemiPulse chart datasets.

All return and risk calculations use adjusted close. Missing observations stay
missing: this module never forward-fills, back-fills, or substitutes close for
adjusted close. Cross-sectional outputs retain requested symbols with NaN when
a lookback is unsupported so downstream prose can disclose the limitation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from math import isfinite
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

METRICS_VERSION = "semipulse-metrics-v1"

DATASET_NAMES: tuple[str, ...] = (
    "normalized_performance",
    "relative_strength",
    "breadth",
    "participation",
    "momentum",
    "trend_heatmap",
    "risk_regime",
    "risk_reward",
)

_BENCHMARKS = ("SMH", "SOXX", "QQQ", "SOXL")
_BENCHMARK_PREFIXES = tuple(symbol.lower() for symbol in _BENCHMARKS)
_BENCHMARK_SCALAR_SUFFIXES = (
    "return_5",
    "return_20",
    "return_63",
    "slope_20",
    "distance_sma_20",
    "distance_sma_50",
    "drawdown_63",
)
_RATIO_DEFINITIONS = (("SMH", "smh_qqq"), ("SOXX", "soxx_qqq"))
_RATIO_SCALAR_SUFFIXES = (
    "return_20",
    "return_63",
    "distance_sma_20",
    "distance_sma_50",
    "crossover_20_50",
    "crossover_20_50_supported",
)

SCALAR_KEYS: tuple[str, ...] = (
    *(
        f"{prefix}_{suffix}"
        for prefix in _BENCHMARK_PREFIXES
        for suffix in _BENCHMARK_SCALAR_SUFFIXES
    ),
    *(
        f"{prefix}_{suffix}"
        for _, prefix in _RATIO_DEFINITIONS
        for suffix in _RATIO_SCALAR_SUFFIXES
    ),
    "breadth_above_20_pct",
    "breadth_above_50_pct",
    "breadth_above_200_pct",
    "breadth_20_change_5",
    "breadth_50_change_5",
    "breadth_200_change_5",
    "breadth_covered_20_count",
    "breadth_covered_50_count",
    "breadth_covered_200_count",
    "participation_spread_63",
    "participation_outperforming_smh_pct",
    "participation_dispersion_63",
    "participation_eligible_count",
    "participation_missing_count",
    "participation_supported",
    "momentum_median_20",
    "momentum_iqr_20",
    "momentum_positive_pct",
    "momentum_eligible_count",
    "momentum_missing_count",
    "trend_positive_cell_pct",
    "trend_unsupported_cells",
    "trend_supported_cells",
    "trend_missing_cells",
    "smh_vol_20",
    "smh_vol_percentile_252",
    "smh_vol_change_5",
    "vix_latest",
    "risk_reward_return_median_63",
    "risk_reward_vol_median_20",
    "risk_reward_xy_eligible_count",
    "risk_reward_xy_missing_count",
    "risk_reward_liquidity_eligible_count",
    "risk_reward_liquidity_missing_count",
)

_ZERO_DEFAULT_SCALARS = frozenset(
    {
        "smh_qqq_crossover_20_50_supported",
        "soxx_qqq_crossover_20_50_supported",
        "breadth_covered_20_count",
        "breadth_covered_50_count",
        "breadth_covered_200_count",
        "participation_eligible_count",
        "participation_missing_count",
        "participation_supported",
        "momentum_eligible_count",
        "momentum_missing_count",
        "trend_unsupported_cells",
        "trend_supported_cells",
        "trend_missing_cells",
        "risk_reward_xy_eligible_count",
        "risk_reward_xy_missing_count",
        "risk_reward_liquidity_eligible_count",
        "risk_reward_liquidity_missing_count",
    }
)

_REQUIRED_COLUMNS = ("date", "symbol", "close", "adj_close", "volume")
_TREND_METRICS = (
    "return_5",
    "return_20",
    "return_63",
    "distance_sma_20",
    "distance_sma_50",
    "distance_sma_200",
)


@dataclass(frozen=True, slots=True)
class MetricBundle:
    """The immutable top-level contract shared by charts and interpretations."""

    methodology_version: str
    as_of: date
    normalized_performance: pd.DataFrame
    relative_strength: pd.DataFrame
    breadth: pd.DataFrame
    participation: pd.DataFrame
    momentum: pd.DataFrame
    trend_heatmap: pd.DataFrame
    risk_regime: pd.DataFrame
    risk_reward: pd.DataFrame
    scalars: Mapping[str, float]

    @property
    def datasets(self) -> Mapping[str, pd.DataFrame]:
        """Expose all and only the stable chart datasets in chart order."""

        return MappingProxyType(
            {
                "normalized_performance": self.normalized_performance,
                "relative_strength": self.relative_strength,
                "breadth": self.breadth,
                "participation": self.participation,
                "momentum": self.momentum,
                "trend_heatmap": self.trend_heatmap,
                "risk_regime": self.risk_regime,
                "risk_reward": self.risk_reward,
            }
        )


def annualized_realized_volatility(
    series: pd.Series,
    window: int = 20,
) -> pd.Series:
    """Return rolling annualized volatility from adjusted log returns."""

    if window < 2:
        raise ValueError("window must be at least 2")
    log_returns = np.log(series).diff()
    return (
        log_returns.rolling(window, min_periods=window).std(ddof=1)
        * np.sqrt(252)
    )


def max_drawdown(series: pd.Series, window: int = 63) -> pd.Series:
    """Return current drawdown from the highest price in each full window."""

    if window < 1:
        raise ValueError("window must be positive")
    rolling_peak = series.rolling(window, min_periods=window).max()
    return series.div(rolling_peak).sub(1.0)


def _symbols(values: Sequence[str]) -> tuple[str, ...]:
    symbols = tuple(
        dict.fromkeys(
            str(value).strip().upper() for value in values if str(value).strip()
        )
    )
    if not symbols:
        raise ValueError("watchlist_symbols must not be empty")
    return symbols


def _prepare_prices(prices: pd.DataFrame, as_of: date) -> pd.DataFrame:
    missing = tuple(column for column in _REQUIRED_COLUMNS if column not in prices)
    if missing:
        raise ValueError(f"prices missing required columns: {','.join(missing)}")

    prepared = prices.copy()
    prepared["date"] = pd.to_datetime(prepared["date"], errors="coerce")
    if isinstance(prepared["date"].dtype, pd.DatetimeTZDtype):
        prepared["date"] = prepared["date"].dt.tz_localize(None)
    if prepared["date"].isna().any():
        raise ValueError("prices contain invalid dates")
    prepared["date"] = prepared["date"].dt.normalize()
    prepared["symbol"] = prepared["symbol"].astype(str).str.strip().str.upper()
    if (prepared["symbol"] == "").any():
        raise ValueError("prices contain blank symbols")
    for column in ("close", "adj_close", "volume"):
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    adjusted = prepared["adj_close"]
    if (~np.isfinite(adjusted) | adjusted.le(0.0)).any():
        raise ValueError("adjusted close must be finite and positive")
    if prepared.duplicated(["symbol", "date"]).any():
        raise ValueError("prices contain duplicate symbol dates")

    cutoff = pd.Timestamp(as_of)
    prepared = prepared.loc[prepared["date"].le(cutoff)].copy()
    return prepared.sort_values(["symbol", "date"], kind="stable").reset_index(
        drop=True
    )


def _series(
    prices: pd.DataFrame,
    symbol: str,
    column: str = "adj_close",
) -> pd.Series:
    selected = prices.loc[prices["symbol"] == symbol, ["date", column]]
    if selected.empty:
        return pd.Series(dtype="float64", name=symbol)
    result = selected.set_index("date")[column].astype("float64").sort_index()
    result.name = symbol
    return result


def _as_float(value: Any) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return converted if isfinite(converted) else float("nan")


def _at(series: pd.Series, timestamp: pd.Timestamp) -> float:
    return _as_float(series.get(timestamp, float("nan")))


def _return(series: pd.Series, periods: int) -> pd.Series:
    return series.pct_change(periods=periods, fill_method=None)


def _distance_from_average(series: pd.Series, window: int) -> pd.Series:
    average = series.rolling(window, min_periods=window).mean()
    return series.div(average).sub(1.0)


def _slope(series: pd.Series, window: int, timestamp: pd.Timestamp) -> float:
    if timestamp not in series.index:
        return float("nan")
    through_date = series.loc[:timestamp].tail(window)
    if len(through_date) != window or not np.isfinite(through_date).all():
        return float("nan")
    values = through_date.to_numpy(dtype="float64")
    return float(np.polyfit(np.arange(window, dtype="float64"), np.log(values), 1)[0])


def recent_moving_average_crossover(
    series: pd.Series,
    short_window: int = 20,
    long_window: int = 50,
    lookback: int = 5,
) -> float:
    """Return the latest moving-average crossing in recent supported sessions.

    ``1`` is a bullish crossing, ``-1`` a bearish crossing, and ``0`` means
    no crossing landed in the latest ``lookback`` observations. A crossing on
    the fifth-latest observation is included when ``lookback=5``. Missing
    observations are not filled; callers choose the authoritative session grid.
    """

    if not 1 <= short_window < long_window:
        raise ValueError("windows must satisfy 1 <= short_window < long_window")
    if lookback < 1:
        raise ValueError("lookback must be positive")
    short = series.rolling(short_window, min_periods=short_window).mean()
    long = series.rolling(long_window, min_periods=long_window).mean()
    difference = short.sub(long).dropna()
    if len(difference) < 2:
        return float("nan")
    recent_targets = set(difference.index[-lookback:])
    latest_direction = 0.0
    for position in range(1, len(difference)):
        if difference.index[position] not in recent_targets:
            continue
        previous = float(difference.iloc[position - 1])
        current = float(difference.iloc[position])
        if previous <= 0.0 < current:
            latest_direction = 1.0
        elif previous >= 0.0 > current:
            latest_direction = -1.0
    return latest_direction


def _crossover(
    series: pd.Series,
    short_window: int,
    long_window: int,
    timestamp: pd.Timestamp,
) -> float:
    through_date = series.loc[:timestamp]
    if through_date.empty or through_date.index[-1] != timestamp:
        return float("nan")
    return recent_moving_average_crossover(
        through_date,
        short_window=short_window,
        long_window=long_window,
        lookback=5,
    )


def _normalized_performance(prices: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for symbol in _BENCHMARKS:
        values = _series(prices, symbol).tail(126)
        if values.empty:
            continue
        frames.append(
            pd.DataFrame(
                {
                    "date": values.index,
                    "symbol": symbol,
                    "value": values.div(float(values.iloc[0])).mul(100.0).to_numpy(),
                }
            )
        )
    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "value"])
    return pd.concat(frames, ignore_index=True)


def _ratio_series(prices: pd.DataFrame, numerator: str) -> pd.Series:
    aligned = pd.concat(
        [_series(prices, numerator), _series(prices, "QQQ")],
        axis="columns",
        join="inner",
    ).dropna()
    if aligned.empty:
        return pd.Series(dtype="float64", name=f"{numerator}/QQQ")
    ratio = aligned.iloc[:, 0].div(aligned.iloc[:, 1])
    ratio.name = f"{numerator}/QQQ"
    return ratio


def _relative_strength(
    prices: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    frames: list[pd.DataFrame] = []
    ratios: dict[str, pd.Series] = {}
    for numerator, _ in _RATIO_DEFINITIONS:
        ratio = _ratio_series(prices, numerator)
        ratios[numerator] = ratio
        output = ratio.tail(126)
        if output.empty:
            continue
        base = float(output.iloc[0])
        frames.append(
            pd.DataFrame(
                {
                    "date": output.index,
                    "symbol": f"{numerator}/QQQ",
                    "ratio": output.to_numpy(),
                    "value": output.div(base).mul(100.0).to_numpy(),
                    "sma_20": ratio.rolling(20, min_periods=20)
                    .mean()
                    .reindex(output.index)
                    .div(base)
                    .mul(100.0)
                    .to_numpy(),
                    "sma_50": ratio.rolling(50, min_periods=50)
                    .mean()
                    .reindex(output.index)
                    .div(base)
                    .mul(100.0)
                    .to_numpy(),
                }
            )
        )
    if not frames:
        columns = ["date", "symbol", "ratio", "value", "sma_20", "sma_50"]
        return pd.DataFrame(columns=columns), ratios
    return pd.concat(frames, ignore_index=True), ratios


def _price_matrix(prices: pd.DataFrame, symbols: tuple[str, ...]) -> pd.DataFrame:
    selected = prices.loc[prices["symbol"].isin(symbols)]
    if selected.empty:
        return pd.DataFrame(columns=list(symbols), dtype="float64")
    matrix = selected.pivot(index="date", columns="symbol", values="adj_close")
    matrix = matrix.reindex(columns=list(symbols)).sort_index()
    matrix.columns.name = None
    return matrix


def _canonical_sessions(prices: pd.DataFrame) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(_series(prices, "SMH").index)


def _canonical_series(
    prices: pd.DataFrame,
    symbol: str,
    sessions: pd.DatetimeIndex,
    column: str = "adj_close",
) -> pd.Series:
    """Place a requested symbol on SMH sessions without filling observations."""

    values = _series(prices, symbol, column).reindex(sessions)
    values.name = symbol
    return values


def _breadth(
    prices: pd.DataFrame,
    symbols: tuple[str, ...],
) -> pd.DataFrame:
    smh_sessions = _series(prices, "SMH").index
    matrix = _price_matrix(prices, symbols).reindex(smh_sessions)
    columns = ["date", "covered_count", "missing_count"]
    for window in (20, 50, 200):
        columns.extend(
            [
                f"above_{window}_pct",
                f"above_{window}_count",
                f"covered_{window}_count",
                f"missing_{window}_count",
            ]
        )
    if matrix.empty:
        return pd.DataFrame(columns=columns)

    output = pd.DataFrame(index=matrix.index)
    output["covered_count"] = matrix.notna().sum(axis="columns")
    output["missing_count"] = len(symbols) - output["covered_count"]
    for window in (20, 50, 200):
        average = matrix.rolling(window, min_periods=window).mean()
        available = matrix.notna() & average.notna()
        above = matrix.gt(average) & available
        denominator = available.sum(axis="columns")
        numerator = above.sum(axis="columns")
        output[f"above_{window}_pct"] = numerator.div(
            denominator.where(denominator.ne(0))
        ).mul(100.0)
        output[f"above_{window}_count"] = numerator
        output[f"covered_{window}_count"] = denominator
        output[f"missing_{window}_count"] = len(symbols) - denominator
    return output.tail(126).reset_index(names="date").loc[:, columns]


def _participation(
    prices: pd.DataFrame,
    symbols: tuple[str, ...],
) -> pd.DataFrame:
    smh = _series(prices, "SMH")
    columns = [
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
    if smh.empty:
        return pd.DataFrame(columns=columns)

    timeline = smh.index[-64:]
    matrix = _price_matrix(prices, symbols).reindex(timeline)
    covered_count = matrix.notna().sum(axis="columns")
    if len(timeline) < 64:
        return pd.DataFrame(
            {
                "date": timeline,
                "watchlist_median_cumulative_return": float("nan"),
                "smh_cumulative_return": float("nan"),
                "spread": float("nan"),
                "outperforming_smh_pct": float("nan"),
                "dispersion": float("nan"),
                "covered_count": covered_count.to_numpy(),
                "eligible_count": 0,
                "missing_count": len(symbols),
                "supported": False,
            }
        ).loc[:, columns]

    baseline = matrix.iloc[0]
    cumulative = matrix.div(baseline).sub(1.0)
    smh_window = smh.reindex(timeline)
    smh_cumulative = smh_window.div(float(smh_window.iloc[0])).sub(1.0)
    median = cumulative.median(axis="columns", skipna=True)
    dispersion = cumulative.quantile(0.75, axis="columns") - cumulative.quantile(
        0.25, axis="columns"
    )
    available = cumulative.notna() & smh_cumulative.notna().to_numpy()[:, None]
    outperforming = cumulative.gt(smh_cumulative, axis="index") & available
    denominator = available.sum(axis="columns")
    outperforming_pct = outperforming.sum(axis="columns").div(
        denominator.where(denominator.ne(0))
    ).mul(100.0)
    supported = smh_cumulative.notna() & denominator.gt(0)
    return pd.DataFrame(
        {
            "date": timeline,
            "watchlist_median_cumulative_return": median.to_numpy(),
            "smh_cumulative_return": smh_cumulative.to_numpy(),
            "spread": median.sub(smh_cumulative).to_numpy(),
            "outperforming_smh_pct": outperforming_pct.to_numpy(),
            "dispersion": dispersion.to_numpy(),
            "covered_count": covered_count.to_numpy(),
            "eligible_count": denominator.to_numpy(),
            "missing_count": len(symbols) - denominator.to_numpy(),
            "supported": supported.to_numpy(),
        }
    ).loc[:, columns]


def _current_symbol_metric(
    prices: pd.DataFrame,
    symbol: str,
    metric: str,
    timestamp: pd.Timestamp,
    sessions: pd.DatetimeIndex,
) -> float:
    values = _canonical_series(prices, symbol, sessions)
    if metric.startswith("return_"):
        return _at(_return(values, int(metric.removeprefix("return_"))), timestamp)
    window = int(metric.removeprefix("distance_sma_"))
    return _at(_distance_from_average(values, window), timestamp)


def _momentum(
    prices: pd.DataFrame,
    symbols: tuple[str, ...],
    timestamp: pd.Timestamp,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    rows = [
        {
            "symbol": symbol,
            "return_20": _current_symbol_metric(
                prices, symbol, "return_20", timestamp, sessions
            ),
        }
        for symbol in symbols
    ]
    output = pd.DataFrame(rows, columns=["symbol", "return_20"])
    output["supported"] = np.isfinite(output["return_20"])
    output["eligible"] = output["supported"]
    output = output.sort_values(
        ["return_20", "symbol"],
        ascending=[False, True],
        na_position="last",
        kind="stable",
    ).reset_index(drop=True)
    eligible_count = int(output["eligible"].sum())
    ranks = pd.array([pd.NA] * len(output), dtype="Int64")
    ranks[:eligible_count] = np.arange(1, eligible_count + 1)
    output["rank"] = ranks
    return output.loc[
        :, ["symbol", "return_20", "supported", "eligible", "rank"]
    ]


def _trend_heatmap(
    prices: pd.DataFrame,
    symbols: tuple[str, ...],
    timestamp: pd.Timestamp,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol_order, symbol in enumerate(symbols):
        for metric_order, metric in enumerate(_TREND_METRICS):
            value = _current_symbol_metric(
                prices, symbol, metric, timestamp, sessions
            )
            rows.append(
                {
                    "symbol": symbol,
                    "metric": metric,
                    "value": value,
                    "supported": isfinite(value),
                    "symbol_order": symbol_order,
                    "metric_order": metric_order,
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "symbol",
            "metric",
            "value",
            "supported",
            "symbol_order",
            "metric_order",
        ],
    )


def _risk_regime(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    smh = _series(prices, "SMH")
    columns = ["date", "volatility_20", "drawdown_63", "vix"]
    if smh.empty:
        return pd.DataFrame(columns=columns), pd.Series(dtype="float64")
    volatility = annualized_realized_volatility(smh)
    drawdown = max_drawdown(smh)
    vix = _series(prices, "^VIX")
    output = pd.DataFrame(
        {
            "date": smh.index,
            "volatility_20": volatility.to_numpy(),
            "drawdown_63": drawdown.to_numpy(),
            "vix": vix.reindex(smh.index).to_numpy(),
        }
    )
    return output.tail(252).reset_index(drop=True), volatility


def _midrank_percentile(values: pd.Series, current: float) -> float:
    available = values.dropna().to_numpy(dtype="float64")
    if not isfinite(current) or len(available) == 0:
        return float("nan")
    less = float(np.count_nonzero(available < current))
    equal = float(np.count_nonzero(available == current))
    return (less + 0.5 * equal) / len(available) * 100.0


def _risk_reward(
    prices: pd.DataFrame,
    symbols: tuple[str, ...],
    timestamp: pd.Timestamp,
    sessions: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, float, float]:
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        adjusted = _canonical_series(prices, symbol, sessions)
        close = _canonical_series(prices, symbol, sessions, "close")
        volume = _canonical_series(prices, symbol, sessions, "volume")
        dollar_volume = close.mul(volume).rolling(20, min_periods=20).median()
        rows.append(
            {
                "symbol": symbol,
                "return_63": _at(_return(adjusted, 63), timestamp),
                "volatility_20": _at(
                    annualized_realized_volatility(adjusted), timestamp
                ),
                "dollar_volume_20": _at(dollar_volume, timestamp),
            }
        )
    output = pd.DataFrame(
        rows,
        columns=["symbol", "return_63", "volatility_20", "dollar_volume_20"],
    )
    output["xy_supported"] = np.isfinite(output["return_63"]) & np.isfinite(
        output["volatility_20"]
    )
    output["liquidity_supported"] = np.isfinite(
        output["dollar_volume_20"]
    ) & output["dollar_volume_20"].gt(0.0)
    complete = output.loc[output["xy_supported"]]
    return_median = _as_float(complete["return_63"].median())
    vol_median = _as_float(complete["volatility_20"].median())

    def quadrant(row: pd.Series) -> str:
        if not bool(row["xy_supported"]):
            return "unsupported"
        return_value = _as_float(row["return_63"])
        vol_value = _as_float(row["volatility_20"])
        if return_value >= return_median and vol_value <= vol_median:
            return "higher-return/lower-vol"
        if return_value >= return_median:
            return "higher-return/higher-vol"
        if vol_value <= vol_median:
            return "lower-return/lower-vol"
        return "lower-return/higher-vol"

    output["quadrant"] = output.apply(quadrant, axis="columns")
    return (
        output.loc[
            :,
            [
                "symbol",
                "return_63",
                "volatility_20",
                "dollar_volume_20",
                "xy_supported",
                "liquidity_supported",
                "quadrant",
            ],
        ],
        return_median,
        vol_median,
    )


def _distribution_scalars(values: pd.Series) -> tuple[float, float, float]:
    available = values.dropna()
    if available.empty:
        return float("nan"), float("nan"), float("nan")
    median = _as_float(available.median())
    iqr = _as_float(available.quantile(0.75) - available.quantile(0.25))
    positive = float(available.gt(0.0).mean() * 100.0)
    return median, iqr, positive


def _build_scalars(
    prices: pd.DataFrame,
    ratios: Mapping[str, pd.Series],
    breadth: pd.DataFrame,
    participation: pd.DataFrame,
    momentum: pd.DataFrame,
    trend_heatmap: pd.DataFrame,
    volatility: pd.Series,
    risk_regime: pd.DataFrame,
    risk_reward: pd.DataFrame,
    risk_reward_medians: tuple[float, float],
    timestamp: pd.Timestamp,
) -> Mapping[str, float]:
    scalars = {
        key: 0.0 if key in _ZERO_DEFAULT_SCALARS else float("nan")
        for key in SCALAR_KEYS
    }
    scalars["participation_missing_count"] = float(len(momentum))
    for symbol, prefix in zip(_BENCHMARKS, _BENCHMARK_PREFIXES, strict=True):
        values = _series(prices, symbol)
        for periods in (5, 20, 63):
            scalars[f"{prefix}_return_{periods}"] = _at(
                _return(values, periods), timestamp
            )
        scalars[f"{prefix}_slope_20"] = _slope(values, 20, timestamp)
        for window in (20, 50):
            scalars[f"{prefix}_distance_sma_{window}"] = _at(
                _distance_from_average(values, window), timestamp
            )
        scalars[f"{prefix}_drawdown_63"] = _at(
            max_drawdown(values), timestamp
        )

    for numerator, prefix in _RATIO_DEFINITIONS:
        ratio = ratios.get(numerator, pd.Series(dtype="float64"))
        for periods in (20, 63):
            scalars[f"{prefix}_return_{periods}"] = _at(
                _return(ratio, periods), timestamp
            )
        for window in (20, 50):
            scalars[f"{prefix}_distance_sma_{window}"] = _at(
                _distance_from_average(ratio, window), timestamp
            )
        crossover = _crossover(ratio, 20, 50, timestamp)
        scalars[f"{prefix}_crossover_20_50"] = crossover
        scalars[f"{prefix}_crossover_20_50_supported"] = float(
            isfinite(crossover)
        )

    if not breadth.empty:
        latest_breadth = breadth.loc[breadth["date"] == timestamp]
        if not latest_breadth.empty:
            latest_row = latest_breadth.iloc[-1]
            for window in (20, 50, 200):
                column = f"above_{window}_pct"
                scalars[f"breadth_{column}"] = _as_float(latest_row[column])
                scalars[f"breadth_covered_{window}_count"] = _as_float(
                    latest_row[f"covered_{window}_count"]
                )
                history = breadth.loc[breadth["date"].le(timestamp), column]
                if len(history) >= 6:
                    current = _as_float(history.iloc[-1])
                    previous = _as_float(history.iloc[-6])
                    if isfinite(current) and isfinite(previous):
                        scalars[f"breadth_{window}_change_5"] = current - previous

    if not participation.empty:
        latest_participation = participation.loc[
            participation["date"] == timestamp
        ]
        if not latest_participation.empty:
            latest_row = latest_participation.iloc[-1]
            scalars["participation_spread_63"] = _as_float(latest_row["spread"])
            scalars["participation_outperforming_smh_pct"] = _as_float(
                latest_row["outperforming_smh_pct"]
            )
            scalars["participation_dispersion_63"] = _as_float(
                latest_row["dispersion"]
            )
            scalars["participation_eligible_count"] = _as_float(
                latest_row["eligible_count"]
            )
            scalars["participation_missing_count"] = _as_float(
                latest_row["missing_count"]
            )
            scalars["participation_supported"] = float(
                bool(latest_row["supported"])
            )

    momentum_median, momentum_iqr, momentum_positive = _distribution_scalars(
        momentum["return_20"]
    )
    scalars["momentum_median_20"] = momentum_median
    scalars["momentum_iqr_20"] = momentum_iqr
    scalars["momentum_positive_pct"] = momentum_positive
    momentum_eligible_count = int(momentum["eligible"].sum())
    scalars["momentum_eligible_count"] = float(momentum_eligible_count)
    scalars["momentum_missing_count"] = float(
        len(momentum) - momentum_eligible_count
    )

    supported_trends = trend_heatmap.loc[trend_heatmap["supported"], "value"]
    if not supported_trends.empty:
        scalars["trend_positive_cell_pct"] = float(
            supported_trends.gt(0.0).mean() * 100.0
        )
    trend_supported_count = int(trend_heatmap["supported"].sum())
    trend_missing_count = len(trend_heatmap) - trend_supported_count
    scalars["trend_unsupported_cells"] = float(trend_missing_count)
    scalars["trend_supported_cells"] = float(trend_supported_count)
    scalars["trend_missing_cells"] = float(trend_missing_count)

    current_volatility = _at(volatility, timestamp)
    scalars["smh_vol_20"] = current_volatility
    scalars["smh_vol_percentile_252"] = _midrank_percentile(
        volatility.loc[:timestamp].dropna().tail(252), current_volatility
    )
    scalars["smh_vol_change_5"] = _at(volatility.diff(5), timestamp)
    if not risk_regime.empty:
        latest_risk = risk_regime.loc[risk_regime["date"] == timestamp]
        if not latest_risk.empty:
            scalars["vix_latest"] = _as_float(latest_risk.iloc[-1]["vix"])

    scalars["risk_reward_return_median_63"] = risk_reward_medians[0]
    scalars["risk_reward_vol_median_20"] = risk_reward_medians[1]
    xy_eligible_count = int(risk_reward["xy_supported"].sum())
    liquidity_eligible_count = int(risk_reward["liquidity_supported"].sum())
    scalars["risk_reward_xy_eligible_count"] = float(xy_eligible_count)
    scalars["risk_reward_xy_missing_count"] = float(
        len(risk_reward) - xy_eligible_count
    )
    scalars["risk_reward_liquidity_eligible_count"] = float(
        liquidity_eligible_count
    )
    scalars["risk_reward_liquidity_missing_count"] = float(
        len(risk_reward) - liquidity_eligible_count
    )
    return MappingProxyType(scalars)


def compute_metrics(
    prices: pd.DataFrame,
    watchlist_symbols: Sequence[str],
    as_of: date,
) -> MetricBundle:
    """Compute deterministic chart data and evidence as of one market date.

    Window judgments are deliberately explicit: period returns require that
    many canonical SMH intervals; rolling averages/volatility require full
    periods; the displayed performance and breadth histories are capped at 126
    dates. Participation uses 64 SMH observations for a true t/t-63 return. A
    symbol missing the shared participation baseline or current observation
    remains unsupported rather than rebasing on a different date. Watchlist
    calculations are reindexed to SMH sessions without filling; benchmark/QQQ
    ratios instead retain their exact common-date intersection.
    """

    symbols = _symbols(watchlist_symbols)
    prepared = _prepare_prices(prices, as_of)
    timestamp = pd.Timestamp(as_of)
    sessions = _canonical_sessions(prepared)

    normalized_performance = _normalized_performance(prepared)
    relative_strength, ratios = _relative_strength(prepared)
    breadth = _breadth(prepared, symbols)
    participation = _participation(prepared, symbols)
    momentum = _momentum(prepared, symbols, timestamp, sessions)
    trend_heatmap = _trend_heatmap(prepared, symbols, timestamp, sessions)
    risk_regime, volatility = _risk_regime(prepared)
    risk_reward, return_median, vol_median = _risk_reward(
        prepared, symbols, timestamp, sessions
    )
    scalars = _build_scalars(
        prepared,
        ratios,
        breadth,
        participation,
        momentum,
        trend_heatmap,
        volatility,
        risk_regime,
        risk_reward,
        (return_median, vol_median),
        timestamp,
    )

    return MetricBundle(
        methodology_version=METRICS_VERSION,
        as_of=as_of,
        normalized_performance=normalized_performance,
        relative_strength=relative_strength,
        breadth=breadth,
        participation=participation,
        momentum=momentum,
        trend_heatmap=trend_heatmap,
        risk_regime=risk_regime,
        risk_reward=risk_reward,
        scalars=scalars,
    )
