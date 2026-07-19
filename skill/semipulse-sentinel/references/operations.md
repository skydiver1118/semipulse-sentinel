# SemiPulse Sentinel operations

## Canonical interfaces

- Repository: `https://github.com/skydiver1118/semipulse-sentinel`
- Report: `https://skydiver1118.github.io/semipulse-sentinel/`
- Structured report: `https://skydiver1118.github.io/semipulse-sentinel/report.json`
- Default branch: `main`
- Workflow: `nightly-report.yml`
- Schedule: `20 18 * * 1-5` in `America/New_York` (6:20 PM Eastern,
  Monday through Friday)

Automatic runs use an XNYS `check-market-session` gate and continue only for a
completed trading session. Manual `workflow_dispatch` is the explicit recovery
path. The production sequence is `build`, `validate`, `decide-publication`,
Pages deploy, then `notify`. If there is no new market data, deployment and
email are skipped and the last successful report remains live. A newly deployed
report sends one link to `1118xmb@gmail.com`.

## Report fields and review order

Require schema `semipulse-report-v1`. The **Trading decision summary** and
`market_as_of` are authoritative. Report, in order:

- `market_as_of`;
- `freshness.state`, `freshness.evaluated_at`, latest and expected session, and
  expected lag, re-evaluating freshness at query time;
- `coverage.covered_count`, watchlist count, `coverage.coverage_ratio`,
  `coverage.missing_required`, exclusions, and material warnings;
- `executive_summary.regime`, `executive_summary.confidence`, score,
  `executive_summary.supports`, and `executive_summary.challenges`;
- what changed and `executive_summary.what_would_change_the_view` as change
  triggers;
- `limitations`, `risk_warning`, and the canonical link.

Keep freshness and coverage separate. Missing required inputs or coverage below
0.70 makes a candidate unpublishable. Coverage from 70% to below 90%, optional
gaps, warnings, or incomplete audit history cap confidence. Never label stale
data current or partial coverage complete.

## Eight chart purposes

Review all ordered `charts[]` records:

1. **Semiconductor complex performance** - benchmark direction and SOXL risk.
2. **Relative strength versus QQQ** - industry leadership versus broad tech.
3. **Watchlist breadth** - participation above three moving averages.
4. **Equal-weight participation** - median constituent confirmation of SMH.
5. **Momentum leaders and laggards** - 20-session return distribution.
6. **Multi-horizon trend heatmap** - return/trend agreement and reversals.
7. **Volatility and peak-distance regime** - realized stress and optional VIX.
8. **Risk/reward map** - return, volatility, and liquidity context.

Each record has flattened `purpose`, `headline`, `signal`, `evidence`,
`interpretation`, `trading_relevance`, `counter_signal`, and `notes`. Summarize
those fields through the visible headings **What this chart measures**,
**Evidence**, **What it means now**, **How it may inform trading decisions**,
and **Counter-signal**. Do not infer meaning from SVG pixels.

## Authorized refresh

Only dispatch with explicit authority in the active conversation. Honor
attached conditions. Missing, invalid, or unreachable JSON is an operational
failure, not proof of staleness:

```powershell
gh workflow run nightly-report.yml --repo skydiver1118/semipulse-sentinel --ref main
gh run list --repo skydiver1118/semipulse-sentinel --workflow nightly-report.yml --limit 5
```

Monitor the selected run. After success, fetch the page and JSON with cache
busting. Confirm schema, `market_as_of`, freshness, coverage, the **Trading
decision summary**, and exactly eight chart records. Do not enable settings,
lower quality gates, forge timestamps, modify generated files, or bypass
validation to obtain a green run.

## Local verification

```powershell
python -m semipulse_sentinel doctor --watchlist config/watchlist.csv --site site --json
python -m semipulse_sentinel build --watchlist config/watchlist.csv --output site --json
python -m semipulse_sentinel validate --site site --json
python -m semipulse_sentinel decide-publication --candidate site/report.json --published published-report.json --github-output publication-output.txt --json
python -m semipulse_sentinel notify --json
```

The last command is post-deploy only and requires configured SMTP/report
environment. The recipient remains fixed at `1118xmb@gmail.com`.

## Research boundary

SemiPulse Sentinel is research-only decision support. It does not place orders,
connect to brokerage accounts, promise returns, or give individualized advice.
Report opposing evidence and confidence caps prominently.
