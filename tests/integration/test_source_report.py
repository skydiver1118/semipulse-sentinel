"""Complete source-copy site integration checks."""

from __future__ import annotations

import hashlib
import struct
from datetime import UTC, datetime
from pathlib import Path

from semipulse_sentinel.source_report import (
    build_source_report,
    validate_source_site,
)
from semipulse_sentinel.wenxuecity_source import (
    SourceBundle,
    SourceImage,
    SourcePost,
)


def _jpeg(width: int, height: int, marker: bytes) -> bytes:
    return (
        b"\xff\xd8\xff\xc0"
        + struct.pack(">H", 17)
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
        + marker
        + b"\xff\xd9"
    )


def test_complete_source_report_contains_no_reconstructed_chart_assets(
    tmp_path: Path,
) -> None:
    post = SourcePost(
        post_id=97669,
        url="https://bbs.wenxuecity.com/cfzh/97669.html",
        title="狼来了的故事",
        author="云起千百度",
        published_at=datetime(2026, 7, 17, 21, 0, 42),
        edited_at=None,
        body_text="SOXL semiconductor",
        image_urls=tuple(
            f"https://bbs.wenxuecity.com/upload/album/aa/bb/{index}.jpeg"
            for index in range(1, 9)
        ),
    )
    images = tuple(
        SourceImage(
            source_url=url,
            resolved_url=url.replace(
                "bbs.wenxuecity.com", "cdn.wenxuecity.net"
            ),
            content_type="image/jpeg",
            data=(data := _jpeg(1000, 600 + index, bytes([index]))),
            sha256=hashlib.sha256(data).hexdigest(),
            width=1000,
            height=600 + index,
        )
        for index, url in enumerate(post.image_urls, start=1)
    )
    output = tmp_path / "site"

    build_source_report(
        SourceBundle(post=post, images=images),
        output,
        lambda: datetime(2026, 7, 19, 1, 30, tzinfo=UTC),
    )
    snapshot = validate_source_site(output)

    assert len(snapshot.image_sha256) == 8
    assert len(list((output / "charts").glob("*.jpeg"))) == 8
    assert not list((output / "charts").glob("*.svg"))
    html = (output / "index.html").read_text(encoding="utf-8").lower()
    assert "yfinance" not in html
    assert "matplotlib" not in html
    assert "executive summary" not in html
