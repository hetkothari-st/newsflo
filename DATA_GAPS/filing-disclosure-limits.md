# DATA GAPS — What annual reports actually disclose

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

---

## 14. Annual reports do not carry the raw-material breakup the ledger needs — MEASURED 2026-08-17

Gap §5 says the exposure ledger's `share_of_base` values come from "the
companies' own filings — annual reports and quarterly results (PDF/XBRL) from
BSE/NSE", listing "raw-material-consumed breakup" as one of the six
per-company disclosures to extract. **That assumption has now been tested and
it is mostly false.**

A crude-shock bootstrap run over **52 listed companies in 6 ripple families**
acquired the latest annual report for every one of them from NSE or BSE — 52
of 52 PDFs, no acquisition failures — and found a commodity-level breakup of
cost of materials consumed in **two** of them.

| | |
|---|---|
| Companies attempted | 52 (paints 6, tyres 7, specialty chemicals incl. adhesives 10, packaging films 8, logistics 7, FMCG 8) |
| Annual reports acquired | 52 / 52, exchange-hosted primary PDFs |
| Companies with a usable input-cost share | **10** (12 rows) |
| Of which from a materials-consumed breakup | **2** — CEAT and Savita Oil |
| Of which from an expense-line ratio (logistics) | 7 |
| Of which from the SEBI LODR commodity table | 1 (HUL, with a basis mismatch) |
| Unsourced | 42, of which 26 `AGGREGATED_SINGLE_LINE` |

**Why, structurally.** Schedule III to the Companies Act 2013 requires "Cost
of materials consumed" as one line. The Schedule VI-era requirement to
disclose consumption by class of raw material, and the imported/indigenous
split, are gone. What remains in a modern Indian annual report is a
roll-forward — opening stock, purchases, closing stock — sometimes split
"raw" versus "packing". A company that itemises rubber, carbon black and
fabric is doing so **voluntarily**, and almost none do.

**The consequence for the ledger:** the acquisition-and-extraction pipeline
built in Phase 1 works — it acquired, parsed, proposed and verbatim-gated
without a single fabricated row — and the *documents it is pointed at do not
contain the data*. Scaling the same approach to Tier 1 (Nifty 200 + F&O,
~250 companies) should be expected to yield a **single-digit percentage** of
companies with a filing-sourced INPUT_COST share, not a majority.

**Sources that did work, and should be tried first next time:**

1. **Named component lines inside the materials note**, where a company
   volunteers them (CEAT's "Details of raw materials consumed"; Savita Oil's
   "Base oils / Process chemicals, solvents, Waxes"). Rare, and the highest
   quality when present — the material type *is* the line item.
2. **Schedule III expense lines** for service businesses — fuel, freight,
   line-haul. This is why logistics returned 7 of 7 while every
   manufacturing family returned nearly nothing: the ratio is against
   TOTAL_COST, not COGS, and those lines are mandatory.
3. **The SEBI LODR commodity table** in the Corporate Governance Report
   (materiality-of-commodities disclosure). Present in 6 of 52 filings and
   quantified in 3. Two of those three quantified only a *non-crude*
   commodity (MRF: natural rubber; Godrej CP: soap base / palm). Note the
   basis: it reports commodity **exposure** (purchase orders / hedged
   position), not consumption, so it does not divide cleanly into a
   materials-consumed denominator.

**Sources that did NOT work, recorded so nobody re-runs them:** the BRSR
materials tables (tonnage and recycled-content percentages, never value by
commodity); MD&A and Board's Report commentary (names the crude basket
qualitatively — Apollo Tyres is the clearest example — and attaches no
figure); "value of imported and indigenous raw materials consumed" (found in
zero of 52 filings).

**What this means for closing §5.** A filing-only route will not populate the
ledger. Either the scope changes (accept `TOTAL_COST`-based expense-line
exposures for service sectors, as this run's logistics rows do), or the
source changes (earnings-call transcripts and analyst-day decks, where
managements do give raw-material basket splits — a different acquisition
problem with weaker provenance), or the ledger accepts far thinner coverage
than Tier 1 implies. **Owner: repo owner — this is a scope decision, not an
engineering one.**

### Sub-gap: three missing vocabulary leaves — CLOSED 2026-08-17

`config/exposure_tags.yaml` could not express three of the exposures this run
found. Closed by a reviewed edit to that file plus **migration 0016**, which
re-syncs `valid_exposure_tag` from the config (0013's loader does not re-run
on a database already at head, so the file would have said the tag was legal
while the trigger refused it).

| leaf | why the vocabulary needed it |
|---|---|
| `input:base_oil` | the entire input cost of the lubricants family, and the single best-disclosed exposure in the run (Savita Oil, note 18 names "Base oils" as a line: 86.1% of cost of materials consumed) |
| `input:bought_in_freight` | an asset-light 3PL does not burn diesel; it buys capacity from an operator who does. Tagging that `input:freight_diesel` would let a freight bill — wages, tolls, tyres, margin and some diesel — be read as a fuel cost with a fuel cost's elasticity |
| `input:intermediated_air_capacity` | the air twin: chartered aircraft and purchased belly space, ATF-linked through fuel surcharges. Distinct from `input:atf`, which is an airline buying the fuel itself |

`input:intermediated_air_capacity` shipped under a confirm-or-revert flag on
the owner (commit `f2e9d902`); **accepted by owner 2026-08-17** — the leaf is
permanent, and 0016's conditional downgrade has nothing left to decide.

The intermediated pair is the substantive addition. It encodes a distinction
the ledger previously could not make — **who is exposed to the commodity, and
who is exposed to somebody else's exposure to it** — and every row carrying
one of those two tags states in `computed_from` that its crude elasticity is
materially below the raw ratio. The pass-through curve that would quantify
"materially below" does not exist for any of them (see §5).

**Still missing, and now visible because of the run:** nothing in the schema
records that `input:bought_in_freight` is a derived exposure of
`input:freight_diesel` rather than an independent one. Two companies at
different points of the same chain look like two independent exposures to the
same shock, which is exactly the double-count `mechanism_edge` and
`graph_distance` exist to prevent — and `mechanism_edge` is empty (§7).
**Owner: repo owner.**
