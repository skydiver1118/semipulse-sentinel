"""XNYS trading-session and post-close workflow gate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import exchange_calendars as xcals  # type: ignore[import-untyped]

NEW_YORK = ZoneInfo("America/New_York")
REPORT_CUTOFF = time(18, 0)


@dataclass(frozen=True, slots=True)
class MarketSessionDecision:
    should_run: bool
    session_date: date
    reason: str


def evaluate_market_session(now: datetime) -> MarketSessionDecision:
    """Return whether the current New York date is a completed XNYS session."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("market-session clock must be timezone-aware")
    local = now.astimezone(NEW_YORK)
    session_date = local.date()
    calendar = xcals.get_calendar("XNYS")
    if not calendar.is_session(session_date.isoformat()):
        return MarketSessionDecision(
            should_run=False,
            session_date=session_date,
            reason="not-a-trading-session",
        )
    if local.time().replace(tzinfo=None) < REPORT_CUTOFF:
        return MarketSessionDecision(
            should_run=False,
            session_date=session_date,
            reason="session-not-complete",
        )
    return MarketSessionDecision(
        should_run=True,
        session_date=session_date,
        reason="completed-trading-session",
    )
