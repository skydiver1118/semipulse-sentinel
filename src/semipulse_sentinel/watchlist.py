"""Strict watchlist loading with recovered-source provenance."""

import csv
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

_REQUIRED_HEADERS = {"Symbol", "Last", "Chg%", "Color", "source_status"}
_SPREADSHEET_FORMULA_PREFIXES = ("=", "+", "-", "@")
_SYMBOL = re.compile(r"^[A-Z^][A-Z0-9.^-]{0,14}$")


class WatchlistError(ValueError):
    """Raised when a watchlist violates the canonical CSV contract."""


@dataclass(frozen=True, slots=True)
class WatchlistEntry:
    """A symbol identity and provenance recovered from the source file."""

    symbol: str
    source_status: str
    source_last: Decimal | None
    source_change_pct: Decimal | None


def _optional_decimal(
    raw_value: str | None,
    *,
    row_number: int,
    column: str,
) -> Decimal | None:
    if raw_value is None or not raw_value.strip():
        return None
    try:
        value = Decimal(raw_value.strip())
    except InvalidOperation as error:
        raise WatchlistError(
            f"invalid decimal in {column} at row {row_number}"
        ) from error
    if not value.is_finite():
        raise WatchlistError(f"invalid decimal in {column} at row {row_number}")
    return value


def load_watchlist(path: Path) -> tuple[WatchlistEntry, ...]:
    """Load a canonical watchlist in file order."""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        if (
            len(fieldnames) != len(_REQUIRED_HEADERS)
            or set(fieldnames) != _REQUIRED_HEADERS
        ):
            raise WatchlistError(f"expected headers {sorted(_REQUIRED_HEADERS)}")

        entries: list[WatchlistEntry] = []
        seen: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise WatchlistError(f"malformed row at row {row_number}")

            raw_symbol = row["Symbol"] or ""
            symbol = raw_symbol.strip().upper()
            if (
                symbol.startswith(_SPREADSHEET_FORMULA_PREFIXES)
                or not _SYMBOL.fullmatch(symbol)
                or symbol in seen
            ):
                raise WatchlistError(
                    f"invalid or duplicate symbol at row {row_number}"
                )
            seen.add(symbol)
            source_status = (row["source_status"] or "").strip()
            if not source_status or source_status.startswith(
                _SPREADSHEET_FORMULA_PREFIXES
            ):
                raise WatchlistError(f"invalid source status at row {row_number}")
            entries.append(
                WatchlistEntry(
                    symbol=symbol,
                    source_status=source_status,
                    source_last=_optional_decimal(
                        row["Last"],
                        row_number=row_number,
                        column="Last",
                    ),
                    source_change_pct=_optional_decimal(
                        row["Chg%"],
                        row_number=row_number,
                        column="Chg%",
                    ),
                )
            )

    if not entries:
        raise WatchlistError("watchlist is empty")
    return tuple(entries)
