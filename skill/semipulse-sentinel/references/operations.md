# SemiPulse Sentinel operations

## Canonical interfaces

- Repository: `https://github.com/skydiver1118/semipulse-sentinel`
- Report: `https://skydiver1118.github.io/semipulse-sentinel/`
- Structured report: `https://skydiver1118.github.io/semipulse-sentinel/report.json`
- Default branch: `main`
- Workflow: `nightly-report.yml`
- Schedule: `0 18 * * *` in `America/New_York` (6:00 PM Eastern every
  calendar day; GitHub Actions may start late)

The public URLs are authoritative only after a successful deployment. A fetch
failure is an operational failure, not evidence of a neutral market regime.

## Local discovery

Run from the repository root:

```powershell
python -m semipulse_sentinel doctor --json
python -m semipulse_sentinel validate --site site --json
```

`doctor` is offline. Inspect its `site_state`, dependency versions, watchlist
count and source-status counts, and schedule. Read `site/report.json` only when
the site exists and validation succeeds. If no local repository is available,
fetch the canonical structured-report URL directly and require HTTP 200 and
valid JSON.

## Report fields

Use the JSON fields directly:

- `market_as_of` is the market date; never substitute file mtime or fetch time.
- `freshness.state`, `freshness.expected_market_session`,
  `freshness.latest_market_session`, `freshness.expected_session_lag`, and
  `freshness.evaluated_at` record freshness when the report was built. At query time,
  compare `latest_market_session` with the expected completed session in
  `America/New_York`: use the previous weekday on weekends and before 16:15 ET,
  otherwise use the current weekday. Count intervening weekdays. Reclassify as
  current for zero lag and at most three calendar days of age, delayed for at
  most one-session lag and three calendar days, and stale otherwise. This
  heuristic has no exchange-holiday calendar, so disclose holiday uncertainty.
- `coverage.covered_count`, `coverage.watchlist_count`, and
  `coverage.coverage_ratio` quantify usable watchlist coverage. Also disclose
  exclusions, `coverage.missing_required`, `coverage.missing_optional`, and
  warnings when material. A ratio below 0.70 or any `missing_required` makes the
  report unpublishable and uninterpretable. Coverage from 70% to below 90% is
  partial and caps confidence at medium, even when the data are fresh.
- `executive_summary.regime`, `executive_summary.confidence`, and
  `executive_summary.score` state the deterministic composite result.
- `executive_summary.supports`, `executive_summary.challenges`,
  `executive_summary.what_changed`, and
  `executive_summary.what_would_change_the_view` provide balanced evidence.
- Each `charts[]` item stores flattened `headline`, `signal`, `evidence`,
  `interpretation`, `trading_relevance`, `counter_signal`, and `notes` fields;
  summarize those fields rather than inferring meaning from SVG pixels.
- Always preserve `limitations`, `risk_warning`, and provenance. The recovered
  watchlist is labeled `recovered_inference`; its original upload identity is
  not verified.

A useful summary reports, in order: market date; freshness; coverage; regime
and confidence; strongest support; strongest challenge; what changed or would
change the view; exclusions/limitations; and the canonical report link.

## Authorized refresh

Only dispatch when the user explicitly requests a refresh or has already given
that authority in the active conversation. Honor attached conditions. For a
conditional request such as "refresh if stale," first establish that condition
from valid report JSON; missing, invalid, or unreachable JSON is an operational
failure, not evidence of staleness:

```powershell
gh workflow run nightly-report.yml --repo skydiver1118/semipulse-sentinel --ref main
gh run list --repo skydiver1118/semipulse-sentinel --workflow nightly-report.yml --limit 5
```

Monitor the selected run through completion. After success, fetch both the
report page and `report.json` with a cache-busting query parameter. Confirm the
agent identity, eight chart records, expected schedule, current build metadata,
freshness, and coverage. A failed build intentionally leaves the prior
known-good Pages deployment live; do not imply that the old page refreshed.

Do not enable or change repository settings, lower the 70% publication gate,
forge timestamps, modify generated files, or bypass validation merely to obtain
a green run. Escalate provider, permission, or Pages failures as operational
limitations.

## Research boundary

SemiPulse Sentinel is research-only decision support. It does not place orders,
connect to brokerage accounts, promise returns, or give individualized
financial advice. Report opposing evidence and confidence caps prominently.
