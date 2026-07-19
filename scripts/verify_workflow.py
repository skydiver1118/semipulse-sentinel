"""Fail-closed structural verification for the GitHub Pages workflow."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import yaml  # type: ignore[import-untyped]
from yaml.constructor import ConstructorError  # type: ignore[import-untyped]
from yaml.nodes import MappingNode, ScalarNode  # type: ignore[import-untyped]
from yaml.tokens import (  # type: ignore[import-untyped]
    AliasToken,
    AnchorToken,
    TagToken,
)


class WorkflowVerificationError(ValueError):
    """Raised when the workflow differs from the audited deployment contract."""


class _UniqueKeyLoader(yaml.SafeLoader):  # type: ignore[misc]
    """Safe YAML loader that rejects duplicate and merge keys."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: MappingNode, deep: bool = False
) -> dict[object, object]:
    for key_node, _value_node in node.value:
        if (
            isinstance(key_node, ScalarNode)
            and key_node.tag == "tag:yaml.org,2002:merge"
        ):
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "merge keys are prohibited",
                key_node.start_mark,
            )
    output: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in output
        except TypeError as error:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "mapping keys must be hashable",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key!r}",
                key_node.start_mark,
            )
        output[key] = loader.construct_object(value_node, deep=deep)
    return output


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)

_CHECKOUT = "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
_SETUP = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
_CONFIGURE = (
    "actions/configure-pages@45bfe0192ca1faeb007ade9deae92b16b8254a0d"
)
_UPLOAD = (
    "actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9"
)
_DEPLOY = "actions/deploy-pages@cd2ce8fcbc39b97be8ca5fce6e763baed58fa128"
_SCAN_IF = (
    "steps.session.outputs.should_run == 'true' || "
    "github.event_name == 'workflow_dispatch'"
)

_EXPECTED: dict[str, object] = {
    "name": "Nightly SemiPulse report",
    "on": {
        "workflow_dispatch": {},
        "schedule": [
            {"cron": "20 18 * * 1-5", "timezone": "America/New_York"}
        ],
    },
    "permissions": {"contents": "read"},
    "concurrency": {"group": "semipulse-pages", "cancel-in-progress": True},
    "env": {
        "PYTHONHASHSEED": "0",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
        "MPLBACKEND": "Agg",
        "TZ": "America/New_York",
    },
    "jobs": {
        "build": {
            "runs-on": "ubuntu-24.04",
            "timeout-minutes": 30,
            "permissions": {"contents": "read", "pages": "read"},
            "outputs": {
                "has_new_data": "${{ steps.publication.outputs.has_new_data }}",
                "market_as_of": "${{ steps.publication.outputs.market_as_of }}",
                "regime": "${{ steps.publication.outputs.regime }}",
                "confidence": "${{ steps.publication.outputs.confidence }}",
                "coverage": "${{ steps.publication.outputs.coverage }}",
            },
            "steps": [
                {
                    "name": "Checkout",
                    "uses": _CHECKOUT,
                    "with": {"persist-credentials": False},
                },
                {
                    "name": "Set up Python",
                    "uses": _SETUP,
                    "with": {"python-version": "3.11.15"},
                },
                {
                    "name": "Install locked dependencies",
                    "run": (
                        "python -m pip install --require-hashes "
                        "-r requirements.lock"
                    ),
                },
                {
                    "name": "Install project",
                    "run": "python -m pip install --no-deps --no-build-isolation .",
                },
                {
                    "name": "Verify workflow",
                    "run": (
                        "python scripts/verify_workflow.py "
                        ".github/workflows/nightly-report.yml"
                    ),
                },
                {"name": "Run offline tests", "run": "python -m pytest -q"},
                {
                    "name": "Check market session",
                    "id": "session",
                    "run": (
                        "python -m semipulse_sentinel check-market-session "
                        '--github-output "$GITHUB_OUTPUT" --json'
                    ),
                },
                {
                    "name": "Build report",
                    "if": _SCAN_IF,
                    "run": (
                        "python -m semipulse_sentinel build --watchlist "
                        "config/watchlist.csv "
                        "--output candidate-site --json"
                    ),
                },
                {
                    "name": "Validate site",
                    "if": _SCAN_IF,
                    "run": (
                        "python -m semipulse_sentinel validate "
                        "--site candidate-site --json"
                    ),
                },
                {
                    "name": "Fetch published report",
                    "if": _SCAN_IF,
                    "run": (
                        "curl --fail --show-error --silent --location --retry 3 "
                        "--output published-report.json "
                        '"https://skydiver1118.github.io/semipulse-sentinel/'
                        'report.json?run_id=${GITHUB_RUN_ID}"'
                    ),
                },
                {
                    "name": "Decide publication",
                    "id": "publication",
                    "if": _SCAN_IF,
                    "run": (
                        "python -m semipulse_sentinel decide-publication "
                        "--candidate candidate-site/report.json "
                        "--published published-report.json "
                        '--github-output "$GITHUB_OUTPUT" --json'
                    ),
                },
                {
                    "name": "Configure Pages",
                    "if": "steps.publication.outputs.has_new_data == 'true'",
                    "uses": _CONFIGURE,
                },
                {
                    "name": "Upload Pages artifact",
                    "if": "steps.publication.outputs.has_new_data == 'true'",
                    "uses": _UPLOAD,
                    "with": {
                        "name": "github-pages",
                        "path": "candidate-site",
                        "retention-days": 1,
                    },
                },
            ],
        },
        "deploy": {
            "needs": "build",
            "if": "needs.build.outputs.has_new_data == 'true'",
            "runs-on": "ubuntu-24.04",
            "timeout-minutes": 10,
            "permissions": {"pages": "write", "id-token": "write"},
            "environment": {
                "name": "github-pages",
                "url": "${{ steps.deployment.outputs.page_url }}",
            },
            "steps": [
                {
                    "name": "Deploy Pages",
                    "id": "deployment",
                    "uses": _DEPLOY,
                }
            ],
        },
        "notify": {
            "needs": ["build", "deploy"],
            "if": (
                "needs.build.outputs.has_new_data == 'true' && "
                "needs.deploy.result == 'success'"
            ),
            "runs-on": "ubuntu-24.04",
            "timeout-minutes": 5,
            "permissions": {"contents": "read"},
            "env": {"PYTHONPATH": "src"},
            "steps": [
                {
                    "name": "Checkout notification source",
                    "uses": _CHECKOUT,
                    "with": {"persist-credentials": False},
                },
                {
                    "name": "Set up notification Python",
                    "uses": _SETUP,
                    "with": {"python-version": "3.11.15"},
                },
                {
                    "name": "Send report email",
                    "env": {
                        "SEMIPULSE_SMTP_HOST": (
                            "${{ secrets.SEMIPULSE_SMTP_HOST }}"
                        ),
                        "SEMIPULSE_SMTP_PORT": (
                            "${{ secrets.SEMIPULSE_SMTP_PORT }}"
                        ),
                        "SEMIPULSE_SMTP_USER": (
                            "${{ secrets.SEMIPULSE_SMTP_USER }}"
                        ),
                        "SEMIPULSE_SMTP_PASSWORD": (
                            "${{ secrets.SEMIPULSE_SMTP_PASSWORD }}"
                        ),
                        "SEMIPULSE_EMAIL_FROM": (
                            "${{ secrets.SEMIPULSE_EMAIL_FROM }}"
                        ),
                        "SEMIPULSE_MARKET_AS_OF": (
                            "${{ needs.build.outputs.market_as_of }}"
                        ),
                        "SEMIPULSE_REGIME": (
                            "${{ needs.build.outputs.regime }}"
                        ),
                        "SEMIPULSE_CONFIDENCE": (
                            "${{ needs.build.outputs.confidence }}"
                        ),
                        "SEMIPULSE_COVERAGE": (
                            "${{ needs.build.outputs.coverage }}"
                        ),
                        "SEMIPULSE_DASHBOARD_URL": (
                            "https://skydiver1118.github.io/"
                            "semipulse-sentinel/"
                        ),
                    },
                    "run": "python -m semipulse_sentinel notify --json",
                },
            ],
        },
    },
}

_ACTION_COMMENTS = {
    f"uses: {_CHECKOUT} # v7.0.0": 2,
    f"uses: {_SETUP} # v6.3.0": 2,
    f"uses: {_CONFIGURE} # v6.0.0": 1,
    f"uses: {_UPLOAD} # v5.0.0": 1,
    f"uses: {_DEPLOY} # v5.0.0": 1,
}
_SECRET_NAMES = {
    "SEMIPULSE_SMTP_HOST",
    "SEMIPULSE_SMTP_PORT",
    "SEMIPULSE_SMTP_USER",
    "SEMIPULSE_SMTP_PASSWORD",
    "SEMIPULSE_EMAIL_FROM",
}
_FORBIDDEN_SOURCE_MARKERS = {
    "build-source",
    "validate-source",
    "decide-source-publication",
    "notify-source",
    "SEMIPULSE_EMAIL_TO",
    "SEMIPULSE_IMAGE_COUNT",
}


def _load(text: str) -> Mapping[str, object]:
    for token in yaml.scan(text):
        if isinstance(token, (AliasToken, AnchorToken, TagToken)):
            raise WorkflowVerificationError(
                "anchors, aliases, and explicit tags are prohibited"
            )
    loader = _UniqueKeyLoader(text)
    try:
        document = loader.get_single_data()
    finally:
        loader.dispose()
    if not isinstance(document, dict) or not all(
        isinstance(key, str) for key in document
    ):
        raise WorkflowVerificationError("workflow root must be a string-key mapping")
    return cast(Mapping[str, object], document)


def verify(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    forbidden = sorted(
        {
            marker
            for marker in _FORBIDDEN_SOURCE_MARKERS
            if marker in text
        }
        | set(re.findall(r"\bSEMIPULSE_SOURCE_[A-Z0-9_]+\b", text))
    )
    if forbidden:
        raise WorkflowVerificationError(
            "production workflow contains forbidden source-copy markers: "
            + ", ".join(forbidden)
        )
    document = _load(text)
    jobs = document.get("jobs")
    if not isinstance(jobs, Mapping) or list(jobs) != [
        "build",
        "deploy",
        "notify",
    ]:
        raise WorkflowVerificationError(
            "workflow jobs must be ordered build, deploy, notify"
        )
    if document != _EXPECTED:
        raise WorkflowVerificationError(
            "workflow differs from the exact audited daily-report contract"
        )
    for marker, count in _ACTION_COMMENTS.items():
        if text.count(marker) != count:
            raise WorkflowVerificationError(
                "action pins require exact adjacent version comments"
            )
    secrets = set(
        re.findall(r"\$\{\{ secrets\.([A-Za-z0-9_]+) \}\}", text)
    )
    if secrets != _SECRET_NAMES:
        raise WorkflowVerificationError(
            "workflow must use only the exact daily-alert secrets"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        verify(arguments.workflow)
    except (OSError, UnicodeError, yaml.YAMLError, WorkflowVerificationError) as error:
        print(f"workflow invalid: {error}", file=sys.stderr)
        return 1
    print("workflow valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
