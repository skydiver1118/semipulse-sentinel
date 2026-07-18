"""Exactly eight deterministic, accessible SVG chart renderers."""

# Matplotlib's noninteractive backend must be selected before importing pyplot.
# ruff: noqa: E402

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast
from xml.etree import ElementTree

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["svg.fonttype"] = "none"
matplotlib.rcParams["svg.hashsalt"] = "semipulse-sentinel-v1"

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from matplotlib.axes import Axes
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from numpy.typing import NDArray

from semipulse_sentinel.metrics import MetricBundle
from semipulse_sentinel.models import ChartArtifact, ChartInsight
from semipulse_sentinel.style import (
    BENCHMARK_STYLES,
    BREADTH_STYLES,
    FIGURE_BACKGROUND,
    GRID_COLOR,
    MUTED_COLOR,
    NEGATIVE_COLOR,
    NEUTRAL_COLOR,
    PANEL_BACKGROUND,
    POSITIVE_COLOR,
    QUADRANT_STYLES,
    RATIO_STYLES,
    RC_PARAMS,
    TEXT_COLOR,
    UNAVAILABLE_COLOR,
)

_SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
_REQUIRED_BENCHMARKS = ("SMH", "SOXX", "QQQ", "SOXL")
_RATIO_SYMBOLS = ("SMH/QQQ", "SOXX/QQQ")
_TREND_METRICS = (
    "return_5",
    "return_20",
    "return_63",
    "distance_sma_20",
    "distance_sma_50",
    "distance_sma_200",
)
_TREND_LABELS = (
    "5d return",
    "20d return",
    "63d return",
    "vs 20d SMA",
    "vs 50d SMA",
    "vs 200d SMA",
)


class ChartContractError(ValueError):
    """Raised before or during rendering when chart inputs violate the contract."""


@dataclass(frozen=True, slots=True)
class ChartSpec:
    """Stable identity, dimensions, and redundant encoding for one chart."""

    chart_id: str
    filename: str
    title: str
    description: str
    figsize: tuple[float, float]
    non_color_encodings: tuple[str, ...]

    @property
    def has_non_color_encoding(self) -> bool:
        """Return whether the tested specification declares real redundancy."""

        return bool(self.non_color_encodings) and all(
            bool(item.strip()) for item in self.non_color_encodings
        )


CHART_SPECS: tuple[ChartSpec, ...] = (
    ChartSpec(
        "chart-1",
        "chart-01-complex-performance.svg",
        "1. Semiconductor complex performance",
        "Four benchmark series indexed to 100 over the latest 126 sessions.",
        (12.0, 6.4),
        ("line dash", "point marker", "direct end label"),
    ),
    ChartSpec(
        "chart-2",
        "chart-02-relative-strength.svg",
        "2. Relative strength versus QQQ",
        "SMH/QQQ and SOXX/QQQ ratios with 20- and 50-session averages.",
        (12.0, 8.0),
        ("line dash", "point marker", "panel label"),
    ),
    ChartSpec(
        "chart-3",
        "chart-03-breadth.svg",
        "3. Watchlist breadth",
        "Percent of eligible watchlist members above three moving averages.",
        (12.0, 6.8),
        ("line dash", "point marker", "window label"),
    ),
    ChartSpec(
        "chart-4",
        "chart-04-participation.svg",
        "4. Equal-weight participation",
        "Median constituent return versus SMH and their percentage-point spread.",
        (12.0, 8.0),
        ("line dash", "point marker", "separate spread panel"),
    ),
    ChartSpec(
        "chart-5",
        "chart-05-momentum.svg",
        "5. Momentum leaders and laggards",
        "Supported 20-session returns sorted from strongest to weakest.",
        (12.0, 8.0),
        ("filled versus hatched bar", "signed value label"),
    ),
    ChartSpec(
        "chart-6",
        "chart-06-trend-heatmap.svg",
        "6. Multi-horizon trend heatmap",
        "Six signed trend metrics per symbol with unsupported cells disclosed.",
        (12.0, 10.5),
        ("signed cell label", "hatched unsupported cell"),
    ),
    ChartSpec(
        "chart-7",
        "chart-07-risk-regime.svg",
        "7. Volatility and peak-distance regime",
        "Realized volatility, distance from a rolling peak, and optional VIX.",
        (12.0, 9.0),
        ("separate labeled panel", "line marker", "reference line"),
    ),
    ChartSpec(
        "chart-8",
        "chart-08-risk-reward.svg",
        "8. Risk/reward map",
        "63-session return versus annualized volatility with liquidity context.",
        (12.0, 8.0),
        ("quadrant marker shape", "direct symbol label", "open liquidity marker"),
    ),
)


def _slug(value: object) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return slug or "unknown"


def _numbers(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce").astype("float64")


def _dates(frame: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(frame["date"], errors="coerce")


def _finite_values(values: pd.Series | Sequence[float]) -> NDArray[np.float64]:
    result = cast(NDArray[np.float64], np.asarray(values, dtype="float64"))
    return result[np.isfinite(result)]


def _latest(values: pd.Series | Sequence[float]) -> float | None:
    """Return only the final supplied observation when it is finite."""

    observations = np.asarray(values, dtype="float64")
    if observations.size == 0 or not np.isfinite(observations[-1]):
        return None
    return float(observations[-1])


def _last_valid_observation(
    dates: pd.Series,
    values: pd.Series,
) -> tuple[str, float] | None:
    """Return a clearly historical fallback without treating it as current."""

    date_values = pd.to_datetime(dates, errors="coerce")
    numeric_values = pd.to_numeric(values, errors="coerce").astype("float64")
    valid = date_values.notna() & np.isfinite(numeric_values)
    if not valid.any():
        return None
    position = int(np.flatnonzero(valid.to_numpy())[-1])
    timestamp = pd.Timestamp(date_values.iloc[position]).strftime("%Y-%m-%d")
    return timestamp, float(numeric_values.iloc[position])


def _format_number(
    value: float | None,
    *,
    digits: int = 1,
    signed: bool = False,
    suffix: str = "",
) -> str:
    if value is None or not np.isfinite(value):
        return "unavailable"
    sign = "+" if signed else ""
    return f"{value:{sign}.{digits}f}{suffix}"


def _integer(value: object) -> str:
    try:
        converted = float(str(value))
    except (TypeError, ValueError):
        return "unavailable"
    return str(int(converted)) if np.isfinite(converted) else "unavailable"


def _require_columns(name: str, frame: pd.DataFrame, columns: Sequence[str]) -> None:
    missing = tuple(column for column in columns if column not in frame.columns)
    if missing:
        raise ChartContractError(f"{name} missing chart columns: {', '.join(missing)}")


def _preflight(metrics: MetricBundle, insights: Sequence[ChartInsight]) -> None:
    expected_ids = tuple(f"chart-{number}" for number in range(1, 9))
    actual_ids = tuple(item.chart_id for item in insights)
    if actual_ids != expected_ids:
        raise ChartContractError(
            "rendering requires exactly eight ordered chart insights "
            f"{expected_ids}; received {actual_ids}"
        )
    if tuple(item.chart_id for item in CHART_SPECS) != expected_ids:
        raise ChartContractError("chart specification registry is not canonical")
    if len(RENDERERS) != len(CHART_SPECS):
        raise ChartContractError("renderer registry must match chart specifications")
    if len({item.filename for item in CHART_SPECS}) != 8:
        raise ChartContractError("chart filenames must be unique")

    contracts: Mapping[str, tuple[str, ...]] = MappingProxyType(
        {
            "normalized_performance": ("date", "symbol", "value"),
            "relative_strength": (
                "date",
                "symbol",
                "value",
                "sma_20",
                "sma_50",
            ),
            "breadth": (
                "date",
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
            ),
            "participation": (
                "date",
                "watchlist_median_cumulative_return",
                "smh_cumulative_return",
                "spread",
                "outperforming_smh_pct",
                "eligible_count",
                "missing_count",
                "supported",
            ),
            "momentum": ("symbol", "return_20", "supported"),
            "trend_heatmap": (
                "symbol",
                "metric",
                "value",
                "supported",
                "symbol_order",
                "metric_order",
            ),
            "risk_regime": ("date", "volatility_20", "drawdown_63", "vix"),
            "risk_reward": (
                "symbol",
                "return_63",
                "volatility_20",
                "dollar_volume_20",
                "xy_supported",
                "liquidity_supported",
                "quadrant",
            ),
        }
    )
    for name, columns in contracts.items():
        _require_columns(name, metrics.datasets[name], columns)

    performance = metrics.normalized_performance
    missing_benchmarks = tuple(
        symbol
        for symbol in _REQUIRED_BENCHMARKS
        if not (
            performance["symbol"].astype(str).eq(symbol)
            & np.isfinite(pd.to_numeric(performance["value"], errors="coerce"))
        ).any()
    )
    if missing_benchmarks:
        raise ChartContractError(
            "required benchmark data unavailable: " + ", ".join(missing_benchmarks)
        )

    relative = metrics.relative_strength
    missing_ratios = tuple(
        symbol
        for symbol in _RATIO_SYMBOLS
        if not (
            relative["symbol"].astype(str).eq(symbol)
            & np.isfinite(pd.to_numeric(relative["value"], errors="coerce"))
        ).any()
    )
    if missing_ratios:
        raise ChartContractError(
            "required relative-strength data unavailable: " + ", ".join(missing_ratios)
        )
    heatmap = metrics.trend_heatmap
    if heatmap.duplicated(["symbol", "metric"]).any():
        raise ChartContractError("trend heatmap contains duplicate symbol/metric cells")


def _copy_metrics(metrics: MetricBundle) -> MetricBundle:
    return MetricBundle(
        methodology_version=metrics.methodology_version,
        as_of=metrics.as_of,
        normalized_performance=metrics.normalized_performance.copy(deep=True),
        relative_strength=metrics.relative_strength.copy(deep=True),
        breadth=metrics.breadth.copy(deep=True),
        participation=metrics.participation.copy(deep=True),
        momentum=metrics.momentum.copy(deep=True),
        trend_heatmap=metrics.trend_heatmap.copy(deep=True),
        risk_regime=metrics.risk_regime.copy(deep=True),
        risk_reward=metrics.risk_reward.copy(deep=True),
        scalars=MappingProxyType(dict(metrics.scalars)),
    )


@contextmanager
def _chart_style() -> Iterator[None]:
    with matplotlib.rc_context(cast(Any, dict(RC_PARAMS))):
        yield


def _style_axis(
    ax: Axes, *, grid_axis: Literal["both", "x", "y", "none"] = "both"
) -> None:
    ax.set_facecolor(PANEL_BACKGROUND)
    ax.set_axisbelow(True)
    if grid_axis != "none":
        ax.grid(
            True,
            axis=grid_axis,
            color=GRID_COLOR,
            linewidth=0.7,
            alpha=0.65,
        )
    for spine in ax.spines.values():
        spine.set_color(MUTED_COLOR)


def _date_axis(ax: Axes) -> None:
    locator = mdates.AutoDateLocator(  # type: ignore[no-untyped-call]
        minticks=4, maxticks=8
    )
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(
        mdates.ConciseDateFormatter(locator)  # type: ignore[no-untyped-call]
    )


def _finish_figure(fig: Figure, spec: ChartSpec) -> None:
    fig.suptitle(
        spec.title,
        color="white",
        fontsize=16,
        fontweight="bold",
        x=0.04,
        y=0.985,
        horizontalalignment="left",
    )
    fig.text(
        0.04,
        0.95,
        spec.description,
        color="#D8E1F0",
        fontsize=9,
        horizontalalignment="left",
    )
    fig.tight_layout(rect=(0.025, 0.035, 0.985, 0.925))


def _safe_limits(
    ax: Axes,
    values: Sequence[float] | pd.Series,
    *,
    axis: str,
    include: Sequence[float] = (),
    minimum_pad: float = 1.0,
) -> None:
    finite = list(_finite_values(values))
    finite.extend(float(value) for value in include if np.isfinite(value))
    if not finite:
        return
    low = min(finite)
    high = max(finite)
    span = high - low
    pad = max(span * 0.08, abs(low) * 0.03, abs(high) * 0.03, minimum_pad)
    if axis == "x":
        ax.set_xlim(low - pad, high + pad)
    elif axis == "y":
        ax.set_ylim(low - pad, high + pad)
    else:
        raise ValueError("axis must be x or y")


def _plot_line(
    ax: Axes,
    dates: pd.Series,
    values: pd.Series,
    *,
    label: str,
    gid: str,
    color: str,
    linestyle: str,
    marker: str,
    linewidth: float = 2.0,
) -> Line2D:
    markevery = max(len(values) // 9, 1)
    (line,) = ax.plot(
        dates,
        values,
        label=label,
        color=color,
        linestyle=linestyle,
        marker=marker,
        markevery=markevery,
        markersize=4.0,
        linewidth=linewidth,
    )
    line.set_gid(gid)
    return line


def _insight_alt(spec: ChartSpec, insight: ChartInsight, observation: str) -> str:
    return f"{spec.title}. {observation} {insight.headline}".strip()


def render_complex_performance(
    metrics: MetricBundle, insight: ChartInsight, spec: ChartSpec
) -> tuple[Figure, str]:
    frame = metrics.normalized_performance.copy(deep=True)
    with _chart_style():
        fig, ax = plt.subplots(figsize=spec.figsize)
        _style_axis(ax)
        latest_parts: list[str] = []
        for symbol in _REQUIRED_BENCHMARKS:
            selected = frame.loc[frame["symbol"].astype(str).eq(symbol)].copy()
            selected = selected.sort_values("date", kind="stable")
            style = BENCHMARK_STYLES[symbol]
            label = "SOXL (3x leveraged)" if symbol == "SOXL" else symbol
            values = _numbers(selected, "value")
            dates = _dates(selected)
            _plot_line(
                ax,
                dates,
                values,
                label=label,
                gid=f"chart-1-{symbol.lower()}-line",
                color=style.color,
                linestyle=style.linestyle,
                marker=style.marker,
            )
            latest = _latest(values)
            latest_parts.append(f"{symbol} {_format_number(latest)}")
            finite_mask = np.isfinite(values) & dates.notna()
            if finite_mask.any() and latest is not None:
                last_index = selected.index[finite_mask][-1]
                annotation = ax.annotate(
                    label,
                    (dates.loc[last_index], values.loc[last_index]),
                    xytext=(6, 0),
                    textcoords="offset points",
                    color=style.color,
                    fontsize=8,
                    va="center",
                )
                annotation.set_gid(f"chart-1-{symbol.lower()}-end-label")
        reference = ax.axhline(100.0, color=MUTED_COLOR, linestyle="--", linewidth=1.0)
        reference.set_gid("chart-1-index-100-reference")
        ax.set_ylabel("Indexed value (start = 100)")
        ax.set_xlabel("Market session")
        _date_axis(ax)
        ax.legend(loc="upper left", ncols=4)
        _finish_figure(fig, spec)
    alt = _insight_alt(
        spec,
        insight,
        "Latest indexed values: " + ", ".join(latest_parts) + ".",
    )
    return fig, alt


def render_relative_strength(
    metrics: MetricBundle, insight: ChartInsight, spec: ChartSpec
) -> tuple[Figure, str]:
    frame = metrics.relative_strength.copy(deep=True)
    latest_parts: list[str] = []
    with _chart_style():
        fig, axes = plt.subplots(2, 1, sharex=True, figsize=spec.figsize)
        for ax, symbol in zip(axes, _RATIO_SYMBOLS, strict=True):
            _style_axis(ax)
            selected = frame.loc[frame["symbol"].astype(str).eq(symbol)].copy()
            selected = selected.sort_values("date", kind="stable")
            dates = _dates(selected)
            for column, label in (
                ("value", "Ratio indexed"),
                ("sma_20", "20-session SMA"),
                ("sma_50", "50-session SMA"),
            ):
                style = RATIO_STYLES[column]
                _plot_line(
                    ax,
                    dates,
                    _numbers(selected, column),
                    label=label,
                    gid=f"chart-2-{_slug(symbol)}-{column.replace('_', '-')}",
                    color=style.color,
                    linestyle=style.linestyle,
                    marker=style.marker,
                )
            reference = ax.axhline(
                100.0, color=MUTED_COLOR, linestyle=":", linewidth=1.0
            )
            reference.set_gid(f"chart-2-{_slug(symbol)}-100-reference")
            ax.set_title(symbol, loc="left")
            ax.set_ylabel("Indexed ratio")
            ax.legend(loc="upper left", ncols=3)
            latest_parts.append(
                f"{symbol} {_format_number(_latest(_numbers(selected, 'value')))}"
            )
        axes[-1].set_xlabel("Market session")
        _date_axis(axes[-1])
        _finish_figure(fig, spec)
    return fig, _insight_alt(
        spec,
        insight,
        "Latest indexed ratios: " + ", ".join(latest_parts) + ".",
    )


def render_breadth(
    metrics: MetricBundle, insight: ChartInsight, spec: ChartSpec
) -> tuple[Figure, str]:
    frame = metrics.breadth.copy(deep=True).sort_values("date", kind="stable")
    latest_row = frame.iloc[-1] if not frame.empty else pd.Series(dtype="object")
    summary_parts: list[str] = []
    unavailable: list[str] = []
    with _chart_style():
        fig, ax = plt.subplots(figsize=spec.figsize)
        _style_axis(ax)
        dates = _dates(frame)
        for window in (20, 50, 200):
            column = f"above_{window}_pct"
            values = _numbers(frame, column)
            style = BREADTH_STYLES[window]
            _plot_line(
                ax,
                dates,
                values,
                label=f"Above {window}-session SMA",
                gid=f"chart-3-breadth-{window}",
                color=style.color,
                linestyle=style.linestyle,
                marker=style.marker,
            )
            latest = _latest(values)
            numerator = _integer(latest_row.get(f"above_{window}_count"))
            denominator = _integer(latest_row.get(f"covered_{window}_count"))
            missing = _integer(latest_row.get(f"missing_{window}_count"))
            summary_parts.append(
                f"{window}-session {_format_number(latest, suffix='%')} "
                f"({numerator}/{denominator}; missing {missing})"
            )
            if latest is None:
                unavailable.append(f"{window}-session unavailable")
        reference = ax.axhline(50.0, color=MUTED_COLOR, linestyle=":", linewidth=1.0)
        reference.set_gid("chart-3-fifty-percent-reference")
        ax.set_ylim(0.0, 100.0)
        ax.set_ylabel("Eligible symbols above average (%)")
        ax.set_xlabel("Market session")
        _date_axis(ax)
        ax.legend(loc="upper left", ncols=3)
        latest_text = "Latest: " + "; ".join(summary_parts)
        ax.text(
            0.01,
            0.02,
            latest_text,
            transform=ax.transAxes,
            fontsize=8,
            color=TEXT_COLOR,
            bbox={"facecolor": "white", "edgecolor": GRID_COLOR, "alpha": 0.9},
        ).set_gid("chart-3-latest-denominators")
        if unavailable:
            ax.text(
                0.99,
                0.02,
                "; ".join(unavailable),
                transform=ax.transAxes,
                ha="right",
                fontsize=8,
                color=NEGATIVE_COLOR,
            )
        _finish_figure(fig, spec)
    return fig, _insight_alt(
        spec, insight, "Latest breadth: " + "; ".join(summary_parts) + "."
    )


def render_participation(
    metrics: MetricBundle, insight: ChartInsight, spec: ChartSpec
) -> tuple[Figure, str]:
    frame = metrics.participation.copy(deep=True).sort_values("date", kind="stable")
    latest_row = frame.iloc[-1] if not frame.empty else pd.Series(dtype="object")
    eligible = _integer(latest_row.get("eligible_count"))
    missing = _integer(latest_row.get("missing_count"))
    outperform = _latest(_numbers(frame, "outperforming_smh_pct"))
    with _chart_style():
        fig, axes = plt.subplots(
            2,
            1,
            sharex=True,
            figsize=spec.figsize,
            gridspec_kw={"height_ratios": (2.0, 1.0)},
        )
        for ax in axes:
            _style_axis(ax)
        dates = _dates(frame)
        median_values = _numbers(frame, "watchlist_median_cumulative_return") * 100.0
        smh_values = _numbers(frame, "smh_cumulative_return") * 100.0
        spread = _numbers(frame, "spread") * 100.0
        _plot_line(
            axes[0],
            dates,
            median_values,
            label="Median constituent",
            gid="chart-4-median-constituent",
            color=POSITIVE_COLOR,
            linestyle="-",
            marker="o",
        )
        _plot_line(
            axes[0],
            dates,
            smh_values,
            label="SMH",
            gid="chart-4-smh",
            color="#E69F00",
            linestyle="--",
            marker="s",
        )
        _plot_line(
            axes[1],
            dates,
            spread,
            label="Median minus SMH",
            gid="chart-4-participation-spread",
            color="#009E73",
            linestyle="-.",
            marker="^",
        )
        zero = axes[1].axhline(0.0, color=MUTED_COLOR, linestyle=":", linewidth=1.0)
        zero.set_gid("chart-4-zero-reference")
        axes[0].set_ylabel("63-session cumulative return (%)")
        axes[1].set_ylabel("Spread (percentage points)")
        axes[1].set_xlabel("Market session")
        axes[0].legend(loc="upper left", ncols=2)
        axes[1].legend(loc="upper left")
        _date_axis(axes[1])
        disclosure = (
            f"Outperforming SMH {_format_number(outperform, suffix='%')}; "
            f"Eligible {eligible}; missing {missing}"
        )
        axes[0].text(
            0.99,
            0.03,
            disclosure,
            transform=axes[0].transAxes,
            ha="right",
            fontsize=8,
            bbox={"facecolor": "white", "edgecolor": GRID_COLOR, "alpha": 0.9},
        ).set_gid("chart-4-participation-disclosure")
        if not np.isfinite(median_values).any() or not np.isfinite(smh_values).any():
            axes[0].text(
                0.5,
                0.5,
                f"Participation unavailable - Eligible {eligible}; missing {missing}",
                transform=axes[0].transAxes,
                ha="center",
                color=NEGATIVE_COLOR,
            )
        _finish_figure(fig, spec)
    spread_latest = _latest(spread)
    spread_text = _format_number(
        spread_latest,
        signed=True,
        suffix=" percentage points",
    )
    outperform_text = _format_number(outperform, suffix="%")
    return fig, _insight_alt(
        spec,
        insight,
        f"Latest median-minus-SMH spread {spread_text}; outperforming "
        f"{outperform_text}; eligible {eligible}, missing {missing}.",
    )


def render_momentum(
    metrics: MetricBundle, insight: ChartInsight, spec: ChartSpec
) -> tuple[Figure, str]:
    frame = metrics.momentum.copy(deep=True)
    values = _numbers(frame, "return_20")
    supported_mask = frame["supported"].fillna(False).astype(bool) & np.isfinite(values)
    supported = frame.loc[supported_mask].copy()
    supported["return_20"] = values.loc[supported_mask]
    supported = supported.sort_values(
        ["return_20", "symbol"], ascending=[False, True], kind="stable"
    ).reset_index(drop=True)
    unsupported = tuple(
        sorted(frame.loc[~supported_mask, "symbol"].astype(str).tolist())
    )
    percentages = _numbers(supported, "return_20") * 100.0
    with _chart_style():
        fig, ax = plt.subplots(figsize=spec.figsize)
        _style_axis(ax, grid_axis="x")
        positions = np.arange(len(supported), dtype="float64")
        for position, (_, row) in zip(positions, supported.iterrows(), strict=True):
            value = float(row["return_20"]) * 100.0
            positive = value >= 0.0
            bars = ax.barh(
                [position],
                [value],
                color=POSITIVE_COLOR if positive else "white",
                edgecolor=POSITIVE_COLOR if positive else NEGATIVE_COLOR,
                hatch="" if positive else "///",
                linewidth=1.2,
            )
            bars.patches[0].set_gid(f"chart-5-bar-{_slug(row['symbol'])}")
            offset = 3 if positive else -3
            ha = "left" if positive else "right"
            label = ax.annotate(
                f"{value:+.1f}%",
                (value, position),
                xytext=(offset, 0),
                textcoords="offset points",
                ha=ha,
                va="center",
                fontsize=8,
                color=TEXT_COLOR,
            )
            label.set_gid(f"chart-5-label-{_slug(row['symbol'])}")
        ax.axvline(0.0, color=MUTED_COLOR, linestyle=":", linewidth=1.0).set_gid(
            "chart-5-zero-reference"
        )
        ax.set_yticks(positions, supported["symbol"].astype(str).tolist())
        ax.invert_yaxis()
        ax.set_xlabel("20-session adjusted return (%)")
        if len(supported):
            _safe_limits(ax, percentages, axis="x", include=(0.0,), minimum_pad=1.0)
        else:
            ax.text(
                0.5,
                0.5,
                "Momentum unavailable: no supported 20-session returns",
                transform=ax.transAxes,
                ha="center",
                color=NEGATIVE_COLOR,
            )
        unsupported_text = (
            "Unsupported: " + ", ".join(unsupported)
            if unsupported
            else "Unsupported: none"
        )
        ax.text(
            0.01,
            -0.10,
            unsupported_text,
            transform=ax.transAxes,
            fontsize=8,
            color=MUTED_COLOR,
            wrap=True,
        ).set_gid("chart-5-unsupported-list")
        _finish_figure(fig, spec)
    strongest = (
        f"{supported.iloc[0]['symbol']} {percentages.iloc[0]:+.1f}%"
        if len(supported)
        else "unavailable"
    )
    weakest = (
        f"{supported.iloc[-1]['symbol']} {percentages.iloc[-1]:+.1f}%"
        if len(supported)
        else "unavailable"
    )
    return fig, _insight_alt(
        spec,
        insight,
        f"{len(supported)} supported symbols; strongest {strongest}; "
        f"weakest {weakest}; {unsupported_text}.",
    )


def render_trend_heatmap(
    metrics: MetricBundle, insight: ChartInsight, spec: ChartSpec
) -> tuple[Figure, str]:
    frame = metrics.trend_heatmap.copy(deep=True)
    frame = frame.sort_values(["symbol_order", "metric_order"], kind="stable")
    symbols = tuple(frame["symbol"].astype(str).drop_duplicates().tolist())
    lookup = frame.set_index(["symbol", "metric"], drop=False)
    values = np.full((len(symbols), len(_TREND_METRICS)), np.nan, dtype="float64")
    supported = np.zeros_like(values, dtype=bool)
    for row_index, symbol in enumerate(symbols):
        for column_index, metric in enumerate(_TREND_METRICS):
            key = (symbol, metric)
            if key not in lookup.index:
                continue
            row = lookup.loc[key]
            value = pd.to_numeric(row["value"], errors="coerce")
            is_supported = bool(row["supported"]) and bool(np.isfinite(value))
            if is_supported:
                values[row_index, column_index] = float(value) * 100.0
                supported[row_index, column_index] = True
    finite = values[supported]
    if finite.size:
        low, high = np.quantile(finite, (0.05, 0.95))
        bound = max(abs(float(low)), abs(float(high)), 1.0)
    else:
        bound = 1.0
    plotted = np.ma.masked_invalid(np.clip(values, -bound, bound))
    cmap = LinearSegmentedColormap.from_list(
        "semipulse-diverging", (NEGATIVE_COLOR, "#FFFFFF", POSITIVE_COLOR)
    ).with_extremes(bad=UNAVAILABLE_COLOR)
    with _chart_style():
        fig, ax = plt.subplots(figsize=spec.figsize)
        _style_axis(ax, grid_axis="none")
        image = ax.pcolormesh(
            np.arange(len(_TREND_METRICS) + 1, dtype="float64") - 0.5,
            np.arange(len(symbols) + 1, dtype="float64") - 0.5,
            plotted,
            shading="flat",
            cmap=cmap,
            norm=Normalize(vmin=-bound, vmax=bound),
        )
        image.set_gid("chart-6-heatmap")
        ax.set_xlim(-0.5, len(_TREND_METRICS) - 0.5)
        ax.set_ylim(len(symbols) - 0.5, -0.5)
        for row_index, symbol in enumerate(symbols):
            for column_index, metric in enumerate(_TREND_METRICS):
                cell_id = f"chart-6-cell-{_slug(symbol)}-{_slug(metric)}"
                if supported[row_index, column_index]:
                    value = values[row_index, column_index]
                    color = "white" if abs(value) > bound * 0.58 else TEXT_COLOR
                    text = ax.text(
                        column_index,
                        row_index,
                        f"{value:+.1f}%",
                        ha="center",
                        va="center",
                        fontsize=7,
                        color=color,
                    )
                    text.set_gid(cell_id)
                else:
                    rectangle = Rectangle(
                        (column_index - 0.5, row_index - 0.5),
                        1.0,
                        1.0,
                        facecolor=UNAVAILABLE_COLOR,
                        edgecolor=NEUTRAL_COLOR,
                        hatch="xx",
                        linewidth=0.8,
                    )
                    rectangle.set_gid(cell_id)
                    ax.add_patch(rectangle)
                    ax.text(
                        column_index,
                        row_index,
                        "-",
                        ha="center",
                        va="center",
                        color=TEXT_COLOR,
                        fontweight="bold",
                    )
        ax.set_xticks(
            np.arange(len(_TREND_METRICS)), _TREND_LABELS, rotation=25, ha="right"
        )
        ax.set_yticks(np.arange(len(symbols)), symbols)
        ax.set_xlabel("Metric (labels are actual values; color is winsorized)")
        ax.set_ylabel("Watchlist symbol")
        colorbar = fig.colorbar(image, ax=ax, pad=0.015, fraction=0.035)
        colorbar.set_label("Percent (%)")
        colorbar.ax.set_gid("chart-6-color-scale")
        _finish_figure(fig, spec)
    supported_count = int(supported.sum())
    total_count = int(supported.size)
    if finite.size:
        strongest_index = np.unravel_index(np.nanargmax(values), values.shape)
        weakest_index = np.unravel_index(np.nanargmin(values), values.shape)
        strongest = (
            f"{symbols[strongest_index[0]]} {_TREND_LABELS[strongest_index[1]]} "
            f"{values[strongest_index]:+.1f}%"
        )
        weakest = (
            f"{symbols[weakest_index[0]]} {_TREND_LABELS[weakest_index[1]]} "
            f"{values[weakest_index]:+.1f}%"
        )
    else:
        strongest = weakest = "unavailable"
    return fig, _insight_alt(
        spec,
        insight,
        f"{supported_count}/{total_count} cells supported; strongest "
        f"{strongest}; weakest {weakest}.",
    )


def render_risk_regime(
    metrics: MetricBundle, insight: ChartInsight, spec: ChartSpec
) -> tuple[Figure, str]:
    frame = metrics.risk_regime.copy(deep=True).sort_values("date", kind="stable")
    dates = _dates(frame)
    volatility = _numbers(frame, "volatility_20") * 100.0
    peak_distance = _numbers(frame, "drawdown_63") * 100.0
    vix = _numbers(frame, "vix")
    current_vix = _latest(vix)
    last_valid_vix = _last_valid_observation(dates, vix)
    if current_vix is None:
        visible_vix_status = "Current VIX unavailable"
        alt_vix_status = "VIX current unavailable"
        if last_valid_vix is not None:
            last_date, last_value = last_valid_vix
            visible_vix_status += f"; Last valid {last_date}: {last_value:.1f}"
            alt_vix_status += f"; last valid {last_date} {last_value:.1f}"
    else:
        visible_vix_status = f"Current VIX {current_vix:.1f}"
        alt_vix_status = f"VIX current {current_vix:.1f}"
    with _chart_style():
        fig, axes = plt.subplots(3, 1, sharex=True, figsize=spec.figsize)
        for ax in axes:
            _style_axis(ax)
        _plot_line(
            axes[0],
            dates,
            volatility,
            label="SMH realized volatility",
            gid="chart-7-volatility-line",
            color=POSITIVE_COLOR,
            linestyle="-",
            marker="o",
        )
        _plot_line(
            axes[1],
            dates,
            peak_distance,
            label="SMH peak distance",
            gid="chart-7-peak-distance-line",
            color=NEGATIVE_COLOR,
            linestyle="--",
            marker="s",
        )
        zero = axes[1].axhline(0.0, color=MUTED_COLOR, linestyle=":", linewidth=1.0)
        zero.set_gid("chart-7-zero-distance-reference")
        if np.isfinite(vix).any():
            _plot_line(
                axes[2],
                dates,
                vix,
                label="VIX",
                gid="chart-7-vix-line",
                color="#CC79A7",
                linestyle="-.",
                marker="^",
            )
            axes[2].legend(loc="upper left")
            if current_vix is None:
                axes[2].text(
                    0.99,
                    0.88,
                    visible_vix_status,
                    transform=axes[2].transAxes,
                    ha="right",
                    va="top",
                    color=NEGATIVE_COLOR,
                    fontsize=8,
                    fontweight="bold",
                ).set_gid("chart-7-vix-current-unavailable")
        else:
            axes[2].text(
                0.5,
                0.5,
                visible_vix_status,
                transform=axes[2].transAxes,
                ha="center",
                va="center",
                color=NEGATIVE_COLOR,
                fontweight="bold",
            ).set_gid("chart-7-vix-unavailable")
        axes[0].set_ylabel("Annualized volatility (%)")
        axes[1].set_ylabel("Distance from rolling 63-session peak (%)")
        axes[2].set_ylabel("VIX level")
        axes[2].set_xlabel("Market session")
        axes[0].legend(loc="upper left")
        axes[1].legend(loc="lower left")
        _date_axis(axes[2])
        _safe_limits(axes[0], volatility, axis="y", minimum_pad=1.0)
        _safe_limits(axes[1], peak_distance, axis="y", include=(0.0,), minimum_pad=1.0)
        if np.isfinite(vix).any():
            _safe_limits(axes[2], vix, axis="y", minimum_pad=1.0)
        _finish_figure(fig, spec)
    peak_text = _format_number(_latest(peak_distance), signed=True, suffix="%")
    return fig, _insight_alt(
        spec,
        insight,
        f"Latest SMH volatility {_format_number(_latest(volatility), suffix='%')}; "
        f"distance from rolling peak {peak_text}; {alt_vix_status}.",
    )


def _quadrant(
    return_value: float, volatility: float, med_return: float, med_vol: float
) -> str:
    if return_value >= med_return and volatility <= med_vol:
        return "higher-return/lower-vol"
    if return_value >= med_return:
        return "higher-return/higher-vol"
    if volatility <= med_vol:
        return "lower-return/lower-vol"
    return "lower-return/higher-vol"


def _bubble_areas(liquidity: pd.Series, supported: pd.Series) -> pd.Series:
    areas = pd.Series(110.0, index=liquidity.index, dtype="float64")
    valid = liquidity.loc[supported]
    if valid.empty:
        return areas
    low = float(valid.min())
    high = float(valid.max())
    areas.loc[supported] = valid.map(
        lambda value: _bubble_area(float(value), low=low, high=high)
    )
    return areas


def _bubble_area(value: float, *, low: float, high: float) -> float:
    if high == low:
        return 260.0
    return 90.0 + 410.0 * (value - low) / (high - low)


def _format_dollar_volume(value: float) -> str:
    if value >= 1_000_000_000.0:
        return f"${value / 1_000_000_000.0:.1f}B"
    if value >= 1_000_000.0:
        return f"${value / 1_000_000.0:.0f}M"
    if value >= 1_000.0:
        return f"${value / 1_000.0:.0f}K"
    return f"${value:.0f}"


def render_risk_reward(
    metrics: MetricBundle, insight: ChartInsight, spec: ChartSpec
) -> tuple[Figure, str]:
    frame = metrics.risk_reward.copy(deep=True)
    returns = _numbers(frame, "return_63") * 100.0
    volatility = _numbers(frame, "volatility_20") * 100.0
    xy = (
        frame["xy_supported"].fillna(False).astype(bool)
        & np.isfinite(returns)
        & np.isfinite(volatility)
    )
    supported = frame.loc[xy].copy()
    supported["return_pct"] = returns.loc[xy]
    supported["volatility_pct"] = volatility.loc[xy]
    supported = supported.sort_values("symbol", kind="stable")
    liquidity = _numbers(supported, "dollar_volume_20")
    liquidity_supported = (
        supported["liquidity_supported"].fillna(False).astype(bool)
        & np.isfinite(liquidity)
        & liquidity.gt(0.0)
    )
    areas = _bubble_areas(liquidity, liquidity_supported)
    valid_liquidity = liquidity.loc[liquidity_supported]
    liquidity_key_values: tuple[float, ...] = ()
    liquidity_low: float | None = None
    liquidity_high: float | None = None
    if not valid_liquidity.empty:
        liquidity_low = float(valid_liquidity.min())
        liquidity_high = float(valid_liquidity.max())
        liquidity_key_values = tuple(
            dict.fromkeys(
                (
                    liquidity_low,
                    float(valid_liquidity.median()),
                    liquidity_high,
                )
            )
        )
    return_median = (
        _latest([float(supported["return_pct"].median())]) if len(supported) else None
    )
    vol_median = (
        _latest([float(supported["volatility_pct"].median())])
        if len(supported)
        else None
    )
    unsupported = tuple(sorted(frame.loc[~xy, "symbol"].astype(str).tolist()))
    no_liquidity = tuple(
        supported.loc[~liquidity_supported, "symbol"].astype(str).tolist()
    )
    with _chart_style():
        fig, ax = plt.subplots(figsize=spec.figsize)
        _style_axis(ax)
        if return_median is not None and vol_median is not None:
            x_reference = ax.axvline(
                vol_median, color=MUTED_COLOR, linestyle="--", linewidth=1.0
            )
            x_reference.set_gid("chart-8-volatility-median-reference")
            y_reference = ax.axhline(
                return_median, color=MUTED_COLOR, linestyle="--", linewidth=1.0
            )
            y_reference.set_gid("chart-8-return-median-reference")
        zero = ax.axhline(0.0, color=NEUTRAL_COLOR, linestyle=":", linewidth=1.0)
        zero.set_gid("chart-8-zero-return-reference")
        for index, row in supported.iterrows():
            return_value = float(row["return_pct"])
            vol_value = float(row["volatility_pct"])
            if return_median is None or vol_median is None:
                continue
            quadrant = _quadrant(return_value, vol_value, return_median, vol_median)
            style = QUADRANT_STYLES[quadrant]
            has_liquidity = bool(liquidity_supported.loc[index])
            point = ax.scatter(
                [vol_value],
                [return_value],
                s=float(areas.loc[index]),
                marker=style.marker,
                facecolors=style.color if has_liquidity else "none",
                edgecolors=style.color,
                linewidths=1.4,
                alpha=0.82 if has_liquidity else 1.0,
            )
            point.set_gid(f"chart-8-point-{_slug(row['symbol'])}")
            label = ax.annotate(
                str(row["symbol"]),
                (vol_value, return_value),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=8,
                color=TEXT_COLOR,
                fontweight="bold",
            )
            label.set_gid(f"chart-8-label-{_slug(row['symbol'])}")
        ax.set_xlabel("20-session annualized volatility (%)")
        ax.set_ylabel("63-session return (%)")
        if len(supported):
            _safe_limits(
                ax,
                supported["volatility_pct"],
                axis="x",
                minimum_pad=1.0,
            )
            _safe_limits(
                ax,
                supported["return_pct"],
                axis="y",
                include=(0.0,),
                minimum_pad=1.0,
            )
        else:
            ax.text(
                0.5,
                0.5,
                "Risk/reward map unavailable: no XY-supported symbols",
                transform=ax.transAxes,
                ha="center",
                color=NEGATIVE_COLOR,
            )
        ax.text(
            0.01,
            0.98,
            "Bubble area = median 20-session dollar volume\n"
            "Open fill + fixed area = liquidity unavailable",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=8,
            color=TEXT_COLOR,
            bbox={"facecolor": "white", "edgecolor": GRID_COLOR, "alpha": 0.9},
        ).set_gid("chart-8-liquidity-encoding-note")
        legend_handles = [
            Line2D(
                [],
                [],
                linestyle="",
                marker=style.marker,
                markerfacecolor=style.color,
                markeredgecolor=style.color,
                label=quadrant.replace("/", " / "),
            )
            for quadrant, style in QUADRANT_STYLES.items()
        ]
        if no_liquidity:
            legend_handles.append(
                Line2D(
                    [],
                    [],
                    linestyle="",
                    marker="o",
                    markerfacecolor="none",
                    markeredgecolor=NEUTRAL_COLOR,
                    label=(
                        "Open fill + fixed area = liquidity unavailable; "
                        "shape still shows quadrant"
                    ),
                )
            )
        quadrant_legend = ax.legend(
            handles=legend_handles,
            loc="upper right",
            fontsize=7,
            title="Quadrant shape + color",
        )
        quadrant_legend.set_gid("chart-8-quadrant-key")
        ax.add_artist(quadrant_legend)
        if (
            liquidity_key_values
            and liquidity_low is not None
            and liquidity_high is not None
        ):
            size_handles = [
                Line2D(
                    [],
                    [],
                    linestyle="",
                    marker="o",
                    markerfacecolor="none",
                    markeredgecolor=NEUTRAL_COLOR,
                    markersize=float(
                        np.sqrt(
                            _bubble_area(
                                value,
                                low=liquidity_low,
                                high=liquidity_high,
                            )
                        )
                    ),
                    label=_format_dollar_volume(value),
                )
                for value in liquidity_key_values
            ]
            size_legend = ax.legend(
                handles=size_handles,
                loc="lower right",
                fontsize=7,
                title="Liquidity size key",
            )
            size_legend.set_gid("chart-8-liquidity-size-key")
        disclosures: list[str] = []
        if no_liquidity:
            disclosures.append("Liquidity unavailable: " + ", ".join(no_liquidity))
        if unsupported:
            disclosures.append("XY unsupported: " + ", ".join(unsupported))
        if disclosures:
            ax.text(
                0.01,
                0.02,
                "; ".join(disclosures),
                transform=ax.transAxes,
                fontsize=8,
                color=MUTED_COLOR,
                bbox={"facecolor": "white", "edgecolor": GRID_COLOR, "alpha": 0.9},
            ).set_gid("chart-8-missing-disclosure")
        _finish_figure(fig, spec)
    return fig, _insight_alt(
        spec,
        insight,
        f"{len(supported)} XY-supported symbols; median return "
        f"{_format_number(return_median, signed=True, suffix='%')}; median volatility "
        f"{_format_number(vol_median, suffix='%')}. Bubble area represents median "
        "20-session dollar volume; open fill with fixed area marks liquidity "
        f"unavailable for {len(no_liquidity)} symbols while shape retains quadrant.",
    )


Renderer = Callable[[MetricBundle, ChartInsight, ChartSpec], tuple[Figure, str]]

RENDERERS: tuple[Renderer, ...] = (
    render_complex_performance,
    render_relative_strength,
    render_breadth,
    render_participation,
    render_momentum,
    render_trend_heatmap,
    render_risk_regime,
    render_risk_reward,
)


def _inject_accessibility(path: Path, spec: ChartSpec, alt_text: str) -> None:
    ElementTree.register_namespace("", _SVG_NAMESPACE)
    ElementTree.register_namespace("xlink", _XLINK_NAMESPACE)
    ElementTree.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    ElementTree.register_namespace("cc", "http://creativecommons.org/ns#")
    ElementTree.register_namespace("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    tree = ElementTree.parse(path)
    root = tree.getroot()
    root.set("role", "img")
    title_id = f"{spec.chart_id}-svg-title"
    description_id = f"{spec.chart_id}-svg-desc"
    root.set("aria-labelledby", f"{title_id} {description_id}")
    title = ElementTree.Element(f"{{{_SVG_NAMESPACE}}}title", {"id": title_id})
    title.text = spec.title
    description = ElementTree.Element(
        f"{{{_SVG_NAMESPACE}}}desc", {"id": description_id}
    )
    description.text = alt_text
    root.insert(0, title)
    root.insert(1, description)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def render_charts(
    metrics: MetricBundle,
    insights: Sequence[ChartInsight],
    output_dir: Path,
) -> tuple[ChartArtifact, ...]:
    """Render eight stable SVGs into the caller-provided staging directory."""

    _preflight(metrics, insights)
    local_metrics = _copy_metrics(metrics)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[ChartArtifact] = []
    for spec, renderer, insight in zip(CHART_SPECS, RENDERERS, insights, strict=True):
        existing_figures = set(plt.get_fignums())
        try:
            figure, alt_text = renderer(local_metrics, insight, spec)
            path = output_dir / spec.filename
            figure.savefig(
                path,
                format="svg",
                facecolor=FIGURE_BACKGROUND,
                edgecolor="none",
                metadata={"Date": None, "Creator": "SemiPulse Sentinel"},
            )
            _inject_accessibility(path, spec, alt_text)
            artifacts.append(
                ChartArtifact(
                    chart_id=spec.chart_id,
                    path=path,
                    alt_text=alt_text,
                    has_non_color_encoding=spec.has_non_color_encoding,
                )
            )
        finally:
            for number in set(plt.get_fignums()) - existing_figures:
                plt.close(number)
    return tuple(artifacts)
