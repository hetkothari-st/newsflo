"""Source `hedge_ratio` at FILED grade for the nine companies in the ledger.

WHAT THIS DOES AND DOES NOT DO
------------------------------
It SOURCES. It does not WRITE. `company_modifier` has no reviewed write path
-- no proposal table, no review function, no loader, and (unlike
`company_exposure`) no trigger guard of any kind. That is defect D1 in
`docs/v5/defects/DEFECTS-001-ceat-proof-of-life.md`, and the owner's
instruction is to stop rather than use direct SQL again. So this emits a
reviewed-ready artefact and stops.

WHY hedge_ratio IS WORTH DOING FIRST
------------------------------------
It is the one link in the §5.1 COST formula that Indian disclosure reliably
supplies at the top grade. SEBI LODR Reg 34(3) / Schedule V requires a
"Commodity price risk or foreign exchange risk and hedging activities" entry
in the Corporate Governance Report, and where a company answers the commodity
limb of it, the answer is a sentence with a page.

THE RULE APPLIED, AND IT IS STRICTER THAN IT LOOKS
--------------------------------------------------
"Does not hedge" is a POSITIVE disclosure of 0.0 and is recorded as one, with
the excerpt. But the heading covers TWO risks, and most companies answer only
the foreign-exchange limb. An FX-only answer is NOT a commodity disclosure and
is NOT recorded as 0.0 -- it goes to the unsourced file with the text that was
actually found, so a reviewer can disagree with the call on the evidence.

Gates, all four, same as the exposure run:
  1. the excerpt must clear `app.ingest.filings.verbatim.check_excerpt`
     -- whitespace-normalised literal containment, in the document AND on the
     cited page
  2. source_page mandatory
  3. hedge_ratio must be in [0, 1]
  4. effective_from / effective_to must bound the period the disclosure
     actually covers. NEVER NULL: a hedging statement for FY2026 says nothing
     about FY2027, and an open-ended row would quietly claim it does.
"""
from __future__ import annotations

import csv
import gzip
import json
import sys
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.ingest.filings.documents import (  # noqa: E402
    SourceDocument, normalize_whitespace,
)
from app.ingest.filings.verbatim import check_excerpt  # noqa: E402

FILINGS = REPO / "data" / "filings"
OUT_FILED = REPO / "data" / "hedge_ratio_FILED.csv"
OUT_ABSENT = REPO / "data" / "hedge_ratio_UNSOURCED.csv"
OUT_JSON = REPO / "data" / "hedge_ratio_proposals.json"

# The financial year each filing's disclosure covers. The LODR entry is made
# in the Corporate Governance Report for a stated financial year and speaks
# for that year only.
FY_WINDOW = {
    2026: ("2025-04-01", "2026-03-31"),
    2025: ("2024-04-01", "2025-03-31"),
}

# --------------------------------------------------------------- SOURCED
# hedge_ratio = 0.0, measurement = FILED. Each is an explicit answer to the
# COMMODITY limb of the LODR disclosure.
SOURCED = [
    dict(
        isin="INE482A01020", tags=["input:crude_derivative_rubber",
                                   "input:crude_derivative_petchem"],
        page="61", hedge_ratio=0.0,
        excerpt=("does not have any exposure hedged through commodity "
                 "during FY 2025-26."),
        note=("Corporate Governance Report, under 'Exposure to commodity and "
              "commodity risk faced throughout the year'. THE EXCERPT IS "
              "TRIMMED AT THE FRONT ON PURPOSE: the sentence begins 'T he "
              "Company does not have...' in the PDF text layer -- pypdf "
              "splits the leading glyph -- and quoting it with the subject "
              "would either embed an extraction artefact in the ledger or "
              "fail the containment gate, which it did on the first run. The "
              "trimmed form is a true substring and reads correctly. "
              "Unambiguous and "
              "specific to commodity. The same paragraph separately describes "
              "FX hedging with forwards and derivatives, so the company is "
              "distinguishing the two limbs itself -- which is what makes the "
              "commodity answer readable as 0.0 rather than as silence. Note "
              "the preceding sentence describes commodity PROCUREMENT ('a "
              "price forecast mechanism and a buying model that includes "
              "spot, forward and long-term contracts'); that is sourcing "
              "practice, not a financial hedge, and it is not what this row "
              "records."),
    ),
    dict(
        isin="INE148O01028", tags=["input:bought_in_freight"],
        page="67", hedge_ratio=0.0,
        excerpt=("The Company considers commodity price risk and currency "
                 "risk to be low and does not hedge these risks."),
        note=("Corporate Governance Report. Answers both limbs explicitly and "
              "names commodity price risk. 'Considers... to be low' is the "
              "company's characterisation of the RISK and is not adopted here "
              "-- only the hedging statement is."),
    ),
    dict(
        isin="INE766P01016", tags=["input:bought_in_freight"],
        page="79", hedge_ratio=0.0,
        excerpt=("The Company does not deal in commodities and has no foreign "
                 "exchange or hedging exposures, hence disclosures relating "
                 "to risk management policy with respect to commodities, "
                 "commodity price risks, foreign exchange risk and hedging "
                 "thereof, in terms of SEBI master circular for compliance "
                 "with the provisions of the SEBI Listing Regulations by "
                 "listed entities, are not applicable/required."),
        note=("Corporate Governance Report. 'has no... hedging exposures' is "
              "an explicit nil. FLAG FOR THE REVIEWER: 'does not deal in "
              "commodities' sits awkwardly beside a company whose largest "
              "cost line is bought-in freight -- the company means it does "
              "not TRADE commodities. The hedging nil is what this row "
              "records; the trading claim is not relied on."),
    ),
    dict(
        isin="INE111A01025", tags=["input:freight_diesel"],
        page="134", hedge_ratio=0.0,
        excerpt=("The Company does not deal in commodity(ies) and hence "
                 "disclosure relating to commodity price risks and commodity "
                 "hedging activities does not apply to the Company."),
        note=("Corporate Governance Report. Explicit on the commodity limb. "
              "Same 'does not deal in' phrasing as Mahindra Logistics and the "
              "same reading applies: the nil on commodity hedging is what is "
              "recorded."),
    ),
]

# ------------------------------------------------------------- UNSOURCED
ABSENT = [
    dict(
        isin="INE035D01020", tags=["input:base_oil",
                                   "input:crude_derivative_petchem"],
        code="NO_HEDGING_STATEMENT",
        reason=("The Corporate Governance Report's hedging entry (p95) is a "
                "cross-reference only: 'HEDGING ACTIVITIES The details are "
                "provided in Notes to Financial Statements.' The financial "
                "risk note lists '(c) Commodity risk' as a category and its "
                "body (p181) describes PROCUREMENT -- 'The Company tries to "
                "enter into long term supply contracts with regular suppliers "
                "and at times buys base oils on spot basis' -- with no "
                "statement about hedging or derivatives either way. The "
                "derivative tables in the same note (p179) cover foreign "
                "exchange only. A procurement description is not a hedge "
                "ratio and is not read as zero."),
    ),
    dict(
        isin="INE366I01010", tags=["input:freight_diesel"],
        code="FX_LIMB_ONLY",
        reason=("The LODR entry (p147) is headed 'Commodity price risk or "
                "foreign exchange risk and hedging activities' and its body "
                "answers only the FX limb: 'The Company had no material "
                "foreign exchange transactions during the year and hence the "
                "Company has not opted for hedging.' It then states that 'no "
                "disclosure is warranted in terms of SEBI circular "
                "SEBI/HO/CFD/CMD1/CIR/P/2018/0000000141' -- which IS the "
                "commodity circular, so this arguably implies nothing to "
                "report on commodities. JUDGEMENT CALL, made conservatively: "
                "an implication drawn from a materiality threshold is not a "
                "statement that the company does not hedge diesel, and diesel "
                "is 27.6% of its total cost. A reviewer may overrule this on "
                "the text quoted here."),
    ),
    dict(
        isin="INE233B01017", tags=["input:intermediated_air_capacity"],
        code="PASS_THROUGH_NOT_HEDGE",
        reason=("The LODR entry (p144) is substantive but describes the wrong "
                "parameter: 'Your Company has an internal hedging mechanism "
                "termed as Fuel Surcharge Mechanism for passing "
                "increase/decrease in ATF cost to its customers.' The company "
                "calls it hedging; it is a PASS-THROUGH to customers, which "
                "belongs in pass_through_curve, not hedge_ratio. Recording it "
                "as a hedge would double-count it against the pass-through "
                "term in the same formula. No statement is made about "
                "commodity derivatives either way, so hedge_ratio is unknown, "
                "not zero. SEE THE REPORT: this is the strongest "
                "filing-sourced PASS-THROUGH lead found so far."),
    ),
    dict(
        isin="INE688A01022", tags=["input:bought_in_freight"],
        code="FX_LIMB_ONLY",
        reason=("The LODR entry (p138) reads in full: 'The Company did not "
                "hedge foreign exchange risk as the exposure is not "
                "material.' Foreign exchange only. The commodity limb of the "
                "heading is not answered."),
    ),
    dict(
        isin="INE586V01016", tags=["input:bought_in_freight"],
        code="NO_DISCLOSURE_FOUND",
        reason=("No commodity-risk or hedging text of any kind was found in "
                "the 391-page FY2026 annual report's text layer -- not a "
                "heading, not a nil return. Either the LODR entry is absent "
                "or it did not extract. Absence in the text layer is not the "
                "same as absence in the document, and this one is recorded as "
                "unresolved rather than as a nil."),
    ),
]


def load(isin):
    d = FILINGS / isin
    meta = json.loads((d / "source.json").read_text())
    with gzip.open(d / "pages.json.gz", "rt", encoding="utf-8") as fh:
        pages = json.load(fh)
    doc = SourceDocument(url=meta["source_url"],
                         retrieved_at=datetime.fromisoformat(meta["retrieved_at"]),
                         media_type="application/pdf", sha256=meta["sha256"],
                         pages=tuple(pages))
    return doc, meta


def main() -> None:
    filed, absent, rejected, proposals = [], [], [], []

    for f in SOURCED:
        doc, meta = load(f["isin"])
        res = check_excerpt(doc, excerpt=f["excerpt"],
                            source_page=str(f["page"]))
        if not res.ok:
            rejected.append((meta["ticker"], f"VERBATIM_{res.reason}"))
            continue
        if not res.page_verified:
            rejected.append((meta["ticker"], "PAGE_NOT_VERIFIED"))
            continue
        if not 0.0 <= float(f["hedge_ratio"]) <= 1.0:
            rejected.append((meta["ticker"], "HEDGE_RATIO_OUT_OF_RANGE"))
            continue
        eff_from, eff_to = FY_WINDOW[int(meta["fy"])]
        for tag in f["tags"]:
            row = {
                "company_isin": f["isin"], "ticker": meta["ticker"],
                "exposure_tag": tag, "modifier_kind": "HEDGE",
                "hedge_ratio": f"{float(f['hedge_ratio']):.4f}",
                "measurement": "FILED",
                "effective_from": eff_from, "effective_to": eff_to,
                "source_url": meta["source_url"],
                "source_page": str(f["page"]),
                "verbatim_excerpt": normalize_whitespace(f["excerpt"]),
                "note": f["note"],
            }
            filed.append(row)
            proposals.append({
                "company_isin": f["isin"], "applies_to_tag": tag,
                "modifier_kind": "HEDGE",
                "parameters": {
                    "hedge_ratio": float(f["hedge_ratio"]),
                    "measurement": "FILED",
                    "_excerpt": normalize_whitespace(f["excerpt"]),
                    "_source_page": str(f["page"]),
                    "_note": f["note"],
                },
                "effective_from": eff_from, "effective_to": eff_to,
                "source_url": meta["source_url"],
                "as_of_date": eff_to,
                "document_sha256": meta["sha256"],
                "confidence": 0.9,
                "created_by": "ingest:ripple_bootstrap/source_hedge_ratio.py@v1",
            })

    for a in ABSENT:
        doc, meta = load(a["isin"])
        for tag in a["tags"]:
            absent.append({"company_isin": a["isin"], "ticker": meta["ticker"],
                           "exposure_tag": tag,
                           "reason": f"{a['code']}: {a['reason']}"})

    for ticker, why in rejected:
        absent.append({"company_isin": "", "ticker": ticker,
                       "exposure_tag": "",
                       "reason": f"ROW_REJECTED_BY_GATE: {why}"})

    with open(OUT_FILED, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, list(filed[0]) if filed else ["company_isin"])
        w.writeheader()
        w.writerows(filed)
    with open(OUT_ABSENT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, ["company_isin", "ticker", "exposure_tag",
                                "reason"])
        w.writeheader()
        w.writerows(absent)
    OUT_JSON.write_text(json.dumps(proposals, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    print(f"FILED rows      : {len(filed)}  -> {OUT_FILED.relative_to(REPO)}")
    print(f"absent rows     : {len(absent)} -> {OUT_ABSENT.relative_to(REPO)}")
    print(f"rejected by gate: {len(rejected)}")
    for t, why in rejected:
        print(f"   REJECTED {t}: {why}")
    print(f"\nproposals ready for a reviewed write path: {len(proposals)} "
          f"-> {OUT_JSON.relative_to(REPO)}")
    print("NOT WRITTEN to company_modifier: no reviewed write path exists "
          "(defect D1).")

    today = date.today().isoformat()
    live = [r for r in filed if r["effective_from"] <= today <= r["effective_to"]]
    print(f"\nof the {len(filed)} FILED rows, {len(live)} would resolve for a "
          f"shock dated today ({today}).")
    for r in filed:
        if r not in live:
            print(f"   EXPIRED {r['ticker']:<13}{r['exposure_tag']:<34}"
                  f"{r['effective_from']} .. {r['effective_to']}")


if __name__ == "__main__":
    main()
