"""Contract tests for the nightly GitHub Pages workflow."""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from semipulse_sentinel.charts import CHART_SPECS

WORKFLOW = Path(".github/workflows/nightly-report.yml")
VERIFIER = Path("scripts/verify_workflow.py")
EXPECTED_ACTIONS = (
    (
        "Checkout",
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
        "v7.0.0",
    ),
    (
        "Set up Python",
        "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
        "v6.3.0",
    ),
    (
        "Configure Pages",
        "actions/configure-pages@45bfe0192ca1faeb007ade9deae92b16b8254a0d",
        "v6.0.0",
    ),
    (
        "Upload Pages artifact",
        "actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9",
        "v5.0.0",
    ),
    (
        "Deploy Pages",
        "actions/deploy-pages@cd2ce8fcbc39b97be8ca5fce6e763baed58fa128",
        "v5.0.0",
    ),
    (
        "Checkout notification source",
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
        "v7.0.0",
    ),
    (
        "Set up notification Python",
        "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
        "v6.3.0",
    ),
)
EXPECTED_RUNS = {
    "Install locked dependencies": (
        "python -m pip install --require-hashes -r requirements.lock"
    ),
    "Install project": "python -m pip install --no-deps --no-build-isolation .",
    "Verify workflow": (
        "python scripts/verify_workflow.py .github/workflows/nightly-report.yml"
    ),
    "Run offline tests": "python -m pytest -q",
    "Build report": (
        "python -m semipulse_sentinel build --watchlist config/watchlist.csv "
        "--output candidate-site --json"
    ),
    "Validate site": (
        "python -m semipulse_sentinel validate --site candidate-site --json"
    ),
    "Fetch published report": (
        "curl --fail --show-error --silent --location --retry 3 "
        "--output published-report.json "
        '"https://skydiver1118.github.io/semipulse-sentinel/'
        'report.json?run_id=${GITHUB_RUN_ID}"'
    ),
    "Decide publication": (
        "python -m semipulse_sentinel decide-publication "
        "--candidate candidate-site/report.json "
        "--published published-report.json "
        '--github-output "$GITHUB_OUTPUT" --json'
    ),
}


def _load_workflow() -> dict[str, Any]:
    return cast(
        dict[str, Any], yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    )


def _build_steps(document: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], document["jobs"]["build"]["steps"])


def _step(steps: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(item for item in steps if item["name"] == name)


def _replace_once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def _replace_first(text: str, old: str, new: str) -> str:
    assert old in text, old
    return text.replace(old, new, 1)


def _run_verifier(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFIER), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )


def _mutation_unquoted_on(text: str) -> str:
    return _replace_once(text, '"on":', "on:")


def _mutation_mutable_action(text: str) -> str:
    return _replace_first(
        text,
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0",
        "actions/checkout@v7 # v7.0.0",
    )


def _mutation_extra_permission(text: str) -> str:
    return _replace_once(
        text,
        "permissions:\n  contents: read",
        "permissions:\n  contents: read\n  issues: write",
    )


def _mutation_build_before_test(text: str) -> str:
    tests = "      - name: Run offline tests\n        run: python -m pytest -q"
    build = (
        "      - name: Build report\n"
        "        run: >-\n"
        "          python -m semipulse_sentinel build --watchlist "
        "config/watchlist.csv\n"
        "          --output candidate-site --json"
    )
    return _replace_once(text, f"{tests}\n\n{build}", f"{build}\n\n{tests}")


def _mutation_configure_enablement(text: str) -> str:
    action = (
        "        uses: actions/configure-pages@"
        "45bfe0192ca1faeb007ade9deae92b16b8254a0d # v6.0.0"
    )
    return _replace_once(
        text,
        action,
        f"{action}\n        with:\n          enablement: true",
    )


def _mutation_setup_cache(text: str) -> str:
    return _replace_first(
        text,
        '          python-version: "3.11.15"',
        '          python-version: "3.11.15"\n          cache: pip',
    )


def _mutation_secret(text: str) -> str:
    return _replace_once(
        text,
        '  TZ: America/New_York',
        '  TZ: America/New_York\n  PROVIDER_TOKEN: "${{ secrets.PROVIDER_TOKEN }}"',
    )


def _mutation_third_party_action(text: str) -> str:
    return _replace_first(text, "actions/checkout@", "example/checkout@")


def _mutation_prebuild_network(text: str) -> str:
    marker = "      - name: Verify workflow"
    injected = (
        "      - name: Fetch remote input\n"
        "        run: curl https://example.invalid/data\n\n"
        f"{marker}"
    )
    return _replace_once(text, marker, injected)


def _mutation_inline_merge_key(text: str) -> str:
    return _replace_once(
        text,
        "permissions:\n  contents: read",
        "permissions:\n  <<: {contents: read}",
    )


def _mutation_flow_mapping_merge_key(text: str) -> str:
    return _replace_once(
        text,
        "permissions:\n  contents: read",
        "permissions: {<<: {contents: read}}",
    )


def _mutation_merge_at_position(
    text: str, position: str, *, block_value: bool
) -> str:
    if block_value:
        probes = {
            "root": "<<:\n  merge_probe: true\n",
            "on": "  <<:\n    merge_probe: true\n",
            "jobs": "  <<:\n    merge_probe: true\n",
            "job": "    <<:\n      merge_probe: true\n",
            "permissions": "  <<:\n    merge_probe: true\n",
            "step": "      - <<:\n          merge_probe: true\n        name: Checkout",
            "with": "          <<:\n            merge_probe: true\n",
            "env": "  <<:\n    merge_probe: true\n",
        }
    else:
        probes = {
            "root": "<<: {merge_probe: true}\n",
            "on": "  <<: {merge_probe: true}\n",
            "jobs": "  <<: {merge_probe: true}\n",
            "job": "    <<: {merge_probe: true}\n",
            "permissions": "  <<: {merge_probe: true}\n",
            "step": "      - <<: {merge_probe: true}\n        name: Checkout",
            "with": "          <<: {merge_probe: true}\n",
            "env": "  <<: {merge_probe: true}\n",
        }

    replacements = {
        "root": (
            "name: Nightly SemiPulse report",
            f"{probes[position]}name: Nightly SemiPulse report",
        ),
        "on": (
            '"on":\n  workflow_dispatch: {}',
            f'"on":\n{probes[position]}  workflow_dispatch: {{}}',
        ),
        "jobs": (
            "jobs:\n  build:",
            f"jobs:\n{probes[position]}  build:",
        ),
        "job": (
            "    timeout-minutes: 30",
            f"{probes[position]}    timeout-minutes: 30",
        ),
        "permissions": (
            "permissions:\n  contents: read",
            f"permissions:\n{probes[position]}  contents: read",
        ),
        "step": (
            "      - name: Checkout",
            probes[position],
        ),
        "with": (
            "        with:\n          persist-credentials: false",
            f"        with:\n{probes[position]}          persist-credentials: false",
        ),
        "env": (
            'env:\n  PYTHONHASHSEED: "0"',
            f'env:\n{probes[position]}  PYTHONHASHSEED: "0"',
        ),
    }
    old, new = replacements[position]
    replace = _replace_first if position in {"step", "with"} else _replace_once
    return replace(text, old, new)


def _mutation_nested_alias(text: str) -> str:
    return _replace_first(
        text,
        "        with:\n          persist-credentials: false",
        (
            "        with: &checkout_options\n"
            "          persist-credentials: false\n"
            "        env:\n"
            "          COPIED_OPTIONS: *checkout_options"
        ),
    )


def _mutation_explicit_tag(text: str) -> str:
    return _replace_first(
        text,
        '          python-version: "3.11.15"',
        '          python-version: !!str "3.11.15"',
    )


def test_workflow_is_valid_yaml_with_a_string_on_key() -> None:
    document = _load_workflow()

    assert "on" in document
    assert True not in document


def test_workflow_has_exact_top_level_contract() -> None:
    document = _load_workflow()

    assert set(document) == {
        "name",
        "on",
        "permissions",
        "concurrency",
        "env",
        "jobs",
    }
    assert document["name"] == "Nightly SemiPulse report"
    assert document["on"] == {
        "workflow_dispatch": {},
        "schedule": [
            {"cron": "0 18 * * 1-5", "timezone": "America/New_York"}
        ],
    }
    assert document["permissions"] == {"contents": "read"}
    assert document["concurrency"] == {
        "group": "semipulse-pages",
        "cancel-in-progress": True,
    }
    assert document["env"] == {
        "PYTHONHASHSEED": "0",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
        "MPLBACKEND": "Agg",
        "TZ": "America/New_York",
    }


def test_jobs_have_exact_runners_timeouts_permissions_and_deploy_gate() -> None:
    jobs = _load_workflow()["jobs"]
    build = jobs["build"]
    deploy = jobs["deploy"]
    notify = jobs["notify"]

    assert set(jobs) == {"build", "deploy", "notify"}
    assert set(build) == {
        "runs-on",
        "timeout-minutes",
        "permissions",
        "outputs",
        "steps",
    }
    assert build["runs-on"] == "ubuntu-24.04"
    assert build["timeout-minutes"] == 30
    assert build["permissions"] == {"contents": "read", "pages": "read"}
    assert build["outputs"] == {
        "has_new_data": "${{ steps.publication.outputs.has_new_data }}",
        "market_as_of": "${{ steps.publication.outputs.market_as_of }}",
        "regime": "${{ steps.publication.outputs.regime }}",
        "confidence": "${{ steps.publication.outputs.confidence }}",
        "coverage": "${{ steps.publication.outputs.coverage }}",
    }
    assert set(deploy) == {
        "needs",
        "if",
        "runs-on",
        "timeout-minutes",
        "permissions",
        "environment",
        "steps",
    }
    assert deploy["needs"] == "build"
    assert deploy["if"] == "needs.build.outputs.has_new_data == 'true'"
    assert deploy["runs-on"] == "ubuntu-24.04"
    assert deploy["timeout-minutes"] == 10
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}
    assert deploy["environment"] == {
        "name": "github-pages",
        "url": "${{ steps.deployment.outputs.page_url }}",
    }
    assert notify["needs"] == ["build", "deploy"]
    assert notify["if"] == (
        "needs.build.outputs.has_new_data == 'true' && "
        "needs.deploy.result == 'success'"
    )
    assert notify["runs-on"] == "ubuntu-24.04"
    assert notify["timeout-minutes"] == 5
    assert notify["permissions"] == {"contents": "read"}
    assert notify["env"] == {"PYTHONPATH": "src"}


def test_build_steps_have_exact_order_commands_and_artifact() -> None:
    steps = _build_steps(_load_workflow())

    assert [item["name"] for item in steps] == [
        "Checkout",
        "Set up Python",
        "Install locked dependencies",
        "Install project",
        "Verify workflow",
        "Run offline tests",
        "Build report",
        "Validate site",
        "Fetch published report",
        "Decide publication",
        "Configure Pages",
        "Upload Pages artifact",
    ]
    assert {
        item["name"]: item["run"] for item in steps if "run" in item
    } == EXPECTED_RUNS
    assert _step(steps, "Checkout")["with"] == {"persist-credentials": False}
    assert _step(steps, "Set up Python")["with"] == {
        "python-version": "3.11.15"
    }
    assert _step(steps, "Upload Pages artifact")["with"] == {
        "name": "github-pages",
        "path": "candidate-site",
        "retention-days": 1,
    }
    assert _step(steps, "Decide publication")["id"] == "publication"
    for name in ("Configure Pages", "Upload Pages artifact"):
        assert _step(steps, name)["if"] == (
            "steps.publication.outputs.has_new_data == 'true'"
        )


def test_all_actions_use_exact_sha_and_adjacent_version_comment() -> None:
    document = _load_workflow()
    build_steps = _build_steps(document)
    deploy_steps = document["jobs"]["deploy"]["steps"]
    notify_steps = document["jobs"]["notify"]["steps"]
    actual = [
        (item["name"], item["uses"])
        for item in [*build_steps, *deploy_steps, *notify_steps]
        if "uses" in item
    ]

    assert actual == [
        (name, reference) for name, reference, _version in EXPECTED_ACTIONS
    ]
    raw = WORKFLOW.read_text(encoding="utf-8")
    for _name, reference, version in EXPECTED_ACTIONS:
        assert f"uses: {reference} # {version}" in raw


def test_deploy_has_one_exact_deployment_step() -> None:
    steps = _load_workflow()["jobs"]["deploy"]["steps"]

    assert steps == [
        {
            "name": "Deploy Pages",
            "id": "deployment",
                "uses": EXPECTED_ACTIONS[4][1],
        }
    ]


def test_notify_job_has_exact_source_setup_and_secret_boundary() -> None:
    steps = _load_workflow()["jobs"]["notify"]["steps"]

    assert [item["name"] for item in steps] == [
        "Checkout notification source",
        "Set up notification Python",
        "Send report email",
    ]
    assert steps[0]["with"] == {"persist-credentials": False}
    assert steps[1]["with"] == {"python-version": "3.11.15"}
    send = steps[2]
    assert send["run"] == "python -m semipulse_sentinel notify --json"
    assert send["env"] == {
        "SEMIPULSE_SMTP_HOST": "${{ secrets.SEMIPULSE_SMTP_HOST }}",
        "SEMIPULSE_SMTP_PORT": "${{ secrets.SEMIPULSE_SMTP_PORT }}",
        "SEMIPULSE_SMTP_USER": "${{ secrets.SEMIPULSE_SMTP_USER }}",
        "SEMIPULSE_SMTP_PASSWORD": "${{ secrets.SEMIPULSE_SMTP_PASSWORD }}",
        "SEMIPULSE_EMAIL_FROM": "${{ secrets.SEMIPULSE_EMAIL_FROM }}",
        "SEMIPULSE_EMAIL_TO": "${{ secrets.SEMIPULSE_EMAIL_TO }}",
        "SEMIPULSE_MARKET_AS_OF": "${{ needs.build.outputs.market_as_of }}",
        "SEMIPULSE_REGIME": "${{ needs.build.outputs.regime }}",
        "SEMIPULSE_CONFIDENCE": "${{ needs.build.outputs.confidence }}",
        "SEMIPULSE_COVERAGE": "${{ needs.build.outputs.coverage }}",
        "SEMIPULSE_DASHBOARD_URL": (
            "https://skydiver1118.github.io/semipulse-sentinel/"
        ),
    }


def test_workflow_contains_only_notification_secrets_and_audited_networking() -> None:
    raw = WORKFLOW.read_text(encoding="utf-8").casefold()
    build_steps = _build_steps(_load_workflow())
    build_index = next(
        index
        for index, item in enumerate(build_steps)
        if item["name"] == "Build report"
    )
    prebuild_runs = "\n".join(
        item.get("run", "") for item in build_steps[:build_index]
    ).casefold()

    assert set(re.findall(r"\$\{\{ secrets\.([a-z0-9_]+) \}\}", raw)) == {
        "semipulse_smtp_host",
        "semipulse_smtp_port",
        "semipulse_smtp_user",
        "semipulse_smtp_password",
        "semipulse_email_from",
        "semipulse_email_to",
    }
    assert "github.token" not in raw
    assert "cache:" not in raw
    assert "enablement:" not in raw
    assert all(
        marker not in prebuild_runs
        for marker in ("curl ", "wget ", "http://", "https://", "yfinance")
    )
    assert raw.count("semipulse_sentinel build") == 1
    assert raw.count("semipulse_sentinel decide-publication") == 1
    assert raw.count("semipulse_sentinel notify") == 1


def test_verifier_accepts_the_repository_workflow() -> None:
    result = _run_verifier(WORKFLOW)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "mutation",
    [
        _mutation_unquoted_on,
        _mutation_mutable_action,
        _mutation_extra_permission,
        _mutation_build_before_test,
        _mutation_configure_enablement,
        _mutation_setup_cache,
        _mutation_secret,
        _mutation_third_party_action,
        _mutation_prebuild_network,
        _mutation_inline_merge_key,
    ],
    ids=lambda function: cast(Callable[[str], str], function).__name__.removeprefix(
        "_mutation_"
    ),
)
def test_verifier_rejects_security_and_order_mutations(
    tmp_path: Path, mutation: Callable[[str], str]
) -> None:
    candidate = tmp_path / "nightly-report.yml"
    candidate.write_text(
        mutation(WORKFLOW.read_text(encoding="utf-8")), encoding="utf-8"
    )

    result = _run_verifier(candidate)

    assert result.returncode != 0
    assert "workflow invalid" in result.stderr.lower()


@pytest.mark.parametrize(
    "position",
    ["root", "on", "jobs", "job", "permissions", "step", "with", "env"],
)
@pytest.mark.parametrize(
    "block_value", [False, True], ids=["flow-value", "block-value"]
)
def test_verifier_rejects_merge_keys_at_every_mapping_position(
    tmp_path: Path, position: str, block_value: bool
) -> None:
    candidate = tmp_path / f"merge-{position}-{block_value}.yml"
    candidate.write_text(
        _mutation_merge_at_position(
            WORKFLOW.read_text(encoding="utf-8"),
            position,
            block_value=block_value,
        ),
        encoding="utf-8",
    )

    result = _run_verifier(candidate)

    assert result.returncode != 0
    assert "merge keys are prohibited" in result.stderr.lower()


def test_verifier_rejects_merge_key_inside_flow_mapping(tmp_path: Path) -> None:
    candidate = tmp_path / "flow-mapping-merge.yml"
    candidate.write_text(
        _mutation_flow_mapping_merge_key(WORKFLOW.read_text(encoding="utf-8")),
        encoding="utf-8",
    )

    result = _run_verifier(candidate)

    assert result.returncode != 0
    assert "merge keys are prohibited" in result.stderr.lower()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (_mutation_nested_alias, "anchors, aliases, and explicit tags are prohibited"),
        (_mutation_explicit_tag, "anchors, aliases, and explicit tags are prohibited"),
    ],
    ids=["nested-alias", "explicit-tag"],
)
def test_verifier_rejects_nested_aliases_and_explicit_tags(
    tmp_path: Path, mutation: Callable[[str], str], message: str
) -> None:
    candidate = tmp_path / "special-yaml.yml"
    candidate.write_text(
        mutation(WORKFLOW.read_text(encoding="utf-8")), encoding="utf-8"
    )

    result = _run_verifier(candidate)

    assert result.returncode != 0
    assert message in result.stderr.lower()


@pytest.mark.parametrize(
    "invalid_yaml",
    [
        '"on": [',
        '---\n"on": {}\n---\n"on": {}\n',
        '"on": &trigger {}\ncopy: *trigger\n',
        '"on": {}\npermissions: {}\npermissions: {contents: read}\n',
    ],
)
def test_verifier_rejects_ambiguous_or_invalid_yaml(
    tmp_path: Path, invalid_yaml: str
) -> None:
    candidate = tmp_path / "invalid.yml"
    candidate.write_text(invalid_yaml, encoding="utf-8")

    result = _run_verifier(candidate)

    assert result.returncode != 0
    assert "workflow invalid" in result.stderr.lower()


def test_pyyaml_is_declared_and_hashed_in_the_lock() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dev = [
        item.casefold()
        for item in project["project"]["optional-dependencies"]["dev"]
    ]
    lock = Path("requirements.lock").read_text(encoding="utf-8").casefold()

    assert "pyyaml>=6.0" in dev
    assert "pyyaml==" in lock
    assert "# via semipulse-sentinel (pyproject.toml)" in lock


def test_public_documentation_covers_identity_methodology_and_operations() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    methodology = Path("docs/methodology.md").read_text(encoding="utf-8")
    operations = Path("docs/operations.md").read_text(encoding="utf-8")
    license_text = Path("LICENSE").read_text(encoding="utf-8")
    methodology_flat = " ".join(methodology.split())
    operations_flat = " ".join(operations.split())

    assert "skydiver1118/semipulse-sentinel" in readme
    assert "https://skydiver1118.github.io/semipulse-sentinel/" in readme
    assert "https://skydiver1118.github.io/semipulse-sentinel/report.json" in readme
    assert "recovered_inference" in readme
    assert "docs/methodology.md" in readme
    assert "docs/operations.md" in readme
    assert "Monday through Friday" in readme
    assert "1118xmb@gmail.com" in readme
    assert all(spec.title in methodology for spec in CHART_SPECS)
    assert all(
        phrase in methodology_flat
        for phrase in (
            "absolute trend: 25%",
            "relative leadership: 20%",
            "breadth and participation: 25%",
            "momentum distribution: 15%",
            "volatility/drawdown risk: 15%",
            "2 * vote sum / fixed input count",
            "absolute trend: 25% (6 inputs)",
            "relative leadership: 20% (8 inputs)",
            "breadth and participation: 25% (8 inputs)",
            "momentum distribution: 15% (4 inputs)",
            "volatility/drawdown risk: 15% (4 inputs)",
            "no duplicate symbol/date rows",
            "exactly eight validated artifacts",
            "three attempts",
            "63-session return horizon (64 common observations)",
            "expected-session lag is unknown or greater than one",
            "current",
            "delayed",
            "stale",
            "70%",
            "yfinance==1.5.1",
            "Research only",
            "personalized sizing",
        )
    )
    assert all(
        phrase in operations_flat
        for phrase in (
            "6:00 PM America/New_York",
            "Monday through Friday",
            "0 18 * * 1-5",
            "daylight saving time",
            "22:00 UTC",
            "23:00 UTC",
            "best effort",
            "60 days",
            "gh workflow enable nightly-report.yml",
            "workflow_dispatch",
            "out-of-band",
            "last successful Page",
            "no new market data",
            "1118xmb@gmail.com",
            "SEMIPULSE_SMTP_PASSWORD",
            "Exit code 0",
            "Exit code 2",
            "Exit code 3",
            "Exit code 4",
            "No secrets",
        )
    )
    assert "forks" in operations_flat.casefold()
    assert "MIT License" in license_text
    assert "Copyright (c) 2026 skydiver1118" in license_text
