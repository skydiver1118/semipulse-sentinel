from semipulse_sentinel.contracts import (
    DASHBOARD_URL,
    REPORT_JSON_URL,
    SCHEDULE_CRON,
    SCHEDULE_DESCRIPTION,
    SCHEDULE_TIMEZONE,
)
from semipulse_sentinel.models import ReportSchedule


def test_trading_session_daily_schedule_contract_is_exact() -> None:
    assert SCHEDULE_CRON == "20 18 * * 1-5"
    assert SCHEDULE_TIMEZONE == "America/New_York"
    assert SCHEDULE_DESCRIPTION == (
        "Monday through Friday at 6:20 PM America/New_York; publish only "
        "when the completed market session advances"
    )
    assert DASHBOARD_URL == "https://skydiver1118.github.io/semipulse-sentinel/"
    assert REPORT_JSON_URL == DASHBOARD_URL + "report.json"


def test_report_schedule_accepts_only_the_weekday_contract() -> None:
    ReportSchedule(SCHEDULE_CRON, SCHEDULE_TIMEZONE, SCHEDULE_DESCRIPTION)

    try:
        ReportSchedule("0 18 * * 1-5", SCHEDULE_TIMEZONE, "legacy")
    except ValueError as error:
        assert "weekdays" in str(error)
    else:
        raise AssertionError("legacy calendar-day schedule was accepted")
