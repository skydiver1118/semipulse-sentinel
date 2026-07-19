# SemiPulse Trading-Day Publishing and Email Alerts

**Date:** 2026-07-18

## Goal

Update SemiPulse Sentinel so its hosted workflow requests scans only on weekdays,
publishes only when the completed market session advances, preserves the most
recent valid report when no new data exists, and emails the canonical report link
to `1118xmb@gmail.com` after each new deployment.

## Scope and constraints

- Keep the existing 6:00 PM `America/New_York` wall-clock schedule.
- Change the scheduled trigger from every calendar day to Monday through Friday.
- Treat the published `report.json` as the previous-session source of truth.
- Never interpret an unreachable or invalid published report as empty or unchanged.
- Keep the existing freshness, required-benchmark, 70% coverage, exactly-eight-chart,
  and static-site validation gates.
- Reuse the private Gmail SMTP sender configuration already used by the SOXL
  intraday scanner, but store its values only as encrypted GitHub Actions secrets.
- Do not add broker access, positions, personalized sizing, or trading execution.

## Chosen architecture

The GitHub Actions workflow remains the scheduler and publisher. Its schedule is
`0 18 * * 1-5` with `timezone: America/New_York`. A weekday trigger can still
occur on an exchange holiday, so the workflow uses a market-session advancement
gate rather than maintaining a second, potentially stale holiday calendar.

The build job performs these stages:

1. Fetch and validate the currently published canonical `report.json`.
2. Run the existing workflow verifier and offline test suite.
3. Build and validate a candidate site from newly downloaded daily market data.
4. Compare the candidate `market_as_of` with the published `market_as_of`.
5. Emit a typed workflow decision:
   - `new`: candidate date is later; upload and deploy it.
   - `unchanged`: dates match; skip upload, deployment, and email.
   - `regressed`: candidate date is earlier; fail without publication.
   - `unverifiable`: the prior public JSON is missing, unreachable, or invalid;
     fail closed rather than guessing.

This makes exchange holidays and provider no-update days safe: the job may start,
but no new report is published and the existing Pages deployment remains intact.
The report therefore advances only on an actual new market session.

## Publication and failure behavior

The existing atomic build and site validation remain unchanged. A candidate must
have valid required benchmarks, at least 70% watchlist coverage, acceptable
freshness and price integrity, and exactly eight validated chart artifacts.

The Pages artifact and deploy job run only for a `new` decision. For `unchanged`,
the workflow succeeds with a clear skip summary and leaves the last successful
report online. `regressed`, `unverifiable`, build, quality, and validation errors
fail before deployment. No path creates a blank or partial public report.

## Email delivery

A separate notification job depends on a successful new-data deployment. It uses
Python standard-library SMTP with STARTTLS and encrypted GitHub Actions secrets:

- `SEMIPULSE_SMTP_HOST`
- `SEMIPULSE_SMTP_PORT`
- `SEMIPULSE_SMTP_USER`
- `SEMIPULSE_SMTP_PASSWORD`
- `SEMIPULSE_EMAIL_FROM`
- `SEMIPULSE_EMAIL_TO`

The recipient secret will contain `1118xmb@gmail.com`. Sender values will be copied
from the existing private SOXL SMTP configuration without printing them or adding
them to the repository.

The alert subject includes the SemiPulse market date. The body contains the market
date, regime, confidence, coverage, and canonical dashboard link:
`https://skydiver1118.github.io/semipulse-sentinel/`.

Notification occurs only after Pages deployment succeeds. SMTP failure does not
roll back or remove the valid report; the notification job fails visibly so the
missing alert can be diagnosed and retried. The notifier must not print passwords,
tokens, or full environment values.

After this feature is deployed and its secrets are configured, operations send one
clearly labeled activation email containing the current canonical report link. This
one-time delivery verifies the reused SOXL sender path. Subsequent automated alerts
remain limited to successful deployments whose `market_as_of` advances.

## Components

### Market-session advancement decision

A small, deterministic Python interface compares two already-validated report
models or JSON documents. It returns the typed decision and relevant market dates.
Comparison logic has no network dependency; the workflow is responsible for
retrieving the prior document.

### Email notifier

A focused Python interface validates required SMTP settings, constructs a plain
text and HTML-safe message containing the public link, establishes STARTTLS,
authenticates, sends one message, and returns structured success metadata. It has
no access to market providers or brokerage systems.

### Workflow orchestration

The workflow captures the prior public JSON, builds the candidate site, invokes
the comparison interface, and exposes `has_new_data` and `market_as_of` outputs.
Artifact upload, Pages deployment, and notification are conditional on new data.

## Testing

Development follows test-first red/green/refactor cycles.

- Workflow tests require the weekday-only timezone-aware schedule and conditional
  upload, deploy, and notify jobs.
- Decision tests cover newer, unchanged, regressed, invalid, and missing prior
  reports.
- Integration tests prove unchanged data leaves an existing valid site untouched.
- Notifier tests use a fake SMTP transport to verify STARTTLS, login, recipient,
  subject, link, and absence of secret values from output.
- Failure tests prove deployment is skipped on unchanged data and email is skipped
  unless deployment succeeds.
- The full offline test suite, workflow verifier, package build, local site build,
  and site validation must pass before publication.

## Operations and documentation

README, methodology disclosures, the operator runbook, installed skill reference,
and report schedule metadata will describe weekday requests and the new-session
publication rule. They will state that GitHub scheduling is best effort and that a
weekday workflow can start on an exchange holiday but will not replace the report
when market data has not advanced.

Repository secret names may be listed in documentation; secret values must never
be committed, echoed, attached as artifacts, or included in generated reports.

## Success criteria

- The public report remains available at the canonical dashboard URL.
- Scheduled workflow requests occur Monday through Friday at 6:00 PM Eastern.
- A newly completed market session produces one validated deployment and one email.
- Initial activation produces one labeled delivery test with the canonical link.
- An exchange holiday, provider lag, or duplicate market date produces no
  deployment and no duplicate email while retaining the last valid report.
- A failed candidate never replaces the last successful report.
- The Gmail credentials remain private and are stored only as encrypted Actions
  secrets.
