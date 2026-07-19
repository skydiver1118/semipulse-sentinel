"""Bounded, source-only ingestion of Wenxuecity chart posts."""

from __future__ import annotations

import hashlib
import re
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Protocol, cast
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener

SOURCE_AUTHOR = "云起千百度"
SOURCE_HOST = "bbs.wenxuecity.com"
CDN_HOST = "cdn.wenxuecity.net"
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 12
MAX_ARCHIVE_POSTS = 5
MIN_WIDTH = 600
MIN_HEIGHT = 350
MAX_DIMENSION = 5000
HTTP_TIMEOUT_SECONDS = 20.0

_POST_PATH = re.compile(r"/cfzh/(?P<post_id>[1-9][0-9]*)\.html")
_ASSET_PATH = re.compile(
    r"/upload/album/(?:[A-Za-z0-9_-]+/)+[A-Za-z0-9_-]+\.(?:jpe?g|png)",
    re.IGNORECASE,
)
_TIMESTAMP = r"(?P<timestamp>20[0-9]{2}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})"
_PUBLISHED = re.compile(rf"来源:\s*(?P<author>\S+)\s*于\s*{_TIMESTAMP}")
_EDITED = re.compile(rf"本帖于\s*{_TIMESTAMP}.*?编辑")
_ARCHIVE_DATE = re.compile(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}")
_RELEVANCE_MARKERS = ("半导体", "semiconductor", "sox", "soxl", "smh")
_JPEG_SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


class WenxuecitySourceError(ValueError):
    """Raised when a public source violates the fail-closed contract."""


class HttpResponse(Protocol):
    headers: object

    def geturl(self) -> str: ...

    def read(self, amount: int = -1) -> bytes: ...

    def __enter__(self) -> HttpResponse: ...

    def __exit__(self, *args: object) -> object: ...


class UrlOpener(Protocol):
    def open(self, url: str, *, timeout: float) -> HttpResponse: ...


class _DefaultOpener:
    def __init__(self) -> None:
        self._opener = build_opener()

    def open(self, url: str, *, timeout: float) -> HttpResponse:
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "SemiPulse-Sentinel/0.1 "
                    "(+https://github.com/skydiver1118/semipulse-sentinel)"
                ),
                "Accept": "text/html,image/jpeg,image/png;q=0.9,*/*;q=0.1",
            },
        )
        return cast(HttpResponse, self._opener.open(request, timeout=timeout))


@dataclass(frozen=True, slots=True)
class SourcePost:
    post_id: int
    url: str
    title: str
    author: str
    published_at: datetime
    edited_at: datetime | None
    body_text: str
    image_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuthorArchivePost:
    post_id: int
    url: str
    title: str
    published_on: date


@dataclass(frozen=True, slots=True)
class SourceImage:
    source_url: str
    resolved_url: str
    content_type: str
    data: bytes
    sha256: str
    width: int
    height: int

    @property
    def byte_length(self) -> int:
        return len(self.data)


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    post_id: int
    published_at: datetime
    image_sha256: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceBundle:
    post: SourcePost
    images: tuple[SourceImage, ...]

    @property
    def identity(self) -> SourceIdentity:
        return SourceIdentity(
            post_id=self.post.post_id,
            published_at=self.post.published_at,
            image_sha256=tuple(image.sha256 for image in self.images),
        )


def _canonical_https_parts(value: str, *, host: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != host
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"URL is outside the allowed {host} HTTPS boundary")
    return parsed.path, parsed.geturl()


def validate_post_url(value: str) -> str:
    """Return one canonical top-level Wealth Forum post URL."""

    path, canonical = _canonical_https_parts(value, host=SOURCE_HOST)
    if _POST_PATH.fullmatch(path) is None:
        raise ValueError("source post URL path is invalid")
    return canonical


def validate_asset_url(value: str) -> str:
    """Return one canonical Wenxuecity upload URL."""

    path, canonical = _canonical_https_parts(value, host=SOURCE_HOST)
    if _ASSET_PATH.fullmatch(path) is None:
        raise ValueError("source asset URL path is invalid")
    return canonical


def _validate_resolved_asset_url(value: str, expected_path: str) -> str:
    try:
        path, canonical = _canonical_https_parts(value, host=CDN_HOST)
    except ValueError as error:
        raise WenxuecitySourceError(
            "source image redirect is outside the allowlist"
        ) from error
    if path != expected_path or _ASSET_PATH.fullmatch(path) is None:
        raise WenxuecitySourceError("source image redirect is outside the allowlist")
    return canonical


def _normalize_text(parts: Iterable[str]) -> str:
    return " ".join(" ".join(parts).split())


class _PostParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.all_text: list[str] = []
        self.body_text: list[str] = []
        self.image_sources: list[str] = []
        self._in_h1 = False
        self._body_div_depth = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if tag == "h1":
            self._in_h1 = True
        if tag == "div":
            if self._body_div_depth:
                self._body_div_depth += 1
            elif attributes.get("id") == "msgbodyContent":
                self._body_div_depth = 1
        if tag == "img" and self._body_div_depth:
            source = attributes.get("src")
            if source:
                self.image_sources.append(source)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1":
            self._in_h1 = False
        if tag == "div" and self._body_div_depth:
            self._body_div_depth -= 1

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.all_text.append(data)
            if self._in_h1:
                self.title_parts.append(data)
            if self._body_div_depth:
                self.body_text.append(data)


class _ArchiveParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, list[tuple[str, str]]]] = []
        self._row_depth = 0
        self._row_text: list[str] = []
        self._links: list[list[str]] = []
        self._anchor_index: int | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "tr":
            if self._row_depth == 0:
                self._row_text = []
                self._links = []
            self._row_depth += 1
            return
        if tag == "a" and self._row_depth:
            href = dict(attrs).get("href")
            if href:
                self._links.append([href, ""])
                self._anchor_index = len(self._links) - 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._anchor_index = None
        if tag == "tr" and self._row_depth:
            self._row_depth -= 1
            if self._row_depth == 0:
                self.rows.append(
                    (
                        _normalize_text(self._row_text),
                        [(href, text.strip()) for href, text in self._links],
                    )
                )

    def handle_data(self, data: str) -> None:
        if self._row_depth:
            self._row_text.append(data)
            if self._anchor_index is not None:
                self._links[self._anchor_index][1] += data


def _decode_html(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise WenxuecitySourceError("source HTML is not valid UTF-8") from error


def parse_source_post(html: bytes, url: str) -> SourcePost:
    """Parse one canonical post and only its `msgbodyContent` images."""

    canonical_url = validate_post_url(url)
    parser = _PostParser()
    parser.feed(_decode_html(html))
    title = _normalize_text(parser.title_parts)
    all_text = _normalize_text(parser.all_text)
    body_text = _normalize_text(parser.body_text)
    published = _PUBLISHED.search(all_text)
    if not title or published is None:
        raise WenxuecitySourceError("source post metadata is incomplete")
    edited = _EDITED.search(all_text)
    image_urls: list[str] = []
    for source in parser.image_sources:
        absolute = urljoin(canonical_url, source)
        image_urls.append(validate_asset_url(absolute))
    post_match = _POST_PATH.fullmatch(urlsplit(canonical_url).path)
    assert post_match is not None
    return SourcePost(
        post_id=int(post_match.group("post_id")),
        url=canonical_url,
        title=title,
        author=published.group("author"),
        published_at=datetime.fromisoformat(published.group("timestamp")),
        edited_at=(
            datetime.fromisoformat(edited.group("timestamp"))
            if edited is not None
            else None
        ),
        body_text=body_text,
        image_urls=tuple(image_urls),
    )


def parse_author_archive(html: bytes) -> tuple[AuthorArchivePost, ...]:
    """Return current-page, top-level posts for the exact configured author."""

    parser = _ArchiveParser()
    parser.feed(_decode_html(html))
    results: list[AuthorArchivePost] = []
    seen: set[int] = set()
    for row_text, links in parser.rows:
        if (
            "[财富智汇]" not in row_text
            or SOURCE_AUTHOR not in row_text
            or "#跟帖#" in row_text
        ):
            continue
        date_match = _ARCHIVE_DATE.search(row_text)
        if date_match is None:
            continue
        for href, link_text in links:
            absolute = urljoin("https://bbs.wenxuecity.com/", href)
            try:
                canonical = validate_post_url(absolute)
            except ValueError:
                continue
            post_match = _POST_PATH.fullmatch(urlsplit(canonical).path)
            assert post_match is not None
            post_id = int(post_match.group("post_id"))
            if post_id in seen:
                continue
            title = link_text.strip()
            if not title or title == "•":
                continue
            seen.add(post_id)
            results.append(
                AuthorArchivePost(
                    post_id=post_id,
                    url=canonical,
                    title=title,
                    published_on=date.fromisoformat(date_match.group(0)),
                )
            )
            break
    return tuple(results)


def is_relevant_source_post(post: SourcePost) -> bool:
    """Require an explicit semiconductor marker in title or post body."""

    text = f"{post.title} {post.body_text}".casefold()
    return any(marker.casefold() in text for marker in _RELEVANCE_MARKERS)


def _headers_content_type(headers: object) -> str:
    getter = getattr(headers, "get", None)
    if getter is None:
        return ""
    value = getter("Content-Type", "")
    return str(value).split(";", 1)[0].strip().lower()


def _read_bounded(response: HttpResponse, limit: int, label: str) -> bytes:
    data = response.read(limit + 1)
    if len(data) > limit:
        raise WenxuecitySourceError(f"{label} is too large")
    return data


def _fetch_html(opener: UrlOpener, url: str, *, archive: bool = False) -> bytes:
    with opener.open(url, timeout=HTTP_TIMEOUT_SECONDS) as response:
        final_url = response.geturl()
        parsed = urlsplit(final_url)
        if parsed.scheme != "https" or parsed.hostname != SOURCE_HOST:
            raise WenxuecitySourceError("source page redirect is outside the allowlist")
        if archive:
            if parsed.path != "/bbs/archive.php":
                raise WenxuecitySourceError("author archive redirect is invalid")
        elif final_url != url:
            raise WenxuecitySourceError("source post redirect is invalid")
        if _headers_content_type(response.headers) != "text/html":
            raise WenxuecitySourceError("source page is not HTML")
        return _read_bounded(response, MAX_HTML_BYTES, "source HTML")


def _image_dimensions(data: bytes, content_type: str) -> tuple[int, int]:
    if content_type == "image/png":
        if (
            len(data) < 24
            or not data.startswith(b"\x89PNG\r\n\x1a\n")
            or data[12:16] != b"IHDR"
        ):
            raise WenxuecitySourceError("source image is not a canonical PNG")
        return struct.unpack(">II", data[16:24])
    if content_type != "image/jpeg" or not data.startswith(b"\xff\xd8"):
        raise WenxuecitySourceError("source image is not a canonical JPEG")
    position = 2
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            position += 1
            continue
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            break
        marker = data[position]
        position += 1
        if marker in {0x01, 0xD8, 0xD9}:
            continue
        if position + 2 > len(data):
            break
        length = struct.unpack(">H", data[position : position + 2])[0]
        if length < 2 or position + length > len(data):
            break
        if marker in _JPEG_SOF_MARKERS:
            if length < 7:
                break
            height, width = struct.unpack(">HH", data[position + 3 : position + 7])
            return width, height
        position += length
    raise WenxuecitySourceError("JPEG dimensions are unavailable")


def download_source_images(
    post: SourcePost, *, opener: UrlOpener | None = None
) -> tuple[SourceImage, ...]:
    """Download and validate the exact ordered post-body image bytes."""

    if not 1 <= len(post.image_urls) <= MAX_IMAGES:
        raise WenxuecitySourceError("source post must contain one to twelve images")
    client = opener or _DefaultOpener()
    images: list[SourceImage] = []
    for source_url in post.image_urls:
        canonical = validate_asset_url(source_url)
        expected_path = urlsplit(canonical).path
        with client.open(canonical, timeout=HTTP_TIMEOUT_SECONDS) as response:
            resolved = _validate_resolved_asset_url(
                response.geturl(), expected_path
            )
            content_type = _headers_content_type(response.headers)
            if content_type not in {"image/jpeg", "image/png"}:
                raise WenxuecitySourceError("source image type is invalid")
            data = _read_bounded(response, MAX_IMAGE_BYTES, "source image")
        width, height = _image_dimensions(data, content_type)
        if (
            width < MIN_WIDTH
            or height < MIN_HEIGHT
            or width > MAX_DIMENSION
            or height > MAX_DIMENSION
        ):
            raise WenxuecitySourceError("source image dimensions are invalid")
        images.append(
            SourceImage(
                source_url=canonical,
                resolved_url=resolved,
                content_type=content_type,
                data=data,
                sha256=hashlib.sha256(data).hexdigest(),
                width=width,
                height=height,
            )
        )
    return tuple(images)


def _bundle_for_post(post: SourcePost, opener: UrlOpener) -> SourceBundle:
    if post.author != SOURCE_AUTHOR:
        raise WenxuecitySourceError("source post author does not match")
    if not is_relevant_source_post(post):
        raise WenxuecitySourceError("source post is not semiconductor-relevant")
    return SourceBundle(post=post, images=download_source_images(post, opener=opener))


def discover_latest_source(
    *,
    seed_url: str,
    archive_url: str,
    current: SourceIdentity | None,
    opener: UrlOpener | None = None,
) -> SourceBundle | None:
    """Return a newer/revised valid source bundle, or `None` when unchanged."""

    seed_canonical = validate_post_url(seed_url)
    archive_parts = urlsplit(archive_url)
    if (
        archive_parts.scheme != "https"
        or archive_parts.hostname != SOURCE_HOST
        or archive_parts.port is not None
        or archive_parts.username is not None
        or archive_parts.password is not None
        or archive_parts.path != "/bbs/archive.php"
        or archive_parts.fragment
    ):
        raise ValueError("author archive URL is invalid")
    client = opener or _DefaultOpener()
    seed = parse_source_post(
        _fetch_html(client, seed_canonical), seed_canonical
    )
    archive = parse_author_archive(
        _fetch_html(client, archive_url, archive=True)
    )
    candidates: list[SourcePost] = [seed]
    for item in archive[:MAX_ARCHIVE_POSTS]:
        if item.post_id == seed.post_id:
            continue
        if current is not None and item.post_id < current.post_id:
            continue
        page = _fetch_html(client, item.url)
        post = parse_source_post(page, item.url)
        if post.author == SOURCE_AUTHOR and is_relevant_source_post(post):
            candidates.append(post)
    selected_post = max(
        candidates,
        key=lambda post: (post.published_at, post.post_id),
    )
    selected = _bundle_for_post(selected_post, client)
    if current is not None:
        if (
            selected.post.published_at < current.published_at
            or selected.post.post_id < current.post_id
        ):
            return None
        if selected.identity == current:
            return None
    return selected
