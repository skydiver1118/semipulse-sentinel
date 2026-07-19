# SemiPulse Wenxuecity Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace reconstructed charts with byte-for-byte copies of the source post's chart set and refresh only from newer qualifying posts by the same author.

**Architecture:** A bounded public-source scanner parses the seed post and author archive, downloads only allowlisted Wenxuecity CDN images, and emits an immutable source manifest. A source-only static report and publication gate deploy only new/revised manifests; an XNYS trading-session gate controls the weekday workflow and the existing SMTP path sends the fixed-recipient link.

**Tech Stack:** Python 3.11, urllib/html.parser, Pillow-free JPEG/PNG header parsing, Jinja2, exchange-calendars 4.13.2, GitHub Actions/Pages, SMTP STARTTLS.

## Global Constraints

- Copy source image bytes unchanged; never recreate or edit a chart.
- Restrict source pages and images to the exact HTTPS hosts and paths in the design.
- Scan only the seed post and at most five current-page top-level author posts.
- Keep the last good deployment for unchanged, missing, irrelevant, stale, or invalid input.
- Fix the sole email recipient to `1118xmb@gmail.com`.
- Follow red-green-refactor for every production behavior.

---

### Task 1: Parse and validate the Wenxuecity source

**Files:**
- Create: `src/semipulse_sentinel/wenxuecity_source.py`
- Create: `tests/unit/test_wenxuecity_source.py`

**Interfaces:**
- `SourcePost(post_id, url, title, author, published_at, edited_at, body_text, image_urls)`
- `SourceImage(source_url, resolved_url, content_type, data, sha256, width, height)`
- `parse_source_post(html: bytes, url: str) -> SourcePost`
- `parse_author_archive(html: bytes) -> tuple[ArchivePost, ...]`
- `download_source_images(post, opener=None) -> tuple[SourceImage, ...]`
- `discover_latest_source(seed_url, archive_url, current_manifest, opener=None) -> SourceBundle | None`

- [ ] Write tests for exact `#msgbodyContent` order, author/title/timestamps, non-reply archive filtering, relevance markers, URL allowlists, redirect validation, image count/size/dimensions, and unchanged fallback.
- [ ] Run `python -m pytest tests/unit/test_wenxuecity_source.py -q` and confirm import/behavior failures.
- [ ] Implement standard-library parsers, bounded reads, JPEG SOF and PNG IHDR dimension parsing, SHA-256, and the five-post discovery limit.
- [ ] Re-run the focused test file and commit `feat: ingest Wenxuecity source charts`.

### Task 2: Build the source-only static report

**Files:**
- Create: `src/semipulse_sentinel/source_report.py`
- Create: `src/semipulse_sentinel/templates/source_report.html.j2`
- Create: `src/semipulse_sentinel/static/source_report.css`
- Create: `tests/unit/test_source_report.py`
- Create: `tests/integration/test_source_report.py`
- Modify: `pyproject.toml`

**Interfaces:**
- `build_source_report(bundle, output, clock) -> SourceReportSnapshot`
- `validate_source_site(path) -> SourceReportSnapshot`
- Schema: `semipulse-wenxuecity-source-v1` with source post metadata and ordered image manifests.

- [ ] Write failing tests proving exact byte copying, image order, hash metadata, escaped source text, source-copy badge, and preservation of a prior output directory on injected failure.
- [ ] Run the two focused files and confirm RED.
- [ ] Implement sibling-directory staging, local `charts/source-01.<ext>` names, canonical JSON, template/CSS, and complete pre-replacement validation.
- [ ] Re-run focused tests and commit `feat: build source-copy report`.

### Task 3: Add source CLI, revision gate, and trading-session gate

**Files:**
- Create: `src/semipulse_sentinel/source_publication.py`
- Create: `src/semipulse_sentinel/market_session.py`
- Modify: `src/semipulse_sentinel/cli.py`
- Create: `tests/unit/test_source_publication.py`
- Create: `tests/unit/test_market_session.py`
- Modify: `tests/unit/test_cli.py`
- Modify: `tests/integration/test_cli.py`
- Modify: `pyproject.toml`
- Modify: `requirements.lock`

**Interfaces:**
- Commands: `build-source`, `validate-source`, `decide-source-publication`, `check-market-session`.
- Decisions: `new`, `revised`, `migration`, `unchanged`, and fail-closed `regressed`.

- [ ] Write failing tests for old-schema migration, newer post, same-post changed ordered hashes, exact unchanged manifest, regression, XNYS holiday/weekend, and completed-session timing.
- [ ] Confirm RED, then implement the commands and safe GitHub output encoding.
- [ ] Pin `exchange-calendars==4.13.2`, regenerate the hashed lock, and run the focused tests.
- [ ] Commit `feat: gate Wenxuecity report refreshes`.

### Task 4: Fix the recipient and replace the hosted workflow

**Files:**
- Modify: `src/semipulse_sentinel/notifications.py`
- Modify: `tests/unit/test_notifications.py`
- Replace: `.github/workflows/nightly-report.yml`
- Modify: `scripts/verify_workflow.py`
- Modify: `tests/unit/test_workflow.py`
- Modify: `tests/unit/test_contracts.py`

- [ ] Write failing notification tests showing an environment recipient override is ignored and the source-report email contains only the source date/title/link and disclosure.
- [ ] Write failing workflow tests requiring weekday 6:20 PM New York scheduling, the market-session check before source scanning, source-only CLI commands, last-good no-deploy behavior, fixed-recipient notification, and absence of yfinance/matplotlib build commands.
- [ ] Implement the source notification and exact audited workflow/verifier contract.
- [ ] Run notification, workflow, contract, and verifier tests; commit `feat: publish Wenxuecity source updates`.

### Task 5: Migrate documentation, release, and verify

**Files:**
- Modify: `README.md`
- Modify: `docs/operations.md`
- Modify: `docs/methodology.md`
- Modify: `skill/semipulse-sentinel/SKILL.md`
- Modify: `skill/semipulse-sentinel/references/operations.md`
- Modify: `tests/unit/test_skill.py`

- [ ] Replace all live eight-SVG/yfinance claims with the source post, author-feed refresh rule, exact-byte guarantee, permanent report URL, and last-good fallback.
- [ ] Run ruff, mypy, the full pytest suite, the workflow verifier, package build, and wheel-install checks.
- [ ] Build the seed report and compare all eight copied hashes to the design manifest.
- [ ] Use the requesting-code-review and verification-before-completion skills, address validated findings, merge, push, and run the source workflow.
- [ ] Verify public HTML/JSON/images, workflow deployment, fixed-recipient email result, and a second unchanged run that preserves the report and sends no email.
- [ ] Record the live report URL, release commit, source post, image count/hashes, and workflow run URL in the final handoff.
