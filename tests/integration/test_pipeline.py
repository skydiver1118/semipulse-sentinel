"""End-to-end, adversarial validation, and atomic publication tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import semipulse_sentinel.pipeline as pipeline
from semipulse_sentinel.charts import CHART_SPECS
from semipulse_sentinel.cli import main
from semipulse_sentinel.metrics import MetricBundle
from semipulse_sentinel.models import ChartArtifact, ChartInsight
from semipulse_sentinel.pipeline import (
    BuildFailed,
    BuildResult,
    build_report,
    tree_output_hash,
)
from semipulse_sentinel.providers.base import MarketData
from semipulse_sentinel.quality import PublicationBlocked
from semipulse_sentinel.report import canonical_json, validate_site
from semipulse_sentinel.watchlist import load_watchlist
from tests.fixtures import make_market_data

WATCHLIST = Path(__file__).parents[2] / "config" / "watchlist.csv"


class FakeProvider:
    def __init__(self, data: MarketData) -> None:
        self.data = data
        self.calls: list[tuple[tuple[str, ...], date, date]] = []

    def fetch(self, symbols: Sequence[str], start: date, end: date) -> MarketData:
        self.calls.append((tuple(symbols), start, end))
        return self.data


def _data() -> MarketData:
    return make_market_data(load_watchlist(WATCHLIST), periods=260)


def _stub_charts(
    _metrics: MetricBundle,
    insights: Sequence[ChartInsight],
    output_dir: Path,
) -> tuple[ChartArtifact, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[ChartArtifact] = []
    for number, (spec, insight) in enumerate(
        zip(CHART_SPECS, insights, strict=True), start=1
    ):
        path = output_dir / spec.filename
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" role="img" '
            f'aria-labelledby="t{number} d{number}">'
            f'<title id="t{number}">Chart</title>'
            f'<desc id="d{number}">Accessible chart {number}</desc></svg>',
            encoding="utf-8",
        )
        artifacts.append(
            ChartArtifact(
                chart_id=insight.chart_id,
                path=path,
                alt_text=f"Accessible chart {number}",
                has_non_color_encoding=True,
            )
        )
    return tuple(artifacts)


def _write_report_and_embedded_payload(
    site: Path, report: dict[str, object]
) -> None:
    serialized = canonical_json(report)
    (site / "report.json").write_text(serialized, encoding="utf-8")
    payload = (
        serialized.rstrip("\n")
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    index = site / "index.html"
    html = index.read_text(encoding="utf-8")
    marker = '<script id="report-data" type="application/json">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    index.write_text(html[:start] + payload + html[end:], encoding="utf-8")


def _refresh_chart_manifest(site: Path, index: int = 0) -> None:
    report = json.loads((site / "report.json").read_text(encoding="utf-8"))
    chart = report["charts"][index]
    data = (site / chart["image"]).read_bytes()
    chart["sha256"] = hashlib.sha256(data).hexdigest()
    chart["byte_length"] = len(data)
    _write_report_and_embedded_payload(site, report)


def _apply_parser_failure(site: Path, failure: str) -> None:
    if failure == "oversized_json_integer":
        (site / "report.json").write_text(
            '{"value":' + "9" * 5_000 + "}\n", encoding="utf-8"
        )
        return
    if failure == "deeply_nested_json":
        (site / "report.json").write_text(
            "[" * 2_000 + "0" + "]" * 2_000 + "\n", encoding="utf-8"
        )
        return
    if failure == "canonicalization_recursion":
        report = json.loads((site / "report.json").read_text(encoding="utf-8"))
        nested: object = 0
        for _ in range(500):
            nested = [nested]
        report["title"] = nested
        (site / "report.json").write_text(
            json.dumps(
                report,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return
    report = json.loads((site / "report.json").read_text(encoding="utf-8"))
    asset = site / report["charts"][0]["image"]
    encoding = "utf-32" if failure == "unsupported_svg_encoding" else "bogus"
    asset.write_bytes(
        f'<?xml version="1.0" encoding="{encoding}"?>\n'.encode()
        + asset.read_bytes()
    )
    _refresh_chart_manifest(site)


def _make_directory_junction(link: Path, target: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("directory junctions are Windows-specific")
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"directory junction creation unavailable: {result.stderr}")
    details = link.lstat()
    assert (
        details.st_file_attributes
        & pipeline.stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _build(
    root: Path,
    *,
    data: MarketData | None = None,
    watchlist: Path = WATCHLIST,
    destination_name: str = "site",
    renderer: Callable[
        [MetricBundle, Sequence[ChartInsight], Path], tuple[ChartArtifact, ...]
    ] = _stub_charts,
    rename_operation: Callable[[Path, Path], None] | None = None,
) -> tuple[BuildResult, FakeProvider, Path]:
    current = data or _data()
    provider = FakeProvider(current)
    destination = root / destination_name
    result = build_report(
        provider,
        watchlist,
        destination,
        lambda: current.fetched_at,
        chart_renderer=renderer,
        rename_operation=rename_operation,
    )
    return result, provider, destination


@pytest.fixture
def built_site(tmp_path: Path) -> Path:
    return _build(tmp_path)[2]


def test_complete_site_uses_one_model_for_summary_and_eight_cards(
    tmp_path: Path,
) -> None:
    result, provider, destination = _build(tmp_path)

    html = (destination / "index.html").read_text(encoding="utf-8")
    raw_report = (destination / "report.json").read_text(encoding="utf-8")
    report = json.loads(raw_report)
    golden = json.loads(
        (Path(__file__).parents[1] / "golden" / "report-structure.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(provider.calls) == 1
    assert html.index('id="executive-summary"') < html.index('id="chart-1"')
    assert html.count('class="chart-card"') == 8
    assert html.count('class="chart-interpretation"') == 8
    assert len(report["charts"]) == 8
    assert all(chart["purpose"].strip() for chart in report["charts"])
    assert html.count("What this chart measures") == 8
    assert html.count("What it means now") == 8
    assert html.count("How it may inform trading decisions") == 8
    assert "Trading decision summary" in html
    posture_start = html.index('<p class="posture">')
    posture_end = html.index("</p>", posture_start)
    assert (
        html[posture_start:posture_end].count("Current research posture:")
        == 1
    )
    assert [item["chart_id"] for item in report["charts"]] == [
        f"chart-{number}" for number in range(1, 9)
    ]
    assert sorted(report) == golden["top_level_keys"]
    assert [item["chart_id"] for item in report["charts"]] == golden["chart_ids"]
    assert len(report["audit"]) == 5
    assert [item["as_of"] for item in report["audit"]] == sorted(
        (item["as_of"] for item in report["audit"]), reverse=True
    )
    assert report["audit"][0]["as_of"] == report["market_as_of"]
    assert report["audit"][0]["pillars"] == report["executive_summary"]["pillars"]
    assert report["provenance"]["upload_identity_verified"] is False
    assert report["provenance"]["provider_version"]
    assert report["freshness"]["latest_market_session"] == report["market_as_of"]
    assert "source_last" not in raw_report
    assert "source_change_pct" not in raw_report
    assert result.output_hash == tree_output_hash(destination)
    assert validate_site(destination).valid is True


def test_one_fetch_filters_exclusions_but_retains_full_watchlist_order(
    tmp_path: Path,
) -> None:
    original = _data()
    latest = pd.to_datetime(original.prices["date"]).max()
    prices = original.prices.copy()
    prices = prices.loc[~prices["symbol"].eq("AAOI")]
    amat = prices.loc[prices["symbol"].eq("AMAT")].tail(10)
    prices = pd.concat(
        [prices.loc[~prices["symbol"].eq("AMAT")], amat], ignore_index=True
    )
    prices = prices.loc[
        ~(prices["symbol"].eq("AMD") & pd.to_datetime(prices["date"]).eq(latest))
    ]
    partial = replace(original, prices=prices.reset_index(drop=True))

    def assert_filtered(
        metrics: MetricBundle,
        insights: Sequence[ChartInsight],
        output_dir: Path,
    ) -> tuple[ChartArtifact, ...]:
        assert set(metrics.momentum["symbol"]) == {
            entry.symbol for entry in load_watchlist(WATCHLIST)
        }
        removed = metrics.trend_heatmap["symbol"].isin({"AAOI", "AMAT", "AMD"})
        assert not metrics.trend_heatmap.loc[removed, "supported"].any()
        return _stub_charts(metrics, insights, output_dir)

    _, provider, destination = _build(
        tmp_path, data=partial, renderer=assert_filtered
    )
    report = json.loads((destination / "report.json").read_text(encoding="utf-8"))
    codes = {
        item["symbol"]: item["code"] for item in report["coverage"]["exclusions"]
    }
    assert codes == {
        "AAOI": "absent",
        "AMAT": "insufficient_history",
        "AMD": "stale",
    }
    entries = tuple(entry.symbol for entry in load_watchlist(WATCHLIST))
    assert len(provider.calls) == 1
    assert provider.calls[0][0][: len(entries)] == entries
    assert provider.calls[0][0][-2:] == ("QQQ", "^VIX")


def test_fixed_inputs_produce_the_same_tree_hash(tmp_path: Path) -> None:
    data = _data()
    first = _build(tmp_path, data=data, destination_name="first")[0]
    second = _build(tmp_path, data=data, destination_name="second")[0]

    assert first.output_hash == second.output_hash
    assert tree_output_hash(first.output_dir) == tree_output_hash(second.output_dir)


def test_real_chart_renderer_builds_a_valid_complete_site(tmp_path: Path) -> None:
    data = _data()
    destination = tmp_path / "real-site"

    result = build_report(
        FakeProvider(data), WATCHLIST, destination, lambda: data.fetched_at
    )

    assert len(result.charts) == 8
    assert validate_site(destination).valid is True
    assert all(
        (destination / item.image).stat().st_size > 1_000
        for item in result.charts
    )


@pytest.mark.parametrize(
    "tamper",
    ["hash", "extra_svg", "traversal", "embedded_json", "broken_link", "remote_css"],
)
def test_validator_rejects_asset_and_representation_tampering(
    built_site: Path, tamper: str
) -> None:
    report_path = built_site / "report.json"
    index_path = built_site / "index.html"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if tamper == "hash":
        (built_site / report["charts"][0]["image"]).write_text(
            "<svg/>", encoding="utf-8"
        )
    elif tamper == "extra_svg":
        (built_site / "charts" / "extra.svg").write_text(
            "<svg/>", encoding="utf-8"
        )
    elif tamper == "traversal":
        report["charts"][0]["image"] = "../outside.svg"
        report_path.write_text(canonical_json(report), encoding="utf-8")
    elif tamper == "embedded_json":
        html = index_path.read_text(encoding="utf-8")
        html = html.replace(
            '"schema_version":"semipulse-report-v1"',
            '"schema_version":"tampered"',
            1,
        )
        index_path.write_text(html, encoding="utf-8")
    elif tamper == "broken_link":
        html = index_path.read_text(encoding="utf-8")
        html = html.replace(report["charts"][0]["image"], "charts/missing.svg", 1)
        index_path.write_text(html, encoding="utf-8")
    else:
        with (built_site / "static" / "report.css").open(
            "a", encoding="utf-8"
        ) as handle:
            handle.write('\n@import "https://example.invalid/x.css";\n')

    with pytest.raises(PublicationBlocked):
        validate_site(built_site)


@pytest.mark.parametrize(
    "payload",
    [
        '<style>@import url("//evil.invalid/pixel");</style>',
        '<style>.x{fill:url(https://evil.invalid/paint)}</style>',
        '<g style="background-image:url(//evil.invalid/pixel)"></g>',
        '<g xml:base="https://evil.invalid/"></g>',
        '<set attributeName="href" to="https://evil.invalid/pixel"></set>',
        (
            '<animate attributeName="href" '
            'values="#local;https://evil.invalid/pixel"></animate>'
        ),
    ],
)
def test_validator_rejects_external_svg_css_with_updated_manifest(
    built_site: Path, payload: str
) -> None:
    report = json.loads((built_site / "report.json").read_text(encoding="utf-8"))
    asset = built_site / report["charts"][0]["image"]
    svg = asset.read_text(encoding="utf-8")
    asset.write_text(svg.replace("</svg>", f"{payload}</svg>"), encoding="utf-8")
    _refresh_chart_manifest(built_site)

    with pytest.raises(PublicationBlocked):
        validate_site(built_site)


@pytest.mark.parametrize(
    "declaration",
    [
        '<!DOCTYPE svg SYSTEM "https://evil.invalid/unused.dtd">',
        (
            '<!DOCTYPE svg [<!ENTITY unused SYSTEM '
            '"https://evil.invalid/unused.ent">]>'
        ),
        '<?xml-stylesheet type="text/css" href="//evil.invalid/a.css"?>',
    ],
)
def test_validator_rejects_svg_doctype_or_entity_with_updated_manifest(
    built_site: Path, declaration: str
) -> None:
    report = json.loads((built_site / "report.json").read_text(encoding="utf-8"))
    asset = built_site / report["charts"][0]["image"]
    asset.write_text(
        declaration + "\n" + asset.read_text(encoding="utf-8"), encoding="utf-8"
    )
    _refresh_chart_manifest(built_site)

    with pytest.raises(PublicationBlocked):
        validate_site(built_site)


@pytest.mark.parametrize(
    "tamper",
    ["interpretation", "summary", "audit", "inline_style", "hidden_risk"],
)
def test_validator_rejects_visible_html_tampering(
    built_site: Path, tamper: str
) -> None:
    report = json.loads((built_site / "report.json").read_text(encoding="utf-8"))
    index = built_site / "index.html"
    html = index.read_text(encoding="utf-8")
    if tamper == "interpretation":
        original = report["charts"][0]["interpretation"]
        html = html.replace(original, "BUY NOW — guaranteed profit.", 1)
    elif tamper == "summary":
        original = report["executive_summary"]["supports"][0]
        html = html.replace(original, "Guaranteed upside with no downside.", 1)
    elif tamper == "audit":
        record = report["audit"][0]
        row = (
            f'<tr><th scope="row">{record["as_of"]}</th>'
            f'<td>{record["regime"]}</td><td>{record["composite_score"]}</td>'
            f'<td>{record["available_inputs"]}/{record["expected_inputs"]}</td>'
            "</tr>"
        )
        html = html.replace(row, "", 1)
    elif tamper == "inline_style":
        html = html.replace(
            "</head>",
            '<style>@import url("//evil.invalid/pixel");</style>\n</head>',
            1,
        )
    else:
        html = html.replace(
            '<section class="risk-warning"',
            '<section class="risk-warning" hidden',
            1,
        )
    index.write_text(html, encoding="utf-8")

    with pytest.raises(PublicationBlocked):
        validate_site(built_site)


@pytest.mark.parametrize(
    "nested_object",
    [
        "executive_summary",
        "audit_record",
        "summary_pillar",
        "audit_pillar",
        "methodology_pillar",
        "provider_issue",
    ],
)
def test_validator_rejects_unknown_nested_report_keys(
    built_site: Path, nested_object: str
) -> None:
    report = json.loads((built_site / "report.json").read_text(encoding="utf-8"))
    if nested_object == "executive_summary":
        target = report["executive_summary"]
    elif nested_object == "audit_record":
        target = report["audit"][0]
    elif nested_object == "summary_pillar":
        target = report["executive_summary"]["pillars"][0]
        report["audit"][0]["pillars"][0]["unexpected"] = "must be rejected"
    elif nested_object == "audit_pillar":
        target = report["audit"][1]["pillars"][0]
    elif nested_object == "methodology_pillar":
        target = report["methodology"]["pillars"][0]
    else:
        target = {"symbol": "SMH", "code": "test"}
        report["provenance"]["provider_issues"].append(target)
    target["unexpected"] = "must be rejected"
    _write_report_and_embedded_payload(built_site, report)

    with pytest.raises(PublicationBlocked):
        validate_site(built_site)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("purpose", "chart purpose missing"),
        ("interpretation", "chart interpretation missing"),
        ("trading_relevance", "trading relevance missing"),
    ],
)
def test_validator_rejects_blank_chart_explanations(
    built_site: Path, field: str, message: str
) -> None:
    report = json.loads((built_site / "report.json").read_text(encoding="utf-8"))
    report["charts"][0][field] = "   "
    _write_report_and_embedded_payload(built_site, report)

    with pytest.raises(PublicationBlocked, match=message):
        validate_site(built_site)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_required_type",
        "unhashable_covered_symbol",
        "unhashable_source_status",
        "bool_freshness_age",
        "bool_chart_byte_length",
        "extreme_pillar_decimal",
    ],
)
def test_validator_rejects_mistyped_nested_report_values(
    built_site: Path, mutation: str
) -> None:
    report = json.loads((built_site / "report.json").read_text(encoding="utf-8"))
    if mutation == "missing_required_type":
        report["coverage"]["missing_required"] = "SMH"
    elif mutation == "unhashable_covered_symbol":
        report["coverage"]["covered_symbols"][0] = {"symbol": "SMH"}
    elif mutation == "unhashable_source_status":
        report["provenance"]["source_statuses"][0]["symbol"] = ["SMH"]
    elif mutation == "bool_freshness_age":
        report["freshness"]["calendar_age_days"] = True
    elif mutation == "bool_chart_byte_length":
        report["charts"][0]["byte_length"] = True
    else:
        report["executive_summary"]["pillars"][0]["value"] = "1E+999999"
    _write_report_and_embedded_payload(built_site, report)

    with pytest.raises(PublicationBlocked):
        validate_site(built_site)


@pytest.mark.parametrize("relative", ["report.json", "index.html", "static/report.css"])
def test_malformed_text_asset_is_publication_blocked_for_validate_and_doctor(
    built_site: Path,
    relative: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (built_site / relative).write_bytes(b"\xff\xfe\xfa")

    assert main(["validate", "--site", str(built_site), "--json"]) == 3
    assert json.loads(capsys.readouterr().err)["category"] == "publication"
    assert main(
        [
            "doctor",
            "--watchlist",
            str(WATCHLIST),
            "--site",
            str(built_site),
            "--json",
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["site_state"] == "invalid"


@pytest.mark.parametrize(
    "failure",
    [
        "oversized_json_integer",
        "deeply_nested_json",
        "canonicalization_recursion",
        "bogus_svg_encoding",
        "unsupported_svg_encoding",
    ],
)
def test_parser_failures_are_normalized_to_publication_blocked(
    built_site: Path, failure: str
) -> None:
    _apply_parser_failure(built_site, failure)

    with pytest.raises(PublicationBlocked):
        validate_site(built_site)


@pytest.mark.parametrize(
    "failure",
    [
        "oversized_json_integer",
        "deeply_nested_json",
        "canonicalization_recursion",
        "bogus_svg_encoding",
        "unsupported_svg_encoding",
    ],
)
def test_parser_failures_are_classified_by_validate_and_doctor(
    built_site: Path,
    failure: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _apply_parser_failure(built_site, failure)

    assert main(["validate", "--site", str(built_site), "--json"]) == 3
    assert json.loads(capsys.readouterr().err)["category"] == "publication"
    assert main(
        [
            "doctor",
            "--watchlist",
            str(WATCHLIST),
            "--site",
            str(built_site),
            "--json",
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["site_state"] == "invalid"


def test_chart_renderer_must_use_each_stable_direct_artifact_filename(
    tmp_path: Path,
) -> None:
    def wrong_name(
        metrics: MetricBundle,
        insights: Sequence[ChartInsight],
        output_dir: Path,
    ) -> tuple[ChartArtifact, ...]:
        artifacts = list(_stub_charts(metrics, insights, output_dir))
        renamed = output_dir / "arbitrary-name.svg"
        artifacts[0].path.rename(renamed)
        artifacts[0] = replace(artifacts[0], path=renamed)
        return tuple(artifacts)

    with pytest.raises(BuildFailed, match="stable filename"):
        _build(tmp_path, renderer=wrong_name)

    assert not (tmp_path / "site").exists()


def test_validator_rejects_noncontract_chart_filename_with_matching_manifest(
    built_site: Path,
) -> None:
    report_path = built_site / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    chart = report["charts"][0]
    original = chart["image"]
    renamed = "charts/arbitrary-name.svg"
    (built_site / original).rename(built_site / renamed)
    chart["image"] = renamed
    _write_report_and_embedded_payload(built_site, report)
    index = built_site / "index.html"
    html = index.read_text(encoding="utf-8")
    index.write_text(html.replace(original, renamed, 1), encoding="utf-8")

    with pytest.raises(PublicationBlocked, match="stable filename"):
        validate_site(built_site)


def test_validator_rejects_unexpected_empty_directory(built_site: Path) -> None:
    (built_site / "unexpected-empty-directory").mkdir()

    with pytest.raises(PublicationBlocked, match="director"):
        validate_site(built_site)


@pytest.mark.parametrize("entry_kind", ["nested_reparse", "special_entry"])
def test_validator_rejects_mocked_nonregular_tree_entries(
    built_site: Path,
    entry_kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = (
        built_site / "static"
        if entry_kind == "nested_reparse"
        else built_site / "index.html"
    )
    original_lstat = Path.lstat

    def unsafe_lstat(path: Path) -> object:
        if path == target:
            mode = (
                pipeline.stat.S_IFDIR
                if entry_kind == "nested_reparse"
                else pipeline.stat.S_IFIFO
            )
            attributes = (
                pipeline.stat.FILE_ATTRIBUTE_REPARSE_POINT
                if entry_kind == "nested_reparse"
                else 0
            )
            return SimpleNamespace(
                st_mode=mode,
                st_file_attributes=attributes,
            )
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", unsafe_lstat)

    with pytest.raises(PublicationBlocked, match=r"reparse|special"):
        validate_site(built_site)


def test_validator_rejects_nonchart_file_resolving_outside_site(
    built_site: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = built_site / "index.html"
    external = tmp_path / "external-index.html"
    external.write_text("outside", encoding="utf-8")
    original_resolve = Path.resolve

    def escaping_resolve(path: Path, strict: bool = False) -> Path:
        if path == index:
            return external
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", escaping_resolve)

    with pytest.raises(PublicationBlocked, match="escape"):
        validate_site(built_site)


def test_validator_normalizes_entry_resolution_loop(
    built_site: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = built_site / "index.html"
    original_resolve = Path.resolve

    def looping_resolve(path: Path, strict: bool = False) -> Path:
        if path == index:
            raise RuntimeError("simulated filesystem link loop")
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", looping_resolve)

    with pytest.raises(PublicationBlocked, match="resolv"):
        validate_site(built_site)


def test_validator_rejects_real_nested_directory_junction(
    built_site: Path, tmp_path: Path
) -> None:
    static = built_site / "static"
    external = tmp_path / "external-static"
    static.rename(external)
    _make_directory_junction(static, external)

    try:
        with pytest.raises(PublicationBlocked, match="reparse"):
            validate_site(built_site)
    finally:
        static.rmdir()
        external.rename(static)


def test_tree_output_hash_includes_empty_directories(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "artifact.txt").write_text("stable", encoding="utf-8")
    without_empty_directory = tree_output_hash(site)

    (site / "empty").mkdir()

    assert tree_output_hash(site) != without_empty_directory


def test_validator_rejects_symlink_asset(built_site: Path, tmp_path: Path) -> None:
    report = json.loads((built_site / "report.json").read_text(encoding="utf-8"))
    asset = built_site / report["charts"][0]["image"]
    external = tmp_path / "external.svg"
    external.write_bytes(asset.read_bytes())
    asset.unlink()
    try:
        asset.symlink_to(external)
    except OSError:
        pytest.skip("symbolic links are unavailable in this environment")

    with pytest.raises(PublicationBlocked, match="symlink"):
        validate_site(built_site)


def test_xss_like_source_status_is_escaped_and_embedded_json_stays_equal(
    tmp_path: Path,
) -> None:
    malicious = "recovered_</script><script>alert(1)</script>&<>"
    watchlist = tmp_path / "watchlist.csv"
    watchlist.write_text(
        WATCHLIST.read_text(encoding="utf-8").replace(
            "recovered_inference", malicious, 1
        ),
        encoding="utf-8",
    )
    data = make_market_data(load_watchlist(watchlist), periods=260)
    destination = _build(tmp_path, data=data, watchlist=watchlist)[2]
    html = (destination / "index.html").read_text(encoding="utf-8")

    assert html.count("<script") == 1
    assert "</script><script>alert(1)" not in html
    assert "\\u003c/script\\u003e" in html
    assert validate_site(destination).valid is True


def test_failed_charting_preserves_previous_site(tmp_path: Path) -> None:
    data = _data()
    destination = _build(tmp_path, data=data)[2]
    known_good_hash = tree_output_hash(destination)

    def fail(
        _metrics: MetricBundle,
        _insights: Sequence[ChartInsight],
        _output: Path,
    ) -> tuple[ChartArtifact, ...]:
        raise RuntimeError("chart failed")

    with pytest.raises(BuildFailed):
        _build(tmp_path, data=data, renderer=fail)

    assert tree_output_hash(destination) == known_good_hash


def test_first_rename_failure_keeps_prior_site_and_cleans_stage(
    tmp_path: Path,
) -> None:
    destination = _build(tmp_path)[2]
    known_good_hash = tree_output_hash(destination)

    def fail_prior_move(source: Path, target: Path) -> None:
        if source == destination:
            raise OSError("simulated Windows rename denial")
        source.rename(target)

    with pytest.raises(BuildFailed, match="prior site"):
        _build(tmp_path, rename_operation=fail_prior_move)

    assert tree_output_hash(destination) == known_good_hash
    assert not tuple(tmp_path.glob(".site.tmp-*"))
    assert not tuple(tmp_path.glob(".site.backup-*"))


def test_second_rename_failure_restores_prior_site_and_cleans_stage(
    tmp_path: Path,
) -> None:
    destination = _build(tmp_path)[2]
    known_good_hash = tree_output_hash(destination)

    def fail_new_move(source: Path, target: Path) -> None:
        if source.name.startswith(".site.tmp-"):
            raise OSError("simulated Windows stage rename denial")
        source.rename(target)

    with pytest.raises(BuildFailed, match="prior site was preserved"):
        _build(tmp_path, rename_operation=fail_new_move)

    assert tree_output_hash(destination) == known_good_hash
    assert not tuple(tmp_path.glob(".site.tmp-*"))
    assert not tuple(tmp_path.glob(".site.backup-*"))


def test_initial_second_rename_failure_leaves_no_destination(tmp_path: Path) -> None:
    destination = tmp_path / "site"

    def fail_new_move(source: Path, target: Path) -> None:
        if source.name.startswith(".site.tmp-"):
            raise OSError("simulated Windows stage rename denial")
        source.rename(target)

    with pytest.raises(BuildFailed):
        _build(tmp_path, rename_operation=fail_new_move)

    assert not destination.exists()
    assert not tuple(tmp_path.glob(".site.tmp-*"))


def test_failed_restore_leaves_verified_backup_untouched(tmp_path: Path) -> None:
    destination = _build(tmp_path)[2]
    known_good_hash = tree_output_hash(destination)

    def fail_new_and_restore(source: Path, target: Path) -> None:
        if source.name.startswith((".site.tmp-", ".site.backup-")):
            raise OSError("simulated rename and restore denial")
        source.rename(target)

    with pytest.raises(BuildFailed, match="backup could not be restored"):
        _build(tmp_path, rename_operation=fail_new_and_restore)

    backups = tuple(tmp_path.glob(".site.backup-*"))
    assert not destination.exists()
    assert len(backups) == 1
    assert tree_output_hash(backups[0]) == known_good_hash


def test_backup_cleanup_failure_is_a_success_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = _build(tmp_path)[2]
    original = pipeline.shutil.rmtree

    def deny_backup_cleanup(path: Path) -> None:
        if Path(path).name.startswith(".site.backup-"):
            raise PermissionError("simulated cleanup denial")
        original(path)

    monkeypatch.setattr(pipeline.shutil, "rmtree", deny_backup_cleanup)
    result = _build(tmp_path)[0]

    assert result.warnings == (
        "prior site backup cleanup failed and was left in place",
    )
    assert validate_site(destination).valid is True
    assert len(tuple(tmp_path.glob(".site.backup-*"))) == 1


def test_unsafe_output_paths_are_rejected_before_fetch(tmp_path: Path) -> None:
    data = _data()
    provider = FakeProvider(data)
    unsafe = tmp_path / "nested" / ".." / "site"

    with pytest.raises(ValueError, match=r"without '\.\.'"):
        build_report(provider, WATCHLIST, unsafe, lambda: data.fetched_at)

    assert provider.calls == []


@pytest.mark.parametrize("nonempty", [False, True])
def test_unrecognized_existing_destination_is_never_mutated_or_fetched(
    tmp_path: Path, nonempty: bool
) -> None:
    destination = tmp_path / "site"
    destination.mkdir()
    if nonempty:
        (destination / "user-data.txt").write_text("keep me", encoding="utf-8")
    before = {
        item.relative_to(destination).as_posix(): item.read_bytes()
        for item in destination.rglob("*")
        if item.is_file()
    }
    data = _data()
    provider = FakeProvider(data)

    with pytest.raises(ValueError, match="recognized SemiPulse site"):
        build_report(provider, WATCHLIST, destination, lambda: data.fetched_at)

    after = {
        item.relative_to(destination).as_posix(): item.read_bytes()
        for item in destination.rglob("*")
        if item.is_file()
    }
    assert destination.is_dir()
    assert after == before
    assert provider.calls == []


def test_destination_created_during_build_is_not_taken_over(tmp_path: Path) -> None:
    destination = tmp_path / "site"

    def create_unrelated_destination(
        metrics: MetricBundle,
        insights: Sequence[ChartInsight],
        output_dir: Path,
    ) -> tuple[ChartArtifact, ...]:
        destination.mkdir()
        (destination / "user-data.txt").write_text("keep me", encoding="utf-8")
        return _stub_charts(metrics, insights, output_dir)

    with pytest.raises(BuildFailed, match="recognized SemiPulse site"):
        _build(tmp_path, renderer=create_unrelated_destination)

    assert (destination / "user-data.txt").read_text(encoding="utf-8") == "keep me"
    assert not tuple(tmp_path.glob(".site.tmp-*"))
    assert not tuple(tmp_path.glob(".site.backup-*"))


def test_filesystem_root_output_is_rejected() -> None:
    with pytest.raises(ValueError, match="named directory"):
        pipeline._destination(Path(Path.cwd().anchor))


def test_destination_symlink_is_rejected_before_fetch(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    destination = tmp_path / "site"
    try:
        destination.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are unavailable in this environment")
    data = _data()
    provider = FakeProvider(data)

    with pytest.raises(ValueError, match="symlink"):
        build_report(provider, WATCHLIST, destination, lambda: data.fetched_at)

    assert provider.calls == []


def test_dangling_destination_symlink_is_rejected_before_fetch(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "site"
    try:
        destination.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are unavailable in this environment")
    assert destination.is_symlink()
    assert not destination.exists()
    data = _data()
    provider = FakeProvider(data)

    with pytest.raises(ValueError, match=r"symlink|reparse"):
        build_report(provider, WATCHLIST, destination, lambda: data.fetched_at)

    assert provider.calls == []


def test_windows_reparse_attribute_is_rejected_before_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "site"
    original_lstat = Path.lstat

    def reparse_lstat(path: Path) -> object:
        if path == destination:
            return SimpleNamespace(
                st_mode=pipeline.stat.S_IFDIR,
                st_file_attributes=pipeline.stat.FILE_ATTRIBUTE_REPARSE_POINT
            )
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", reparse_lstat)
    data = _data()
    provider = FakeProvider(data)

    with pytest.raises(ValueError, match="reparse"):
        build_report(provider, WATCHLIST, destination, lambda: data.fetched_at)

    assert provider.calls == []


@pytest.mark.parametrize("position", ["destination", "ancestor"])
def test_real_windows_junction_is_rejected_before_fetch(
    tmp_path: Path, position: str
) -> None:
    target = tmp_path / f"real-{position}"
    target.mkdir()
    junction = tmp_path / f"junction-{position}"
    _make_directory_junction(junction, target)
    destination = junction if position == "destination" else junction / "site"
    data = _data()
    provider = FakeProvider(data)

    try:
        with pytest.raises(ValueError, match="reparse"):
            build_report(provider, WATCHLIST, destination, lambda: data.fetched_at)
    finally:
        junction.rmdir()

    assert provider.calls == []
