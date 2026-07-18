"""Rendering, accessibility, and determinism contracts for all eight charts."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from types import MappingProxyType
from xml.etree import ElementTree

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from matplotlib.figure import Figure
from pandas.testing import assert_frame_equal

from semipulse_sentinel.charts import (
    CHART_SPECS,
    RENDERERS,
    ChartContractError,
    render_charts,
)
from semipulse_sentinel.metrics import METRICS_VERSION, MetricBundle
from semipulse_sentinel.models import ChartInsight

AS_OF = date(2025, 7, 2)
EXPECTED_FILENAMES = [
    "chart-01-complex-performance.svg",
    "chart-02-relative-strength.svg",
    "chart-03-breadth.svg",
    "chart-04-participation.svg",
    "chart-05-momentum.svg",
    "chart-06-trend-heatmap.svg",
    "chart-07-risk-regime.svg",
    "chart-08-risk-reward.svg",
]


def _insights() -> tuple[ChartInsight, ...]:
    return tuple(
        ChartInsight(
            chart_id=f"chart-{number}",
            headline=f"Observed chart {number} evidence is mixed.",
            signal="mixed",
            evidence=(f"Chart {number} evidence is measured, not forecast.",),
            interpretation="The observed series supplies market context.",
            trading_relevance="Use with explicit invalidation conditions.",
            counter_signal="A reversal in the plotted evidence would challenge it.",
            notes=("Unsupported observations remain disclosed.",),
        )
        for number in range(1, 9)
    )


def _bundle() -> MetricBundle:
    dates = pd.bdate_range(end=AS_OF, periods=126)
    benchmark_rows: list[dict[str, object]] = []
    benchmark_offsets = {"SMH": 16.0, "SOXX": 11.0, "QQQ": 7.0, "SOXL": 31.0}
    for symbol, end_gain in benchmark_offsets.items():
        values = np.linspace(100.0, 100.0 + end_gain, len(dates))
        values += np.sin(np.linspace(0.0, 7.0, len(dates)))
        for timestamp, value in zip(dates, values, strict=True):
            benchmark_rows.append({"date": timestamp, "symbol": symbol, "value": value})

    relative_rows: list[dict[str, object]] = []
    for offset, symbol in enumerate(("SMH/QQQ", "SOXX/QQQ")):
        values = np.linspace(100.0, 106.0 - offset, len(dates))
        sma_20 = pd.Series(values).rolling(20).mean().to_numpy()
        sma_50 = pd.Series(values).rolling(50).mean().to_numpy()
        for index, timestamp in enumerate(dates):
            relative_rows.append(
                {
                    "date": timestamp,
                    "symbol": symbol,
                    "ratio": values[index] / 100.0,
                    "value": values[index],
                    "sma_20": sma_20[index],
                    "sma_50": sma_50[index],
                }
            )

    breadth = pd.DataFrame({"date": dates})
    for window, start, end, numerator, denominator in (
        (20, 42.0, 68.0, 15, 22),
        (50, 38.0, 59.0, 13, 22),
        (200, 30.0, 50.0, 10, 20),
    ):
        breadth[f"above_{window}_pct"] = np.linspace(start, end, len(dates))
        breadth[f"above_{window}_count"] = numerator
        breadth[f"covered_{window}_count"] = denominator
        breadth[f"missing_{window}_count"] = 23 - denominator
    breadth["covered_count"] = 22
    breadth["missing_count"] = 1

    participation_dates = dates[-64:]
    smh_return = np.linspace(0.0, 0.12, 64)
    median_return = np.linspace(0.0, 0.15, 64)
    participation = pd.DataFrame(
        {
            "date": participation_dates,
            "watchlist_median_cumulative_return": median_return,
            "smh_cumulative_return": smh_return,
            "spread": median_return - smh_return,
            "outperforming_smh_pct": np.linspace(45.0, 61.0, 64),
            "dispersion": np.linspace(0.02, 0.08, 64),
            "covered_count": 22,
            "eligible_count": 21,
            "missing_count": 2,
            "supported": True,
        }
    )

    momentum = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC", "UNS"],
            "return_20": [0.18, 0.04, -0.09, np.nan],
            "supported": [True, True, True, False],
            "eligible": [True, True, True, False],
            "rank": pd.array([1, 2, 3, pd.NA], dtype="Int64"),
        }
    )

    trend_metrics = (
        "return_5",
        "return_20",
        "return_63",
        "distance_sma_20",
        "distance_sma_50",
        "distance_sma_200",
    )
    trend_rows: list[dict[str, object]] = []
    trend_values = {
        "AAA": (0.03, 0.18, 0.28, 0.04, 0.08, 0.12),
        "BBB": (-0.01, 0.04, 0.11, 0.01, 0.02, 0.05),
        "CCC": (0.02, -0.09, -0.16, -0.04, -0.08, -0.13),
        "UNS": (np.nan,) * 6,
    }
    for symbol_order, (symbol, values) in enumerate(trend_values.items()):
        for metric_order, (metric, value) in enumerate(
            zip(trend_metrics, values, strict=True)
        ):
            trend_rows.append(
                {
                    "symbol": symbol,
                    "metric": metric,
                    "value": value,
                    "supported": bool(np.isfinite(value)),
                    "symbol_order": symbol_order,
                    "metric_order": metric_order,
                }
            )

    risk_regime = pd.DataFrame(
        {
            "date": dates,
            "volatility_20": np.linspace(0.18, 0.31, len(dates)),
            "drawdown_63": np.linspace(-0.01, -0.08, len(dates)),
            "vix": np.linspace(15.0, 23.0, len(dates)),
        }
    )
    risk_reward = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC", "DDD", "UNS"],
            "return_63": [0.28, 0.20, -0.16, 0.11, np.nan],
            "volatility_20": [0.22, 0.49, 0.50, 0.34, np.nan],
            "dollar_volume_20": [
                80_000_000.0,
                30_000_000.0,
                np.nan,
                10_000_000.0,
                np.nan,
            ],
            "xy_supported": [True, True, True, True, False],
            "liquidity_supported": [True, True, False, True, False],
            "quadrant": [
                "higher-return/lower-vol",
                "higher-return/higher-vol",
                "lower-return/higher-vol",
                "lower-return/lower-vol",
                "unsupported",
            ],
        }
    )
    return MetricBundle(
        methodology_version=METRICS_VERSION,
        as_of=AS_OF,
        normalized_performance=pd.DataFrame(benchmark_rows),
        relative_strength=pd.DataFrame(relative_rows),
        breadth=breadth,
        participation=participation,
        momentum=momentum,
        trend_heatmap=pd.DataFrame(trend_rows),
        risk_regime=risk_regime,
        risk_reward=risk_reward,
        scalars=MappingProxyType({}),
    )


def _svg_text(path: Path) -> str:
    return " ".join("".join(ElementTree.parse(path).getroot().itertext()).split())


def _svg_ids(path: Path) -> set[str]:
    return {
        element.attrib["id"]
        for element in ElementTree.parse(path).getroot().iter()
        if "id" in element.attrib
    }


def _by_id(path: Path, element_id: str) -> ElementTree.Element:
    for element in ElementTree.parse(path).getroot().iter():
        if element.attrib.get("id") == element_id:
            return element
    raise AssertionError(f"missing SVG element id: {element_id}")


def _descendant_styles(element: ElementTree.Element) -> str:
    return " ".join(
        child.attrib.get("style", "") for child in element.iter()
    )


def _descendant_paths(element: ElementTree.Element) -> tuple[str, ...]:
    return tuple(
        child.attrib["d"]
        for child in element.iter()
        if child.tag.endswith("path") and "d" in child.attrib
    )


def _has_svg_use(element: ElementTree.Element) -> bool:
    return any(child.tag.endswith("use") for child in element.iter())


def test_renderer_registry_has_fixed_exact_order_and_non_color_contract() -> None:
    assert len(CHART_SPECS) == len(RENDERERS) == 8
    assert [item.chart_id for item in CHART_SPECS] == [
        f"chart-{number}" for number in range(1, 9)
    ]
    assert [item.filename for item in CHART_SPECS] == EXPECTED_FILENAMES
    assert [renderer.__name__ for renderer in RENDERERS] == [
        "render_complex_performance",
        "render_relative_strength",
        "render_breadth",
        "render_participation",
        "render_momentum",
        "render_trend_heatmap",
        "render_risk_regime",
        "render_risk_reward",
    ]
    assert all(item.has_non_color_encoding for item in CHART_SPECS)
    assert all(item.non_color_encodings for item in CHART_SPECS)


def test_renderer_outputs_exactly_eight_valid_accessible_svgs(tmp_path: Path) -> None:
    artifacts = render_charts(_bundle(), _insights(), tmp_path)

    assert len(artifacts) == 8
    assert [item.chart_id for item in artifacts] == [
        f"chart-{number}" for number in range(1, 9)
    ]
    assert [item.path.name for item in artifacts] == EXPECTED_FILENAMES
    assert len({item.alt_text for item in artifacts}) == 8
    for artifact in artifacts:
        root = ElementTree.parse(artifact.path).getroot()
        assert root.tag.endswith("svg")
        assert artifact.path.stat().st_size > 1_000
        assert root.attrib["role"] == "img"
        labelled_by = root.attrib["aria-labelledby"].split()
        ids = _svg_ids(artifact.path)
        assert labelled_by == [
            f"{artifact.chart_id}-svg-title",
            f"{artifact.chart_id}-svg-desc",
        ]
        assert set(labelled_by) <= ids
        assert artifact.alt_text in _svg_text(artifact.path)
        assert artifact.has_non_color_encoding


@pytest.mark.parametrize(
    "bad_insights",
    [
        _insights()[:-1],
        tuple(reversed(_insights())),
        (_insights()[0], *_insights()[0:7]),
        (replace(_insights()[0], chart_id="chart-9"), *_insights()[1:]),
    ],
)
def test_strict_insight_preflight_rejects_before_writing(
    bad_insights: tuple[ChartInsight, ...], tmp_path: Path
) -> None:
    output = tmp_path / "not-created"

    with pytest.raises(ChartContractError, match="ordered chart insights"):
        render_charts(_bundle(), bad_insights, output)

    assert not output.exists()


def test_required_benchmark_preflight_rejects_before_writing(tmp_path: Path) -> None:
    bundle = _bundle()
    without_qqq = replace(
        bundle,
        normalized_performance=bundle.normalized_performance.loc[
            bundle.normalized_performance["symbol"] != "QQQ"
        ].copy(),
    )
    output = tmp_path / "not-created"

    with pytest.raises(ChartContractError, match="QQQ"):
        render_charts(without_qqq, _insights(), output)

    assert not output.exists()


def test_svg_has_stable_series_ids_units_denominators_and_no_external_code(
    tmp_path: Path,
) -> None:
    artifacts = render_charts(_bundle(), _insights(), tmp_path)
    combined = " ".join(_svg_text(item.path) for item in artifacts)

    assert "Indexed value (start = 100)" in combined
    assert "SOXL (3x leveraged)" in combined
    assert "SMH/QQQ" in combined and "SOXX/QQQ" in combined
    assert "15/22" in combined and "13/22" in combined and "10/20" in combined
    breadth_text = _svg_text(artifacts[2].path)
    assert "20-session 68.0% (15/22; missing 1)" in breadth_text
    assert "50-session 59.0% (13/22; missing 1)" in breadth_text
    assert "200-session 50.0% (10/20; missing 3)" in breadth_text
    assert "Eligible 21; missing 2" in combined
    assert "Annualized volatility (%)" in combined
    assert "Distance from rolling 63-session peak (%)" in combined
    assert "63-session return (%)" in combined
    assert "20-session annualized volatility (%)" in combined

    expected_ids = {
        "chart-1-smh-line",
        "chart-1-soxl-line",
        "chart-2-smh-qqq-value",
        "chart-3-breadth-200",
        "chart-4-participation-spread",
        "chart-5-bar-aaa",
        "chart-6-cell-uns-return-5",
        "chart-7-vix-line",
        "chart-8-point-aaa",
    }
    all_ids = set().union(*(_svg_ids(item.path) for item in artifacts))
    assert expected_ids <= all_ids
    for artifact in artifacts:
        root = ElementTree.parse(artifact.path).getroot()
        assert not any(element.tag.endswith("script") for element in root.iter())
        for element in root.iter():
            for key, value in element.attrib.items():
                if key.endswith("href"):
                    assert not value.startswith(("http:", "https:"))


def test_svg_redundant_encodings_are_material_not_only_declared(
    tmp_path: Path,
) -> None:
    artifacts = render_charts(_bundle(), _insights(), tmp_path)

    smh = _by_id(artifacts[0].path, "chart-1-smh-line")
    soxl = _by_id(artifacts[0].path, "chart-1-soxl-line")
    assert _has_svg_use(smh) and _has_svg_use(soxl)
    assert "stroke-dasharray" not in _descendant_styles(smh)
    assert "stroke-dasharray" in _descendant_styles(soxl)

    positive_bar = _by_id(artifacts[4].path, "chart-5-bar-aaa")
    negative_bar = _by_id(artifacts[4].path, "chart-5-bar-ccc")
    assert "fill: #0072b2" in _descendant_styles(positive_bar)
    assert "fill: url(#" in _descendant_styles(negative_bar)
    assert "stroke: #d55e00" in _descendant_styles(negative_bar)

    signed_cell = _by_id(artifacts[5].path, "chart-6-cell-aaa-return-5")
    unavailable_cell = _by_id(artifacts[5].path, "chart-6-cell-uns-return-5")
    assert "+3.0%" in "".join(signed_cell.itertext())
    assert "fill: url(#" in _descendant_styles(unavailable_cell)
    assert "stroke: #6b7280" in _descendant_styles(unavailable_cell)

    circle = _by_id(artifacts[7].path, "chart-8-point-aaa")
    triangle = _by_id(artifacts[7].path, "chart-8-point-bbb")
    open_diamond = _by_id(artifacts[7].path, "chart-8-point-ccc")
    square = _by_id(artifacts[7].path, "chart-8-point-ddd")
    assert any(" C " in path for path in _descendant_paths(circle))
    assert all(" C " not in path for path in _descendant_paths(triangle))
    assert all(" C " not in path for path in _descendant_paths(square))
    assert _descendant_paths(triangle) != _descendant_paths(square)
    assert _descendant_paths(square) != _descendant_paths(open_diamond)
    assert "fill: #e69f00" in _descendant_styles(triangle)
    assert "fill: #56b4e9" in _descendant_styles(square)
    assert "fill: none" in _descendant_styles(open_diamond)
    assert "stroke: #d55e00" in _descendant_styles(open_diamond)


def test_risk_reward_explains_liquidity_area_and_open_fixed_area(
    tmp_path: Path,
) -> None:
    artifact = render_charts(_bundle(), _insights(), tmp_path)[7]
    text = _svg_text(artifact.path)

    assert "Bubble area = median 20-session dollar volume" in text
    assert "Open fill + fixed area = liquidity unavailable" in text
    assert "Liquidity size key" in text
    assert "$10M" in text and "$80M" in text
    assert "bubble area represents median 20-session dollar volume" in (
        artifact.alt_text.lower()
    )
    assert "open fill with fixed area" in artifact.alt_text.lower()


def test_identical_inputs_are_byte_identical_without_volatile_metadata(
    tmp_path: Path,
) -> None:
    first = render_charts(_bundle(), _insights(), tmp_path / "first")
    second = render_charts(_bundle(), _insights(), tmp_path / "second")

    assert [item.path.read_bytes() for item in first] == [
        item.path.read_bytes() for item in second
    ]
    for artifact in first:
        raw = artifact.path.read_text(encoding="utf-8")
        assert "<dc:date>" not in raw
        assert "matplotlib.org" not in raw.lower()
        assert "matplotlib v" not in raw.lower()


def test_missing_optional_series_and_symbols_stay_visibly_unavailable(
    tmp_path: Path,
) -> None:
    bundle = _bundle()
    missing_momentum = bundle.momentum.copy()
    missing_momentum.loc[missing_momentum["symbol"] == "BBB", ["return_20"]] = np.nan
    missing_momentum.loc[
        missing_momentum["symbol"] == "BBB", ["supported", "eligible"]
    ] = False
    missing_heatmap = bundle.trend_heatmap.copy()
    missing_heatmap["value"] = np.nan
    missing_heatmap["supported"] = False
    risk = bundle.risk_regime.copy()
    risk["vix"] = np.nan
    risk_reward = bundle.risk_reward.copy()
    risk_reward["dollar_volume_20"] = np.nan
    risk_reward["liquidity_supported"] = False
    changed = replace(
        bundle,
        momentum=missing_momentum,
        trend_heatmap=missing_heatmap,
        risk_regime=risk,
        risk_reward=risk_reward,
    )

    artifacts = render_charts(changed, _insights(), tmp_path)

    momentum_text = _svg_text(artifacts[4].path)
    heatmap_text = _svg_text(artifacts[5].path)
    risk_text = _svg_text(artifacts[6].path)
    reward_text = _svg_text(artifacts[7].path)
    assert "Unsupported: BBB, UNS" in momentum_text
    assert "-" in heatmap_text and "BBB" in heatmap_text
    assert "VIX unavailable" in risk_text
    assert "Liquidity unavailable" in reward_text
    assert (
        "nan"
        not in " ".join((momentum_text, heatmap_text, risk_text, reward_text)).lower()
    )


def test_breadth_current_disclosure_uses_final_chronological_row_only(
    tmp_path: Path,
) -> None:
    bundle = _bundle()
    breadth = bundle.breadth.sort_values("date", kind="stable").copy()
    final_index = breadth.index[-1]
    for window in (20, 50, 200):
        breadth.loc[final_index, f"above_{window}_pct"] = np.nan
        breadth.loc[final_index, f"above_{window}_count"] = 1
        breadth.loc[final_index, f"covered_{window}_count"] = 7
        breadth.loc[final_index, f"missing_{window}_count"] = 16
    breadth = breadth.iloc[::-1].reset_index(drop=True)

    artifact = render_charts(
        replace(bundle, breadth=breadth), _insights(), tmp_path
    )[2]
    text = _svg_text(artifact.path)

    for window in (20, 50, 200):
        assert f"{window}-session unavailable (1/7; missing 16)" in text
    assert "68.0% (1/7" not in text
    assert "Latest breadth: 20-session unavailable" in artifact.alt_text


def test_participation_current_disclosure_uses_final_row_after_sort(
    tmp_path: Path,
) -> None:
    bundle = _bundle()
    participation = bundle.participation.sort_values("date", kind="stable").copy()
    final_index = participation.index[-1]
    participation.loc[
        final_index,
        [
            "watchlist_median_cumulative_return",
            "smh_cumulative_return",
            "spread",
            "outperforming_smh_pct",
        ],
    ] = np.nan
    participation.loc[final_index, "eligible_count"] = 7
    participation.loc[final_index, "missing_count"] = 16
    participation.loc[final_index, "supported"] = False
    participation = participation.iloc[::-1].reset_index(drop=True)

    artifact = render_charts(
        replace(bundle, participation=participation), _insights(), tmp_path
    )[3]
    text = _svg_text(artifact.path)

    assert "Outperforming SMH unavailable; Eligible 7; missing 16" in text
    assert "Latest median-minus-SMH spread unavailable" in artifact.alt_text
    assert "outperforming unavailable; eligible 7, missing 16" in artifact.alt_text


def test_risk_regime_current_gap_is_not_replaced_by_older_finite_value(
    tmp_path: Path,
) -> None:
    bundle = _bundle()
    risk = bundle.risk_regime.sort_values("date", kind="stable").copy()
    last_valid_date = pd.Timestamp(risk.iloc[-2]["date"]).strftime("%Y-%m-%d")
    last_valid_vix = float(risk.iloc[-2]["vix"])
    final_index = risk.index[-1]
    risk.loc[final_index, ["volatility_20", "drawdown_63", "vix"]] = np.nan
    risk = risk.iloc[::-1].reset_index(drop=True)

    artifact = render_charts(
        replace(bundle, risk_regime=risk), _insights(), tmp_path
    )[6]
    text = _svg_text(artifact.path)

    assert "Current VIX unavailable" in text
    assert f"Last valid {last_valid_date}: {last_valid_vix:.1f}" in text
    assert "Latest SMH volatility unavailable" in artifact.alt_text
    assert "distance from rolling peak unavailable" in artifact.alt_text
    assert "VIX current unavailable" in artifact.alt_text
    assert f"last valid {last_valid_date} {last_valid_vix:.1f}" in artifact.alt_text


def test_all_negative_and_constant_values_use_safe_axes(tmp_path: Path) -> None:
    bundle = _bundle()
    momentum = bundle.momentum.copy()
    supported = momentum["supported"].astype(bool)
    momentum.loc[supported, "return_20"] = [-0.01, -0.01, -0.01]
    reward = bundle.risk_reward.copy()
    xy = reward["xy_supported"].astype(bool)
    reward.loc[xy, "return_63"] = -0.05
    reward.loc[xy, "volatility_20"] = 0.25
    risk = bundle.risk_regime.copy()
    risk["volatility_20"] = 0.2
    risk["drawdown_63"] = -0.03
    changed = replace(bundle, momentum=momentum, risk_reward=reward, risk_regime=risk)

    artifacts = render_charts(changed, _insights(), tmp_path)

    assert all(item.path.stat().st_size > 1_000 for item in artifacts)
    assert "-1.0%" in _svg_text(artifacts[4].path)
    assert "-5.0%" in _svg_text(artifacts[7].path)


def test_rendering_never_mutates_metric_frames(tmp_path: Path) -> None:
    bundle = _bundle()
    snapshots = {name: frame.copy(deep=True) for name, frame in bundle.datasets.items()}

    render_charts(bundle, _insights(), tmp_path)

    for name, before in snapshots.items():
        assert_frame_equal(bundle.datasets[name], before, check_exact=True)


def test_renderer_closes_only_owned_figures_on_success(tmp_path: Path) -> None:
    caller = plt.figure()
    caller_number = caller.number
    try:
        render_charts(_bundle(), _insights(), tmp_path)
        assert plt.get_fignums() == [caller_number]
    finally:
        plt.close(caller)


def test_renderer_closes_only_owned_figures_when_save_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    caller = plt.figure()
    caller_number = caller.number

    def fail_save(self: Figure, *args: object, **kwargs: object) -> None:
        raise OSError("injected save failure")

    monkeypatch.setattr(Figure, "savefig", fail_save)
    try:
        with pytest.raises(OSError, match="injected save failure"):
            render_charts(_bundle(), _insights(), tmp_path)
        assert plt.get_fignums() == [caller_number]
    finally:
        plt.close(caller)
