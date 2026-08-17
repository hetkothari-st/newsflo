"""STEP 3b(bulk) - dump the note text around every raw-material hit, per family.

Writes one plain-text report per family to the scratch dir so the pages can
be read in bulk. Nothing is computed here.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from roster import ROSTER, FAMILY_ORDER  # noqa: E402

FILINGS = REPO / "data" / "filings"

PATTERNS = [
    r"[Cc]ost of materials? consumed",
    r"[Rr]aw materials? consumed",
    r"[Cc]onsumption of raw material",
    r"[Ff]reight[, ].{0,40}handling",
    r"[Ff]uel (?:and|&) ",
]


def by_ticker() -> dict:
    out = {}
    for d in FILINGS.iterdir():
        if d.is_dir() and (d / "source.json").exists():
            m = json.loads((d / "source.json").read_text())
            out[m["ticker"]] = (d, m)
    return out


def main() -> None:
    fams = sys.argv[1:] or FAMILY_ORDER
    pats = [re.compile(p) for p in PATTERNS]
    idx = by_ticker()
    for fam in fams:
        lines = []
        for ticker in ROSTER[fam]:
            d, m = idx[ticker]
            gz = d / "pages.json.gz"
            if not gz.exists():
                lines.append(f"\n##### {ticker} {m['name']} -- NOT INDEXED\n")
                continue
            with gzip.open(gz, "rt", encoding="utf-8") as fh:
                pages = json.load(fh)
            lines.append(f"\n\n##### {ticker} | {m['name']} | FY{m['fy']} | "
                         f"{len(pages)} pages | {m['isin']}")
            hits = {}
            for i, t in enumerate(pages):
                for p in pats:
                    if p.search(t):
                        hits.setdefault(i + 1, set()).add(p.pattern)
            lines.append(f"  hit pages: {sorted(hits)}")
            for pg in sorted(hits):
                lines.append(f"\n----- page {pg} -----")
                lines.append(pages[pg - 1])
        dest = Path(sys.argv[0]).parent / f"_sweep_{fam}.txt"
        dest.write_text("\n".join(lines), encoding="utf-8")
        print(f"{fam}: {dest} ({dest.stat().st_size//1024}kb)")


if __name__ == "__main__":
    main()
