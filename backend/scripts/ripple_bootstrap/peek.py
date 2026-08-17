"""Dump the text around a match on given pages, compactly.

  python peek.py TICKER 124 199            # windows around the note match
  python peek.py TICKER 124 --full         # whole page
  python peek.py TICKER --grep "Carbon"    # pages containing a term
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[3]
FILINGS = REPO / "data" / "filings"
NOTE = re.compile(r"cost\s+of\s+materials?\s+consumed|raw\s+materials?\s+consumed"
                  r"|materials?\s+consumed", re.I)
WIN = 1600


def find(key: str):
    for d in FILINGS.iterdir():
        if d.is_dir() and (d / "source.json").exists():
            m = json.loads((d / "source.json").read_text())
            if key.upper() in (m["ticker"].upper(),
                               m["ticker"].split(".")[0].upper(), m["isin"]):
                with gzip.open(d / "pages.json.gz", "rt", encoding="utf-8") as fh:
                    return m, json.load(fh)
    raise SystemExit(f"unknown {key}")


def main() -> None:
    m, pages = find(sys.argv[1])
    args = sys.argv[2:]
    print(f"### {m['ticker']} {m['name']} FY{m['fy']} pages={len(pages)}")
    if args and args[0] == "--grep":
        rx = re.compile(args[1], re.I)
        for i, t in enumerate(pages):
            for mt in rx.finditer(t):
                s = max(0, mt.start() - 300)
                print(f"--- p{i+1} ---\n{t[s:mt.end()+500]}\n")
        return
    full = "--full" in args
    nums = [int(a) for a in args if a.isdigit()]
    for n in nums:
        t = pages[n - 1]
        print(f"\n=========== page {n} ===========")
        if full:
            print(t)
            continue
        mt = NOTE.search(t)
        if not mt:
            print(t[:WIN])
            continue
        s = max(0, mt.start() - 200)
        print(t[s:mt.start() + WIN])


if __name__ == "__main__":
    main()
