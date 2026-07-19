"""Structured, network-safe command-line boundary."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from .contracts import SCHEDULE_CRON, SCHEDULE_DESCRIPTION, SCHEDULE_TIMEZONE
from .version import __version__


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="semipulse-sentinel",
        description="Build and validate the SemiPulse Sentinel report.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="Build and atomically publish a report")
    build.add_argument("--watchlist", type=Path, default=Path("config/watchlist.csv"))
    build.add_argument("--output", type=Path, default=Path("site"))
    build.add_argument("--json", action="store_true", dest="json_output")

    validate = commands.add_parser("validate", help="Validate a static report site")
    validate.add_argument("--site", type=Path, default=Path("site"))
    validate.add_argument("--json", action="store_true", dest="json_output")

    doctor = commands.add_parser(
        "doctor", help="Inspect local readiness without network access"
    )
    doctor.add_argument("--watchlist", type=Path, default=Path("config/watchlist.csv"))
    doctor.add_argument("--site", type=Path, default=Path("site"))
    doctor.add_argument("--json", action="store_true", dest="json_output")

    publication = commands.add_parser(
        "decide-publication",
        help="Compare a candidate report with the published market date",
    )
    publication.add_argument("--candidate", type=Path, required=True)
    publication.add_argument("--published", type=Path, required=True)
    publication.add_argument("--github-output", type=Path, required=True)
    publication.add_argument("--json", action="store_true", dest="json_output")

    notify = commands.add_parser(
        "notify", help="Send one post-deploy report alert from environment settings"
    )
    notify.add_argument("--json", action="store_true", dest="json_output")

    build_source = commands.add_parser(
        "build-source",
        help="Copy the newest qualifying Wenxuecity chart post into a report",
    )
    build_source.add_argument("--seed-url")
    build_source.add_argument("--archive-url")
    build_source.add_argument("--output", type=Path, default=Path("site"))
    build_source.add_argument("--json", action="store_true", dest="json_output")

    validate_source = commands.add_parser(
        "validate-source", help="Validate a source-copy report site"
    )
    validate_source.add_argument("--site", type=Path, default=Path("site"))
    validate_source.add_argument(
        "--json", action="store_true", dest="json_output"
    )

    source_publication = commands.add_parser(
        "decide-source-publication",
        help="Compare source post identity and ordered image hashes",
    )
    source_publication.add_argument("--candidate", type=Path, required=True)
    source_publication.add_argument("--published", type=Path, required=True)
    source_publication.add_argument(
        "--github-output", type=Path, required=True
    )
    source_publication.add_argument(
        "--json", action="store_true", dest="json_output"
    )

    market_session = commands.add_parser(
        "check-market-session",
        help="Gate source scanning on a completed XNYS session",
    )
    market_session.add_argument("--at")
    market_session.add_argument("--github-output", type=Path, required=True)
    market_session.add_argument(
        "--json", action="store_true", dest="json_output"
    )
    return parser


def _emit(
    payload: dict[str, object], *, json_output: bool, error: bool = False
) -> None:
    stream = sys.stderr if error else sys.stdout
    if json_output:
        print(
            json.dumps(
                payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=stream,
        )
        return
    for key, value in payload.items():
        print(f"{key}: {value}", file=stream)


def _build(arguments: argparse.Namespace) -> int:
    from semipulse_sentinel.pipeline import build_report
    from semipulse_sentinel.providers.yfinance_provider import YFinanceProvider

    result = build_report(
        YFinanceProvider(),
        arguments.watchlist,
        arguments.output,
        lambda: datetime.now(UTC),
    )
    _emit(
        {
            "status": "success",
            "market_as_of": result.as_of.isoformat(),
            "chart_count": len(result.charts),
            "coverage": (
                f"{result.quality.covered_count}/"
                f"{result.quality.watchlist_count}"
            ),
            "output_hash": result.output_hash,
            "warnings": list(result.warnings),
        },
        json_output=arguments.json_output,
    )
    return 0


def _validate(arguments: argparse.Namespace) -> int:
    from semipulse_sentinel.report import validate_site

    result = validate_site(arguments.site)
    _emit(
        {
            "status": "valid",
            "chart_count": result.chart_count,
            "files_checked": result.files_checked,
            "schema_version": result.report_schema_version,
        },
        json_output=arguments.json_output,
    )
    return 0


def _dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for distribution in ("jinja2", "matplotlib", "numpy", "pandas", "yfinance"):
        try:
            versions[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            versions[distribution] = "missing"
    return versions


def _doctor(arguments: argparse.Namespace) -> int:
    from semipulse_sentinel.quality import PublicationBlocked
    from semipulse_sentinel.report import validate_site
    from semipulse_sentinel.watchlist import load_watchlist

    entries = load_watchlist(arguments.watchlist)
    statuses = Counter(entry.source_status for entry in entries)
    if not arguments.site.exists():
        site_state = "missing"
        diagnosis = "No published site exists at the requested path."
    else:
        try:
            validate_site(arguments.site)
        except PublicationBlocked:
            site_state = "invalid"
            diagnosis = "The local site exists but fails publication validation."
        else:
            site_state = "valid"
            diagnosis = "The local site passes publication validation."
    _emit(
        {
            "status": "ready",
            "package_version": __version__,
            "python_version": sys.version.split()[0],
            "dependencies": _dependency_versions(),
            "provider": "yfinance",
            "watchlist_path": str(arguments.watchlist),
            "watchlist_symbol_count": len(entries),
            "watchlist_source_status_counts": dict(sorted(statuses.items())),
            "site_path": str(arguments.site),
            "site_state": site_state,
            "site_diagnosis": diagnosis,
            "schedule": {
                "cron": SCHEDULE_CRON,
                "timezone": SCHEDULE_TIMEZONE,
                "description": SCHEDULE_DESCRIPTION,
            },
        },
        json_output=arguments.json_output,
    )
    return 0


def _decide_publication(arguments: argparse.Namespace) -> int:
    from semipulse_sentinel.publication import (
        append_github_outputs,
        decide_publication,
        read_report_snapshot,
    )

    candidate = read_report_snapshot(arguments.candidate)
    published = read_report_snapshot(arguments.published)
    decision = decide_publication(candidate, published)
    append_github_outputs(arguments.github_output, decision)
    _emit(
        {
            "status": "success",
            "decision": decision.kind,
            "has_new_data": decision.has_new_data,
            "market_as_of": decision.candidate.market_as_of.isoformat(),
            "published_market_as_of": decision.published.market_as_of.isoformat(),
        },
        json_output=arguments.json_output,
    )
    return 0


def _notify(arguments: argparse.Namespace) -> int:
    from semipulse_sentinel.notifications import (
        ReportAlert,
        SmtpSettings,
        send_report_alert,
    )

    settings = SmtpSettings.from_environment(os.environ)
    alert = ReportAlert.from_environment(os.environ)
    result = send_report_alert(settings, alert)
    _emit(result, json_output=arguments.json_output)
    return 0


def _build_source(arguments: argparse.Namespace) -> int:
    from semipulse_sentinel.source_report import build_source_report
    from semipulse_sentinel.wenxuecity_source import (
        AUTHOR_ARCHIVE_URL,
        SEED_POST_URL,
        discover_latest_source,
    )

    bundle = discover_latest_source(
        seed_url=arguments.seed_url or SEED_POST_URL,
        archive_url=arguments.archive_url or AUTHOR_ARCHIVE_URL,
        current=None,
    )
    if bundle is None:
        raise ValueError("source discovery returned no report bundle")
    result = build_source_report(
        bundle,
        arguments.output,
        lambda: datetime.now(UTC),
    )
    _emit(
        {
            "status": "success",
            "market_as_of": result.market_as_of.isoformat(),
            "source_post_id": result.source_post_id,
            "source_title": result.source_title,
            "image_count": result.image_count,
        },
        json_output=arguments.json_output,
    )
    return 0


def _validate_source(arguments: argparse.Namespace) -> int:
    from semipulse_sentinel.source_report import validate_source_site

    result = validate_source_site(arguments.site)
    _emit(
        {
            "status": "valid",
            "schema_version": result.schema_version,
            "market_as_of": result.market_as_of.isoformat(),
            "source_post_id": result.source_post_id,
            "image_count": result.image_count,
        },
        json_output=arguments.json_output,
    )
    return 0


def _decide_source_publication(arguments: argparse.Namespace) -> int:
    from semipulse_sentinel.source_publication import (
        append_source_github_outputs,
        decide_source_publication,
        read_source_publication_snapshot,
    )

    candidate = read_source_publication_snapshot(
        arguments.candidate, require_source=True
    )
    published = read_source_publication_snapshot(
        arguments.published, require_source=False
    )
    decision = decide_source_publication(candidate, published)
    append_source_github_outputs(arguments.github_output, decision)
    _emit(
        {
            "status": "success",
            "decision": decision.kind,
            "has_new_data": decision.has_new_data,
            "market_as_of": candidate.market_as_of.isoformat(),
            "source_post_id": candidate.source_post_id,
            "image_count": len(candidate.image_sha256),
        },
        json_output=arguments.json_output,
    )
    return 0


def _check_market_session(arguments: argparse.Namespace) -> int:
    from semipulse_sentinel.market_session import evaluate_market_session

    if arguments.at:
        try:
            now = datetime.fromisoformat(arguments.at)
        except ValueError as error:
            raise ValueError("--at must be an ISO timestamp") from error
    else:
        now = datetime.now(UTC)
    decision = evaluate_market_session(now)
    lines = (
        f"should_run={'true' if decision.should_run else 'false'}",
        f"session_date={decision.session_date.isoformat()}",
        f"reason={decision.reason}",
    )
    with arguments.github_output.open(
        "a", encoding="utf-8", newline="\n"
    ) as handle:
        handle.write("\n".join(lines) + "\n")
    _emit(
        {
            "status": "success",
            "should_run": decision.should_run,
            "session_date": decision.session_date.isoformat(),
            "reason": decision.reason,
        },
        json_output=arguments.json_output,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command with stable, documented process exit codes."""

    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "build":
            return _build(arguments)
        if arguments.command == "validate":
            return _validate(arguments)
        if arguments.command == "doctor":
            return _doctor(arguments)
        if arguments.command == "decide-publication":
            return _decide_publication(arguments)
        if arguments.command == "notify":
            return _notify(arguments)
        if arguments.command == "build-source":
            return _build_source(arguments)
        if arguments.command == "validate-source":
            return _validate_source(arguments)
        if arguments.command == "decide-source-publication":
            return _decide_source_publication(arguments)
        if arguments.command == "check-market-session":
            return _check_market_session(arguments)
        raise RuntimeError("unreachable command")
    except KeyboardInterrupt:
        raise
    except (
        FileNotFoundError,
        NotADirectoryError,
        PermissionError,
        ValueError,
    ) as error:
        _emit(
            {"status": "error", "category": "configuration", "message": str(error)},
            json_output=arguments.json_output,
            error=True,
        )
        return 2
    except Exception as error:
        if arguments.command == "notify":
            from semipulse_sentinel.notifications import NotificationFailed

            if isinstance(error, NotificationFailed):
                _emit(
                    {
                        "status": "error",
                        "category": "notification",
                        "message": str(error),
                    },
                    json_output=arguments.json_output,
                    error=True,
                )
                return 4
            _emit(
                {
                    "status": "error",
                    "category": "unexpected",
                    "message": f"unexpected failure ({type(error).__name__})",
                },
                json_output=arguments.json_output,
                error=True,
            )
            return 4
        from semipulse_sentinel.pipeline import BuildFailed
        from semipulse_sentinel.quality import PublicationBlocked

        if isinstance(error, PublicationBlocked):
            _emit(
                {"status": "blocked", "category": "publication", "message": str(error)},
                json_output=arguments.json_output,
                error=True,
            )
            return 3
        category = "build" if isinstance(error, BuildFailed) else "unexpected"
        _emit(
            {
                "status": "error",
                "category": category,
                "message": f"unexpected failure ({type(error).__name__})",
            },
            json_output=arguments.json_output,
            error=True,
        )
        return 4
