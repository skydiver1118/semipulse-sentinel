# Methodology

SemiPulse Sentinel turns one normalized daily OHLCV download into a versioned
metrics bundle, exactly eight chart artifacts, and deterministic prose. The
same observations drive the charts, chart interpretations, and executive
summary. Unsupported observations are disclosed and excluded from aggregates;
they are not silently imputed.

The current calculation version is `semipulse-metrics-v1`, the interpretation
version is `semipulse-rules-v1`, and the public report schema is
`semipulse-report-v1`.

## The eight charts

### 1. Semiconductor complex performance

SMH, SOXX, QQQ, and SOXL adjusted closes are rebased to 100 across the latest
126 sessions. The interpretation uses 5-, 20-, and 63-session returns, a
20-session log-price slope, distance from the 20- and 50-session simple moving
averages, and distance from the recent peak. SOXL is explicitly treated as a
leveraged, path-dependent instrument rather than a normal unleveraged proxy.

### 2. Relative strength versus QQQ

The SMH/QQQ and SOXX/QQQ adjusted-close ratios are rebased to 100 and displayed
with 20- and 50-session moving averages. The signal uses 20- and 63-session
ratio changes, location versus both averages, and the supported 20/50
crossover state. This separates semiconductor-specific leadership from broad
technology beta.

### 3. Watchlist breadth

For each date, the chart reports the percentage of eligible watchlist members
above their 20-, 50-, and 200-session simple moving averages. Each window has
its own covered and missing denominator. The interpretation uses current
levels, five-session changes, and the ordering of the three breadth horizons.

### 4. Equal-weight participation

Across the 63-session return horizon (64 common observations), the chart
compares the median watchlist cumulative return with SMH and shows their
percentage-point spread.
It also records the share of eligible symbols outperforming SMH and the
cross-sectional dispersion. A symbol must have a common baseline and current
observation to participate.

### 5. Momentum leaders and laggards

Supported symbols are sorted by actual 20-session adjusted return. The
interpretation reports the leaders, laggards, median, positive share, and
interquartile range. The ranking is descriptive evidence, not a chase list or
recommendation.

### 6. Multi-horizon trend heatmap

Each supported symbol has six signed cells: 5-, 20-, and 63-session return and
distance from its 20-, 50-, and 200-session simple moving averages. Values may
be winsorized for color scaling only; printed labels retain the actual values.
Unsupported cells remain visibly unsupported. The interpretation considers
the positive-cell share, consistent trends, reversals, and missing cells.

### 7. Volatility and peak-distance regime

The risk chart shows SMH 20-session annualized realized volatility, current
distance from the rolling 63-session price peak, and VIX when available. Chart
7 uses peak distance - the current adjusted close divided by the rolling peak
minus one - rather than a forecast or a separate historical maximum-drawdown
statistic. The interpretation also uses the trailing-year volatility
percentile and five-session volatility change. VIX is optional and never
blocks the other two series.

### 8. Risk/reward map

Each eligible symbol is placed by 63-session adjusted return and 20-session
annualized realized volatility. Reference lines are the supported medians.
Bubble size represents median 20-session dollar volume when it is available;
an open marker discloses missing liquidity instead of inventing it. The map
supports cross-sectional research and is not a portfolio optimizer.

## Composite regime

The composite has 30 fixed-denominator atoms. Each available atom votes +1,
0, or -1 at a published threshold. An unavailable atom votes zero and remains
in its pillar denominator, so missing observations cannot amplify the
remaining evidence. Each pillar score is `2 * vote sum / fixed input count`,
which scales it from -2 through +2. The weighted total is rounded half-up to
two decimals.

The five weights are:

- absolute trend: 25% (6 inputs)
- relative leadership: 20% (8 inputs)
- breadth and participation: 25% (8 inputs)
- momentum distribution: 15% (4 inputs)
- volatility/drawdown risk: 15% (4 inputs)

The score maps to one of five labels:

- `risk-on` at +1.20 or higher;
- `constructive` from +0.45 through +1.19;
- `mixed` above -0.45 and below +0.45;
- `defensive` above -1.20 through -0.45; and
- `risk-off` at -1.20 or lower.

The report includes supporting evidence, opposing evidence or an invalidation
condition, and a five-session audit when enough snapshots exist. Its prose is
template-based and deterministic; an LLM is not used to create the nightly
signal.

## Confidence, coverage, and publication gates

A watchlist member is covered only when it has at least 64 eligible daily
observations and is not stale, invalid, or dated in the future. Missing and
unsupported symbols remain named in the coverage section. Required benchmarks
are SMH, SOXX, QQQ, and SOXL; VIX is optional.

Publication fails below 70% watchlist coverage or when a required benchmark is
missing, stale, or has insufficient history. Publication also requires no
duplicate symbol/date rows, valid dates and prices, no consecutive adjusted-
price ratio near 100x or 0.01x, and exactly eight validated artifacts. The
ratio gate treats a 90x-110x scale switch (or its reciprocal) as a likely
currency-unit mixup and blocks publication rather than altering the source
data. Confidence is capped low for coverage below 70%, a missing required
input, data more than three calendar days old, a wholly unavailable pillar, or
fewer than 70% of the fixed scoring inputs. Other incompleteness - including
coverage below 90%, optional-data gaps, warnings, cases where the
expected-session lag is unknown or greater than one, or an incomplete
five-session audit - caps confidence at medium.

## Freshness

Freshness is reported as `current`, `delayed`, or `stale`:

- `current`: zero expected-session lag and no more than three calendar days
  old;
- `delayed`: no more than one expected-session lag and no more than three
  calendar days old; or
- `stale`: anything older or farther behind.

The expected-session calculation is deliberately a weekday freshness heuristic,
not an exchange-holiday calendar. At or after 4:15 PM
America/New_York it expects the current weekday; before that it expects the
previous weekday. On a weekend it expects the preceding Friday. A market
holiday can therefore produce a conservative delay or stale indication.

## Data source and provenance

The default adapter is pinned to `yfinance==1.5.1`. It is a keyless,
unofficial source intended for personal research, not a licensed or
execution-quality market-data feed. Data can be delayed, incomplete, revised,
or temporarily unavailable. A fetch uses bounded retries of no more than three
attempts. Upstream price repair is disabled because it can return an empty
multi-symbol frame on hosted Linux; the fail-closed unit-discontinuity gate
above protects against its principal 100x scale-error class without silently
rewriting provider values. Daily bars do not describe intraday moves after the
latest completed bar.

The current `config/watchlist.csv` is an explicitly labeled recovered seed.
The missing upload's identity was not verifiable, so every row remains
`recovered_inference` until the user confirms or replaces it. The recovered
`Last` and `Chg%` columns are not inputs to the calculations; current adjusted
OHLCV data comes from the provider.

## Risk boundary

Research only - not individualized investment advice or a recommendation to
buy or sell. Signals are backward-looking and can whipsaw. Market data may be
delayed, incomplete, or revised; SOXL introduces leverage, path dependency,
decay, and large-loss risk. Verify market data independently before acting.
The report does not place orders, promise returns, use personal positions, or
provide personalized sizing.
