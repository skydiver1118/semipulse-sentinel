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
PUBLIC_FILES = (
    "README.md",
    "docs/methodology.md",
    "docs/operations.md",
    "skill/semipulse-sentinel/SKILL.md",
    "skill/semipulse-sentinel/references/operations.md",
)
CHART_PURPOSES = (
    "Semiconductor complex performance",
    "Relative strength versus QQQ",
    "Watchlist breadth",
    "Equal-weight participation",
    "Momentum leaders and laggards",
    "Multi-horizon trend heatmap",
    "Volatility and peak-distance regime",
    "Risk/reward map",
)
EXPECTED_TRUSTED_PRIOR_PACKAGE_HASHES = (
    "017c615c077db7e173dbcc685aecb4e3d1b28d9f2f22ef1a25259f15b429f4f2",
    "6fb15cef1ad7451b4da68bbf2f7f5d2491092a6a3482e97aae1db22bff358aad",
    "0441ae4b5802a7aa528b313a38d1c02c7df80d0cbb6d6132023bd439d7dbe024",
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
    assert "python -m semipulse_sentinel validate" in data
    assert "report.json" in data
    assert "gh workflow run nightly-report.yml" in data


def test_skill_guidance_is_fail_closed_and_research_only() -> None:
    data = _read("skill/semipulse-sentinel/SKILL.md")
    data_flat = " ".join(data.split())
    required = (
        "semipulse-report-v1",
        "market_as_of",
        "Trading decision summary",
        "freshness",
        "coverage",
        "regime",
        "confidence",
        "supports",
        "challenges",
        "change triggers",
        "What this chart measures",
        "Evidence",
        "What it means now",
        "How it may inform trading decisions",
        "Counter-signal",
        "Do not dispatch unless",
        "Honor conditions attached to refresh authority",
        "not usable refresh authority",
        "not proof of staleness",
        "Keep freshness and coverage separate",
        "last successful report",
        "sends no email",
        "6:20 PM Eastern",
        "XNYS",
        "1118xmb@gmail.com",
        "research only",
        "Never place orders",
    )
    for phrase in required:
        assert phrase in data_flat
    for purpose in CHART_PURPOSES:
        assert purpose in data_flat


def test_operations_reference_has_canonical_interfaces() -> None:
    data = _read("skill/semipulse-sentinel/references/operations.md")
    data_flat = " ".join(data.split())
    required = (
        "https://github.com/skydiver1118/semipulse-sentinel",
        "https://skydiver1118.github.io/semipulse-sentinel/",
        "https://skydiver1118.github.io/semipulse-sentinel/report.json",
        "semipulse-report-v1",
        "Trading decision summary",
        "python -m semipulse_sentinel build --watchlist",
        "python -m semipulse_sentinel validate --site",
        "python -m semipulse_sentinel decide-publication",
        "python -m semipulse_sentinel notify --json",
        "gh workflow run nightly-report.yml --repo skydiver1118/semipulse-sentinel",
        "gh run list --repo skydiver1118/semipulse-sentinel",
        "main",
        "20 18 * * 1-5",
        "America/New_York",
        "6:20 PM Eastern",
        "Monday through Friday",
        "no new market data",
        "last successful",
        "email",
        "1118xmb@gmail.com",
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
        "query time",
        "check-market-session",
        "XNYS",
        "limitations",
        "risk_warning",
        "serialized",
        "cannot cancel",
    )
    for phrase in required:
        assert phrase in data_flat
    for purpose in CHART_PURPOSES:
        assert purpose in data_flat


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


def test_public_operator_material_omits_source_scanner_language() -> None:
    forbidden = (
        "Wenxuecity",
        "source-copy",
        "exact author",
        "\u4e91\u8d77\u5343\u767e\u5ea6",
    )

    for relative in PUBLIC_FILES:
        text = _read(relative)
        assert all(term.casefold() not in text.casefold() for term in forbidden)


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


def test_installers_trust_only_exact_released_package_hashes() -> None:
    pattern = re.compile(
        r"(?m)^\$TrustedPriorPackageHashes = @\((?P<values>[^\r\n]*)\)$"
    )

    for relative in ("scripts/install-agent.ps1", "scripts/uninstall-agent.ps1"):
        text = _read(relative)
        match = pattern.search(text)
        assert match is not None
        hashes = tuple(re.findall(r"'([0-9a-f]{64})'", match.group("values")))
        assert hashes == EXPECTED_TRUSTED_PRIOR_PACKAGE_HASHES
