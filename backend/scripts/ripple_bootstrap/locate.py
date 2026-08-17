"""STEP 3b - locate candidate pages in an indexed annual report.

Usage:
  python locate.py <ISIN|TICKER> [regex ...]      # search
  python locate.py <ISIN|TICKER> --page 214       # dump one page verbatim
  python locate.py --notes                        # default note-hunting sweep

Prints 1-based PDF page numbers. Nothing here computes or proposes a value;
it only finds the page a human/model must then read.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "data" / "filings"

DEFAULT_PATTERNS = [
    r"cost of materials? consumed",
    r"raw materials? consumed",
    r"materials? consumed",
    r"consumption of raw material",
]


def resolve(key: str) -> Path:
    p = OUT / key
    if p.exists():
        return p
    for d in OUT.iterdir():
        if not d.is_dir() or not (d / "source.json").exists():
            continue
        m = json.loads((d / "source.json").read_text())
        if m["ticker"].upper() == key.upper() or m["ticker"].split(".")[0].upper() == key.upper():
            return d
    raise SystemExit(f"unknown company: {key}")


def pages_of(d: Path) -> list[str]:
    with gzip.open(d / "pages.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)


def main() -> None:
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    d = resolve(args[0])
    meta = json.loads((d / "source.json").read_text())
    pages = pages_of(d)
    rest = args[1:]

    if rest and rest[0] == "--page":
        for n in rest[1:]:
            i = int(n)
            print(f"=========== {meta['ticker']} page {i} / {len(pages)} ===========")
            print(pages[i - 1])
        return

    pats = rest or DEFAULT_PATTERNS
    print(f"# {meta['ticker']} {meta['name']} FY{meta['fy']} "
          f"({len(pages)} pages, {meta['exchange']})")
    for pat in pats:
        rx = re.compile(pat, re.I)
        hits = [i + 1 for i, t in enumerate(pages) if rx.search(t)]
        print(f"  /{pat}/ -> {hits}")


if __name__ == "__main__":
    main()
