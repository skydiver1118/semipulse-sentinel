import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

import semipulse_sentinel.publication as publication
from semipulse_sentinel.publication import (
    append_github_outputs,
    decide_publication,
    read_report_snapshot,
)
from semipulse_sentinel.source_publication import SourcePublicationSnapshot


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


def _source_report(path: Path, market_as_of: str = "2026-07-17") -> Path:
    payload = {
        "schema_version": "semipulse-wenxuecity-source-v1",
        "market_as_of": market_as_of,
        "source": {
            "post_id": 97669,
            "published_at": f"{market_as_of}T21:00:42",
            "title": "狼来了的故事",
        },
        "images": [
            {"sha256": "a" * 64},
            {"sha256": "b" * 64},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_newer_candidate_is_publishable_and_writes_safe_outputs(tmp_path: Path) -> None:
    candidate = read_report_snapshot(_report(tmp_path / "candidate.json", "2026-07-20"))
    published = publication.read_published_report_snapshot(
        _report(tmp_path / "published.json", "2026-07-17")
    )
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
    candidate = read_report_snapshot(
        _report(tmp_path / "candidate.json", "2026-07-17")
    )
    published = publication.read_published_report_snapshot(
        _report(tmp_path / "published.json", "2026-07-17")
    )

    decision = decide_publication(candidate, published)

    assert decision.kind == "unchanged"
    assert decision.has_new_data is False


def test_same_date_source_report_allows_one_way_daily_migration(
    tmp_path: Path,
) -> None:
    candidate = read_report_snapshot(
        _report(tmp_path / "candidate.json", "2026-07-17")
    )
    published = publication.read_published_report_snapshot(
        _source_report(tmp_path / "published.json")
    )
    assert isinstance(published, SourcePublicationSnapshot)
    assert published.image_sha256 == ("a" * 64, "b" * 64)

    decision = decide_publication(candidate, published)
    output = tmp_path / "github-output"
    append_github_outputs(output, decision)

    assert decision.kind == "migration"
    assert decision.has_new_data is True
    assert output.read_text(encoding="utf-8").splitlines() == [
        "decision=migration",
        "has_new_data=true",
        "market_as_of=2026-07-17",
        "published_market_as_of=2026-07-17",
        "regime=defensive",
        "confidence=medium",
        "coverage=21/23 (91.3%)",
    ]


def test_overlapping_same_date_migration_serializes_the_first_notification(
    tmp_path: Path,
) -> None:
    candidate_path = _report(tmp_path / "candidate.json", "2026-07-17")
    candidate = read_report_snapshot(candidate_path)
    source = publication.read_published_report_snapshot(
        _source_report(tmp_path / "published-source.json")
    )

    first = decide_publication(candidate, source)
    published_daily = publication.read_published_report_snapshot(candidate_path)
    second = decide_publication(candidate, published_daily)
    workflow = yaml.safe_load(
        Path(".github/workflows/nightly-report.yml").read_text(encoding="utf-8")
    )

    assert first.kind == "migration"
    assert first.has_new_data is True
    assert second.kind == "unchanged"
    assert second.has_new_data is False
    assert workflow["concurrency"] == {
        "group": "semipulse-pages",
        "cancel-in-progress": False,
    }
    assert workflow["jobs"]["notify"]["if"] == (
        "needs.build.outputs.has_new_data == 'true' && "
        "needs.deploy.result == 'success'"
    )


def test_newer_daily_candidate_migrates_over_source_report(tmp_path: Path) -> None:
    candidate = read_report_snapshot(
        _report(tmp_path / "candidate.json", "2026-07-20")
    )
    published = publication.read_published_report_snapshot(
        _source_report(tmp_path / "published.json")
    )

    decision = decide_publication(candidate, published)

    assert decision.kind == "migration"
    assert decision.has_new_data is True


def test_older_daily_candidate_cannot_migrate_over_source_report(
    tmp_path: Path,
) -> None:
    candidate = read_report_snapshot(
        _report(tmp_path / "candidate.json", "2026-07-16")
    )
    published = publication.read_published_report_snapshot(
        _source_report(tmp_path / "published.json")
    )

    with pytest.raises(ValueError, match="regressed"):
        decide_publication(candidate, published)


def test_regressed_candidate_is_rejected(tmp_path: Path) -> None:
    candidate = read_report_snapshot(_report(tmp_path / "candidate.json", "2026-07-16"))
    published = publication.read_published_report_snapshot(
        _report(tmp_path / "published.json", "2026-07-17")
    )

    with pytest.raises(ValueError, match="regressed"):
        decide_publication(candidate, published)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema_version="unknown-report-v1"),
        lambda payload: payload["source"].update(post_id=True),
        lambda payload: payload["source"].update(
            published_at="2026-07-16T21:00:42"
        ),
        lambda payload: payload["source"].update(title="unsafe\nvalue"),
        lambda payload: payload.update(images=[{"sha256": "not-a-hash"}]),
    ],
)
def test_published_reader_rejects_unknown_or_malformed_source_reports(
    tmp_path: Path, mutation: Callable[[dict[str, Any]], None]
) -> None:
    path = _source_report(tmp_path / "published.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutation(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        publication.read_published_report_snapshot(path)


def test_published_reader_does_not_accept_schema_and_date_only(
    tmp_path: Path,
) -> None:
    path = tmp_path / "published.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "semipulse-report-v1",
                "market_as_of": "2026-07-17",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        publication.read_published_report_snapshot(path)


def test_source_schema_is_never_accepted_as_daily_candidate(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="schema"):
        read_report_snapshot(_source_report(tmp_path / "candidate.json"))


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
