"""QUALITATIVE-TAG YIELD PROBE v2 — the company-count the plan rests on.

READ ONLY. Reads data/filings/*/pages.json.gz. Writes nothing to the repo.

WHAT CHANGED FROM v1 (backend/scripts/probes/qualitative_tag_yield.py)

  1. THE ACRONYM RULE, APPLIED RETROACTIVELY. v1's own finding: no bare 2-4
     letter uppercase token may be a standalone alternative. `ATF` matched a
     CSR foundation, `SMP` matched "Senior Management Personnel". Every such
     alternative is moved to BARE_ACRONYMS below and is OFF by default;
     `--with-acronyms` re-enables them so the delta can be measured.
  2. ONE LINE PER (company, leaf) PAIR, not 4 per leaf. v1 printed a sample;
     the reach question needs the whole population classified.
  3. CRUDE-REACHABLE LEAVES are marked, so "usable at a leaf a crude shock
     actually reaches" is separable from "usable anywhere".

OUTPUT is a TSV of every (company, leaf) pair for hand classification, plus
the counts. The classification itself is NOT done here -- a script that
classified its own hits would be the thing this whole programme exists to
refuse.
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

MIN_EXCERPT_CHARS = 24

SELF = re.compile(
    r"\b(?:the\s+Compan(?:y|ies)|our|we|us|the\s+Group|the\s+Corporation)\b",
    re.IGNORECASE)

MACRO = re.compile(
    r"\b(?:global(?:ly)?|world|international market|geopolit|OPEC|Brent|"
    r"macro-?economic|the Indian economy|GDP|the country's)\b", re.IGNORECASE)

# THE LEAVES A CRUDE SHOCK ACTUALLY REACHES. The `input:crude:*` group of
# config/exposure_tags.yaml plus the three crude revenue-realisation leaves.
# Metals, agri, fx and rate leaves are reached by OTHER shock variables and
# are excluded from the crude reach number.
CRUDE_REACHABLE = frozenset({
    "input:crude_direct", "input:crude_derivative_petchem",
    "input:crude_derivative_rubber", "input:crude_derivative_bitumen",
    "input:atf", "input:fuel_furnace_pet_coke", "input:freight_diesel",
    "input:base_oil", "input:bought_in_freight",
    "input:intermediated_air_capacity",
    "revenue:crude_realization", "revenue:refining_gross_margin",
    "revenue:marketing_margin_retail_fuel",
})

# --- patterns SAFE under the acronym rule -----------------------------------
PATTERNS: dict[str, list[str]] = {
    "input:crude_direct": [
        r"crude oil (?:is|as)?\s*(?:a|the|our)?\s*(?:principal|key|main|primary)?\s*(?:raw material|feedstock|input)",
        r"(?:process|refine|purchase|procure|import)(?:s|ed|ing)?\s+crude oil",
        r"crude (?:oil )?throughput",
    ],
    "input:crude_derivative_petchem": [
        r"\bnaphtha\b", r"\bpropylene\b", r"\bethylene\b", r"\bpolymer(?:s)?\b",
        r"\bpolyester\b", r"\bmonoethylene glycol\b", r"\bresin(?:s)?\b",
        r"\btitanium dioxide\b", r"\bsolvent(?:s)?\b", r"\bparaxylene\b",
        r"\bpolyol(?:s)?\b",
    ],
    "input:crude_derivative_rubber": [
        r"\bsynthetic rubber\b", r"\bcarbon black\b", r"\bstyrene butadiene\b",
        r"\brubber chemical(?:s)?\b", r"\btyre cord\b", r"\bnylon tyre cord\b",
    ],
    "input:crude_derivative_bitumen": [r"\bbitumen\b", r"\basphalt\b"],
    "input:atf": [r"\baviation turbine fuel\b", r"\bjet fuel\b"],
    "input:fuel_furnace_pet_coke": [
        r"\bpet ?coke\b", r"\bpetroleum coke\b", r"\bfurnace oil\b",
        r"\blight diesel oil\b",
    ],
    "input:freight_diesel": [
        r"\bdiesel\b", r"\bhigh speed diesel\b", r"fuel (?:cost|expense|consumption)",
    ],
    "input:base_oil": [r"\bbase oil\b", r"\bbase stock\b", r"\blube base\b"],
    "input:bought_in_freight": [
        r"(?:freight|transport(?:ation)?|carriage)\s+(?:and\s+\w+\s+)?"
        r"(?:cost|expense|charges|outward|inward)",
        r"\b(?:hired|bought[- ]out|outsourced|third[- ]party)\s+"
        r"(?:vehicle|truck|transport|fleet|carrier)",
        r"\blorry hire\b", r"\bvehicle hire\b",
    ],
    "input:intermediated_air_capacity": [
        r"\bcharter(?:ed|ing)?\s+(?:aircraft|freighter|flight)",
        r"\baircraft\s+charter\b", r"\bbelly (?:space|cargo|capacity)\b",
        r"\bcommercial airlift\b", r"\bair freight (?:cost|charges|capacity)\b",
    ],
    "input:steel_flat": [
        r"\b(?:hot|cold)[- ]rolled\b", r"\bflat steel\b",
        r"\bsteel sheet(?:s)?\b", r"\bgalvanised steel\b",
    ],
    "input:steel_long": [
        r"\blong steel\b", r"\bsteel bar(?:s)?\b",
        r"\breinforcement steel\b", r"\bwire rod(?:s)?\b",
    ],
    "input:aluminium": [r"\baluminium\b", r"\baluminum\b"],
    "input:copper": [r"\bcopper\b"],
    "input:palm_oil": [
        r"\bpalm oil\b", r"\bpalm (?:fatty acid|kernel|stearin)\b",
    ],
    "input:wheat": [r"\bwheat\b", r"\bmaida\b", r"\batta\b", r"\bwheat flour\b"],
    "input:sugar": [r"\bsugar\b"],
    "input:milk": [r"\bmilk\b", r"\bskimmed milk powder\b"],
    "revenue:crude_realization": [
        r"crude (?:oil )?realis?ation", r"\bprice realis?ation.{0,30}crude\b",
    ],
    "revenue:refining_gross_margin": [
        r"\bgross refining margin\b", r"\brefining margin\b",
    ],
    "revenue:marketing_margin_retail_fuel": [
        r"\bmarketing margin\b", r"\bretail (?:fuel|selling) price\b",
    ],
    "revenue:gas_realization_apm": [
        r"\badministered price(?:d)? (?:mechanism|gas)\b",
    ],
    "revenue:gas_realization_market": [
        r"\bcity gas distribution\b", r"\bmarket[- ]priced gas\b",
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
    ],
    "rate:floating_debt_share": [
        r"\bfloating[- ]rate\b", r"\bvariable[- ]rate borrowing",
        r"\brepo[- ]linked\b", r"\bbenchmark[- ]linked rate\b",
    ],
    "rate:nim_asset_sensitivity": [
        r"\bnet interest margin\b", r"\binterest rate sensitivit(?:y|ies)\b",
    ],
}

# --- REMOVED BY THE ACRONYM RULE. Off unless --with-acronyms. ---------------
# Every one of these is a bare 2-4 letter uppercase token. v1 shipped them and
# `ATF` / `SMP` produced 100% false hits on the leaves that carried them.
BARE_ACRONYMS: dict[str, list[str]] = {
    "input:atf": [r"\bATF\b"],
    "input:milk": [r"\bSMP\b"],
    "input:palm_oil": [r"\bCPO\b"],
    "input:freight_diesel": [r"\bHSD\b"],
    "input:fuel_furnace_pet_coke": [r"\bLDO\b"],
    "input:crude_derivative_petchem": [r"\bPTA\b", r"\bMEG\b", r"\bBOPP\b",
                                       r"\bBOPET\b"],
    "input:crude_derivative_rubber": [r"\bSBR\b", r"\bPBR\b"],
    "input:steel_flat": [r"\bHR coil(?:s)?\b", r"\bCR coil(?:s)?\b"],
    "input:steel_long": [r"\bTMT\b"],
    "revenue:refining_gross_margin": [r"\bGRM\b"],
    "revenue:gas_realization_apm": [r"\bAPM (?:gas|price)\b"],
    "revenue:gas_realization_market": [r"\bCGD\b"],
    "fx:usd_debt_share": [r"\bECB\b"],
    "rate:floating_debt_share": [r"\bMCLR\b"],
    "rate:nim_asset_sensitivity": [r"\bNIM\b"],
}

PASS_THROUGH_PATTERNS: dict[str, list[str]] = {
    "MITIGATED": [
        r"price[- ]adjustment (?:clause|mechanism|formula)",
        r"\bprice variation clause\b", r"\bescalation clause\b",
        r"\b(?:quarterly|monthly|periodic(?:ally)?)[^.]{0,40}\bre-?pric",
        r"\bpass(?:ed|es|ing)?[- ]?(?:on|through)\b[^.]{0,60}\bcustomer",
        r"raw material[^.]{0,60}\b(?:escalation|pass(?:ed|es|ing)?[- ]?(?:on|through))",
        r"\b(?:linked|indexed) to (?:raw material|input) (?:price|cost)",
        r"\bfuel surcharge\b", r"\bfuel adjustment (?:factor|charge)\b",
        r"\bfuel (?:and power )?cost (?:adjustment|pass[- ]through)\b",
    ],
    # The half v1 was not looking for, and the more decision-relevant one:
    # the company telling its shareholders it CANNOT reprice.
    "UNMITIGATED": [
        r"\b(?:unable|inability|may not be able|cannot|could not)\b[^.]{0,80}"
        r"\bpass(?:ed|es|ing)?[- ]?(?:on|through)\b",
        r"\bability to pass on\b",
        r"\bprofitability[^.]{0,60}\bsensitive to\b[^.]{0,60}"
        r"\b(?:raw material|input|commodity)\b",
        r"\b(?:margins?|profitability)[^.]{0,50}\b(?:compress|erode|squeeze)"
        r"[^.]{0,60}\b(?:raw material|input|commodity)\b",
        r"\bcannot (?:fully |immediately )?(?:recover|recoup)\b",
    ],
}

_SENT = re.compile(r"(?<=[.!?])\s+")

# --- CLAIM STRENGTH ---------------------------------------------------------
# v2's first run ranked candidates by SENTENCE LENGTH and surfaced boilerplate
# tables over the crisp disclosures v1 had found by accident. Length is not
# evidence. This scorer ranks by whether the sentence ASSERTS A PROCUREMENT OR
# COST RELATION, which is what a reviewer is looking for.
#
# It ranks. It does NOT classify, and it never decides whether a row may be
# written -- that is the reviewer's, and a scorer that decided would be the
# thing this programme exists to refuse.
_CONSUMES = re.compile(
    r"\b(?:purchas\w*|procur\w*|consum\w*|buy\w*|bought|import\w*|sourc\w*|"
    r"requir\w*|depend\w*|relian\w*|rel(?:y|ies|ied)|uses?|using|used|"
    r"input\w*|feedstock)\b", re.IGNORECASE)
_COSTRISK = re.compile(
    r"\b(?:raw material|input cost|commodity price|cost of material|"
    r"price risk|exposure|exposed|volatilit\w*|cost(?:s)? of|"
    r"principal|key|major)\b", re.IGNORECASE)
_BOILER = re.compile(
    r"\b(?:DIN|CIN|Private Limited|Pvt\.? Ltd|Whole-?time Director|"
    r"paid-?up|authorised|subscribed|Sirketi|Anonim|basis points|"
    r"as at March 31|for the year ended|Notes forming part)\b", re.IGNORECASE)
_DIGITS = re.compile(r"\d")


def claim_strength(sentence: str) -> int:
    score = 0
    if _CONSUMES.search(sentence):
        score += 3
    if _COSTRISK.search(sentence):
        score += 3
    if _BOILER.search(sentence):
        score -= 4
    # A sentence that is mostly figures is a table row, not a claim.
    density = len(_DIGITS.findall(sentence)) / max(len(sentence), 1)
    if density > 0.08:
        score -= 3
    # Mild preference for a readable length once the above has decided.
    if 60 <= len(sentence) <= 320:
        score += 1
    return score


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


def sweep(corpus, patterns):
    compiled = {k: [re.compile(p, re.IGNORECASE) for p in v]
                for k, v in patterns.items()}
    # (leaf, ticker) -> (score, pageno, sentence) -- the STRONGEST CLAIM wins.
    best: dict[tuple[str, str], tuple[int, int, str]] = {}
    npairs = defaultdict(int)
    for meta, pages in corpus:
        ticker = meta["ticker"]
        for pageno, text in enumerate(pages, start=1):
            if not text or len(text) < 40:
                continue
            for sent in sentences(text):
                if not SELF.search(sent) or MACRO.search(sent):
                    continue
                for key, pats in compiled.items():
                    if not any(p.search(sent) for p in pats):
                        continue
                    npairs[key] += 1
                    score = claim_strength(sent)
                    cur = best.get((key, ticker))
                    if cur is None or score > cur[0]:
                        best[(key, ticker)] = (score, pageno, sent)
    return best, npairs


def main() -> None:
    with_acronyms = "--with-acronyms" in sys.argv
    patterns = {k: list(v) for k, v in PATTERNS.items()}
    if with_acronyms:
        for k, v in BARE_ACRONYMS.items():
            patterns.setdefault(k, []).extend(v)

    corpus = load_corpus()
    n = len(corpus)
    best, _ = sweep(corpus, patterns)

    label = "WITH bare acronyms" if with_acronyms else "acronym rule APPLIED"
    print(f"# corpus {n} reports | {label}")
    print(f"# (company, leaf) pairs: {len(best)}")
    print(f"# distinct companies with >=1 hit: "
          f"{len({t for _, t in best})} of {n}")
    crude = {t for (k, t) in best if k in CRUDE_REACHABLE}
    print(f"# distinct companies with >=1 CRUDE-REACHABLE hit: "
          f"{len(crude)} of {n}")

    print("\nCRUDE\tSCORE\tLEAF\tTICKER\tPAGE\tSENTENCE")
    for (key, ticker), (score, pageno, sent) in sorted(best.items()):
        flag = "C" if key in CRUDE_REACHABLE else "-"
        print(f"{flag}\t{score}\t{key}\t{ticker}\t{pageno}\t{sent}")

    pbest, _ = sweep(corpus, PASS_THROUGH_PATTERNS)
    print(f"\n\n# PASS_THROUGH pairs: {len(pbest)} | "
          f"distinct companies: {len({t for _, t in pbest})}")
    for state in ("MITIGATED", "UNMITIGATED"):
        members = sorted(t for (k, t) in pbest if k == state)
        print(f"#   {state}: {len(members)} companies -- {members}")
    print("\nSTATE\tSCORE\tTICKER\tPAGE\tSENTENCE")
    for (key, ticker), (score, pageno, sent) in sorted(pbest.items()):
        print(f"{key}\t{score}\t{ticker}\t{pageno}\t{sent}")


if __name__ == "__main__":
    main()
