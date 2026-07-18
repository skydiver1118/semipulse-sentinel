"""Deterministic, colorblind-safe styling shared by SVG renderers."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

FIGURE_BACKGROUND: Final = "#0B132B"
PANEL_BACKGROUND: Final = "#F8FAFC"
TEXT_COLOR: Final = "#172033"
MUTED_COLOR: Final = "#526079"
GRID_COLOR: Final = "#CBD5E1"
POSITIVE_COLOR: Final = "#0072B2"
NEGATIVE_COLOR: Final = "#D55E00"
NEUTRAL_COLOR: Final = "#6B7280"
UNAVAILABLE_COLOR: Final = "#D1D5DB"


@dataclass(frozen=True, slots=True)
class SeriesStyle:
    """A color plus redundant line/marker encoding."""

    color: str
    linestyle: str
    marker: str


BENCHMARK_STYLES = MappingProxyType(
    {
        "SMH": SeriesStyle("#0072B2", "-", "o"),
        "SOXX": SeriesStyle("#E69F00", "--", "s"),
        "QQQ": SeriesStyle("#009E73", "-.", "^"),
        "SOXL": SeriesStyle("#CC79A7", ":", "D"),
    }
)

RATIO_STYLES = MappingProxyType(
    {
        "value": SeriesStyle("#0072B2", "-", "o"),
        "sma_20": SeriesStyle("#E69F00", "--", "s"),
        "sma_50": SeriesStyle("#009E73", "-.", "^"),
    }
)

BREADTH_STYLES = MappingProxyType(
    {
        20: SeriesStyle("#0072B2", "-", "o"),
        50: SeriesStyle("#E69F00", "--", "s"),
        200: SeriesStyle("#009E73", "-.", "^"),
    }
)

QUADRANT_STYLES = MappingProxyType(
    {
        "higher-return/lower-vol": SeriesStyle("#009E73", "", "o"),
        "higher-return/higher-vol": SeriesStyle("#E69F00", "", "^"),
        "lower-return/lower-vol": SeriesStyle("#56B4E9", "", "s"),
        "lower-return/higher-vol": SeriesStyle("#D55E00", "", "D"),
    }
)

RC_PARAMS = MappingProxyType(
    {
        "axes.edgecolor": MUTED_COLOR,
        "axes.facecolor": PANEL_BACKGROUND,
        "axes.labelcolor": TEXT_COLOR,
        "axes.titlecolor": TEXT_COLOR,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "figure.facecolor": FIGURE_BACKGROUND,
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "grid.color": GRID_COLOR,
        "grid.linewidth": 0.7,
        "grid.alpha": 0.65,
        "legend.frameon": False,
        "savefig.facecolor": FIGURE_BACKGROUND,
        "text.color": TEXT_COLOR,
        "xtick.color": MUTED_COLOR,
        "ytick.color": MUTED_COLOR,
    }
)
