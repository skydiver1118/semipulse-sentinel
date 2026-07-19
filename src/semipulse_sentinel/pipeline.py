"""One-fetch report orchestration and failure-atomic site publication."""

from __future__ import annotations

import hashlib
import shutil
import stat
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from importlib import metadata
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd  # type: ignore[import-untyped]

from semipulse_sentinel.charts import CHART_SPECS, render_charts
from semipulse_sentinel.config import AppConfig
from semipulse_sentinel.contracts import (
    AGENT_NAME,
    AGENT_SLUG,
    REPORT_SCHEMA_VERSION,
    SCHEDULE_CRON,
    SCHEDULE_DESCRIPTION,
    SCHEDULE_TIMEZONE,
)
from semipulse_sentinel.interpret import (
    RULES_VERSION,
    build_composite,
    build_composite_audit,
    interpret_charts,
)
from semipulse_sentinel.metrics import METRICS_VERSION, MetricBundle, compute_metrics
from semipulse_sentinel.models import (
    BuildMetadata,
    ChartArtifact,
    ChartInsight,
    CompositeInsight,
    CoverageExclusion,
    MethodologyPillar,
    ProviderIssue,
    QualityReport,
    ReportChart,
    ReportCoverage,
    ReportFreshness,
    ReportMethodology,
    ReportModel,
    ReportProvenance,
    ReportSchedule,
    ReportSourceStatus,
)
from semipulse_sentinel.providers.base import MarketData, MarketDataProvider
from semipulse_sentinel.quality import PublicationBlocked, validate_market_data
from semipulse_sentinel.report import (
    RISK_WARNING,
    _site_tree,
    render_report,
    safe_chart_uri,
    validate_site,
)
from semipulse_sentinel.version import __version__
from semipulse_sentinel.watchlist import WatchlistEntry, load_watchlist

Clock = Callable[[], datetime]
ChartRenderer = Callable[
    [MetricBundle, Sequence[ChartInsight], Path], tuple[ChartArtifact, ...]
]
RenameOperation = Callable[[Path, Path], None]

_LIMITATIONS = (
    "The missing uploaded file could not be proven to be the recovered watchlist; "
    "all rows remain labeled recovered_inference until confirmed or replaced.",
    "The default yfinance adapter is unofficial, intended for personal research, "
    "and is not a licensed execution-quality feed.",
    "Daily bars cannot describe intraday reversals after the latest completed "
    "provider bar.",
    "Technical indicators are backward-looking and can whipsaw; unsupported "
    "observations are excluded rather than imputed.",
    "Public output must not contain secrets, brokerage data, personal positions, "
    "or personalized sizing.",
)


class BuildFailed(RuntimeError):
    """Raised when a staged build or atomic publication cannot complete."""


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Typed result for a successfully published report."""

    output_dir: Path
    output_hash: str
    as_of: date
    quality: QualityReport
    charts: tuple[ReportChart, ...]
    warnings: tuple[str, ...]

    @property
    def artifacts(self) -> tuple[ReportChart, ...]:
        """Compatibility name for the eight paired chart artifacts."""

        return self.charts


def _now(clock: Clock) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value


def _requested_symbols(
    watchlist: Sequence[WatchlistEntry], config: AppConfig
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                *(entry.symbol for entry in watchlist),
                *config.required_benchmarks,
                *config.optional_benchmarks,
            )
        )
    )


def _filtered_prices(
    data: MarketData,
    quality: QualityReport,
    config: AppConfig,
) -> pd.DataFrame:
    retained = {
        *quality.covered_symbols,
        *config.required_benchmarks,
        *config.optional_benchmarks,
    }
    symbols = data.prices["symbol"].astype(str).str.strip().str.upper()
    filtered = data.prices.loc[symbols.isin(retained)].copy()
    filtered["symbol"] = symbols.loc[filtered.index]
    return filtered.reset_index(drop=True)


def _canonical_sessions(prices: pd.DataFrame, as_of: date) -> tuple[date, ...]:
    dates = pd.to_datetime(
        prices.loc[prices["symbol"].eq("SMH"), "date"], errors="coerce"
    )
    if isinstance(dates.dtype, pd.DatetimeTZDtype):
        dates = dates.dt.tz_localize(None)
    sessions = tuple(
        value.date()
        for value in sorted(dates.dropna().drop_duplicates())
        if value.date() <= as_of
    )
    if not sessions or sessions[-1] != as_of:
        raise PublicationBlocked("current SMH session is unavailable")
    return sessions[-5:]


def _previous_weekday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _expected_market_session(value: datetime, timezone: str) -> date:
    local = value.astimezone(ZoneInfo(timezone))
    if local.weekday() >= 5:
        candidate = local.date()
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate
    if local.time().replace(tzinfo=None) < time(16, 15):
        return _previous_weekday(local.date())
    return local.date()


def _freshness(
    quality: QualityReport,
    data: MarketData,
    evaluated: datetime,
    expected_session: date,
) -> ReportFreshness:
    age = quality.calendar_age_days or 0
    lag = quality.expected_session_lag or 0
    if lag == 0 and age <= 3:
        state = "current"
    elif lag <= 1 and age <= 3:
        state = "delayed"
    else:
        state = "stale"
    return ReportFreshness(
        state=state,
        expected_market_session=expected_session,
        latest_market_session=quality.as_of.date(),
        fetched_at=data.fetched_at,
        evaluated_at=quality.evaluated_at or evaluated,
        calendar_age_days=age,
        expected_session_lag=lag,
    )


def _exclusions(
    watchlist: Sequence[WatchlistEntry], quality: QualityReport, data: MarketData
) -> tuple[CoverageExclusion, ...]:
    missing = set(quality.missing_symbols)
    stale = set(quality.stale_symbols)
    issues = {error.symbol: error.code for error in data.errors}
    symbols = data.prices["symbol"].astype(str).str.strip().str.upper()
    counts = (
        data.prices.assign(_symbol=symbols)
        .groupby("_symbol", sort=False)["date"]
        .nunique()
    )
    output: list[CoverageExclusion] = []
    for entry in watchlist:
        if entry.symbol not in missing:
            continue
        if entry.symbol in stale:
            code = "stale"
            reason = "latest adjusted-close observation is stale"
        elif int(counts.get(entry.symbol, 0)) == 0:
            code = "absent"
            provider_note = (
                f"; provider status {issues[entry.symbol]}"
                if entry.symbol in issues
                else ""
            )
            reason = f"no normalized observations were returned{provider_note}"
        else:
            code = "insufficient_history"
            reason = "fewer than 64 eligible daily observations were returned"
        output.append(CoverageExclusion(entry.symbol, code, reason))
    return tuple(output)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report_charts(
    artifacts: Sequence[ChartArtifact],
    insights: Sequence[ChartInsight],
    chart_root: Path,
) -> tuple[ReportChart, ...]:
    expected_ids = tuple(f"chart-{number}" for number in range(1, 9))
    if tuple(item.chart_id for item in artifacts) != expected_ids:
        raise BuildFailed(
            "chart renderer did not return exactly eight ordered artifacts"
        )
    if tuple(item.chart_id for item in insights) != expected_ids:
        raise BuildFailed("interpretation contract did not return exactly eight items")
    resolved_root = chart_root.resolve(strict=True)
    charts: list[ReportChart] = []
    for spec, artifact, insight in zip(CHART_SPECS, artifacts, insights, strict=True):
        path = artifact.path
        if path != chart_root / spec.filename:
            raise BuildFailed(
                f"chart renderer must use the stable filename {spec.filename}"
            )
        try:
            resolved = path.resolve(strict=True)
        except OSError as error:
            raise BuildFailed("chart renderer returned a missing artifact") from error
        if path.is_symlink() or resolved.parent != resolved_root:
            raise BuildFailed("chart renderer returned an unsafe artifact path")
        image = safe_chart_uri(f"charts/{path.name}")
        charts.append(
            ReportChart(
                chart_id=artifact.chart_id,
                title=spec.title,
                image=image,
                sha256=_hash(path),
                byte_length=path.stat().st_size,
                alt_text=artifact.alt_text,
                has_non_color_encoding=artifact.has_non_color_encoding,
                insight=insight,
            )
        )
    return tuple(charts)


def _watchlist_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provider_version(provider: str) -> str:
    distribution = "yfinance" if provider.casefold() == "yfinance" else provider
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return "not-reported"


def _model(
    *,
    started_at: datetime,
    completed_at: datetime,
    data: MarketData,
    watchlist: Sequence[WatchlistEntry],
    watchlist_sha256: str,
    quality: QualityReport,
    metrics: MetricBundle,
    composite: CompositeInsight,
    charts: tuple[ReportChart, ...],
    exclusions: tuple[CoverageExclusion, ...],
) -> ReportModel:
    audit = tuple(reversed(composite.audit))
    methodology_pillars = tuple(
        MethodologyPillar(item.name, item.weight, item.expected_inputs)
        for item in composite.pillars
    )
    return ReportModel(
        schema_version=REPORT_SCHEMA_VERSION,
        agent_name=AGENT_NAME,
        agent_slug=AGENT_SLUG,
        title="SemiPulse Sentinel — Semiconductor Market Regime Report",
        timezone=SCHEDULE_TIMEZONE,
        market_as_of=metrics.as_of,
        build=BuildMetadata(
            version=__version__, started_at=started_at, completed_at=completed_at
        ),
        schedule=ReportSchedule(
            cron=SCHEDULE_CRON,
            timezone=SCHEDULE_TIMEZONE,
            description=SCHEDULE_DESCRIPTION,
        ),
        freshness=_freshness(
            quality,
            data,
            completed_at,
            _expected_market_session(started_at, SCHEDULE_TIMEZONE),
        ),
        coverage=ReportCoverage(
            covered_count=quality.covered_count,
            watchlist_count=quality.watchlist_count,
            coverage_ratio=quality.coverage_ratio,
            covered_symbols=quality.covered_symbols,
            missing_required=quality.missing_required,
            missing_optional=quality.missing_optional,
            warnings=quality.warnings,
        ),
        provenance=ReportProvenance(
            provider=data.provider,
            provider_version=_provider_version(data.provider),
            watchlist_sha256=watchlist_sha256,
            upload_identity_verified=False,
            source_statuses=tuple(
                ReportSourceStatus(entry.symbol, entry.source_status)
                for entry in watchlist
            ),
            provider_issues=tuple(
                ProviderIssue(error.symbol, error.code) for error in data.errors
            ),
            statement=(
                f"Daily adjusted OHLCV observations were fetched from {data.provider}. "
                "The watchlist is a recovered inference because the original upload "
                "identity could not be verified; recovered Last and Chg% fields are "
                "never used as market data."
            ),
        ),
        methodology=ReportMethodology(
            metrics_version=METRICS_VERSION,
            rules_version=RULES_VERSION,
            report_schema_version=REPORT_SCHEMA_VERSION,
            pillars=methodology_pillars,
            chart_count=8,
            adjusted_close_only=True,
        ),
        executive_summary=composite,
        audit=audit,
        charts=charts,
        exclusions=exclusions,
        limitations=_LIMITATIONS,
        risk_warning=RISK_WARNING,
    )


def tree_output_hash(path: Path) -> str:
    """Hash sorted directory and relative-name/content entries for a site tree."""

    _root, directories, files = _site_tree(path)
    digest = hashlib.sha256()
    for relative in sorted(directories):
        digest.update(b"directory\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\n")
    for relative in sorted(files):
        item = path / Path(*relative.split("/"))
        try:
            content_hash = _hash(item)
        except OSError as error:
            raise PublicationBlocked("cannot hash an unreadable site asset") from error
        digest.update(b"file\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _destination(path: Path) -> tuple[Path, Path]:
    raw = Path(path)
    if not raw.name or raw.name in {".", ".."} or ".." in raw.parts:
        raise ValueError("output destination must be a named directory without '..'")
    if _is_link_or_reparse(raw):
        raise ValueError("output destination cannot be a symlink or reparse point")
    absolute_parent = raw.absolute().parent
    current = Path(absolute_parent.anchor)
    for part in absolute_parent.parts[1:]:
        current /= part
        if _is_link_or_reparse(current):
            raise ValueError(
                "output parent chain cannot contain a symlink or reparse point"
            )
    parent = raw.parent.resolve(strict=False)
    if _is_link_or_reparse(raw.parent):
        raise ValueError("output parent cannot be a symlink or reparse point")
    parent.mkdir(parents=True, exist_ok=True)
    parent = parent.resolve(strict=True)
    destination = parent / raw.name
    if destination == Path(destination.anchor):
        raise ValueError("output destination cannot be a filesystem root")
    if _is_link_or_reparse(destination):
        raise ValueError("output destination cannot be a symlink or reparse point")
    if destination.exists() and not destination.is_dir():
        raise ValueError("output destination must be a directory")
    if destination.exists():
        try:
            validate_site(destination)
        except PublicationBlocked as error:
            raise ValueError(
                "existing output destination is not a recognized SemiPulse site"
            ) from error
    return destination, parent


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise ValueError("output path metadata cannot be inspected") from error
    attributes = getattr(details, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def _verified_sibling(candidate: Path, parent: Path, prefix: str) -> bool:
    return candidate.parent == parent and candidate.name.startswith(prefix)


def _cleanup(candidate: Path, parent: Path, prefix: str) -> None:
    if _is_link_or_reparse(candidate):
        raise BuildFailed("refused to clean a symlink or reparse point")
    if not candidate.exists():
        return
    if not _verified_sibling(candidate, parent, prefix):
        raise BuildFailed("refused to clean an unverified staging path")
    shutil.rmtree(candidate)


def _rename(source: Path, destination: Path) -> None:
    source.rename(destination)


def _publish(
    stage: Path,
    destination: Path,
    parent: Path,
    backup: Path,
    rename_operation: RenameOperation,
) -> tuple[str, ...]:
    warnings: list[str] = []
    try:
        unsafe_destination = _is_link_or_reparse(destination)
    except ValueError as error:
        raise BuildFailed("could not inspect the publish destination") from error
    if unsafe_destination:
        raise BuildFailed(
            "publish destination became a symlink or reparse point"
        )
    had_destination = destination.exists()
    if had_destination:
        if not destination.is_dir():
            raise BuildFailed("publish destination became a non-directory")
        try:
            validate_site(destination)
        except PublicationBlocked as error:
            raise BuildFailed(
                "publish destination is not a recognized SemiPulse site"
            ) from error
        try:
            rename_operation(destination, backup)
        except OSError as error:
            raise BuildFailed(
                "could not move the prior site into a safe backup"
            ) from error
    try:
        rename_operation(stage, destination)
    except OSError as error:
        if had_destination and backup.exists():
            try:
                rename_operation(backup, destination)
            except OSError as restore_error:
                raise BuildFailed(
                    "new-site rename failed and the prior backup could not be restored"
                ) from restore_error
        raise BuildFailed("new-site rename failed; prior site was preserved") from error
    if had_destination and backup.exists():
        try:
            _cleanup(backup, parent, f".{destination.name}.backup-")
        except (BuildFailed, OSError):
            warnings.append("prior site backup cleanup failed and was left in place")
    return tuple(warnings)


def build_report(
    provider: MarketDataProvider,
    watchlist_path: Path,
    output_path: Path,
    clock: Clock,
    *,
    config: AppConfig | None = None,
    chart_renderer: ChartRenderer = render_charts,
    rename_operation: RenameOperation | None = None,
) -> BuildResult:
    """Build, validate, and atomically publish one complete static report."""

    settings = config or AppConfig()
    if settings.chart_count != 8 or settings.timezone != SCHEDULE_TIMEZONE:
        raise ValueError("report configuration must use eight charts and New York time")
    started_at = _now(clock)
    destination, parent = _destination(output_path)
    watchlist_file = Path(watchlist_path)
    watchlist = load_watchlist(watchlist_file)
    watchlist_sha256 = _watchlist_hash(watchlist_file)
    requested = _requested_symbols(watchlist, settings)
    local_date = started_at.astimezone(ZoneInfo(settings.timezone)).date()
    data = provider.fetch(
        requested,
        start=local_date - timedelta(days=730),
        end=local_date + timedelta(days=1),
    )
    quality = validate_market_data(data, settings, watchlist, started_at)
    prices = _filtered_prices(data, quality, settings)
    sessions = _canonical_sessions(prices, quality.as_of.date())
    snapshots = tuple(
        compute_metrics(prices, requested[: len(watchlist)], session)
        for session in sessions
    )
    current = snapshots[-1]
    audit = build_composite_audit(snapshots, current=current)
    insights = interpret_charts(current, quality)
    composite = build_composite(insights, current, quality, audit=audit)
    exclusions = _exclusions(watchlist, quality, data)

    token = uuid4().hex
    stage_prefix = f".{destination.name}.tmp-"
    backup_prefix = f".{destination.name}.backup-"
    stage = parent / f"{stage_prefix}{token}"
    backup = parent / f"{backup_prefix}{token}"
    stage.mkdir()
    try:
        chart_root = stage / "charts"
        artifacts = chart_renderer(current, insights, chart_root)
        report_charts = _report_charts(artifacts, insights, chart_root)
        completed_at = _now(clock)
        model = _model(
            started_at=started_at,
            completed_at=completed_at,
            data=data,
            watchlist=watchlist,
            watchlist_sha256=watchlist_sha256,
            quality=quality,
            metrics=current,
            composite=composite,
            charts=report_charts,
            exclusions=exclusions,
        )
        render_report(model, stage)
        validate_site(stage)
        output_hash = tree_output_hash(stage)
    except (BuildFailed, PublicationBlocked):
        _cleanup(stage, parent, stage_prefix)
        raise
    except (KeyboardInterrupt, SystemExit):
        _cleanup(stage, parent, stage_prefix)
        raise
    except Exception as error:
        _cleanup(stage, parent, stage_prefix)
        raise BuildFailed("staged report build failed") from error

    try:
        warnings = _publish(
            stage,
            destination,
            parent,
            backup,
            rename_operation or _rename,
        )
    except Exception:
        if stage.exists():
            _cleanup(stage, parent, stage_prefix)
        raise
    return BuildResult(
        output_dir=destination,
        output_hash=output_hash,
        as_of=current.as_of,
        quality=quality,
        charts=report_charts,
        warnings=warnings,
    )
