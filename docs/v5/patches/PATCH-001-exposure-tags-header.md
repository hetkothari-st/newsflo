# PATCH-001 — the leaf-authoring rule, into `config/exposure_tags.yaml`

**Status:** PATCH, NOT APPLIED. `backend/config/exposure_tags.yaml` is untouched.
**Applied by:** a human, as a review of that file — which is what its own header
requires and what this patch is careful not to route around.
**Two parts:** §1 header text (no behaviour change). §2 a leaf change that needs a
migration and a decision.

---

## 1. HEADER INSERT — no behaviour change

Insert immediately after the existing `ADDING A LEAF:` paragraph, before the
`IF YOU CAME HERE FROM THE ADDENDUM` divider.

```yaml
# ---------------------------------------------------------------------------
# BEFORE YOU ADD A LEAF — TWO RULES, BOTH LEARNED THE EXPENSIVE WAY
# ---------------------------------------------------------------------------
# RULE 1. NAME THE LEAF IN THE BUYER'S VOCABULARY, NOT THE PRODUCER'S.
#
# A leaf is matched against the prose of the company that CARRIES the exposure.
# That company is normally the BUYER, and buyers do not use their suppliers'
# words. Measured 2026-08-17 over 11 auto-component annual reports (3,929
# pages), for a sector where steel is the core input:
#
#     input:steel_flat   ("hot-rolled", "cold-rolled", "flat steel",
#                         "steel sheet", "galvanised steel")      1 of 11
#     input:steel_long   ("TMT", "steel bar", "wire rod")         0 of 11
#     the bare word "steel"                                       7 of 11
#
# Flat-versus-long is a distinction STEEL MILLS make. An auto-component maker
# writes "the Company consumes alloy steel, steel, aluminium and copper"
# (Sona BLW, FY2026 p64). Two leaves, written from the supply side, found
# almost nothing in the demand-side prose they exist to match.
#
# RULE 2. NO LEAF IS AUTHORED UNTIL IT HAS BEEN SWEPT AGAINST A CORPUS OF THE
#         COMPANIES EXPECTED TO CARRY IT.
#
# The sweep is written (backend/scripts/probes/qualitative_tag_yield_v2.py) and
# the acquisition is one script (acquire_auto_components.py). Ten filings is
# enough to tell an 80% hit rate from a 20% one. Running it costs a day and it
# would have caught BOTH failures on this list:
#
#   * input:steel_flat / input:steel_long -- TOO SPECIFIC. Two leaves covering
#     a word buyers never use.  1 of 11 and 0 of 11.
#   * input:crude_derivative_petchem -- TOO GENERIC, the mirror image. ONE leaf
#     swept by eleven words ("polymer", "resin", "solvent", "polyester", ...)
#     that appear in product descriptions, waste-disposal notes and directors'
#     biographies. 32 candidate pairs, 4 usable, 9 of them companies that
#     PRODUCE the input rather than buy it. Whole roster families score 0% on
#     it. Measured in docs/v5/MEASUREMENTS_2026-08-17.md 9.3.
#
# THE PREDICTOR, stated so it can be checked rather than felt: a leaf's hit
# rate tracks WHETHER ITS TERM IS THE WORD THE BUYER USES IN ITS OWN FILING.
# It does not track term specificity in the abstract -- base_oil (83%) and
# steel_flat (9%) are both specific, and only one is the buyer's word.
#
# A leaf that cannot be extracted is not merely low-yield. It is a leaf whose
# ledger rows can only ever come from somewhere other than a filing.
# ---------------------------------------------------------------------------
```

---

## 2. THE STEEL LEAVES — proposal, decision required

### 2.1 Recommendation: **replace both with one buyer-vocabulary leaf**

```yaml
    metals:
      # WAS: steel_flat, steel_long. Replaced 2026-08-__ after both measured
      # 1-of-11 and 0-of-11 against an auto-component corpus (PATCH-001).
      # Buyers write "steel". The flat/long split is the mill's distinction and
      # belongs on the EDGE, not on the leaf -- an edge from STEEL_FLAT can
      # point at industry:auto_component_makers carrying `input:steel` without
      # the leaf having to encode which mill product it was.
      steel:                      # steel in any form -> autos, capital goods,
                                  # appliances, construction, white goods
      aluminium:
      copper:
```

**Why the edge, not the leaf.** `mechanism_edge` already carries `from_node`, so a
flat-steel shock and a long-steel shock are **different edges** that may both point at
`input:steel`. The distinction survives where it is verifiable (the shock variable, a
published price series) and is dropped where it is not (the buyer's prose). This is
the same move as `role`: put the discrimination on the edge, where a human authors it.

`config/discovery.yaml` keeps **both** `STEEL_FLAT` and `STEEL_LONG` as shock
variables. Nothing about the shock side changes.

### 2.2 What it does to the existing tag — **nothing is stranded**

| | |
|---|---|
| `company_exposure` rows on `input:steel_flat` | **0** |
| `company_exposure` rows on `input:steel_long` | **0** |
| `mechanism_edge` rows on either | **0** (both are among the 26 orphan tags, `MEASUREMENTS` §3) |
| `valid_exposure_tag` rows | 2, to be replaced by 1 |

**Both leaves are orphans with zero ledger rows, so this is a rename with no
migration of data — only of vocabulary.** It will not be true later: the moment one
row exists, replacing the leaf becomes a ledger migration through the review path,
because `company_exposure` has no reviewed UPDATE path for `exposure_tag` and the 0012
trigger guards that column. **Now is materially cheaper than after the first steel
manifest.**

### 2.3 Mechanics

1. Edit `config/exposure_tags.yaml` as above (a human, per its header).
2. New migration — **claim the number in `docs/v5/MIGRATION_CLAIMS.md` first**
   (0017 was next as of 2026-08-17; coordinator-write-only). It must:
   `DELETE FROM valid_exposure_tag WHERE exposure_tag IN ('input:steel_flat',
   'input:steel_long')` and re-run the loader that populates it from the YAML —
   0016 is the precedent for exactly this resync.
3. Update `qualitative_tag_yield_v2.py::PATTERNS` — merge the two entries into
   `input:steel` and **keep the generic `\bsteel\b`**, which is what worked.
4. Re-sweep the 11 auto-component filings. Expect ~6 of 11 usable, per
   `MEASUREMENTS` §10.

### 2.4 The alternative, and why it is worse

Keep both leaves and have the extractor map generic "steel" to whichever the edge
names. **Rejected:** it puts a silent inference between the filing sentence and the
stored row — the company said "steel" and the ledger would say "flat steel", which is
a claim the filing does not make. That is the fabrication guard's shape even though no
number is involved.

### 2.5 What this does NOT propose

`input:crude_derivative_petchem` is the mirror failure and **needs splitting, not
merging** — candidates named in `MEASUREMENTS` §9.6 (`input:polyester_chain`,
`input:styrenics`, `input:coating_resins`, `input:packaging_polymer`). **It is not
patched here** because, unlike steel, it has **live ledger rows** (2 of the 11
`company_exposure` rows, CEAT and Savita) and 2 of the 2 `mechanism_edge` rows. That
is a ledger migration through the review path, not a rename, and it needs its own
ticket.
