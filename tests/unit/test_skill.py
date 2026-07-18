"""Contract tests for the installable SemiPulse Sentinel Codex skill."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skill" / "semipulse-sentinel"
EXPECTED_SKILL_FILES = {
    "SKILL.md",
    "agents/openai.yaml",
    "references/operations.md",
}
EXPECTED_DESCRIPTION = (
    "Use when a user asks for SemiPulse, a semi monitor, the semiconductor "
    "nightly report, a refresh of the eight charts, or interpretation of the "
    "semiconductor dashboard."
)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_skill_package_has_exact_thin_tree() -> None:
    files = {
        path.relative_to(SKILL_ROOT).as_posix()
        for path in SKILL_ROOT.rglob("*")
        if path.is_file()
    }
    assert files == EXPECTED_SKILL_FILES


def test_skill_frontmatter_and_body_are_thin_and_named() -> None:
    data = _read("skill/semipulse-sentinel/SKILL.md")
    expected_frontmatter = (
        "---\n"
        "name: semipulse-sentinel\n"
        f"description: {EXPECTED_DESCRIPTION}\n"
        "---\n"
    )
    assert data.startswith(expected_frontmatter)
    assert data.count("\n---\n") == 1
    assert len(data.split()) < 500
    assert "SemiPulse Sentinel" in data
    assert "python -m semipulse_sentinel doctor --json" in data
    assert "report.json" in data
    assert "gh workflow run nightly-report.yml" in data


def test_skill_guidance_is_fail_closed_and_research_only() -> None:
    data = _read("skill/semipulse-sentinel/SKILL.md")
    required = (
        "market_as_of",
        "freshness",
        "coverage",
        "regime",
        "confidence",
        "supports",
        "challenges",
        "limitations",
        "Never infer chart meaning from SVG pixels",
        "Do not dispatch unless",
        "Honor conditions attached to refresh authority",
        "not proof of staleness",
        "Keep freshness and coverage separate",
        "Never describe stale data as current or partial coverage as broad or complete",
        "research only",
        "Never place orders",
    )
    for phrase in required:
        assert phrase in data


def test_operations_reference_has_canonical_interfaces() -> None:
    data = _read("skill/semipulse-sentinel/references/operations.md")
    required = (
        "https://github.com/skydiver1118/semipulse-sentinel",
        "https://skydiver1118.github.io/semipulse-sentinel/",
        "https://skydiver1118.github.io/semipulse-sentinel/report.json",
        "python -m semipulse_sentinel doctor --json",
        "gh workflow run nightly-report.yml --repo skydiver1118/semipulse-sentinel",
        "gh run list --repo skydiver1118/semipulse-sentinel",
        "main",
        "0 18 * * *",
        "America/New_York",
        "market_as_of",
        "freshness.state",
        "freshness.evaluated_at",
        "coverage.coverage_ratio",
        "coverage.missing_required",
        "executive_summary.regime",
        "executive_summary.confidence",
        "executive_summary.supports",
        "executive_summary.challenges",
        "executive_summary.what_would_change_the_view",
        "charts[]",
        "flattened",
        "query time",
        "16:15",
        "previous weekday",
        "exchange-holiday calendar",
        "below 0.70",
        "unpublishable",
        "70% to below 90%",
        "limitations",
        "risk_warning",
    )
    for phrase in required:
        assert phrase in data
    assert "executive_summary.change_triggers" not in data
    assert "charts[].insight" not in data


def test_openai_interface_is_exact_and_uses_skill_token() -> None:
    path = SKILL_ROOT / "agents" / "openai.yaml"
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert parsed == {
        "interface": {
            "display_name": "SemiPulse Sentinel",
            "short_description": "Inspect nightly semiconductor market reports",
            "default_prompt": (
                "Use $semipulse-sentinel to summarize the latest semiconductor "
                "report and assess whether it needs a refresh."
            ),
        }
    }


def test_skill_sources_are_utf8_without_bom_or_local_machine_paths() -> None:
    forbidden = re.compile(
        r"(?i)(C:\\\\Users\\\\|/Users/|/home/|BEGIN [A-Z ]*PRIVATE KEY|ghp_[A-Za-z0-9])"
    )
    for relative in EXPECTED_SKILL_FILES:
        raw = (SKILL_ROOT / relative).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8")
        assert forbidden.search(text) is None


def test_installer_sources_are_utf8_and_use_literal_path_guards() -> None:
    for relative in ("scripts/install-agent.ps1", "scripts/uninstall-agent.ps1"):
        raw = (ROOT / relative).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8")
        assert "Set-StrictMode -Version Latest" in text
        assert "$ErrorActionPreference = 'Stop'" in text
        assert "-LiteralPath" in text
        assert "ReparsePoint" in text
        assert "semipulse-sentinel" in text
