import tomllib
from dataclasses import FrozenInstanceError, is_dataclass
from pathlib import Path

import pytest

from semipulse_sentinel.config import AppConfig
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
from semipulse_sentinel.watchlist import WatchlistEntry


@pytest.mark.parametrize(
    "model_type",
    [
        WatchlistEntry,
        AppConfig,
        QualityReport,
        ChartInsight,
        CompositeInsight,
        ChartArtifact,
        ReportChart,
        BuildMetadata,
        ReportSchedule,
        ReportFreshness,
        CoverageExclusion,
        ReportCoverage,
        ReportSourceStatus,
        ProviderIssue,
        ReportProvenance,
        MethodologyPillar,
        ReportMethodology,
        ReportModel,
    ],
)
def test_shared_models_are_frozen_dataclasses(model_type: type[object]) -> None:
    assert is_dataclass(model_type)
    assert model_type.__dataclass_params__.frozen is True


def test_report_model_is_immutable() -> None:
    assert ReportModel.__dataclass_params__.frozen is True


def test_app_config_has_the_report_contract_defaults() -> None:
    config = AppConfig()

    assert config.required_benchmarks == ("SMH", "SOXX", "QQQ", "SOXL")
    assert config.optional_benchmarks == ("^VIX",)
    assert config.timezone == "America/New_York"
    assert config.chart_count == 8

    with pytest.raises(FrozenInstanceError):
        config.chart_count = 9  # type: ignore[misc]


def test_isolated_build_dependencies_are_exactly_pinned() -> None:
    pyproject_path = Path(__file__).parents[2] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert pyproject["build-system"]["requires"] == [
        "setuptools==83.0.0",
        "wheel==0.47.0",
    ]
