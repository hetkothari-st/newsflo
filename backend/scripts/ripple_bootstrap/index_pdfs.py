"""STEP 3a - extract per-page text from each acquired annual report.

The extracted text is what the verbatim-containment gate checks against, so
it is cached to disk verbatim and never normalised in place. Page numbers
recorded are 1-based PDF page indices (the physical page of the file, which
is what a reviewer opening the PDF at that page will see).
"""
from __future__ import annotations

import gzip
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pypdf

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "data" / "filings"


def index_one(isin: str) -> tuple[str, int, str]:
    d = OUT / isin
    meta = json.loads((d / "source.json").read_text())
    pdf = d / meta["filename"]
    dest = d / "pages.json.gz"
    if dest.exists():
        return isin, -1, "cached"
    try:
        reader = pypdf.PdfReader(str(pdf))
        pages = []
        for p in reader.pages:
            try:
                pages.append(p.extract_text() or "")
            except Exception as e:  # a single bad page must not lose the file
                pages.append(f"<<EXTRACT_ERROR {e.__class__.__name__}>>")
    except Exception as e:
        return isin, 0, f"FAILED {e.__class__.__name__}: {e}"
    with gzip.open(dest, "wt", encoding="utf-8") as fh:
        json.dump(pages, fh)
    empties = sum(1 for t in pages if len(t.strip()) < 20)
    return isin, len(pages), f"ok ({empties} near-empty pages)"


def main() -> None:
    isins = sorted(p.name for p in OUT.iterdir()
                   if p.is_dir() and (p / "source.json").exists())
    if len(sys.argv) > 1:
        isins = [i for i in isins if i in set(sys.argv[1:])]
    with ProcessPoolExecutor(max_workers=6) as ex:
        for isin, n, msg in ex.map(index_one, isins):
            print(f"{isin}  {n:>5} pages  {msg}")


if __name__ == "__main__":
    main()
