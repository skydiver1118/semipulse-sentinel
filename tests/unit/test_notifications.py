import smtplib
from collections.abc import Mapping
from datetime import date
from email.message import EmailMessage
from typing import ClassVar

import pytest

from semipulse_sentinel.notifications import (
    ALERT_RECIPIENT,
    SOURCE_ALERT_RECIPIENT,
    NotificationFailed,
    ReportAlert,
    SmtpSettings,
    SourceReportAlert,
    send_report_alert,
    send_source_report_alert,
)


class FakeSMTP:
    instance: ClassVar["FakeSMTP"]

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_args: tuple[str, str] | None = None
        self.message: EmailMessage | None = None
        type(self).instance = self

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def starttls(self, *, context: object) -> None:
        assert context is not None
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.login_args = (username, password)

    def send_message(self, message: EmailMessage) -> None:
        self.message = message


def _settings() -> SmtpSettings:
    return SmtpSettings(
        host="smtp.gmail.com",
        port=587,
        username="sender@example.com",
        password="app-password-secret",
        sender="sender@example.com",
        recipient="1118xmb@gmail.com",
    )


def _alert() -> ReportAlert:
    return ReportAlert(
        market_as_of=date(2026, 7, 20),
        regime="defensive",
        confidence="medium",
        coverage="21/23 (91.3%)",
        dashboard_url="https://skydiver1118.github.io/semipulse-sentinel/",
    )


def _environment() -> dict[str, str]:
    return {
        "SEMIPULSE_SMTP_HOST": "smtp.gmail.com",
        "SEMIPULSE_SMTP_PORT": "587",
        "SEMIPULSE_SMTP_USER": "sender@example.com",
        "SEMIPULSE_SMTP_PASSWORD": "app-password-secret",
        "SEMIPULSE_EMAIL_FROM": "sender@example.com",
        "SEMIPULSE_MARKET_AS_OF": "2026-07-20",
        "SEMIPULSE_REGIME": "defensive",
        "SEMIPULSE_CONFIDENCE": "medium",
        "SEMIPULSE_COVERAGE": "21/23 (91.3%)",
        "SEMIPULSE_DASHBOARD_URL": (
            "https://skydiver1118.github.io/semipulse-sentinel/"
        ),
    }


def test_send_report_alert_uses_starttls_and_contains_the_report_link() -> None:
    result = send_report_alert(_settings(), _alert(), smtp_factory=FakeSMTP)

    assert result == {"status": "sent", "market_as_of": "2026-07-20"}
    assert FakeSMTP.instance.host == "smtp.gmail.com"
    assert FakeSMTP.instance.port == 587
    assert FakeSMTP.instance.timeout == 20
    assert FakeSMTP.instance.started_tls is True
    assert FakeSMTP.instance.login_args == (
        "sender@example.com",
        "app-password-secret",
    )
    message = FakeSMTP.instance.message
    assert message is not None
    assert message["To"] == "1118xmb@gmail.com"
    assert "2026-07-20" in str(message["Subject"])
    plain = message.get_body(preferencelist=("plain",))
    html = message.get_body(preferencelist=("html",))
    assert plain is not None and html is not None
    plain_body = plain.get_content()
    html_body = html.get_content()
    assert "View report:" in plain_body
    assert "View the SemiPulse Sentinel report" in html_body
    for body in (plain_body, html_body):
        assert _alert().dashboard_url in body
        assert "Source post" not in body
        assert "author" not in body.lower()
        assert "\u4e91\u8d77\u5343\u767e\u5ea6" not in body
    assert "app-password-secret" not in str(result)


def test_settings_and_alert_load_from_environment() -> None:
    environment: Mapping[str, str] = _environment() | {
        "SEMIPULSE_EMAIL_TO": "attacker@example.com"
    }

    settings = SmtpSettings.from_environment(environment)
    alert = ReportAlert.from_environment(environment)

    assert settings.port == 587
    assert settings.recipient == ALERT_RECIPIENT == "1118xmb@gmail.com"
    assert "app-password-secret" not in repr(settings)
    assert alert == _alert()


@pytest.mark.parametrize("port", ["invalid", "0", "65536"])
def test_settings_reject_invalid_ports(port: str) -> None:
    environment = _environment()
    environment["SEMIPULSE_SMTP_PORT"] = port

    with pytest.raises(ValueError, match="port"):
        SmtpSettings.from_environment(environment)


def test_settings_reject_missing_or_header_injection() -> None:
    missing = _environment()
    del missing["SEMIPULSE_SMTP_PASSWORD"]
    injected = _environment()
    injected["SEMIPULSE_EMAIL_FROM"] = (
        "victim@example.com\nBcc: attacker@example.com"
    )

    with pytest.raises(ValueError, match="SEMIPULSE_SMTP_PASSWORD"):
        SmtpSettings.from_environment(missing)
    with pytest.raises(ValueError, match="single-line"):
        SmtpSettings.from_environment(injected)


def test_alert_rejects_non_https_url_and_invalid_fields() -> None:
    insecure = _environment()
    insecure["SEMIPULSE_DASHBOARD_URL"] = "http://example.com/report"
    bad_regime = _environment()
    bad_regime["SEMIPULSE_REGIME"] = "unsafe\nregime"

    with pytest.raises(ValueError, match="HTTPS"):
        ReportAlert.from_environment(insecure)
    with pytest.raises(ValueError, match="single-line"):
        ReportAlert.from_environment(bad_regime)


def test_smtp_failure_is_sanitized() -> None:
    class FailingSMTP(FakeSMTP):
        def send_message(self, message: EmailMessage) -> None:
            raise smtplib.SMTPException("upstream-secret-detail")

    with pytest.raises(NotificationFailed) as captured:
        send_report_alert(_settings(), _alert(), smtp_factory=FailingSMTP)

    assert str(captured.value) == "report alert delivery failed"
    assert "upstream-secret-detail" not in str(captured.value)


def test_source_settings_hard_lock_the_only_recipient() -> None:
    environment = _environment()
    environment["SEMIPULSE_EMAIL_TO"] = "attacker@example.com"

    settings = SmtpSettings.from_source_environment(environment)

    assert SOURCE_ALERT_RECIPIENT == "1118xmb@gmail.com"
    assert settings.recipient == SOURCE_ALERT_RECIPIENT


def test_source_report_alert_sends_only_source_facts_and_link() -> None:
    settings = SmtpSettings.from_source_environment(_environment())
    alert = SourceReportAlert(
        market_as_of=date(2026, 7, 17),
        source_post_id=97669,
        source_title="狼来了的故事",
        image_count=8,
        dashboard_url="https://skydiver1118.github.io/semipulse-sentinel/",
    )

    result = send_source_report_alert(
        settings, alert, smtp_factory=FakeSMTP
    )

    assert result == {"status": "sent", "market_as_of": "2026-07-17"}
    message = FakeSMTP.instance.message
    assert message is not None
    assert message["To"] == SOURCE_ALERT_RECIPIENT
    assert "2026-07-17" in str(message["Subject"])
    plain = message.get_body(preferencelist=("plain",))
    assert plain is not None
    body = plain.get_content()
    assert "狼来了的故事" in body
    assert "8 source images" in body
    assert alert.dashboard_url in body


def test_source_report_alert_loads_validated_workflow_facts() -> None:
    environment = _environment() | {
        "SEMIPULSE_MARKET_AS_OF": "2026-07-17",
        "SEMIPULSE_SOURCE_POST_ID": "97669",
        "SEMIPULSE_SOURCE_TITLE": "狼来了的故事",
        "SEMIPULSE_IMAGE_COUNT": "8",
    }

    alert = SourceReportAlert.from_environment(environment)

    assert alert.market_as_of == date(2026, 7, 17)
    assert alert.source_post_id == 97669
    assert alert.image_count == 8
