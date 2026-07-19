"""Source-only static report contracts."""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from semipulse_sentinel.source_report import (
    SOURCE_REPORT_SCHEMA,
    build_source_report,
    validate_source_site,
)
from semipulse_sentinel.wenxuecity_source import (
    SourceBundle,
    SourceImage,
    SourcePost,
)


def _jpeg(width: int, height: int, suffix: bytes = b"") -> bytes:
    return (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x04JF"
        + b"\xff\xc0"
        + struct.pack(">H", 17)
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
        + suffix
        + b"\xff\xd9"
    )


def _bundle(*, title: str = "狼来了的故事") -> SourceBundle:
    first = _jpeg(1000, 786, b"first")
    second = _jpeg(1000, 650, b"second")
    post = SourcePost(
        post_id=97669,
        url="https://bbs.wenxuecity.com/cfzh/97669.html",
        title=title,
        author="云起千百度",
        published_at=datetime(2026, 7, 17, 21, 0, 42),
        edited_at=datetime(2026, 7, 17, 22, 17, 59),
        body_text="半导体 source",
        image_urls=(
            "https://bbs.wenxuecity.com/upload/album/aa/bb/one.jpeg",
            "https://bbs.wenxuecity.com/upload/album/aa/bb/two.jpeg",
        ),
    )
    images = (
        SourceImage(
            source_url=post.image_urls[0],
            resolved_url=(
                "https://cdn.wenxuecity.net/upload/album/aa/bb/one.jpeg"
            ),
            content_type="image/jpeg",
            data=first,
            sha256=hashlib.sha256(first).hexdigest(),
            width=1000,
            height=786,
        ),
        SourceImage(
            source_url=post.image_urls[1],
            resolved_url=(
                "https://cdn.wenxuecity.net/upload/album/aa/bb/two.jpeg"
            ),
            content_type="image/jpeg",
            data=second,
            sha256=hashlib.sha256(second).hexdigest(),
            width=1000,
            height=650,
        ),
    )
    return SourceBundle(post=post, images=images)


def _clock() -> datetime:
    return datetime(2026, 7, 19, 1, 30, tzinfo=UTC)


def test_build_copies_every_source_image_byte_for_byte_in_order(
    tmp_path: Path,
) -> None:
    bundle = _bundle()
    output = tmp_path / "site"

    result = build_source_report(bundle, output, _clock)

    assert result.schema_version == SOURCE_REPORT_SCHEMA
    assert result.market_as_of.isoformat() == "2026-07-17"
    assert result.source_post_id == 97669
    assert result.image_sha256 == tuple(image.sha256 for image in bundle.images)
    assert (output / "charts/source-01.jpeg").read_bytes() == (
        bundle.images[0].data
    )
    assert (output / "charts/source-02.jpeg").read_bytes() == (
        bundle.images[1].data
    )


def test_report_json_records_source_provenance_and_exact_hashes(
    tmp_path: Path,
) -> None:
    output = tmp_path / "site"
    bundle = _bundle()
    build_source_report(bundle, output, _clock)

    payload = json.loads((output / "report.json").read_text(encoding="utf-8"))

    assert payload["schema_version"] == SOURCE_REPORT_SCHEMA
    assert payload["market_as_of"] == "2026-07-17"
    assert payload["source"]["url"] == bundle.post.url
    assert payload["source"]["author"] == "云起千百度"
    assert payload["source"]["copied_unchanged"] is True
    assert [item["ordinal"] for item in payload["images"]] == [1, 2]
    assert [item["sha256"] for item in payload["images"]] == [
        image.sha256 for image in bundle.images
    ]


def test_html_identifies_source_copy_and_escapes_post_title(tmp_path: Path) -> None:
    output = tmp_path / "site"
    build_source_report(_bundle(title="<script>alert(1)</script>"), output, _clock)

    html = (output / "index.html").read_text(encoding="utf-8")

    assert "Copied from source - not recreated" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "charts/source-01.jpeg" in html
    assert "charts/source-02.jpeg" in html
    assert html.index("charts/source-01.jpeg") < html.index(
        "charts/source-02.jpeg"
    )


def test_invalid_candidate_preserves_previous_good_site(tmp_path: Path) -> None:
    output = tmp_path / "site"
    output.mkdir()
    (output / "sentinel.txt").write_text("last-good", encoding="utf-8")
    bundle = _bundle()
    broken_first = replace(bundle.images[0], data=b"not-a-jpeg")
    broken = replace(bundle, images=(broken_first, bundle.images[1]))

    with pytest.raises(ValueError):
        build_source_report(broken, output, _clock)

    assert (output / "sentinel.txt").read_text(encoding="utf-8") == "last-good"
    assert not (output / "report.json").exists()


def test_validate_source_site_rejects_tampered_local_image(tmp_path: Path) -> None:
    output = tmp_path / "site"
    build_source_report(_bundle(), output, _clock)
    (output / "charts/source-01.jpeg").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="hash"):
        validate_source_site(output)


def test_validate_source_site_round_trips_snapshot(tmp_path: Path) -> None:
    output = tmp_path / "site"
    expected = build_source_report(_bundle(), output, _clock)

    assert validate_source_site(output) == expected
