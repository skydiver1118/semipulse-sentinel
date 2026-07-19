"""Stable public and automation contracts without third-party imports."""

AGENT_NAME = "SemiPulse Sentinel"
AGENT_SLUG = "semipulse-sentinel"
REPORT_SCHEMA_VERSION = "semipulse-report-v1"
SCHEDULE_CRON = "0 18 * * 1-5"
SCHEDULE_TIMEZONE = "America/New_York"
SCHEDULE_DESCRIPTION = (
    "Monday through Friday at 6:00 PM America/New_York; publish only "
    "when the completed market session advances"
)
DASHBOARD_URL = "https://skydiver1118.github.io/semipulse-sentinel/"
REPORT_JSON_URL = DASHBOARD_URL + "report.json"
