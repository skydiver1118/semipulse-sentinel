# SemiPulse Daily Decision Report Design

## Objective

Redo SemiPulse Sentinel as a completed-trading-session report. On every XNYS
trading date, all eight charts must be recomputed from the latest available
daily market data, explained in plain language, and synthesized into a bounded
research summary that can inform trading decisions. The report must never
identify the original forum poster.

## Chosen approach

Reactivate and strengthen the repository's existing deterministic market-data
pipeline. It already computes eight complementary chart datasets, renders
accessible SVGs, interprets each chart, creates a five-session signal audit,
and validates a canonical `semipulse-report-v1` site.

Two alternatives were rejected:

- A hybrid of copied third-party charts and daily overlays would mix stale and
  current timestamps and could mislead the reader.
- Recreating the third-party charts from substitutes would not be faithful
  because several inputs are proprietary or do not update daily.

The live report will therefore describe its own public-market methodology and
will not claim to reproduce the third-party charts.

## Public report contract

The canonical report is `report.json`, rendered into the matching static HTML
page. It uses schema `semipulse-report-v1` and contains exactly eight ordered
charts:

1. Semiconductor complex performance.
2. Relative strength versus QQQ.
3. Watchlist breadth.
4. Equal-weight participation.
5. Momentum leaders and laggards.
6. Multi-horizon trend heatmap.
7. Volatility and peak-distance regime.
8. Return, volatility, and liquidity risk-reward map.

Every chart card contains three distinct explanations:

- **What this chart measures:** a stable description of the chart's purpose.
- **What it means now:** a deterministic interpretation of current evidence.
- **How it may inform trading decisions:** conditional research relevance,
  paired with an explicit counter-signal or invalidation condition.

The top section is titled **Trading decision summary**. It shows the regime,
score, confidence, current research posture, change from the prior session,
supporting evidence, challenging evidence, and conditions that would change
the view. Language stays conditional and non-personalized. The system does not
place orders, connect to a broker, promise returns, or prescribe position size.

No public HTML, JSON, or email field contains a forum author or original-poster
name. The report includes only the market-data provider and the watchlist and
methodology provenance needed to reproduce the analysis.

## Trading-session update flow

The GitHub Actions workflow runs at 6:20 PM America/New_York on weekdays. An
XNYS calendar gate allows automatic builds only after a completed trading
session. Manual dispatch remains a recovery mechanism, but it cannot force an
older or equal `market_as_of` report to deploy.

For an eligible run:

1. Install the locked project and run the full offline test suite.
2. Fetch sufficient daily adjusted OHLCV history for the fixed semiconductor
   watchlist and required benchmarks.
3. Validate required-series freshness and coverage.
4. Recompute all eight metric datasets through the latest completed session.
5. Render all eight SVGs and generate the matching explanations and summary.
6. Validate the complete site and compare its `market_as_of` with the live
   report.
7. Deploy and email only when the candidate date is newer.

Chart assets are generated in one staging directory and published atomically,
so all eight charts always represent the same `market_as_of` session.

## Failure and no-new-data behavior

The last successfully deployed report is the fallback. If the provider has not
advanced, the candidate has the same `market_as_of`, validation fails, required
data are missing, or the build is partial, the workflow does not deploy and
does not email. It never replaces the live page with blanks or a partial chart
set. A regressed market date fails closed.

Missing optional data may be shown as unavailable only when the report still
passes the documented coverage contract; confidence is reduced and the gap is
disclosed.

## Email behavior

After a new report deploys successfully, one email is sent to the hard-locked
recipient `1118xmb@gmail.com`. The message contains the market date, regime,
confidence, coverage, research disclaimer, and permanent report link. No email
is sent for an unchanged session or a failed deployment. SMTP credentials stay
in GitHub secrets and are never logged or published.

## Testing and acceptance

Automated tests must prove that:

- the report has exactly eight ordered charts and every card has purpose,
  current meaning, decision relevance, evidence, and a counter-signal;
- all chart files and the summary use the same `market_as_of` session;
- public output and email contain no original-poster name or author field;
- the workflow uses the daily build, validation, date-comparison, deploy, and
  fixed-recipient notification commands in the required order;
- scheduled runs are trading-session gated;
- a newer session deploys and emails once, while an equal session keeps the
  current report and skips both deploy and email;
- the generated HTML, embedded JSON, standalone JSON, and eight SVG files pass
  validation and remain internally consistent.

Release acceptance requires the full local test suite or equivalent split test
runs, a successful GitHub Actions run, live HTML and JSON verification, eight
reachable chart assets for the latest completed session, absence of the poster
identity, and a second unchanged run that demonstrates last-good retention.
