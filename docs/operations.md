# Operations

This runbook covers the live repository `skydiver1118/semipulse-sentinel` and
the daily `semipulse-report-v1` decision report. Canonical interfaces:

- `https://github.com/skydiver1118/semipulse-sentinel`
- `https://skydiver1118.github.io/semipulse-sentinel/`
- `https://skydiver1118.github.io/semipulse-sentinel/report.json`

The JSON is authoritative for `market_as_of`, freshness, coverage, the
**Trading decision summary**, and all chart explanations. A failed fetch is an
operational failure, not evidence of a neutral regime.

## Operator review checklist

Confirm schema `semipulse-report-v1`, then report `market_as_of`, freshness,
covered/watchlist counts and ratio, regime, confidence, strongest supports,
strongest challenges, change triggers, exclusions, limitations, and the
canonical link. Review all eight chart purposes:

1. **Semiconductor complex performance** - benchmark direction.
2. **Relative strength versus QQQ** - semiconductor leadership.
3. **Watchlist breadth** - moving-average participation.
4. **Equal-weight participation** - median constituent confirmation.
5. **Momentum leaders and laggards** - 20-session return distribution.
6. **Multi-horizon trend heatmap** - cross-horizon agreement and reversals.
7. **Volatility and peak-distance regime** - observed stress conditions.
8. **Risk/reward map** - return, volatility, and liquidity context.

For every card, verify the visible **What this chart measures**, **Evidence**,
**What it means now**, **How it may inform trading decisions**, and
**Counter-signal** sections against the corresponding flattened `charts[]`
fields. Keep freshness and coverage distinct and preserve the report's
limitations and risk warning.

## Schedule, XNYS gate, and last-good behavior

The workflow requests a run Monday through Friday at **6:20 PM Eastern** using
the timezone-aware schedule `20 18 * * 1-5` in `America/New_York`. The named
timezone handles daylight saving time. GitHub Actions scheduling is best
effort and may start late; public-repository schedules may be disabled after 60
days without activity, and forks begin with schedules disabled.

`check-market-session` uses the XNYS exchange calendar. A scheduled run
continues only when the New York date is a trading session and that session is
complete. A manual `workflow_dispatch` is the explicit recovery path and can
proceed outside the automatic gate, while the report's normal data-quality and
publication checks still apply.

If there is no new market data, deployment and email are skipped.

The daily sequence is `build`, `validate`, `decide-publication`, Pages deploy,
then `notify`. A validated later `market_as_of` deploys. The current public
schema can also migrate once to the daily schema without relaxing candidate
validation. An unchanged date skips deployment and email. Regressed dates,
invalid candidates, failed builds, and current-report failures fail closed, so
the last successful Page remains online rather than a blank or partial report.

Restore an inactive schedule and request a manual run with:

```powershell
gh workflow enable nightly-report.yml --repo skydiver1118/semipulse-sentinel
gh workflow run nightly-report.yml --repo skydiver1118/semipulse-sentinel --ref main
gh run list --repo skydiver1118/semipulse-sentinel --workflow nightly-report.yml --limit 5
```

Concurrency uses the `semipulse-pages` group with `cancel-in-progress: false`,
so overlapping runs are serialized. A newer run waits and cannot cancel an
older run after deployment but before its notification job finishes.

## Local daily verification

Use Python 3.11 or later from the repository root:

```powershell
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps --no-build-isolation .
python scripts/verify_workflow.py .github/workflows/nightly-report.yml
python -m pytest -q
python -m semipulse_sentinel doctor --watchlist config/watchlist.csv --site site --json
python -m semipulse_sentinel build --watchlist config/watchlist.csv --output candidate-site --json
python -m semipulse_sentinel validate --site candidate-site --json
python -m semipulse_sentinel decide-publication --candidate candidate-site/report.json --published published-report.json --github-output publication-output.txt --json
python -m semipulse_sentinel notify --json
```

`doctor` is offline. `build` is the explicit provider network boundary and is
failure-atomic. Do not upload a candidate unless `validate` succeeds.
`decide-publication` requires a validated candidate, the fetched public JSON,
and a GitHub-output path. `notify` is reserved for the post-deploy workflow; a
manual local call requires the documented SMTP and report-summary environment.

## GitHub Pages setup and recovery

Pages enablement is an out-of-band repository setting. Select **GitHub
Actions** as the Pages source. The build job has read-only repository and Pages
access; the separate deploy job receives only `pages: write` and
`id-token: write`.

After a deployment, verify HTTP 200 for the page and JSON. Require
`semipulse-report-v1`, the expected `market_as_of`, exactly eight chart records,
the **Trading decision summary**, valid freshness and coverage, and all chart
assets. Retry a Pages platform failure after artifact upload. Do not edit
generated output or weaken validation.

## Email delivery

The `notify` command runs only after a changed Pages deployment succeeds. Its
sole recipient is hard-locked in code to `1118xmb@gmail.com`; no recipient
secret is read. Configure these encrypted repository secrets:

- `SEMIPULSE_SMTP_HOST`
- `SEMIPULSE_SMTP_PORT`
- `SEMIPULSE_SMTP_USER`
- `SEMIPULSE_SMTP_PASSWORD`
- `SEMIPULSE_EMAIL_FROM`

No credentials are written to the repository, report, artifact, or logs. An
email failure does not roll back a successful report deployment.

## Exit codes

- **Exit code 0**: operation succeeded, including a skipped automatic gate.
- **Exit code 2**: configuration, input, or validation argument error.
- **Exit code 3**: publication was blocked by quality or site validation.
- **Exit code 4**: notification, build orchestration, or unexpected failure.

Research only - not individualized investment advice. Do not add broker
credentials, personal positions, or other private data to this public system.
