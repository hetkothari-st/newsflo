"""STEP 3c - turn reviewed findings into the two output CSVs.

Input:  data/filings/<isin>/finding.json   (one per company, hand-authored
        while reading the cited page; see SCHEMA below)
Output: data/ripple_exposures.csv
        data/ripple_exposures_UNSOURCED.csv

THIS SCRIPT COMPUTES share_of_base. Nothing else may. A finding states the
component VALUES it read off the page and the arithmetic is done here, so
there is no place for a share to arrive as a number somebody felt was about
right.

FOUR GATES, every one of which drops the row rather than warning:

  1. VERBATIM      - app.ingest.filings.verbatim.check_excerpt, the same gate
                     the Phase 1 ledger uses. Whitespace-normalised literal
                     containment, in the document AND on the cited page.
                     Run TWICE where the denominator lives on a different
                     page from the numerator: that page needs its own excerpt
                     and its own containment check.
  2. FIGURES       - every numerator and denominator figure must itself
                     appear on its own cited page, as written. This is the
                     guard against a correctly-cited excerpt carrying
                     transcribed numbers that are not in it.
  3. ARITHMETIC    - share = sum(numerator) / denominator, computed here,
                     must land in (0, 1]. A share of 0 is not an exposure and
                     a share above 1 means the base is wrong.
  4. PAGE          - source_page mandatory (gate 1 enforces it too).

SCHEMA of finding.json:
{
  "isin": "INE883A01011",
  "family": "tyres",
  "exposure_tag": "input:crude_derivative_rubber",
  "base_kind": "COGS",
  "source_page": "214",
  "verbatim_excerpt": "<copied out of the page dump, unedited>",
  "numerator": [{"label": "Synthetic Rubber", "value": "1,234.56"}],
  "denominator": {"label": "Total materials consumed", "value": "9,876.54"},
  "computed_from": "<what was added up, and any judgement made>",
  "unit_note": "Rs in crores"          # optional, free text
}

or, for a company that could not be sourced:
{
  "isin": "...", "family": "...", "unsourced": "AGGREGATED_SINGLE_LINE",
  "reason": "<the specific reason, in a sentence>",
  "checked_pages": [214, 215]
}
"""
from __future__ import annotations

import csv
import gzip
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend"))

from app.ingest.filings.documents import (  # noqa: E402
    SourceDocument, normalize_whitespace,
)
from app.ingest.filings.verbatim import check_excerpt  # noqa: E402

FILINGS = REPO / "data" / "filings"
SOURCED_CSV = REPO / "data" / "ripple_exposures.csv"
UNSOURCED_CSV = REPO / "data" / "ripple_exposures_UNSOURCED.csv"

SOURCED_COLS = ["company_isin", "exposure_tag", "share_of_base", "base_kind",
                "source_url", "source_page", "verbatim_excerpt", "computed_from"]
UNSOURCED_COLS = ["company_isin", "family", "reason"]


def load_document(isin: str) -> tuple[SourceDocument, dict]:
    d = FILINGS / isin
    meta = json.loads((d / "source.json").read_text())
    with gzip.open(d / "pages.json.gz", "rt", encoding="utf-8") as fh:
        pages = json.load(fh)
    doc = SourceDocument(
        url=meta["source_url"],
        retrieved_at=datetime.fromisoformat(meta["retrieved_at"]),
        media_type="application/pdf",
        sha256=meta["sha256"],
        pages=tuple(pages),
    )
    return doc, meta


def to_decimal(raw: str) -> Decimal:
    return Decimal(str(raw).replace(",", "").replace("−", "-").strip())


def main() -> None:
    findings = sorted(FILINGS.glob("*/finding.json"))
    sourced, unsourced, rejected = [], [], []

    loaded = []
    for path in findings:
        blob = json.loads(path.read_text(encoding="utf-8"))
        loaded.extend(blob if isinstance(blob, list) else [blob])

    for f in loaded:
        isin = f["isin"]
        family = f["family"]

        if f.get("unsourced"):
            unsourced.append({
                "company_isin": isin, "family": family,
                "reason": f"{f['unsourced']}: {f['reason']}",
            })
            continue

        doc, meta = load_document(isin)
        num_page = str(f["source_page"])
        den = f["denominator"]
        den_page = str(den.get("page") or num_page)
        num_txt = doc.page_text(int(num_page)) or ""
        den_txt = doc.page_text(int(den_page)) or ""

        # GATE 1 - verbatim, once per cited page
        res = check_excerpt(doc, excerpt=f["verbatim_excerpt"],
                            source_page=num_page)
        if not res.ok:
            rejected.append((isin, family, f"VERBATIM_{res.reason}"))
            continue
        if den_page != num_page:
            den_ex = f.get("denominator_excerpt")
            if not den_ex:
                rejected.append((isin, family,
                                 "NO_DENOMINATOR_EXCERPT_FOR_SECOND_PAGE"))
                continue
            res2 = check_excerpt(doc, excerpt=den_ex, source_page=den_page)
            if not res2.ok:
                rejected.append((isin, family, f"VERBATIM_DEN_{res2.reason}"))
                continue

        # GATE 2 - every figure on its own cited page
        missing = [c["value"] for c in f["numerator"]
                   if normalize_whitespace(str(c["value"])) not in num_txt]
        if normalize_whitespace(str(den["value"])) not in den_txt:
            missing.append(str(den["value"]))
        if missing:
            rejected.append((isin, family,
                             f"FIGURE_NOT_ON_PAGE: {', '.join(missing)}"))
            continue

        # GATE 3 - arithmetic, computed here
        try:
            num = sum((to_decimal(c["value"]) for c in f["numerator"]), Decimal(0))
            den = to_decimal(f["denominator"]["value"])
        except (InvalidOperation, ValueError) as e:
            rejected.append((isin, family, f"UNPARSEABLE_FIGURE: {e}"))
            continue
        if den <= 0:
            rejected.append((isin, family, "NON_POSITIVE_DENOMINATOR"))
            continue
        share = num / den
        if not (Decimal(0) < share <= Decimal(1)):
            rejected.append((isin, family, f"SHARE_OUT_OF_RANGE: {share:.4f}"))
            continue

        sourced.append({
            "company_isin": isin,
            "exposure_tag": f["exposure_tag"],
            "share_of_base": f"{share:.4f}",
            "base_kind": f["base_kind"],
            "source_url": meta["source_url"],
            "source_page": (num_page if den_page == num_page
                            else f"{num_page} + {den_page}"),
            "verbatim_excerpt": normalize_whitespace(
                f["verbatim_excerpt"] if den_page == num_page
                else f"[p{num_page}] {f['verbatim_excerpt']}  ||  "
                     f"[p{den_page}] {f['denominator_excerpt']}"),
            "computed_from": f["computed_from"],
        })

    for isin, family, why in rejected:
        unsourced.append({"company_isin": isin, "family": family,
                          "reason": f"ROW_REJECTED_BY_GATE: {why}"})

    SOURCED_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(SOURCED_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, SOURCED_COLS)
        w.writeheader()
        w.writerows(sorted(sourced, key=lambda r: r["company_isin"]))
    with open(UNSOURCED_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, UNSOURCED_COLS)
        w.writeheader()
        w.writerows(sorted(unsourced, key=lambda r: r["company_isin"]))

    print(f"finding files  : {len(findings)}")
    print(f"findings read  : {len(loaded)}")
    print(f"sourced rows  : {len(sourced)}  -> {SOURCED_CSV.relative_to(REPO)}")
    print(f"unsourced rows: {len(unsourced)} -> {UNSOURCED_CSV.relative_to(REPO)}")
    print(f"  of which rejected by a gate: {len(rejected)}")
    for isin, family, why in rejected:
        print(f"    REJECTED {isin} ({family}) {why}")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"\nrun at {stamp}")


if __name__ == "__main__":
    main()
