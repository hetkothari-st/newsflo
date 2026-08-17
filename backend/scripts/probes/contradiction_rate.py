"""CONTRADICTION RATE — does a member's own filing contradict what its
industry node would assert?

READ ONLY. Reads data/filings/*/pages.json.gz and backend/newsflo.db
(mode=ro). Writes nothing.

THE QUESTION. Under membership-only publication, a company is published
because its `official_isubgroup` puts it at a node, and the node's edge
supplies the exposure and the sign. Nobody reads the company's filing. This
measures how often that filing would have said something that changes the
answer -- which is the one case `MEMBERSHIP_CLAIM_ASSESSMENT.md` sec 5.3
calls indefensible, and it has n=1 (Goodyear).

TWO DIRECTIONS, as the owner asked:

  DISCLAIMS   the node asserts an exposure; the filing disclaims it
              ("limited exposure ... low reliance on imported raw materials")
  INVERTS     the node asserts a CONSUMER; the filing shows the company also
              PRODUCES the input (backward integration), so the sign is not
              purely negative

Candidates are surfaced by pattern and then HAND-CLASSIFIED. A script that
decided what contradicts what would be exactly the thing this programme
refuses.
"""
from __future__ import annotations

import gzip
import json
import re
import sqlite3
import sys
from pathlib import Path

import os

# `data/` and `backend/newsflo.db` are untracked and therefore MAIN-TREE ONLY --
# a worktree does not carry either. Set NEWSFLO_REPO to the main tree when
# running this from a worktree checkout.
REPO = Path(os.environ.get("NEWSFLO_REPO") or Path(__file__).resolve().parents[3])
FILINGS = REPO / "data" / "filings"
DB = REPO / "backend" / "newsflo.db"
sys.path.insert(0, str(REPO / "backend"))
if not FILINGS.exists() or not DB.exists():
    raise SystemExit(
        f"corpus or dev DB not found under {REPO}. Both are untracked and live "
        f"only in the main tree; set NEWSFLO_REPO to it.")

# --- what each isubgroup's node ASSERTS -------------------------------------
# (node, leaves the node's edges carry, side)
NODE_FOR_ISUBGROUP = {
    "Lubricants":                    ("lubricant_blenders",      ["base_oil"],            "CONSUMER"),
    "Paints":                        ("paint_makers",            ["petchem"],             "CONSUMER"),
    "Tyres & Rubber Products":       ("tyre_makers",             ["rubber", "petchem"],   "CONSUMER"),
    "Packaging":                     ("packaging_film_makers",   ["petchem"],             "CONSUMER"),
    "Plastic Products - Industrial": ("plastic_converters",      ["petchem"],             "CONSUMER"),
    "Logistics Solution Provider":   ("logistics_operators",     ["diesel", "freight"],   "CONSUMER"),
    # WITHHELD at first release (MIXED by construction) -- counted separately.
    "Specialty Chemicals":           ("specialty_chemical_makers", ["petchem"],           "BOTH"),
}
# Isubgroups in the corpus that NO crude node claims. Not a denominator.
UNCLAIMED = {"Personal Care", "Diversified FMCG", "Packaged Foods",
             "Commodity Chemicals"}

# --- the input vocabulary, per leaf group -----------------------------------
LEAF_TERMS = {
    "base_oil": r"base oil|base stock|lube base",
    "petchem":  (r"naphtha|propylene|ethylene|polymer|polyester|resin|solvent|"
                 r"paraxylene|polyol|PET\b|titanium dioxide"),
    "rubber":   r"synthetic rubber|carbon black|styrene butadiene|rubber chemical|tyre cord",
    "diesel":   r"diesel|fuel cost|fuel expense|fuel consumption",
    "freight":  r"freight|transportation cost|lorry hire|vehicle hire",
}

# --- direction 1: the filing DISCLAIMS an exposure ---------------------------
DISCLAIM = re.compile(
    r"\b(?:limited|no|not|nil|negligible|insignificant|minimal|low|without)\s+"
    r"(?:any\s+|significant\s+|material\s+)?"
    r"(?:exposure|reliance|dependence|dependency|impact|consumption|usage)"
    r"|\bdoes not\s+(?:use|consume|purchase|import|hedge|have)"
    r"|\bnot\s+(?:exposed|dependent|material)\b"
    r"|\bno\s+(?:material|significant)\s+(?:exposure|impact|risk)"
    r"|\b(?:ceased|discontinued|exited|phased out|eliminated|stopped)\b"
    r"|\bno longer\s+(?:use|uses|using|consume|consumes|purchase|purchases)"
    r"|\bfully\s+(?:hedged|passed on|passed through|recovered|offset)",
    re.IGNORECASE)

# --- direction 2: the filing shows the company PRODUCES the input ------------
PRODUCES = re.compile(
    r"\b(?:manufactur\w*|produc\w*|our own|captive|backward[- ]integrat\w*|"
    r"in[- ]house|we make|convert\w*\s+\w+\s+into)\b", re.IGNORECASE)

# The generic exposure vocabulary a DISCLAIMER uses. See the anchor-asymmetry
# note in main(): a company disclaiming an exposure rarely names the input.
GENERIC = re.compile(
    r"\b(?:raw material|input cost|commodity|imported|import of|feedstock|"
    r"fuel|energy cost|price risk|price volatilit\w*)\b", re.IGNORECASE)

SELF = re.compile(r"\b(?:the\s+Compan(?:y|ies)|our|we|us|the\s+Group)\b", re.IGNORECASE)
MACRO = re.compile(r"\b(?:global(?:ly)?|world|OPEC|Brent|the Indian economy)\b",
                   re.IGNORECASE)
_SENT = re.compile(r"(?<=[.!?])\s+")


def sentences(text: str):
    for raw in _SENT.split(text):
        s = " ".join(raw.split())
        if 24 <= len(s) <= 600:
            yield s


def main() -> None:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = {}
    for d in sorted(FILINGS.iterdir()):
        src, gz = d / "source.json", d / "pages.json.gz"
        if not (src.exists() and gz.exists()):
            continue
        meta = json.loads(src.read_text(encoding="utf-8"))
        sub = con.execute("SELECT official_isubgroup FROM companies WHERE ticker = ?",
                          (meta["ticker"],)).fetchone()
        rows[meta["ticker"]] = (meta, gz, sub[0] if sub else None)

    claimed = {t: v for t, v in rows.items()
               if v[2] in NODE_FOR_ISUBGROUP
               and NODE_FOR_ISUBGROUP[v[2]][2] != "BOTH"}
    withheld = {t: v for t, v in rows.items()
                if v[2] in NODE_FOR_ISUBGROUP
                and NODE_FOR_ISUBGROUP[v[2]][2] == "BOTH"}
    unclaimed = {t: v for t, v in rows.items() if v[2] in UNCLAIMED}

    print(f"corpus {len(rows)} | published by a crude node: {len(claimed)} "
          f"| withheld (MIXED): {len(withheld)} | no crude node: {len(unclaimed)}")
    print(f"DENOMINATOR for the contradiction rate = {len(claimed)}\n")

    hits = {"DISCLAIMS": [], "INVERTS": []}
    for ticker, (meta, gz, sub) in sorted(claimed.items()):
        node, leaves, side = NODE_FOR_ISUBGROUP[sub]
        terms = re.compile("|".join(LEAF_TERMS[l] for l in leaves), re.IGNORECASE)
        with gzip.open(gz, "rt", encoding="utf-8") as fh:
            pages = json.load(fh)
        for pageno, text in enumerate(pages, start=1):
            if not text or len(text) < 40:
                continue
            for s in sentences(text):
                if not SELF.search(s) or MACRO.search(s):
                    continue
                # ANCHOR ASYMMETRY, and it is load-bearing (found on run 1).
                # An AFFIRMATION names the input ("carbon black"). A DISCLAIMER
                # is almost always generic -- Goodyear's is "low reliance on
                # imported raw materials", which contains no leaf term at all
                # and was invisible to a leaf-anchored sweep. So the two
                # directions get different anchors: INVERTS needs the leaf
                # (a company producing SOMETHING is not an inversion), while
                # DISCLAIMS anchors on the exposure vocabulary generally.
                if DISCLAIM.search(s) and (terms.search(s) or GENERIC.search(s)):
                    hits["DISCLAIMS"].append((ticker, node, pageno, s))
                elif terms.search(s) and PRODUCES.search(s):
                    hits["INVERTS"].append((ticker, node, pageno, s))

    for kind in ("DISCLAIMS", "INVERTS"):
        seen, uniq = set(), []
        for ticker, node, pageno, s in hits[kind]:
            if ticker in seen:
                continue
            seen.add(ticker)
            uniq.append((ticker, node, pageno, s))
        print(f"\n{'=' * 76}\n{kind} candidates -- {len(seen)} companies, "
              f"{len(hits[kind])} sentences\n{'=' * 76}")
        for ticker, node, pageno, s in sorted(uniq):
            print(f"\n[{ticker}] {node} p{pageno}\n  {s[:400]}")
        print(f"\n  companies: {sorted(seen)}")


if __name__ == "__main__":
    main()
