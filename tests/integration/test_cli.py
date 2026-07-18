"""Process-boundary CLI behavior."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import semipulse_sentinel.cli as cli
from semipulse_sentinel.cli import main
from semipulse_sentinel.providers.yfinance_provider import YFinanceProvider

WATCHLIST = Path(__file__).parents[2] / "config" / "watchlist.csv"


def test_doctor_is_offline_and_reports_missing_site_as_diagnosis(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def network_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("doctor touched the provider")

    monkeypatch.setattr(YFinanceProvider, "__post_init__", network_forbidden)
    monkeypatch.setattr(YFinanceProvider, "fetch", network_forbidden)
    code = main(
        [
            "doctor",
            "--watchlist",
            str(WATCHLIST),
            "--site",
            str(tmp_path / "missing"),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 0
    assert payload["site_state"] == "missing"
    assert payload["schedule"]["cron"] == "0 18 * * *"
    assert payload["schedule"]["timezone"] == "America/New_York"
    assert payload["provider"] == "yfinance"


def test_doctor_reports_invalid_site_without_failing(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "sentinel.txt").write_text("not a report", encoding="utf-8")

    assert main(
        [
            "doctor",
            "--watchlist",
            str(WATCHLIST),
            "--site",
            str(site),
            "--json",
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["site_state"] == "invalid"


def test_doctor_malformed_watchlist_is_configuration_exit_code(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    malformed = tmp_path / "bad.csv"
    malformed.write_text("Symbol\nSMH\n", encoding="utf-8")

    assert main(["doctor", "--watchlist", str(malformed), "--json"]) == 2
    payload = json.loads(capsys.readouterr().err)
    assert payload["category"] == "configuration"


def test_validate_missing_site_is_publication_exit_code(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["validate", "--site", str(tmp_path / "missing"), "--json"]) == 3
    assert json.loads(capsys.readouterr().err)["category"] == "publication"


def test_unexpected_cli_error_is_sanitized(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(_arguments: argparse.Namespace) -> int:
        raise RuntimeError("secret-token-should-not-escape")

    monkeypatch.setattr(cli, "_validate", fail)
    assert main(["validate", "--site", str(tmp_path), "--json"]) == 4
    output = capsys.readouterr().err
    assert "secret-token-should-not-escape" not in output
    assert json.loads(output)["category"] == "unexpected"
