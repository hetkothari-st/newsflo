# THE USDINR FEED — end-to-end specification

**Status:** DESIGN ONLY. Nothing implemented, no row written, `mechanism_edge`
untouched.

> ### SUPERSEDED FOR IMPLEMENTATION — read `BUILD-001-usdinr-feed.md`
> *Pointer added 2026-08-17 by the merge-integration session.*
>
> `BUILD-001` declares itself superseding this document for implementation
> purposes, and the two **disagree on the company count**: this spec says
> **15 publish**; `BUILD-001` §4.2 says **20**. BUILD-001 is later and is
> authoritative. This document remains the reasoning — the leaf-to-sign
> mapping, the Goodyear exclusion argument and the natural-hedge MIXED case
> are all still current and are not restated there.
>
> Recorded rather than reconciled: editing the count here would make one of
> the two numbers unattributable, and per `SESSION_PROTOCOL.md` §7.4 the fix
> for a duplicated status is a pointer with a date, not a second edit.
**Question answered:** could a rupee story render this week, with **no acquisition**?
**Answer: yes for 15 companies, and the direction is determinable per company.**

---

## 1. Why this one is different — and it is the exception to the whole design

Every other feed in this programme publishes a company because of **what industry it
is in**. USDINR cannot: whether a company imports, exports or carries USD debt is a
**balance-sheet fact, not an industry fact** (`MEMBERSHIP_CLAIM_ASSESSMENT.md` §4.2).
Two paint makers can sit at opposite signs.

That looks like a problem and is in fact why this feed is shippable first:

* the exposure is company-specific, so it **needs A+ evidence** — but
* Ind AS 107 makes the market-risk note **mandatory in every annual report ever
  filed**, so the evidence is already in every corpus, whatever it was acquired for.

**`fx:usd_cost_share` scored 10 usable of 11 candidate pairs — 91% precision, the
highest of any leaf in the sweep.** Nothing else measured comes close.

---

## 2. The companies — 16 found, 15 publish

From `backend/scripts/probes/_v2_classification.tsv`, all verdicts hand-classified,
every excerpt in `_v2_clean.tsv` at the same `(leaf, ticker)` key.

**Direction is read off WHICH LEAF, not off the sentence:**

| leaf | economics on INR **depreciation** | sign |
|---|---|---|
| `fx:usd_cost_share` | imported inputs cost more rupees | **NEGATIVE** |
| `fx:usd_revenue_share` | exports realise more rupees | **POSITIVE** |
| `fx:usd_debt_share` | USD liability is worth more rupees | **NEGATIVE** |

| # | ticker | usable legs | direction | excerpt (abridged) | p |
|---|---|---|---|---|---|
| 1 | AARTIIND | COST | NEGATIVE | *"Exposures … arise on account of the various assets and liabilities which are denominated in currencies other than Indian Rupee"* | 185 |
| 2 | BALKRISIND | COST | NEGATIVE | *"Consumption of Raw Materials is arrived at after adjusting … imported raw materials"* | 234 |
| 3 | COLPAL | COST | NEGATIVE | *"changes in foreign currency values that impact costs of imported raw material"* | 284 |
| 4 | COSMOFIRST | COST | NEGATIVE | *"policy is to hedge material foreign exchange risk associated with borrowings, highly probable forecast sales and purchases"* | 111 |
| 5 | SIRCA | COST | NEGATIVE | *"The Company make significant amount of purchases in foreign currency which exposes th[em]"* | 124 |
| 6 | XPROINDIA | COST | NEGATIVE | *"major borrowings are in foreign currency and also purchases are made in foreign currency"* | 127 |
| 7 | HUHTAMAKI | DEBT | NEGATIVE | *"availed External Commercial Borrowings from Huhtamaki Finance Company V B.V., Netherlands"* | 90 |
| 8 | JKTYRE | DEBT | NEGATIVE | *"rebalanced its borrowing mix … including foreign curr[ency]"* | 57 |
| 9 | SRF | DEBT | NEGATIVE | *"designates non derivative financial liabilities, such as foreign currency borrowings from banks, as hedging instruments"* | 142 |
| 10 | BRITANNIA | REV | **POSITIVE** | *"The Company has export sales (2% to 3% of total sales) primarily denominated in US dollars and Euro."* | 123 |
| 11 | MRF | REV | **POSITIVE** | *"Earnings in Foreign Exchange: FOB Value of Exports"* | 151 |
| 12 | POLYPLEX | REV | **POSITIVE** | *"exposure to the risk of changes in foreign exchange rates also relates to the Company's operating activities (when revenue …)"* | 248 |
| 13 | GANDHAR | COST + REV | **MIXED** | *"currency risk mainly on account of its import payables, short term borrowings and export receivab[les]"* | 178 |
| 14 | PANAMAPET | COST + REV | **MIXED** | *"currency risk mainly on account of its import payables and export receivables"* | 155 |
| 15 | SOTL | COST + REV | **MIXED** | *"The Company is exposed to currency risk mainly on account of its import payables and export receivables"* | 179 |
| — | **GOODYEAR** | COST | **EXCLUDED** | *"limited exposure to foreign exchange risk due to low reliance on imported raw materials and thus the company does not hedge"* | 100 |

**15 publish: 9 NEGATIVE, 3 POSITIVE, 3 MIXED.**

**Goodyear is excluded, and it is the proof the exception handler works.** Its
`fx:usd_cost_share` sentence passes the same sweep that admits the other ten — and it
says the opposite. Under membership-only it would have published NEGATIVE with the
other tyre makers. `member_evidence = EXAMINED_CONTRADICTS` removes it with a
citation the reader can follow.

---

## 3. What USDINR needs in nodes and edges

**Almost nothing, and that is the point.**

| layer | requirement | status |
|---|---|---|
| 1 · shock variable | `USDINR` | **already in `modelled_shock_variables`** |
| 2 · exposure leaves | `fx:usd_cost_share`, `fx:usd_revenue_share`, `fx:usd_debt_share` | **already in `valid_exposure_tag`** (all 3 of 28) |
| 3 · mechanism edges | **3 edges** | must be authored |
| 4 · section labels | 3 | must be authored |
| 5 · policy modifiers | none | — |
| 6 · node membership | **NONE — see below** | — |

### 3.1 The edges — three, and they point at the LEAF, not at an industry

```
USDINR --(FX_TRANSACTION, INPUT_COST side)--> exposure:usd_cost_share      NEGATIVE
USDINR --(FX_TRANSACTION, REVENUE side)-----> exposure:usd_revenue_share   POSITIVE
USDINR --(FX_TRANSLATION)-------------------> exposure:usd_debt_share      NEGATIVE
```

**This feed needs no industry nodes at all.** Because the exposure is
balance-sheet-determined, the `to_node` is the exposure itself and membership is
established per company by its own filing. It is the *only* family in the design where
layer 6 is empty — and consequently the only one where **there is no `SECTOR_PROXY`
row anywhere in the feed.** Every published company carries a company-named filing
citation.

Existing labels in `config/section_taxonomy.yaml` are close but not exact:
`it_export_realization`, `pharma_export_realization`, `import_cost_inflation`,
`electronic_import_cost` are all sector-flavoured. **Three new generic labels are
needed** — `IMPORTED INPUT COSTS`, `EXPORT REALISATION`, `FOREIGN CURRENCY DEBT` —
because this feed's sections are keyed on the exposure, not on a sector.

### 3.2 The FX channel formulas already exist and are not needed

`channels.py` has `FX_TRANSACTION` and `FX_TRANSLATION` with
`REQUIRED_PARAMS = ("natural_hedge_fraction", "hedge_ratio")` and
`("net_investment_hedge_ratio",)`. **The qualitative tier runs none of them** — no
parameter is resolved, no band computed, `sensitivity = None`. They stay for the day a
filing supplies a number.

---

## 4. The sign problem, at company level

You named the shock's sign as unverifiable at event level. **At company level it is
determinable, and from a different thing than I expected.**

* **event level**: is `USDINR` UP or DOWN? — a model reads the article. *Unverifiable
  against a closed vocabulary; one human glance per event.*
* **company level**: given the direction of the move, is this company helped or hurt?
  — **read off the LEAF, deterministically.** Import leg → negative; export leg →
  positive; USD-debt leg → negative. No model, no judgement, no per-company inference.

So the per-company sign is a **pure function of (leaf, shock direction)**, and the leaf
came from the company's own filing. **The only judgement in the entire feed is the
event-level sign, made once per story.**

**Two real complications, both handled by existing machinery:**

1. **Natural hedge → MIXED, not a net.** Gandhar, Panama Petro and Savita each
   disclose *both* import payables and export receivables in one sentence. The honest
   output is `MIXED`, and inventing a net would require the two shares — a magnitude.
   Invariant 9 already forbids collapsing it, and the reducer already produces MIXED
   from opposite-signed channels. **3 of 15 land here.**
2. **A hedge is not an offset.** Cosmo First *"hedges material foreign exchange risk"*;
   JK Tyre and SRF disclose hedging instruments. Under the qualitative tier that is a
   **`MITIGATED` annotation**, not a sign change — because "hedged" without a ratio
   does not say how much. Publishing it as an offset would be inventing `hedge_ratio`.

---

## 5. What would publish today, with no acquisition

| | |
|---|---|
| companies | **15** (9 NEGATIVE, 3 POSITIVE, 3 MIXED) + **1 excluded with a citation** |
| evidence | **grade C**, every row a company-named filing sentence with a page number |
| `SECTOR_PROXY` rows | **zero** |
| acquisition needed | **none** — the corpus is on disk, the excerpts are extracted, the pages are cited |
| new authored artefacts | 3 mechanism edges, 3 section labels |
| new code | qualitative tier (`DEFECTS-003` prerequisites first), no FX-specific code |
| distance | all d1 — a direct balance-sheet exposure to the shock variable |
| sections | 3, keyed on exposure: imported costs / export realisation / FX debt |

**Could a rupee story render this week?** The *data* is ready now and needs no
acquisition. What stands between it and a render is the qualitative tier itself, and
**D11 is a hard prerequisite** — without it, the 37 corpus companies with no usable FX
leg would each publish a rejected row reading `NO_MATERIAL_IMPACT`, asserting that a
rupee move does not affect them when nobody looked.

**Honest sequencing:** D11 + D11.1 → qualitative tier → 3 edges + 3 labels → this
feed. The feed itself is the smallest piece of that chain.

### 5.1 Why this is the right first feed

1. **Highest measured precision in the corpus** — 91% on `fx:usd_cost_share`.
2. **Zero acquisition.**
3. **Zero `SECTOR_PROXY`** — the only feed where every company is filing-cited, so it
   never depends on the membership argument at all.
4. **Only one human judgement per story** (the event-level sign).
5. **It exercises MIXED honestly** on 3 of 15, with a natural-hedge disclosure behind
   each — a real test of invariant 9 on real data rather than a fixture.
6. **It is the event class a reader sees most often.** A rupee move is a daily
   headline; a crude derivative story is not.

### 5.2 What it does not do

* **15 companies is not a market view.** It is 15 companies out of a corpus of 52
  acquired for an unrelated reason. Coverage grows only with corpus size — and, unlike
  crude, **there is no classification shortcut**, because no industry determines FX
  exposure.
* **No magnitude.** "Britannia's export sales are 2–3% of total" is in the excerpt and
  must **not** be rendered — the entailment firewall would pass it, since the numeral
  traces to a stored record, but publishing it would be the sized tier arriving by the
  back door with `n=1`.
* **`fx:usd_debt_share` is the weak leg** — 3 usable of 15 pairs, and one of those
  (ASIANPAINT) is a **JPY** ECB against a leaf that says USD. That leaf needs either a
  currency-general rename or an extractor that refuses a non-USD disclosure.
