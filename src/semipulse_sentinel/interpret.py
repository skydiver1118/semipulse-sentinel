"""Versioned, deterministic interpretation of the eight market datasets.

The composite is deliberately mechanical. Thirty fixed-denominator atoms vote
``+1``, ``0``, or ``-1``; unavailable atoms vote zero and are never removed
from a denominator. Human-facing prose reports observations, conditional
relevance, counter-signals, and limitations without issuing trading orders.
"""

# The bounded prose templates remain readable as complete sentences.
# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from math import isfinite

import pandas as pd  # type: ignore[import-untyped]

from semipulse_sentinel.metrics import MetricBundle
from semipulse_sentinel.models import (
    ChartInsight,
    CompositeAuditRecord,
    CompositeInsight,
    PillarScore,
    QualityReport,
)

RULES_VERSION = "semipulse-rules-v1"
EXPECTED_ATOM_COUNT = 30

_WEIGHTS: tuple[tuple[str, Decimal, int], ...] = (
    ("absolute_trend", Decimal("0.25"), 6),
    ("relative_leadership", Decimal("0.20"), 8),
    ("breadth_participation", Decimal("0.25"), 8),
    ("momentum_distribution", Decimal("0.15"), 4),
    ("volatility_drawdown_risk", Decimal("0.15"), 4),
)


def _number(scalars: Mapping[str, float], key: str) -> Decimal | None:
    try:
        value = float(scalars[key])
    except (KeyError, TypeError, ValueError):
        return None
    if not isfinite(value):
        return None
    return Decimal(str(value))


def _threshold_vote(
    value: Decimal | None,
    positive_at: Decimal,
    negative_at: Decimal,
) -> int | None:
    if value is None:
        return None
    if value >= positive_at:
        return 1
    if value <= negative_at:
        return -1
    return 0


def _lower_is_better_vote(
    value: Decimal | None,
    positive_at_or_below: Decimal,
    negative_at_or_above: Decimal,
) -> int | None:
    if value is None:
        return None
    if value <= positive_at_or_below:
        return 1
    if value >= negative_at_or_above:
        return -1
    return 0


def _moving_average_vote(scalars: Mapping[str, float], prefix: str) -> int | None:
    short = _number(scalars, f"{prefix}_distance_sma_20")
    long = _number(scalars, f"{prefix}_distance_sma_50")
    if short is None or long is None:
        return None
    threshold = Decimal("0.005")
    if short >= threshold and long >= threshold:
        return 1
    if short <= -threshold and long <= -threshold:
        return -1
    return 0


def _crossover_vote(scalars: Mapping[str, float], prefix: str) -> int | None:
    supported = _number(scalars, f"{prefix}_crossover_20_50_supported")
    value = _number(scalars, f"{prefix}_crossover_20_50")
    if supported is None or supported < Decimal("1") or value is None:
        return None
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _supported_value(
    scalars: Mapping[str, float], key: str, support_key: str
) -> Decimal | None:
    supported = _number(scalars, support_key)
    if supported is None or supported < Decimal("1"):
        return None
    return _number(scalars, key)


def _format_decimal_percent(
    scalars: Mapping[str, float], key: str, *, signed: bool = True
) -> str:
    value = _number(scalars, key)
    if value is None:
        return "unavailable"
    numeric = value * Decimal(100)
    return f"{numeric:+.1f}%" if signed else f"{numeric:.1f}%"


def _format_percentage_points(
    scalars: Mapping[str, float], key: str, *, signed: bool = False
) -> str:
    value = _number(scalars, key)
    if value is None:
        return "unavailable"
    return f"{value:+.1f} pp" if signed else f"{value:.1f}%"


def _format_decimal_points(
    scalars: Mapping[str, float], key: str, *, signed: bool = True
) -> str:
    value = _number(scalars, key)
    if value is None:
        return "unavailable"
    numeric = value * Decimal(100)
    return f"{numeric:+.1f} vol points" if signed else f"{numeric:.1f}%"


def _format_number(scalars: Mapping[str, float], key: str, *, digits: int = 1) -> str:
    value = _number(scalars, key)
    if value is None:
        return "unavailable"
    return f"{value:.{digits}f}"


def _format_count(scalars: Mapping[str, float], key: str) -> str:
    value = _number(scalars, key)
    if value is None:
        return "unavailable"
    return str(int(value))


def _format_slope(scalars: Mapping[str, float], key: str) -> str:
    value = _number(scalars, key)
    if value is None:
        return "unavailable"
    return f"{value:+.4f}/session"


def _format_crossover(scalars: Mapping[str, float], prefix: str) -> str:
    vote = _crossover_vote(scalars, prefix)
    if vote is None:
        return "unavailable"
    if vote > 0:
        return "bullish"
    if vote < 0:
        return "bearish"
    return "none"


def _pillar(
    name: str,
    weight: Decimal,
    expected_inputs: int,
    votes: Sequence[int | None],
    evidence: Sequence[str],
    counter_evidence: Sequence[str],
) -> PillarScore:
    if len(votes) != expected_inputs:
        raise ValueError(f"{name} must have {expected_inputs} fixed atoms")
    available = sum(vote is not None for vote in votes)
    vote_sum = sum(vote for vote in votes if vote is not None)
    value = Decimal(2) * Decimal(vote_sum) / Decimal(expected_inputs)
    return PillarScore(
        name=name,
        value=value,
        weight=weight,
        evidence=tuple(evidence),
        counter_evidence=tuple(counter_evidence),
        available_inputs=available,
        expected_inputs=expected_inputs,
    )


def _absolute_votes(scalars: Mapping[str, float]) -> tuple[int | None, ...]:
    return (
        _threshold_vote(
            _number(scalars, "smh_return_20"), Decimal("0.03"), Decimal("-0.03")
        ),
        _threshold_vote(
            _number(scalars, "smh_return_63"), Decimal("0.08"), Decimal("-0.08")
        ),
        _moving_average_vote(scalars, "smh"),
        _threshold_vote(
            _number(scalars, "smh_slope_20"),
            Decimal("0.0005"),
            Decimal("-0.0005"),
        ),
        _threshold_vote(
            _number(scalars, "soxx_return_20"), Decimal("0.03"), Decimal("-0.03")
        ),
        _moving_average_vote(scalars, "soxx"),
    )


def _relative_votes(scalars: Mapping[str, float]) -> tuple[int | None, ...]:
    votes: list[int | None] = []
    for prefix in ("smh_qqq", "soxx_qqq"):
        votes.extend(
            (
                _threshold_vote(
                    _number(scalars, f"{prefix}_return_20"),
                    Decimal("0.02"),
                    Decimal("-0.02"),
                ),
                _threshold_vote(
                    _number(scalars, f"{prefix}_return_63"),
                    Decimal("0.05"),
                    Decimal("-0.05"),
                ),
                _moving_average_vote(scalars, prefix),
                _crossover_vote(scalars, prefix),
            )
        )
    return tuple(votes)


def _breadth_votes(scalars: Mapping[str, float]) -> tuple[int | None, ...]:
    return (
        _threshold_vote(
            _number(scalars, "breadth_above_20_pct"), Decimal("60"), Decimal("40")
        ),
        _threshold_vote(
            _number(scalars, "breadth_above_50_pct"), Decimal("60"), Decimal("40")
        ),
        _threshold_vote(
            _number(scalars, "breadth_above_200_pct"), Decimal("55"), Decimal("45")
        ),
        _threshold_vote(
            _number(scalars, "breadth_20_change_5"), Decimal("10"), Decimal("-10")
        ),
        _threshold_vote(
            _number(scalars, "breadth_50_change_5"), Decimal("10"), Decimal("-10")
        ),
        _threshold_vote(
            _number(scalars, "breadth_200_change_5"), Decimal("10"), Decimal("-10")
        ),
    )


def _participation_votes(scalars: Mapping[str, float]) -> tuple[int | None, ...]:
    spread = _supported_value(
        scalars, "participation_spread_63", "participation_supported"
    )
    outperforming = _supported_value(
        scalars,
        "participation_outperforming_smh_pct",
        "participation_supported",
    )
    return (
        _threshold_vote(spread, Decimal("0.03"), Decimal("-0.03")),
        _threshold_vote(outperforming, Decimal("60"), Decimal("40")),
    )


def _momentum_votes(scalars: Mapping[str, float]) -> tuple[int | None, ...]:
    return (
        _threshold_vote(
            _number(scalars, "momentum_median_20"), Decimal("0.03"), Decimal("-0.03")
        ),
        _threshold_vote(
            _number(scalars, "momentum_positive_pct"), Decimal("60"), Decimal("40")
        ),
    )


def _trend_votes(scalars: Mapping[str, float]) -> tuple[int | None, ...]:
    value = _number(scalars, "trend_positive_cell_pct")
    supported = _number(scalars, "trend_supported_cells")
    if supported is None or supported <= 0:
        value = None
    return (_threshold_vote(value, Decimal("60"), Decimal("40")),)


def _risk_reward_votes(scalars: Mapping[str, float]) -> tuple[int | None, ...]:
    return (
        _threshold_vote(
            _number(scalars, "risk_reward_return_median_63"),
            Decimal("0.08"),
            Decimal("-0.08"),
        ),
    )


def _risk_votes(scalars: Mapping[str, float]) -> tuple[int | None, ...]:
    return (
        _lower_is_better_vote(
            _number(scalars, "smh_vol_percentile_252"),
            Decimal("35"),
            Decimal("70"),
        ),
        _threshold_vote(
            _number(scalars, "smh_drawdown_63"),
            Decimal("-0.03"),
            Decimal("-0.10"),
        ),
        _lower_is_better_vote(
            _number(scalars, "smh_vol_change_5"),
            Decimal("-0.03"),
            Decimal("0.03"),
        ),
        _lower_is_better_vote(
            _number(scalars, "vix_latest"), Decimal("18"), Decimal("25")
        ),
    )


def _absolute_trend(metrics: MetricBundle) -> PillarScore:
    scalars = metrics.scalars
    votes = _absolute_votes(scalars)
    return _pillar(
        "absolute_trend",
        Decimal("0.25"),
        6,
        votes,
        (
            "SMH returns: 20-session "
            f"{_format_decimal_percent(scalars, 'smh_return_20')}; 63-session "
            f"{_format_decimal_percent(scalars, 'smh_return_63')}.",
            "SMH distance from 20-/50-session averages: "
            f"{_format_decimal_percent(scalars, 'smh_distance_sma_20')} / "
            f"{_format_decimal_percent(scalars, 'smh_distance_sma_50')}; "
            f"log slope {_format_slope(scalars, 'smh_slope_20')}.",
            "SOXX returns: 20-session "
            f"{_format_decimal_percent(scalars, 'soxx_return_20')}; 63-session "
            f"{_format_decimal_percent(scalars, 'soxx_return_63')} (evidence only).",
            "SOXL is leveraged and path-dependent; its 20-session return is "
            f"{_format_decimal_percent(scalars, 'soxl_return_20')} (evidence only).",
        ),
        (
            "Absolute trend would weaken if 20-session returns fall to -3.0% "
            "or both 20-/50-session average distances reach -0.5%.",
        ),
    )


def _relative_leadership(metrics: MetricBundle) -> PillarScore:
    scalars = metrics.scalars
    votes = _relative_votes(scalars)
    return _pillar(
        "relative_leadership",
        Decimal("0.20"),
        8,
        votes,
        (
            "SMH/QQQ changes: 20-session "
            f"{_format_decimal_percent(scalars, 'smh_qqq_return_20')}; "
            f"63-session {_format_decimal_percent(scalars, 'smh_qqq_return_63')}; "
            f"recent crossover {_format_crossover(scalars, 'smh_qqq')}.",
            "SOXX/QQQ changes: 20-session "
            f"{_format_decimal_percent(scalars, 'soxx_qqq_return_20')}; "
            f"63-session {_format_decimal_percent(scalars, 'soxx_qqq_return_63')}; "
            f"recent crossover {_format_crossover(scalars, 'soxx_qqq')}.",
        ),
        (
            "Relative leadership would weaken if both ratios lose 2.0% over "
            "20 sessions or move at least 0.5% below both averages.",
        ),
    )


def _breadth_participation(metrics: MetricBundle) -> PillarScore:
    scalars = metrics.scalars
    votes = (*_breadth_votes(scalars), *_participation_votes(scalars))
    return _pillar(
        "breadth_participation",
        Decimal("0.25"),
        8,
        votes,
        (
            "Above-average breadth (20/50/200 sessions): "
            f"{_format_percentage_points(scalars, 'breadth_above_20_pct')} / "
            f"{_format_percentage_points(scalars, 'breadth_above_50_pct')} / "
            f"{_format_percentage_points(scalars, 'breadth_above_200_pct')}.",
            "Five-session breadth changes (20/50/200): "
            f"{_format_percentage_points(scalars, 'breadth_20_change_5', signed=True)} / "
            f"{_format_percentage_points(scalars, 'breadth_50_change_5', signed=True)} / "
            f"{_format_percentage_points(scalars, 'breadth_200_change_5', signed=True)}.",
            "Median participation spread (one symbol, one vote) is "
            f"{_format_decimal_percent(scalars, 'participation_spread_63')}; "
            f"{_format_percentage_points(scalars, 'participation_outperforming_smh_pct')} "
            "outperformed SMH.",
            "Participation dispersion is "
            f"{_format_decimal_percent(scalars, 'participation_dispersion_63', signed=False)} "
            "(counter-evidence only).",
        ),
        (
            "Participation would weaken if 20-/50-session breadth reaches 40% "
            "or the median participation spread falls to -3.0%.",
        ),
    )


def _momentum_distribution(metrics: MetricBundle) -> PillarScore:
    scalars = metrics.scalars
    votes = (
        *_momentum_votes(scalars),
        *_trend_votes(scalars),
        *_risk_reward_votes(scalars),
    )
    return _pillar(
        "momentum_distribution",
        Decimal("0.15"),
        4,
        votes,
        (
            "Watchlist 20-session median return is "
            f"{_format_decimal_percent(scalars, 'momentum_median_20')}; positive "
            f"share {_format_percentage_points(scalars, 'momentum_positive_pct')}.",
            "Positive supported heatmap cells are "
            f"{_format_percentage_points(scalars, 'trend_positive_cell_pct')}; "
            "risk/reward-map median 63-session return is "
            f"{_format_decimal_percent(scalars, 'risk_reward_return_median_63')}.",
            "The 20-session momentum IQR is "
            f"{_format_decimal_percent(scalars, 'momentum_iqr_20', signed=False)} "
            "(15 percentage points or more is a concentration warning).",
        ),
        (
            "Momentum would weaken if the median return reaches -3.0% or the "
            "positive share reaches 40%.",
        ),
    )


def _volatility_drawdown_risk(metrics: MetricBundle) -> PillarScore:
    scalars = metrics.scalars
    votes = _risk_votes(scalars)
    return _pillar(
        "volatility_drawdown_risk",
        Decimal("0.15"),
        4,
        votes,
        (
            "SMH 20-session realized volatility is "
            f"{_format_decimal_percent(scalars, 'smh_vol_20', signed=False)} at "
            f"the {_format_number(scalars, 'smh_vol_percentile_252')} percentile.",
            "SMH distance from 63-session peak is "
            f"{_format_decimal_percent(scalars, 'smh_drawdown_63')}; its "
            "five-session volatility change is "
            f"{_format_decimal_points(scalars, 'smh_vol_change_5')}.",
            f"VIX is {_format_number(scalars, 'vix_latest')}.",
        ),
        (
            "Risk conditions would worsen if volatility reaches its 70th "
            "percentile, the peak distance reaches -10.0%, or VIX reaches 25.",
        ),
    )


def score_pillars(metrics: MetricBundle) -> tuple[PillarScore, ...]:
    """Score all five versioned pillars in their fixed published order."""

    pillars = (
        _absolute_trend(metrics),
        _relative_leadership(metrics),
        _breadth_participation(metrics),
        _momentum_distribution(metrics),
        _volatility_drawdown_risk(metrics),
    )
    expected_contract = tuple((name, weight, count) for name, weight, count in _WEIGHTS)
    actual_contract = tuple(
        (item.name, item.weight, item.expected_inputs) for item in pillars
    )
    if actual_contract != expected_contract:
        raise RuntimeError("pillar contract drifted from semipulse-rules-v1")
    return pillars


def _composite_score(pillars: Sequence[PillarScore]) -> Decimal:
    weighted = sum((pillar.value * pillar.weight for pillar in pillars), Decimal("0"))
    return weighted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def classify_regime(score: Decimal | float) -> str:
    """Map an exact composite score to the audited five regime labels."""

    exact = score if isinstance(score, Decimal) else Decimal(str(score))
    if exact >= Decimal("1.20"):
        return "risk-on"
    if exact >= Decimal("0.45"):
        return "constructive"
    if exact > Decimal("-0.45"):
        return "mixed"
    if exact > Decimal("-1.20"):
        return "defensive"
    return "risk-off"


def _validate_audit_records(
    records: Sequence[CompositeAuditRecord],
    *,
    current: MetricBundle | None = None,
) -> tuple[CompositeAuditRecord, ...]:
    validated = tuple(records)
    if len(validated) > 5:
        raise ValueError("audit accepts at most five records")
    dates = tuple(record.as_of for record in validated)
    if len(set(dates)) != len(dates):
        raise ValueError("audit records contain duplicate as-of dates")
    if dates != tuple(sorted(dates)):
        raise ValueError("audit records must be chronological")

    expected_contract = _WEIGHTS
    for record in validated:
        if record.rules_version != RULES_VERSION:
            raise ValueError("audit record rules version does not match")
        contract = tuple(
            (pillar.name, pillar.weight, pillar.expected_inputs)
            for pillar in record.pillars
        )
        if contract != expected_contract:
            raise ValueError("audit record pillar contract does not match")
        if any(
            pillar.available_inputs < 0
            or pillar.available_inputs > pillar.expected_inputs
            for pillar in record.pillars
        ):
            raise ValueError("audit record input availability is invalid")
        available = sum(
            pillar.available_inputs for pillar in record.pillars
        )
        expected = sum(pillar.expected_inputs for pillar in record.pillars)
        if (
            record.available_inputs != available
            or record.expected_inputs != expected
        ):
            raise ValueError("audit record input totals do not match pillars")
        rebuilt_score = _composite_score(record.pillars)
        if record.composite_score != rebuilt_score:
            raise ValueError("audit record score does not match pillars")
        if record.regime != classify_regime(record.composite_score):
            raise ValueError("audit record regime does not match score")

    if current is not None and validated:
        current_pillars = score_pillars(current)
        current_score = _composite_score(current_pillars)
        if validated[-1].as_of != current.as_of:
            raise ValueError("latest audit record must match current metrics date")
        if validated[-1].metrics_version != current.methodology_version:
            raise ValueError("latest audit metrics version does not match current")
        if validated[-1].pillars != current_pillars:
            raise ValueError("latest audit record must match current pillars")
        if validated[-1].composite_score != current_score:
            raise ValueError("latest audit record must match current score")
    return validated


def build_composite_audit(
    snapshots: Sequence[MetricBundle],
    *,
    current: MetricBundle,
) -> tuple[CompositeAuditRecord, ...]:
    """Build up to five non-chart records from independent metric snapshots."""

    if not snapshots:
        raise ValueError("audit requires at least one snapshot")
    if len(snapshots) > 5:
        raise ValueError("audit accepts at most five snapshots")
    dates = tuple(snapshot.as_of for snapshot in snapshots)
    if len(set(dates)) != len(dates):
        raise ValueError("audit snapshots contain duplicate as-of dates")
    if dates != tuple(sorted(dates)):
        raise ValueError("audit snapshots must be chronological")
    if dates[-1] != current.as_of:
        raise ValueError("latest audit snapshot must match current as-of date")

    records: list[CompositeAuditRecord] = []
    for snapshot in snapshots:
        pillars = score_pillars(snapshot)
        score = _composite_score(pillars)
        records.append(
            CompositeAuditRecord(
                as_of=snapshot.as_of,
                metrics_version=snapshot.methodology_version,
                rules_version=RULES_VERSION,
                pillars=pillars,
                composite_score=score,
                regime=classify_regime(score),
                available_inputs=sum(pillar.available_inputs for pillar in pillars),
                expected_inputs=sum(pillar.expected_inputs for pillar in pillars),
            )
        )

    return _validate_audit_records(records, current=current)


def _signal(pillar: PillarScore) -> str:
    if pillar.available_inputs == 0:
        return "limited"
    if pillar.value >= Decimal("0.25"):
        return "positive"
    if pillar.value <= Decimal("-0.25"):
        return "negative"
    return "mixed"


def _signal_from_votes(votes: Sequence[int | None]) -> str:
    available = tuple(vote for vote in votes if vote is not None)
    if not available:
        return "limited"
    net = sum(available)
    if net > 0:
        return "positive"
    if net < 0:
        return "negative"
    return "mixed"


def _counter_signal(signal: str, weaker: str, stronger: str) -> str:
    if signal == "positive":
        return f"Invalidation: {weaker}"
    if signal == "negative":
        return f"Potential improvement: {stronger}"
    if signal == "limited":
        return (
            "Limitation: missing evidence prevents a directional reading; "
            f"improvement requires {stronger.lower()}"
        )
    return f"Two-way trigger: the view improves if {stronger}; it weakens if {weaker}"


def _quality_note(quality: QualityReport) -> str:
    return (
        f"Quality coverage is {quality.covered_count}/{quality.watchlist_count} "
        f"symbols ({quality.coverage_ratio * Decimal(100):.1f}%)."
    )


def _breadth_divergence(metrics: MetricBundle) -> str:
    smh_return = _number(metrics.scalars, "smh_return_20")
    breadth_change = _number(metrics.scalars, "breadth_50_change_5")
    if smh_return is None or breadth_change is None:
        return "Divergence check is unavailable because one input is missing."
    if smh_return > 0 and breadth_change < 0:
        return "Negative divergence: SMH rose while 50-session breadth narrowed."
    if smh_return < 0 and breadth_change > 0:
        return "Positive divergence: SMH fell while 50-session breadth improved."
    return "SMH direction and the five-session 50-day breadth change do not diverge."


def _latest_breadth_counts(metrics: MetricBundle) -> str:
    required = {
        "date",
        *(f"above_{window}_count" for window in (20, 50, 200)),
        *(f"covered_{window}_count" for window in (20, 50, 200)),
        *(f"missing_{window}_count" for window in (20, 50, 200)),
    }
    if metrics.breadth.empty or not required.issubset(metrics.breadth.columns):
        return "Latest breadth counts are unavailable."
    dates = pd.to_datetime(metrics.breadth["date"], errors="coerce")
    latest = metrics.breadth.loc[dates.eq(pd.Timestamp(metrics.as_of))]
    if latest.empty:
        return "Latest breadth counts are unavailable."
    row = latest.iloc[-1]
    parts: list[str] = []
    for window in (20, 50, 200):
        values: list[int] = []
        for prefix in ("above", "covered", "missing"):
            value = pd.to_numeric(
                pd.Series([row[f"{prefix}_{window}_count"]]),
                errors="coerce",
            ).iloc[0]
            if pd.isna(value) or not isfinite(float(value)):
                return "Latest breadth counts are unavailable."
            values.append(int(value))
        above, covered, missing = values
        parts.append(
            f"{window}-session: {above}/{covered} above, {missing} missing"
        )
    return "Exact latest breadth counts — " + "; ".join(parts) + "."


def _high_return_trend_cross_check(metrics: MetricBundle) -> str:
    median = _number(metrics.scalars, "risk_reward_return_median_63")
    required_risk = {"symbol", "return_63", "xy_supported"}
    required_trend = {"symbol", "value", "supported"}
    if (
        median is None
        or metrics.risk_reward.empty
        or not required_risk.issubset(metrics.risk_reward.columns)
    ):
        return "High-return trend cross-check is unavailable."

    risk = metrics.risk_reward.copy()
    risk["return_63"] = pd.to_numeric(risk["return_63"], errors="coerce")
    high_return = risk.loc[
        risk["xy_supported"].fillna(False).astype(bool)
        & risk["return_63"].map(
            lambda value: isfinite(float(value)) if pd.notna(value) else False
        )
        & risk["return_63"].gt(float(median))
    ]
    if high_return.empty:
        return (
            "High-return names with fewer than three positive supported trend "
            "cells: none."
        )
    if metrics.trend_heatmap.empty or not required_trend.issubset(
        metrics.trend_heatmap.columns
    ):
        return (
            "High-return names with fewer than three positive supported trend "
            "cells: unavailable because trend support is absent."
        )

    trend = metrics.trend_heatmap.copy()
    trend["value"] = pd.to_numeric(trend["value"], errors="coerce")
    findings: list[str] = []
    for symbol in high_return["symbol"].astype(str):
        rows = trend.loc[
            trend["symbol"].astype(str).eq(symbol)
            & trend["supported"].fillna(False).astype(bool)
            & trend["value"].map(
                lambda value: isfinite(float(value))
                if pd.notna(value)
                else False
            )
        ]
        if rows.empty:
            findings.append(f"{symbol} (trend support unavailable)")
            continue
        positive = int(rows["value"].gt(0.0).sum())
        supported = len(rows)
        if positive < 3:
            findings.append(
                f"{symbol} ({positive}/{supported} positive supported cells)"
            )
    rendered = ", ".join(findings) if findings else "none"
    return (
        "High-return names with fewer than three positive supported trend "
        f"cells: {rendered}."
    )


def _finite_rows(frame: pd.DataFrame, value_column: str) -> pd.DataFrame:
    if frame.empty or value_column not in frame or "symbol" not in frame:
        return pd.DataFrame(columns=["symbol", value_column])
    values = pd.to_numeric(frame[value_column], errors="coerce")
    mask = values.map(
        lambda value: isfinite(float(value)) if pd.notna(value) else False
    )
    if "supported" in frame:
        mask &= frame["supported"].fillna(False).astype(bool)
    if "eligible" in frame:
        mask &= frame["eligible"].fillna(False).astype(bool)
    output = frame.loc[mask].copy()
    output[value_column] = values.loc[mask]
    return output


def _format_symbol_returns(frame: pd.DataFrame, count: int = 3) -> str:
    if frame.empty:
        return "unavailable"
    items = tuple(
        f"{row.symbol} {float(row.return_20) * 100:+.1f}%"
        for row in frame.head(count).itertuples(index=False)
    )
    return ", ".join(items)


def _trend_names(frame: pd.DataFrame) -> tuple[str, str, str]:
    supported = frame.copy()
    if supported.empty or not {
        "symbol",
        "metric",
        "value",
        "supported",
    }.issubset(supported):
        return "unavailable", "unavailable", "none supported"
    supported["value"] = pd.to_numeric(supported["value"], errors="coerce")
    supported = supported.loc[
        supported["supported"].fillna(False).astype(bool)
        & supported["value"].map(
            lambda value: isfinite(float(value)) if pd.notna(value) else False
        )
    ]
    if supported.empty:
        return "unavailable", "unavailable", "none supported"
    ranking = (
        supported.assign(positive=supported["value"].gt(0.0).astype(int))
        .groupby("symbol", sort=False)
        .agg(
            positive=("positive", "sum"),
            mean_value=("value", "mean"),
            symbol_order=("symbol_order", "min"),
        )
        .reset_index()
    )
    strongest = ranking.sort_values(
        ["positive", "mean_value", "symbol_order", "symbol"],
        ascending=[False, False, True, True],
        kind="stable",
    ).iloc[0]["symbol"]
    weakest = ranking.sort_values(
        ["positive", "mean_value", "symbol_order", "symbol"],
        ascending=[True, True, True, True],
        kind="stable",
    ).iloc[0]["symbol"]
    pivot = supported.pivot_table(
        index="symbol", columns="metric", values="value", aggfunc="first"
    )
    reversals: list[str] = []
    if {"return_5", "return_63"}.issubset(pivot.columns):
        for symbol, row in pivot.iterrows():
            short = float(row["return_5"])
            long = float(row["return_63"])
            if isfinite(short) and isfinite(long) and short * long < 0:
                reversals.append(str(symbol))
    return str(strongest), str(weakest), ", ".join(reversals) or "none"


def _chart_one(
    metrics: MetricBundle, quality: QualityReport, pillar: PillarScore
) -> ChartInsight:
    scalars = metrics.scalars
    signal = _signal(pillar)
    return ChartInsight(
        chart_id="chart-1",
        headline=f"Semiconductor complex trend is {signal}.",
        signal=signal,
        evidence=(
            "SMH 5/20/63-session returns: "
            f"{_format_decimal_percent(scalars, 'smh_return_5')} / "
            f"{_format_decimal_percent(scalars, 'smh_return_20')} / "
            f"{_format_decimal_percent(scalars, 'smh_return_63')}; distance "
            "from 63-session peak "
            f"{_format_decimal_percent(scalars, 'smh_drawdown_63')}.",
            "SOXX 5/20/63-session returns: "
            f"{_format_decimal_percent(scalars, 'soxx_return_5')} / "
            f"{_format_decimal_percent(scalars, 'soxx_return_20')} / "
            f"{_format_decimal_percent(scalars, 'soxx_return_63')}; distance "
            "from 63-session peak "
            f"{_format_decimal_percent(scalars, 'soxx_drawdown_63')}.",
            "QQQ 5/20/63-session returns: "
            f"{_format_decimal_percent(scalars, 'qqq_return_5')} / "
            f"{_format_decimal_percent(scalars, 'qqq_return_20')} / "
            f"{_format_decimal_percent(scalars, 'qqq_return_63')}; distance "
            "from 63-session peak "
            f"{_format_decimal_percent(scalars, 'qqq_drawdown_63')}.",
            "SMH distance from 20-/50-session averages and log slope: "
            f"{_format_decimal_percent(scalars, 'smh_distance_sma_20')} / "
            f"{_format_decimal_percent(scalars, 'smh_distance_sma_50')} / "
            f"{_format_slope(scalars, 'smh_slope_20')}.",
            "SOXL leveraged 5/20/63-session returns: "
            f"{_format_decimal_percent(scalars, 'soxl_return_5')} / "
            f"{_format_decimal_percent(scalars, 'soxl_return_20')} / "
            f"{_format_decimal_percent(scalars, 'soxl_return_63')}; SOXL is a "
            "leveraged, path-dependent ETF.",
        ),
        interpretation=(
            "The benchmark trend measures whether the complex has sustained "
            "directional confirmation; leveraged SOXL can magnify gains and "
            "losses through path-dependent compounding."
        ),
        trading_relevance=(
            "If SMH and SOXX maintain aligned trend evidence, that condition "
            "would support broader risk-taking research; divergence would favor "
            "more conservative risk assumptions."
        ),
        counter_signal=_counter_signal(
            signal,
            "SMH or SOXX loses -3.0% over 20 sessions and both average states turn negative.",
            "SMH and SOXX regain +3.0% 20-session returns above both trend averages.",
        ),
        notes=(
            "Returns use adjusted close; the chart rebases each series to 100.",
            _quality_note(quality),
        ),
    )


def _chart_two(
    metrics: MetricBundle, quality: QualityReport, pillar: PillarScore
) -> ChartInsight:
    scalars = metrics.scalars
    signal = _signal(pillar)
    return ChartInsight(
        chart_id="chart-2",
        headline=f"Semiconductor leadership versus QQQ is {signal}.",
        signal=signal,
        evidence=(
            "SMH/QQQ 20-/63-session changes: "
            f"{_format_decimal_percent(scalars, 'smh_qqq_return_20')} / "
            f"{_format_decimal_percent(scalars, 'smh_qqq_return_63')}; distances "
            "from 20-/50-session averages: "
            f"{_format_decimal_percent(scalars, 'smh_qqq_distance_sma_20')} / "
            f"{_format_decimal_percent(scalars, 'smh_qqq_distance_sma_50')}; "
            f"crossover {_format_crossover(scalars, 'smh_qqq')}.",
            "SOXX/QQQ 20-/63-session changes: "
            f"{_format_decimal_percent(scalars, 'soxx_qqq_return_20')} / "
            f"{_format_decimal_percent(scalars, 'soxx_qqq_return_63')}; distances "
            "from 20-/50-session averages: "
            f"{_format_decimal_percent(scalars, 'soxx_qqq_distance_sma_20')} / "
            f"{_format_decimal_percent(scalars, 'soxx_qqq_distance_sma_50')}; "
            f"crossover {_format_crossover(scalars, 'soxx_qqq')}.",
        ),
        interpretation=(
            "The ratios isolate semiconductor-specific leadership from broad "
            "technology beta. A ratio can rise while both numerator and QQQ fall."
        ),
        trading_relevance=(
            "If both ratios hold positive multi-horizon trends, semiconductor "
            "exposure would have relative confirmation; absolute price trend "
            "still determines whether that leadership occurs in a rising market."
        ),
        counter_signal=_counter_signal(
            signal,
            "both ratios lose 2.0% over 20 sessions or bearish crossovers appear.",
            "both ratios gain 2.0% over 20 sessions above both moving averages.",
        ),
        notes=(
            "Ratios use only dates shared exactly with QQQ and are never filled.",
            _quality_note(quality),
        ),
    )


def _chart_three(metrics: MetricBundle, quality: QualityReport) -> ChartInsight:
    scalars = metrics.scalars
    signal = _signal_from_votes(_breadth_votes(scalars))
    return ChartInsight(
        chart_id="chart-3",
        headline=f"Watchlist breadth is {signal}.",
        signal=signal,
        evidence=(
            _latest_breadth_counts(metrics),
            "Above 20-/50-/200-session averages: "
            f"{_format_percentage_points(scalars, 'breadth_above_20_pct')} "
            f"({_format_count(scalars, 'breadth_covered_20_count')} eligible), "
            f"{_format_percentage_points(scalars, 'breadth_above_50_pct')} "
            f"({_format_count(scalars, 'breadth_covered_50_count')} eligible), "
            f"{_format_percentage_points(scalars, 'breadth_above_200_pct')} "
            f"({_format_count(scalars, 'breadth_covered_200_count')} eligible).",
            "Five-session changes for 20-/50-/200-session breadth: "
            f"{_format_percentage_points(scalars, 'breadth_20_change_5', signed=True)} / "
            f"{_format_percentage_points(scalars, 'breadth_50_change_5', signed=True)} / "
            f"{_format_percentage_points(scalars, 'breadth_200_change_5', signed=True)}.",
            _breadth_divergence(metrics),
        ),
        interpretation=(
            "Breadth distinguishes broad participation from an index move "
            "carried by a smaller set of constituents."
        ),
        trading_relevance=(
            "If intermediate and long-horizon breadth expand with SMH, trend "
            "research has wider confirmation; narrowing breadth would raise "
            "concentration and reversal risk."
        ),
        counter_signal=_counter_signal(
            signal,
            "20- and 50-session breadth fall to 40% or drop 10 percentage points in five sessions.",
            "20- and 50-session breadth rise to 60% with improving five-session changes.",
        ),
        notes=(
            "Each horizon prints its own exact eligible denominator; missing observations are not imputed.",
            _quality_note(quality),
        ),
    )


def _chart_four(metrics: MetricBundle, quality: QualityReport) -> ChartInsight:
    scalars = metrics.scalars
    signal = _signal_from_votes(_participation_votes(scalars))
    return ChartInsight(
        chart_id="chart-4",
        headline=f"Equal-weight participation is {signal}.",
        signal=signal,
        evidence=(
            "Median participation spread (watchlist median minus SMH over 63 sessions): "
            f"{_format_decimal_percent(scalars, 'participation_spread_63')}; "
            "members outperforming SMH: "
            f"{_format_percentage_points(scalars, 'participation_outperforming_smh_pct')}.",
            "Cross-sectional dispersion: "
            f"{_format_decimal_percent(scalars, 'participation_dispersion_63', signed=False)}; "
            f"eligible {_format_count(scalars, 'participation_eligible_count')}; "
            f"missing {_format_count(scalars, 'participation_missing_count')}.",
        ),
        interpretation=(
            "One symbol, one vote; the cross-sectional median participation "
            "spread tests whether the index move is broadly shared. High "
            "dispersion is counter-evidence to a uniform trend."
        ),
        trading_relevance=(
            "If the median participation spread and outperformer share improve "
            "together, the index trend would have stronger participation confirmation."
        ),
        counter_signal=_counter_signal(
            signal,
            "the spread reaches -3.0% or no more than 40% of eligible members outperform SMH.",
            "the spread reaches +3.0% and at least 60% of eligible members outperform SMH.",
        ),
        notes=(
            "Participation requires a common 64-observation SMH window for a true t/t-63 return.",
            _quality_note(quality),
        ),
    )


def _chart_five(metrics: MetricBundle, quality: QualityReport) -> ChartInsight:
    scalars = metrics.scalars
    signal = _signal_from_votes(_momentum_votes(scalars))
    finite = _finite_rows(metrics.momentum, "return_20").sort_values(
        ["return_20", "symbol"],
        ascending=[False, True],
        kind="stable",
    )
    laggards = finite.sort_values(
        ["return_20", "symbol"], ascending=[True, True], kind="stable"
    )
    return ChartInsight(
        chart_id="chart-5",
        headline=f"Watchlist momentum distribution is {signal}.",
        signal=signal,
        evidence=(
            f"Top three finite 20-session returns: {_format_symbol_returns(finite)}.",
            f"Bottom three finite 20-session returns: {_format_symbol_returns(laggards)}.",
            "Median / IQR / positive share: "
            f"{_format_decimal_percent(scalars, 'momentum_median_20')} / "
            f"{_format_decimal_percent(scalars, 'momentum_iqr_20', signed=False)} / "
            f"{_format_percentage_points(scalars, 'momentum_positive_pct')}.",
            f"Eligible {_format_count(scalars, 'momentum_eligible_count')}; "
            f"unsupported {_format_count(scalars, 'momentum_missing_count')}.",
        ),
        interpretation=(
            "This ranking is descriptive, not a chase list. A wide IQR can mean "
            "headline strength is concentrated rather than broadly repeatable."
        ),
        trading_relevance=(
            "If the median and positive share improve while dispersion remains "
            "contained, follow-through research would have broader support."
        ),
        counter_signal=_counter_signal(
            signal,
            "the median reaches -3.0%, the positive share reaches 40%, or the IQR widens beyond 15 percentage points.",
            "the median reaches +3.0% and the positive share reaches 60% without extreme concentration.",
        ),
        notes=(
            "Unsupported symbols remain visible but are not ranked as laggards.",
            _quality_note(quality),
        ),
    )


def _chart_six(metrics: MetricBundle, quality: QualityReport) -> ChartInsight:
    scalars = metrics.scalars
    signal = _signal_from_votes(_trend_votes(scalars))
    strongest, weakest, reversals = _trend_names(metrics.trend_heatmap)
    supported = _format_count(scalars, "trend_supported_cells")
    missing = _number(scalars, "trend_missing_cells")
    total = "unavailable"
    supported_value = _number(scalars, "trend_supported_cells")
    if supported_value is not None and missing is not None:
        total = str(int(supported_value + missing))
    return ChartInsight(
        chart_id="chart-6",
        headline=f"Multi-horizon trend participation is {signal}.",
        signal=signal,
        evidence=(
            "Positive supported cells: "
            f"{_format_percentage_points(scalars, 'trend_positive_cell_pct')}; "
            f"supported {supported}/{total}; missing {_format_count(scalars, 'trend_missing_cells')}.",
            f"Deterministic strongest / weakest trend profiles: {strongest} / {weakest}.",
            f"Short-versus-long return reversals: {reversals}.",
        ),
        interpretation=(
            "The heatmap checks whether return and moving-average evidence agree "
            "across symbols and horizons; reversals identify internal rotation."
        ),
        trading_relevance=(
            "If positive cells expand beyond 60% with fewer reversals, directional "
            "research would have better cross-horizon confirmation."
        ),
        counter_signal=_counter_signal(
            signal,
            "positive cells fall to 40% or short-horizon reversals spread.",
            "positive cells rise to 60% with stronger multi-horizon agreement.",
        ),
        notes=(
            "Winsorization applies only to chart color scaling; labels and interpretation use actual values.",
            _quality_note(quality),
        ),
    )


def _chart_seven(
    metrics: MetricBundle, quality: QualityReport, pillar: PillarScore
) -> ChartInsight:
    scalars = metrics.scalars
    signal = _signal(pillar)
    vix = _format_number(scalars, "vix_latest")
    return ChartInsight(
        chart_id="chart-7",
        headline=f"Volatility and drawdown conditions are {signal}.",
        signal=signal,
        evidence=(
            "SMH 20-session annualized realized volatility: "
            f"{_format_decimal_percent(scalars, 'smh_vol_20', signed=False)}; "
            f"trailing percentile {_format_number(scalars, 'smh_vol_percentile_252')}; "
            f"five-session change {_format_decimal_points(scalars, 'smh_vol_change_5')}.",
            "SMH distance from 63-session peak: "
            f"{_format_decimal_percent(scalars, 'smh_drawdown_63')}.",
            "50-session breadth is "
            f"{_format_percentage_points(scalars, 'breadth_above_50_pct')}; VIX is {vix}.",
        ),
        interpretation=(
            "Volatility, distance from the recent peak, breadth, and VIX test "
            "whether price stress is isolated or broadly confirmed."
        ),
        trading_relevance=(
            "If volatility cools while peak distance and breadth recover, adverse "
            "risk conditions would be easing; simultaneous deterioration would "
            "support more conservative scenario assumptions."
        ),
        counter_signal=_counter_signal(
            signal,
            "volatility reaches its 70th percentile, peak distance reaches -10.0%, or VIX reaches 25.",
            "volatility falls to its 35th percentile, peak distance improves to -3.0%, and VIX is 18 or lower.",
        ),
        notes=(
            "Distance from the 63-session peak is current drawdown, not a forecast.",
            "Missing VIX is noncritical but reduces confidence.",
            _quality_note(quality),
        ),
    )


def _chart_eight(metrics: MetricBundle, quality: QualityReport) -> ChartInsight:
    scalars = metrics.scalars
    signal = _signal_from_votes(_risk_reward_votes(scalars))
    frame = metrics.risk_reward
    supported = frame.loc[
        frame.get("xy_supported", pd.Series(False, index=frame.index))
        .fillna(False)
        .astype(bool)
    ].copy()
    counts: dict[str, int] = {}
    if "quadrant" in supported:
        counts = {
            str(key): int(value)
            for key, value in supported["quadrant"].value_counts().items()
        }
    quadrant_order = (
        "higher-return/lower-vol",
        "higher-return/higher-vol",
        "lower-return/lower-vol",
        "lower-return/higher-vol",
    )
    count_text = ", ".join(f"{name} {counts.get(name, 0)}" for name in quadrant_order)
    outliers = _finite_rows(supported, "return_63")
    if outliers.empty:
        outlier_text = "unavailable"
    else:
        high = outliers.sort_values(
            ["return_63", "symbol"], ascending=[False, True], kind="stable"
        ).iloc[0]
        low = outliers.sort_values(
            ["return_63", "symbol"], ascending=[True, True], kind="stable"
        ).iloc[0]
        outlier_text = (
            f"{high['symbol']} {float(high['return_63']) * 100:+.1f}% / "
            f"{low['symbol']} {float(low['return_63']) * 100:+.1f}%"
        )
    return ChartInsight(
        chart_id="chart-8",
        headline=f"Cross-sectional risk/reward distribution is {signal}.",
        signal=signal,
        evidence=(
            "Reference medians: 63-session return "
            f"{_format_decimal_percent(scalars, 'risk_reward_return_median_63')}; "
            "20-session annualized volatility "
            f"{_format_decimal_percent(scalars, 'risk_reward_vol_median_20', signed=False)}.",
            f"Quadrant counts: {count_text}.",
            f"Highest / lowest supported return outliers: {outlier_text}.",
            _high_return_trend_cross_check(metrics),
            f"XY eligible {_format_count(scalars, 'risk_reward_xy_eligible_count')}; "
            f"XY missing {_format_count(scalars, 'risk_reward_xy_missing_count')}; "
            "liquidity bubbles missing "
            f"{_format_count(scalars, 'risk_reward_liquidity_missing_count')}.",
        ),
        interpretation=(
            "The map compares observed return with realized volatility and "
            "liquidity context. It is a research map, not a portfolio optimizer."
        ),
        trading_relevance=(
            "If higher-return/lower-vol observations broaden with adequate "
            "liquidity, cross-sectional conditions would be more balanced; "
            "high-return/high-vol outliers retain reversal and sizing risk."
        ),
        counter_signal=_counter_signal(
            signal,
            "more symbols migrate to lower-return/higher-vol and liquidity support declines.",
            "more symbols migrate to higher-return/lower-vol with supported liquidity.",
        ),
        notes=(
            "Bubble size is median 20-session dollar volume when available; missing liquidity is disclosed, not imputed.",
            _quality_note(quality),
        ),
    )


def interpret_charts(
    metrics: MetricBundle, quality: QualityReport
) -> tuple[ChartInsight, ...]:
    """Return exactly eight ordered, observation-led chart interpretations."""

    pillars = score_pillars(metrics)
    insights = (
        _chart_one(metrics, quality, pillars[0]),
        _chart_two(metrics, quality, pillars[1]),
        _chart_three(metrics, quality),
        _chart_four(metrics, quality),
        _chart_five(metrics, quality),
        _chart_six(metrics, quality),
        _chart_seven(metrics, quality, pillars[4]),
        _chart_eight(metrics, quality),
    )
    if tuple(item.chart_id for item in insights) != tuple(
        f"chart-{number}" for number in range(1, 9)
    ):
        raise RuntimeError("interpretation contract must contain exactly eight charts")
    return insights


def _confidence(
    metrics: MetricBundle,
    quality: QualityReport,
    pillars: Sequence[PillarScore],
    audit: Sequence[CompositeAuditRecord],
) -> str:
    available = sum(item.available_inputs for item in pillars)
    expected = sum(item.expected_inputs for item in pillars)
    low = (
        quality.coverage_ratio < Decimal("0.70")
        or bool(quality.missing_required)
        or (quality.calendar_age_days is not None and quality.calendar_age_days > 3)
        or any(item.available_inputs == 0 for item in pillars)
        or Decimal(available) / Decimal(expected) < Decimal("0.70")
    )
    if low:
        return "low"
    medium = (
        quality.coverage_ratio < Decimal("0.90")
        or bool(quality.missing_optional)
        or bool(quality.stale_symbols)
        or bool(quality.missing_symbols)
        or bool(quality.warnings)
        or quality.calendar_age_days is None
        or quality.expected_session_lag is None
        or quality.expected_session_lag > 1
        or available < expected
        or (_number(metrics.scalars, "trend_missing_cells") or Decimal("0")) > 0
        or len(audit) < 5
    )
    return "medium" if medium else "high"


def _quality_challenges(
    metrics: MetricBundle,
    quality: QualityReport,
    pillars: Sequence[PillarScore],
    audit: Sequence[CompositeAuditRecord],
) -> tuple[str, ...]:
    challenges: list[str] = []
    if quality.coverage_ratio < Decimal("0.90"):
        challenges.append(
            f"Coverage is {quality.covered_count}/{quality.watchlist_count} symbols."
        )
    if quality.missing_required:
        challenges.append(
            "Required benchmark inputs are missing: "
            + ", ".join(quality.missing_required)
            + "."
        )
    if quality.missing_optional:
        challenges.append(
            "Optional input is missing: " + ", ".join(quality.missing_optional) + "."
        )
    available = sum(item.available_inputs for item in pillars)
    if available < EXPECTED_ATOM_COUNT:
        challenges.append(
            f"Only {available}/{EXPECTED_ATOM_COUNT} scoring inputs are available; missing atoms vote zero."
        )
    if quality.calendar_age_days is not None and quality.calendar_age_days > 0:
        challenges.append(
            f"Market data is {quality.calendar_age_days} calendar days old."
        )
    if quality.expected_session_lag is not None and quality.expected_session_lag > 0:
        challenges.append(
            f"Market data trails the expected session by {quality.expected_session_lag} session(s)."
        )
    trend_missing = _number(metrics.scalars, "trend_missing_cells")
    if trend_missing is not None and trend_missing > 0:
        challenges.append(f"{int(trend_missing)} trend cells are unsupported.")
    if len(audit) < 5:
        challenges.append(
            f"Five-session audit history is incomplete ({len(audit)}/5 snapshots)."
        )
    if quality.warnings:
        challenges.append(
            f"Quality gate reports {len(quality.warnings)} nonfatal warning(s)."
        )
    return tuple(challenges)


def _pillar_label(pillar: PillarScore) -> str:
    return pillar.name.replace("_", " ")


def _directional_summary(
    pillars: Sequence[PillarScore], regime: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    contributions = tuple(
        (pillar, pillar.value * pillar.weight) for pillar in pillars
    )
    positive = tuple(item for item in contributions if item[1] > 0)
    negative = tuple(item for item in contributions if item[1] < 0)

    if regime in {"risk-on", "constructive"}:
        strongest = max(positive, key=lambda item: item[1])
        supports = (
            "Positive contribution: "
            f"{_pillar_label(strongest[0])} adds {strongest[1]:+.2f} "
            f"from a {strongest[0].value:+.2f} pillar score.",
        )
        if negative:
            opposing = min(negative, key=lambda item: item[1])
            challenges = (
                "Opposing contribution: "
                f"{_pillar_label(opposing[0])} subtracts {abs(opposing[1]):.2f} "
                f"from a {opposing[0].value:+.2f} pillar score.",
            )
        else:
            weakest = min(contributions, key=lambda item: item[1])[0]
            challenges = (
                "Invalidation condition: " + weakest.counter_evidence[0],
            )
        return supports, challenges

    if regime in {"defensive", "risk-off"}:
        strongest = min(negative, key=lambda item: item[1])
        supports = (
            "Defensive contribution: "
            f"{_pillar_label(strongest[0])} subtracts {abs(strongest[1]):.2f} "
            f"from a {strongest[0].value:+.2f} pillar score.",
        )
        if positive:
            improvement = max(positive, key=lambda item: item[1])
            challenges = (
                "Improvement evidence: "
                f"{_pillar_label(improvement[0])} still adds "
                f"{improvement[1]:+.2f} from a "
                f"{improvement[0].value:+.2f} pillar score.",
            )
        else:
            challenges = (
                "Improvement condition: SMH and SOXX would need +3.0% "
                "20-session returns while 20-/50-session breadth reaches 60%.",
            )
        return supports, challenges

    if positive and negative:
        upside = max(positive, key=lambda item: item[1])
        downside = min(negative, key=lambda item: item[1])
        return (
            (
                "Positive side: "
                f"{_pillar_label(upside[0])} adds {upside[1]:+.2f}.",
            ),
            (
                "Negative side: "
                f"{_pillar_label(downside[0])} subtracts "
                f"{abs(downside[1]):.2f}.",
            ),
        )
    if positive:
        upside = max(positive, key=lambda item: item[1])
        weakest = min(contributions, key=lambda item: item[1])[0]
        return (
            (
                "Positive side: "
                f"{_pillar_label(upside[0])} adds {upside[1]:+.2f}.",
            ),
            (
                "Negative side is not yet active; downside trigger: "
                + weakest.counter_evidence[0],
            ),
        )
    if negative:
        downside = min(negative, key=lambda item: item[1])
        return (
            (
                "Negative side: "
                f"{_pillar_label(downside[0])} subtracts "
                f"{abs(downside[1]):.2f}.",
            ),
            (
                "Positive side could improve if SMH and SOXX exceed +3.0% "
                "over 20 sessions with breadth at 60%.",
            ),
        )
    return (
        (
            "No pillar has a nonzero weighted contribution; the mixed label "
            "reflects neutral fixed-threshold votes.",
        ),
        (
            "Directional evidence could emerge if either positive confirmation "
            "or negative deterioration crosses the published thresholds.",
        ),
    )


def _change_triggers(
    regime: str, metrics: MetricBundle
) -> tuple[str, ...]:
    improve = (
        "The view could improve if SMH and SOXX exceed +3.0% over 20 sessions "
        "while 20-/50-session breadth reaches 60%."
    )
    weaken = (
        "The view would weaken if SMH and SOXX reach -3.0% over 20 sessions "
        "or 20-/50-session breadth reaches 40%."
    )
    drawdown = _number(metrics.scalars, "smh_drawdown_63")
    volatility = _number(metrics.scalars, "smh_vol_percentile_252")
    missing_risk_inputs: list[str] = []
    if drawdown is None:
        missing_risk_inputs.append("SMH peak distance")
    if volatility is None:
        missing_risk_inputs.append("volatility percentile")
    active_risk_facts: list[str] = []
    if drawdown is not None and drawdown <= Decimal("-0.10"):
        active_risk_facts.append(
            f"SMH peak distance is {drawdown * Decimal('100'):.1f}%"
        )
    if volatility is not None and volatility >= Decimal("70"):
        active_risk_facts.append(
            f"volatility is at the {volatility:.1f}th percentile"
        )
    if active_risk_facts:
        risk = (
            "Risk stress is already active because "
            + " and ".join(active_risk_facts)
            + "; it would ease once SMH is within -3.0% of its 63-session "
            "peak and volatility is at or below its 35th percentile."
        )
        if missing_risk_inputs:
            missing_text = " and ".join(missing_risk_inputs)
            verb = "is" if len(missing_risk_inputs) == 1 else "are"
            risk += (
                f" The {missing_text} {verb} unavailable, so the remaining "
                "risk-trigger status is indeterminate."
            )
    elif missing_risk_inputs:
        missing_text = " and ".join(missing_risk_inputs)
        verb = "is" if len(missing_risk_inputs) == 1 else "are"
        risk = (
            f"Risk-trigger status is indeterminate because {missing_text} "
            f"{verb} unavailable. Published adverse thresholds are a -10.0% "
            "SMH distance from its 63-session peak and the 70th volatility "
            "percentile."
        )
    else:
        risk = (
            "Risk conditions would deteriorate if SMH reaches a -10.0% distance "
            "from its 63-session peak or volatility reaches its 70th percentile."
        )
    if regime in {"risk-on", "constructive"}:
        return weaken, risk
    if regime in {"defensive", "risk-off"}:
        return improve, risk
    return improve, weaken, risk


def _posture(regime: str) -> str:
    if regime == "risk-on":
        return (
            "Conditional research posture: trend participation is broad enough "
            "to study continuation scenarios, while leverage and invalidation "
            "conditions remain explicit."
        )
    if regime == "constructive":
        return (
            "Conditional research posture: continuation scenarios have support, "
            "but concentration, breadth, and volatility counter-signals still matter."
        )
    if regime == "mixed":
        return (
            "Conditional research posture: evidence is balanced, so both upside "
            "confirmation and downside deterioration scenarios remain active."
        )
    if regime == "defensive":
        return (
            "Conditional research posture: downside-risk scenarios have more "
            "support until participation and leadership improve."
        )
    return (
        "Conditional research posture: stress evidence dominates; improvement "
        "requires trend, breadth, and risk conditions to confirm together."
    )


def build_composite(
    insights: Sequence[ChartInsight],
    metrics: MetricBundle,
    quality: QualityReport,
    *,
    audit: Sequence[CompositeAuditRecord] = (),
) -> CompositeInsight:
    """Build the versioned cross-chart score and bounded executive summary."""

    expected_ids = tuple(f"chart-{number}" for number in range(1, 9))
    if tuple(item.chart_id for item in insights) != expected_ids:
        raise ValueError("composite requires exactly eight ordered chart insights")
    pillars = score_pillars(metrics)
    score = _composite_score(pillars)
    regime = classify_regime(score)
    validated_audit = _validate_audit_records(audit, current=metrics)
    if len(validated_audit) >= 2:
        previous = validated_audit[-2]
        latest = validated_audit[-1]
        delta = score - previous.composite_score
        pillar_deltas = tuple(
            current_pillar.value - previous_pillar.value
            for current_pillar, previous_pillar in zip(
                latest.pillars, previous.pillars, strict=True
            )
        )
        largest_index = max(
            range(len(pillar_deltas)),
            key=lambda index: abs(pillar_deltas[index]),
        )
        largest = latest.pillars[largest_index]
        largest_delta = pillar_deltas[largest_index]
        changed = (
            f"Composite changed {delta:+.2f} from the prior audited session "
            f"and is now {score:+.2f}. Largest pillar move: "
            f"{_pillar_label(largest)} {largest_delta:+.2f}."
        )
    else:
        changed = (
            "Five-session comparison is not yet available; this is the current "
            f"{score:+.2f} snapshot."
        )
    supports, directional_challenges = _directional_summary(pillars, regime)
    challenges = (
        *directional_challenges,
        *_quality_challenges(
            metrics, quality, pillars, validated_audit
        ),
    )
    available = sum(item.available_inputs for item in pillars)
    expected = sum(item.expected_inputs for item in pillars)
    return CompositeInsight(
        score=score,
        regime=regime,
        confidence=_confidence(metrics, quality, pillars, validated_audit),
        what_changed=(changed,),
        supports=supports,
        challenges=challenges,
        change_triggers=_change_triggers(regime, metrics),
        posture=_posture(regime),
        rules_version=RULES_VERSION,
        pillars=pillars,
        available_inputs=available,
        expected_inputs=expected,
        audit=validated_audit,
    )
