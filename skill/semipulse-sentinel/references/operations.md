# SemiPulse Sentinel operations

## Canonical interfaces

- Repository: `https://github.com/skydiver1118/semipulse-sentinel`
- Report: `https://skydiver1118.github.io/semipulse-sentinel/`
- Structured report: `https://skydiver1118.github.io/semipulse-sentinel/report.json`
- Source post: `https://bbs.wenxuecity.com/cfzh/97669.html`
- Default branch: `main`
- Workflow: `nightly-report.yml`
- Schedule: `20 18 * * 1-5` in `America/New_York` (6:20 PM Eastern,
  Monday through Friday)

Automatic runs use an XNYS `check-market-session` gate. Manual
`workflow_dispatch` is the explicit recovery path. The source sequence is
`build-source`, `validate-source`, `decide-source-publication`, Pages deploy,
then `notify-source`.

## Source report fields

Require `semipulse-wenxuecity-source-v1`. Read:

- `market_as_of`;
- `source.post_id`, `source.published_at`, `source.edited_at`, `source.url`,
  author, title, and `copied_unchanged`;
- `images[]`: ordinal, `local_path`, `source_url`, `resolved_url`, content type,
  dimensions, `byte_length`, and `sha256`;
- `risk_disclosure`.

The scanner checks the seed and at most five newest top-level posts by the
exact author. Candidates require semiconductor markers and 1-12 allowlisted
images. Assets are copied byte-for-byte; do not derive replacement charts.

## Authorized refresh

Only dispatch with explicit authority in the active conversation:

```powershell
gh workflow run nightly-report.yml --repo skydiver1118/semipulse-sentinel --ref main
gh run list --repo skydiver1118/semipulse-sentinel --workflow nightly-report.yml --limit 5
```

Monitor the selected run. After success, fetch HTML, JSON, and every local
image with cache busting. Confirm source identity, count, and ordered hashes.
If there is no new source data, the deploy and email jobs are skipped and the
last successful report stays live. A changed deployment sends one report link
to `1118xmb@gmail.com`.

## Local verification

```powershell
python -m semipulse_sentinel build-source --output site --json
python -m semipulse_sentinel validate-source --site site --json
```

Do not change repository settings, weaken validation, edit generated output,
or expose SMTP credentials. Treat failures as operational limitations.

## Research boundary

SemiPulse Sentinel is research-only. It does not place orders, connect to
brokerage accounts, promise returns, or provide individualized advice.
