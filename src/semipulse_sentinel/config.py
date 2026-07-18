"""Immutable application configuration."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Stable report and benchmark settings."""

    required_benchmarks: tuple[str, ...] = ("SMH", "SOXX", "QQQ", "SOXL")
    optional_benchmarks: tuple[str, ...] = ("^VIX",)
    timezone: str = "America/New_York"
    chart_count: int = 8
