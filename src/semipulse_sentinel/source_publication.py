"""Fail-closed publication decisions for source-copy report manifests."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal, cast

from .source_report import SOURCE_REPORT_SCHEMA

LEGACY_REPORT_SCHEMA = "semipulse-report-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class SourcePublicationSnapshot:
    schema_version: str
    market_as_of: date
    source_post_id: int | None
    source_published_at: datetime | None
    source_title: str | None
    image_sha256: tuple[str, ...]

    @property
    def is_source_report(self) -> bool:
        return self.schema_version == SOURCE_REPORT_SCHEMA


@dataclass(frozen=True, slots=True)
class SourcePublicationDecision:
    kind: Literal["new", "revised", "migration", "unchanged"]
    candidate: SourcePublicationSnapshot
    published: SourcePublicationSnapshot

    @property
    def has_new_data(self) -> bool:
        return self.kind != "unchanged"


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise ValueError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _single_line(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\r" in value
        or "\n" in value
    ):
        raise ValueError(f"{label} must be a nonempty single-line string")
    return value


def _date(value: object, label: str) -> date:
    text = _single_line(value, label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO date") from error
    if parsed.isoformat() != text:
        raise ValueError(f"{label} must be canonical")
    return parsed


def _datetime(value: object, label: str) -> datetime:
    text = _single_line(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO timestamp") from error
    if parsed.tzinfo is not None or parsed.isoformat(timespec="seconds") != text:
        raise ValueError(f"{label} must be a canonical naive timestamp")
    return parsed


def read_source_publication_snapshot(
    path: Path, *, require_source: bool
) -> SourcePublicationSnapshot:
    """Read the source facts needed by automation from canonical report JSON."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("report JSON is unreadable") from error
    report = _mapping(payload, "report")
    schema = _single_line(report.get("schema_version"), "schema_version")
    market_as_of = _date(report.get("market_as_of"), "market_as_of")
    if schema == LEGACY_REPORT_SCHEMA and not require_source:
        return SourcePublicationSnapshot(
            schema_version=schema,
            market_as_of=market_as_of,
            source_post_id=None,
            source_published_at=None,
            source_title=None,
            image_sha256=(),
        )
    if schema != SOURCE_REPORT_SCHEMA:
        raise ValueError("candidate must use the source schema")
    source = _mapping(report.get("source"), "source")
    post_id = source.get("post_id")
    if isinstance(post_id, bool) or not isinstance(post_id, int) or post_id < 1:
        raise ValueError("source post id is invalid")
    published_at = _datetime(source.get("published_at"), "source published_at")
    if published_at.date() != market_as_of:
        raise ValueError("source published_at disagrees with market_as_of")
    title = _single_line(source.get("title"), "source title")
    images = report.get("images")
    if not isinstance(images, list) or not 1 <= len(images) <= 12:
        raise ValueError("source image manifest is invalid")
    hashes: list[str] = []
    for item in images:
        record = _mapping(item, "source image")
        digest = _single_line(record.get("sha256"), "source image sha256")
        if _SHA256.fullmatch(digest) is None:
            raise ValueError("source image sha256 is invalid")
        hashes.append(digest)
    return SourcePublicationSnapshot(
        schema_version=schema,
        market_as_of=market_as_of,
        source_post_id=post_id,
        source_published_at=published_at,
        source_title=title,
        image_sha256=tuple(hashes),
    )


def decide_source_publication(
    candidate: SourcePublicationSnapshot,
    published: SourcePublicationSnapshot,
) -> SourcePublicationDecision:
    """Deploy only a source migration, newer post, or revised image manifest."""

    if not candidate.is_source_report:
        raise ValueError("candidate must use the source schema")
    if candidate.market_as_of < published.market_as_of:
        raise ValueError("candidate market date regressed")
    if not published.is_source_report:
        return SourcePublicationDecision("migration", candidate, published)
    assert candidate.source_published_at is not None
    assert candidate.source_post_id is not None
    assert published.source_published_at is not None
    assert published.source_post_id is not None
    candidate_key = (
        candidate.source_published_at,
        candidate.source_post_id,
    )
    published_key = (
        published.source_published_at,
        published.source_post_id,
    )
    if candidate_key < published_key:
        raise ValueError("candidate source post regressed")
    if candidate_key > published_key:
        return SourcePublicationDecision("new", candidate, published)
    kind: Literal["revised", "unchanged"] = (
        "unchanged"
        if candidate.image_sha256 == published.image_sha256
        else "revised"
    )
    return SourcePublicationDecision(kind, candidate, published)


def append_source_github_outputs(
    path: Path, decision: SourcePublicationDecision
) -> None:
    """Append only fixed, validated single-line source facts."""

    candidate = decision.candidate
    assert candidate.source_post_id is not None
    assert candidate.source_title is not None
    title = _single_line(candidate.source_title, "source title")
    lines = (
        f"decision={decision.kind}",
        f"has_new_data={'true' if decision.has_new_data else 'false'}",
        f"market_as_of={candidate.market_as_of.isoformat()}",
        f"source_post_id={candidate.source_post_id}",
        f"source_title={title}",
        f"image_count={len(candidate.image_sha256)}",
    )
    with Path(path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
