"""Redacted report-ready email delivery through authenticated SMTP."""

from __future__ import annotations

import smtplib
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from email.message import EmailMessage
from html import escape
from typing import Protocol, cast
from urllib.parse import urlsplit

_REGIMES = {"risk-on", "constructive", "mixed", "defensive", "risk-off"}
_CONFIDENCE = {"high", "medium", "low"}
ALERT_RECIPIENT = "1118xmb@gmail.com"
SOURCE_ALERT_RECIPIENT = ALERT_RECIPIENT


class NotificationFailed(RuntimeError):
    """Raised when an SMTP delivery fails without exposing provider details."""


class SmtpClient(Protocol):
    """The SMTP methods required by report delivery."""

    def __enter__(self) -> SmtpClient: ...

    def __exit__(self, *args: object) -> object: ...

    def starttls(self, *, context: ssl.SSLContext) -> object: ...

    def login(self, username: str, password: str) -> object: ...

    def send_message(self, message: EmailMessage) -> object: ...


SmtpFactory = Callable[..., SmtpClient]


def _single_line(value: str, label: str) -> str:
    if not value or "\r" in value or "\n" in value:
        raise ValueError(f"{label} must be a nonempty single-line value")
    return value


def _required(environment: Mapping[str, str], name: str, *, strip: bool = True) -> str:
    raw = environment.get(name, "")
    value = raw.strip() if strip else raw
    return _single_line(value, name)


@dataclass(frozen=True, slots=True)
class SmtpSettings:
    """Validated SMTP settings whose password is excluded from repr output."""

    host: str
    port: int
    username: str
    password: str = field(repr=False)
    sender: str
    recipient: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.host, "SMTP host"),
            (self.username, "SMTP username"),
            (self.password, "SMTP password"),
            (self.sender, "email sender"),
            (self.recipient, "email recipient"),
        ):
            _single_line(value, label)
        if not 1 <= self.port <= 65535:
            raise ValueError("SMTP port must be between 1 and 65535")
        if "@" not in self.sender or "@" not in self.recipient:
            raise ValueError("sender and recipient must be email addresses")

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> SmtpSettings:
        """Load the exact notification variables without returning their values."""

        port_text = _required(environment, "SEMIPULSE_SMTP_PORT")
        try:
            port = int(port_text)
        except ValueError as error:
            raise ValueError("SMTP port must be an integer") from error
        return cls(
            host=_required(environment, "SEMIPULSE_SMTP_HOST"),
            port=port,
            username=_required(environment, "SEMIPULSE_SMTP_USER"),
            password=_required(
                environment, "SEMIPULSE_SMTP_PASSWORD", strip=False
            ),
            sender=_required(environment, "SEMIPULSE_EMAIL_FROM"),
            recipient=ALERT_RECIPIENT,
        )

    @classmethod
    def from_source_environment(
        cls, environment: Mapping[str, str]
    ) -> SmtpSettings:
        """Load SMTP credentials while hard-locking the source-alert recipient."""

        port_text = _required(environment, "SEMIPULSE_SMTP_PORT")
        try:
            port = int(port_text)
        except ValueError as error:
            raise ValueError("SMTP port must be an integer") from error
        return cls(
            host=_required(environment, "SEMIPULSE_SMTP_HOST"),
            port=port,
            username=_required(environment, "SEMIPULSE_SMTP_USER"),
            password=_required(
                environment, "SEMIPULSE_SMTP_PASSWORD", strip=False
            ),
            sender=_required(environment, "SEMIPULSE_EMAIL_FROM"),
            recipient=SOURCE_ALERT_RECIPIENT,
        )


@dataclass(frozen=True, slots=True)
class ReportAlert:
    """Safe report facts included in one post-deploy email."""

    market_as_of: date
    regime: str
    confidence: str
    coverage: str
    dashboard_url: str

    def __post_init__(self) -> None:
        regime = _single_line(self.regime, "regime")
        confidence = _single_line(self.confidence, "confidence")
        _single_line(self.coverage, "coverage")
        dashboard_url = _single_line(self.dashboard_url, "dashboard URL")
        if regime not in _REGIMES:
            raise ValueError("report regime is invalid")
        if confidence not in _CONFIDENCE:
            raise ValueError("report confidence is invalid")
        parsed = urlsplit(dashboard_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("dashboard URL must be an HTTPS URL without credentials")

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> ReportAlert:
        """Load only the audited report summary environment variables."""

        market_text = _required(environment, "SEMIPULSE_MARKET_AS_OF")
        try:
            market_as_of = date.fromisoformat(market_text)
        except ValueError as error:
            raise ValueError("SEMIPULSE_MARKET_AS_OF must be an ISO date") from error
        if market_as_of.isoformat() != market_text:
            raise ValueError("SEMIPULSE_MARKET_AS_OF must be a canonical ISO date")
        return cls(
            market_as_of=market_as_of,
            regime=_required(environment, "SEMIPULSE_REGIME"),
            confidence=_required(environment, "SEMIPULSE_CONFIDENCE"),
            coverage=_required(environment, "SEMIPULSE_COVERAGE"),
            dashboard_url=_required(environment, "SEMIPULSE_DASHBOARD_URL"),
        )


@dataclass(frozen=True, slots=True)
class SourceReportAlert:
    """Safe source-copy facts included in one post-deploy email."""

    market_as_of: date
    source_post_id: int
    source_title: str
    image_count: int
    dashboard_url: str

    def __post_init__(self) -> None:
        _single_line(self.source_title, "source title")
        dashboard_url = _single_line(self.dashboard_url, "dashboard URL")
        if self.source_post_id < 1:
            raise ValueError("source post id must be positive")
        if not 1 <= self.image_count <= 12:
            raise ValueError("source image count must be between 1 and 12")
        parsed = urlsplit(dashboard_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(
                "dashboard URL must be an HTTPS URL without credentials"
            )

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str]
    ) -> SourceReportAlert:
        """Load only validated source facts produced by the build job."""

        market_text = _required(environment, "SEMIPULSE_MARKET_AS_OF")
        try:
            market_as_of = date.fromisoformat(market_text)
        except ValueError as error:
            raise ValueError(
                "SEMIPULSE_MARKET_AS_OF must be an ISO date"
            ) from error
        if market_as_of.isoformat() != market_text:
            raise ValueError(
                "SEMIPULSE_MARKET_AS_OF must be a canonical ISO date"
            )
        try:
            post_id = int(_required(environment, "SEMIPULSE_SOURCE_POST_ID"))
            image_count = int(_required(environment, "SEMIPULSE_IMAGE_COUNT"))
        except ValueError as error:
            raise ValueError(
                "source post id and image count must be integers"
            ) from error
        return cls(
            market_as_of=market_as_of,
            source_post_id=post_id,
            source_title=_required(environment, "SEMIPULSE_SOURCE_TITLE"),
            image_count=image_count,
            dashboard_url=_required(environment, "SEMIPULSE_DASHBOARD_URL"),
        )


def build_message(settings: SmtpSettings, alert: ReportAlert) -> EmailMessage:
    """Build a plain-text and escaped-HTML report-ready message."""

    message = EmailMessage()
    message["Subject"] = (
        f"[SemiPulse] Report ready — {alert.market_as_of.isoformat()}"
    )
    message["From"] = settings.sender
    message["To"] = settings.recipient
    message.set_content(
        "SemiPulse Sentinel report is ready.\n\n"
        f"Market as of: {alert.market_as_of.isoformat()}\n"
        f"Regime: {alert.regime}\n"
        f"Confidence: {alert.confidence}\n"
        f"Coverage: {alert.coverage}\n\n"
        f"View report: {alert.dashboard_url}\n\n"
        "Research only — not individualized investment advice.\n"
    )
    url = escape(alert.dashboard_url, quote=True)
    message.add_alternative(
        "<!doctype html><html><body>"
        "<p>SemiPulse Sentinel report is ready.</p>"
        "<ul>"
        f"<li>Market as of: {escape(alert.market_as_of.isoformat())}</li>"
        f"<li>Regime: {escape(alert.regime)}</li>"
        f"<li>Confidence: {escape(alert.confidence)}</li>"
        f"<li>Coverage: {escape(alert.coverage)}</li>"
        "</ul>"
        f'<p><a href="{url}">View the SemiPulse Sentinel report</a></p>'
        "<p>Research only — not individualized investment advice.</p>"
        "</body></html>",
        subtype="html",
    )
    return message


def build_source_message(
    settings: SmtpSettings, alert: SourceReportAlert
) -> EmailMessage:
    """Build a source-copy report-ready message with one report link."""

    message = EmailMessage()
    message["Subject"] = (
        f"[SemiPulse] Source charts ready — {alert.market_as_of.isoformat()}"
    )
    message["From"] = settings.sender
    message["To"] = settings.recipient
    message.set_content(
        "SemiPulse Sentinel source-copy report is ready.\n\n"
        f"Market as of: {alert.market_as_of.isoformat()}\n"
        f"Source post: {alert.source_title} (#{alert.source_post_id})\n"
        f"Copied: {alert.image_count} source images\n\n"
        f"View report: {alert.dashboard_url}\n\n"
        "Research only — not individualized investment advice.\n"
    )
    url = escape(alert.dashboard_url, quote=True)
    message.add_alternative(
        "<!doctype html><html><body>"
        "<p>SemiPulse Sentinel source-copy report is ready.</p>"
        "<ul>"
        f"<li>Market as of: {escape(alert.market_as_of.isoformat())}</li>"
        f"<li>Source post: {escape(alert.source_title)} "
        f"(#{alert.source_post_id})</li>"
        f"<li>Copied: {alert.image_count} source images</li>"
        "</ul>"
        f'<p><a href="{url}">View the SemiPulse Sentinel report</a></p>'
        "<p>Research only — not individualized investment advice.</p>"
        "</body></html>",
        subtype="html",
    )
    return message


def send_report_alert(
    settings: SmtpSettings,
    alert: ReportAlert,
    *,
    smtp_factory: SmtpFactory | None = None,
) -> dict[str, object]:
    """Send one report alert and expose no credentials in the result."""

    message = build_message(settings, alert)
    factory = smtp_factory or cast(SmtpFactory, smtplib.SMTP)
    try:
        context = ssl.create_default_context()
        with factory(settings.host, settings.port, timeout=20) as server:
            server.starttls(context=context)
            server.login(settings.username, settings.password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise NotificationFailed("report alert delivery failed") from error
    return {"status": "sent", "market_as_of": alert.market_as_of.isoformat()}


def send_source_report_alert(
    settings: SmtpSettings,
    alert: SourceReportAlert,
    *,
    smtp_factory: SmtpFactory | None = None,
) -> dict[str, object]:
    """Send one fixed-recipient source alert without exposing credentials."""

    message = build_source_message(settings, alert)
    factory = smtp_factory or cast(SmtpFactory, smtplib.SMTP)
    try:
        context = ssl.create_default_context()
        with factory(settings.host, settings.port, timeout=20) as server:
            server.starttls(context=context)
            server.login(settings.username, settings.password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise NotificationFailed("report alert delivery failed") from error
    return {"status": "sent", "market_as_of": alert.market_as_of.isoformat()}
