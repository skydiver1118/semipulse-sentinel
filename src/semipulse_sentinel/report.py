"""Canonical report serialization, rendering, and fail-closed validation."""

from __future__ import annotations

import hashlib
import json
import math
import re
import stat
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from html import unescape
from html.parser import HTMLParser
from importlib import resources
from os import stat_result
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.parse import urlsplit
from xml.etree import ElementTree

from jinja2 import Environment, StrictUndefined, select_autoescape

from semipulse_sentinel.models import (
    ChartInsight,
    CompositeAuditRecord,
    CompositeInsight,
    PillarScore,
    ReportModel,
)
from semipulse_sentinel.quality import PublicationBlocked

REPORT_SCHEMA_VERSION = "semipulse-report-v1"
RISK_WARNING = (
    "Research only—not individualized investment advice or a recommendation to "
    "buy or sell. Market data may be delayed, incomplete, or revised. Leveraged "
    "ETFs such as SOXL can suffer path-dependent decay and large losses. Verify "
    "prices and signals with a licensed source before trading."
)
_TOP_LEVEL_KEYS = {
    "schema_version",
    "agent",
    "title",
    "timezone",
    "market_as_of",
    "build",
    "schedule",
    "freshness",
    "coverage",
    "provenance",
    "methodology",
    "executive_summary",
    "audit",
    "charts",
    "limitations",
    "risk_warning",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_MACHINE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|file://|\\\\)", re.IGNORECASE)
_CREDENTIAL_URL = re.compile(r"https?://[^\s/]+@", re.IGNORECASE)
_EMBEDDED_MARKER = "__SEMIPULSE_CANONICAL_JSON_PAYLOAD__"
_CSS_URL = re.compile(r"url\s*\(\s*(.*?)\s*\)", re.IGNORECASE | re.DOTALL)
_SAFE_FRAGMENT = re.compile(r"^#[A-Za-z_][A-Za-z0-9_.:-]*$")
_DATA_PNG = re.compile(
    r"^data:image/png;base64,[ \t]*[A-Za-z0-9+/]+={0,2}$"
)
_SUMMARY_KEYS = {
    "score",
    "regime",
    "confidence",
    "what_changed",
    "supports",
    "challenges",
    "what_would_change_the_view",
    "posture",
    "rules_version",
    "pillars",
    "available_inputs",
    "expected_inputs",
}
_AUDIT_KEYS = {
    "as_of",
    "metrics_version",
    "rules_version",
    "pillars",
    "composite_score",
    "regime",
    "available_inputs",
    "expected_inputs",
}
_PILLAR_KEYS = {
    "name",
    "value",
    "weight",
    "evidence",
    "counter_evidence",
    "available_inputs",
    "expected_inputs",
}
_EXPECTED_PILLARS = [
    ("absolute_trend", "0.25", 6),
    ("relative_leadership", "0.20", 8),
    ("breadth_participation", "0.25", 8),
    ("momentum_distribution", "0.15", 4),
    ("volatility_drawdown_risk", "0.15", 4),
]
_EXPECTED_CHART_IMAGES = (
    "charts/chart-01-complex-performance.svg",
    "charts/chart-02-relative-strength.svg",
    "charts/chart-03-breadth.svg",
    "charts/chart-04-participation.svg",
    "charts/chart-05-momentum.svg",
    "charts/chart-06-trend-heatmap.svg",
    "charts/chart-07-risk-regime.svg",
    "charts/chart-08-risk-reward.svg",
)
_EXPECTED_SITE_DIRECTORIES = frozenset({"charts", "static"})
_EXPECTED_SITE_FILES = frozenset(
    {"index.html", "report.json", "static/report.css", *_EXPECTED_CHART_IMAGES}
)


@dataclass(frozen=True, slots=True)
class SiteValidation:
    """Successful read-only validation result."""

    valid: bool
    chart_count: int
    files_checked: int
    report_schema_version: str


def safe_chart_uri(value: str) -> str:
    """Validate and return a canonical local ``charts/...`` URI."""

    parsed = urlsplit(value)
    path = PurePosixPath(value)
    if (
        not value
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or "\\" in value
        or "%" in value
        or ":" in value
        or value.strip() != value
        or path.is_absolute()
        or not value.startswith("charts/")
        or path.as_posix() != value
        or path.suffix.casefold() != ".svg"
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("chart URI must be a safe charts/... POSIX path")
    return value


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("report timestamps must be timezone-aware")
    utc = value.astimezone(UTC)
    return utc.isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_json(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        return str(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        return {key: _normalize_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normalize_json(item) for item in value]
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json(value: object) -> str:
    """Return sorted compact strict UTF-8-compatible JSON plus one newline."""

    normalized = _normalize_json(value)
    return (
        json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def _pillar_dict(pillar: PillarScore) -> dict[str, object]:
    return {
        "name": pillar.name,
        "value": pillar.value,
        "weight": pillar.weight,
        "evidence": pillar.evidence,
        "counter_evidence": pillar.counter_evidence,
        "available_inputs": pillar.available_inputs,
        "expected_inputs": pillar.expected_inputs,
    }


def _audit_dict(record: CompositeAuditRecord) -> dict[str, object]:
    return {
        "as_of": record.as_of,
        "metrics_version": record.metrics_version,
        "rules_version": record.rules_version,
        "pillars": tuple(_pillar_dict(item) for item in record.pillars),
        "composite_score": record.composite_score,
        "regime": record.regime,
        "available_inputs": record.available_inputs,
        "expected_inputs": record.expected_inputs,
    }


def _summary_dict(summary: CompositeInsight) -> dict[str, object]:
    return {
        "score": summary.score,
        "regime": summary.regime,
        "confidence": summary.confidence,
        "what_changed": summary.what_changed,
        "supports": summary.supports,
        "challenges": summary.challenges,
        "what_would_change_the_view": summary.change_triggers,
        "posture": summary.posture,
        "rules_version": summary.rules_version,
        "pillars": tuple(_pillar_dict(item) for item in summary.pillars),
        "available_inputs": summary.available_inputs,
        "expected_inputs": summary.expected_inputs,
    }


def _insight_dict(insight: ChartInsight) -> dict[str, object]:
    return {
        "headline": insight.headline,
        "signal": insight.signal,
        "evidence": insight.evidence,
        "interpretation": insight.interpretation,
        "trading_relevance": insight.trading_relevance,
        "counter_signal": insight.counter_signal,
        "notes": insight.notes,
    }


def report_to_dict(model: ReportModel) -> dict[str, object]:
    """Explicitly map the immutable model to the public schema."""

    return {
        "schema_version": model.schema_version,
        "agent": {"name": model.agent_name, "slug": model.agent_slug},
        "title": model.title,
        "timezone": model.timezone,
        "market_as_of": model.market_as_of,
        "build": {
            "version": model.build.version,
            "started_at": model.build.started_at,
            "completed_at": model.build.completed_at,
        },
        "schedule": {
            "cron": model.schedule.cron,
            "timezone": model.schedule.timezone,
            "description": model.schedule.description,
        },
        "freshness": {
            "state": model.freshness.state,
            "expected_market_session": model.freshness.expected_market_session,
            "latest_market_session": model.freshness.latest_market_session,
            "fetched_at": model.freshness.fetched_at,
            "evaluated_at": model.freshness.evaluated_at,
            "calendar_age_days": model.freshness.calendar_age_days,
            "expected_session_lag": model.freshness.expected_session_lag,
        },
        "coverage": {
            "covered_count": model.coverage.covered_count,
            "watchlist_count": model.coverage.watchlist_count,
            "coverage_ratio": model.coverage.coverage_ratio,
            "covered_symbols": model.coverage.covered_symbols,
            "missing_required": model.coverage.missing_required,
            "missing_optional": model.coverage.missing_optional,
            "warnings": model.coverage.warnings,
            "exclusions": tuple(
                {"symbol": item.symbol, "code": item.code, "reason": item.reason}
                for item in model.exclusions
            ),
        },
        "provenance": {
            "provider": model.provenance.provider,
            "provider_version": model.provenance.provider_version,
            "watchlist_sha256": model.provenance.watchlist_sha256,
            "upload_identity_verified": model.provenance.upload_identity_verified,
            "source_statuses": tuple(
                {"symbol": item.symbol, "source_status": item.source_status}
                for item in model.provenance.source_statuses
            ),
            "provider_issues": tuple(
                {"symbol": item.symbol, "code": item.code}
                for item in model.provenance.provider_issues
            ),
            "statement": model.provenance.statement,
        },
        "methodology": {
            "metrics_version": model.methodology.metrics_version,
            "rules_version": model.methodology.rules_version,
            "report_schema_version": model.methodology.report_schema_version,
            "chart_count": model.methodology.chart_count,
            "adjusted_close_only": model.methodology.adjusted_close_only,
            "pillars": tuple(
                {
                    "name": item.name,
                    "weight": item.weight,
                    "expected_inputs": item.expected_inputs,
                }
                for item in model.methodology.pillars
            ),
        },
        "executive_summary": _summary_dict(model.executive_summary),
        "audit": tuple(_audit_dict(item) for item in model.audit),
        "charts": tuple(
            {
                "chart_id": chart.chart_id,
                "title": chart.title,
                "image": safe_chart_uri(chart.image),
                "sha256": chart.sha256,
                "byte_length": chart.byte_length,
                "alt_text": chart.alt_text,
                "has_non_color_encoding": chart.has_non_color_encoding,
                **_insight_dict(chart.insight),
            }
            for chart in model.charts
        ),
        "limitations": model.limitations,
        "risk_warning": model.risk_warning,
    }


def serialize_report(model: ReportModel) -> str:
    """Serialize a report through the only supported public mapping."""

    return canonical_json(report_to_dict(model))


def _embedded_json(serialized: str) -> str:
    return (
        serialized.rstrip("\n")
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _resource_text(folder: str, name: str) -> str:
    root = resources.files("semipulse_sentinel")
    return root.joinpath(folder, name).read_text(encoding="utf-8")


def _render_html(public: dict[str, object], serialized: str) -> str:
    environment = Environment(
        autoescape=select_autoescape(enabled_extensions=("html", "xml")),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = environment.from_string(_resource_text("templates", "report.html.j2"))
    html = template.render(report=public, embedded_marker=_EMBEDDED_MARKER)
    if html.count(_EMBEDDED_MARKER) != 1:
        raise RuntimeError("report template embedded-data marker drifted")
    return html.replace(_EMBEDDED_MARKER, _embedded_json(serialized))


def render_report(model: ReportModel, output_dir: Path) -> None:
    """Write JSON, HTML, and the one packaged stylesheet into staging."""

    output_dir.mkdir(parents=True, exist_ok=True)
    static_dir = output_dir / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    serialized = serialize_report(model)
    (output_dir / "report.json").write_text(serialized, encoding="utf-8", newline="\n")
    (static_dir / "report.css").write_text(
        _resource_text("static", "report.css"), encoding="utf-8", newline="\n"
    )

    public = _normalize_json(report_to_dict(model))
    if not isinstance(public, dict):
        raise RuntimeError("report mapping did not normalize to an object")
    html = _render_html(public, serialized)
    (output_dir / "index.html").write_text(html, encoding="utf-8", newline="\n")


class _ReportHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.order: list[tuple[str, str | None, tuple[str, ...]]] = []
        self.ids: list[str] = []
        self.article_ids: list[str] = []
        self.nav_links: list[str] = []
        self.anchor_links: list[str] = []
        self.local_refs: list[str] = []
        self.images: list[tuple[str, str]] = []
        self.interpretation_count = 0
        self.h1_count = 0
        self.scripts: list[dict[str, str]] = []
        self.unsafe_markup = False
        self.html_lang = ""
        self.has_viewport = False
        self.has_skip_link = False
        self._in_script = False
        self._script_data: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag in {"base", "embed", "iframe", "object"}:
            self.unsafe_markup = True
        if any(
            key.casefold().startswith("on")
            or "javascript:" in value.casefold()
            or (key.casefold() == "http-equiv" and value.casefold() == "refresh")
            for key, value in values.items()
        ):
            self.unsafe_markup = True
        classes = tuple(values.get("class", "").split())
        element_id = values.get("id") or None
        self.order.append((tag, element_id, classes))
        if element_id:
            self.ids.append(element_id)
        if tag == "h1":
            self.h1_count += 1
        if tag == "html":
            self.html_lang = values.get("lang", "")
        if tag == "meta" and values.get("name", "").casefold() == "viewport":
            self.has_viewport = bool(values.get("content"))
        if tag == "article" and "chart-card" in classes and element_id:
            self.article_ids.append(element_id)
        if "chart-interpretation" in classes:
            self.interpretation_count += 1
        if tag == "a" and values.get("href", "").startswith("#chart-"):
            self.nav_links.append(values["href"])
        if tag == "a" and values.get("href", "").startswith("#"):
            self.anchor_links.append(values["href"])
            if "skip-link" in classes:
                self.has_skip_link = True
        for attribute in ("href", "src"):
            value = values.get(attribute)
            if value and not value.startswith("#"):
                self.local_refs.append(value)
        if tag == "img":
            self.images.append((values.get("src", ""), values.get("alt", "")))
        if tag == "script":
            self.scripts.append(values)
            self._in_script = True
            self._script_data = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._script_data.append(data)

    @property
    def embedded_data(self) -> str:
        return "".join(self._script_data)


def _blocked(message: str) -> PublicationBlocked:
    return PublicationBlocked(f"site_validation_failed:{message}")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise _blocked(message)


def _require_keys(value: object, keys: set[str], name: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise _blocked(f"{name} schema")
    return value


def _read_text(path: Path, name: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise _blocked(f"{name} unreadable") from error


def _read_bytes(path: Path, name: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise _blocked(f"{name} unreadable") from error


def _string_list(value: object, name: str, *, nonempty: bool = False) -> list[str]:
    _require(
        isinstance(value, list)
        and (bool(value) or not nonempty)
        and all(isinstance(item, str) and bool(item) for item in value),
        name,
    )
    return cast(list[str], value)


def _nonempty_string(value: object, name: str) -> str:
    _require(isinstance(value, str) and bool(value), name)
    return cast(str, value)


def _date_string(value: object, name: str) -> str:
    text = _nonempty_string(value, name)
    _require(_DATE.fullmatch(text) is not None, name)
    try:
        date.fromisoformat(text)
    except ValueError as error:
        raise _blocked(name) from error
    return text


def _utc_timestamp(value: object, name: str) -> str:
    text = _nonempty_string(value, name)
    _require(_UTC_TIMESTAMP.fullmatch(text) is not None, name)
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise _blocked(name) from error
    return text


def _integer(value: object, name: str) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool), name)
    return cast(int, value)


def _finite_decimal(value: object, name: str) -> Decimal:
    _require(isinstance(value, str), name)
    try:
        number = Decimal(cast(str, value))
    except ArithmeticError as error:
        raise _blocked(name) from error
    _require(number.is_finite(), name)
    return number


def _validate_pillars(value: object, name: str) -> list[dict[str, object]]:
    _require(
        isinstance(value, list) and len(value) == len(_EXPECTED_PILLARS),
        f"{name} schema",
    )
    pillars: list[dict[str, object]] = []
    for raw, expected in zip(cast(list[object], value), _EXPECTED_PILLARS, strict=True):
        pillar = _require_keys(raw, _PILLAR_KEYS, name)
        expected_name, expected_weight, expected_inputs = expected
        _require(
            pillar["name"] == expected_name
            and pillar["weight"] == expected_weight
            and pillar["expected_inputs"] == expected_inputs,
            f"{name} contract",
        )
        pillar_value = _finite_decimal(pillar["value"], f"{name} value")
        _require(
            Decimal("-2") <= pillar_value <= Decimal("2"),
            f"{name} value domain",
        )
        _string_list(pillar["evidence"], f"{name} evidence")
        _string_list(pillar["counter_evidence"], f"{name} counter evidence")
        available = _integer(pillar["available_inputs"], f"{name} inputs")
        _require(0 <= available <= expected_inputs, f"{name} inputs")
        pillars.append(pillar)
    return pillars


def _composite_score(pillars: list[dict[str, object]]) -> Decimal:
    score = sum(
        (
            Decimal(cast(str, item["value"]))
            * Decimal(cast(str, item["weight"]))
            for item in pillars
        ),
        Decimal("0"),
    )
    return score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _regime(score: Decimal) -> str:
    if score >= Decimal("1.20"):
        return "risk-on"
    if score >= Decimal("0.45"):
        return "constructive"
    if score > Decimal("-0.45"):
        return "mixed"
    if score > Decimal("-1.20"):
        return "defensive"
    return "risk-off"


def _validate_summary(value: object) -> dict[str, object]:
    summary = _require_keys(value, _SUMMARY_KEYS, "executive summary")
    score = _finite_decimal(summary["score"], "summary score")
    regime = summary["regime"]
    _require(
        isinstance(regime, str)
        and regime in {
            "risk-on",
            "constructive",
            "mixed",
            "defensive",
            "risk-off",
        },
        "summary regime",
    )
    _require(
        isinstance(summary["confidence"], str)
        and summary["confidence"] in {"low", "medium", "high"},
        "confidence",
    )
    for key in (
        "what_changed",
        "supports",
        "challenges",
        "what_would_change_the_view",
    ):
        _string_list(summary[key], f"summary {key}", nonempty=True)
    _nonempty_string(summary["posture"], "posture")
    _require(summary["rules_version"] == "semipulse-rules-v1", "summary rules")
    pillars = _validate_pillars(summary["pillars"], "summary pillars")
    _require(score == _composite_score(pillars), "summary score calculation")
    _require(summary["regime"] == _regime(score), "summary regime calculation")
    available = _integer(summary["available_inputs"], "summary inputs")
    expected = _integer(summary["expected_inputs"], "summary inputs")
    _require(
        available == sum(cast(int, item["available_inputs"]) for item in pillars)
        and expected == sum(cast(int, item["expected_inputs"]) for item in pillars),
        "summary input totals",
    )
    return summary


def _validate_audit(value: object) -> list[dict[str, object]]:
    _require(
        isinstance(value, list) and len(value) == 5,
        "audit must contain the latest five sessions",
    )
    records: list[dict[str, object]] = []
    for raw in cast(list[object], value):
        record = _require_keys(raw, _AUDIT_KEYS, "audit record")
        _date_string(record["as_of"], "audit date")
        _nonempty_string(record["metrics_version"], "audit metrics version")
        _require(record["rules_version"] == "semipulse-rules-v1", "audit rules")
        score = _finite_decimal(record["composite_score"], "audit score")
        regime = record["regime"]
        _require(
            isinstance(regime, str)
            and regime in {
                "risk-on",
                "constructive",
                "mixed",
                "defensive",
                "risk-off",
            },
            "audit regime",
        )
        pillars = _validate_pillars(record["pillars"], "audit pillars")
        _require(score == _composite_score(pillars), "audit score calculation")
        _require(record["regime"] == _regime(score), "audit regime calculation")
        available = _integer(record["available_inputs"], "audit inputs")
        expected = _integer(record["expected_inputs"], "audit inputs")
        _require(
            available
            == sum(cast(int, item["available_inputs"]) for item in pillars)
            and expected
            == sum(cast(int, item["expected_inputs"]) for item in pillars),
            "audit input totals",
        )
        records.append(record)
    return records


def _is_link_or_reparse(details: stat_result) -> bool:
    attributes = getattr(details, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(details.st_mode) or bool(
        reparse_flag and attributes & reparse_flag
    )


def _site_tree(root: Path) -> tuple[Path, set[str], set[str]]:
    """Inspect a site tree without following links or accepting special entries."""

    try:
        root_details = root.lstat()
    except (OSError, ValueError) as error:
        raise _blocked("site tree unreadable") from error
    _require(
        not _is_link_or_reparse(root_details),
        "site root cannot be a symlink or reparse point",
    )
    _require(stat.S_ISDIR(root_details.st_mode), "site tree root is not a directory")
    try:
        resolved_root = root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise _blocked("site root cannot be resolved") from error
    _require(
        resolved_root != Path(resolved_root.anchor),
        "site cannot be a filesystem root",
    )

    directories: set[str] = set()
    files: set[str] = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except (OSError, ValueError) as error:
            raise _blocked("site tree unreadable") from error
        child_directories: list[Path] = []
        for item in children:
            relative = item.relative_to(root).as_posix()
            try:
                details = item.lstat()
            except (OSError, ValueError) as error:
                raise _blocked("site entry metadata unreadable") from error
            _require(
                not _is_link_or_reparse(details),
                "site tree contains a symlink or reparse point",
            )
            is_directory = stat.S_ISDIR(details.st_mode)
            is_file = stat.S_ISREG(details.st_mode)
            _require(is_directory or is_file, "site tree contains a special entry")
            try:
                resolved_item = item.resolve(strict=True)
            except (OSError, RuntimeError, ValueError) as error:
                raise _blocked("site entry cannot be resolved") from error
            _require(
                resolved_item.is_relative_to(resolved_root),
                "site entry escape",
            )
            if is_directory:
                directories.add(relative)
                child_directories.append(item)
            else:
                files.add(relative)
        pending.extend(reversed(child_directories))
    return resolved_root, directories, files


def _validate_svg_css(value: str) -> None:
    lowered = value.casefold()
    _require("@import" not in lowered, "external SVG stylesheet import")
    _require("\\" not in value and "/*" not in value, "obfuscated SVG CSS")
    matches = list(_CSS_URL.finditer(value))
    without_urls = _CSS_URL.sub("", value)
    _require(
        re.search(r"url\s*\(", without_urls, re.IGNORECASE) is None,
        "malformed SVG CSS URL",
    )
    for match in matches:
        target = match.group(1).strip()
        if len(target) >= 2 and target[0] in {'"', "'"} and target[-1] == target[0]:
            target = target[1:-1].strip()
        _require(
            _SAFE_FRAGMENT.fullmatch(target) is not None
            or _DATA_PNG.fullmatch(target) is not None,
            "external SVG CSS URL",
        )
    scrubbed = _CSS_URL.sub("", lowered)
    _require(
        not any(
            marker in scrubbed
            for marker in ("http:", "https:", "file:", "javascript:", "data:", "//")
        ),
        "external SVG CSS content",
    )


def _validate_svg(path: Path) -> None:
    data = _read_bytes(path, "chart SVG")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _blocked("invalid SVG encoding") from error
    _require(
        re.search(
            r"(?:<!\s*(?:doctype|entity)\b|<\?\s*xml-stylesheet\b)",
            text,
            re.IGNORECASE,
        )
        is None,
        "SVG declarations are prohibited",
    )
    try:
        root = ElementTree.fromstring(data)
    except (ElementTree.ParseError, LookupError, ValueError) as error:
        raise _blocked("invalid SVG XML") from error
    _require(root.tag.rsplit("}", maxsplit=1)[-1] == "svg", "chart is not SVG")
    _require(root.attrib.get("role") == "img", "SVG lacks image role")
    _require(bool(root.attrib.get("aria-labelledby")), "SVG lacks accessible label")
    children = {child.tag.rsplit("}", maxsplit=1)[-1] for child in root}
    _require({"title", "desc"}.issubset(children), "SVG lacks title or description")
    for element in root.iter():
        tag = element.tag.rsplit("}", maxsplit=1)[-1].casefold()
        _require(
            tag
            not in {
                "animate",
                "animatecolor",
                "animatemotion",
                "animatetransform",
                "discard",
                "foreignobject",
                "set",
                "script",
            },
            "unsafe SVG element",
        )
        if tag == "style":
            _validate_svg_css(element.text or "")
        for attribute, value in element.attrib.items():
            name = attribute.rsplit("}", maxsplit=1)[-1].casefold()
            lowered = value.casefold().strip()
            _require(not name.startswith("on"), "unsafe SVG event attribute")
            _require(name != "base", "SVG base URI is prohibited")
            if name == "href":
                _require(
                    _SAFE_FRAGMENT.fullmatch(value.strip()) is not None
                    or _DATA_PNG.fullmatch(value.strip()) is not None,
                    "external SVG reference",
                )
            if name == "style" or re.search(r"url\s*\(", value, re.IGNORECASE):
                _validate_svg_css(value)
            _require(
                "javascript:" not in lowered
                and "file://" not in lowered
                and "url(http://" not in lowered
                and "url(https://" not in lowered,
                "external SVG content",
            )


def validate_site(path: Path) -> SiteValidation:
    """Read and validate a complete staged or published site without mutation."""

    root = Path(path)
    resolved, directories, files = _site_tree(root)
    _require(
        directories == _EXPECTED_SITE_DIRECTORIES,
        "unexpected, missing, or extra site directories",
    )

    report_path = root / "report.json"
    index_path = root / "index.html"
    css_path = root / "static" / "report.css"
    _require(report_path.is_file(), "report.json missing")
    _require(index_path.is_file(), "index.html missing")
    _require(css_path.is_file(), "stylesheet missing")
    raw_report = _read_text(report_path, "report.json")
    try:
        report = json.loads(raw_report)
    except (ValueError, RecursionError) as error:
        raise _blocked("report JSON invalid") from error
    _require(isinstance(report, dict), "report JSON must be an object")
    _require(set(report) == _TOP_LEVEL_KEYS, "report top-level schema mismatch")
    try:
        canonical_report = canonical_json(report)
    except (ValueError, RecursionError) as error:
        raise _blocked("report JSON cannot be canonicalized") from error
    _require(raw_report == canonical_report, "report JSON is not canonical")
    _require(report.get("schema_version") == REPORT_SCHEMA_VERSION, "schema version")
    _require(report.get("risk_warning") == RISK_WARNING, "risk warning mismatch")
    _nonempty_string(report.get("title"), "report title")
    _require(_MACHINE_PATH.search(raw_report) is None, "machine path in report data")
    _require(
        _CREDENTIAL_URL.search(raw_report) is None,
        "credential URL in report data",
    )

    agent = _require_keys(report.get("agent"), {"name", "slug"}, "agent")
    _require(
        agent == {"name": "SemiPulse Sentinel", "slug": "semipulse-sentinel"},
        "agent identity",
    )
    _require(report.get("timezone") == "America/New_York", "report timezone")
    _date_string(report.get("market_as_of"), "market as-of date")
    build = _require_keys(
        report.get("build"), {"version", "started_at", "completed_at"}, "build"
    )
    _nonempty_string(build["version"], "build version")
    started_at = _utc_timestamp(build["started_at"], "build timestamps")
    completed_at = _utc_timestamp(build["completed_at"], "build timestamps")
    _require(started_at <= completed_at, "build order")

    charts = report.get("charts")
    if not isinstance(charts, list):
        raise _blocked("charts must be an array")
    _require(
        len(charts) == 8 and all(isinstance(item, dict) for item in charts),
        "chart entry schema",
    )
    expected_ids = [f"chart-{number}" for number in range(1, 9)]
    _require(
        [item.get("chart_id") for item in charts if isinstance(item, dict)]
        == expected_ids,
        "chart ids or order",
    )
    summary = _validate_summary(report.get("executive_summary"))
    audit_records = _validate_audit(report.get("audit"))
    audit_dates = [cast(str, item["as_of"]) for item in audit_records]
    _require(
        len(set(audit_dates)) == len(audit_dates)
        and audit_dates == sorted(audit_dates, reverse=True)
        and all(_DATE.fullmatch(item) is not None for item in audit_dates),
        "audit dates or order",
    )
    _require(
        audit_records[0]["as_of"] == report.get("market_as_of"),
        "current audit date",
    )
    _require(
        audit_records[0]["composite_score"] == summary["score"],
        "audit score",
    )
    _require(
        audit_records[0]["regime"] == summary["regime"],
        "audit regime",
    )
    _require(
        audit_records[0]["pillars"] == summary["pillars"],
        "audit pillars",
    )

    provenance = _require_keys(
        report.get("provenance"),
        {
            "provider",
            "provider_version",
            "watchlist_sha256",
            "upload_identity_verified",
            "source_statuses",
            "provider_issues",
            "statement",
        },
        "provenance",
    )
    freshness = _require_keys(
        report.get("freshness"),
        {
            "state",
            "expected_market_session",
            "latest_market_session",
            "fetched_at",
            "evaluated_at",
            "calendar_age_days",
            "expected_session_lag",
        },
        "freshness",
    )
    coverage = _require_keys(
        report.get("coverage"),
        {
            "covered_count",
            "watchlist_count",
            "coverage_ratio",
            "covered_symbols",
            "missing_required",
            "missing_optional",
            "warnings",
            "exclusions",
        },
        "coverage",
    )
    schedule = _require_keys(
        report.get("schedule"),
        {"cron", "timezone", "description"},
        "schedule",
    )
    methodology = _require_keys(
        report.get("methodology"),
        {
            "metrics_version",
            "rules_version",
            "report_schema_version",
            "chart_count",
            "adjusted_close_only",
            "pillars",
        },
        "methodology",
    )
    _require(provenance.get("upload_identity_verified") is False, "upload identity")
    _nonempty_string(provenance.get("provider"), "provider disclosure")
    _nonempty_string(
        provenance.get("provider_version"), "provider version disclosure"
    )
    _nonempty_string(provenance.get("statement"), "provenance statement")
    _require(
        isinstance(provenance.get("watchlist_sha256"), str)
        and _SHA256.fullmatch(cast(str, provenance["watchlist_sha256"])) is not None,
        "watchlist hash",
    )
    _require(bool(provenance.get("source_statuses")), "source statuses")
    _require(
        isinstance(freshness.get("state"), str)
        and freshness.get("state") in {"current", "delayed", "stale"},
        "freshness",
    )
    _date_string(freshness.get("expected_market_session"), "freshness market sessions")
    latest_market_session = _date_string(
        freshness.get("latest_market_session"), "freshness market sessions"
    )
    _require(
        latest_market_session == report.get("market_as_of"),
        "freshness market sessions",
    )
    _require(isinstance(coverage.get("exclusions"), list), "exclusions missing")
    _require(
        schedule.get("cron") == "0 18 * * *"
        and schedule.get("timezone") == "America/New_York",
        "schedule disclosure",
    )
    _nonempty_string(schedule.get("description"), "schedule description")
    _require(
        methodology.get("report_schema_version") == REPORT_SCHEMA_VERSION
        and methodology.get("chart_count") == 8,
        "methodology disclosure",
    )
    _require(methodology.get("adjusted_close_only") is True, "adjusted-close rule")
    _nonempty_string(methodology.get("metrics_version"), "metrics version")
    _require(methodology.get("rules_version") == "semipulse-rules-v1", "rules version")
    _require(
        all(
            record["metrics_version"] == methodology["metrics_version"]
            and record["rules_version"] == methodology["rules_version"]
            for record in audit_records
        ),
        "audit methodology versions",
    )
    methodology_pillars = methodology.get("pillars")
    if not isinstance(methodology_pillars, list):
        raise _blocked("methodology pillars")
    methodology_records = [
        _require_keys(item, {"name", "weight", "expected_inputs"}, "methodology pillar")
        for item in methodology_pillars
    ]
    _require(
        [
            (item["name"], item["weight"], item["expected_inputs"])
            for item in methodology_records
        ]
        == _EXPECTED_PILLARS,
        "methodology pillars",
    )
    covered_count = _integer(coverage.get("covered_count"), "coverage counts")
    watchlist_count = _integer(coverage.get("watchlist_count"), "coverage counts")
    _require(
        0 <= covered_count <= watchlist_count and watchlist_count > 0,
        "coverage counts",
    )
    covered_symbols = _string_list(
        coverage.get("covered_symbols"), "covered symbols"
    )
    _require(
        len(covered_symbols) == covered_count
        and len(set(covered_symbols)) == covered_count,
        "covered symbols",
    )
    _string_list(coverage.get("missing_required"), "missing required")
    _string_list(coverage.get("missing_optional"), "missing optional")
    _string_list(coverage.get("warnings"), "coverage warnings")
    reported_ratio = _finite_decimal(
        coverage.get("coverage_ratio"), "coverage ratio"
    )
    _require(
        reported_ratio == Decimal(covered_count) / Decimal(watchlist_count),
        "coverage ratio",
    )
    exclusions = coverage["exclusions"]
    if not isinstance(exclusions, list):
        raise _blocked("coverage exclusions")
    _require(
        all(
            isinstance(item, dict)
            and set(item) == {"symbol", "code", "reason"}
            and isinstance(item["code"], str)
            and item["code"] in {"absent", "stale", "insufficient_history"}
            and isinstance(item["symbol"], str)
            and bool(item["symbol"])
            and isinstance(item["reason"], str)
            and bool(item["reason"])
            for item in exclusions
        ),
        "coverage exclusions",
    )
    statuses = provenance["source_statuses"]
    if not isinstance(statuses, list) or not all(
        isinstance(item, dict) for item in statuses
    ):
        raise _blocked("source status schema")
    status_records = cast(list[dict[str, object]], statuses)
    _require(
        len(status_records) == watchlist_count
        and all(
            set(item) == {"symbol", "source_status"}
            and isinstance(item["symbol"], str)
            and bool(item["symbol"])
            and isinstance(item["source_status"], str)
            and bool(item["source_status"])
            for item in status_records
        )
        and len({item["symbol"] for item in status_records}) == watchlist_count,
        "source status schema",
    )
    issues = provenance["provider_issues"]
    _require(isinstance(issues, list), "provider issue schema")
    issue_records = [
        _require_keys(item, {"symbol", "code"}, "provider issue")
        for item in cast(list[object], issues)
    ]
    _require(
        all(
            isinstance(item["symbol"], str)
            and bool(item["symbol"])
            and isinstance(item["code"], str)
            and bool(item["code"])
            for item in issue_records
        ),
        "provider issue schema",
    )
    for key in ("fetched_at", "evaluated_at"):
        _utc_timestamp(freshness.get(key), "freshness timestamps")
    ages = [
        _integer(freshness.get(key), "freshness ages")
        for key in ("calendar_age_days", "expected_session_lag")
    ]
    _require(all(value >= 0 for value in ages), "freshness ages")
    limitations = report.get("limitations")
    _require(
        isinstance(limitations, list)
        and len(limitations) >= 5
        and all(isinstance(item, str) and item for item in limitations),
        "limitations",
    )

    images: list[str] = []
    chart_keys = {
        "chart_id",
        "title",
        "image",
        "sha256",
        "byte_length",
        "alt_text",
        "has_non_color_encoding",
        "headline",
        "signal",
        "evidence",
        "interpretation",
        "trading_relevance",
        "counter_signal",
        "notes",
    }
    for chart, expected_image in zip(
        charts, _EXPECTED_CHART_IMAGES, strict=True
    ):
        _require(
            isinstance(chart, dict) and set(chart) == chart_keys,
            "chart entry schema",
        )
        _nonempty_string(chart.get("chart_id"), "chart id")
        _nonempty_string(chart.get("title"), "chart title")
        try:
            image = safe_chart_uri(
                _nonempty_string(chart.get("image"), "chart image")
            )
        except ValueError as error:
            raise _blocked("unsafe chart URI") from error
        _require(image == expected_image, "chart stable filename")
        _nonempty_string(chart.get("alt_text"), "chart alt text missing")
        _nonempty_string(chart.get("headline"), "chart headline missing")
        _require(
            isinstance(chart.get("signal"), str)
            and chart.get("signal") in {"positive", "negative", "mixed", "limited"},
            "chart signal",
        )
        _string_list(chart.get("evidence"), "chart evidence", nonempty=True)
        _nonempty_string(chart.get("interpretation"), "chart interpretation missing")
        _nonempty_string(chart.get("trading_relevance"), "trading relevance missing")
        _nonempty_string(chart.get("counter_signal"), "counter-signal missing")
        _string_list(chart.get("notes"), "chart notes", nonempty=True)
        _require(chart.get("has_non_color_encoding") is True, "non-color encoding")
        asset = root / Path(*PurePosixPath(image).parts)
        try:
            _require(
                asset.resolve(strict=True).is_relative_to(resolved), "asset escape"
            )
        except (OSError, RuntimeError) as error:
            raise _blocked("chart asset missing") from error
        _require(asset.is_file() and not asset.is_symlink(), "chart asset missing")
        data = _read_bytes(asset, "chart asset")
        digest = hashlib.sha256(data).hexdigest()
        _require(
            isinstance(chart.get("sha256"), str)
            and _SHA256.fullmatch(cast(str, chart["sha256"])) is not None,
            "chart hash shape",
        )
        _require(digest == chart.get("sha256"), "chart hash mismatch")
        byte_length = _integer(chart.get("byte_length"), "chart byte length")
        _require(byte_length > 0, "chart byte length")
        _require(len(data) == byte_length, "chart byte length mismatch")
        _validate_svg(asset)
        images.append(image)
    _require(len(set(images)) == 8, "chart images must be unique")
    _require(
        files == _EXPECTED_SITE_FILES,
        "unexpected, missing, or extra site files",
    )

    css = _read_text(css_path, "stylesheet")
    try:
        expected_css = _resource_text("static", "report.css")
    except (OSError, UnicodeError) as error:
        raise _blocked("packaged stylesheet unreadable") from error
    _require(css == expected_css, "stylesheet differs from packaged asset")
    lowered_css = css.lower()
    _require(
        "@import" not in lowered_css
        and "url(" not in lowered_css
        and "http://" not in lowered_css
        and "https://" not in lowered_css,
        "remote stylesheet content",
    )
    _require(
        "prefers-color-scheme" in lowered_css
        and "prefers-reduced-motion" in lowered_css
        and "@media print" in lowered_css,
        "responsive preference styles",
    )
    _require(_MACHINE_PATH.search(css) is None, "machine path in stylesheet")

    html = _read_text(index_path, "index.html")
    try:
        expected_html = _render_html(cast(dict[str, object], report), raw_report)
    except Exception as error:
        raise _blocked("report HTML cannot be reproduced") from error
    _require(html == expected_html, "HTML differs from canonical rendering")
    lowered = html.lower()
    _require(_MACHINE_PATH.search(html) is None, "machine path disclosure")
    _require(_CREDENTIAL_URL.search(html) is None, "credential-bearing URL")
    _require("<form" not in lowered, "forms are prohibited")
    _require("tracker" not in lowered and "analytics" not in lowered, "tracker marker")
    parser = _ReportHTMLParser()
    try:
        parser.feed(html)
    except Exception as error:
        raise _blocked("HTML parsing failed") from error
    _require(parser.h1_count == 1, "report must contain one h1")
    _require(not parser.unsafe_markup, "unsafe HTML markup")
    _require(parser.html_lang == "en", "document language")
    _require(parser.has_viewport, "responsive viewport")
    _require(parser.has_skip_link, "skip link")
    first_section = next(
        (element_id for tag, element_id, _classes in parser.order if tag == "section"),
        None,
    )
    _require(first_section == "executive-summary", "executive summary reading order")
    _require(parser.article_ids == expected_ids, "chart card ids or order")
    _require(parser.interpretation_count == 8, "chart interpretation count")
    _require(parser.nav_links == [f"#{item}" for item in expected_ids], "chart nav")
    _require(
        all(
            reference.removeprefix("#") in parser.ids
            for reference in parser.anchor_links
        ),
        "broken internal anchor",
    )
    _require("executive-summary" in parser.ids, "executive summary section")
    _require(
        parser.ids.index("executive-summary") < parser.ids.index("chart-1"),
        "summary must precede charts",
    )
    _require(
        parser.images == [
            (chart["image"], chart["alt_text"]) for chart in charts
        ],
        "chart image or alt pairing",
    )
    _require(
        parser.local_refs == ["static/report.css", *images],
        "linked asset order or scope",
    )
    for reference in parser.local_refs:
        parsed = urlsplit(reference)
        _require(
            not parsed.scheme
            and not parsed.netloc
            and "\\" not in reference
            and not PurePosixPath(parsed.path).is_absolute()
            and ".." not in PurePosixPath(parsed.path).parts,
            "remote or unsafe linked asset",
        )
        target = root / Path(*PurePosixPath(parsed.path).parts)
        _require(target.is_file(), "broken local link")
    _require(
        len(parser.scripts) == 1
        and parser.scripts[0].get("id") == "report-data"
        and parser.scripts[0].get("type") == "application/json"
        and "src" not in parser.scripts[0],
        "only embedded non-executable report JSON is allowed",
    )
    try:
        embedded = json.loads(parser.embedded_data)
    except (ValueError, RecursionError) as error:
        raise _blocked("embedded JSON invalid") from error
    _require(embedded == report, "embedded JSON differs from report.json")
    _require(RISK_WARNING in html, "risk warning not rendered")
    _require(str(provenance["provider"]) in html, "provider not rendered")
    _require(
        str(provenance["provider_version"]) in html,
        "provider version not rendered",
    )
    _require(str(schedule["description"]) in html, "schedule not rendered")
    _require(str(freshness["state"]) in html, "freshness state not rendered")
    decoded_html = unescape(html)
    for item in status_records:
        _require(
            str(item["source_status"]) in decoded_html,
            "source status not rendered",
        )
    return SiteValidation(
        valid=True,
        chart_count=8,
        files_checked=len(files),
        report_schema_version=REPORT_SCHEMA_VERSION,
    )
