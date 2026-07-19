"""Immutable models shared by the report pipeline."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from semipulse_sentinel.contracts import SCHEDULE_CRON, SCHEDULE_TIMEZONE


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Market-data coverage and publication-quality findings."""

    as_of: datetime
    covered_symbols: tuple[str, ...]
    missing_symbols: tuple[str, ...]
    stale_symbols: tuple[str, ...]
    missing_required: tuple[str, ...]
    missing_optional: tuple[str, ...]
    covered_count: int
    watchlist_count: int
    coverage_ratio: Decimal
    publishable: bool
    warnings: tuple[str, ...] = ()
    evaluated_at: datetime | None = None
    calendar_age_days: int | None = None
    expected_session_lag: int | None = None


@dataclass(frozen=True, slots=True)
class PillarScore:
    """One fixed-denominator component of the composite regime score."""

    name: str
    value: Decimal
    weight: Decimal
    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    available_inputs: int
    expected_inputs: int


@dataclass(frozen=True, slots=True)
class CompositeAuditRecord:
    """Reproducible non-chart score record for one market session."""

    as_of: date
    metrics_version: str
    rules_version: str
    pillars: tuple[PillarScore, ...]
    composite_score: Decimal
    regime: str
    available_inputs: int
    expected_inputs: int


@dataclass(frozen=True, slots=True)
class ChartInsight:
    """Deterministic interpretation attached to one chart."""

    chart_id: str
    headline: str
    signal: str
    evidence: tuple[str, ...]
    interpretation: str
    trading_relevance: str
    counter_signal: str
    notes: tuple[str, ...]

    def as_text(self) -> str:
        """Return all human-facing fields for safety and rendering checks."""

        return " ".join(
            (
                self.chart_id,
                self.headline,
                self.signal,
                *self.evidence,
                self.interpretation,
                self.trading_relevance,
                self.counter_signal,
                *self.notes,
            )
        )


@dataclass(frozen=True, slots=True)
class CompositeInsight:
    """Cross-chart regime synthesis."""

    score: Decimal
    regime: str
    confidence: str
    what_changed: tuple[str, ...]
    supports: tuple[str, ...]
    challenges: tuple[str, ...]
    change_triggers: tuple[str, ...]
    posture: str
    rules_version: str
    pillars: tuple[PillarScore, ...]
    available_inputs: int
    expected_inputs: int
    audit: tuple[CompositeAuditRecord, ...]

    def as_text(self) -> str:
        """Return deterministic summary prose for validation and rendering."""

        pillar_text = tuple(
            " ".join((*pillar.evidence, *pillar.counter_evidence))
            for pillar in self.pillars
        )
        return " ".join(
            (
                str(self.score),
                self.regime,
                self.confidence,
                self.rules_version,
                *self.what_changed,
                *self.supports,
                *self.challenges,
                *self.change_triggers,
                self.posture,
                *pillar_text,
            )
        )


@dataclass(frozen=True, slots=True)
class ChartArtifact:
    """One rendered and accessibility-checked chart asset."""

    chart_id: str
    path: Path
    alt_text: str
    has_non_color_encoding: bool


@dataclass(frozen=True, slots=True)
class ReportChart:
    """One inseparable interpretation-and-asset report card."""

    chart_id: str
    title: str
    purpose: str
    image: str
    sha256: str
    byte_length: int
    alt_text: str
    has_non_color_encoding: bool
    insight: ChartInsight

    def __post_init__(self) -> None:
        if not self.purpose.strip():
            raise ValueError("chart purpose must not be empty")
        parsed = urlsplit(self.image)
        path = PurePosixPath(self.image)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or "\\" in self.image
            or "%" in self.image
            or ":" in self.image
            or self.image.strip() != self.image
            or path.is_absolute()
            or not self.image.startswith("charts/")
            or path.as_posix() != self.image
            or path.suffix.casefold() != ".svg"
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("chart image must be a safe charts/... POSIX path")
        if self.chart_id != self.insight.chart_id:
            raise ValueError("chart artifact and insight ids must match")
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValueError("chart sha256 must be lowercase hexadecimal")
        if self.byte_length <= 0:
            raise ValueError("chart byte length must be positive")
        if not self.alt_text.strip():
            raise ValueError("chart alt text must not be empty")
        if not self.has_non_color_encoding:
            raise ValueError("report charts require a non-color encoding")


@dataclass(frozen=True, slots=True)
class BuildMetadata:
    """Traceable build timing and package identity."""

    version: str
    started_at: datetime
    completed_at: datetime

    def __post_init__(self) -> None:
        for value in (self.started_at, self.completed_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("build timestamps must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("build completion cannot precede its start")


@dataclass(frozen=True, slots=True)
class ReportSchedule:
    """The exact local-time automation contract."""

    cron: str
    timezone: str
    description: str

    def __post_init__(self) -> None:
        if self.cron != SCHEDULE_CRON or self.timezone != SCHEDULE_TIMEZONE:
            raise ValueError(
                "report schedule must be 18:00 America/New_York on weekdays"
            )


@dataclass(frozen=True, slots=True)
class ReportFreshness:
    """Observed freshness facts, independent from interpretation."""

    state: str
    expected_market_session: date
    latest_market_session: date
    fetched_at: datetime
    evaluated_at: datetime
    calendar_age_days: int
    expected_session_lag: int

    def __post_init__(self) -> None:
        if self.state not in {"current", "delayed", "stale"}:
            raise ValueError("invalid freshness state")
        for value in (self.fetched_at, self.evaluated_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("freshness timestamps must be timezone-aware")
        if self.calendar_age_days < 0 or self.expected_session_lag < 0:
            raise ValueError("freshness age and lag cannot be negative")


@dataclass(frozen=True, slots=True)
class CoverageExclusion:
    """A named watchlist member excluded from aggregate calculations."""

    symbol: str
    code: str
    reason: str

    def __post_init__(self) -> None:
        if self.code not in {"absent", "stale", "insufficient_history"}:
            raise ValueError("invalid coverage exclusion code")
        if not self.symbol or not self.reason:
            raise ValueError("coverage exclusions require a symbol and reason")


@dataclass(frozen=True, slots=True)
class ReportCoverage:
    """Ordered coverage facts printed in both report representations."""

    covered_count: int
    watchlist_count: int
    coverage_ratio: Decimal
    covered_symbols: tuple[str, ...]
    missing_required: tuple[str, ...]
    missing_optional: tuple[str, ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        if not 0 <= self.covered_count <= self.watchlist_count:
            raise ValueError("invalid report coverage counts")
        if self.watchlist_count <= 0:
            raise ValueError("report watchlist count must be positive")
        if len(self.covered_symbols) != self.covered_count:
            raise ValueError("covered symbol count does not match coverage")
        if len(set(self.covered_symbols)) != len(self.covered_symbols):
            raise ValueError("covered report symbols must be unique")
        expected = Decimal(self.covered_count) / Decimal(self.watchlist_count)
        if self.coverage_ratio != expected:
            raise ValueError("coverage ratio does not match counts")


@dataclass(frozen=True, slots=True)
class ReportSourceStatus:
    """One ordered watchlist source-provenance label."""

    symbol: str
    source_status: str

    def __post_init__(self) -> None:
        if not self.symbol or not self.source_status:
            raise ValueError("source status requires a symbol and label")


@dataclass(frozen=True, slots=True)
class ProviderIssue:
    """A sanitized provider issue safe for public disclosure."""

    symbol: str
    code: str

    def __post_init__(self) -> None:
        if not self.symbol or not self.code:
            raise ValueError("provider issue requires a symbol and code")


@dataclass(frozen=True, slots=True)
class ReportProvenance:
    """Public, non-secret source lineage for the current build."""

    provider: str
    provider_version: str
    watchlist_sha256: str
    upload_identity_verified: bool
    source_statuses: tuple[ReportSourceStatus, ...]
    provider_issues: tuple[ProviderIssue, ...]
    statement: str

    def __post_init__(self) -> None:
        if not self.provider or not self.provider_version or not self.statement:
            raise ValueError("report provenance fields must not be empty")
        if len(self.watchlist_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.watchlist_sha256
        ):
            raise ValueError("watchlist sha256 must be lowercase hexadecimal")
        if self.upload_identity_verified:
            raise ValueError("version 1 cannot claim the upload identity was verified")
        symbols = tuple(item.symbol for item in self.source_statuses)
        if not symbols or len(set(symbols)) != len(symbols):
            raise ValueError("source statuses must be nonempty and unique")


@dataclass(frozen=True, slots=True)
class MethodologyPillar:
    """Published composite weight and fixed atom count."""

    name: str
    weight: Decimal
    expected_inputs: int


@dataclass(frozen=True, slots=True)
class ReportMethodology:
    """Structured version identifiers and scoring contract."""

    metrics_version: str
    rules_version: str
    report_schema_version: str
    pillars: tuple[MethodologyPillar, ...]
    chart_count: int
    adjusted_close_only: bool

    def __post_init__(self) -> None:
        if not self.metrics_version or not self.rules_version:
            raise ValueError("methodology versions must not be empty")
        if self.report_schema_version != "semipulse-report-v1":
            raise ValueError("unsupported report schema version")
        if self.chart_count != 8 or not self.adjusted_close_only:
            raise ValueError("methodology must use eight adjusted-close charts")
        if sum((item.weight for item in self.pillars), Decimal("0")) != Decimal(
            "1.00"
        ):
            raise ValueError("methodology pillar weights must sum to one")
        if sum(item.expected_inputs for item in self.pillars) != 30:
            raise ValueError("methodology must disclose 30 fixed inputs")


@dataclass(frozen=True, slots=True)
class ReportModel:
    """The sole immutable source for canonical JSON and rendered HTML."""

    schema_version: str
    agent_name: str
    agent_slug: str
    title: str
    timezone: str
    market_as_of: date
    build: BuildMetadata
    schedule: ReportSchedule
    freshness: ReportFreshness
    coverage: ReportCoverage
    provenance: ReportProvenance
    methodology: ReportMethodology
    executive_summary: CompositeInsight
    audit: tuple[CompositeAuditRecord, ...]
    charts: tuple[ReportChart, ...]
    exclusions: tuple[CoverageExclusion, ...]
    limitations: tuple[str, ...]
    risk_warning: str

    def __post_init__(self) -> None:
        if self.agent_name != "SemiPulse Sentinel" or self.agent_slug != (
            "semipulse-sentinel"
        ):
            raise ValueError("invalid report agent identity")
        if not self.title or not self.limitations or not self.risk_warning:
            raise ValueError("report title, limitations, and risk warning are required")
        expected_ids = tuple(f"chart-{number}" for number in range(1, 9))
        if tuple(chart.chart_id for chart in self.charts) != expected_ids:
            raise ValueError("report must pair exactly chart-1 through chart-8")
        if self.methodology.chart_count != 8:
            raise ValueError("report methodology chart count must be eight")
        if len(self.audit) != 5:
            raise ValueError("report audit must contain the latest five snapshots")
        current = self.audit[0]
        if current.as_of != self.market_as_of:
            raise ValueError("first report audit record must be current")
        if current.composite_score != self.executive_summary.score:
            raise ValueError("current audit score must match executive summary")
        if current.regime != self.executive_summary.regime:
            raise ValueError("current audit regime must match executive summary")
        if current.pillars != self.executive_summary.pillars:
            raise ValueError("current audit pillars must match executive summary")
        dates = tuple(record.as_of for record in self.audit)
        if dates != tuple(sorted(dates, reverse=True)) or len(set(dates)) != len(dates):
            raise ValueError("report audit must be unique and newest-first")
        if self.schema_version != self.methodology.report_schema_version:
            raise ValueError("report schema and methodology must agree")
        if self.timezone != self.schedule.timezone:
            raise ValueError("report timezone and schedule must agree")
        if len(self.provenance.source_statuses) != self.coverage.watchlist_count:
            raise ValueError("source-status count must match the watchlist")
        excluded = {item.symbol for item in self.exclusions}
        if excluded & set(self.coverage.covered_symbols):
            raise ValueError("covered symbols cannot also be excluded")
