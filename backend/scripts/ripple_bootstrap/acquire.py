"""STEP 2 - acquire the latest annual report PDF for each roster company.

Sources, in order of preference:
  1. NSE corporate-filings annual-reports API -> nsearchives.nseindia.com PDF
  2. BSE AnnualReport_New API -> bseindia.com PDF

Both are the exchange's own copy of the company's filed annual report, i.e.
a primary document. No aggregator, no summary, no secondary source is used
or accepted - if neither exchange serves a PDF, the company goes to the
UNSOURCED file with reason PDF_UNAVAILABLE.

Artefacts, per company:
  data/filings/<isin>/<fy>_annual_report.pdf
  data/filings/<isin>/source.json   {source_url, retrieved_at, exchange, fy, sha256, bytes}
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roster import ROSTER, FAMILY_ORDER  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
DB = REPO / "backend" / "newsflo.db"
OUT = REPO / "data" / "filings"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def universe() -> dict:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out = {}
    for fam in FAMILY_ORDER:
        for ticker in ROSTER[fam]:
            r = con.execute(
                """select c.id, c.ticker, c.name, c.isin, c.market_cap,
                          (select symbol from listings l where l.company_id=c.id
                             and l.exchange='NSE') nse,
                          (select scrip_code from listings l where l.company_id=c.id
                             and l.exchange='BSE') bse
                     from companies c where c.ticker=?""", (ticker,)).fetchone()
            if r is None:
                raise SystemExit(f"roster ticker not in companies: {ticker}")
            out[ticker] = dict(r, family=fam)
    con.close()
    return out


def nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    # The homepage 403s but still sets the cookies the API needs.
    for url in ("https://www.nseindia.com/",
                "https://www.nseindia.com/companies-listing/corporate-filings-annual-reports"):
        try:
            s.get(url, timeout=30)
        except requests.RequestException:
            pass
    return s


def nse_reports(s: requests.Session, symbol: str) -> list[dict]:
    url = "https://www.nseindia.com/api/annual-reports"
    r = s.get(url, params={"index": "equities", "symbol": symbol},
              headers={"Referer": "https://www.nseindia.com/companies-listing/"
                                  "corporate-filings-annual-reports"}, timeout=40)
    if r.status_code != 200:
        return []
    try:
        data = r.json().get("data") or []
    except ValueError:
        return []
    out = []
    for d in data:
        fn = (d.get("fileName") or "").strip()
        if not fn.lower().endswith(".pdf"):
            continue
        try:
            to_yr = int(d.get("toYr") or 0)
        except (TypeError, ValueError):
            to_yr = 0
        out.append({"url": fn, "fy": to_yr, "exchange": "NSE",
                    "from_yr": d.get("fromYr")})
    out.sort(key=lambda x: x["fy"], reverse=True)
    return out


def bse_reports(s: requests.Session, scrip: str) -> list[dict]:
    url = "https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w"
    r = s.get(url, params={"scripcode": scrip},
              headers={"Referer": "https://www.bseindia.com/",
                       "Origin": "https://www.bseindia.com"}, timeout=40)
    if r.status_code != 200:
        return []
    try:
        rows = r.json().get("Table") or []
    except ValueError:
        return []
    out = []
    for d in rows:
        fn = (d.get("PDFDownload") or "").strip()
        if not fn.lower().endswith(".pdf"):
            continue
        try:
            fy = int(d.get("Year") or 0)
        except (TypeError, ValueError):
            fy = 0
        out.append({"url": fn, "fy": fy, "exchange": "BSE", "from_yr": None})
    out.sort(key=lambda x: x["fy"], reverse=True)
    return out


def download(s: requests.Session, url: str, dest: Path) -> tuple[bool, str]:
    ref = ("https://www.nseindia.com/" if "nseindia" in url
           else "https://www.bseindia.com/")
    try:
        r = s.get(url, headers={"Referer": ref, "Accept": "application/pdf,*/*"},
                  timeout=240, stream=True)
    except requests.RequestException as e:
        return False, f"request failed: {e.__class__.__name__}"
    if r.status_code != 200:
        return False, f"http {r.status_code}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    n = 0
    with open(tmp, "wb") as fh:
        for chunk in r.iter_content(1 << 16):
            fh.write(chunk)
            n += len(chunk)
    with open(tmp, "rb") as fh:
        head = fh.read(5)
    if head != b"%PDF-":
        tmp.unlink(missing_ok=True)
        return False, "response is not a PDF"
    if n < 100_000:
        tmp.unlink(missing_ok=True)
        return False, f"PDF suspiciously small ({n} bytes)"
    os.replace(tmp, dest)
    return True, ""


def main() -> None:
    only = set(sys.argv[1:]) or None
    uni = universe()
    s = nse_session()
    log = []
    for ticker, c in uni.items():
        if only and c["family"] not in only and ticker not in only:
            continue
        isin = c["isin"]
        d = OUT / isin
        meta_p = d / "source.json"
        if meta_p.exists():
            m = json.loads(meta_p.read_text())
            if (d / m["filename"]).exists():
                print(f"[skip] {ticker:<14} already have FY{m['fy']}")
                log.append({"ticker": ticker, "status": "CACHED", **m})
                continue

        cands = []
        if c["nse"]:
            cands = nse_reports(s, c["nse"])
            time.sleep(0.6)
        if not cands and c["bse"]:
            cands = bse_reports(s, c["bse"])
            time.sleep(0.6)
        if not cands and c["nse"]:  # NSE listed but API empty -> try BSE anyway
            if c["bse"]:
                cands = bse_reports(s, c["bse"])

        if not cands:
            print(f"[MISS] {ticker:<14} no annual report listed on either exchange")
            log.append({"ticker": ticker, "isin": isin, "family": c["family"],
                        "status": "NO_LISTING"})
            continue

        ok = False
        for cand in cands[:3]:
            fy = cand["fy"]
            fname = f"FY{fy}_annual_report.pdf"
            good, why = download(s, cand["url"], d / fname)
            if good:
                raw = (d / fname).read_bytes()
                meta = {
                    "isin": isin, "ticker": ticker, "name": c["name"],
                    "family": c["family"], "filename": fname, "fy": fy,
                    "exchange": cand["exchange"], "source_url": cand["url"],
                    "retrieved_at": now_iso(),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                }
                meta_p.write_text(json.dumps(meta, indent=2))
                print(f"[ok]   {ticker:<14} FY{fy} {cand['exchange']} "
                      f"{len(raw)//1024}kb")
                log.append({"status": "OK", **meta})
                ok = True
                break
            print(f"       {ticker:<14} FY{fy} {cand['exchange']} failed: {why}")
            time.sleep(1.0)
        if not ok:
            log.append({"ticker": ticker, "isin": isin, "family": c["family"],
                        "status": "DOWNLOAD_FAILED"})
        time.sleep(0.4)

    (OUT / "_acquire_log.json").parent.mkdir(parents=True, exist_ok=True)
    prev = []
    lp = OUT / "_acquire_log.json"
    if lp.exists():
        prev = json.loads(lp.read_text())
    lp.write_text(json.dumps(prev + log, indent=2))
    ok = sum(1 for x in log if x.get("status") in ("OK", "CACHED"))
    print(f"\nacquired {ok}/{len(log)} this run")


if __name__ == "__main__":
    main()
