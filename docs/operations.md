# Operations

This runbook covers the live public repository
`skydiver1118/semipulse-sentinel`. GitHub Pages uses the audited Actions
workflow, and the first deployment has been verified. The canonical report and
structured JSON are:

- `https://skydiver1118.github.io/semipulse-sentinel/`
- `https://skydiver1118.github.io/semipulse-sentinel/report.json`

## Schedule and delivery guarantees

The workflow requests a run Monday through Friday at **6:00 PM America/New_York**
using the timezone-aware schedule `0 18 * * 1-5`. The local timezone follows
daylight saving time, so the corresponding UTC hour changes
seasonally while the requested New York wall-clock time remains 6:00 PM: the
request is 22:00 UTC during EDT and 23:00 UTC during EST.

The weekday cron is only a launch schedule; it is not an exchange-holiday
calendar. After building and validating a candidate, the workflow compares its
`market_as_of` date with the currently published report. A later date deploys.
The same date means there is no new market data, so deployment and email are
skipped and the last successful Page remains online. A regressed date,
unreachable current report, or invalid current report fails closed. This also
keeps the most recent valid data visible instead of publishing a blank report.

GitHub Actions scheduling is best effort. A scheduled run can start late or be
queued during platform load. In addition, GitHub may automatically disable
scheduled workflows in a public repository after 60 days without repository
activity. A maintainer must re-enable the workflow and use a manual dispatch
after such inactivity. Forks also begin with scheduled workflows disabled.

After repository activity resumes, restore scheduling and trigger a recovery
run with:

```powershell
gh workflow enable nightly-report.yml --repo skydiver1118/semipulse-sentinel
gh workflow run nightly-report.yml --repo skydiver1118/semipulse-sentinel
```

The workflow also exposes `workflow_dispatch` for recovery and verification.
Concurrency is limited to the `semipulse-pages` group, with an older in-flight
run canceled when a newer run begins.

## GitHub Pages setup and recovery

Pages enablement is an out-of-band repository administration step; the
workflow intentionally does not enable Pages on its own. The canonical
repository is already configured; use this checklist when recreating the site
or validating a replacement repository.

1. Create the public repository as `skydiver1118/semipulse-sentinel`, push the
   reviewed default branch, and confirm that the Actions workflow is present.
2. In repository **Settings > Pages**, select **GitHub Actions** as the build
   and deployment source.
3. In **Actions**, open **Nightly SemiPulse report** and choose **Run
   workflow** on the reviewed default branch.
4. Wait for the `build` job and, when the market date advances, the `deploy`
   and `notify` jobs to succeed.
5. Verify HTTP 200 responses and current content at:
   `https://skydiver1118.github.io/semipulse-sentinel/` and
   `https://skydiver1118.github.io/semipulse-sentinel/report.json`.

Do not remove the validation gate or grant broader permissions to make a
deployment pass. The build job has read-only repository and Pages access; the
separate deploy job receives only `pages: write` and `id-token: write`.

## Manual run

From the GitHub Actions web interface, select **Nightly SemiPulse report**,
select **Run workflow**, choose the reviewed branch, and confirm. With an
authenticated GitHub CLI, the equivalent request after the public repository
exists is:

```powershell
gh workflow run nightly-report.yml --repo skydiver1118/semipulse-sentinel
```

Watch the result with:

```powershell
gh run list --repo skydiver1118/semipulse-sentinel --workflow nightly-report.yml --limit 5
```

## Local verification and build

Use Python 3.11 or later from the repository root. The first command verifies
every locked dependency hash; the second installs the local project without
resolving or rebuilding dependencies independently:

```powershell
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps --no-build-isolation .
python scripts/verify_workflow.py .github/workflows/nightly-report.yml
python -m pytest -q
python -m semipulse_sentinel doctor --watchlist config/watchlist.csv --site site --json
```

`doctor` does not contact the provider. It reports dependency versions,
watchlist provenance, the schedule, and whether the local site is missing,
invalid, or valid.

The live build is the explicit network boundary:

```powershell
python -m semipulse_sentinel build --watchlist config/watchlist.csv --output site --json
python -m semipulse_sentinel validate --site site --json
```

Do not upload `site` unless `validate` succeeds. The hosted workflow runs its
offline verifier and test suite before the provider-backed build, validates the
staged output, compares the candidate market date with the live report, and
only for a newer date configures Pages and uploads the single `github-pages`
artifact for deployment. After deployment, the notifier emails the canonical
report link to `1118xmb@gmail.com`.

## Failure behavior and last-good rollback

A local build writes to a temporary sibling directory. Only a completely
rendered and validated site can replace `site`; a failure leaves the prior
destination intact. In GitHub Actions, the deploy job depends on the validated
build, a newer market date, and artifact upload. A failed build or a candidate
with no new market data therefore leaves the last successful Page online rather
than publishing a partial or blank report. Email failure does not roll back a
successfully deployed report; inspect and retry the `notify` job after fixing
the mail configuration.

For a provider or freshness failure, inspect the structured build message,
confirm the upstream data state, and rerun manually when data becomes valid.
Do not lower the 70% coverage gate, forge timestamps, or remove missing-symbol
disclosures.

For a site-validation failure, reproduce locally, fix the source, run the full
offline suite, build again, and validate the complete site before dispatching.

For a Pages-platform failure after a valid artifact was created, retry the
failed workflow run. If a regression was already deployed, revert the faulty
source change on the default branch and use `workflow_dispatch` to build and
deploy the known-good source again. The generated site is not committed to the
source branch, so recovery always goes through the same build and validation
gates.

## Exit codes

- **Exit code 0**: the requested operation succeeded. `doctor` also uses 0 when
  it successfully diagnoses a missing or invalid site; read its `site_state`.
- **Exit code 2**: configuration or local input error, such as a missing or
  malformed watchlist, a permissions problem, or an invalid value.
- **Exit code 3**: publication was blocked by market-data quality or static-site
  validation.
- **Exit code 4**: build orchestration failed or an unexpected exception was
  sanitized at the command boundary.

An interrupted command propagates the keyboard interrupt instead of converting
it into one of these results.

## Email configuration and security boundary

The notifier uses Gmail SMTP with STARTTLS only after a newly dated report has
deployed. The sole recipient is `1118xmb@gmail.com`. The sender is configured
independently through the existing SOXL alert account settings. Configure these
encrypted GitHub Actions secrets:

- `SEMIPULSE_SMTP_HOST`
- `SEMIPULSE_SMTP_PORT`
- `SEMIPULSE_SMTP_USER`
- `SEMIPULSE_SMTP_PASSWORD`
- `SEMIPULSE_EMAIL_FROM`
- `SEMIPULSE_EMAIL_TO`

No secrets are written to the repository, report, artifacts, or workflow logs.
The yfinance adapter remains keyless, and Pages deployment uses the job's
narrowly scoped GitHub and OIDC permissions. Do not add broker credentials,
provider tokens, cookies, personal positions, personalized sizing, or other
private data to the watchlist, workflow, logs, report, artifacts, or public
Pages site.
