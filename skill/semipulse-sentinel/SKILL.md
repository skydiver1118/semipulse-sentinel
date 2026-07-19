---
name: semipulse-sentinel
description: Use when a user asks for SemiPulse, the semiconductor source-chart report, a Wenxuecity chart refresh, the eight copied charts, or the semiconductor dashboard.
---

# SemiPulse Sentinel

Review the source-copy semiconductor report. Read
`references/operations.md` before locating, explaining, or refreshing it.

## Locate and verify

Prefer the canonical public `report.json`; use a local site only after
`python -m semipulse_sentinel validate-source --site site --json` succeeds.
A failed fetch is an operational failure, not an empty report.

Require schema `semipulse-wenxuecity-source-v1`. State `market_as_of`,
`source.post_id`, `source.url`, `source.published_at`, `source.edited_at`, image
count, and the permanent report link. For `images[]`, use `local_path`,
`source_url`, `sha256`, byte length, and dimensions as integrity evidence.
`copied_unchanged` means the published files match the downloaded source bytes.

## Review the charts

Open the copied images when the user wants a visual review. Separate visible
observations from claims printed inside the source. Preserve source provenance
and `risk_disclosure`. Do not recreate, redraw, calculate substitutes, or infer
missing values from unrelated market data.

If JSON, source metadata, an image, or a hash is invalid, report that the
source-copy report cannot be verified. Keep the last successful report; never
replace a failed scan with blanks or partial images.

## Refresh only with authority

Do not dispatch unless the user explicitly requests a refresh or the active
conversation already grants it. Honor conditions attached to refresh authority.
An unreachable report is not proof of new source data.

When authorized, use the exact `gh workflow run nightly-report.yml` command in
the operations reference and monitor the selected run. Confirm the deployed
schema, source identity, image count, and ordered hashes. An unchanged scan
keeps the last successful report and sends no email. A changed successful
deployment sends one link to the fixed recipient.

## Research boundary

Frame output as research only. Never place orders, connect to a broker, promise
returns, or provide individualized financial advice.
