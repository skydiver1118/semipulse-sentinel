from decimal import Decimal
from pathlib import Path

import pytest

from semipulse_sentinel.watchlist import (
    WatchlistEntry,
    WatchlistError,
    load_watchlist,
)


def _write_watchlist(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "watchlist.csv"
    path.write_text(
        "Symbol,Last,Chg%,Color,source_status\n" + body,
        encoding="utf-8",
    )
    return path


def test_recovered_watchlist_has_expected_identity(tmp_path: Path) -> None:
    path = _write_watchlist(tmp_path, "NVDA,194.44,-1.59,,recovered_inference\n")

    assert load_watchlist(path) == (
        WatchlistEntry(
            symbol="NVDA",
            source_status="recovered_inference",
            source_last=Decimal("194.44"),
            source_change_pct=Decimal("-1.59"),
        ),
    )


@pytest.mark.parametrize(
    "symbol",
    ["", "NV DA", "=NVDA", "+NVDA", "-NVDA", "@NVDA", "../NVDA"],
)
def test_watchlist_rejects_unsafe_symbols(tmp_path: Path, symbol: str) -> None:
    path = _write_watchlist(
        tmp_path,
        f"{symbol},1,0,,recovered_inference\n",
    )

    with pytest.raises(WatchlistError):
        load_watchlist(path)


def test_watchlist_normalizes_symbols_and_preserves_file_order(tmp_path: Path) -> None:
    path = _write_watchlist(
        tmp_path,
        "nvda,194.44,-1.59,,recovered_inference\n"
        "^vix,,,,optional_benchmark\n",
    )

    entries = load_watchlist(path)

    assert [entry.symbol for entry in entries] == ["NVDA", "^VIX"]
    assert entries[1].source_last is None
    assert entries[1].source_change_pct is None


def test_watchlist_rejects_duplicates_after_normalization(tmp_path: Path) -> None:
    path = _write_watchlist(
        tmp_path,
        "NVDA,1,0,,recovered_inference\n"
        "nvda,2,1,,recovered_inference\n",
    )

    with pytest.raises(WatchlistError, match="row 3"):
        load_watchlist(path)


@pytest.mark.parametrize(
    "header",
    [
        "Symbol,Last,Chg%,Color\n",
        "Symbol,Last,Chg%,Color,source_status,Notes\n",
        "symbol,Last,Chg%,Color,source_status\n",
    ],
)
def test_watchlist_requires_exact_headers(
    tmp_path: Path,
    header: str,
) -> None:
    path = tmp_path / "watchlist.csv"
    path.write_text(header, encoding="utf-8")

    with pytest.raises(WatchlistError, match="expected headers"):
        load_watchlist(path)


def test_watchlist_rejects_invalid_decimal_provenance(tmp_path: Path) -> None:
    path = _write_watchlist(
        tmp_path,
        "NVDA,not-a-number,-1.59,,recovered_inference\n",
    )

    with pytest.raises(WatchlistError, match="decimal"):
        load_watchlist(path)


@pytest.mark.parametrize(
    "body",
    [
        "NVDA,1,0\n",
        "NVDA,1,0,,recovered_inference,unexpected\n",
    ],
)
def test_watchlist_rejects_malformed_row_shapes(
    tmp_path: Path,
    body: str,
) -> None:
    path = _write_watchlist(tmp_path, body)

    with pytest.raises(WatchlistError, match="malformed row"):
        load_watchlist(path)


@pytest.mark.parametrize("source_status", ["", "=recovered_inference"])
def test_watchlist_rejects_unsafe_source_status(
    tmp_path: Path,
    source_status: str,
) -> None:
    path = _write_watchlist(tmp_path, f"NVDA,1,0,,{source_status}\n")

    with pytest.raises(WatchlistError, match="source status"):
        load_watchlist(path)


def test_watchlist_rejects_empty_files(tmp_path: Path) -> None:
    path = _write_watchlist(tmp_path, "")

    with pytest.raises(WatchlistError, match="watchlist is empty"):
        load_watchlist(path)


def test_seed_watchlist_matches_all_recovered_rows() -> None:
    path = Path(__file__).parents[2] / "config" / "watchlist.csv"
    entries = load_watchlist(path)

    expected = (
        ("AAOI", "121.2", "-12.81"),
        ("AMAT", "608.2899", "-6.55"),
        ("AMD", "519.5", "-3.95"),
        ("ASML", "1777.9", "-3.53"),
        ("AXTI", "59.6535", "-8.27"),
        ("CBRS", "204.3108", "-7.66"),
        ("DRAM", "61.2", "-7.09"),
        ("IREN", "39.1999", "-9.51"),
        ("LITE", "725.0021", "-9.51"),
        ("LRCX", "355.2", "-9.22"),
        ("MRVL", "246.0547", "-9.56"),
        ("MU", "976.63", "-5.39"),
        ("NVDA", "194.44", "-1.59"),
        ("ONTO", "305", "-13.32"),
        ("SMH", "594.2175", "-4.23"),
        ("SNDK", "1762.0106", "-13.3"),
        ("SOXL", "182.92", "-15.96"),
        ("SOXX", "569.5", "-5.04"),
        ("STX", "824.5231", "-9.91"),
        ("TER", "375.2396", "-12.19"),
        ("TSEM", "217.5", "-11.39"),
        ("TSM", "437.64", "-1.51"),
        ("WDC", "543.3", "-9.2"),
    )
    assert tuple(
        (
            entry.symbol,
            str(entry.source_last),
            str(entry.source_change_pct),
        )
        for entry in entries
    ) == expected
    assert {entry.source_status for entry in entries} == {"recovered_inference"}
