"""STEP 3d - independent re-verification of the emitted CSV.

build_csv.py gates rows on the way out. This reads the CSV back and checks
every surviving row AGAIN, from the file rather than from the finding, so a
bug in the writer cannot hide a bad row. It also runs an adversarial control:
a plausible but fabricated excerpt must be rejected, otherwise the gate is
not actually gating.

Exit code 1 if any row fails or the adversarial control passes.
"""
from __future__ import annotations

import csv
import gzip
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.ingest.filings.documents import SourceDocument  # noqa: E402
from app.ingest.filings.verbatim import check_excerpt  # noqa: E402

FILINGS = REPO / "data" / "filings"
CSV_PATH = REPO / "data" / "ripple_exposures.csv"


def doc_for(isin: str) -> SourceDocument:
    meta = json.loads((FILINGS / isin / "source.json").read_text())
    with gzip.open(FILINGS / isin / "pages.json.gz", "rt", encoding="utf-8") as fh:
        pages = json.load(fh)
    return SourceDocument(url=meta["source_url"],
                          retrieved_at=datetime.fromisoformat(meta["retrieved_at"]),
                          media_type="application/pdf", sha256=meta["sha256"],
                          pages=tuple(pages))


def split_row(row: dict) -> list[tuple[str, str]]:
    """A row may cite one page or two. Returns (page, excerpt) pairs."""
    pages = [p.strip() for p in row["source_page"].split("+")]
    ex = row["verbatim_excerpt"]
    if len(pages) == 1:
        return [(pages[0], ex)]
    parts = ex.split("||")
    out = []
    for page, part in zip(pages, parts):
        part = part.strip()
        prefix = f"[p{page}]"
        if part.startswith(prefix):
            part = part[len(prefix):].strip()
        out.append((page, part))
    return out


def main() -> None:
    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8")))
    checked = failed = 0
    for row in rows:
        doc = doc_for(row["company_isin"])
        for page, excerpt in split_row(row):
            checked += 1
            res = check_excerpt(doc, excerpt=excerpt, source_page=page)
            ok = res.ok and res.page_verified
            flag = "ok " if ok else "FAIL"
            if not ok:
                failed += 1
                print(f"{flag} {row['company_isin']} p{page} {res.reason} "
                      f"page_verified={res.page_verified}")
        if not row["source_page"].strip():
            failed += 1
            print(f"FAIL {row['company_isin']} empty source_page")

    # adversarial control: a fabricated-but-plausible excerpt must be refused
    control_isin = rows[0]["company_isin"]
    fake = ("Details of raw materials consumed Synthetic rubber 2,11,904 "
            "Carbon black 1,43,495 Solvents 88,214 Total 9,19,712")
    ctrl = check_excerpt(doc_for(control_isin), excerpt=fake,
                         source_page=rows[0]["source_page"].split("+")[0].strip())
    control_ok = not ctrl.ok

    print(f"\nrows in CSV                 : {len(rows)}")
    print(f"page-level containment checks: {checked}")
    print(f"failures                     : {failed}")
    print(f"adversarial control refused  : {control_ok} ({ctrl.reason})")
    if failed or not control_ok:
        sys.exit(1)
    print("\nPASS - every row's excerpt appears verbatim on its cited page, "
          "and a fabricated excerpt is refused.")


if __name__ == "__main__":
    main()
