"""Extract just the 'cost of materials consumed' note block from every filing.

Prints the header line and the lines that follow it up to the next note
heading, so the presence or absence of a component breakup can be judged
across the whole roster without reading whole pages.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from roster import ROSTER, FAMILY_ORDER  # noqa: E402

FILINGS = REPO / "data" / "filings"
HEAD = re.compile(r"cost\s+of\s+materials?\s+consumed|raw\s+materials?\s+consumed",
                  re.I)
NEXT = re.compile(r"^\s*(?:note\s*[-:]?\s*)?\d{1,2}[.)]?\s+[A-Z]", re.I)
MAXLINES = 22


def idx():
    out = {}
    for d in FILINGS.iterdir():
        if d.is_dir() and (d / "source.json").exists():
            m = json.loads((d / "source.json").read_text())
            out[m["ticker"]] = (d, m)
    return out


def main() -> None:
    fams = sys.argv[1:] or FAMILY_ORDER
    tbl = idx()
    for fam in fams:
        print("\n" + "#" * 74)
        print("# FAMILY:", fam)
        for ticker in ROSTER[fam]:
            d, m = tbl[ticker]
            gz = d / "pages.json.gz"
            print("\n" + "=" * 66)
            print(f"{ticker} | {m['name']} | FY{m['fy']} | {m['isin']}")
            if not gz.exists():
                print("  !! NOT INDEXED")
                continue
            with gzip.open(gz, "rt", encoding="utf-8") as fh:
                pages = json.load(fh)
            shown = 0
            for pno, txt in enumerate(pages, 1):
                lines = txt.split("\n")
                for i, ln in enumerate(lines):
                    if not HEAD.search(ln):
                        continue
                    block = lines[i:i + MAXLINES]
                    out = []
                    for j, b in enumerate(block):
                        if j and NEXT.match(b) and j > 3:
                            break
                        out.append(b.rstrip())
                    print(f"  --- p{pno} ---")
                    print("    " + "\n    ".join(out))
                    shown += 1
                    break
                if shown >= 2:
                    break
            if not shown:
                print("  (no 'materials consumed' heading found in text layer)")


if __name__ == "__main__":
    main()
