"""Load AMFI's published half-yearly LARGE/MID/SMALL categorisation list
into Company.amfi_tier -- the sourced half of "sourced-or-derived" cap
tiers (app.market.cap_tier.resolve_cap_tier prefers this over the
BSE/yfinance-cap-derived rank whenever it's present and fresh).

AMFI publishes ONLY .xlsx (verified live on 2026-08-03:
https://portal.amfiindia.com/spages/AverageMarketCapitalization30Jun2026.xlsx,
linked from https://www.amfiindia.com/otherdata/categorisation-of-stocks).
This project deliberately does not depend on an Excel-reading library to
read it: `openpyxl` is not installed, and `pandas` (which IS a dependency,
see requirements.txt) cannot read .xlsx without it -- `pd.read_excel()`/
`pd.DataFrame.to_excel()` both raise `ModuleNotFoundError: No module named
'openpyxl'` in this environment. Adding openpyxl for one half-yearly manual
run was judged not worth a new production dependency.

So the flow is manual-download-and-convert, then this script does the
DB write:
    1. Download the .xlsx from the URL above (re-fetch the current file
       from the landing page if that exact filename has rolled over to a
       new half-year).
    2. Open it in Excel/LibreOffice/Google Sheets and "Save As" / "Export"
       CSV, keeping the header row exactly as published -- this script
       (via app.companies.universe.normalize.parse_amfi_rows) matches on
       the literal column names "ISIN" and
       "Categorization as per SEBI Circular dated Oct 6, 2017".
    3. python load_amfi.py path/to/converted.csv

Idempotent: re-running with a newer file overwrites amfi_tier/amfi_rank/
amfi_as_of for every matched company; never creates a company (AMFI
categorises the universe, it isn't a source for it -- unmatched ISINs are
silently skipped by apply_amfi_categorisation).
"""
import argparse
from datetime import date
from pathlib import Path

from app.companies.universe import loader, normalize
from app.db import SessionLocal, init_db


def run_load(csv_text: str, session, as_of: date) -> dict:
    rows = normalize.parse_amfi_rows(csv_text)
    updated = loader.apply_amfi_categorisation(session, rows, as_of)
    return {"parsed": len(rows), "updated": updated}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "csv_path",
        help="Path to the AMFI categorisation CSV, converted from the published .xlsx (see module docstring)",
    )
    parser.add_argument(
        "--as-of", help="Effective date for this categorisation, YYYY-MM-DD (default: today)",
    )
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    csv_text = Path(args.csv_path).read_text(encoding="utf-8")

    init_db()
    session = SessionLocal()
    try:
        result = run_load(csv_text, session, as_of)
        if result["parsed"] == 0:
            print(
                f"WARNING: 0 usable rows parsed from {args.csv_path} -- "
                "check the header matches the AMFI workbook shape "
                "(expects an 'ISIN' column and a "
                "'Categorization as per SEBI Circular dated Oct 6, 2017' column)"
            )
        print(f"AMFI categorisation: {result['updated']}/{result['parsed']} companies updated (as_of={as_of.isoformat()})")
    finally:
        session.close()


if __name__ == "__main__":
    main()
