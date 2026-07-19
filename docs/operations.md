# Operations

The canonical repository is `skydiver1118/semipulse-sentinel`. GitHub Pages
serves the last successfully deployed report at:

- `https://skydiver1118.github.io/semipulse-sentinel/`
- `https://skydiver1118.github.io/semipulse-sentinel/report.json`

## Schedule and last-good behavior

The workflow starts Monday through Friday at **6:20 PM America/New_York** with
the timezone-aware schedule `20 18 * * 1-5`. The daylight saving time change is handled by
the named timezone. GitHub Actions scheduling is best effort and may start
late. Public-repository schedules may be disabled after 60 days without
activity, and forks begin with schedules disabled.

The `check-market-session` command uses the XNYS calendar. An automatic run
continues only when the local date is an exchange session and the 6:00 PM
post-close cutoff has passed. `workflow_dispatch` is the explicit manual
recovery path and may check the most recent source outside that automatic gate.

The source pipeline runs `build-source`, `validate-source`, and
`decide-source-publication`. A new post or changed ordered hashes deploys. If
there is no new source data, deploy and email are skipped and the last
successful Page stays live. Network, validation, regression, or current-report
failures also fail closed without replacing the Page.

Restore an inactive schedule and request a manual scan with:

```powershell
gh workflow enable nightly-report.yml --repo skydiver1118/semipulse-sentinel
gh workflow run nightly-report.yml --repo skydiver1118/semipulse-sentinel --ref main
gh run list --repo skydiver1118/semipulse-sentinel --workflow nightly-report.yml --limit 5
```

Concurrency uses the `semipulse-pages` group, so a newer run cancels an older
in-flight run.

## GitHub Pages setup and recovery

Pages enablement is an out-of-band repository setting. Select **GitHub
Actions** as the Pages source. The build job has read-only repository and Pages
access; the separate deploy job receives only `pages: write` and
`id-token: write`.

After a changed deployment, verify HTTP 200 for the page and JSON. Confirm the
schema, source post, image count, and every local image hash. For a Pages
failure after artifact upload, retry the run. Do not edit generated Pages
content or weaken validation.

## Local source build

```powershell
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps --no-build-isolation .
python scripts/verify_workflow.py .github/workflows/nightly-report.yml
python -m pytest -q
python -m semipulse_sentinel build-source --output site --json
python -m semipulse_sentinel validate-source --site site --json
```

The networked build copies the allowlisted source images byte-for-byte into a
staging site. Validation requires `semipulse-wenxuecity-source-v1`, canonical
source metadata, 1-12 images, exact files, matching SHA-256 values, and no
unexpected artifacts.

## Email delivery

The `notify-source` command runs only after a changed Pages deployment. Its
recipient is hard-locked in code to `1118xmb@gmail.com`; no recipient secret is
read. Configure these encrypted repository secrets:

- `SEMIPULSE_SMTP_HOST`
- `SEMIPULSE_SMTP_PORT`
- `SEMIPULSE_SMTP_USER`
- `SEMIPULSE_SMTP_PASSWORD`
- `SEMIPULSE_EMAIL_FROM`

No credentials are written to the repository, report, artifact, or logs. An
email failure does not roll back a successful report deployment.

## Exit codes

- **Exit code 0**: operation succeeded, including an unchanged trading-day gate.
- **Exit code 2**: configuration, input, source, or validation error.
- **Exit code 3**: legacy publication gate blocked a report.
- **Exit code 4**: notification, build orchestration, or unexpected failure.

Research only - not individualized investment advice. Do not add broker
credentials, personal positions, or other private data to this public system.
