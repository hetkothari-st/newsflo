"""THE 10-FILING AUTO-COMPONENTS PROBE — acquisition half.

Acquires annual reports for a hand-picked list of `Auto Components &
Equipments` companies so the two STEEL leaves can be swept against a corpus
where steel is CORE. `MEASUREMENTS_2026-08-17.md` sec 9.4 states the purpose:
10 filings distinguishes an 80% hit rate from a 20% one, and that is the
number that sizes the whole acquisition project.

REUSES the deployed acquisition path (`backend/scripts/ripple_bootstrap/
acquire.py`) rather than reimplementing it -- same exchange APIs, same PDF
validation, same `source.json` provenance shape (URL, UTC retrieval time,
sha256, bytes). It does NOT edit `roster.py`, which is tracked and owned by
another session; the ticker list is a local constant.

Writes ONLY to `data/filings/<isin>/`, additively, and never overwrites an
existing directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO = Path(os.environ.get("NEWSFLO_REPO") or Path(__file__).resolve().parents[3])
DB = REPO / "backend" / "newsflo.db"
OUT = REPO / "data" / "filings"
sys.path.insert(0, str(REPO / "backend" / "scripts" / "ripple_bootstrap"))

from acquire import UA, bse_reports, download, nse_reports, nse_session  # noqa: E402

# Ten by market cap, all with a BSE scrip code, all pure auto-component makers.
# Asahi India Glass is deliberately INCLUDED as a negative control: it is in the
# same isubgroup and makes GLASS, so it should NOT yield a steel claim. If it
# does, the sweep is over-matching.
TICKERS = [
    "MOTHERSON.NS", "BOSCHLTD.NS", "BHARATFORG.NS", "UNOMINDA.NS",
    "SCHAEFFLER.NS", "TIINDIA.NS", "SONACOMS.NS", "ENDURANCE.NS",
    "EXIDEIND.NS", "CRAFTSMAN.NS", "ASAHIINDIA.NS",
]


def rows():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out = []
    for ticker in TICKERS:
        r = con.execute(
            """select c.id, c.ticker, c.name, c.isin,
                      (select symbol from listings l where l.company_id=c.id
                         and l.exchange='NSE') nse,
                      (select scrip_code from listings l where l.company_id=c.id
                         and l.exchange='BSE') bse
                 from companies c where c.ticker=?""", (ticker,)).fetchone()
        if r is None:
            print(f"  !! {ticker} not in companies")
            continue
        out.append(dict(r))
    con.close()
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    try:
        nse = nse_session()
    except Exception as exc:                       # NSE 403s from this machine
        print(f"nse_session unavailable ({exc.__class__.__name__}); BSE only")
        nse = session

    ok, failed = [], []
    for row in rows():
        isin, ticker = row["isin"], row["ticker"]
        d = OUT / isin
        if (d / "source.json").exists():
            print(f"  == {ticker} already acquired, skipping")
            ok.append(ticker)
            continue

        reports = []
        if row["nse"]:
            try:
                reports = nse_reports(nse, row["nse"])
            except Exception as exc:
                print(f"  .. {ticker} NSE {exc.__class__.__name__}")
        if not reports and row["bse"]:
            try:
                reports = bse_reports(session, str(row["bse"]))
            except Exception as exc:
                print(f"  .. {ticker} BSE {exc.__class__.__name__}")
        if not reports:
            failed.append((ticker, "NO_REPORT_LISTED"))
            print(f"  XX {ticker} no report listed on either exchange")
            continue

        wrote = False
        for rep in reports[:3]:                    # newest first, try up to 3
            dest = d / f"FY{rep['fy']}_annual_report.pdf"
            good, why = download(session, rep["url"], dest)
            if not good:
                print(f"  .. {ticker} FY{rep['fy']} {why}")
                continue
            data = dest.read_bytes()
            (d / "source.json").write_text(json.dumps({
                "isin": isin, "ticker": ticker, "name": row["name"],
                "family": "auto_components", "filename": dest.name,
                "fy": rep["fy"], "exchange": rep["exchange"],
                "source_url": rep["url"],
                "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }, indent=2), encoding="utf-8")
            print(f"  OK {ticker} FY{rep['fy']} {len(data):,} bytes {rep['exchange']}")
            ok.append(ticker)
            wrote = True
            break
        if not wrote:
            failed.append((ticker, "PDF_UNAVAILABLE"))

    print(f"\nacquired {len(ok)} / {len(TICKERS)}")
    for ticker, why in failed:
        print(f"  UNSOURCED {ticker} {why}")


if __name__ == "__main__":
    main()
