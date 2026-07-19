"""XNYS completed-session gate."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from semipulse_sentinel.market_session import evaluate_market_session

NEW_YORK = ZoneInfo("America/New_York")


def test_completed_xnys_session_runs() -> None:
    decision = evaluate_market_session(
        datetime(2026, 7, 17, 18, 20, tzinfo=NEW_YORK)
    )
    assert decision.should_run is True
    assert decision.session_date.isoformat() == "2026-07-17"
    assert decision.reason == "completed-trading-session"


def test_observed_independence_day_does_not_run() -> None:
    decision = evaluate_market_session(
        datetime(2026, 7, 3, 18, 20, tzinfo=NEW_YORK)
    )
    assert decision.should_run is False
    assert decision.reason == "not-a-trading-session"


def test_weekend_does_not_run() -> None:
    decision = evaluate_market_session(
        datetime(2026, 7, 18, 18, 20, tzinfo=NEW_YORK)
    )
    assert decision.should_run is False
    assert decision.reason == "not-a-trading-session"


def test_session_before_report_cutoff_does_not_run() -> None:
    decision = evaluate_market_session(
        datetime(2026, 7, 17, 17, 59, tzinfo=NEW_YORK)
    )
    assert decision.should_run is False
    assert decision.reason == "session-not-complete"
