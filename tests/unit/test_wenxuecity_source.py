"""Contracts for copying charts from the authoritative Wenxuecity posts."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from datetime import date, datetime

import pytest

from semipulse_sentinel.wenxuecity_source import (
    AuthorArchivePost,
    SourceIdentity,
    SourcePost,
    WenxuecitySourceError,
    discover_latest_source,
    download_source_images,
    is_relevant_source_post,
    parse_author_archive,
    parse_source_post,
    validate_asset_url,
    validate_post_url,
)

SEED_URL = "https://bbs.wenxuecity.com/cfzh/97669.html"
ARCHIVE_URL = (
    "https://bbs.wenxuecity.com/bbs/archive.php?"
    "SubID=cfzh&keyword=%E4%BA%91%E8%B5%B7%E5%8D%83%E7%99%BE%E5%BA%A6&username=on"
)


def _jpeg(width: int = 1000, height: int = 786) -> bytes:
    return (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x04JF"
        + b"\xff\xc0"
        + struct.pack(">H", 17)
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
        + b"\xff\xd9"
    )


def _post_html(
    *,
    post_id: int = 97669,
    title: str = "狼来了的故事",
    author: str = "云起千百度",
    published: str = "2026-07-17 21:00:42",
    edited: str = "2026-07-17 22:17:59",
    body: str = "半导体 SOXL risk",
    images: tuple[str, ...] = (
        "/upload/album/bb/e8/bd/one.jpeg",
        "/upload/album/bb/e8/bd/two.jpeg",
    ),
) -> bytes:
    image_html = "".join(f'<img src="{item}">' for item in images)
    return f"""<!doctype html>
    <html><body>
      <h1>{title}</h1>
      <div class="post-source">来源: <a>{author}</a> 于 {published}</div>
      <div class="edit">本帖于 {edited} 时间, 由普通用户 {author} 编辑</div>
      <div id="msgbodyContent"><p>{body}</p><p>{image_html}</p></div>
      <div id="comment"><img src="/images/not-source.gif"></div>
      <a href="/cfzh/{post_id}.html">canonical</a>
    </body></html>""".encode()


def _archive_html() -> bytes:
    return """<!doctype html><table>
      <tr><td>• #跟帖# reply [财富智汇] - 云起千百度 2026-07-19
        <a href="https://bbs.wenxuecity.com/cfzh/97888.html">reply</a></td></tr>
      <tr><td>• 新半导体图表 [财富智汇] - 云起千百度 2026-07-18
        <a href="https://bbs.wenxuecity.com/cfzh/97800.html">新半导体图表</a></td></tr>
      <tr><td>• 狼来了的故事 [财富智汇] - 云起千百度 2026-07-17
        <a href="https://bbs.wenxuecity.com/cfzh/97669.html">狼来了的故事</a></td></tr>
      <tr><td>• unrelated host [财富智汇] - 云起千百度 2026-07-16
        <a href="https://evil.example/cfzh/1.html">bad</a></td></tr>
    </table>""".encode()


@dataclass
class _Response:
    body: bytes
    content_type: str
    final_url: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Content-Type": self.content_type}

    def geturl(self) -> str:
        return self.final_url

    def read(self, amount: int = -1) -> bytes:
        return self.body if amount < 0 else self.body[:amount]

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _Opener:
    def __init__(self) -> None:
        self.responses: dict[str, _Response] = {}
        self.calls: list[str] = []

    def add(
        self,
        url: str,
        body: bytes,
        content_type: str = "text/html; charset=UTF-8",
        *,
        final_url: str | None = None,
    ) -> None:
        self.responses[url] = _Response(body, content_type, final_url or url)

    def open(self, url: str, *, timeout: float) -> _Response:
        del timeout
        self.calls.append(url)
        return self.responses[url]


def test_parse_source_post_reads_only_ordered_post_body_images() -> None:
    post = parse_source_post(_post_html(), SEED_URL)

    assert post == SourcePost(
        post_id=97669,
        url=SEED_URL,
        title="狼来了的故事",
        author="云起千百度",
        published_at=datetime(2026, 7, 17, 21, 0, 42),
        edited_at=datetime(2026, 7, 17, 22, 17, 59),
        body_text="半导体 SOXL risk",
        image_urls=(
            "https://bbs.wenxuecity.com/upload/album/bb/e8/bd/one.jpeg",
            "https://bbs.wenxuecity.com/upload/album/bb/e8/bd/two.jpeg",
        ),
    )


def test_archive_parser_excludes_replies_and_noncanonical_hosts() -> None:
    posts = parse_author_archive(_archive_html())

    assert posts == (
        AuthorArchivePost(
            post_id=97800,
            url="https://bbs.wenxuecity.com/cfzh/97800.html",
            title="新半导体图表",
            published_on=date(2026, 7, 18),
        ),
        AuthorArchivePost(
            post_id=97669,
            url=SEED_URL,
            title="狼来了的故事",
            published_on=date(2026, 7, 17),
        ),
    )


@pytest.mark.parametrize(
    "value",
    [
        "http://bbs.wenxuecity.com/cfzh/97669.html",
        "https://evil.example/cfzh/97669.html",
        "https://user@bbs.wenxuecity.com/cfzh/97669.html",
        "https://bbs.wenxuecity.com/other/97669.html",
        "https://bbs.wenxuecity.com/cfzh/97669.html?x=1",
    ],
)
def test_post_url_validation_is_fail_closed(value: str) -> None:
    with pytest.raises(ValueError):
        validate_post_url(value)


@pytest.mark.parametrize(
    "value",
    [
        "http://bbs.wenxuecity.com/upload/album/a.jpeg",
        "https://evil.example/upload/album/a.jpeg",
        "https://bbs.wenxuecity.com/images/a.jpeg",
        "https://bbs.wenxuecity.com/upload/album/a.svg",
        "https://bbs.wenxuecity.com/upload/album/a.jpeg?token=x",
    ],
)
def test_asset_url_validation_is_fail_closed(value: str) -> None:
    with pytest.raises(ValueError):
        validate_asset_url(value)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("半导体风险", True),
        ("SOXL broke support", True),
        ("new SMH chart", True),
        ("football photos", False),
    ],
)
def test_relevance_requires_semiconductor_markers(text: str, expected: bool) -> None:
    post = parse_source_post(_post_html(body=text), SEED_URL)
    assert is_relevant_source_post(post) is expected


def test_download_preserves_jpeg_bytes_and_validates_cdn_redirect() -> None:
    post = parse_source_post(
        _post_html(images=("/upload/album/bb/e8/bd/one.jpeg",)), SEED_URL
    )
    opener = _Opener()
    jpeg = _jpeg()
    opener.add(
        post.image_urls[0],
        jpeg,
        "image/jpeg",
        final_url="https://cdn.wenxuecity.net/upload/album/bb/e8/bd/one.jpeg",
    )

    images = download_source_images(post, opener=opener)

    assert len(images) == 1
    assert images[0].data == jpeg
    assert images[0].width == 1000
    assert images[0].height == 786
    assert images[0].sha256 == hashlib.sha256(jpeg).hexdigest()
    assert images[0].resolved_url.startswith("https://cdn.wenxuecity.net/")


def test_download_rejects_redirect_to_untrusted_host() -> None:
    post = parse_source_post(
        _post_html(images=("/upload/album/bb/e8/bd/one.jpeg",)), SEED_URL
    )
    opener = _Opener()
    opener.add(
        post.image_urls[0],
        _jpeg(),
        "image/jpeg",
        final_url="https://evil.example/upload/album/one.jpeg",
    )

    with pytest.raises(WenxuecitySourceError, match="redirect"):
        download_source_images(post, opener=opener)


def test_discovery_selects_newer_relevant_top_level_post() -> None:
    opener = _Opener()
    opener.add(SEED_URL, _post_html())
    opener.add(ARCHIVE_URL, _archive_html())
    newer_url = "https://bbs.wenxuecity.com/cfzh/97800.html"
    newer_image = "https://bbs.wenxuecity.com/upload/album/aa/bb/cc/new.jpeg"
    opener.add(
        newer_url,
        _post_html(
            post_id=97800,
            title="新半导体图表",
            published="2026-07-18 18:30:00",
            edited="2026-07-18 18:31:00",
            body="semiconductor update",
            images=("/upload/album/aa/bb/cc/new.jpeg",),
        ),
    )
    opener.add(
        newer_image,
        _jpeg(1200, 700),
        "image/jpeg",
        final_url="https://cdn.wenxuecity.net/upload/album/aa/bb/cc/new.jpeg",
    )
    current = SourceIdentity(
        post_id=97669,
        published_at=datetime(2026, 7, 17, 21, 0, 42),
        image_sha256=("old",),
    )

    bundle = discover_latest_source(
        seed_url=SEED_URL,
        archive_url=ARCHIVE_URL,
        current=current,
        opener=opener,
    )

    assert bundle is not None
    assert bundle.post.post_id == 97800
    assert len(bundle.images) == 1


def test_discovery_returns_none_for_exact_current_manifest() -> None:
    opener = _Opener()
    seed_image = "https://bbs.wenxuecity.com/upload/album/bb/e8/bd/one.jpeg"
    jpeg = _jpeg()
    opener.add(
        SEED_URL,
        _post_html(images=("/upload/album/bb/e8/bd/one.jpeg",)),
    )
    opener.add(ARCHIVE_URL, _archive_html().replace(b"97800", b"97500"))
    opener.add(
        seed_image,
        jpeg,
        "image/jpeg",
        final_url="https://cdn.wenxuecity.net/upload/album/bb/e8/bd/one.jpeg",
    )
    current = SourceIdentity(
        post_id=97669,
        published_at=datetime(2026, 7, 17, 21, 0, 42),
        image_sha256=(hashlib.sha256(jpeg).hexdigest(),),
    )

    assert (
        discover_latest_source(
            seed_url=SEED_URL,
            archive_url=ARCHIVE_URL,
            current=current,
            opener=opener,
        )
        is None
    )
