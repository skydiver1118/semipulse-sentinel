"""Deterministic scoring and wording contracts for all eight chart insights."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from semipulse_sentinel.interpret import (
    EXPECTED_ATOM_COUNT,
    RULES_VERSION,
    build_composite,
    build_composite_audit,
    classify_regime,
    interpret_charts,
    score_pillars,
)
from semipulse_sentinel.metrics import METRICS_VERSION, SCALAR_KEYS, MetricBundle
from semipulse_sentinel.models import (
    CompositeAuditRecord,
    PillarScore,
    QualityReport,
)

NEW_YORK = ZoneInfo("America/New_York")
AS_OF = date(2025, 7, 2)


def _momentum() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "return_20": [0.12, 0.03, -0.06],
            "supported": [True, True, True],
            "eligible": [True, True, True],
            "rank": pd.array([1, 2, 3], dtype="Int64"),
        }
    )


def _trend_heatmap() -> pd.DataFrame:
    metrics = (
        "return_5",
        "return_20",
        "return_63",
        "distance_sma_20",
        "distance_sma_50",
        "distance_sma_200",
    )
    values = {
        "AAA": (0.08, 0.12, 0.20, 0.05, 0.07, 0.10),
        "BBB": (-0.02, 0.03, 0.08, 0.01, 0.02, 0.03),
        "CCC": (0.02, -0.06, -0.12, -0.04, -0.07, -0.09),
    }
    rows: list[dict[str, object]] = []
    for symbol_order, (symbol, symbol_values) in enumerate(values.items()):
        for metric_order, (metric, value) in enumerate(
            zip(metrics, symbol_values, strict=True)
        ):
            rows.append(
                {
                    "symbol": symbol,
                    "metric": metric,
                    "value": value,
                    "supported": True,
                    "symbol_order": symbol_order,
                    "metric_order": metric_order,
                }
            )
    return pd.DataFrame(rows)


def _risk_reward() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "return_63": [0.20, 0.08, -0.12],
            "volatility_20": [0.25, 0.35, 0.50],
            "dollar_volume_20": [50_000_000.0, 20_000_000.0, np.nan],
            "xy_supported": [True, True, True],
            "liquidity_supported": [True, True, False],
            "quadrant": [
                "higher-return/lower-vol",
                "higher-return/higher-vol",
                "lower-return/higher-vol",
            ],
        }
    )


def _breadth(as_of: date = AS_OF) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [pd.Timestamp(as_of)],
            "covered_count": [23],
            "missing_count": [0],
            "above_20_pct": [60.0],
            "above_20_count": [12],
            "covered_20_count": [20],
            "missing_20_count": [3],
            "above_50_pct": [55.0],
            "above_50_count": [11],
            "covered_50_count": [20],
            "missing_50_count": [3],
            "above_200_pct": [50.0],
            "above_200_count": [9],
            "covered_200_count": [18],
            "missing_200_count": [5],
        }
    )


def _neutral_scalars() -> dict[str, float]:
    values = {key: float("nan") for key in SCALAR_KEYS}
    values.update(
        {
            "smh_return_5": 0.0,
            "smh_return_20": 0.0,
            "smh_return_63": 0.0,
            "smh_slope_20": 0.0,
            "smh_distance_sma_20": 0.0,
            "smh_distance_sma_50": 0.0,
            "smh_drawdown_63": -0.05,
            "soxx_return_20": 0.0,
            "soxx_return_63": 0.0,
            "soxx_distance_sma_20": 0.0,
            "soxx_distance_sma_50": 0.0,
            "soxl_return_20": 0.0,
            "soxl_return_63": 0.0,
            "smh_qqq_return_20": 0.0,
            "smh_qqq_return_63": 0.0,
            "smh_qqq_distance_sma_20": 0.0,
            "smh_qqq_distance_sma_50": 0.0,
            "smh_qqq_crossover_20_50": 0.0,
            "smh_qqq_crossover_20_50_supported": 1.0,
            "soxx_qqq_return_20": 0.0,
            "soxx_qqq_return_63": 0.0,
            "soxx_qqq_distance_sma_20": 0.0,
            "soxx_qqq_distance_sma_50": 0.0,
            "soxx_qqq_crossover_20_50": 0.0,
            "soxx_qqq_crossover_20_50_supported": 1.0,
            "breadth_above_20_pct": 50.0,
            "breadth_above_50_pct": 50.0,
            "breadth_above_200_pct": 50.0,
            "breadth_20_change_5": 0.0,
            "breadth_50_change_5": 0.0,
            "breadth_200_change_5": 0.0,
            "breadth_covered_20_count": 23.0,
            "breadth_covered_50_count": 23.0,
            "breadth_covered_200_count": 23.0,
            "participation_spread_63": 0.0,
            "participation_outperforming_smh_pct": 50.0,
            "participation_dispersion_63": 0.08,
            "participation_eligible_count": 23.0,
            "participation_missing_count": 0.0,
            "participation_supported": 1.0,
            "momentum_median_20": 0.0,
            "momentum_iqr_20": 0.08,
            "momentum_positive_pct": 50.0,
            "momentum_eligible_count": 3.0,
            "momentum_missing_count": 0.0,
            "trend_positive_cell_pct": 50.0,
            "trend_unsupported_cells": 0.0,
            "trend_supported_cells": 18.0,
            "trend_missing_cells": 0.0,
            "smh_vol_20": 0.25,
            "smh_vol_percentile_252": 50.0,
            "smh_vol_change_5": 0.0,
            "vix_latest": 20.0,
            "risk_reward_return_median_63": 0.0,
            "risk_reward_vol_median_20": 0.35,
            "risk_reward_xy_eligible_count": 3.0,
            "risk_reward_xy_missing_count": 0.0,
            "risk_reward_liquidity_eligible_count": 2.0,
            "risk_reward_liquidity_missing_count": 1.0,
        }
    )
    return values


def _bundle(
    *,
    as_of: date = AS_OF,
    scalar_updates: dict[str, float] | None = None,
    all_missing: bool = False,
) -> MetricBundle:
    scalars = {key: float("nan") for key in SCALAR_KEYS}
    if not all_missing:
        scalars.update(_neutral_scalars())
    if scalar_updates:
        scalars.update(scalar_updates)
    return MetricBundle(
        methodology_version=METRICS_VERSION,
        as_of=as_of,
        normalized_performance=pd.DataFrame(),
        relative_strength=pd.DataFrame(),
        breadth=_breadth(as_of),
        participation=pd.DataFrame(),
        momentum=_momentum(),
        trend_heatmap=_trend_heatmap(),
        risk_regime=pd.DataFrame(),
        risk_reward=_risk_reward(),
        scalars=MappingProxyType(scalars),
    )


def _quality(**updates: object) -> QualityReport:
    base: dict[str, object] = {
        "as_of": datetime(2025, 7, 2, tzinfo=NEW_YORK),
        "covered_symbols": tuple(f"S{index:02d}" for index in range(23)),
        "missing_symbols": (),
        "stale_symbols": (),
        "missing_required": (),
        "missing_optional": (),
        "covered_count": 23,
        "watchlist_count": 23,
        "coverage_ratio": Decimal("1"),
        "publishable": True,
        "warnings": (),
        "evaluated_at": datetime(2025, 7, 2, 18, 0, tzinfo=NEW_YORK),
        "calendar_age_days": 0,
        "expected_session_lag": 0,
    }
    base.update(updates)
    return QualityReport(**base)  # type: ignore[arg-type]


POSITIVE = {
    "smh_return_20": 0.03,
    "smh_return_63": 0.08,
    "smh_distance_sma_20": 0.005,
    "smh_distance_sma_50": 0.005,
    "smh_slope_20": 0.0005,
    "soxx_return_20": 0.03,
    "soxx_distance_sma_20": 0.005,
    "soxx_distance_sma_50": 0.005,
    "smh_qqq_return_20": 0.02,
    "smh_qqq_return_63": 0.05,
    "smh_qqq_distance_sma_20": 0.005,
    "smh_qqq_distance_sma_50": 0.005,
    "smh_qqq_crossover_20_50": 1.0,
    "smh_qqq_crossover_20_50_supported": 1.0,
    "soxx_qqq_return_20": 0.02,
    "soxx_qqq_return_63": 0.05,
    "soxx_qqq_distance_sma_20": 0.005,
    "soxx_qqq_distance_sma_50": 0.005,
    "soxx_qqq_crossover_20_50": 1.0,
    "soxx_qqq_crossover_20_50_supported": 1.0,
    "breadth_above_20_pct": 60.0,
    "breadth_above_50_pct": 60.0,
    "breadth_above_200_pct": 55.0,
    "breadth_20_change_5": 10.0,
    "breadth_50_change_5": 10.0,
    "breadth_200_change_5": 10.0,
    "participation_spread_63": 0.03,
    "participation_outperforming_smh_pct": 60.0,
    "momentum_median_20": 0.03,
    "momentum_positive_pct": 60.0,
    "trend_positive_cell_pct": 60.0,
    "risk_reward_return_median_63": 0.08,
    "smh_vol_percentile_252": 35.0,
    "smh_drawdown_63": -0.03,
    "smh_vol_change_5": -0.03,
    "vix_latest": 18.0,
}

NEGATIVE = {
    "smh_return_20": -0.03,
    "smh_return_63": -0.08,
    "smh_distance_sma_20": -0.005,
    "smh_distance_sma_50": -0.005,
    "smh_slope_20": -0.0005,
    "soxx_return_20": -0.03,
    "soxx_distance_sma_20": -0.005,
    "soxx_distance_sma_50": -0.005,
    "smh_qqq_return_20": -0.02,
    "smh_qqq_return_63": -0.05,
    "smh_qqq_distance_sma_20": -0.005,
    "smh_qqq_distance_sma_50": -0.005,
    "smh_qqq_crossover_20_50": -1.0,
    "smh_qqq_crossover_20_50_supported": 1.0,
    "soxx_qqq_return_20": -0.02,
    "soxx_qqq_return_63": -0.05,
    "soxx_qqq_distance_sma_20": -0.005,
    "soxx_qqq_distance_sma_50": -0.005,
    "soxx_qqq_crossover_20_50": -1.0,
    "soxx_qqq_crossover_20_50_supported": 1.0,
    "breadth_above_20_pct": 40.0,
    "breadth_above_50_pct": 40.0,
    "breadth_above_200_pct": 45.0,
    "breadth_20_change_5": -10.0,
    "breadth_50_change_5": -10.0,
    "breadth_200_change_5": -10.0,
    "participation_spread_63": -0.03,
    "participation_outperforming_smh_pct": 40.0,
    "momentum_median_20": -0.03,
    "momentum_positive_pct": 40.0,
    "trend_positive_cell_pct": 40.0,
    "risk_reward_return_median_63": -0.08,
    "smh_vol_percentile_252": 70.0,
    "smh_drawdown_63": -0.10,
    "smh_vol_change_5": 0.03,
    "vix_latest": 25.0,
}


@pytest.mark.parametrize(
    ("score", "label"),
    [
        (Decimal("1.20"), "risk-on"),
        (Decimal("0.45"), "constructive"),
        (Decimal("0.44"), "mixed"),
        (Decimal("-0.44"), "mixed"),
        (Decimal("-0.45"), "defensive"),
        (Decimal("-1.19"), "defensive"),
        (Decimal("-1.20"), "risk-off"),
    ],
)
def test_composite_boundaries(score: Decimal, label: str) -> None:
    assert classify_regime(score) == label


@pytest.mark.parametrize(
    ("updates", "expected"),
    [(POSITIVE, Decimal("2")), (NEGATIVE, Decimal("-2"))],
)
def test_all_threshold_boundaries_vote_inclusively(
    updates: dict[str, float], expected: Decimal
) -> None:
    pillars = score_pillars(_bundle(scalar_updates=updates))

    assert RULES_VERSION == "semipulse-rules-v1"
    assert [pillar.value for pillar in pillars] == [expected] * 5
    assert [pillar.expected_inputs for pillar in pillars] == [6, 8, 8, 4, 4]
    assert [pillar.available_inputs for pillar in pillars] == [6, 8, 8, 4, 4]
    assert (
        sum(pillar.expected_inputs for pillar in pillars) == EXPECTED_ATOM_COUNT == 30
    )


def test_pillar_counter_evidence_tracks_each_current_state() -> None:
    positive = score_pillars(_bundle(scalar_updates=POSITIVE))
    negative = score_pillars(_bundle(scalar_updates=NEGATIVE))
    mixed = score_pillars(_bundle())
    limited = score_pillars(_bundle(all_missing=True))

    assert all(
        "Published downside thresholds:" in pillar.counter_evidence[0]
        for pillar in positive
    )
    assert all(
        "Published recovery thresholds:" in pillar.counter_evidence[0]
        for pillar in negative
    )
    assert all(
        "Published downside thresholds:" in pillar.counter_evidence[0]
        and "Published upside thresholds:" in pillar.counter_evidence[1]
        for pillar in mixed
    )
    assert all(
        "vote mix is unavailable" in pillar.counter_evidence[0]
        and "Published improvement thresholds:" in pillar.counter_evidence[0]
        for pillar in limited
    )
    all_conditions = " ".join(
        condition
        for pillar in (*positive, *negative, *mixed, *limited)
        for condition in pillar.counter_evidence
    ).lower()
    assert "would weaken if" not in all_conditions
    assert "would worsen if" not in all_conditions
    assert "would improve once" not in all_conditions
    assert "would ease once" not in all_conditions


def test_pillar_conditions_disclose_mixed_atom_votes_without_future_tense() -> None:
    positive_with_active_downside = {
        **POSITIVE,
        "smh_return_20": -0.03,
        "smh_qqq_return_20": -0.02,
        "breadth_above_20_pct": 40.0,
        "momentum_median_20": -0.03,
        "smh_vol_percentile_252": 70.0,
    }
    positive = score_pillars(
        _bundle(scalar_updates=positive_with_active_downside)
    )

    assert all(pillar.value > 0 for pillar in positive)
    assert all(
        "1 adverse" in pillar.counter_evidence[0] for pillar in positive
    )
    assert all(
        "Published downside thresholds:" in pillar.counter_evidence[0]
        for pillar in positive
    )

    negative_with_active_recovery = {
        **NEGATIVE,
        "breadth_above_20_pct": 60.0,
        "breadth_above_50_pct": 60.0,
        "participation_spread_63": 0.03,
    }
    breadth = score_pillars(
        _bundle(scalar_updates=negative_with_active_recovery)
    )[2]

    assert breadth.value == Decimal("-0.5")
    assert "3 supportive" in breadth.counter_evidence[0]
    assert "Published recovery thresholds:" in breadth.counter_evidence[0]
    assert "would improve once" not in breadth.counter_evidence[0]


def test_missing_atoms_are_zero_without_denominator_renormalization() -> None:
    missing = score_pillars(_bundle(all_missing=True))
    one_vote = score_pillars(
        _bundle(all_missing=True, scalar_updates={"smh_return_20": 0.20})
    )

    assert all(item.value == Decimal("0") for item in missing)
    assert all(item.available_inputs == 0 for item in missing)
    assert one_vote[0].value == Decimal(2) / Decimal(6)
    assert one_vote[0].available_inputs == 1
    assert one_vote[0].expected_inputs == 6


def test_pillar_and_audit_records_are_immutable() -> None:
    pillar = score_pillars(_bundle())[0]
    audit = build_composite_audit([_bundle()], current=_bundle())[0]

    with pytest.raises(FrozenInstanceError):
        pillar.value = Decimal("2")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        audit.regime = "risk-on"  # type: ignore[misc]
    assert isinstance(pillar, PillarScore)
    assert isinstance(audit, CompositeAuditRecord)


def test_composite_uses_decimal_weights_and_rounds_only_final_score() -> None:
    current = _bundle(scalar_updates=POSITIVE)
    audit = build_composite_audit([current], current=current)

    assert audit[0].composite_score == Decimal("2.00")
    assert audit[0].regime == "risk-on"
    assert audit[0].available_inputs == 30
    assert audit[0].expected_inputs == 30


def test_composite_exposes_versioned_weighted_pillar_audit() -> None:
    metrics = _bundle(scalar_updates=POSITIVE)
    summary = build_composite(
        interpret_charts(metrics, _quality()), metrics, _quality()
    )

    assert summary.rules_version == RULES_VERSION
    assert summary.pillars == score_pillars(metrics)
    assert [pillar.weight for pillar in summary.pillars] == [
        Decimal("0.25"),
        Decimal("0.20"),
        Decimal("0.25"),
        Decimal("0.15"),
        Decimal("0.15"),
    ]
    assert summary.available_inputs == 30
    assert summary.expected_inputs == 30
    rebuilt = sum(pillar.value * pillar.weight for pillar in summary.pillars).quantize(
        Decimal("0.01")
    )
    assert rebuilt == summary.score


def test_audit_requires_unique_chronological_max_five_with_current_latest() -> None:
    snapshots = [_bundle(as_of=AS_OF + timedelta(days=offset)) for offset in range(5)]
    records = build_composite_audit(snapshots, current=snapshots[-1])

    assert [record.as_of for record in records] == [item.as_of for item in snapshots]
    assert len(records) == 5
    with pytest.raises(ValueError, match="chronological"):
        build_composite_audit([snapshots[1], snapshots[0]], current=snapshots[0])
    with pytest.raises(ValueError, match="duplicate"):
        build_composite_audit([snapshots[0], snapshots[0]], current=snapshots[0])
    with pytest.raises(ValueError, match="at most five"):
        six = [_bundle(as_of=AS_OF + timedelta(days=offset)) for offset in range(6)]
        build_composite_audit(six, current=six[-1])
    with pytest.raises(ValueError, match="latest"):
        build_composite_audit(snapshots[:-1], current=snapshots[-1])


def test_every_chart_has_rich_evidence_and_required_safety_language() -> None:
    metrics = _bundle(scalar_updates=POSITIVE)
    insights = interpret_charts(metrics, _quality())

    assert [item.chart_id for item in insights] == [
        f"chart-{number}" for number in range(1, 9)
    ]
    for item in insights:
        assert item.headline
        assert item.signal in {"positive", "negative", "mixed", "limited"}
        assert item.evidence
        assert item.interpretation
        assert item.trading_relevance
        assert item.counter_signal
        assert item.notes
    chart_one = " ".join(
        (*insights[0].evidence, insights[0].interpretation, *insights[0].notes)
    ).lower()
    assert "leveraged" in chart_one
    assert "path-dependent" in chart_one
    assert "distance from 63-session peak" in insights[6].as_text().lower()
    assert "descriptive" in insights[4].as_text().lower()
    assert "chase list" in insights[4].as_text().lower()
    assert "not a portfolio optimizer" in insights[7].as_text().lower()


def test_chart_specific_signals_do_not_leak_across_pillar_components() -> None:
    breadth_positive_participation_negative = _bundle(
        scalar_updates={
            "breadth_above_20_pct": 60.0,
            "breadth_above_50_pct": 60.0,
            "breadth_above_200_pct": 55.0,
            "breadth_20_change_5": 10.0,
            "breadth_50_change_5": 10.0,
            "breadth_200_change_5": 10.0,
            "participation_spread_63": -0.03,
            "participation_outperforming_smh_pct": 40.0,
        }
    )
    insights = interpret_charts(
        breadth_positive_participation_negative, _quality()
    )

    assert insights[2].signal == "positive"
    assert insights[3].signal == "negative"
    assert insights[3].counter_signal.startswith(
        "Published improvement thresholds:"
    )

    risk_reward_positive = _bundle(
        scalar_updates={
            "risk_reward_return_median_63": 0.08,
            "momentum_median_20": 0.20,
            "momentum_positive_pct": 90.0,
            "trend_positive_cell_pct": 90.0,
        }
    )
    unrelated_momentum_negative = _bundle(
        scalar_updates={
            "risk_reward_return_median_63": 0.08,
            "momentum_median_20": -0.20,
            "momentum_positive_pct": 10.0,
            "trend_positive_cell_pct": 10.0,
        }
    )
    first = interpret_charts(risk_reward_positive, _quality())[7]
    second = interpret_charts(unrelated_momentum_negative, _quality())[7]

    assert first.signal == second.signal == "positive"


@pytest.mark.parametrize(
    ("updates", "all_missing", "signal", "prefix"),
    [
        (POSITIVE, False, "positive", "Published downside thresholds:"),
        (NEGATIVE, False, "negative", "Published improvement thresholds:"),
        ({}, False, "mixed", "Published two-way thresholds:"),
        ({}, True, "limited", "Limitation:"),
    ],
)
def test_every_counter_signal_agrees_with_its_chart_signal(
    updates: dict[str, float],
    all_missing: bool,
    signal: str,
    prefix: str,
) -> None:
    insights = interpret_charts(
        _bundle(scalar_updates=updates, all_missing=all_missing), _quality()
    )

    assert {item.signal for item in insights} == {signal}
    assert all(item.counter_signal.startswith(prefix) for item in insights)
    assert all(item.counter_signal.endswith(".") for item in insights)
    assert all(".;" not in item.counter_signal for item in insights)


def test_chart_one_prints_compact_multi_horizon_and_peak_distance_evidence() -> None:
    chart = interpret_charts(_bundle(scalar_updates=POSITIVE), _quality())[0]
    text = chart.as_text().lower()

    assert "5/20/63-session" in text
    assert "smh" in text and "soxx" in text and "qqq" in text
    assert "distance from 63-session peak" in text
    assert "soxl" in text and "leveraged" in text and "path-dependent" in text


def test_chart_three_uses_exact_latest_counts_denominators_and_missing() -> None:
    metrics = replace(
        _bundle(),
        breadth=pd.DataFrame(
            {
                "date": [pd.Timestamp(AS_OF)],
                "above_20_count": [11],
                "covered_20_count": [17],
                "missing_20_count": [6],
                "above_50_count": [7],
                "covered_50_count": [16],
                "missing_50_count": [7],
                "above_200_count": [5],
                "covered_200_count": [12],
                "missing_200_count": [11],
            }
        ),
    )

    text = interpret_charts(metrics, _quality())[2].as_text().lower()

    assert "20-session: 11/17 above, 6 missing" in text
    assert "50-session: 7/16 above, 7 missing" in text
    assert "200-session: 5/12 above, 11 missing" in text


def test_chart_eight_cross_checks_high_returns_against_trend_support() -> None:
    trend = _trend_heatmap()
    bbb = trend["symbol"].eq("BBB")
    trend.loc[bbb, "value"] = [-0.02, 0.03, 0.08, -0.01, -0.02, -0.03]
    metrics = replace(
        _bundle(scalar_updates={"risk_reward_return_median_63": 0.05}),
        trend_heatmap=trend,
    )

    text = interpret_charts(metrics, _quality())[7].as_text().lower()

    assert "fewer than three positive supported trend cells" in text
    assert "bbb (2/6 positive supported cells)" in text


def test_participation_wording_qualifies_cross_sectional_median() -> None:
    text = " ".join(
        item.as_text() for item in interpret_charts(_bundle(), _quality())
    ).lower()

    assert "equal-weight spread" not in text
    assert "equal-weight return" not in text
    assert "median participation spread" in text
    assert "one symbol, one vote" in text


def test_insights_never_emit_raw_nonfinite_or_imperative_language() -> None:
    metrics = _bundle(
        scalar_updates={
            "vix_latest": float("nan"),
            "soxl_return_20": float("inf"),
            "trend_positive_cell_pct": float("nan"),
        }
    )
    text = " ".join(item.as_text() for item in interpret_charts(metrics, _quality()))
    lowered = text.lower()

    assert " nan" not in lowered
    assert " inf" not in lowered
    assert "buy now" not in lowered
    assert "sell now" not in lowered
    assert "guaranteed" not in lowered
    assert "will rise" not in lowered
    assert "you should" not in lowered


@pytest.mark.parametrize(
    ("quality", "expected"),
    [
        (_quality(coverage_ratio=Decimal("0.69"), covered_count=15), "low"),
        (_quality(missing_required=("QQQ",)), "low"),
        (_quality(calendar_age_days=4), "low"),
        (_quality(expected_session_lag=2), "medium"),
        (_quality(coverage_ratio=Decimal("0.89"), covered_count=20), "medium"),
        (_quality(missing_optional=("^VIX",)), "medium"),
        (_quality(warnings=("provider_error:AAA:timeout",)), "medium"),
    ],
)
def test_quality_facts_cap_confidence(quality: QualityReport, expected: str) -> None:
    metrics = _bundle()
    snapshots = [
        replace(metrics, as_of=AS_OF + timedelta(days=offset)) for offset in range(5)
    ]
    current = snapshots[-1]
    summary = build_composite(
        interpret_charts(current, quality),
        current,
        quality,
        audit=build_composite_audit(snapshots, current=current),
    )

    assert summary.confidence == expected


def test_quality_challenges_pluralize_counts() -> None:
    metrics = _bundle(scalar_updates={"trend_missing_cells": 1.0})
    summary = build_composite(
        interpret_charts(metrics, _quality()),
        metrics,
        _quality(
            calendar_age_days=1,
            expected_session_lag=1,
            warnings=("provider_notice",),
        ),
    )
    text = " ".join(summary.challenges)

    assert "1 calendar day old" in text
    assert "1 calendar days" not in text
    assert "by 1 session." in text
    assert "session(s)" not in text
    assert "1 nonfatal warning." in text
    assert "warning(s)" not in text
    assert "1 trend cell is unsupported." in text
    assert "1 trend cells" not in text


def test_input_and_history_missingness_caps_confidence() -> None:
    metrics = _bundle(scalar_updates={"vix_latest": float("nan")})
    short_audit = build_composite_audit([metrics], current=metrics)
    summary = build_composite(
        interpret_charts(metrics, _quality()),
        metrics,
        _quality(),
        audit=short_audit,
    )

    assert summary.confidence == "medium"
    assert any("history" in item.lower() for item in summary.challenges)
    assert any(
        "input" in item.lower() or "vix" in item.lower() for item in summary.challenges
    )


def test_zero_available_pillar_or_under_seventy_percent_atoms_is_low() -> None:
    metrics = _bundle(all_missing=True)
    summary = build_composite(
        interpret_charts(metrics, _quality()), metrics, _quality()
    )

    assert summary.confidence == "low"
    assert (
        "coverage" in summary.as_text().lower()
        or "available" in summary.as_text().lower()
    )


def test_high_confidence_requires_five_current_complete_clean_snapshots() -> None:
    snapshots = [_bundle(as_of=AS_OF + timedelta(days=offset)) for offset in range(5)]
    current = snapshots[-1]
    quality = _quality(
        as_of=datetime.combine(current.as_of, datetime.min.time(), NEW_YORK),
        evaluated_at=datetime.combine(current.as_of, datetime.min.time(), NEW_YORK),
    )
    summary = build_composite(
        interpret_charts(current, quality),
        current,
        quality,
        audit=build_composite_audit(snapshots, current=current),
    )

    assert summary.confidence == "high"
    assert summary.supports
    assert summary.challenges
    assert summary.change_triggers
    assert "guaranteed" not in summary.as_text().lower()


def test_neutral_composite_has_both_upside_and_downside_paths() -> None:
    metrics = _bundle()
    summary = build_composite(
        interpret_charts(metrics, _quality()), metrics, _quality()
    )
    text = summary.as_text().lower()

    assert summary.score == Decimal("0.00")
    assert summary.regime == "mixed"
    assert "upside threshold status" in text
    assert "downside threshold status" in text


def test_active_risk_threshold_is_not_described_as_an_unmet_trigger() -> None:
    metrics = _bundle(scalar_updates=NEGATIVE)
    summary = build_composite(
        interpret_charts(metrics, _quality()), metrics, _quality()
    )
    triggers = " ".join(summary.change_triggers).lower()

    assert "risk stress is already active" in triggers
    assert "would ease once" in triggers
    assert "risk conditions would deteriorate if" not in triggers


def test_inactive_risk_threshold_is_reported_as_current_threshold_state() -> None:
    metrics = _bundle()
    summary = build_composite(
        interpret_charts(metrics, _quality()), metrics, _quality()
    )

    triggers = " ".join(summary.change_triggers).lower()

    assert "published adverse risk thresholds" in triggers
    assert "neither is active" in triggers
    assert "would deteriorate if" not in triggers


def test_risk_on_change_trigger_counts_already_active_downside_atoms() -> None:
    metrics = _bundle(
        scalar_updates={
            **POSITIVE,
            "smh_return_20": -0.03,
            "soxx_return_20": -0.03,
        }
    )
    summary = build_composite(
        interpret_charts(metrics, _quality()), metrics, _quality()
    )
    triggers = " ".join(summary.change_triggers).lower()

    assert summary.regime == "risk-on"
    assert "downside threshold status: 2 active, 2 inactive" in triggers
    assert "would weaken if" not in triggers


def test_risk_off_summary_counts_already_active_upside_atoms() -> None:
    metrics = _bundle(
        scalar_updates={
            **NEGATIVE,
            "smh_return_20": 0.03,
            "soxx_return_20": 0.03,
            "breadth_above_20_pct": 60.0,
            "breadth_above_50_pct": 60.0,
        }
    )
    summary = build_composite(
        interpret_charts(metrics, _quality()), metrics, _quality()
    )
    text = summary.as_text().lower()

    assert summary.regime == "risk-off"
    assert "upside threshold status: 4 active, 0 inactive" in text
    assert "would need" not in text
    assert "could improve if" not in text


def test_composite_threshold_status_counts_unavailable_atoms() -> None:
    metrics = _bundle(
        scalar_updates={
            "smh_return_20": float("nan"),
            "soxx_return_20": 0.04,
            "breadth_above_20_pct": 55.0,
            "breadth_above_50_pct": float("nan"),
        }
    )
    summary = build_composite(
        interpret_charts(metrics, _quality()), metrics, _quality()
    )
    triggers = " ".join(summary.change_triggers).lower()

    assert (
        "upside threshold status: 1 active, 1 inactive, and 2 unavailable"
        in triggers
    )
    assert (
        "downside threshold status: 0 active, 2 inactive, and 2 unavailable"
        in triggers
    )


def test_active_risk_trigger_prints_live_values_and_state_based_recovery() -> None:
    metrics = _bundle(
        scalar_updates={
            "smh_drawdown_63": -0.168,
            "smh_vol_percentile_252": 91.5,
        }
    )
    summary = build_composite(
        interpret_charts(metrics, _quality()), metrics, _quality()
    )
    triggers = " ".join(summary.change_triggers)

    assert "-16.8%" in triggers
    assert "91.5th percentile" in triggers
    assert "once SMH is within -3.0%" in triggers
    assert "volatility is at or below its 35th percentile" in triggers


@pytest.mark.parametrize(
    ("updates", "forbidden_temporal_phrase"),
    [
        (
            {"smh_drawdown_63": -0.15, "smh_vol_percentile_252": 20.0},
            "volatility falls",
        ),
        (
            {"smh_drawdown_63": -0.01, "smh_vol_percentile_252": 80.0},
            "SMH recovers",
        ),
    ],
)
def test_one_sided_risk_stress_does_not_reactivate_a_healthy_leg(
    updates: dict[str, float], forbidden_temporal_phrase: str
) -> None:
    metrics = _bundle(scalar_updates=updates)
    summary = build_composite(
        interpret_charts(metrics, _quality()), metrics, _quality()
    )
    triggers = " ".join(summary.change_triggers)

    assert "Risk stress is already active" in triggers
    assert forbidden_temporal_phrase not in triggers
    assert "once SMH is within -3.0%" in triggers


@pytest.mark.parametrize(
    "updates",
    [
        {
            "smh_drawdown_63": float("nan"),
            "smh_vol_percentile_252": float("nan"),
        },
        {"smh_drawdown_63": -0.01, "smh_vol_percentile_252": float("nan")},
    ],
)
def test_unavailable_risk_inputs_are_indeterminate(
    updates: dict[str, float]
) -> None:
    metrics = _bundle(scalar_updates=updates)
    summary = build_composite(
        interpret_charts(metrics, _quality()), metrics, _quality()
    )
    triggers = " ".join(summary.change_triggers).lower()

    assert "indeterminate" in triggers
    assert "risk conditions would deteriorate if" not in triggers


def test_known_active_risk_is_disclosed_even_when_other_input_is_missing() -> None:
    metrics = _bundle(
        scalar_updates={
            "smh_drawdown_63": -0.15,
            "smh_vol_percentile_252": float("nan"),
        }
    )
    summary = build_composite(
        interpret_charts(metrics, _quality()), metrics, _quality()
    )
    triggers = " ".join(summary.change_triggers).lower()

    assert "risk stress is already active" in triggers
    assert "volatility percentile is unavailable" in triggers
    assert any(
        "The volatility percentile is unavailable" in item
        for item in summary.change_triggers
    )


@pytest.mark.parametrize(
    ("drawdown", "volatility", "active"),
    [
        (-0.10, 69.9, True),
        (-0.099, 70.0, True),
        (-0.099, 69.9, False),
    ],
)
def test_risk_trigger_boundaries_match_pillar_votes(
    drawdown: float, volatility: float, active: bool
) -> None:
    metrics = _bundle(
        scalar_updates={
            "smh_drawdown_63": drawdown,
            "smh_vol_percentile_252": volatility,
        }
    )
    summary = build_composite(
        interpret_charts(metrics, _quality()), metrics, _quality()
    )
    triggers = " ".join(summary.change_triggers).lower()

    assert ("risk stress is already active" in triggers) is active


def _offsetting_bundle(*, as_of: date) -> MetricBundle:
    return _bundle(
        as_of=as_of,
        scalar_updates={
            "smh_return_20": 0.03,
            "smh_return_63": 0.08,
            "smh_slope_20": 0.0005,
            "smh_qqq_return_20": -0.02,
            "smh_qqq_return_63": -0.05,
            "smh_qqq_distance_sma_20": -0.005,
            "smh_qqq_distance_sma_50": -0.005,
            "smh_qqq_crossover_20_50": -1.0,
            "soxx_qqq_return_20": -0.02,
        },
    )


def test_composite_prose_is_regime_aware_for_positive_negative_mixed_and_zero() -> None:
    positive_metrics = _bundle(scalar_updates=POSITIVE)
    positive = build_composite(
        interpret_charts(positive_metrics, _quality()),
        positive_metrics,
        _quality(),
    )
    assert "positive contribution" in positive.supports[0].lower()
    assert "published downside threshold context" in positive.challenges[0].lower()

    negative_metrics = _bundle(scalar_updates=NEGATIVE)
    negative = build_composite(
        interpret_charts(negative_metrics, _quality()),
        negative_metrics,
        _quality(),
    )
    assert "defensive contribution" in negative.supports[0].lower()
    assert "upside threshold status" in negative.challenges[0].lower()
    assert "positive contribution" not in negative.supports[0].lower()

    mixed_metrics = _offsetting_bundle(as_of=AS_OF)
    mixed = build_composite(
        interpret_charts(mixed_metrics, _quality()), mixed_metrics, _quality()
    )
    assert mixed.regime == "mixed"
    assert "positive side" in mixed.supports[0].lower()
    assert "negative side" in mixed.challenges[0].lower()

    zero_metrics = _bundle()
    zero = build_composite(
        interpret_charts(zero_metrics, _quality()), zero_metrics, _quality()
    )
    assert "no pillar has a nonzero" in zero.supports[0].lower()
    assert "offsetting" in zero.challenges[0].lower()


def test_zero_contribution_summary_discloses_offsetting_active_votes() -> None:
    metrics = _bundle(
        scalar_updates={
            "smh_return_20": 0.03,
            "smh_return_63": -0.08,
        }
    )
    summary = build_composite(
        interpret_charts(metrics, _quality()), metrics, _quality()
    )
    text = summary.as_text().lower()

    assert summary.score == Decimal("0.00")
    assert summary.regime == "mixed"
    assert "neutral or offsetting" in summary.supports[0].lower()
    assert "1 supportive, 1 adverse" in text
    assert "upside threshold status: 1 active" in text
    assert "could emerge if" not in text
    assert "crosses the published thresholds" not in text


def test_directional_summary_does_not_label_upside_text_as_downside() -> None:
    positive_updates = {
        **POSITIVE,
        "smh_vol_percentile_252": float("nan"),
        "smh_drawdown_63": float("nan"),
        "smh_vol_change_5": float("nan"),
        "vix_latest": float("nan"),
    }
    positive_metrics = _bundle(scalar_updates=positive_updates)
    positive = build_composite(
        interpret_charts(positive_metrics, _quality()),
        positive_metrics,
        _quality(),
    )

    assert positive.regime == "risk-on"
    assert (
        "published downside threshold context is indeterminate"
        in positive.challenges[0].lower()
    )
    assert "improvement" not in positive.challenges[0].lower()

    mixed_metrics = _bundle(
        all_missing=True,
        scalar_updates={"smh_return_20": 0.20},
    )
    mixed = build_composite(
        interpret_charts(mixed_metrics, _quality()),
        mixed_metrics,
        _quality(),
    )

    assert mixed.regime == "mixed"
    assert (
        "published downside threshold context is indeterminate"
        in mixed.challenges[0].lower()
    )
    assert "improvement" not in mixed.challenges[0].lower()


def test_composite_preserves_and_validates_nested_audit_records() -> None:
    snapshots = [
        _bundle(as_of=AS_OF + timedelta(days=offset)) for offset in range(2)
    ]
    current = snapshots[-1]
    audit = build_composite_audit(snapshots, current=current)
    insights = interpret_charts(current, _quality())
    summary = build_composite(insights, current, _quality(), audit=audit)

    assert summary.audit == audit
    with pytest.raises(ValueError, match="chronological"):
        build_composite(insights, current, _quality(), audit=tuple(reversed(audit)))
    with pytest.raises(ValueError, match="duplicate"):
        build_composite(insights, current, _quality(), audit=(audit[-1], audit[-1]))
    with pytest.raises(ValueError, match="score"):
        corrupt = replace(
            audit[-1], composite_score=audit[-1].composite_score + Decimal("0.01")
        )
        build_composite(insights, current, _quality(), audit=(corrupt,))
    with pytest.raises(ValueError, match="at most five"):
        six = tuple(
            replace(audit[-1], as_of=AS_OF - timedelta(days=5 - offset))
            for offset in range(6)
        )
        build_composite(insights, current, _quality(), audit=six)


def test_current_audit_rejects_offsetting_same_score_pillar_tampering() -> None:
    current = _bundle(as_of=AS_OF)
    tampered_snapshot = _offsetting_bundle(as_of=AS_OF)
    tampered = build_composite_audit(
        [tampered_snapshot], current=tampered_snapshot
    )[0]

    assert tampered.composite_score == Decimal("0.00")
    assert tampered.composite_score == build_composite_audit(
        [current], current=current
    )[0].composite_score
    assert tampered.pillars != score_pillars(current)

    with pytest.raises(ValueError, match="current pillars"):
        build_composite_audit([tampered_snapshot], current=current)
    with pytest.raises(ValueError, match="current pillars"):
        build_composite(
            interpret_charts(current, _quality()),
            current,
            _quality(),
            audit=(tampered,),
        )


def test_what_changed_names_largest_pillar_move_when_total_delta_offsets() -> None:
    previous = _bundle(as_of=AS_OF)
    current = _offsetting_bundle(as_of=AS_OF + timedelta(days=1))
    audit = build_composite_audit([previous, current], current=current)
    summary = build_composite(
        interpret_charts(current, _quality()),
        current,
        _quality(),
        audit=audit,
    )

    assert audit[0].composite_score == audit[1].composite_score == Decimal("0.00")
    assert "relative leadership" in summary.what_changed[0].lower()
    assert "-1.25" in summary.what_changed[0]
