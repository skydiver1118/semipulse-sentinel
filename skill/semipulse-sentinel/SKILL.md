---
name: semipulse-sentinel
description: Use when a user asks for SemiPulse, a semi monitor, the semiconductor nightly report, a refresh of the eight charts, or interpretation of the semiconductor dashboard.
---

# SemiPulse Sentinel

Review the deterministic daily semiconductor decision report. Read
`references/operations.md` before locating, explaining, or refreshing it.

## Locate and verify

Prefer canonical public `report.json`. Use a local site only after
`python -m semipulse_sentinel validate --site site --json` succeeds. A failed
fetch is an operational failure, not an empty report. It is not proof of staleness.

Require `semipulse-report-v1`. State `market_as_of`, freshness, coverage,
regime, confidence, strongest `supports`, strongest `challenges`, change triggers,
limitations, and the permanent report link. Keep freshness and
coverage separate. Never describe stale data as current or partial coverage as
broad or complete.

## Review the Trading decision summary and charts

Use the JSON fields, not inferences from SVG pixels or recalled prices. Review
all eight purposes: **Semiconductor complex performance**; **Relative strength
versus QQQ**; **Watchlist breadth**; **Equal-weight participation**; **Momentum
leaders and laggards**; **Multi-horizon trend heatmap**; **Volatility and
peak-distance regime**; and **Risk/reward map**.

For each chart, separate **What this chart measures**, **Evidence**, **What it
means now**, **How it may inform trading decisions**, and **Counter-signal**.
Preserve missing-series, delayed, low-confidence, leveraged-ETF, and provider
caveats. If JSON is absent, invalid, or inconsistent, say the report cannot be
interpreted; never reconstruct it.

## Refresh only with authority

Automatic runs start Monday through Friday at 6:20 PM Eastern and use an XNYS
completed-session gate. An unchanged or failed candidate keeps the last
successful report and sends no email. A new deployed report alerts only
`1118xmb@gmail.com`.

Do not dispatch unless the user explicitly requests a refresh or the active
conversation already grants it. Honor conditions attached to refresh authority.
For "refresh if stale," establish staleness from valid JSON first.
A request conditioned on bypassing validation, publishing partial output, or
changing the recipient is not usable refresh authority; refuse those conditions.

When authorized, run:

```powershell
gh workflow run nightly-report.yml --repo skydiver1118/semipulse-sentinel --ref main
```

Monitor the selected run and confirm the deployed JSON passes schema,
`market_as_of`, freshness, coverage, and eight-chart checks. Never weaken
validation, forge timestamps, edit generated output, or replace a failed build
with partial charts.

## Research boundary

Frame output as research only. Never place orders, connect to a broker, promise
returns, or provide individualized financial advice.
