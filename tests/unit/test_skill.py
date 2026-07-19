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
    "Use when a user asks for SemiPulse, the semiconductor source-chart "
    "report, a Wenxuecity chart refresh, the eight copied charts, or the "
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
    assert "python -m semipulse_sentinel validate-source" in data
    assert "report.json" in data
    assert "gh workflow run nightly-report.yml" in data


def test_skill_guidance_is_fail_closed_and_research_only() -> None:
    data = _read("skill/semipulse-sentinel/SKILL.md")
    required = (
        "market_as_of",
        "semipulse-wenxuecity-source-v1",
        "source.post_id",
        "source.url",
        "source.published_at",
        "source.edited_at",
        "images[]",
        "sha256",
        "copied_unchanged",
        "risk_disclosure",
        "Do not recreate",
        "Do not dispatch unless",
        "Honor conditions attached to refresh authority",
        "not proof of new source data",
        "last successful report",
        "sends no email",
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
        "python -m semipulse_sentinel validate-source",
        "gh workflow run nightly-report.yml --repo skydiver1118/semipulse-sentinel",
        "gh run list --repo skydiver1118/semipulse-sentinel",
        "main",
        "20 18 * * 1-5",
        "America/New_York",
        "Monday through Friday",
        "no new source data",
        "last successful",
        "email",
        "1118xmb@gmail.com",
        "market_as_of",
        "semipulse-wenxuecity-source-v1",
        "source.post_id",
        "source.published_at",
        "source.edited_at",
        "source.url",
        "images[]",
        "local_path",
        "source_url",
        "resolved_url",
        "sha256",
        "byte_length",
        "check-market-session",
        "build-source",
        "decide-source-publication",
        "notify-source",
        "XNYS",
        "byte-for-byte",
        "risk_disclosure",
    )
    for phrase in required:
        assert phrase in data
    assert "yfinance" not in data
    assert "reconstruct" not in data.casefold()


def test_openai_interface_is_exact_and_uses_skill_token() -> None:
    path = SKILL_ROOT / "agents" / "openai.yaml"
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert parsed == {
        "interface": {
            "display_name": "SemiPulse Sentinel",
            "short_description": "Review semiconductor source-chart reports",
            "default_prompt": (
                "Use $semipulse-sentinel to review the latest copied source charts "
                "and assess whether the source scanner needs a refresh."
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
