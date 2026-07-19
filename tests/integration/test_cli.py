"""Process-boundary CLI behavior."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import semipulse_sentinel.cli as cli
import semipulse_sentinel.notifications as notifications
from semipulse_sentinel.cli import main
from semipulse_sentinel.notifications import NotificationFailed
from semipulse_sentinel.providers.yfinance_provider import YFinanceProvider

WATCHLIST = Path(__file__).parents[2] / "config" / "watchlist.csv"


def _publication_report(path: Path, market_as_of: str) -> Path:
    payload = {
        "schema_version": "semipulse-report-v1",
        "agent": {"name": "SemiPulse Sentinel", "slug": "semipulse-sentinel"},
        "market_as_of": market_as_of,
        "freshness": {"latest_market_session": market_as_of},
        "coverage": {
            "covered_count": 21,
            "watchlist_count": 23,
            "coverage_ratio": "0.9130434782608695652173913043",
        },
        "executive_summary": {"regime": "defensive", "confidence": "medium"},
        "charts": [{} for _ in range(8)],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _source_publication_report(
    path: Path,
    *,
    post_id: int = 97669,
    published_at: str = "2026-07-17T21:00:42",
    digest: str = "a" * 64,
) -> Path:
    payload = {
        "schema_version": "semipulse-wenxuecity-source-v1",
        "market_as_of": published_at[:10],
        "source": {
            "post_id": post_id,
            "published_at": published_at,
            "title": "狼来了的故事",
        },
        "images": [{"sha256": digest}],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _notification_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "SEMIPULSE_SMTP_HOST": "smtp.gmail.com",
        "SEMIPULSE_SMTP_PORT": "587",
        "SEMIPULSE_SMTP_USER": "sender@example.com",
        "SEMIPULSE_SMTP_PASSWORD": "secret-app-password",
        "SEMIPULSE_EMAIL_FROM": "sender@example.com",
        "SEMIPULSE_MARKET_AS_OF": "2026-07-20",
        "SEMIPULSE_REGIME": "defensive",
        "SEMIPULSE_CONFIDENCE": "medium",
        "SEMIPULSE_COVERAGE": "21/23 (91.3%)",
        "SEMIPULSE_DASHBOARD_URL": (
            "https://skydiver1118.github.io/semipulse-sentinel/"
        ),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


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
    assert payload["schedule"] == {
        "cron": "20 18 * * 1-5",
        "timezone": "America/New_York",
        "description": (
            "Monday through Friday at 6:20 PM America/New_York; publish only "
            "when the completed market session advances"
        ),
    }
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


def test_decide_publication_emits_safe_json_and_github_outputs(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    candidate = _publication_report(tmp_path / "candidate.json", "2026-07-17")
    published = _source_publication_report(tmp_path / "published.json")
    github_output = tmp_path / "github-output"

    code = main(
        [
            "decide-publication",
            "--candidate",
            str(candidate),
            "--published",
            str(published),
            "--github-output",
            str(github_output),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload == {
        "decision": "migration",
        "has_new_data": True,
        "market_as_of": "2026-07-17",
        "published_market_as_of": "2026-07-17",
        "status": "success",
    }
    assert github_output.read_text(encoding="utf-8").splitlines()[0:2] == [
        "decision=migration",
        "has_new_data=true",
    ]


def test_decide_publication_rejects_regressed_date_without_outputs(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    candidate = _publication_report(tmp_path / "candidate.json", "2026-07-16")
    published = _publication_report(tmp_path / "published.json", "2026-07-17")
    github_output = tmp_path / "github-output"

    code = main(
        [
            "decide-publication",
            "--candidate",
            str(candidate),
            "--published",
            str(published),
            "--github-output",
            str(github_output),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().err)
    assert code == 2
    assert payload["category"] == "configuration"
    assert "regressed" in payload["message"]
    assert not github_output.exists()


def test_decide_source_publication_emits_revision_outputs(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    candidate = _source_publication_report(
        tmp_path / "candidate.json", digest="b" * 64
    )
    published = _source_publication_report(tmp_path / "published.json")
    github_output = tmp_path / "github-output"

    code = main(
        [
            "decide-source-publication",
            "--candidate",
            str(candidate),
            "--published",
            str(published),
            "--github-output",
            str(github_output),
            "--json",
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {
        "decision": "revised",
        "has_new_data": True,
        "image_count": 1,
        "market_as_of": "2026-07-17",
        "source_post_id": 97669,
        "status": "success",
    }
    assert "source_title=狼来了的故事" in github_output.read_text(
        encoding="utf-8"
    )


def test_check_market_session_emits_safe_github_outputs(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    github_output = tmp_path / "github-output"

    code = main(
        [
            "check-market-session",
            "--at",
            "2026-07-17T18:20:00-04:00",
            "--github-output",
            str(github_output),
            "--json",
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {
        "reason": "completed-trading-session",
        "session_date": "2026-07-17",
        "should_run": True,
        "status": "success",
    }
    assert github_output.read_text(encoding="utf-8").splitlines() == [
        "should_run=true",
        "session_date=2026-07-17",
        "reason=completed-trading-session",
    ]


def test_notify_emits_only_safe_delivery_metadata(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _notification_environment(monkeypatch)

    def send_once(*_args: object, **_kwargs: object) -> dict[str, str]:
        return {"status": "sent", "market_as_of": "2026-07-20"}

    monkeypatch.setattr(notifications, "send_report_alert", send_once)

    assert main(["notify", "--json"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "market_as_of": "2026-07-20",
        "status": "sent",
    }
    assert "1118xmb" not in output
    assert "secret-app-password" not in output
    assert "sender@example.com" not in output


def test_notify_failure_is_sanitized_before_heavy_cli_imports(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _notification_environment(monkeypatch)

    def fail(*_args: object, **_kwargs: object) -> dict[str, str]:
        raise NotificationFailed("report alert delivery failed") from RuntimeError(
            "upstream-secret-detail"
        )

    monkeypatch.setattr(notifications, "send_report_alert", fail)

    assert main(["notify", "--json"]) == 4
    output = capsys.readouterr().err
    assert json.loads(output) == {
        "category": "notification",
        "message": "report alert delivery failed",
        "status": "error",
    }
    assert "upstream-secret-detail" not in output


def test_notify_source_uses_fixed_recipient_path_and_safe_output(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _notification_environment(monkeypatch)
    monkeypatch.setenv("SEMIPULSE_MARKET_AS_OF", "2026-07-17")
    monkeypatch.setenv("SEMIPULSE_SOURCE_POST_ID", "97669")
    monkeypatch.setenv("SEMIPULSE_SOURCE_TITLE", "狼来了的故事")
    monkeypatch.setenv("SEMIPULSE_IMAGE_COUNT", "8")

    def send_once(*_args: object, **_kwargs: object) -> dict[str, str]:
        return {"status": "sent", "market_as_of": "2026-07-17"}

    monkeypatch.setattr(notifications, "send_source_report_alert", send_once)

    assert main(["notify-source", "--json"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "market_as_of": "2026-07-17",
        "status": "sent",
    }
    assert "1118xmb" not in output
    assert "secret-app-password" not in output


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
