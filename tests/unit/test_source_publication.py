"""Publication decisions for source-copy reports."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest

from semipulse_sentinel.source_publication import (
    SourcePublicationSnapshot,
    append_source_github_outputs,
    decide_source_publication,
    read_source_publication_snapshot,
)


def _source_snapshot() -> SourcePublicationSnapshot:
    return SourcePublicationSnapshot(
        schema_version="semipulse-wenxuecity-source-v1",
        market_as_of=date(2026, 7, 17),
        source_post_id=97669,
        source_published_at=datetime(2026, 7, 17, 21, 0, 42),
        source_title="狼来了的故事",
        image_sha256=("a" * 64, "b" * 64),
    )


def test_exact_source_manifest_is_unchanged() -> None:
    snapshot = _source_snapshot()
    decision = decide_source_publication(snapshot, snapshot)
    assert decision.kind == "unchanged"
    assert decision.has_new_data is False


def test_same_post_changed_ordered_hashes_is_revised() -> None:
    published = _source_snapshot()
    candidate = replace(published, image_sha256=("b" * 64, "a" * 64))
    decision = decide_source_publication(candidate, published)
    assert decision.kind == "revised"
    assert decision.has_new_data is True


def test_newer_post_is_new() -> None:
    published = _source_snapshot()
    candidate = replace(
        published,
        market_as_of=date(2026, 7, 20),
        source_post_id=98000,
        source_published_at=datetime(2026, 7, 20, 18, 30),
        source_title="new SMH charts",
    )
    decision = decide_source_publication(candidate, published)
    assert decision.kind == "new"
    assert decision.has_new_data is True


def test_legacy_same_date_report_allows_one_time_source_migration() -> None:
    candidate = _source_snapshot()
    published = SourcePublicationSnapshot(
        schema_version="semipulse-report-v1",
        market_as_of=date(2026, 7, 17),
        source_post_id=None,
        source_published_at=None,
        source_title=None,
        image_sha256=(),
    )
    decision = decide_source_publication(candidate, published)
    assert decision.kind == "migration"
    assert decision.has_new_data is True


@pytest.mark.parametrize(
    "candidate",
    [
        replace(_source_snapshot(), market_as_of=date(2026, 7, 16)),
        replace(
            _source_snapshot(),
            source_post_id=97000,
            source_published_at=datetime(2026, 7, 16, 21, 0),
        ),
    ],
)
def test_regressed_candidate_is_rejected(
    candidate: SourcePublicationSnapshot,
) -> None:
    with pytest.raises(ValueError, match="regressed"):
        decide_source_publication(candidate, _source_snapshot())


def test_reader_accepts_source_and_legacy_schema(tmp_path: Path) -> None:
    source_path = tmp_path / "source.json"
    source_path.write_text(
        json.dumps(
            {
                "schema_version": "semipulse-wenxuecity-source-v1",
                "market_as_of": "2026-07-17",
                "source": {
                    "post_id": 97669,
                    "published_at": "2026-07-17T21:00:42",
                    "title": "狼来了的故事",
                },
                "images": [
                    {"sha256": "a" * 64},
                    {"sha256": "b" * 64},
                ],
            }
        ),
        encoding="utf-8",
    )
    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text(
        json.dumps(
            {
                "schema_version": "semipulse-report-v1",
                "market_as_of": "2026-07-17",
            }
        ),
        encoding="utf-8",
    )

    assert read_source_publication_snapshot(
        source_path, require_source=True
    ) == _source_snapshot()
    assert read_source_publication_snapshot(
        legacy_path, require_source=False
    ).source_post_id is None
    with pytest.raises(ValueError, match="source schema"):
        read_source_publication_snapshot(legacy_path, require_source=True)


def test_github_outputs_are_fixed_and_single_line(tmp_path: Path) -> None:
    published = SourcePublicationSnapshot(
        schema_version="semipulse-report-v1",
        market_as_of=date(2026, 7, 17),
        source_post_id=None,
        source_published_at=None,
        source_title=None,
        image_sha256=(),
    )
    decision = decide_source_publication(_source_snapshot(), published)
    output = tmp_path / "github-output"

    append_source_github_outputs(output, decision)

    assert output.read_text(encoding="utf-8").splitlines() == [
        "decision=migration",
        "has_new_data=true",
        "market_as_of=2026-07-17",
        "source_post_id=97669",
        "source_title=狼来了的故事",
        "image_count=2",
    ]
