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

    loader.flatten_mapping(node)
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

_ACTIONS = (
    (
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
        "v7.0.0",
    ),
    (
        "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
        "v6.3.0",
    ),
    (
        "actions/configure-pages@45bfe0192ca1faeb007ade9deae92b16b8254a0d",
        "v6.0.0",
    ),
    (
        "actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9",
        "v5.0.0",
    ),
    (
        "actions/deploy-pages@cd2ce8fcbc39b97be8ca5fce6e763baed58fa128",
        "v5.0.0",
    ),
)

_EXPECTED: dict[str, object] = {
    "name": "Nightly SemiPulse report",
    "on": {
        "workflow_dispatch": {},
        "schedule": [
            {"cron": "0 18 * * *", "timezone": "America/New_York"}
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
            "steps": [
                {
                    "name": "Checkout",
                    "uses": _ACTIONS[0][0],
                    "with": {"persist-credentials": False},
                },
                {
                    "name": "Set up Python",
                    "uses": _ACTIONS[1][0],
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
                    "run": (
                        "python -m pip install --no-deps --no-build-isolation ."
                    ),
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
                    "name": "Build report",
                    "run": (
                        "python -m semipulse_sentinel build --watchlist "
                        "config/watchlist.csv --output site --json"
                    ),
                },
                {
                    "name": "Validate site",
                    "run": (
                        "python -m semipulse_sentinel validate --site site --json"
                    ),
                },
                {"name": "Configure Pages", "uses": _ACTIONS[2][0]},
                {
                    "name": "Upload Pages artifact",
                    "uses": _ACTIONS[3][0],
                    "with": {
                        "name": "github-pages",
                        "path": "site",
                        "retention-days": 1,
                    },
                },
            ],
        },
        "deploy": {
            "needs": "build",
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
                    "uses": _ACTIONS[4][0],
                }
            ],
        },
    },
}


def _fail(message: str) -> None:
    raise WorkflowVerificationError(message)


def _compare(actual: object, expected: object, location: str) -> None:
    if type(actual) is not type(expected):
        _fail(
            f"{location} has type {type(actual).__name__}; "
            f"expected {type(expected).__name__}"
        )
    if isinstance(expected, Mapping):
        actual_mapping = actual
        assert isinstance(actual_mapping, Mapping)
        if set(actual_mapping) != set(expected):
            _fail(
                f"{location} keys are {sorted(map(str, actual_mapping))}; "
                f"expected {sorted(map(str, expected))}"
            )
        for key, expected_value in expected.items():
            _compare(actual_mapping[key], expected_value, f"{location}.{key}")
        return
    if isinstance(expected, list):
        actual_sequence = actual
        assert isinstance(actual_sequence, list)
        if len(actual_sequence) != len(expected):
            _fail(
                f"{location} has {len(actual_sequence)} entries; "
                f"expected {len(expected)}"
            )
        for index, (actual_value, expected_value) in enumerate(
            zip(actual_sequence, expected, strict=True)
        ):
            _compare(actual_value, expected_value, f"{location}[{index}]")
        return
    if actual != expected:
        _fail(f"{location} is {actual!r}; expected {expected!r}")


def _require_double_quoted_on(text: str) -> None:
    node = yaml.compose(text, Loader=yaml.SafeLoader)
    if not isinstance(node, MappingNode):
        _fail("workflow root must be a mapping")
    matches = [
        key
        for key, _value in node.value
        if isinstance(key, ScalarNode) and key.value == "on"
    ]
    if len(matches) != 1 or matches[0].tag != "tag:yaml.org,2002:str":
        _fail('top-level "on" must be a string key')
    if matches[0].style != '"':
        _fail('top-level "on" must use double quotes')


def _load(text: str) -> dict[object, object]:
    try:
        if any(
            isinstance(token, (AnchorToken, AliasToken, TagToken))
            for token in yaml.scan(text)
        ):
            _fail("anchors, aliases, and explicit tags are prohibited")
        documents = list(yaml.load_all(text, Loader=_UniqueKeyLoader))
        _require_double_quoted_on(text)
    except yaml.YAMLError as error:
        raise WorkflowVerificationError(f"invalid YAML: {error}") from error
    if len(documents) != 1:
        _fail("workflow must contain exactly one YAML document")
    document = documents[0]
    if not isinstance(document, dict):
        _fail("workflow root must be a mapping")
    if True in document:
        _fail('top-level "on" was coerced to boolean true')
    return cast(dict[object, object], document)


def _uses_values(document: Mapping[object, object]) -> list[str]:
    jobs = document["jobs"]
    assert isinstance(jobs, Mapping)
    values: list[str] = []
    for job in jobs.values():
        assert isinstance(job, Mapping)
        steps = job["steps"]
        assert isinstance(steps, Sequence)
        for step in steps:
            assert isinstance(step, Mapping)
            uses = step.get("uses")
            if isinstance(uses, str):
                values.append(uses)
    return values


def _verify_security(text: str, document: Mapping[object, object]) -> None:
    lowered = text.casefold()
    for marker in ("${{ secrets.", "${{ github.token", "contents: write"):
        if marker in lowered:
            _fail(f"forbidden credential or permission marker: {marker}")
    if _uses_values(document) != [reference for reference, _version in _ACTIONS]:
        _fail("workflow actions must be first-party and pinned exactly once")

    jobs = document["jobs"]
    assert isinstance(jobs, Mapping)
    build = jobs["build"]
    assert isinstance(build, Mapping)
    steps = build["steps"]
    assert isinstance(steps, list)
    build_index = next(
        index
        for index, step in enumerate(steps)
        if isinstance(step, Mapping) and step.get("name") == "Build report"
    )
    prebuild = "\n".join(
        str(step.get("run", ""))
        for step in steps[:build_index]
        if isinstance(step, Mapping)
    ).casefold()
    for marker in ("curl ", "wget ", "http://", "https://", "yfinance"):
        if marker in prebuild:
            _fail(f"network-capable command appears before the live build: {marker}")
    if lowered.count("semipulse_sentinel build") != 1:
        _fail("workflow must contain exactly one live report build")


def _verify_action_comments(text: str) -> None:
    lines = re.findall(r"^\s*uses:\s*(\S+)\s+#\s*(v\d+\.\d+\.\d+)\s*$", text, re.M)
    if lines != list(_ACTIONS):
        _fail("every action must have its exact adjacent version comment")


def verify_workflow(path: Path) -> None:
    """Verify one workflow file against the complete audited contract."""

    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise WorkflowVerificationError(f"workflow unreadable: {error}") from error
    document = _load(text)
    _compare(document, _EXPECTED, "workflow")
    _verify_security(text, document)
    _verify_action_comments(text)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the workflow verifier as a deterministic offline CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    arguments = parser.parse_args(argv)
    try:
        verify_workflow(arguments.path)
    except WorkflowVerificationError as error:
        print(f"workflow invalid: {arguments.path}: {error}", file=sys.stderr)
        return 1
    print(f"workflow valid: {arguments.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
