"""QUALITATIVE-TAG YIELD PROBE — §C.2 of docs/v5/QUALITATIVE_TIER_DESIGN.md

READ ONLY. Reads data/filings/*/pages.json.gz and writes nothing to the repo.

QUESTION: for each of the 28 vocabulary leaves, how many of the 52 indexed
annual reports contain a COMPANY-NAMED sentence naming that input, where
"company-named" means the sentence carries a first-person / possessive
self-reference ("the Company", "our", "we", "the Group") -- not a macro
paragraph about world markets.

Directly comparable to the sized route's measured 9 of 52.

TWO COUNTS PER LEAF, and the difference is the point:
  RAW   the leaf's keyword appears in a sentence anywhere in the report.
        Includes macro commentary. NOT a claim.
  SELF  the same sentence also carries a self-reference. This is the
        candidate for a FILED_QUALITATIVE exposure row.

EVERY reported sentence is then re-checked through the deployed gate
(app.ingest.filings.verbatim.contains_verbatim + the cited-page check), so a
sentence defeated by a pypdf glyph split (the CEAT "T he Company" artefact)
is counted as GATE_FAIL and NOT as a hit. That is the same failure that cost
the last session a working excerpt.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FILINGS = REPO / "data" / "filings"
sys.path.insert(0, str(REPO / "backend"))

from app.ingest.filings.documents import normalize_whitespace  # noqa: E402


def contains_verbatim(document_text: str, excerpt: str) -> bool:
    needle = normalize_whitespace(excerpt)
    if not needle:
        return False
    return needle in normalize_whitespace(document_text)


MIN_EXCERPT_CHARS = 24          # verbatim.MIN_EXCERPT_CHARS

# A sentence is a claim about THIS company only when it says so. Deliberately
# narrow: "India imports 85% of its crude" is in every annual report and is
# not an exposure.
SELF = re.compile(
    r"\b(?:the\s+Compan(?:y|ies)|our|we|us|the\s+Group|the\s+Corporation)\b",
    re.IGNORECASE)

# Sentences that are macro commentary even when they carry "our". Removing
# these matters more than adding patterns: they are the noise the whole
# qualitative tier is accused of being.
MACRO = re.compile(
    r"\b(?:global(?:ly)?|world|international market|geopolit|OPEC|Brent|"
    r"macro-?economic|the Indian economy|GDP|the country's)\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# LEAF -> PATTERNS. Hand-authored, conservative. A pattern that would match a
# generic word ("fuel", "steel") on its own is anchored to a consumption or
# procurement context, because the count this produces is the number the whole
# plan rests on and a loose pattern inflates it.
# ---------------------------------------------------------------------------
PATTERNS: dict[str, list[str]] = {
    "input:crude_direct": [
        r"crude oil (?:is|as)?\s*(?:a|the|our)?\s*(?:principal|key|main|primary)?\s*(?:raw material|feedstock|input)",
        r"(?:process|refine|purchase|procure|import)(?:s|ed|ing)?\s+crude oil",
        r"crude (?:oil )?throughput",
    ],
    "input:crude_derivative_petchem": [
        r"\bnaphtha\b", r"\bpropylene\b", r"\bethylene\b", r"\bpolymer(?:s)?\b",
        r"\bpolyester\b", r"\bPTA\b", r"\bMEG\b", r"\bmonoethylene glycol\b",
        r"\bBOPP\b", r"\bBOPET\b", r"\bresin(?:s)?\b", r"\btitanium dioxide\b",
        r"\bsolvent(?:s)?\b", r"\bparaxylene\b", r"\bpolyol(?:s)?\b",
    ],
    "input:crude_derivative_rubber": [
        r"\bsynthetic rubber\b", r"\bcarbon black\b", r"\bstyrene butadiene\b",
        r"\bSBR\b", r"\bPBR\b", r"\brubber chemical(?:s)?\b",
        r"\btyre cord\b", r"\bnylon tyre cord\b",
    ],
    "input:crude_derivative_bitumen": [r"\bbitumen\b", r"\basphalt\b"],
    "input:atf": [
        r"\baviation turbine fuel\b", r"\bATF\b", r"\bjet fuel\b",
    ],
    "input:fuel_furnace_pet_coke": [
        r"\bpet ?coke\b", r"\bpetroleum coke\b", r"\bfurnace oil\b",
        r"\bLDO\b", r"\blight diesel oil\b",
    ],
    "input:freight_diesel": [
        r"\bdiesel\b", r"\bHSD\b", r"\bhigh speed diesel\b",
        r"fuel (?:cost|expense|consumption)",
    ],
    "input:base_oil": [
        r"\bbase oil\b", r"\bbase stock\b", r"\blube base\b",
    ],
    "input:bought_in_freight": [
        r"(?:freight|transport(?:ation)?|carriage)\s+(?:and\s+\w+\s+)?"
        r"(?:cost|expense|charges|outward|inward)",
        r"\b(?:hired|bought[- ]out|outsourced|third[- ]party)\s+"
        r"(?:vehicle|truck|transport|fleet|carrier)",
        r"\blorry hire\b", r"\bvehicle hire\b",
    ],
    # NOTE: a bare \bchartered\b matched "Chartered Accountants" in all 52
    # reports on the first run. Anchored to aircraft/airlift only.
    "input:intermediated_air_capacity": [
        r"\bcharter(?:ed|ing)?\s+(?:aircraft|freighter|flight)",
        r"\baircraft\s+charter\b",
        r"\bbelly (?:space|cargo|capacity)\b", r"\bcommercial airlift\b",
        r"\bair freight (?:cost|charges|capacity)\b",
    ],
    "input:steel_flat": [
        r"\b(?:hot|cold)[- ]rolled\b", r"\bHR coil(?:s)?\b", r"\bCR coil(?:s)?\b",
        r"\bflat steel\b", r"\bsteel sheet(?:s)?\b", r"\bgalvanised steel\b",
    ],
    "input:steel_long": [
        r"\bTMT\b", r"\blong steel\b", r"\bsteel bar(?:s)?\b",
        r"\breinforcement steel\b", r"\bwire rod(?:s)?\b",
    ],
    "input:aluminium": [r"\baluminium\b", r"\baluminum\b"],
    "input:copper": [r"\bcopper\b"],
    "input:palm_oil": [
        r"\bpalm oil\b", r"\bpalm (?:fatty acid|kernel|stearin)\b", r"\bCPO\b",
    ],
    "input:wheat": [r"\bwheat\b", r"\bmaida\b", r"\batta\b", r"\bwheat flour\b"],
    "input:sugar": [r"\bsugar\b"],
    "input:milk": [r"\bmilk\b", r"\bskimmed milk powder\b", r"\bSMP\b"],
    "revenue:crude_realization": [
        r"crude (?:oil )?realis?ation", r"\bprice realis?ation.{0,30}crude\b",
    ],
    "revenue:refining_gross_margin": [
        r"\bgross refining margin\b", r"\bGRM\b", r"\brefining margin\b",
    ],
    "revenue:marketing_margin_retail_fuel": [
        r"\bmarketing margin\b", r"\bretail (?:fuel|selling) price\b",
    ],
    "revenue:gas_realization_apm": [
        r"\bAPM (?:gas|price)\b", r"\badministered price(?:d)? (?:mechanism|gas)\b",
    ],
    "revenue:gas_realization_market": [
        r"\bcity gas distribution\b", r"\bCGD\b", r"\bmarket[- ]priced gas\b",
    ],
    "fx:usd_revenue_share": [
        r"(?:revenue|export(?:s)?|sales|billing(?:s)?)[^.]{0,60}\b(?:denominated in|billed in|in)\s+(?:US ?D|USD|United States [Dd]ollar|foreign currenc)",
        r"\bexport(?:s)?\b[^.]{0,40}\b(?:USD|US ?\$|foreign currency)\b",
    ],
    "fx:usd_cost_share": [
        r"(?:import(?:s|ed)?|purchase(?:s|d)?)[^.]{0,60}\b(?:denominated in|in)\s+(?:US ?D|USD|foreign currenc)",
        r"\bimported raw material(?:s)?\b",
    ],
    "fx:usd_debt_share": [
        r"\b(?:foreign currency|USD|external commercial)\s+"
        r"(?:borrowing(?:s)?|loan(?:s)?|debt|term loan)\b",
        r"\bECB\b",
    ],
    "rate:floating_debt_share": [
        r"\bfloating[- ]rate\b", r"\bvariable[- ]rate borrowing",
        r"\bMCLR\b", r"\brepo[- ]linked\b", r"\bbenchmark[- ]linked rate\b",
    ],
    "rate:nim_asset_sensitivity": [
        r"\bnet interest margin\b", r"\bNIM\b",
        r"\binterest rate sensitivit(?:y|ies)\b",
    ],
}

# ---------------------------------------------------------------------------
# The qualitative PASS_THROUGH sweep (§F.3.2). A recovery MECHANISM stated in
# prose with no number. This is what separates two companies in one section.
# ---------------------------------------------------------------------------
PASS_THROUGH_PATTERNS: dict[str, list[str]] = {
    "PRICE_ADJUSTMENT_CLAUSE": [
        r"price[- ]adjustment (?:clause|mechanism|formula)",
        r"\bprice variation clause\b",
        r"\bescalation clause\b",
        r"\b(?:quarterly|monthly|periodic(?:ally)?)[^.]{0,40}\bre-?pric",
        r"\bpass(?:ed|es|ing)?[- ]?(?:on|through)\b[^.]{0,60}\bcustomer",
    ],
    "RM_ESCALATION": [
        r"raw material[^.]{0,60}\b(?:escalation|pass(?:ed|es|ing)?[- ]?(?:on|through))",
        r"\b(?:linked|indexed) to (?:raw material|input) (?:price|cost)",
        r"\bcost[- ]plus\b",
    ],
    "FUEL_SURCHARGE": [
        r"\bfuel surcharge\b",
        r"\bFuel Surcharge Mechanism\b",
        r"\bfuel adjustment (?:factor|charge)\b",
    ],
    "REGULATED_TARIFF_PASS": [
        r"\btariff (?:order|revision)\b[^.]{0,60}\b(?:fuel|input) cost",
        r"\bfuel (?:and power )?cost (?:adjustment|pass[- ]through)\b",
    ],
}

_SENT = re.compile(r"(?<=[.!?])\s+")


def sentences(page_text: str):
    for raw in _SENT.split(page_text):
        s = " ".join(raw.split())
        if MIN_EXCERPT_CHARS <= len(s) <= 600:
            yield s


def load_corpus():
    out = []
    for d in sorted(FILINGS.iterdir()):
        if not d.is_dir():
            continue
        src, gz = d / "source.json", d / "pages.json.gz"
        if not (src.exists() and gz.exists()):
            continue
        meta = json.loads(src.read_text(encoding="utf-8"))
        with gzip.open(gz, "rt", encoding="utf-8") as fh:
            pages = json.load(fh)
        out.append((meta, pages))
    return out


def sweep(corpus, patterns: dict[str, list[str]], *, require_self: bool):
    compiled = {k: [re.compile(p, re.IGNORECASE) for p in v]
                for k, v in patterns.items()}
    raw_hits = defaultdict(set)          # key -> {ticker}
    self_hits = defaultdict(set)
    gate_fail = defaultdict(set)
    examples = defaultdict(list)         # key -> [(ticker, page, sentence)]

    for meta, pages in corpus:
        ticker = meta["ticker"]
        full = "\n".join(pages)
        for pageno, text in enumerate(pages, start=1):
            if not text or len(text) < 40:
                continue
            for sent in sentences(text):
                for key, pats in compiled.items():
                    if not any(p.search(sent) for p in pats):
                        continue
                    raw_hits[key].add(ticker)
                    if require_self:
                        if not SELF.search(sent) or MACRO.search(sent):
                            continue
                    # THE DEPLOYED GATE, both halves.
                    if not contains_verbatim(full, sent) or \
                       not contains_verbatim(text, sent):
                        gate_fail[key].add(ticker)
                        continue
                    self_hits[key].add(ticker)
                    if len(examples[key]) < 4 and \
                       ticker not in {e[0] for e in examples[key]}:
                        examples[key].append((ticker, pageno, sent[:260]))
    return raw_hits, self_hits, gate_fail, examples


def report(title, keys, raw, hit, fail, examples, n):
    print(f"\n{'=' * 78}\n{title}  (n = {n} indexed annual reports)\n{'=' * 78}")
    print(f"{'key':42} {'RAW':>5} {'HIT':>5} {'GATEFAIL':>9}")
    print("-" * 78)
    for k in keys:
        print(f"{k:42} {len(raw.get(k, ())):5} {len(hit.get(k, ())):5} "
              f"{len(fail.get(k, ())):9}")
    print("-" * 78)
    print(f"{'leaves with >=1 company-named hit':42} "
          f"{sum(1 for k in keys if hit.get(k)):5}")
    covered = set()
    for k in keys:
        covered |= hit.get(k, set())
    print(f"{'DISTINCT COMPANIES with >=1 hit':42} {len(covered):5}  of {n}")
    return covered


def main():
    corpus = load_corpus()
    n = len(corpus)
    print(f"corpus: {n} indexed reports "
          f"({sum(len(p) for _, p in corpus)} pages total)")

    raw, hit, fail, ex = sweep(corpus, PATTERNS, require_self=True)
    covered = report("EXPOSURE LEAVES", sorted(PATTERNS), raw, hit, fail, ex, n)

    praw, phit, pfail, pex = sweep(corpus, PASS_THROUGH_PATTERNS,
                                   require_self=True)
    pcovered = report("QUALITATIVE PASS_THROUGH", sorted(PASS_THROUGH_PATTERNS),
                      praw, phit, pfail, pex, n)

    print(f"\ncompanies with BOTH an exposure hit and a pass-through hit: "
          f"{len(covered & pcovered)}")

    print(f"\n\n{'=' * 78}\nEXCERPTS — exposure leaves (gate-passing, verbatim)\n{'=' * 78}")
    for k in sorted(ex):
        print(f"\n### {k}   [{len(hit[k])} companies]")
        for ticker, pageno, sent in ex[k]:
            print(f"  - {ticker} p{pageno}: {sent}")

    print(f"\n\n{'=' * 78}\nEXCERPTS — pass-through (gate-passing, verbatim)\n{'=' * 78}")
    for k in sorted(pex):
        print(f"\n### {k}   [{len(phit[k])} companies]")
        for ticker, pageno, sent in pex[k]:
            print(f"  - {ticker} p{pageno}: {sent}")


if __name__ == "__main__":
    main()
