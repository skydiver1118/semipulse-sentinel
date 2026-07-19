# SemiPulse Sentinel

SemiPulse Sentinel builds a deterministic trading-day research report for the
semiconductor market. It retrieves adjusted daily market data, validates
freshness and coverage, renders exactly eight SVG charts, and publishes a
static HTML report plus canonical `report.json`. The public JSON schema is
`semipulse-report-v1`, and `market_as_of` identifies the completed market
session represented by the report.

Canonical interfaces:

- [GitHub repository](https://github.com/skydiver1118/semipulse-sentinel)
- [SemiPulse Sentinel report](https://skydiver1118.github.io/semipulse-sentinel/)
- [Canonical report.json](https://skydiver1118.github.io/semipulse-sentinel/report.json)

The hosted workflow starts Monday through Friday at 6:20 PM Eastern
(`America/New_York`). An XNYS calendar gate permits an automatic build only for
a completed trading session. Publication requires a validated candidate whose
`market_as_of` advances beyond the current daily report; the first migration
from the previously published schema is one-way. An unchanged session, failed
build, or failed validation leaves the last successful report online and sends
no email. After a new report deploys successfully, one alert with the permanent
report link goes to the hard-locked recipient `1118xmb@gmail.com`.

## What the report answers

The **Trading decision summary** combines 30 fixed scoring inputs into a
five-pillar regime while preserving supporting and challenging evidence. The
eight chart purposes are:

1. **Semiconductor complex performance** - Are SMH, SOXX, QQQ, and SOXL
   strengthening or weakening across recent horizons?
2. **Relative strength versus QQQ** - Are semiconductor benchmarks leading or
   lagging broad technology?
3. **Watchlist breadth** - How much of the watchlist is above key moving
   averages?
4. **Equal-weight participation** - Is the typical constituent confirming or
   diverging from SMH?
5. **Momentum leaders and laggards** - How are 20-session returns distributed?
6. **Multi-horizon trend heatmap** - Do return and moving-average signals agree
   across symbols and horizons?
7. **Volatility and peak-distance regime** - Are volatility and drawdown
   conditions becoming more or less adverse?
8. **Risk/reward map** - How do observed return, volatility, and liquidity
   compare across eligible symbols?

Every chart card keeps its explanation explicit under **What this chart
measures**, **Evidence**, **What it means now**, **How it may inform trading
decisions**, and **Counter-signal**. The JSON exposes the corresponding
`purpose`, evidence, interpretation, trading relevance, and counter-signal
fields for operator and agent review.

See [docs/methodology.md](docs/methodology.md) for chart calculations,
deterministic scoring, freshness, coverage, and provider limits. See
[docs/operations.md](docs/operations.md) for the 6:20 PM Eastern schedule,
XNYS gate, local commands, manual dispatch, email, and recovery.

## Local daily commands

Python 3.11 or later is required. From the repository root:

```powershell
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps --no-build-isolation .
python -m semipulse_sentinel build --watchlist config/watchlist.csv --output site --json
python -m semipulse_sentinel validate --site site --json
python -m semipulse_sentinel decide-publication --candidate site/report.json --published published-report.json --github-output publication-output.txt --json
python -m semipulse_sentinel notify --json
```

`build` is the network boundary. It renders in a temporary sibling directory
and replaces the requested destination only after complete validation.
`decide-publication` compares validated report dates; `notify` is a post-deploy
operation whose SMTP settings come from the environment and whose recipient
cannot be overridden.

## Research boundary

Research only - not individualized investment advice or a recommendation to
buy or sell. Market data may be delayed, incomplete, or revised. Leveraged ETFs
such as SOXL can suffer path-dependent decay and large losses. Verify market
data independently before acting. SemiPulse Sentinel does not place orders,
optimize a portfolio, promise returns, or provide personalized sizing.

## License

MIT. See [LICENSE](LICENSE).
