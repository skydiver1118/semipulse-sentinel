"""Structured, network-safe command-line boundary."""

from __future__ import annotations

import argparse
import json
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
    return parser


def _emit(
    payload: dict[str, object], *, json_output: bool, error: bool = False
) -> None:
    stream = sys.stderr if error else sys.stdout
    if json_output:
        print(
            json.dumps(
                payload,
                ensure_ascii=False,
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
