# Methodology

SemiPulse Sentinel turns one normalized daily OHLCV download into a versioned
metrics bundle, exactly eight chart artifacts, and deterministic prose. The
same observations drive the charts, each chart explanation, and the **Trading
decision summary**. Unsupported observations are disclosed and excluded from
aggregates; they are not silently imputed.

The current calculation version is `semipulse-metrics-v1`, the interpretation
version is `semipulse-rules-v1`, and the public report schema is
`semipulse-report-v1`. The report's `market_as_of` value is the completed market
session represented by every chart and summary calculation.

## Explanation contract

Every chart answers a stable question and presents five visible sections:
**What this chart measures**, **Evidence**, **What it means now**, **How it may
inform trading decisions**, and **Counter-signal**. The same facts are flattened
onto each `charts[]` item in `report.json`. Interpretation is observation-led,
template-based, and conditional; it does not turn a descriptive chart into an
order or recommendation.

## The eight chart questions

### 1. Semiconductor complex performance

Are SMH, SOXX, QQQ, and SOXL strengthening or weakening? Adjusted closes are
rebased to 100 across the latest 126 sessions. Evidence includes 5-, 20-, and
63-session returns, log-price slope, moving-average distances, and distance
from the recent peak. SOXL is treated as leveraged and path-dependent.

### 2. Relative strength versus QQQ

Are semiconductor benchmarks leading broad technology? SMH/QQQ and SOXX/QQQ
adjusted-close ratios are rebased to 100 and displayed with 20- and 50-session
averages. Ratio changes and supported crossover states distinguish industry
leadership from broad technology beta.

### 3. Watchlist breadth

How much of the watchlist participates? Each date reports the percentage of
eligible members above 20-, 50-, and 200-session moving averages, with separate
covered and missing denominators. Current levels, five-session changes, and
horizon ordering reveal whether participation is broadening or narrowing.

### 4. Equal-weight participation

Is the typical constituent confirming SMH? Across the 63-session return horizon
(64 common observations), the chart compares median watchlist cumulative return
with SMH and shows the percentage-point spread. It also records the eligible
share outperforming SMH and cross-sectional dispersion.

### 5. Momentum leaders and laggards

How are recent returns distributed? Supported symbols are sorted by actual
20-session adjusted return. Evidence names leaders, laggards, the median,
positive share, and interquartile range. The ranking is descriptive, not a
chase list.

### 6. Multi-horizon trend heatmap

Do return and moving-average signals agree across symbols and horizons? Each
supported symbol has six signed cells: 5-, 20-, and 63-session return plus
distance from 20-, 50-, and 200-session averages. Color scaling may be
winsorized, but labels and interpretation retain actual values; unsupported
cells remain visible.

### 7. Volatility and peak-distance regime

Are risk conditions becoming more or less adverse? The chart shows SMH
20-session annualized realized volatility, distance from the rolling 63-session
peak, and optional VIX. Distance from peak is current drawdown, not a forecast.
The interpretation also uses volatility percentile and five-session change.

### 8. Risk/reward map

How do observed return, volatility, and liquidity compare across symbols?
Eligible members are placed by 63-session adjusted return and 20-session
annualized realized volatility. Reference lines use supported medians; bubble
size uses median dollar volume, and an open marker discloses missing liquidity.
The map is not a portfolio optimizer.

## Deterministic composite

The composite has 30 fixed-denominator atoms. Each available atom votes +1, 0,
or -1 at a published threshold. An unavailable atom votes zero and stays in its
pillar denominator, so missing data cannot amplify the remaining evidence.
Each pillar score is `2 * vote sum / fixed input count`, scaled from -2 through
+2, and the weighted total is rounded half-up to two decimals.

The five weights are:

- absolute trend: 25% (6 inputs)
- relative leadership: 20% (8 inputs)
- breadth and participation: 25% (8 inputs)
- momentum distribution: 15% (4 inputs)
- volatility/drawdown risk: 15% (4 inputs)

The score maps deterministically to `risk-on`, `constructive`, `mixed`,
`defensive`, or `risk-off`. The **Trading decision summary** publishes `regime`,
`confidence`, `supports`, `challenges`, what changed, and conditions that would
change the view. A five-session audit is included when enough independently
computed snapshots exist.

## Confidence, coverage, and freshness

A watchlist member is covered only with at least 64 eligible daily observations
and no stale, invalid, or future-dated input. SMH, SOXX, QQQ, and SOXL are
required; VIX is optional. Publication fails below 70% watchlist coverage or
when a required benchmark is missing, stale, or has insufficient history. It
also requires valid dates and prices, no duplicate symbol/date rows, no likely
100x unit switch, and exactly eight validated artifacts.

Freshness is reported as `current`, `delayed`, or `stale`. The report preserves
the evaluated time, calendar age, and expected-session lag. Freshness and
coverage are separate: current data can be partial, while broad coverage can be
stale. Missing required data, old data, unavailable pillars, or fewer than 70%
of fixed scoring inputs caps confidence low. Other material incompleteness,
including coverage below 90%, caps it at medium.

The hosted workflow starts Monday through Friday at **6:20 PM Eastern**. Its
XNYS gate allows automatic work only for a completed exchange session. A
candidate deploys only when validated publication logic permits it; an
unchanged date, build failure, or validation failure preserves the last
successful report. A successful new deployment alone can alert the fixed
recipient `1118xmb@gmail.com`.

## Provider and risk boundary

The default adapter is pinned to `yfinance==1.5.1`, a keyless unofficial data
source intended for personal research rather than execution-quality use. Data
may be delayed, incomplete, revised, or temporarily unavailable. Fetching uses
at most three attempts, and failures remain visible rather than being silently
repaired.

Research only - not individualized investment advice or a recommendation to
buy or sell. Signals are backward-looking and can whipsaw. The report does not
place orders, promise returns, use personal positions, or provide personalized
sizing.
