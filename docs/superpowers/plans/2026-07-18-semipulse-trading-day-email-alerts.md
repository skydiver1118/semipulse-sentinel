# SemiPulse Trading-Day Email Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish SemiPulse only when a completed market session advances and send one Gmail alert with the canonical report link after each new deployment.

**Architecture:** GitHub Actions requests builds at 6:00 PM America/New_York on weekdays, builds a validated candidate site, and compares its `market_as_of` with the canonical published JSON. Only a newer candidate is uploaded and deployed; a separate post-deploy job sends Gmail SMTP through encrypted repository secrets. Unchanged dates skip deployment and notification, preserving the last known-good Page.

**Tech Stack:** Python 3.11 standard library, existing pandas/yfinance report pipeline, pytest, PyYAML workflow verifier, GitHub Actions, GitHub Pages, Gmail SMTP with STARTTLS.

## Global Constraints

- Schedule requests are exactly `0 18 * * 1-5` with `timezone: America/New_York`.
- The workflow may start on an exchange holiday, but publication and email occur only when `market_as_of` advances.
- The current canonical `report.json` must be fetched successfully and validated; unreachable or invalid JSON fails closed.
- Existing freshness, required-benchmark, 70% coverage, exactly-eight-chart, price-integrity, and static-site gates remain active.
- Unchanged or failed data must leave the previous GitHub Pages deployment online.
- SMTP values live only in encrypted GitHub Actions secrets and must never be printed, committed, or included in artifacts.
- The recipient is `1118xmb@gmail.com`; sender values come from the existing private SOXL alert configuration.
- Email failure occurs after deployment and must not roll back the valid Page.
- Research only: no brokerage credentials, orders, positions, personalized sizing, or execution logic.

---

## File map

- Create `src/semipulse_sentinel/contracts.py`: shared agent, schedule, schema, and canonical URL constants with no third-party imports.
- Create `src/semipulse_sentinel/publication.py`: strict report snapshot parsing and market-date advancement decisions.
- Create `src/semipulse_sentinel/notifications.py`: environment-backed Gmail SMTP settings and report-ready message delivery.
- Create `tests/unit/test_contracts.py`: exact schedule and URL contract tests.
- Create `tests/unit/test_publication.py`: newer, unchanged, regressed, and malformed report tests.
- Create `tests/unit/test_notifications.py`: MIME, STARTTLS, login, recipient, redaction, and failure tests using a fake SMTP transport.
- Modify `src/semipulse_sentinel/pipeline.py`, `models.py`, `report.py`, and `cli.py`: consume shared contracts and expose `decide-publication` and `notify` commands.
- Modify `tests/integration/test_cli.py`: verify new CLI boundaries and weekday doctor metadata.
- Modify `.github/workflows/nightly-report.yml`, `scripts/verify_workflow.py`, and `tests/unit/test_workflow.py`: implement and audit conditional build/deploy/notify orchestration.
- Modify `README.md`, `docs/operations.md`, `docs/methodology.md`, `skill/semipulse-sentinel/references/operations.md`, `tests/unit/test_skill.py`, `scripts/install-agent.ps1`, and `scripts/uninstall-agent.ps1`: document operations and safely upgrade the installed skill.
- Regenerate `site/` through the application after code verification so the bundled local site satisfies the new schedule contract while retaining the latest available market date.

---

### Task 1: Centralize the weekday schedule contract

**Files:**
- Create: `src/semipulse_sentinel/contracts.py`
- Create: `tests/unit/test_contracts.py`
- Modify: `src/semipulse_sentinel/pipeline.py:64-70`
- Modify: `src/semipulse_sentinel/models.py:200-210`
- Modify: `src/semipulse_sentinel/report.py:33,1031-1037`
- Modify: `src/semipulse_sentinel/cli.py:145-156`
- Modify: `tests/integration/test_cli.py:34-44`

**Interfaces:**
- Produces: `AGENT_NAME`, `AGENT_SLUG`, `REPORT_SCHEMA_VERSION`, `SCHEDULE_CRON`, `SCHEDULE_TIMEZONE`, `SCHEDULE_DESCRIPTION`, `DASHBOARD_URL`, and `REPORT_JSON_URL` string constants.
- Consumes: no project modules or third-party packages.

- [ ] **Step 1: Write the failing contract and doctor tests**

Create `tests/unit/test_contracts.py`:

```python
from semipulse_sentinel.contracts import (
    DASHBOARD_URL,
    REPORT_JSON_URL,
    SCHEDULE_CRON,
    SCHEDULE_DESCRIPTION,
    SCHEDULE_TIMEZONE,
)
from semipulse_sentinel.models import ReportSchedule


def test_weekday_schedule_contract_is_exact() -> None:
    assert SCHEDULE_CRON == "0 18 * * 1-5"
    assert SCHEDULE_TIMEZONE == "America/New_York"
    assert "Monday through Friday" in SCHEDULE_DESCRIPTION
    assert "market session advances" in SCHEDULE_DESCRIPTION
    assert DASHBOARD_URL == "https://skydiver1118.github.io/semipulse-sentinel/"
    assert REPORT_JSON_URL == DASHBOARD_URL + "report.json"


def test_report_schedule_accepts_only_the_weekday_contract() -> None:
    ReportSchedule(SCHEDULE_CRON, SCHEDULE_TIMEZONE, SCHEDULE_DESCRIPTION)

    try:
        ReportSchedule("0 18 * * *", SCHEDULE_TIMEZONE, "legacy")
    except ValueError as error:
        assert "weekdays" in str(error)
    else:
        raise AssertionError("legacy calendar-day schedule was accepted")
```

Change the doctor assertions in `tests/integration/test_cli.py` to:

```python
assert payload["schedule"] == {
    "cron": "0 18 * * 1-5",
    "timezone": "America/New_York",
    "description": (
        "Monday through Friday at 6:00 PM America/New_York; publish only "
        "when the completed market session advances"
    ),
}
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/unit/test_contracts.py tests/integration/test_cli.py::test_doctor_is_offline_and_reports_missing_site_as_diagnosis -q
```

Expected: collection fails because `semipulse_sentinel.contracts` does not exist, or the legacy schedule assertions fail against `0 18 * * *`.

- [ ] **Step 3: Add the shared contract module**

Create `src/semipulse_sentinel/contracts.py`:

```python
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
```

Import these constants in `pipeline.py`, remove `_AGENT_NAME`, `_AGENT_SLUG`, `_SCHEDULE_CRON`, `_SCHEDULE_TIMEZONE`, and `_SCHEDULE_DESCRIPTION`, and replace their uses with the public names.

In `models.py`, replace the literal validation with:

```python
from semipulse_sentinel.contracts import SCHEDULE_CRON, SCHEDULE_TIMEZONE

# inside ReportSchedule.__post_init__
if self.cron != SCHEDULE_CRON or self.timezone != SCHEDULE_TIMEZONE:
    raise ValueError("report schedule must be 18:00 America/New_York on weekdays")
```

In `report.py`, import `REPORT_SCHEMA_VERSION`, `SCHEDULE_CRON`, and `SCHEDULE_TIMEZONE` from `contracts.py`, remove the local schema literal, and validate those constants at the schedule-disclosure gate.

In `cli.py`, emit the three schedule constants from `_doctor` instead of literals.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/unit/test_contracts.py tests/integration/test_cli.py::test_doctor_is_offline_and_reports_missing_site_as_diagnosis tests/integration/test_pipeline.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the schedule contract**

```powershell
git add src/semipulse_sentinel/contracts.py src/semipulse_sentinel/pipeline.py src/semipulse_sentinel/models.py src/semipulse_sentinel/report.py src/semipulse_sentinel/cli.py tests/unit/test_contracts.py tests/integration/test_cli.py
git commit -m "feat: schedule reports on weekdays"
```

---

### Task 2: Decide publication from validated market dates

**Files:**
- Create: `src/semipulse_sentinel/publication.py`
- Create: `tests/unit/test_publication.py`
- Modify: `src/semipulse_sentinel/cli.py`
- Modify: `tests/integration/test_cli.py`

**Interfaces:**
- Consumes: `AGENT_NAME`, `AGENT_SLUG`, and `REPORT_SCHEMA_VERSION` from `contracts.py`.
- Produces: `ReportSnapshot`, `PublicationDecision`, `read_report_snapshot(path)`, `decide_publication(candidate, published)`, and `append_github_outputs(path, decision)`.
- Produces CLI: `semipulse-sentinel decide-publication --candidate <json> --published <json> --github-output <path> --json`.

- [ ] **Step 1: Write failing publication tests**

Create `tests/unit/test_publication.py` with this fixture and assertions:

```python
import json
from pathlib import Path

import pytest

from semipulse_sentinel.publication import (
    append_github_outputs,
    decide_publication,
    read_report_snapshot,
)


def _report(path: Path, market_as_of: str) -> Path:
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


def test_newer_candidate_is_publishable_and_writes_safe_outputs(tmp_path: Path) -> None:
    candidate = read_report_snapshot(_report(tmp_path / "candidate.json", "2026-07-20"))
    published = read_report_snapshot(_report(tmp_path / "published.json", "2026-07-17"))
    decision = decide_publication(candidate, published)
    output = tmp_path / "github-output"

    append_github_outputs(output, decision)

    assert decision.kind == "new"
    assert decision.has_new_data is True
    assert output.read_text(encoding="utf-8").splitlines() == [
        "decision=new",
        "has_new_data=true",
        "market_as_of=2026-07-20",
        "published_market_as_of=2026-07-17",
        "regime=defensive",
        "confidence=medium",
        "coverage=21/23 (91.3%)",
    ]


def test_equal_candidate_is_unchanged(tmp_path: Path) -> None:
    current = read_report_snapshot(_report(tmp_path / "current.json", "2026-07-17"))
    decision = decide_publication(current, current)
    assert decision.kind == "unchanged"
    assert decision.has_new_data is False


def test_regressed_candidate_is_rejected(tmp_path: Path) -> None:
    candidate = read_report_snapshot(_report(tmp_path / "candidate.json", "2026-07-16"))
    published = read_report_snapshot(_report(tmp_path / "published.json", "2026-07-17"))
    with pytest.raises(ValueError, match="regressed"):
        decide_publication(candidate, published)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema_version="wrong"),
        lambda payload: payload["agent"].update(slug="wrong"),
        lambda payload: payload.update(market_as_of="not-a-date"),
        lambda payload: payload["freshness"].update(latest_market_session="2026-07-16"),
        lambda payload: payload.update(charts=[]),
        lambda payload: payload["coverage"].update(covered_count=22),
        lambda payload: payload["executive_summary"].update(regime="unsafe\nvalue"),
    ],
)
def test_report_snapshot_rejects_invalid_identity_or_outputs(
    tmp_path: Path, mutation: object
) -> None:
    path = _report(tmp_path / "report.json", "2026-07-17")
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutation(payload)  # type: ignore[operator]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        read_report_snapshot(path)
```

- [ ] **Step 2: Run publication tests and verify RED**

```powershell
python -m pytest tests/unit/test_publication.py -q
```

Expected: FAIL because `semipulse_sentinel.publication` is missing.

- [ ] **Step 3: Implement the strict publication module**

Create `publication.py` with frozen dataclasses. `read_report_snapshot` must:

```python
@dataclass(frozen=True, slots=True)
class ReportSnapshot:
    market_as_of: date
    regime: str
    confidence: str
    covered_count: int
    watchlist_count: int
    coverage_ratio: Decimal

    @property
    def coverage_label(self) -> str:
        percent = self.coverage_ratio * Decimal(100)
        return f"{self.covered_count}/{self.watchlist_count} ({percent:.1f}%)"


@dataclass(frozen=True, slots=True)
class PublicationDecision:
    kind: Literal["new", "unchanged"]
    candidate: ReportSnapshot
    published: ReportSnapshot

    @property
    def has_new_data(self) -> bool:
        return self.kind == "new"
```

Parse JSON with `json.loads(Path(path).read_text(encoding="utf-8"))`. Require an object; exact agent name/slug and schema version; an ISO date equal to `freshness.latest_market_session`; exactly eight charts; integer counts with `0 < covered_count <= watchlist_count`; a decimal coverage ratio exactly equal to `Decimal(covered_count) / Decimal(watchlist_count)`; regime in `{"risk-on", "constructive", "mixed", "defensive", "risk-off"}`; and confidence in `{"high", "medium", "low"}`. Reject booleans where integers are required and reject any output string containing CR or LF.

Implement the decision exactly as:

```python
def decide_publication(
    candidate: ReportSnapshot, published: ReportSnapshot
) -> PublicationDecision:
    if candidate.market_as_of < published.market_as_of:
        raise ValueError(
            "candidate market_as_of regressed from "
            f"{published.market_as_of.isoformat()} to {candidate.market_as_of.isoformat()}"
        )
    kind: Literal["new", "unchanged"] = (
        "new" if candidate.market_as_of > published.market_as_of else "unchanged"
    )
    return PublicationDecision(kind, candidate, published)
```

`append_github_outputs` opens the requested path in append mode with UTF-8 and writes the seven exact lines asserted by the test. It writes no secret or arbitrary provider text.

- [ ] **Step 4: Run publication tests and verify GREEN**

```powershell
python -m pytest tests/unit/test_publication.py -q
```

Expected: PASS.

- [ ] **Step 5: Add the decision CLI test and command**

Add to `tests/integration/test_cli.py` a process-boundary test that writes two fixture JSON files, calls:

```python
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
```

and asserts code `0`, JSON status `success`, decision `new`, `has_new_data is True`, and the exact GitHub output lines from the unit test. Add a second test asserting a regressed date returns configuration exit code `2` without writing an output file.

Extend `_parser()` and `main()` in `cli.py` with the `decide-publication` command and a lazy `_decide_publication` handler. The handler reads both snapshots, decides, appends outputs, emits only safe fields, and returns `0`.

- [ ] **Step 6: Verify the CLI tests**

```powershell
python -m pytest tests/unit/test_publication.py tests/integration/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the publication gate**

```powershell
git add src/semipulse_sentinel/publication.py src/semipulse_sentinel/cli.py tests/unit/test_publication.py tests/integration/test_cli.py
git commit -m "feat: gate publication on new market data"
```

---

### Task 3: Add a redacted Gmail SMTP notifier

**Files:**
- Create: `src/semipulse_sentinel/notifications.py`
- Create: `tests/unit/test_notifications.py`
- Modify: `src/semipulse_sentinel/cli.py`
- Modify: `tests/integration/test_cli.py`

**Interfaces:**
- Consumes environment keys `SEMIPULSE_SMTP_HOST`, `SEMIPULSE_SMTP_PORT`, `SEMIPULSE_SMTP_USER`, `SEMIPULSE_SMTP_PASSWORD`, `SEMIPULSE_EMAIL_FROM`, `SEMIPULSE_EMAIL_TO`, `SEMIPULSE_MARKET_AS_OF`, `SEMIPULSE_REGIME`, `SEMIPULSE_CONFIDENCE`, `SEMIPULSE_COVERAGE`, and `SEMIPULSE_DASHBOARD_URL`.
- Produces: `SmtpSettings.from_environment`, `ReportAlert.from_environment`, `build_message`, `send_report_alert`, and `NotificationFailed`.
- Produces CLI: `semipulse-sentinel notify --json`.

- [ ] **Step 1: Write failing notifier tests with a real fake transport**

Create a `FakeSMTP` context manager that records constructor arguments, `starttls`, `login`, and `send_message`. Test that:

```python
settings = SmtpSettings(
    host="smtp.gmail.com",
    port=587,
    username="sender@example.com",
    password="app-password-secret",
    sender="sender@example.com",
    recipient="1118xmb@gmail.com",
)
alert = ReportAlert(
    market_as_of=date(2026, 7, 20),
    regime="defensive",
    confidence="medium",
    coverage="21/23 (91.3%)",
    dashboard_url="https://skydiver1118.github.io/semipulse-sentinel/",
)
result = send_report_alert(settings, alert, smtp_factory=FakeSMTP)

assert result == {"status": "sent", "market_as_of": "2026-07-20"}
assert FakeSMTP.instance.started_tls is True
assert FakeSMTP.instance.login_args == ("sender@example.com", "app-password-secret")
message = FakeSMTP.instance.message
assert message["To"] == "1118xmb@gmail.com"
assert "2026-07-20" in message["Subject"]
assert "https://skydiver1118.github.io/semipulse-sentinel/" in message.get_body(
    preferencelist=("plain",)
).get_content()
assert "app-password-secret" not in str(result)
```

Add tests that missing configuration, a nonnumeric/out-of-range port, CR/LF header injection, a non-HTTPS dashboard URL, and an SMTP exception raise `ValueError` or the sanitized `NotificationFailed("report alert delivery failed")` without exposing the password or upstream exception string.

- [ ] **Step 2: Run notifier tests and verify RED**

```powershell
python -m pytest tests/unit/test_notifications.py -q
```

Expected: FAIL because `semipulse_sentinel.notifications` is missing.

- [ ] **Step 3: Implement notifier settings, MIME content, and delivery**

Use frozen, slotted `SmtpSettings` and `ReportAlert` dataclasses. Password fields use `field(repr=False)`. `from_environment` accepts a `Mapping[str, str]`, strips non-password fields, requires every named variable, and validates the same regime/confidence values as publication parsing.

`build_message` creates `EmailMessage` with:

```python
message["Subject"] = f"[SemiPulse] Report ready — {alert.market_as_of.isoformat()}"
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
```

Add an HTML alternative using `html.escape` for every dynamic field and an escaped anchor URL. `send_report_alert` uses `ssl.create_default_context()`, `smtplib.SMTP(host, port, timeout=20)`, `starttls(context=context)`, `login`, and `send_message`. Catch `OSError` and `smtplib.SMTPException` and raise `NotificationFailed("report alert delivery failed")` from the original error.

- [ ] **Step 4: Run notifier tests and verify GREEN**

```powershell
python -m pytest tests/unit/test_notifications.py -q
```

Expected: PASS.

- [ ] **Step 5: Add and test the lightweight notify CLI**

Add `notify --json` to `_parser()`. `_notify` loads settings and alert data from `os.environ`, sends once, and emits only `status` and `market_as_of`; it must not emit sender, recipient, username, password, or raw SMTP errors.

In `main()`, handle `NotificationFailed` before importing the heavy pipeline modules:

```python
if arguments.command == "notify" and isinstance(error, NotificationFailed):
    _emit(
        {"status": "error", "category": "notification", "message": str(error)},
        json_output=arguments.json_output,
        error=True,
    )
    return 4
```

Add CLI tests with the notifier send function monkeypatched to return a safe result, plus a failure test asserting the upstream secret-bearing exception text is absent.

- [ ] **Step 6: Verify notifier and CLI tests**

```powershell
python -m pytest tests/unit/test_notifications.py tests/integration/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the notifier**

```powershell
git add src/semipulse_sentinel/notifications.py src/semipulse_sentinel/cli.py tests/unit/test_notifications.py tests/integration/test_cli.py
git commit -m "feat: email new SemiPulse reports"
```

---

### Task 4: Make the audited workflow conditional and post-deploy email aware

**Files:**
- Modify: `.github/workflows/nightly-report.yml`
- Modify: `scripts/verify_workflow.py`
- Modify: `tests/unit/test_workflow.py`

**Interfaces:**
- Consumes: the two new CLI commands and six encrypted SMTP/email secrets.
- Produces build outputs: `has_new_data`, `market_as_of`, `regime`, `confidence`, and `coverage`.
- Produces jobs: `build`, conditional `deploy`, and conditional `notify`.

- [ ] **Step 1: Change workflow tests first**

Update `test_workflow_has_exact_top_level_contract` to require `0 18 * * 1-5`. Update the job contract test to require exactly `{"build", "deploy", "notify"}` and these conditions:

```python
assert build["outputs"] == {
    "has_new_data": "${{ steps.publication.outputs.has_new_data }}",
    "market_as_of": "${{ steps.publication.outputs.market_as_of }}",
    "regime": "${{ steps.publication.outputs.regime }}",
    "confidence": "${{ steps.publication.outputs.confidence }}",
    "coverage": "${{ steps.publication.outputs.coverage }}",
}
assert deploy["if"] == "needs.build.outputs.has_new_data == 'true'"
assert notify["needs"] == ["build", "deploy"]
assert notify["if"] == (
    "needs.build.outputs.has_new_data == 'true' && "
    "needs.deploy.result == 'success'"
)
```

Require build steps in this order: checkout, Python, locked dependencies, project install, workflow verification, offline tests, candidate build, candidate validation, published-report fetch, publication decision, conditional Pages configuration, conditional artifact upload. Require the notifier job to use only pinned first-party checkout/setup actions and one `Send report email` command.

Replace the old blanket `"secrets." not in raw` assertion with an exact set assertion for these six secret expressions only:

```python
assert set(re.findall(r"\$\{\{ secrets\.([A-Z0-9_]+) \}\}", raw)) == {
    "SEMIPULSE_SMTP_HOST",
    "SEMIPULSE_SMTP_PORT",
    "SEMIPULSE_SMTP_USER",
    "SEMIPULSE_SMTP_PASSWORD",
    "SEMIPULSE_EMAIL_FROM",
    "SEMIPULSE_EMAIL_TO",
}
```

- [ ] **Step 2: Run workflow tests and verify RED**

```powershell
python -m pytest tests/unit/test_workflow.py -q
```

Expected: FAIL on the calendar-day cron, missing outputs, missing notification job, and forbidden-secret assumptions.

- [ ] **Step 3: Replace the workflow with the exact conditional flow**

Use this job behavior:

```yaml
"on":
  workflow_dispatch: {}
  schedule:
    - cron: "0 18 * * 1-5"
      timezone: "America/New_York"

jobs:
  build:
    outputs:
      has_new_data: "${{ steps.publication.outputs.has_new_data }}"
      market_as_of: "${{ steps.publication.outputs.market_as_of }}"
      regime: "${{ steps.publication.outputs.regime }}"
      confidence: "${{ steps.publication.outputs.confidence }}"
      coverage: "${{ steps.publication.outputs.coverage }}"
```

Keep the existing checkout, setup, install, verifier, and tests. Build and validate `candidate-site`. Then add:

```yaml
      - name: Fetch published report
        run: >-
          curl --fail --show-error --silent --location --retry 3
          --output published-report.json
          "https://skydiver1118.github.io/semipulse-sentinel/report.json?run_id=${GITHUB_RUN_ID}"

      - name: Decide publication
        id: publication
        run: >-
          python -m semipulse_sentinel decide-publication
          --candidate candidate-site/report.json
          --published published-report.json
          --github-output "$GITHUB_OUTPUT"
          --json
```

Set `if: steps.publication.outputs.has_new_data == 'true'` on Configure Pages and Upload Pages artifact, and upload `candidate-site`.

Set the deploy job condition to `needs.build.outputs.has_new_data == 'true'`.

Add a notify job with `contents: read`, checkout and Python 3.11.15, `PYTHONPATH: src`, and this exact send-step environment:

```yaml
        env:
          SEMIPULSE_SMTP_HOST: "${{ secrets.SEMIPULSE_SMTP_HOST }}"
          SEMIPULSE_SMTP_PORT: "${{ secrets.SEMIPULSE_SMTP_PORT }}"
          SEMIPULSE_SMTP_USER: "${{ secrets.SEMIPULSE_SMTP_USER }}"
          SEMIPULSE_SMTP_PASSWORD: "${{ secrets.SEMIPULSE_SMTP_PASSWORD }}"
          SEMIPULSE_EMAIL_FROM: "${{ secrets.SEMIPULSE_EMAIL_FROM }}"
          SEMIPULSE_EMAIL_TO: "${{ secrets.SEMIPULSE_EMAIL_TO }}"
          SEMIPULSE_MARKET_AS_OF: "${{ needs.build.outputs.market_as_of }}"
          SEMIPULSE_REGIME: "${{ needs.build.outputs.regime }}"
          SEMIPULSE_CONFIDENCE: "${{ needs.build.outputs.confidence }}"
          SEMIPULSE_COVERAGE: "${{ needs.build.outputs.coverage }}"
          SEMIPULSE_DASHBOARD_URL: "https://skydiver1118.github.io/semipulse-sentinel/"
        run: python -m semipulse_sentinel notify --json
```

- [ ] **Step 4: Update the structural verifier**

Change `_EXPECTED` to the exact new YAML structure, including build outputs, every `if`, the notify job, and the six exact secret references. Update the action occurrence list so checkout/setup are each accepted once in `build` and once in `notify`, while configure/upload/deploy remain single occurrences.

Replace the blanket secret prohibition with:

```python
allowed_secrets = {
    "SEMIPULSE_SMTP_HOST",
    "SEMIPULSE_SMTP_PORT",
    "SEMIPULSE_SMTP_USER",
    "SEMIPULSE_SMTP_PASSWORD",
    "SEMIPULSE_EMAIL_FROM",
    "SEMIPULSE_EMAIL_TO",
}
observed_secrets = set(re.findall(r"\$\{\{ secrets\.([A-Z0-9_]+) \}\}", text))
if observed_secrets != allowed_secrets:
    _fail("workflow must use only the exact SemiPulse notification secrets")
```

Keep `github.token`, `contents: write`, mutable actions, caches, Pages enablement, aliases, merge keys, and pre-build network access prohibited. Permit the one audited `curl` step only after candidate build and validation. Require exactly one build command, one publication decision command, and one notification command.

- [ ] **Step 5: Verify the workflow contract and mutations**

```powershell
python scripts/verify_workflow.py .github/workflows/nightly-report.yml
python -m pytest tests/unit/test_workflow.py -q
```

Expected: verifier prints `workflow valid`; all workflow tests PASS.

- [ ] **Step 6: Commit the audited workflow**

```powershell
git add .github/workflows/nightly-report.yml scripts/verify_workflow.py tests/unit/test_workflow.py
git commit -m "feat: deploy and notify only for new sessions"
```

---

### Task 5: Update public operations and the installed skill

**Files:**
- Modify: `README.md`
- Modify: `docs/operations.md`
- Modify: `docs/methodology.md`
- Modify: `skill/semipulse-sentinel/references/operations.md`
- Modify: `tests/unit/test_skill.py`
- Modify: `scripts/install-agent.ps1`
- Modify: `scripts/uninstall-agent.ps1`

**Interfaces:**
- Produces: documented weekday/no-new-data/email behavior and a trusted upgrade path for the installed skill package.
- Consumes: prior installed package hash `017c615c077db7e173dbcc685aecb4e3d1b28d9f2f22ef1a25259f15b429f4f2`.

- [ ] **Step 1: Add failing documentation and skill assertions**

Require README and operations text to contain all of:

```python
required = (
    "Monday through Friday",
    "0 18 * * 1-5",
    "market_as_of",
    "no new market data",
    "last successful",
    "1118xmb@gmail.com",
    "SEMIPULSE_SMTP_PASSWORD",
    "email",
)
```

Update `tests/unit/test_skill.py` to require the weekday cron, unchanged-data skip, last-good retention, and the rule that email is sent only after a successful new deployment. Remove the old `0 18 * * *` assertion.

- [ ] **Step 2: Run documentation tests and verify RED**

```powershell
python -m pytest tests/unit/test_skill.py tests/unit/test_workflow.py::test_public_documentation_covers_identity_methodology_and_operations -q
```

Expected: FAIL because public and skill documentation still describes every-calendar-day execution and no notification.

- [ ] **Step 3: Update documentation with exact operational behavior**

In README, replace “nightly” cadence claims with “weekdays at 6:00 PM Eastern; publication only when the completed market session advances.” Add a short Email Alerts section naming the recipient and explaining encrypted secrets, post-deploy timing, and no duplicate email for unchanged dates.

In `docs/operations.md`, document:

- schedule `0 18 * * 1-5` and DST UTC conversions;
- exchange-holiday behavior as a started workflow that exits successfully without deploy/email when `market_as_of` is unchanged;
- prior JSON fetch failure as an operational failure;
- the six repository secret names;
- post-deploy notification failure behavior;
- how to retry a failed notification without republishing a blank or partial site;
- the permanent dashboard and JSON links.

In methodology, state that weekday scheduling is not an exchange calendar and the market-date advancement gate decides publication.

Mirror these facts in `skill/semipulse-sentinel/references/operations.md`, preserving the skill’s refresh-authority and research-only boundaries.

- [ ] **Step 4: Add the trusted prior package hash**

Set the same exact value in both PowerShell scripts:

```powershell
$TrustedPriorPackageHashes = @(
    '017c615c077db7e173dbcc685aecb4e3d1b28d9f2f22ef1a25259f15b429f4f2'
)
```

This allows the currently installed, manifest-verified skill to upgrade atomically to the new operations reference without trusting arbitrary package content.

- [ ] **Step 5: Verify docs and installer behavior**

```powershell
python -m pytest tests/unit/test_skill.py tests/unit/test_workflow.py::test_public_documentation_covers_identity_methodology_and_operations -q
powershell -NoProfile -ExecutionPolicy Bypass -File tests/windows/test_install_agent.ps1
```

Expected: PASS and `SemiPulse Sentinel installer acceptance passed.`

- [ ] **Step 6: Commit documentation and skill upgrade**

```powershell
git add README.md docs/operations.md docs/methodology.md skill/semipulse-sentinel/references/operations.md tests/unit/test_skill.py scripts/install-agent.ps1 scripts/uninstall-agent.ps1
git commit -m "docs: explain trading-day report alerts"
```

---

### Task 6: Run complete verification and refresh the bundled local site

**Files:**
- Regenerate: `site/index.html`
- Regenerate: `site/report.json`
- Regenerate: `site/charts/*.svg`
- Regenerate: `site/static/report.css`

**Interfaces:**
- Consumes: completed source changes and current provider data.
- Produces: a locally valid bundled site using the latest available market session and the new schedule disclosure.

- [ ] **Step 1: Run static and full offline verification**

```powershell
python -m ruff check .
python -m mypy src
python -m pytest -q
python scripts/verify_workflow.py .github/workflows/nightly-report.yml
python -m build
```

Expected: all commands exit `0`; pytest has no failures; both wheel and source archive build.

- [ ] **Step 2: Build the bundled site through the application**

```powershell
python -m semipulse_sentinel build --watchlist config/watchlist.csv --output site --json
python -m semipulse_sentinel validate --site site --json
python -m semipulse_sentinel doctor --watchlist config/watchlist.csv --site site --json
```

Expected: build status `success`; validation reports exactly eight charts and schema `semipulse-report-v1`; doctor reports `site_state=valid`, weekday cron, and the most recent available `market_as_of`. This development build may reuse Friday data on a weekend; it does not deploy or email.

- [ ] **Step 3: Inspect generated metadata without inferring from chart pixels**

Parse `site/report.json` and assert:

```powershell
$report = Get-Content -Raw site/report.json | ConvertFrom-Json
if ($report.schedule.cron -cne '0 18 * * 1-5') { throw 'wrong report schedule' }
if ($report.charts.Count -ne 8) { throw 'wrong chart count' }
if ($report.market_as_of -cne $report.freshness.latest_market_session) { throw 'market date mismatch' }
```

Expected: no output and exit `0`.

- [ ] **Step 4: Commit the application-generated site**

```powershell
git add site
git commit -m "build: refresh weekday report metadata"
```

- [ ] **Step 5: Re-run the final clean-tree gate**

```powershell
git diff --check
python -m pytest -q
python -m semipulse_sentinel validate --site site --json
git status --short
```

Expected: tests and validation pass; `git status --short` prints nothing.

---

### Task 7: Configure secrets, release to public main, and verify activation

**Files:**
- Upgrade installed package at: `C:\Users\SKYDI\.codex\skills\semipulse-sentinel`
- No secret-bearing file is created or committed.

**Interfaces:**
- Consumes: local private SOXL environment file and the completed feature commits.
- Produces: six encrypted repository secrets, updated public `main`, one unchanged-data validation run, and one labeled activation email.

- [ ] **Step 1: Upgrade the installed skill atomically**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-agent.ps1
python -m pytest tests/unit/test_skill.py -q
```

Expected: installer reports the canonical installed path and skill tests PASS.

- [ ] **Step 2: Load the existing SOXL SMTP settings without printing values**

Use a PowerShell hashtable parser in the same shell process that performs secret writes:

```powershell
$sourcePath = 'C:\Users\SKYDI\Documents\Codex\2026-06-27\im\work\Intraday Trading Strategy Export 2026-06-27\.env.stock_alerts.local'
$settings = @{}
Get-Content -LiteralPath $sourcePath | ForEach-Object {
    if ($_ -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        $settings[$matches[1]] = $matches[2]
    }
}
$required = @('ALERT_SMTP_HOST','ALERT_SMTP_PORT','ALERT_SMTP_USER','ALERT_SMTP_PASSWORD','ALERT_EMAIL_FROM')
foreach ($name in $required) {
    if ([string]::IsNullOrWhiteSpace($settings[$name])) { throw "Missing private setting: $name" }
}
```

Expected: no setting values are written to stdout.

- [ ] **Step 3: Write the encrypted GitHub Actions secrets**

In the same PowerShell process, pipe values directly to `gh secret set`:

```powershell
$repo = 'skydiver1118/semipulse-sentinel'
$secretMap = [ordered]@{
    SEMIPULSE_SMTP_HOST = $settings['ALERT_SMTP_HOST']
    SEMIPULSE_SMTP_PORT = $settings['ALERT_SMTP_PORT']
    SEMIPULSE_SMTP_USER = $settings['ALERT_SMTP_USER']
    SEMIPULSE_SMTP_PASSWORD = $settings['ALERT_SMTP_PASSWORD']
    SEMIPULSE_EMAIL_FROM = $settings['ALERT_EMAIL_FROM']
    SEMIPULSE_EMAIL_TO = '1118xmb@gmail.com'
}
foreach ($item in $secretMap.GetEnumerator()) {
    $item.Value | gh secret set $item.Key --repo $repo
    if ($LASTEXITCODE -ne 0) { throw "Failed to set secret: $($item.Key)" }
}
gh secret list --repo $repo
```

Expected: the six secret names are listed; values are never returned by GitHub.

- [ ] **Step 4: Port the reviewed commits onto the public release branch**

Create a clean temporary worktree from the current remote main, then cherry-pick only commits created after the pre-feature baseline `9192859`:

```powershell
git fetch origin main
$releasePath = 'C:\Users\SKYDI\Documents\Codex\2026-07-18\semi-monitor-agent-create-a-new\.worktrees\semipulse-public-alert'
if (Test-Path -LiteralPath $releasePath) { throw "Release path already exists: $releasePath" }
git worktree add -b semipulse-public-alert-release $releasePath origin/main
$featureCommits = @(git rev-list --reverse '9192859..feature/semipulse-sentinel')
if ($featureCommits.Count -lt 3) { throw 'Expected design and implementation commits are missing.' }
git -C $releasePath cherry-pick $featureCommits
```

Run the full tests and verifier in the release worktree, then push fast-forward:

```powershell
Push-Location $releasePath
try {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Release tests failed.' }
    python scripts/verify_workflow.py .github/workflows/nightly-report.yml
    if ($LASTEXITCODE -ne 0) { throw 'Release workflow verification failed.' }
    git push origin HEAD:main
    if ($LASTEXITCODE -ne 0) { throw 'Release push failed.' }
}
finally {
    Pop-Location
}
```

Expected: push succeeds without force and remote `main` points to the reviewed release commit.

- [ ] **Step 5: Dispatch and verify the no-new-data path**

```powershell
gh workflow run nightly-report.yml --repo skydiver1118/semipulse-sentinel --ref main
$runId = gh run list --repo skydiver1118/semipulse-sentinel --workflow nightly-report.yml --limit 1 --json databaseId --jq '.[0].databaseId'
gh run watch $runId --repo skydiver1118/semipulse-sentinel --exit-status
gh run view $runId --repo skydiver1118/semipulse-sentinel --json conclusion,jobs,url
```

Expected on the current weekend: build concludes successfully with `decision=unchanged`; Pages deploy and notify jobs are skipped; the existing report remains HTTP 200 and retains its prior `market_as_of`.

- [ ] **Step 6: Verify the canonical report remains available**

Fetch both URLs with a cache-busting query, require HTTP 200, parse JSON, and confirm agent identity, eight charts, freshness, and coverage. Do not require the new schedule field until the next advancing market session deploys a new report.

- [ ] **Step 7: Send one labeled activation email through the reused sender**

Load the current canonical JSON, set the notifier’s non-secret summary environment variables, map the private SOXL SMTP values to the six `SEMIPULSE_*` variables only for this child process, and run:

```powershell
$sourcePath = 'C:\Users\SKYDI\Documents\Codex\2026-06-27\im\work\Intraday Trading Strategy Export 2026-06-27\.env.stock_alerts.local'
$settings = @{}
Get-Content -LiteralPath $sourcePath | ForEach-Object {
    if ($_ -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        $settings[$matches[1]] = $matches[2]
    }
}
$cacheBust = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$report = Invoke-RestMethod -Uri "https://skydiver1118.github.io/semipulse-sentinel/report.json?activation=$cacheBust"
$names = @(
    'SEMIPULSE_SMTP_HOST','SEMIPULSE_SMTP_PORT','SEMIPULSE_SMTP_USER',
    'SEMIPULSE_SMTP_PASSWORD','SEMIPULSE_EMAIL_FROM','SEMIPULSE_EMAIL_TO',
    'SEMIPULSE_MARKET_AS_OF','SEMIPULSE_REGIME','SEMIPULSE_CONFIDENCE',
    'SEMIPULSE_COVERAGE','SEMIPULSE_DASHBOARD_URL'
)
$saved = @{}
foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    $env:SEMIPULSE_SMTP_HOST = $settings['ALERT_SMTP_HOST']
    $env:SEMIPULSE_SMTP_PORT = $settings['ALERT_SMTP_PORT']
    $env:SEMIPULSE_SMTP_USER = $settings['ALERT_SMTP_USER']
    $env:SEMIPULSE_SMTP_PASSWORD = $settings['ALERT_SMTP_PASSWORD']
    $env:SEMIPULSE_EMAIL_FROM = $settings['ALERT_EMAIL_FROM']
    $env:SEMIPULSE_EMAIL_TO = '1118xmb@gmail.com'
    $env:SEMIPULSE_MARKET_AS_OF = [string]$report.market_as_of
    $env:SEMIPULSE_REGIME = [string]$report.executive_summary.regime
    $env:SEMIPULSE_CONFIDENCE = [string]$report.executive_summary.confidence
    $percent = [decimal]$report.coverage.coverage_ratio * 100
    $env:SEMIPULSE_COVERAGE = '{0}/{1} ({2:N1}%)' -f $report.coverage.covered_count,$report.coverage.watchlist_count,$percent
    $env:SEMIPULSE_DASHBOARD_URL = 'https://skydiver1118.github.io/semipulse-sentinel/'
    python -m semipulse_sentinel notify --json
    if ($LASTEXITCODE -ne 0) { throw 'Activation email failed.' }
}
finally {
    foreach ($name in $names) {
        [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process')
    }
}
```

Use subject `[SemiPulse] Report ready — <market_as_of>` and the canonical dashboard link. Expected: safe JSON `{"market_as_of":"<date>","status":"sent"}` without sender, recipient, password, or raw SMTP details.

- [ ] **Step 8: Remove temporary process variables and release worktree**

The activation command restores every process environment value in its `finally` block. Confirm the release worktree is clean, then remove that exact validated worktree path and delete only the merged temporary branch:

```powershell
if ((git -C $releasePath status --porcelain)) { throw 'Release worktree is dirty.' }
git worktree remove $releasePath
git branch -d semipulse-public-alert-release
git worktree prune
```

- [ ] **Step 9: Record the next-session expectation**

The next successful weekday run whose candidate `market_as_of` is newer than the published value must deploy the eight-chart Page and send exactly one automatic email. A holiday or duplicate provider date must retain the current Page and send no automatic email.
