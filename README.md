# SemiPulse Sentinel

SemiPulse Sentinel builds a deterministic nightly research report for the
semiconductor market. It downloads daily adjusted market data, validates its
freshness and coverage, renders exactly eight SVG charts, and publishes a
static HTML and JSON report only after the complete site passes validation.

The public source and independently verified live endpoints are:

- [GitHub repository](https://github.com/skydiver1118/semipulse-sentinel)
- [SemiPulse Sentinel report](https://skydiver1118.github.io/semipulse-sentinel/)
- [Canonical report.json](https://skydiver1118.github.io/semipulse-sentinel/report.json)

GitHub Pages is configured for the audited Actions workflow. A successful
manual deployment has verified the HTML, JSON, and all eight chart assets;
subsequent refreshes are requested nightly at 6:00 PM America/New_York.

## What the report contains

The report pairs each chart with an observation-led interpretation and then
combines 30 fixed scoring inputs into a five-pillar regime. The eight charts
cover:

1. semiconductor-complex performance;
2. relative strength versus QQQ;
3. watchlist breadth;
4. equal-weight participation;
5. momentum leaders and laggards;
6. a multi-horizon trend heatmap;
7. volatility and distance from the recent peak; and
8. a return, volatility, and liquidity risk/reward map.

The input watchlist is replaceable without changing code. Its current rows are
labeled `source_status=recovered_inference` because the identity of the
original upload could not be verified. The recovered `Last` and `Chg%` values
are retained only as provenance and are never used as current market data.

See [docs/methodology.md](docs/methodology.md) for chart calculations,
composite scoring, freshness, coverage, and provider limitations. See
[docs/operations.md](docs/operations.md) for scheduling, local verification,
manual runs, Pages setup, and recovery.

## Local verification

Python 3.11 or later is required. From the repository root:

```powershell
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps --no-build-isolation .
python -m pytest -q
python -m semipulse_sentinel doctor --watchlist config/watchlist.csv --site site --json
```

The tests and `doctor` command are offline. A report build is the deliberate
network boundary because it retrieves market data from the configured
provider:

```powershell
python -m semipulse_sentinel build --watchlist config/watchlist.csv --output site --json
python -m semipulse_sentinel validate --site site --json
```

Successful publication is failure-atomic: the new site is built and validated
in a staging directory, then replaces the destination. A failed build or
validation does not replace the prior valid site.

## Research boundary

Research only - not individualized investment advice or a recommendation to
buy or sell. Market data may be delayed, incomplete, or revised. Leveraged
ETFs such as SOXL can suffer path-dependent decay and large losses. Verify
prices and signals with a licensed source before trading. SemiPulse Sentinel
does not place orders, optimize a portfolio, or provide personalized sizing.

## License

MIT. See [LICENSE](LICENSE).
