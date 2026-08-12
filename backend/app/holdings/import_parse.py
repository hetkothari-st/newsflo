"""Provider-agnostic holdings import: parse whatever CSV an Indian
broker's console exports (Zerodha, Groww, Upstox, Angel One, ...) and
resolve each row to a Company.

Broker exports differ in header names and preamble rows, but every
holdings file carries some subset of: an ISIN, an exchange symbol, and a
quantity. The parser scans for the first row that looks like a header,
maps columns by fuzzy name, and matches companies by ISIN first (unique,
exchange-agnostic), then by NSE/BSE ticker variants. Unmatched rows are
reported back, never silently dropped -- the user sees exactly what
didn't import and why.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import Company

# Column-name fragments, checked lowercase. Order matters for quantity:
# broker files carry several quantity-ish columns (pledged, discrepant,
# T1) -- the effective-holdings ones are preferred.
_QTY_PRIORITY = (
    "quantity available", "available quantity", "balance quantity",
    "net quantity", "total quantity", "closing balance", "quantity", "qty",
    "shares", "units",
)
_SYMBOL_FRAGMENTS = ("tradingsymbol", "trading symbol", "symbol", "ticker", "scrip", "instrument", "stock name")
_ISIN_FRAGMENT = "isin"


@dataclass
class ImportReport:
    imported: list[dict] = field(default_factory=list)  # {ticker, name, quantity}
    skipped: list[dict] = field(default_factory=list)   # {row, reason}

    def as_dict(self) -> dict:
        return {"imported": self.imported, "skipped": self.skipped}


def _find_header(rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    """First row that yields a quantity column plus an ISIN or symbol
    column wins. Returns (row_index, {isin/symbol/qty -> column index})."""
    for index, row in enumerate(rows[:20]):
        lowered = [cell.strip().lower() for cell in row]
        mapping: dict[str, int] = {}
        for col, cell in enumerate(lowered):
            if _ISIN_FRAGMENT in cell and "isin" not in mapping:
                mapping["isin"] = col
            if "symbol" not in mapping and any(f in cell for f in _SYMBOL_FRAGMENTS):
                mapping["symbol"] = col
        best_qty: tuple[int, int] | None = None  # (priority, col)
        for col, cell in enumerate(lowered):
            for priority, fragment in enumerate(_QTY_PRIORITY):
                if fragment in cell:
                    if best_qty is None or priority < best_qty[0]:
                        best_qty = (priority, col)
                    break
        if best_qty is not None and ("isin" in mapping or "symbol" in mapping):
            mapping["qty"] = best_qty[1]
            return index, mapping
    return None


def _match_company(session: Session, isin: str, symbol: str) -> Company | None:
    if isin:
        company = session.query(Company).filter_by(isin=isin).one_or_none()
        if company is not None:
            return company
    if symbol:
        # Broker symbols are bare ("RELIANCE"); tickers are suffixed.
        for candidate in (symbol, f"{symbol}.NS", f"{symbol}.BO"):
            company = session.query(Company).filter_by(ticker=candidate).one_or_none()
            if company is not None:
                return company
    return None


def parse_and_match(session: Session, raw: bytes | str) -> tuple[list[tuple[Company, float]], ImportReport]:
    """Returns (matches, report). Matches are (company, quantity>0) pairs;
    the report's imported list is filled by the caller AFTER upserting so
    it reflects what was actually written."""
    text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw
    rows = list(csv.reader(io.StringIO(text)))
    report = ImportReport()

    header = _find_header(rows)
    if header is None:
        report.skipped.append({"row": "", "reason": "no recognizable header (need ISIN or symbol plus a quantity column)"})
        return [], report

    header_index, cols = header
    matches: list[tuple[Company, float]] = []
    for row in rows[header_index + 1:]:
        if not any(cell.strip() for cell in row):
            continue
        isin = row[cols["isin"]].strip().upper() if "isin" in cols and cols["isin"] < len(row) else ""
        symbol = row[cols["symbol"]].strip().upper() if "symbol" in cols and cols["symbol"] < len(row) else ""
        qty_raw = row[cols["qty"]].strip() if cols["qty"] < len(row) else ""
        label = symbol or isin or ",".join(row)[:40]
        try:
            quantity = float(qty_raw.replace(",", ""))
        except ValueError:
            report.skipped.append({"row": label, "reason": f"unreadable quantity {qty_raw!r}"})
            continue
        if quantity <= 0:
            report.skipped.append({"row": label, "reason": "zero quantity"})
            continue
        company = _match_company(session, isin, symbol)
        if company is None:
            report.skipped.append({"row": label, "reason": "no matching company (ISIN/symbol unknown)"})
            continue
        matches.append((company, quantity))
    return matches, report
