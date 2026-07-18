# SemiPulse Sentinel Design Specification

**Status:** Approved for autonomous implementation by the user's standing instruction not to pause for approval.

**Product name:** SemiPulse Sentinel  
**Repository:** `semipulse-sentinel`  
**Python package:** `semipulse_sentinel`  
**Codex skill:** `semipulse-sentinel`  
**Primary report:** A static GitHub Pages site refreshed nightly at 6:00 PM America/New_York

## 1. Purpose

SemiPulse Sentinel is a nightly decision-support report for the semiconductor complex. It refreshes exactly eight charts, interprets each chart from the same underlying measurements, and places a concise cross-chart synthesis at the top of a permanent web link.

The system supports research and risk framing; it does not place orders, promise returns, or produce individualized financial advice. Every report must show the market-data timestamp, coverage, stale-data state, methodology version, and this warning:

> Research only—not individualized investment advice or a recommendation to buy or sell. Market data may be delayed, incomplete, or revised. Leveraged ETFs such as SOXL can suffer path-dependent decay and large losses. Verify prices and signals with a licensed source before trading.

## 2. Source-file status and recovery decision

The assigned workspace and current Codex session contain no attachment object. The Codex attachment cache also contains no file associated with this thread. A bounded local audit found one plausible source artifact:

`semi_05Jul2026_1149.csv`

It is a 23-row semiconductor watchlist with columns `Symbol`, `Last`, `Chg%`, and `Color`. Its filename and constituents align with “Semi monitor,” but there is no authoritative evidence that it is the missing upload. Therefore:

- the file is used only as an explicitly labeled recovered seed;
- the report never treats its stale `Last` or `Chg%` values as current market data;
- the canonical input is a replaceable `config/watchlist.csv`;
- every row retains `source_status=recovered_inference` until the user supplies or confirms the attachment;
- replacing the CSV must not require code changes;
- completion documentation must state that upload identity was not verifiable.

Seed symbols:

`AAOI, AMAT, AMD, ASML, AXTI, CBRS, DRAM, IREN, LITE, LRCX, MRVL, MU, NVDA, ONTO, SMH, SNDK, SOXL, SOXX, STX, TER, TSEM, TSM, WDC`.

Provider validation may mark symbols unsupported or stale. Unsupported symbols remain visible in the coverage panel and are excluded from aggregates rather than silently imputed.

## 3. Approaches considered

### A. Static GitHub Pages plus deterministic analytics — selected

A Python job downloads daily market data, computes versioned metrics, renders eight charts and an HTML report, validates the artifact, and deploys it through GitHub Actions.

Benefits: no server, stable web link, auditable calculations, low operating cost, reproducible prose, graceful failure that preserves the previous good page, and exact local-time scheduling.

Trade-offs: the default keyless data adapter is suitable only for personal research and may be delayed or brittle. The design therefore isolates the provider and publishes prominent provenance/quality warnings.

### B. LLM-generated nightly interpretation

An LLM could write more varied prose, but it requires a paid secret, creates nondeterministic output, increases hallucination risk, and makes numerical regression testing harder. It may be added later as a clearly labeled optional commentary layer, never as the source of metrics.

### C. Browser screenshots of eight external charts

This most closely reproduces a chart-link attachment, but the attachment and source URLs are absent. Browser automation is also vulnerable to layout, authentication, bot detection, and terms changes. A future `screenshot` adapter can be added after the eight authoritative URLs are supplied.

## 4. Report contract

The top of the page contains:

1. report title and as-of timestamp in America/New_York;
2. freshness badge and symbol coverage;
3. composite regime: `risk-on`, `constructive`, `mixed`, `defensive`, or `risk-off`;
4. confidence: `high`, `medium`, or `low`, capped by coverage and staleness;
5. “what changed,” “supports the view,” “challenges the view,” and “what would change the view” bullets;
6. tactical research posture expressed as risk conditions, never as an order or personalized allocation;
7. direct anchors to the eight charts.

Each chart card contains:

- stable chart number and title;
- image with accessible alt text;
- one-sentence signal headline;
- evidence bullets with exact values and lookback windows;
- interpretation and trading relevance;
- counter-signal or invalidation condition;
- data coverage and calculation notes.

The footer contains data provenance, methodology, symbol exclusions, build version, source-file status, and the mandatory risk warning.

## 5. The eight charts

### Chart 1 — Semiconductor complex performance

Normalized total-return lines for `SMH`, `SOXX`, `QQQ`, and `SOXL` over 126 sessions, rebased to 100. It establishes absolute trend and whether leveraged participation confirms or exaggerates the move.

Interpretation inputs: 5-, 20-, and 63-session returns; slope; distance from 20- and 50-day averages; latest drawdown. SOXL commentary must explicitly mention leverage and path dependency.

### Chart 2 — Relative strength versus QQQ

Normalized `SMH / QQQ` and `SOXX / QQQ` ratios with 20- and 50-session trend references. It distinguishes broad technology beta from semiconductor-specific leadership.

Interpretation inputs: 20- and 63-session ratio change, moving-average state, and recent crossover.

### Chart 3 — Watchlist breadth

Time series of the percentage of covered watchlist members above their 20-, 50-, and 200-day simple moving averages.

Interpretation inputs: current breadth levels, 5-session change, breadth stack order, and divergence from SMH price trend. Denominator and missing count are printed.

### Chart 4 — Equal-weight participation

Median watchlist cumulative return versus `SMH` over 63 sessions, plus the participation spread. This tests whether the index move is broad or concentrated.

Interpretation inputs: median-versus-SMH spread, percentage outperforming SMH, and dispersion.

### Chart 5 — Momentum leaders and laggards

Sorted horizontal bars of 20-session adjusted returns for every covered watchlist symbol, colored by positive/negative return and labeled with values.

Interpretation inputs: top three, bottom three, median, interquartile range, and concentration warning. It is descriptive, not a chase list.

### Chart 6 — Multi-horizon trend heatmap

Heatmap by symbol for 5-, 20-, and 63-session returns plus distance from 20-, 50-, and 200-day averages. Values are winsorized only for color scaling; labels show actual values.

Interpretation inputs: share of positive cells, strongest/weakest consistent trends, reversals, and unsupported cells.

### Chart 7 — Volatility and drawdown regime

SMH 20-session annualized realized volatility, 63-session rolling maximum drawdown, and `^VIX` when available. Missing VIX never blocks the other series.

Interpretation inputs: volatility percentile against the trailing year, current drawdown, 5-session volatility change, and whether price/breadth confirm stress.

### Chart 8 — Risk/reward map

Scatter plot of 63-session return versus 20-session annualized volatility for covered symbols. Bubble size represents median 20-session dollar volume when available; reference lines show medians.

Interpretation inputs: quadrant membership, outliers, liquidity caveats, and names whose return is not supported by breadth/trend. It is a research map, not a portfolio optimizer.

## 6. Composite interpretation

The engine is deterministic and versioned as `semipulse-rules-v1`. It computes five pillars:

- absolute trend, 25%;
- relative leadership, 20%;
- breadth and participation, 25%;
- momentum distribution, 15%;
- volatility/drawdown risk, 15%.

Each pillar produces a score from -2 to +2, evidence strings, and counter-evidence. The weighted composite maps to:

- at least +1.20: `risk-on`;
- +0.45 to +1.19: `constructive`;
- -0.44 to +0.44: `mixed`;
- -1.19 to -0.45: `defensive`;
- at most -1.20: `risk-off`.

Confidence starts high and is capped:

- low when fewer than 70% of watchlist symbols have 63-session coverage, any required benchmark is absent, or data is more than three calendar days old;
- medium when coverage is below 90%, a noncritical series is absent, or the latest session is more than one expected U.S. market session old;
- otherwise high.

No favorable language may hide missing or stale inputs. The top summary must include at least one supporting and one challenging fact. If the provider fails validation, the workflow fails before deployment and the previous known-good page remains live.

## 7. Architecture and boundaries

```text
config/watchlist.csv
        |
        v
watchlist loader --> provider interface --> normalized OHLCV frame
                          |                       |
                          v                       v
                    yfinance adapter       quality validator
                                                  |
                                                  v
metrics engine --> eight chart models --> deterministic interpreter
        |                 |                         |
        +-----------------+-------------------------+
                          |
                          v
                   immutable ReportModel
                          |
                  +-------+--------+
                  v                v
              HTML/JSON         SVG charts
                  |
                  v
            artifact validator
                  |
                  v
        GitHub Pages deployment
```

Focused modules:

- `config.py`: immutable settings and chart contract;
- `watchlist.py`: strict CSV parsing, identity, provenance;
- `providers/base.py`: provider protocol and normalized data model;
- `providers/yfinance.py`: default keyless personal-research adapter;
- `quality.py`: coverage, timestamp, duplicates, price/volume sanity, required benchmarks;
- `metrics.py`: all reusable indicators and chart datasets;
- `interpret.py`: chart interpretations and composite regime;
- `charts.py`: exactly eight SVG renderers;
- `report.py`: canonical report model and HTML/JSON renderers;
- `pipeline.py`: orchestration and atomic output publication;
- `cli.py`: `build`, `validate`, and `doctor` commands.

The site uses generated static HTML/CSS with no client-side data fetch and no analytics or tracking.

## 8. Scheduling and publishing

The GitHub Actions workflow runs every calendar day at 6:00 PM in `America/New_York` using GitHub's timezone-aware schedule:

```yaml
on:
  schedule:
    - cron: "0 18 * * *"
      timezone: "America/New_York"
  workflow_dispatch:
```

Scheduled workflows may start late; the report displays actual start and completion timestamps. The workflow uses:

- latest default-branch commit;
- pinned major versions of official `actions/checkout`, `actions/setup-python`, `actions/configure-pages`, `actions/upload-pages-artifact`, and `actions/deploy-pages`;
- read-only repository permissions for build and only `pages: write` plus `id-token: write` for deployment;
- dependency hashes through a committed lock file;
- concurrency cancellation so an older build cannot overwrite a newer one;
- artifact validation before upload;
- manual dispatch for recovery.

The report URL is the repository's permanent GitHub Pages URL. Failure never replaces the previous successful deployment.

## 9. Historical context

The public page is latest-first. “What changed” comparisons are calculated from the current download's trailing daily history, so they do not depend on mutable bot commits or a previous deployment artifact. The report model includes the last five sessions of composite inputs for auditability, while the visible page emphasizes the latest completed session.

The workflow never commits generated reports to the source branch. Persistent report archives are outside version-1 scope; they can be added later through a dedicated artifact branch without changing the current report contract. Version 1 prioritizes a reliable latest report and a clean source history.

## 10. Error handling and safety

- Required benchmark absence, fewer than 70% watchlist coverage, nonpositive adjusted prices, duplicate dates, or an output count other than eight are fatal.
- A missing optional VIX series is visible but not fatal.
- Partial symbols are excluded with named reasons and denominator updates.
- Network calls retry with bounded exponential backoff.
- Output builds in a temporary sibling directory and replaces the destination only after JSON/schema, HTML, image, and link checks pass.
- Logs never print cookies, tokens, or full provider responses.
- The workflow carries no broker credentials and has no trading or messaging permissions.
- The report must distinguish observed facts, deterministic inference, and limitations.

## 11. Testing and acceptance

Unit tests cover:

- strict watchlist parsing and provenance;
- normalized provider shapes, split-adjusted calculations, missing symbols, and duplicate dates;
- every indicator boundary;
- all five regime labels and confidence caps;
- stable interpretations with evidence and counter-evidence;
- exactly eight chart renderers and valid SVG;
- HTML escaping and risk-warning presence.

Integration tests use a deterministic multi-symbol fixture to build the complete site and assert:

- eight images and eight interpretations;
- summary precedes chart cards;
- top summary agrees with chart evidence;
- data quality and source status are visible;
- no unsupported recommendation language;
- atomic publication preserves the previous site on injected failure.

Live acceptance requires:

1. a successful current-data build with at least 70% seed-watchlist coverage;
2. artifact validation;
3. repository creation and push under the authenticated GitHub account;
4. GitHub Pages enabled for Actions;
5. a successful manual workflow run;
6. an HTTP 200 page containing eight chart cards, the current timestamp, and SemiPulse Sentinel name;
7. the installed `semipulse-sentinel` Codex skill discovering the repository, report URL, status, and manual refresh command from a future chat.

## 12. Explicit limitations

- The missing uploaded file cannot be proven to be the recovered CSV.
- The default yfinance adapter is unofficial, intended for personal research, and subject to Yahoo terms and availability. The report is not a licensed execution-quality feed.
- Daily data cannot describe intraday reversals after the provider's latest completed bar.
- Technical indicators are backward-looking and can whipsaw.
- Public GitHub Pages should not contain secrets, brokerage data, personal positions, or personalized sizing.
- The report remains useful only when freshness, coverage, and provenance checks pass.
