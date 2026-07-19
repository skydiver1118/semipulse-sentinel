# SemiPulse Daily Decision Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a newly computed, explained, decision-oriented eight-chart semiconductor report after every completed trading session while retaining the last good report when market data has not advanced.

**Architecture:** Reactivate the existing `semipulse-report-v1` market-data pipeline and make each chart's stable purpose explicit alongside its current deterministic interpretation. Route the trading-session-gated GitHub Actions workflow through the daily build, validation, date-comparison, Pages deployment, and fixed-recipient notification commands; source-copy code remains non-production compatibility code.

**Tech Stack:** Python 3.11, pandas, NumPy, Matplotlib SVG, yfinance, Jinja2, pytest, GitHub Actions, GitHub Pages, SMTP STARTTLS.

## Global Constraints

- Run automatically at `20 18 * * 1-5` in `America/New_York` and only after a completed XNYS trading session.
- Publish schema `semipulse-report-v1` with exactly eight ordered SVG charts derived from one `market_as_of` session.
- Deploy and email only when `candidate.market_as_of > published.market_as_of`; retain the last valid report for equal, regressed, failed, or partial candidates.
- Hard-lock the only recipient to `1118xmb@gmail.com`; do not read a recipient secret.
- Public HTML, JSON, and email must not contain the original poster's identity or an author field.
- Keep all interpretation conditional, research-only, non-personalized, and free of order execution or promises.

---

### Task 1: Make every chart's purpose and current meaning explicit

**Files:**
- Modify: `src/semipulse_sentinel/models.py`
- Modify: `src/semipulse_sentinel/pipeline.py`
- Modify: `src/semipulse_sentinel/report.py`
- Modify: `src/semipulse_sentinel/templates/report.html.j2`
- Modify: `src/semipulse_sentinel/static/report.css`
- Modify: `tests/unit/test_report.py`
- Modify: `tests/integration/test_pipeline.py`

**Interfaces:**
- Consumes: `ChartSpec.description: str` from `src/semipulse_sentinel/charts.py` and `ChartInsight.interpretation` / `trading_relevance` from `src/semipulse_sentinel/models.py`.
- Produces: `ReportChart.purpose: str` and public `charts[].purpose`, rendered under “What this chart measures.”

- [ ] **Step 1: Write failing model and end-to-end report tests**

Add `purpose="The stable purpose."` to the `ReportChart` fixture in `test_report_chart_is_immutable_and_pairs_matching_ids`, assert `chart.purpose`, and add a rejection for whitespace-only purpose:

```python
assert chart.purpose == "The stable purpose."
with pytest.raises(ValueError, match="purpose"):
    replace(chart, purpose="   ")
```

In the successful pipeline integration test, load `report.json` and assert:

```python
assert len(report["charts"]) == 8
assert all(chart["purpose"].strip() for chart in report["charts"])
html = (site / "index.html").read_text(encoding="utf-8")
assert html.count("What this chart measures") == 8
assert html.count("What it means now") == 8
assert html.count("How it may inform trading decisions") == 8
assert "Trading decision summary" in html
```

- [ ] **Step 2: Run the focused tests and verify the new contract fails**

Run:

```powershell
python -m pytest tests/unit/test_report.py tests/integration/test_pipeline.py -q
```

Expected: FAIL because `ReportChart` has no `purpose` field and the current HTML uses the old headings.

- [ ] **Step 3: Add purpose to the immutable model and public schema**

Add `purpose: str` after `title` on `ReportChart`, validate it in `__post_init__`, pass `spec.description` from `_report_charts`, and serialize it in each chart object:

```python
if not self.purpose.strip():
    raise ValueError("chart purpose must not be empty")
```

```python
ReportChart(
    chart_id=artifact.chart_id,
    title=spec.title,
    purpose=spec.description,
    # existing artifact and insight fields
)
```

```python
"purpose": chart.purpose,
```

Require nonempty `purpose`, `interpretation`, and `trading_relevance` strings in `validate_site`'s per-chart validation so handcrafted or partial JSON cannot pass.

- [ ] **Step 4: Rename the summary and chart explanation headings**

Update the template to use:

```html
<h2 id="summary-heading">Trading decision summary</h2>
<p class="posture"><strong>Current research posture:</strong> {{ report.executive_summary.posture }}</p>
```

Before evidence on every chart card render:

```html
<section aria-labelledby="{{ chart.chart_id }}-purpose">
  <h3 id="{{ chart.chart_id }}-purpose">What this chart measures</h3>
  <p>{{ chart.purpose }}</p>
</section>
```

Rename “Interpretation” to “What it means now” and “Conditional trading relevance” to “How it may inform trading decisions.” Keep evidence and counter-signal visible. Adjust only the existing `.chart-analysis` rules needed for five analysis panels to wrap cleanly.

- [ ] **Step 5: Run report, pipeline, interpretation, and chart tests**

Run:

```powershell
python -m pytest tests/unit/test_report.py tests/unit/test_interpret.py tests/unit/test_charts.py tests/integration/test_pipeline.py -q
```

Expected: PASS with exactly eight purposes and all current safety-language tests intact.

- [ ] **Step 6: Commit the chart explanation contract**

```powershell
git add src/semipulse_sentinel/models.py src/semipulse_sentinel/pipeline.py src/semipulse_sentinel/report.py src/semipulse_sentinel/templates/report.html.j2 src/semipulse_sentinel/static/report.css tests/unit/test_report.py tests/integration/test_pipeline.py
git commit -m "feat: explain every daily chart"
```

### Task 2: Hard-lock the daily report email and exclude source attribution

**Files:**
- Modify: `src/semipulse_sentinel/notifications.py`
- Modify: `tests/unit/test_notifications.py`
- Modify: `tests/integration/test_cli.py`

**Interfaces:**
- Consumes: `ReportAlert.from_environment(environment)` with market date, regime, confidence, coverage, and dashboard URL.
- Produces: `SmtpSettings.from_environment(environment)` whose `recipient` is always `1118xmb@gmail.com`, plus the existing `notify` CLI result.

- [ ] **Step 1: Write failing fixed-recipient and redaction tests**

Change the daily settings test to omit `SEMIPULSE_EMAIL_TO`, inject a hostile value when desired, and assert:

```python
settings = SmtpSettings.from_environment(environment)
assert settings.recipient == ALERT_RECIPIENT == "1118xmb@gmail.com"
```

For the generated plain-text and HTML alternatives assert:

```python
payload = message.as_string()
assert message["To"] == "1118xmb@gmail.com"
assert "View report:" in payload
assert "Source post" not in payload
assert "author" not in payload.lower()
assert "\u4e91\u8d77\u5343\u767e\u5ea6" not in payload
```

Update the CLI notification integration fixture so it supplies no recipient environment variable and still sends successfully through the fake SMTP boundary.

- [ ] **Step 2: Run notification tests and verify recipient loading fails**

Run:

```powershell
python -m pytest tests/unit/test_notifications.py tests/integration/test_cli.py -q
```

Expected: FAIL because daily `from_environment` currently requires `SEMIPULSE_EMAIL_TO`.

- [ ] **Step 3: Hard-lock the shared daily recipient**

Rename the public constant and preserve a compatibility alias for non-production source-copy tests:

```python
ALERT_RECIPIENT = "1118xmb@gmail.com"
SOURCE_ALERT_RECIPIENT = ALERT_RECIPIENT
```

Set `recipient=ALERT_RECIPIENT` inside `SmtpSettings.from_environment` and keep the message body limited to market date, regime, confidence, coverage, permanent link, and research disclaimer.

- [ ] **Step 4: Run notification and CLI tests**

Run:

```powershell
python -m pytest tests/unit/test_notifications.py tests/integration/test_cli.py -q
```

Expected: PASS; the fake SMTP message has only the fixed recipient and contains no source attribution.

- [ ] **Step 5: Commit the email boundary**

```powershell
git add src/semipulse_sentinel/notifications.py tests/unit/test_notifications.py tests/integration/test_cli.py
git commit -m "fix: hard-lock daily report recipient"
```

### Task 3: Route production through the trading-session daily pipeline

**Files:**
- Modify: `.github/workflows/nightly-report.yml`
- Modify: `scripts/verify_workflow.py`
- Modify: `tests/unit/test_workflow.py`
- Modify: `tests/unit/test_cli.py`
- Modify: `tests/unit/test_contracts.py`

**Interfaces:**
- Consumes: CLI commands `check-market-session`, `build`, `validate`, `decide-publication`, and `notify`.
- Produces: workflow outputs `has_new_data`, `market_as_of`, `regime`, `confidence`, and `coverage`; deploy and notify gates based on `has_new_data`.

- [ ] **Step 1: Rewrite workflow tests for the daily command sequence**

Assert the build step order is exactly:

```python
[
    "Checkout",
    "Set up Python",
    "Install locked dependencies",
    "Install project",
    "Verify workflow",
    "Run offline tests",
    "Check market session",
    "Build report",
    "Validate site",
    "Fetch published report",
    "Decide publication",
    "Configure Pages",
    "Upload Pages artifact",
]
```

Require the session condition on build, validate, fetch, and publication steps; require daily commands exactly once; require `MPLBACKEND: Agg`; require the five daily outputs; require `notify --json`; and assert `SEMIPULSE_EMAIL_TO`, source post ID, source title, and image count are absent from the workflow.

- [ ] **Step 2: Run workflow tests and verify they fail against source-copy production**

Run:

```powershell
python -m pytest tests/unit/test_workflow.py tests/unit/test_cli.py tests/unit/test_contracts.py -q
```

Expected: FAIL because production currently invokes source-copy commands and emits source outputs.

- [ ] **Step 3: Switch the workflow to daily build and publication commands**

Keep the current 6:20 PM schedule and XNYS gate. Set `MPLBACKEND: Agg`. Replace source outputs with:

```yaml
outputs:
  has_new_data: "${{ steps.publication.outputs.has_new_data }}"
  market_as_of: "${{ steps.publication.outputs.market_as_of }}"
  regime: "${{ steps.publication.outputs.regime }}"
  confidence: "${{ steps.publication.outputs.confidence }}"
  coverage: "${{ steps.publication.outputs.coverage }}"
```

Use the existing manual-dispatch/session condition for the four network/publication steps. Run:

```yaml
python -m semipulse_sentinel build --watchlist config/watchlist.csv --output candidate-site --json
python -m semipulse_sentinel validate --site candidate-site --json
python -m semipulse_sentinel decide-publication --candidate candidate-site/report.json --published published-report.json --github-output "$GITHUB_OUTPUT" --json
```

The notification environment passes `SEMIPULSE_MARKET_AS_OF`, `SEMIPULSE_REGIME`, `SEMIPULSE_CONFIDENCE`, `SEMIPULSE_COVERAGE`, and the permanent dashboard URL, then runs `python -m semipulse_sentinel notify --json`.

- [ ] **Step 4: Align the fail-closed workflow verifier**

Update `scripts/verify_workflow.py` to accept only the daily step names, commands, outputs, session gates, secret boundary, pinned action SHAs, exact permissions, and job order. Explicitly reject `build-source`, `validate-source`, `decide-source-publication`, `notify-source`, `SEMIPULSE_EMAIL_TO`, and every `SEMIPULSE_SOURCE_*` variable in production YAML.

- [ ] **Step 5: Run the workflow verifier and tests**

Run:

```powershell
python scripts/verify_workflow.py .github/workflows/nightly-report.yml
python -m pytest tests/unit/test_workflow.py tests/unit/test_cli.py tests/unit/test_contracts.py tests/unit/test_market_session.py tests/unit/test_publication.py -q
```

Expected: verifier exits 0 and all tests pass. Mutation tests continue to reject reordered builds, mutable actions, extra permissions, unsafe YAML, extra secrets, and missing gates.

- [ ] **Step 6: Commit the production workflow**

```powershell
git add .github/workflows/nightly-report.yml scripts/verify_workflow.py tests/unit/test_workflow.py tests/unit/test_cli.py tests/unit/test_contracts.py
git commit -m "feat: publish every completed trading session"
```

### Task 4: Update the operator-facing agent and documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/methodology.md`
- Modify: `docs/operations.md`
- Modify: `skill/semipulse-sentinel/SKILL.md`
- Modify: `skill/semipulse-sentinel/references/operations.md`
- Modify: `tests/unit/test_skill.py`
- Modify: `tests/unit/test_workflow.py`
- Modify: `tests/integration/test_packaging.py`

**Interfaces:**
- Consumes: public `semipulse-report-v1` JSON and the daily CLI/workflow commands from Tasks 1–3.
- Produces: operator instructions that review, refresh, and verify the daily report without referring to the forum poster.

- [ ] **Step 1: Write failing documentation and packaged-skill tests**

Require the README, methodology, operations guide, skill, and skill operations reference to name `semipulse-report-v1`, all eight chart purposes, `market_as_of`, `Trading decision summary`, the 6:20 PM Eastern schedule, the XNYS gate, last-good retention, `1118xmb@gmail.com`, and the daily `build` / `validate` / `decide-publication` / `notify` commands where applicable.

Add a forbidden public-language assertion over those files:

```python
forbidden = ("Wenxuecity", "source-copy", "exact author", "\u4e91\u8d77\u5343\u767e\u5ea6")
for path in public_files:
    text = path.read_text(encoding="utf-8")
    assert all(term.casefold() not in text.casefold() for term in forbidden)
```

Update the packaging probe to assert the wheel contains the daily report template, CSS, skill, operations reference, and watchlist resources.

- [ ] **Step 2: Run documentation and packaging tests and verify they fail**

Run:

```powershell
python -m pytest tests/unit/test_skill.py tests/unit/test_workflow.py tests/integration/test_packaging.py -q
```

Expected: FAIL because public docs and the installed agent currently describe the source-copy report.

- [ ] **Step 3: Rewrite public docs around the daily decision report**

Document the eight chart questions, per-chart explanation structure, deterministic composite, freshness/coverage boundaries, trading-session schedule, last-good fallback, fixed-recipient email, local daily commands, manual workflow dispatch, and research disclaimer. Remove source-post and author discovery instructions from all operator-facing content.

The skill must direct reviews to canonical `report.json`, report `market_as_of`, freshness, coverage, regime, confidence, supports, challenges, and change triggers, and use the authorized refresh command:

```powershell
gh workflow run nightly-report.yml --repo skydiver1118/semipulse-sentinel --ref main
```

- [ ] **Step 4: Run documentation, skill, and packaging tests**

Run:

```powershell
python -m pytest tests/unit/test_skill.py tests/unit/test_workflow.py tests/integration/test_packaging.py -q
```

Expected: PASS; packaged resources describe only the daily public report.

- [ ] **Step 5: Install the updated skill locally and verify exact packaged bytes**

Run:

```powershell
powershell -NoProfile -File scripts/install-agent.ps1 -RepositoryRoot .
python -m pytest tests/unit/test_skill.py tests/windows/test_install_agent.ps1 -q
```

Expected: the installed `semipulse-sentinel` skill matches the repository release and tests pass without changing any unrelated installed skill.

- [ ] **Step 6: Commit the agent and documentation**

```powershell
git add README.md docs/methodology.md docs/operations.md skill/semipulse-sentinel/SKILL.md skill/semipulse-sentinel/references/operations.md tests/unit/test_skill.py tests/unit/test_workflow.py tests/integration/test_packaging.py
git commit -m "docs: operate the daily decision report"
```

### Task 5: Verify, release, and prove last-good behavior

**Files:**
- Modify only if verification exposes a defect: files already named in Tasks 1–4.

**Interfaces:**
- Consumes: the complete candidate branch and GitHub repository `skydiver1118/semipulse-sentinel`.
- Produces: a passing release on `main`, a live daily report, one new-session email, and an unchanged run with deploy/email skipped.

- [ ] **Step 1: Run formatting, static checks, and the full local suite**

Run:

```powershell
git diff --check
python -m ruff check .
python -m mypy src
python -m pytest -q
python scripts/verify_workflow.py .github/workflows/nightly-report.yml
```

Expected: all commands exit 0. If the monolithic pytest process is terminated by the Windows wrapper, run `tests/unit`, `tests/integration`, and `tests/windows` separately and require every split to pass.

- [ ] **Step 2: Build and validate a real candidate**

Run:

```powershell
python -m semipulse_sentinel build --watchlist config/watchlist.csv --output site --json
python -m semipulse_sentinel validate --site site --json
```

Expected: schema `semipulse-report-v1`, exactly eight charts, nonblank purpose/interpretation/relevance fields, and a `market_as_of` equal to the latest provider session available.

- [ ] **Step 3: Audit the generated public files for forbidden attribution**

Run:

```powershell
rg -n -i "Wenxuecity|source-copy|exact author|\u4e91\u8d77\u5343\u767e\u5ea6|\"author\"" site/index.html site/report.json
```

Expected: no matches. Verify all eight `charts/*.svg` paths in `report.json` exist and their SHA-256 hashes match.

- [ ] **Step 4: Review the cumulative diff and commit any verification-only fixes**

Run:

```powershell
git status --short
git diff HEAD~4 --check
git log -5 --oneline
```

Expected: only intended files changed and the working tree is clean after any narrowly scoped fix commit.

- [ ] **Step 5: Merge the feature branch to `main` and push**

From the primary checkout, fast-forward `main` to `feature/semipulse-sentinel`, push `main`, and confirm:

```powershell
git ls-remote origin refs/heads/main
```

Expected: the remote main SHA equals the verified release SHA.

- [ ] **Step 6: Dispatch and monitor the activation run**

Run:

```powershell
gh workflow run nightly-report.yml --repo skydiver1118/semipulse-sentinel --ref main
gh run list --repo skydiver1118/semipulse-sentinel --workflow nightly-report.yml --limit 5
```

Monitor the selected run through completion. Expected: offline tests, real build, site validation, new-date decision, Pages deployment, and fixed-recipient notification all succeed.

- [ ] **Step 7: Verify the live report**

Fetch the permanent HTML, JSON, and all eight chart URLs with cache busting. Expected: `semipulse-report-v1`; latest completed `market_as_of`; eight unique ordered chart IDs; nonblank purpose, interpretation, decision relevance, evidence, and counter-signal; visible Trading decision summary; matching embedded and standalone JSON; valid hashes; and no poster identity or author field.

- [ ] **Step 8: Dispatch and monitor an unchanged run**

Dispatch the same workflow again after the first deployment. Expected: `decide-publication` reports `unchanged`; configure, upload, deploy, and notify are skipped; the live report remains byte-consistent for the same market date.

- [ ] **Step 9: Record final evidence**

Capture the release SHA, activation and unchanged GitHub Actions URLs, live report URL, `market_as_of`, chart count, recipient policy, and test totals in the final handoff. Do not expose SMTP credentials or claim mailbox receipt; report only that the GitHub notification step succeeded.
