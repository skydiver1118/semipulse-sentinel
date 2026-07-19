"""Atomic static report built only from copied Wenxuecity source images."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from .wenxuecity_source import (
    CDN_HOST,
    MAX_DIMENSION,
    MAX_IMAGES,
    MIN_HEIGHT,
    MIN_WIDTH,
    SOURCE_AUTHOR,
    SourceBundle,
    SourceImage,
    _image_dimensions,
    validate_asset_url,
    validate_post_url,
)

SOURCE_REPORT_SCHEMA = "semipulse-wenxuecity-source-v1"
DASHBOARD_URL = "https://skydiver1118.github.io/semipulse-sentinel/"
RISK_DISCLOSURE = (
    "Research only - not individualized investment advice or a recommendation "
    "to buy or sell. Source images may be delayed, incomplete, or revised."
)


@dataclass(frozen=True, slots=True)
class SourceReportSnapshot:
    schema_version: str
    market_as_of: date
    source_post_id: int
    source_published_at: datetime
    source_edited_at: datetime | None
    source_title: str
    image_sha256: tuple[str, ...]

    @property
    def image_count(self) -> int:
        return len(self.image_sha256)


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("build clock must return a timezone-aware datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_naive_timestamp(value: datetime) -> str:
    if value.tzinfo is not None:
        raise ValueError("source timestamps must be naive Wenxuecity local times")
    return value.isoformat(timespec="seconds")


def _validate_resolved_url(value: str, source_url: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != CDN_HOST
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != urlsplit(source_url).path
    ):
        raise ValueError("resolved source image URL is invalid")
    return value


def _validate_source_image(image: SourceImage) -> None:
    validate_asset_url(image.source_url)
    _validate_resolved_url(image.resolved_url, image.source_url)
    if image.content_type not in {"image/jpeg", "image/png"}:
        raise ValueError("source image content type is invalid")
    if hashlib.sha256(image.data).hexdigest() != image.sha256:
        raise ValueError("source image hash metadata does not match its bytes")
    width, height = _image_dimensions(image.data, image.content_type)
    if (width, height) != (image.width, image.height):
        raise ValueError("source image dimensions do not match its bytes")
    if (
        width < MIN_WIDTH
        or height < MIN_HEIGHT
        or width > MAX_DIMENSION
        or height > MAX_DIMENSION
    ):
        raise ValueError("source image dimensions are outside the report contract")


def _validate_bundle(bundle: SourceBundle) -> None:
    validate_post_url(bundle.post.url)
    if bundle.post.author != SOURCE_AUTHOR:
        raise ValueError("source author is invalid")
    if not bundle.post.title.strip():
        raise ValueError("source title is empty")
    if not 1 <= len(bundle.images) <= MAX_IMAGES:
        raise ValueError("source image count is outside the report contract")
    if tuple(image.source_url for image in bundle.images) != bundle.post.image_urls:
        raise ValueError("source image order does not match the post body")
    for image in bundle.images:
        _validate_source_image(image)


def _image_extension(content_type: str) -> str:
    if content_type == "image/jpeg":
        return "jpeg"
    if content_type == "image/png":
        return "png"
    raise ValueError("source image content type is invalid")


def _payload(bundle: SourceBundle, built_at: datetime) -> dict[str, Any]:
    images: list[dict[str, Any]] = []
    for ordinal, image in enumerate(bundle.images, start=1):
        extension = _image_extension(image.content_type)
        images.append(
            {
                "ordinal": ordinal,
                "source_url": image.source_url,
                "resolved_url": image.resolved_url,
                "local_path": f"charts/source-{ordinal:02d}.{extension}",
                "content_type": image.content_type,
                "sha256": image.sha256,
                "byte_length": image.byte_length,
                "width": image.width,
                "height": image.height,
            }
        )
    return {
        "schema_version": SOURCE_REPORT_SCHEMA,
        "market_as_of": bundle.post.published_at.date().isoformat(),
        "built_at": _iso_utc(built_at),
        "dashboard_url": DASHBOARD_URL,
        "source": {
            "post_id": bundle.post.post_id,
            "url": bundle.post.url,
            "title": bundle.post.title,
            "author": bundle.post.author,
            "published_at": _canonical_naive_timestamp(
                bundle.post.published_at
            ),
            "edited_at": (
                _canonical_naive_timestamp(bundle.post.edited_at)
                if bundle.post.edited_at is not None
                else None
            ),
            "copied_unchanged": True,
        },
        "images": images,
        "risk_disclosure": RISK_DISCLOSURE,
    }


def _resources() -> tuple[Path, Path]:
    package = Path(__file__).resolve().parent
    return (
        package / "templates" / "source_report.html.j2",
        package / "static" / "source_report.css",
    )


def _write_candidate(
    bundle: SourceBundle, stage: Path, built_at: datetime
) -> None:
    template_path, css_path = _resources()
    if not template_path.is_file() or not css_path.is_file():
        raise FileNotFoundError("source report resources are missing")
    charts = stage / "charts"
    static = stage / "static"
    charts.mkdir(parents=True)
    static.mkdir()
    payload = _payload(bundle, built_at)
    for image, record in zip(bundle.images, payload["images"], strict=True):
        target = stage / str(record["local_path"])
        target.write_bytes(image.data)
    (stage / "report.json").write_text(
        _canonical_json(payload), encoding="utf-8", newline="\n"
    )
    shutil.copyfile(css_path, static / "source-report.css")
    environment = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=select_autoescape(("html", "xml", "j2")),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    html = environment.get_template(template_path.name).render(report=payload)
    (stage / "index.html").write_text(html, encoding="utf-8", newline="\n")


def _parse_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a timestamp string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} is invalid") from error
    if parsed.tzinfo is not None or parsed.isoformat(timespec="seconds") != value:
        raise ValueError(f"{label} is not canonical")
    return parsed


def _safe_local_path(value: object, expected: str) -> str:
    if not isinstance(value, str) or value != expected:
        raise ValueError("source image local path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("source image local path is unsafe")
    return value


def validate_source_site(path: Path) -> SourceReportSnapshot:
    """Validate one complete source-copy site and return its typed snapshot."""

    if not path.is_dir() or path.is_symlink():
        raise ValueError("source report site is missing or unsafe")
    report_path = path / "report.json"
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("source report JSON is unreadable") from error
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "market_as_of",
        "built_at",
        "dashboard_url",
        "source",
        "images",
        "risk_disclosure",
    }:
        raise ValueError("source report JSON root is invalid")
    if payload["schema_version"] != SOURCE_REPORT_SCHEMA:
        raise ValueError("source report schema is invalid")
    if payload["dashboard_url"] != DASHBOARD_URL:
        raise ValueError("source report dashboard URL is invalid")
    try:
        market_as_of = date.fromisoformat(payload["market_as_of"])
    except (TypeError, ValueError) as error:
        raise ValueError("source report market date is invalid") from error
    if market_as_of.isoformat() != payload["market_as_of"]:
        raise ValueError("source report market date is not canonical")
    built_at = payload["built_at"]
    if not isinstance(built_at, str) or not built_at.endswith("Z"):
        raise ValueError("source report build timestamp is invalid")
    try:
        built = datetime.fromisoformat(built_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("source report build timestamp is invalid") from error
    if built.tzinfo is None or built.utcoffset() != UTC.utcoffset(built):
        raise ValueError("source report build timestamp is not UTC")
    source = payload["source"]
    if not isinstance(source, dict) or set(source) != {
        "post_id",
        "url",
        "title",
        "author",
        "published_at",
        "edited_at",
        "copied_unchanged",
    }:
        raise ValueError("source report post metadata is invalid")
    if (
        not isinstance(source["post_id"], int)
        or source["post_id"] < 1
        or source["url"] != validate_post_url(source["url"])
        or source["author"] != SOURCE_AUTHOR
        or not isinstance(source["title"], str)
        or not source["title"].strip()
        or source["copied_unchanged"] is not True
    ):
        raise ValueError("source report post metadata is invalid")
    published_at = _parse_datetime(source["published_at"], "published_at")
    edited_at = (
        _parse_datetime(source["edited_at"], "edited_at")
        if source["edited_at"] is not None
        else None
    )
    if market_as_of != published_at.date():
        raise ValueError("source report market date disagrees with the post")
    records = payload["images"]
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_IMAGES:
        raise ValueError("source report image manifest is invalid")
    hashes: list[str] = []
    expected_files = {
        "index.html",
        "report.json",
        "static/source-report.css",
    }
    for ordinal, record in enumerate(records, start=1):
        if not isinstance(record, dict) or set(record) != {
            "ordinal",
            "source_url",
            "resolved_url",
            "local_path",
            "content_type",
            "sha256",
            "byte_length",
            "width",
            "height",
        }:
            raise ValueError("source report image record is invalid")
        if record["ordinal"] != ordinal:
            raise ValueError("source report image order is invalid")
        source_url = validate_asset_url(record["source_url"])
        _validate_resolved_url(record["resolved_url"], source_url)
        content_type = record["content_type"]
        extension = _image_extension(content_type)
        expected = f"charts/source-{ordinal:02d}.{extension}"
        local_path = _safe_local_path(record["local_path"], expected)
        image_path = path / local_path
        if not image_path.is_file() or image_path.is_symlink():
            raise ValueError("source report image file is missing or unsafe")
        data = image_path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != record["sha256"]:
            raise ValueError("source report image hash is invalid")
        if len(data) != record["byte_length"]:
            raise ValueError("source report image byte length is invalid")
        width, height = _image_dimensions(data, content_type)
        if (width, height) != (record["width"], record["height"]):
            raise ValueError("source report image dimensions are invalid")
        hashes.append(digest)
        expected_files.add(local_path)
    actual_files = {
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_file()
    }
    if actual_files != expected_files:
        raise ValueError("source report contains missing or unexpected files")
    for required in (path / "index.html", path / "static/source-report.css"):
        if (
            required.is_symlink()
            or not required.is_file()
            or required.stat().st_size < 1
        ):
            raise ValueError("source report HTML or CSS is missing")
    html = (path / "index.html").read_text(encoding="utf-8")
    if "Copied from source - not recreated" not in html:
        raise ValueError("source-copy disclosure is missing")
    for ordinal, record in enumerate(records, start=1):
        if html.count(str(record["local_path"])) != 1:
            raise ValueError(f"source image {ordinal} is not linked exactly once")
    return SourceReportSnapshot(
        schema_version=SOURCE_REPORT_SCHEMA,
        market_as_of=market_as_of,
        source_post_id=source["post_id"],
        source_published_at=published_at,
        source_edited_at=edited_at,
        source_title=source["title"],
        image_sha256=tuple(hashes),
    )


def _replace_directory(stage: Path, output: Path) -> None:
    backup = output.parent / f".{output.name}.backup"
    if backup.exists():
        raise ValueError("source report backup path is unexpectedly occupied")
    moved_previous = False
    try:
        if output.exists():
            if not output.is_dir() or output.is_symlink():
                raise ValueError("source report output path is unsafe")
            output.rename(backup)
            moved_previous = True
        stage.rename(output)
    except Exception:
        if moved_previous and backup.exists() and not output.exists():
            backup.rename(output)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def build_source_report(
    bundle: SourceBundle,
    output: Path,
    clock: Callable[[], datetime],
) -> SourceReportSnapshot:
    """Build, validate, and atomically replace a source-only static report."""

    _validate_bundle(bundle)
    built_at = clock()
    _iso_utc(built_at)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent)
    )
    try:
        _write_candidate(bundle, stage, built_at)
        expected = validate_source_site(stage)
        _replace_directory(stage, output)
        return expected
    finally:
        if stage.exists():
            shutil.rmtree(stage)
