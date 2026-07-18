"""Canonical static-report contracts."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from semipulse_sentinel.models import ChartInsight, ReportChart
from semipulse_sentinel.report import canonical_json, safe_chart_uri


@pytest.mark.parametrize(
    "value",
    [
        "/charts/a.svg",
        "../charts/a.svg",
        "charts/../a.svg",
        "charts\\a.svg",
        "https://x/a.svg",
        "C:/a.svg",
        "charts/%2e%2e/a.svg",
        "charts//a.svg",
    ],
)
def test_chart_uri_rejects_every_nonlocal_or_noncanonical_path(value: str) -> None:
    with pytest.raises(ValueError):
        safe_chart_uri(value)


def test_canonical_json_is_sorted_utf8_strict_and_normalizes_scalars() -> None:
    payload = {
        "z": float("nan"),
        "decimal": Decimal("1.2300"),
        "date": date(2025, 7, 2),
        "timestamp": datetime(2025, 7, 2, 14, 30, tzinfo=UTC),
        "a": "<script>&",
    }

    encoded = canonical_json(payload)

    assert encoded.endswith("\n")
    assert encoded.startswith('{"a":')
    assert "NaN" not in encoded
    assert json.loads(encoded) == {
        "a": "<script>&",
        "date": "2025-07-02",
        "decimal": "1.2300",
        "timestamp": "2025-07-02T14:30:00Z",
        "z": None,
    }


def test_report_chart_is_immutable_and_pairs_matching_ids() -> None:
    assert ReportChart.__dataclass_params__.frozen is True
    assert safe_chart_uri("charts/chart-01.svg") == "charts/chart-01.svg"
    insight = ChartInsight(
        chart_id="chart-1",
        headline="Observed headline.",
        signal="mixed",
        evidence=("Observed evidence.",),
        interpretation="Deterministic interpretation.",
        trading_relevance="Conditional relevance.",
        counter_signal="Two-way trigger.",
        notes=("Coverage note.",),
    )
    chart = ReportChart(
        chart_id="chart-1",
        title="1. Test chart",
        image="charts/chart-01.svg",
        sha256="0" * 64,
        byte_length=1,
        alt_text="Accessible observation.",
        has_non_color_encoding=True,
        insight=insight,
    )

    assert chart.insight is insight
    with pytest.raises(ValueError, match="ids must match"):
        ReportChart(
            chart_id="chart-2",
            title=chart.title,
            image=chart.image,
            sha256=chart.sha256,
            byte_length=chart.byte_length,
            alt_text=chart.alt_text,
            has_non_color_encoding=True,
            insight=insight,
        )
