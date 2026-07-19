"""Fail-closed decisions for publishing only advancing market sessions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, cast

from semipulse_sentinel.contracts import (
    AGENT_NAME,
    AGENT_SLUG,
    REPORT_SCHEMA_VERSION,
)

_REGIMES = {"risk-on", "constructive", "mixed", "defensive", "risk-off"}
_CONFIDENCE = {"high", "medium", "low"}


@dataclass(frozen=True, slots=True)
class ReportSnapshot:
    """The safe, single-line report facts needed by automation."""

    market_as_of: date
    regime: str
    confidence: str
    covered_count: int
    watchlist_count: int
    coverage_ratio: Decimal

    @property
    def coverage_label(self) -> str:
        """Return a compact, deterministic coverage label."""

        percent = self.coverage_ratio * Decimal(100)
        return f"{self.covered_count}/{self.watchlist_count} ({percent:.1f}%)"


@dataclass(frozen=True, slots=True)
class PublicationDecision:
    """Whether one validated candidate advances the published market date."""

    kind: Literal["new", "unchanged"]
    candidate: ReportSnapshot
    published: ReportSnapshot

    @property
    def has_new_data(self) -> bool:
        """Return whether deployment and notification may proceed."""

        return self.kind == "new"


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise ValueError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _safe_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\r" in value or "\n" in value:
        raise ValueError(f"{label} must be a nonempty single-line string")
    return value


def _date(value: object, label: str) -> date:
    text = _safe_string(value, label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO date") from error
    if parsed.isoformat() != text:
        raise ValueError(f"{label} must be a canonical ISO date")
    return parsed


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def _decimal(value: object, label: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{label} must be a decimal string") from error
    if not parsed.is_finite():
        raise ValueError(f"{label} must be finite")
    return parsed


def read_report_snapshot(path: Path) -> ReportSnapshot:
    """Read strict automation facts from one canonical report JSON file."""

    report_path = Path(path)
    try:
        raw = report_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"report JSON is unreadable: {report_path}") from error
    report = _mapping(payload, "report")
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise ValueError("report schema version is invalid")
    agent = _mapping(report.get("agent"), "agent")
    if agent.get("name") != AGENT_NAME or agent.get("slug") != AGENT_SLUG:
        raise ValueError("report agent identity is invalid")

    market_as_of = _date(report.get("market_as_of"), "market_as_of")
    freshness = _mapping(report.get("freshness"), "freshness")
    latest = _date(
        freshness.get("latest_market_session"), "latest_market_session"
    )
    if latest != market_as_of:
        raise ValueError("latest market session must match market_as_of")

    charts = report.get("charts")
    if not isinstance(charts, list) or len(charts) != 8:
        raise ValueError("report must contain exactly eight charts")

    coverage = _mapping(report.get("coverage"), "coverage")
    covered_count = _integer(coverage.get("covered_count"), "coverage count")
    watchlist_count = _integer(
        coverage.get("watchlist_count"), "coverage watchlist count"
    )
    if not 0 < covered_count <= watchlist_count:
        raise ValueError("coverage counts are invalid")
    coverage_ratio = _decimal(coverage.get("coverage_ratio"), "coverage ratio")
    expected_ratio = Decimal(covered_count) / Decimal(watchlist_count)
    if coverage_ratio != expected_ratio:
        raise ValueError("coverage ratio does not match coverage counts")

    summary = _mapping(report.get("executive_summary"), "executive summary")
    regime = _safe_string(summary.get("regime"), "regime")
    confidence = _safe_string(summary.get("confidence"), "confidence")
    if regime not in _REGIMES:
        raise ValueError("report regime is invalid")
    if confidence not in _CONFIDENCE:
        raise ValueError("report confidence is invalid")

    return ReportSnapshot(
        market_as_of=market_as_of,
        regime=regime,
        confidence=confidence,
        covered_count=covered_count,
        watchlist_count=watchlist_count,
        coverage_ratio=coverage_ratio,
    )


def decide_publication(
    candidate: ReportSnapshot, published: ReportSnapshot
) -> PublicationDecision:
    """Return a deployment decision or reject a regressed market date."""

    if candidate.market_as_of < published.market_as_of:
        raise ValueError(
            "candidate market_as_of regressed from "
            f"{published.market_as_of.isoformat()} to "
            f"{candidate.market_as_of.isoformat()}"
        )
    kind: Literal["new", "unchanged"] = (
        "new" if candidate.market_as_of > published.market_as_of else "unchanged"
    )
    return PublicationDecision(kind, candidate, published)


def append_github_outputs(path: Path, decision: PublicationDecision) -> None:
    """Append only audited single-line facts to GitHub's output file."""

    lines = (
        f"decision={decision.kind}",
        f"has_new_data={'true' if decision.has_new_data else 'false'}",
        f"market_as_of={decision.candidate.market_as_of.isoformat()}",
        f"published_market_as_of={decision.published.market_as_of.isoformat()}",
        f"regime={decision.candidate.regime}",
        f"confidence={decision.candidate.confidence}",
        f"coverage={decision.candidate.coverage_label}",
    )
    with Path(path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
