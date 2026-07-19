import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from semipulse_sentinel.publication import (
    append_github_outputs,
    decide_publication,
    read_report_snapshot,
)


def _report(path: Path, market_as_of: str) -> Path:
    payload = {
        "schema_version": "semipulse-report-v1",
        "agent": {"name": "SemiPulse Sentinel", "slug": "semipulse-sentinel"},
        "market_as_of": market_as_of,
        "freshness": {"latest_market_session": market_as_of},
        "coverage": {
            "covered_count": 21,
            "watchlist_count": 23,
            "coverage_ratio": "0.9130434782608695652173913043",
        },
        "executive_summary": {"regime": "defensive", "confidence": "medium"},
        "charts": [{} for _ in range(8)],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_newer_candidate_is_publishable_and_writes_safe_outputs(tmp_path: Path) -> None:
    candidate = read_report_snapshot(_report(tmp_path / "candidate.json", "2026-07-20"))
    published = read_report_snapshot(_report(tmp_path / "published.json", "2026-07-17"))
    decision = decide_publication(candidate, published)
    output = tmp_path / "github-output"

    append_github_outputs(output, decision)

    assert decision.kind == "new"
    assert decision.has_new_data is True
    assert output.read_text(encoding="utf-8").splitlines() == [
        "decision=new",
        "has_new_data=true",
        "market_as_of=2026-07-20",
        "published_market_as_of=2026-07-17",
        "regime=defensive",
        "confidence=medium",
        "coverage=21/23 (91.3%)",
    ]


def test_equal_candidate_is_unchanged(tmp_path: Path) -> None:
    current = read_report_snapshot(_report(tmp_path / "current.json", "2026-07-17"))

    decision = decide_publication(current, current)

    assert decision.kind == "unchanged"
    assert decision.has_new_data is False


def test_regressed_candidate_is_rejected(tmp_path: Path) -> None:
    candidate = read_report_snapshot(_report(tmp_path / "candidate.json", "2026-07-16"))
    published = read_report_snapshot(_report(tmp_path / "published.json", "2026-07-17"))

    with pytest.raises(ValueError, match="regressed"):
        decide_publication(candidate, published)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema_version="wrong"),
        lambda payload: payload["agent"].update(slug="wrong"),
        lambda payload: payload.update(market_as_of="not-a-date"),
        lambda payload: payload["freshness"].update(
            latest_market_session="2026-07-16"
        ),
        lambda payload: payload.update(charts=[]),
        lambda payload: payload["coverage"].update(covered_count=22),
        lambda payload: payload["executive_summary"].update(
            regime="unsafe\nvalue"
        ),
    ],
)
def test_report_snapshot_rejects_invalid_identity_or_outputs(
    tmp_path: Path, mutation: Callable[[dict[str, Any]], None]
) -> None:
    path = _report(tmp_path / "report.json", "2026-07-17")
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutation(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        read_report_snapshot(path)


def test_report_snapshot_rejects_boolean_counts(tmp_path: Path) -> None:
    path = _report(tmp_path / "report.json", "2026-07-17")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["coverage"]["covered_count"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="coverage"):
        read_report_snapshot(path)
