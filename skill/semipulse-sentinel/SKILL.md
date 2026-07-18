---
name: semipulse-sentinel
description: Use when a user asks for SemiPulse, a semi monitor, the semiconductor nightly report, a refresh of the eight charts, or interpretation of the semiconductor dashboard.
---

# SemiPulse Sentinel

Inspect the deterministic eight-chart semiconductor research report. Read
`references/operations.md` before locating, summarizing, or refreshing it.

## Locate the report

1. Prefer the canonical local repository when it is available. From its root,
   run `python -m semipulse_sentinel doctor --json` and inspect the structured
   result before reading `site/report.json`.
2. Use the canonical public `report.json` when local access is unavailable or
   the local site is missing. Do not treat a failed fetch as an empty report.
3. Treat the report JSON as the source of truth. Never infer chart meaning from SVG pixels,
   colors, filesystem modification times, or market prices recalled from elsewhere.

## Summarize the evidence

State these items explicitly: `market_as_of`, freshness state and expected
session lag, covered/watchlist counts and `coverage_ratio`, composite `regime`
and `confidence`, strongest `supports`, strongest `challenges`, change triggers,
material exclusions or `limitations`, and the canonical report link.

Re-evaluate freshness at query time with the rule in the operations reference;
the stored state describes build time. Keep freshness and coverage separate:
current data can be partial, and broad coverage can still be stale.

Describe observations separately from deterministic interpretation. Preserve
delayed, stale, low-confidence, missing-series, and recovered-watchlist caveats.
Never describe stale data as current or partial coverage as broad or complete. If the JSON is absent,
invalid, or internally inconsistent, say that the report cannot be interpreted
and stop rather than reconstructing it.

## Refresh only with authority

Do not dispatch unless the user explicitly asks for a refresh or the current
conversation already grants refresh authority. Honor conditions attached to refresh authority:
for "refresh if stale," establish staleness from valid JSON first. Missing,
invalid, or unreachable report JSON is not proof of staleness. When authorized,
use the exact
`gh workflow run nightly-report.yml` command in `references/operations.md`, monitor the run, and
confirm that the newly deployed JSON passes its freshness and coverage gates.
Never weaken validation, forge timestamps, edit generated output, or replace a
failed build with partial charts.

## Preserve the boundary

Frame all output as market research only. Never place orders, connect to a
broker, promise returns, or turn the report into individualized financial
advice. Make uncertainty and counter-evidence visible.
