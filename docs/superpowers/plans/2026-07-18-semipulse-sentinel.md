# SemiPulse Sentinel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, publish, schedule, and install a reusable SemiPulse Sentinel agent that produces a validated nightly GitHub Pages report with exactly eight semiconductor-market charts, an interpretation for each, and a cross-chart summary.

**Architecture:** A typed Python package loads the recovered watchlist, obtains normalized daily OHLCV data through a provider interface, validates freshness and coverage, computes deterministic market metrics, renders eight SVG charts and a canonical report model, and atomically builds a static site. GitHub Actions runs the same CLI every day at 6:00 PM America/New_York and deploys only validated artifacts; a thin Codex skill lets future chats inspect or refresh the monitor.

**Tech Stack:** Python 3.11+, pandas, NumPy, yfinance 1.5.1, matplotlib/Agg, Jinja2, pytest, Ruff, mypy, GitHub Actions, GitHub Pages, PowerShell installer.

## Global Constraints

- Follow `docs/superpowers/specs/2026-07-18-semipulse-sentinel-design.md` exactly.
- The report contains exactly eight chart cards and eight SVG files in the stable order defined by the specification.
- The nightly schedule is `0 18 * * *` with `timezone: "America/New_York"` and runs every calendar day.
- The uploaded file is absent; `config/watchlist.csv` is labeled `recovered_inference` and seeded only from the local recovery candidate `semi_05Jul2026_1149.csv`.
- Values from the recovered file's `Last` and `Chg%` columns are provenance only and never current inputs.
- A build with missing required benchmarks, less than 70% watchlist coverage, stale required data, invalid prices, duplicate dates, or an output count other than eight fails before publication.
- Every report distinguishes observations, deterministic inference, counter-evidence, and limitations.
- No brokerage connection, order entry, personalized allocation, hidden secret, analytics tracker, or unsupported return promise is permitted.
- Runtime network access is confined to the provider adapter.
- Generated `site/` output is never committed to the source branch.
- Use test-driven development and commit after every task.

---

### Task 1: Package scaffold, immutable models, and recovered watchlist

**Files:**

- Create: `pyproject.toml`
- Create: `requirements.lock`
- Create: `config/watchlist.csv`
- Create: `src/semipulse_sentinel/__init__.py`
- Create: `src/semipulse_sentinel/__main__.py`
- Create: `src/semipulse_sentinel/version.py`
- Create: `src/semipulse_sentinel/models.py`
- Create: `src/semipulse_sentinel/config.py`
- Create: `src/semipulse_sentinel/watchlist.py`
- Create: `tests/unit/test_watchlist.py`
- Create: `tests/unit/test_models.py`

**Interfaces:**

- Produces: `WatchlistEntry(symbol: str, source_status: str, source_last: Decimal | None, source_change_pct: Decimal | None)`.
- Produces: `load_watchlist(path: Path) -> tuple[WatchlistEntry, ...]`.
- Produces: `AppConfig` with required benchmarks `("SMH", "SOXX", "QQQ", "SOXL")`, optional `("^VIX",)`, `timezone="America/New_York"`, and `chart_count=8`.
- Produces: immutable shared dataclasses `QualityReport`, `ChartInsight`, `CompositeInsight`, `ChartArtifact`, and `ReportModel`.

- [ ] **Step 1: Write strict watchlist and model tests**

```python
def test_recovered_watchlist_has_expected_identity(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.csv"
    path.write_text(
        "Symbol,Last,Chg%,Color,source_status\n"
        "NVDA,194.44,-1.59,,recovered_inference\n",
        encoding="utf-8",
    )
    assert load_watchlist(path) == (
        WatchlistEntry(
            symbol="NVDA",
            source_status="recovered_inference",
            source_last=Decimal("194.44"),
            source_change_pct=Decimal("-1.59"),
        ),
    )


@pytest.mark.parametrize("symbol", ["", "NV DA", "=NVDA", "../NVDA"])
def test_watchlist_rejects_unsafe_symbols(tmp_path: Path, symbol: str) -> None:
    path = tmp_path / "watchlist.csv"
    path.write_text(
        f"Symbol,Last,Chg%,Color,source_status\n{symbol},1,0,,recovered_inference\n",
        encoding="utf-8",
    )
    with pytest.raises(WatchlistError):
        load_watchlist(path)


def test_report_model_is_immutable() -> None:
    assert ReportModel.__dataclass_params__.frozen is True
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest tests/unit/test_watchlist.py tests/unit/test_models.py -q`  
Expected: collection fails because `semipulse_sentinel` does not exist.

- [ ] **Step 3: Add packaging, model, configuration, and parser implementation**

The parser must use `csv.DictReader`, require the exact headers, normalize symbols to uppercase, reject duplicates and spreadsheet-formula prefixes, parse decimal provenance values without using them as market data, and return a tuple sorted in file order.

```python
_SYMBOL = re.compile(r"^[A-Z^][A-Z0-9.^-]{0,14}$")


def load_watchlist(path: Path) -> tuple[WatchlistEntry, ...]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"Symbol", "Last", "Chg%", "Color", "source_status"}
        if set(reader.fieldnames or ()) != required:
            raise WatchlistError(f"expected headers {sorted(required)}")
        entries: list[WatchlistEntry] = []
        seen: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            symbol = row["Symbol"].strip().upper()
            if not _SYMBOL.fullmatch(symbol) or symbol in seen:
                raise WatchlistError(f"invalid or duplicate symbol at row {row_number}")
            seen.add(symbol)
            entries.append(
                WatchlistEntry(
                    symbol=symbol,
                    source_status=row["source_status"].strip(),
                    source_last=_optional_decimal(row["Last"]),
                    source_change_pct=_optional_decimal(row["Chg%"]),
                )
            )
    if not entries:
        raise WatchlistError("watchlist is empty")
    return tuple(entries)
```

Seed `config/watchlist.csv` with all 23 audited symbols and `source_status=recovered_inference`. Configure the `src` layout, console script `semipulse-sentinel = semipulse_sentinel.cli:main`, runtime dependencies, and test/lint settings in `pyproject.toml`. Generate `requirements.lock` with hashes using `pip-tools` from the declared dependency set.

- [ ] **Step 4: Run tests, lint, and import smoke**

Run:

```powershell
python -m pip install -e ".[dev]"
python -m pytest tests/unit/test_watchlist.py tests/unit/test_models.py -q
python -m ruff check src tests
python -c "from semipulse_sentinel.watchlist import load_watchlist; print(len(load_watchlist(__import__('pathlib').Path('config/watchlist.csv'))))"
```

Expected: tests and Ruff pass; smoke prints `23`.

- [ ] **Step 5: Commit**

```powershell
git add pyproject.toml requirements.lock config src tests
git commit -m "feat: scaffold SemiPulse Sentinel watchlist"
```

### Task 2: Provider boundary and fail-closed data quality

**Files:**

- Create: `src/semipulse_sentinel/providers/__init__.py`
- Create: `src/semipulse_sentinel/providers/base.py`
- Create: `src/semipulse_sentinel/providers/yfinance_provider.py`
- Create: `src/semipulse_sentinel/quality.py`
- Create: `tests/fixtures.py`
- Create: `tests/unit/test_provider.py`
- Create: `tests/unit/test_quality.py`

**Interfaces:**

- Consumes: `AppConfig` and `WatchlistEntry`.
- Produces: `MarketData(prices: DataFrame, fetched_at: datetime, provider: str, errors: tuple[SymbolError, ...])`.
- Produces: `MarketDataProvider.fetch(symbols: Sequence[str], start: date, end: date) -> MarketData`.
- Produces: `validate_market_data(data: MarketData, config: AppConfig, watchlist: tuple[WatchlistEntry, ...], now: datetime) -> QualityReport`; raises `PublicationBlocked` on fatal conditions.

- [ ] **Step 1: Write provider-normalization and quality-boundary tests**

```python
def test_provider_normalizes_to_tidy_adjusted_ohlcv(monkeypatch) -> None:
    monkeypatch.setattr(yf, "download", fake_multilevel_download)
    data = YFinanceProvider(max_attempts=1).fetch(
        ["SMH", "NVDA"], date(2025, 1, 1), date(2025, 7, 1)
    )
    assert list(data.prices.columns) == [
        "date", "symbol", "open", "high", "low", "close", "adj_close", "volume"
    ]
    assert data.prices.groupby("symbol")["date"].is_monotonic_increasing.all()


def test_quality_blocks_below_seventy_percent_coverage(
    market_data_factory, app_config, recovered_watchlist
) -> None:
    data = market_data_factory(covered_symbols=recovered_watchlist[:16])
    with pytest.raises(PublicationBlocked, match="coverage"):
        validate_market_data(data, app_config, recovered_watchlist, NOW)


def test_quality_names_optional_vix_without_blocking(
    complete_market_data, app_config, recovered_watchlist
) -> None:
    without_vix = complete_market_data.without("^VIX")
    report = validate_market_data(without_vix, app_config, recovered_watchlist, NOW)
    assert "^VIX" in report.missing_optional
    assert report.publishable is True
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest tests/unit/test_provider.py tests/unit/test_quality.py -q`  
Expected: failures for missing provider and validator modules.

- [ ] **Step 3: Implement provider and validation**

Call `yfinance.download` once for the combined symbol set with `period="2y"`, `interval="1d"`, `auto_adjust=False`, `actions=False`, `group_by="column"`, `threads=True`, `repair=True`, and a 30-second timeout. Normalize single- and multi-index results identically. Retry at most three times with injected sleep, and never log cookies or raw responses.

Validation must check:

```python
fatal_reasons = (
    required_benchmark_missing
    or watchlist_coverage < Decimal("0.70")
    or duplicate_symbol_dates
    or nonpositive_required_prices
    or latest_required_bar_is_stale
)
if fatal_reasons:
    raise PublicationBlocked("; ".join(reason_codes))
```

Use the injected New York clock and weekday/session heuristic documented in the spec. The report must list covered, missing, stale, and optional-missing symbols and exact denominators.

- [ ] **Step 4: Verify provider and quality behavior**

Run:

```powershell
python -m pytest tests/unit/test_provider.py tests/unit/test_quality.py -q
python -m pytest -q
python -m ruff check src tests
```

Expected: all tests and lint pass.

- [ ] **Step 5: Commit**

```powershell
git add src/semipulse_sentinel/providers src/semipulse_sentinel/quality.py tests
git commit -m "feat: validate normalized market data"
```

### Task 3: Versioned metrics and eight chart datasets

**Files:**

- Create: `src/semipulse_sentinel/metrics.py`
- Create: `tests/unit/test_metrics.py`

**Interfaces:**

- Consumes: validated tidy adjusted OHLCV.
- Produces: `MetricBundle` containing `normalized_performance`, `relative_strength`, `breadth`, `participation`, `momentum`, `trend_heatmap`, `risk_regime`, `risk_reward`, and exact scalar evidence.
- Produces: `compute_metrics(prices: DataFrame, watchlist_symbols: Sequence[str], as_of: date) -> MetricBundle`.

- [ ] **Step 1: Write exact indicator tests**

```python
def test_normalization_rebases_each_series_to_100(prices_fixture) -> None:
    result = compute_metrics(prices_fixture, WATCHLIST, AS_OF)
    first = result.normalized_performance.groupby("symbol")["value"].first()
    assert first.to_dict() == {"QQQ": 100.0, "SMH": 100.0, "SOXL": 100.0, "SOXX": 100.0}


def test_breadth_uses_available_denominator_per_date(prices_fixture) -> None:
    result = compute_metrics(prices_fixture, WATCHLIST, AS_OF)
    row = result.breadth.query("date == @AS_OF").iloc[0]
    assert row["covered_count"] == 20
    assert row["above_20_pct"] == pytest.approx(65.0)


def test_annualized_volatility_uses_adjusted_log_returns(prices_fixture) -> None:
    result = compute_metrics(prices_fixture, WATCHLIST, AS_OF)
    expected = np.log(SMH_ADJ_CLOSE).diff().tail(20).std(ddof=1) * np.sqrt(252)
    assert result.scalars["smh_vol_20"] == pytest.approx(expected)
```

Add boundary tests for insufficient lookbacks, constant prices, missing volume, all-negative returns, ratio alignment, drawdown sign, percentile ties, and risk/reward medians.

- [ ] **Step 2: Run the metric test and confirm RED**

Run: `python -m pytest tests/unit/test_metrics.py -q`  
Expected: import failure for `metrics`.

- [ ] **Step 3: Implement pure metric functions and aggregate bundle**

Use adjusted close for return math, unadjusted close only for display when explicitly labeled, and volume times unadjusted close for dollar-volume bubbles. Preserve NaN rather than filling market observations. Every rolling calculation uses `min_periods=window`.

```python
def annualized_realized_volatility(series: pd.Series, window: int = 20) -> pd.Series:
    log_returns = np.log(series).diff()
    return log_returns.rolling(window, min_periods=window).std(ddof=1) * np.sqrt(252)


def max_drawdown(series: pd.Series, window: int = 63) -> pd.Series:
    rolling_peak = series.rolling(window, min_periods=window).max()
    return series.div(rolling_peak).sub(1.0)
```

Return exactly eight named datasets and a scalar dictionary with stable keys used by interpretations.

- [ ] **Step 4: Verify metrics**

Run: `python -m pytest tests/unit/test_metrics.py -q && python -m pytest -q`  
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/semipulse_sentinel/metrics.py tests/unit/test_metrics.py
git commit -m "feat: compute semiconductor market metrics"
```

### Task 4: Deterministic chart interpretations and composite summary

**Files:**

- Create: `src/semipulse_sentinel/interpret.py`
- Create: `tests/unit/test_interpret.py`

**Interfaces:**

- Consumes: `MetricBundle` and `QualityReport`.
- Produces: `interpret_charts(metrics, quality) -> tuple[ChartInsight, ...]` with length eight.
- Produces: `build_composite(insights, metrics, quality) -> CompositeInsight`.
- Each `ChartInsight` has `chart_id`, `headline`, `signal`, `evidence`, `interpretation`, `trading_relevance`, `counter_signal`, and `notes`.

- [ ] **Step 1: Write regime, confidence, and wording tests**

```python
@pytest.mark.parametrize(
    ("score", "label"),
    [(1.20, "risk-on"), (0.45, "constructive"), (0.44, "mixed"),
     (-0.44, "mixed"), (-0.45, "defensive"), (-1.20, "risk-off")],
)
def test_composite_boundaries(score: float, label: str) -> None:
    assert classify_regime(score) == label


def test_every_chart_has_evidence_and_counter_signal(
    constructive_metrics, high_quality
) -> None:
    insights = interpret_charts(constructive_metrics, high_quality)
    assert [item.chart_id for item in insights] == [f"chart-{n}" for n in range(1, 9)]
    assert all(item.evidence and item.counter_signal for item in insights)


def test_low_coverage_caps_confidence_and_language(
    constructive_metrics, low_coverage_quality
) -> None:
    summary = build_composite(
        interpret_charts(constructive_metrics, low_coverage_quality),
        constructive_metrics,
        low_coverage_quality,
    )
    assert summary.confidence == "low"
    assert "coverage" in " ".join(summary.challenges).lower()
    forbidden = ("guaranteed", "will rise", "buy now", "sure thing")
    assert not any(term in summary.as_text().lower() for term in forbidden)
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest tests/unit/test_interpret.py -q`  
Expected: import failure for `interpret`.

- [ ] **Step 3: Implement `semipulse-rules-v1`**

Implement each pillar as a focused function returning `PillarScore(value: Decimal, evidence, counter_evidence)`. Apply weights `0.25, 0.20, 0.25, 0.15, 0.15` without renormalizing missing pillars. Missing pillars contribute zero and reduce confidence.

```python
REGIME_BOUNDS = (
    (Decimal("1.20"), "risk-on"),
    (Decimal("0.45"), "constructive"),
    (Decimal("-0.45"), "mixed"),
    (Decimal("-1.20"), "defensive"),
)


def classify_regime(score: Decimal) -> str:
    if score >= Decimal("1.20"):
        return "risk-on"
    if score >= Decimal("0.45"):
        return "constructive"
    if score > Decimal("-0.45"):
        return "mixed"
    if score > Decimal("-1.20"):
        return "defensive"
    return "risk-off"
```

Generate prose from bounded templates that interpolate rounded exact values. Every positive view includes a challenge; every negative view includes a potential improvement trigger. SOXL language always names leverage/path dependency.

- [ ] **Step 4: Verify interpretation consistency**

Run:

```powershell
python -m pytest tests/unit/test_interpret.py -q
python -m pytest -q
python -m ruff check src tests
```

Expected: all checks pass.

- [ ] **Step 5: Commit**

```powershell
git add src/semipulse_sentinel/interpret.py tests/unit/test_interpret.py
git commit -m "feat: interpret eight market signals"
```

### Task 5: Exactly eight accessible SVG charts

**Files:**

- Create: `src/semipulse_sentinel/charts.py`
- Create: `src/semipulse_sentinel/style.py`
- Create: `tests/unit/test_charts.py`

**Interfaces:**

- Consumes: `MetricBundle`, `tuple[ChartInsight, ...]`, and output directory.
- Produces: `render_charts(metrics, insights, output_dir) -> tuple[ChartArtifact, ...]` with eight stable filenames `chart-01-complex-performance.svg` through `chart-08-risk-reward.svg`.

- [ ] **Step 1: Write chart contract and accessibility tests**

```python
def test_renderer_outputs_exactly_eight_valid_svgs(
    metric_bundle, insights, tmp_path
) -> None:
    artifacts = render_charts(metric_bundle, insights, tmp_path)
    assert len(artifacts) == 8
    assert [item.chart_id for item in artifacts] == [f"chart-{n}" for n in range(1, 9)]
    for artifact in artifacts:
        root = ElementTree.parse(artifact.path).getroot()
        assert root.tag.endswith("svg")
        assert artifact.path.stat().st_size > 1_000
        assert artifact.alt_text


def test_chart_color_palette_remains_legible_in_grayscale(
    metric_bundle, insights, tmp_path
) -> None:
    artifacts = render_charts(metric_bundle, insights, tmp_path)
    assert all(item.has_non_color_encoding for item in artifacts)
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest tests/unit/test_charts.py -q`  
Expected: import failure for `charts`.

- [ ] **Step 3: Implement eight focused renderers**

Configure Matplotlib before importing pyplot:

```python
import matplotlib
matplotlib.use("Agg")
```

Use a dark report palette, white plotting panels, colorblind-safe series colors, line-style/marker redundancy, concise axes, end labels where possible, and metadata stripped from SVG. Close every figure in `finally`. Heatmap color scaling may winsorize at the 5th/95th percentiles, but text labels show actual percentages.

The dispatcher is a fixed tuple, not dynamic discovery:

```python
RENDERERS = (
    render_complex_performance,
    render_relative_strength,
    render_breadth,
    render_participation,
    render_momentum,
    render_trend_heatmap,
    render_risk_regime,
    render_risk_reward,
)
```

- [ ] **Step 4: Verify SVG output and full suite**

Run: `python -m pytest tests/unit/test_charts.py -q && python -m pytest -q`  
Expected: exactly eight valid SVGs and all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/semipulse_sentinel/charts.py src/semipulse_sentinel/style.py tests/unit/test_charts.py
git commit -m "feat: render eight accessible market charts"
```

### Task 6: Canonical report, atomic site build, and CLI

**Files:**

- Create: `src/semipulse_sentinel/templates/report.html.j2`
- Create: `src/semipulse_sentinel/static/report.css`
- Create: `src/semipulse_sentinel/report.py`
- Create: `src/semipulse_sentinel/pipeline.py`
- Create: `src/semipulse_sentinel/cli.py`
- Create: `tests/unit/test_report.py`
- Create: `tests/integration/test_pipeline.py`
- Create: `tests/integration/test_cli.py`
- Create: `tests/golden/report-structure.json`

**Interfaces:**

- Consumes: provider, watchlist path, output path, and injected clock.
- Produces: `build_report(...) -> BuildResult` with output hash, as-of date, quality, and eight artifacts.
- CLI: `python -m semipulse_sentinel build --watchlist config/watchlist.csv --output site`.
- CLI: `python -m semipulse_sentinel validate --site site`.
- CLI: `python -m semipulse_sentinel doctor --json`.

- [ ] **Step 1: Write report and failure-atomicity tests**

```python
def test_complete_site_has_summary_before_eight_chart_cards(
    fake_provider, fixed_clock, tmp_path
) -> None:
    result = build_report(fake_provider, WATCHLIST_PATH, tmp_path / "site", fixed_clock)
    html = (result.output_dir / "index.html").read_text(encoding="utf-8")
    assert html.index('id="executive-summary"') < html.index('id="chart-1"')
    assert html.count('class="chart-card"') == 8
    assert html.count('class="chart-interpretation"') == 8
    assert "Research only—not individualized investment advice" in html


def test_failed_rebuild_preserves_previous_site(
    fake_provider, failing_chart_renderer, fixed_clock, tmp_path
) -> None:
    destination = tmp_path / "site"
    destination.mkdir()
    (destination / "sentinel.txt").write_text("known-good", encoding="utf-8")
    with pytest.raises(BuildFailed):
        build_report(
            fake_provider,
            WATCHLIST_PATH,
            destination,
            fixed_clock,
            chart_renderer=failing_chart_renderer,
        )
    assert (destination / "sentinel.txt").read_text(encoding="utf-8") == "known-good"
```

Test HTML escaping, valid relative links, embedded JSON escaping, source-status disclosure, exact eight chart references, top-summary agreement, doctor output, structured exit codes, and no generated site committed.

- [ ] **Step 2: Run report/pipeline tests and confirm RED**

Run: `python -m pytest tests/unit/test_report.py tests/integration/test_pipeline.py tests/integration/test_cli.py -q`  
Expected: missing report/pipeline/CLI failures.

- [ ] **Step 3: Implement canonical rendering and atomic publication**

Build one immutable `ReportModel` first, serialize it to `report.json` with sorted keys, and pass that exact model to Jinja. Copy only packaged CSS. Build within `.<destination>.tmp-<uuid>`, validate, then perform an atomic rename after moving an existing destination to a sibling backup; restore the backup on failure.

```python
def validate_site(path: Path) -> SiteValidation:
    report = json.loads((path / "report.json").read_text(encoding="utf-8"))
    chart_ids = [chart["chart_id"] for chart in report["charts"]]
    if chart_ids != [f"chart-{n}" for n in range(1, 9)]:
        raise PublicationBlocked("report must contain chart-1 through chart-8")
    missing = [
        chart["image"] for chart in report["charts"]
        if not (path / chart["image"]).is_file()
    ]
    if missing:
        raise PublicationBlocked(f"missing chart assets: {missing}")
    return SiteValidation(chart_count=8, valid=True)
```

Use exit code 0 for success, 2 for invalid arguments/config, 3 for data/publication block, and 4 for unexpected failure. `doctor --json` must disclose package version, Python version, watchlist path, symbol count, provider, and current report state without network access.

- [ ] **Step 4: Verify complete offline build**

Run:

```powershell
python -m pytest tests/unit/test_report.py tests/integration/test_pipeline.py tests/integration/test_cli.py -q
python -m pytest -q
python -m ruff check src tests
python -m mypy src
```

Expected: all tests, lint, and typing pass.

- [ ] **Step 5: Commit**

```powershell
git add src/semipulse_sentinel tests
git commit -m "feat: build validated static market report"
```

### Task 7: Nightly GitHub Pages workflow and deployment tests

**Files:**

- Create: `.github/workflows/nightly-report.yml`
- Create: `scripts/verify_workflow.py`
- Create: `tests/unit/test_workflow.py`
- Create: `README.md`
- Create: `docs/methodology.md`
- Create: `docs/operations.md`
- Create: `LICENSE`

**Interfaces:**

- Consumes: `python -m semipulse_sentinel build` and `validate`.
- Produces: one GitHub Pages artifact named `github-pages` and deployment environment `github-pages`.
- Produces: exact schedule `0 18 * * *` with `America/New_York`.

- [ ] **Step 1: Write workflow structure tests**

```python
def test_workflow_has_exact_local_schedule() -> None:
    workflow = yaml.safe_load(Path(".github/workflows/nightly-report.yml").read_text())
    schedules = workflow[True]["schedule"]
    assert schedules == [{"cron": "0 18 * * *", "timezone": "America/New_York"}]


def test_deploy_has_minimum_permissions_and_validation_gate() -> None:
    workflow = load_workflow()
    assert workflow["permissions"] == {"contents": "read"}
    deploy = workflow["jobs"]["deploy"]
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}
    build_steps = workflow["jobs"]["build"]["steps"]
    assert step_index(build_steps, "Validate site") < step_index(
        build_steps, "Upload Pages artifact"
    )
```

- [ ] **Step 2: Run workflow tests and confirm RED**

Run: `python -m pytest tests/unit/test_workflow.py -q`  
Expected: missing workflow failure.

- [ ] **Step 3: Implement the build/deploy workflow**

The workflow must include `workflow_dispatch`, `schedule`, `concurrency: {group: semipulse-pages, cancel-in-progress: true}`, separate build and deploy jobs, minimum permissions, Python 3.11, `actions/checkout@v6`, `actions/setup-python@v6`, `actions/configure-pages@v5`, `actions/upload-pages-artifact@v4`, `actions/deploy-pages@v4`, `pip install --require-hashes -r requirements.lock`, offline tests before the live build, site validation, Pages configuration/upload, and deploy.

Core trigger:

```yaml
name: Nightly SemiPulse report

on:
  workflow_dispatch:
  schedule:
    - cron: "0 18 * * *"
      timezone: "America/New_York"

permissions:
  contents: read

concurrency:
  group: semipulse-pages
  cancel-in-progress: true
```

Document the exact eight charts, methodology, 6 PM timezone/DST behavior, provider limitations, manual run, local verification, and risk boundary. README must link to the live report after the repository name is confirmed.

- [ ] **Step 4: Validate YAML, tests, and documentation commands**

Run:

```powershell
python scripts/verify_workflow.py .github/workflows/nightly-report.yml
python -m pytest tests/unit/test_workflow.py -q
python -m pytest -q
python -m build
```

Expected: workflow reports valid, tests pass, and wheel/sdist build.

- [ ] **Step 5: Commit**

```powershell
git add .github scripts tests README.md docs LICENSE
git commit -m "feat: schedule nightly GitHub Pages reports"
```

### Task 8: Install the named future-chat Codex agent

**Prerequisite:** Read and follow `skill-creator` and `writing-skills` before editing these files.

**Files:**

- Create: `skill/semipulse-sentinel/SKILL.md`
- Create: `skill/semipulse-sentinel/references/operations.md`
- Create: `skill/semipulse-sentinel/agents/openai.yaml`
- Create: `scripts/install-agent.ps1`
- Create: `scripts/uninstall-agent.ps1`
- Create: `tests/unit/test_skill.py`
- Create: `tests/windows/test_install_agent.ps1`

**Interfaces:**

- Produces installed skill directory `%USERPROFILE%\.codex\skills\semipulse-sentinel`.
- Skill handshake: locate repository/report URL, run `doctor --json`, inspect `report.json`, and offer manual workflow dispatch.
- Installer is idempotent and records no mutable report state inside the skill.

- [ ] **Step 1: Write skill-contract and installer tests**

```python
def test_skill_is_thin_and_named() -> None:
    path = Path("skill/semipulse-sentinel/SKILL.md")
    data = path.read_text(encoding="utf-8")
    assert data.startswith("---\nname: semipulse-sentinel\n")
    assert "SemiPulse Sentinel" in data
    assert "doctor --json" in data
    assert "report.json" in data
    assert len(data.split()) < 1_200
```

PowerShell acceptance uses an isolated `CODEX_HOME` equivalent test root passed explicitly to the installer, invokes the installer twice, and asserts byte-identical files and no state/database/cache directory.

- [ ] **Step 2: Run skill tests and confirm RED**

Run:

```powershell
python -m pytest tests/unit/test_skill.py -q
powershell -NoProfile -ExecutionPolicy Bypass -File tests/windows/test_install_agent.ps1
```

Expected: missing skill/installer failures.

- [ ] **Step 3: Implement the thin skill and installers**

The skill frontmatter description must trigger when a future chat asks for “SemiPulse,” “semi monitor,” “semiconductor nightly report,” “refresh the eight charts,” or “interpret the semiconductor dashboard.” It instructs the chat to:

1. run `python -m semipulse_sentinel doctor --json` in the installed repository when local inspection is possible;
2. fetch the public `report.json` for read-only summaries when only the web link is available;
3. never reinterpret stale/low-coverage data as fresh;
4. use `gh workflow run nightly-report.yml` only when the user asks for or has already authorized a refresh;
5. preserve the research-only boundary.

`install-agent.ps1` accepts `-Destination` for tests and defaults to `$env:USERPROFILE\.codex\skills\semipulse-sentinel`, copies by temporary sibling and atomic rename, and refuses to delete unrelated content. The uninstall script removes only a matching manifest hash and reports whether removal occurred.

- [ ] **Step 4: Verify and install for the current user**

Run:

```powershell
python -m pytest tests/unit/test_skill.py -q
powershell -NoProfile -ExecutionPolicy Bypass -File tests/windows/test_install_agent.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-agent.ps1
Get-Content -Raw "$env:USERPROFILE\.codex\skills\semipulse-sentinel\SKILL.md"
```

Expected: tests pass and installed skill identifies `semipulse-sentinel` / SemiPulse Sentinel.

- [ ] **Step 5: Commit**

```powershell
git add skill scripts tests
git commit -m "feat: install SemiPulse Sentinel agent"
```

### Task 9: Live data acceptance and local report QA

**Files:**

- Create: `docs/live-acceptance.md`
- Create: `docs/completion-audit.md`

**Interfaces:**

- Consumes: actual keyless provider response and the recovered watchlist.
- Produces: a validated local `site/` with exactly eight current charts.

- [ ] **Step 1: Run the entire offline suite before network access**

Run:

```powershell
python -m pytest -q
python -m ruff check src tests
python -m mypy src
python -m build
```

Expected: all checks pass and `dist/` contains wheel and source distribution.

- [ ] **Step 2: Run a live build and validate it**

Run:

```powershell
python -m semipulse_sentinel build --watchlist config/watchlist.csv --output site
python -m semipulse_sentinel validate --site site
python -m semipulse_sentinel doctor --json
```

Expected: exit 0; at least 70% watchlist coverage; required benchmarks present; eight SVGs; `report.json` and `index.html` valid.

- [ ] **Step 3: Inspect the rendered report**

Serve `site/` locally, capture a full-page screenshot, and inspect desktop and mobile-width layouts. Verify the summary is above all charts, values are legible, interpretations agree with plotted data, no labels overlap materially, source/freshness warnings are prominent, and the eight chart anchors work.

Run: `python -m http.server 8765 --directory site`  
Expected: `http://127.0.0.1:8765/` returns 200.

- [ ] **Step 4: Record nonsecret live evidence**

Write `docs/live-acceptance.md` with build timestamp, market as-of date, provider name/version, covered and excluded symbols, eight artifact hashes, regime/confidence, validation commands, and limitations. Do not copy cookies or provider payloads.

- [ ] **Step 5: Commit**

```powershell
git add docs/live-acceptance.md docs/completion-audit.md
git commit -m "test: record live SemiPulse acceptance"
```

### Task 10: GitHub publication, scheduled-run verification, and final audit

**Files:**

- Update: `README.md`
- Update: `docs/operations.md`
- Update: `docs/completion-audit.md`

**Interfaces:**

- Produces: public repository `skydiver1118/semipulse-sentinel`.
- Produces: permanent page `https://skydiver1118.github.io/semipulse-sentinel/`.
- Produces: successful workflow run and Pages deployment.

- [ ] **Step 1: Confirm repository identity and create/push**

Run:

```powershell
gh auth status
gh repo view skydiver1118/semipulse-sentinel
gh repo create skydiver1118/semipulse-sentinel --public --source . --remote origin --push
```

Expected: if `repo view` reports not found, creation succeeds; if it already exists, verify ownership and configure `origin` without overwriting unrelated history.

- [ ] **Step 2: Enable Pages with GitHub Actions and dispatch**

Run:

```powershell
gh api --method POST repos/skydiver1118/semipulse-sentinel/pages -f build_type=workflow
gh workflow run nightly-report.yml --repo skydiver1118/semipulse-sentinel
gh run list --workflow nightly-report.yml --repo skydiver1118/semipulse-sentinel --limit 1
```

Expected: Pages reports `build_type=workflow` and one queued/in-progress run.

- [ ] **Step 3: Wait for and inspect the deployment**

Run:

```powershell
$runId = gh run list --workflow nightly-report.yml --repo skydiver1118/semipulse-sentinel --limit 1 --json databaseId --jq '.[0].databaseId'
gh run watch $runId --repo skydiver1118/semipulse-sentinel --exit-status
gh run view $runId --repo skydiver1118/semipulse-sentinel --log-failed
gh api repos/skydiver1118/semipulse-sentinel/pages
```

Expected: workflow conclusion `success` and Pages URL matches the interface.

- [ ] **Step 4: Verify the public page and future-chat agent**

Fetch `index.html` and `report.json` from the Pages URL with cache-busting query parameters. Assert HTTP 200, SemiPulse Sentinel name, eight chart cards/artifacts, current build timestamp, and schedule metadata.

Spawn a fresh-context reviewer with only the installed skill name. Require it to discover the live URL, read `report.json`, report freshness/coverage/regime, and identify the manual workflow command without repository conversation context.

- [ ] **Step 5: Apply completion and security audits**

Read and follow `verification-before-completion` and `requesting-code-review`. Run:

```powershell
python -m pytest -q
python -m ruff check src tests
python -m mypy src
python -m build
python -m semipulse_sentinel validate --site site
git diff --check
git status --short --branch
gh run list --workflow nightly-report.yml --repo skydiver1118/semipulse-sentinel --limit 3
```

Inspect tracked files, action logs, report JSON/HTML, installed skill, and GitHub configuration for secrets, credentials, personal brokerage data, unsupported claims, or unexpected files. Map every original requirement and every design acceptance item to concrete evidence in `docs/completion-audit.md`.

- [ ] **Step 6: Commit and push the final audit**

```powershell
git add README.md docs/operations.md docs/completion-audit.md
git commit -m "chore: complete SemiPulse Sentinel verification"
git push origin main
```

Expected: clean working tree, final workflow success, HTTP 200 live page, exact 6 PM Eastern schedule, and installed future-chat agent.
