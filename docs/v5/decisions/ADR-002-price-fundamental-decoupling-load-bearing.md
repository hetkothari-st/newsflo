# ADR-002: The price/fundamental decoupling doctrine is load-bearing — EVIDENCE

**Status:** ACCEPTED (evidence record; no code change proposed or made)
**Date:** 2026-08-17
**Recorded by:** implementer, at the repo owner's instruction
**Governs:** `NEWSFLO_V5_BUILD_SPEC.md` §2 (the three axes) · master-context invariant 3 ·
`backend/tests/phase0/test_market_isolation.py` · `backend/tests/test_price_fundamental_decoupling.py`

**Nothing in this document changes any code.** It records a measurement that
tests an existing doctrine, and confirms two structural refusals that already
exist.

---

## THE CLAIM UNDER TEST

Master-context invariant 3:

> Market price movement never influences fundamental direction, materiality,
> evidence, or tier.

`NEWSFLO_V5_BUILD_SPEC.md` §2 states it as an axis separation — Axis A
(fundamental impact) may never read Axis B (market reaction), "enforced by
module boundary + test".

A doctrine enforced by a test is only worth its cost if something actually
pushes against it. This record is the evidence that something does.

---

## THE MEASUREMENT

Audit of the V4 impact graph's stored node ids (runtime ingestion corpus,
2026-08-17): **45 of 58 distinct mechanism ids resolve to no
`knowledge.MECHANISMS` entry.** Classified, six of those 45 are neither
synonyms of an existing mechanism nor gaps in the registry. They are the
graph proposing a **price-driven channel**:

| stored node id | the mechanism sentence the model wrote |
|---|---|
| `equity_valuation_multiple` | "Higher crude raises expected inflation and macro uncertainty → required equity risk premium…" |
| `shk_equity_risk_premium` | "Higher crude raises expected inflation and import-bill uncertainty for an oil-importing economy…" |
| `shk_risk_appetite_down` | "Crude-driven inflation and current-account risk raise the expected discount rate…" |
| `shock_market_sentiment` | "Rising crude oil prices trigger inflation and margin compression fears, leading to…" |
| `shock_equity_selloff` | (no sentence recorded) |
| `midcap_outperformance` | "Strong buying interest in select midcap stocks drives the Nifty MidCap Select…" |

Every one of them is a claim about a **discount rate, a risk premium, or a
flow of buying** — Axis B and Axis C material, dressed as Axis A. None of
them says anything about a company's EBITDA.

**This is the finding.** The registry does not omit these channels by
oversight. It omits them because they are the thing the doctrine refuses,
and a competent language model reaching for "what does crude do to equities"
produces them **unprompted, repeatedly, across separate events**. Six of 45
orphans — 13% — are attempted doctrine violations.

Without invariant 3 they would be indistinguishable from the fundamental
mechanisms beside them: they read fluently, they are causally coherent, and
several are *true statements about markets*. They are simply not statements
this system is entitled to make about a company's economics.

**Conclusion: the doctrine is load-bearing.** It is not defensive
boilerplate around a hazard nobody encounters. It is a filter with measured
throughput.

---

## DOES V5 REJECT THEM BY CONSTRUCTION?

Yes, and at three independent points. The first two were verified by running
them against production code on 2026-08-17, not asserted from reading; the
third is an existing test.

### Refusal 1 — the closed exposure vocabulary has no market leaf

`config/exposure_tags.yaml` has exactly four families: `input`, `revenue`,
`fx`, `rate`. Scanning all leaves for `equity`, `sentiment`, `risk_premium`,
`valuation`, `multiple`, `discount`, `beta`, `price`, `appetite` returns
**nothing**.

A V5 mechanism is a `mechanism_edge` row and `exposure_tag` is NOT NULL.
Attempting to insert one on a market tag:

```
INSERT INTO mechanism_edge (... exposure_tag ...) VALUES ('market:equity_risk_premium' ...)
→ sqlite3.IntegrityError: exposure_tag is not in the closed vocabulary
```

The refusal is the `mechanism_edge_valid_tag_insert` trigger
(`app/models.py`), not a Python `if` — so it holds against anything with a
database handle.

### Refusal 2 — no §5.1 channel formula sizes a valuation exposure

Even granting the tag, `channels.CHANNEL_FOR_KIND` maps only seven exposure
kinds to a formula: `INPUT_COST`, `INVENTORY`, `REVENUE_REALIZATION`,
`VOLUME_DEMAND`, `FX_TRANSACTION`, `FX_TRANSLATION`, `INTEREST_RATE`. Every
one computes a ΔEBITDA. Offering a valuation exposure:

```
compute_channel(ExposureView(exposure_kind="VALUATION_MULTIPLE", ...), ...)
→ InsufficientParameterData: exposure_kind 'VALUATION_MULTIPLE' has no §5.1
  channel formula. It is a real exposure and it is recorded, but it cannot be
  sized, so it publishes nothing.
→ reason = NO_FORMULA
```

Abstention, with a named reason, carried into the published materiality
block. Not a silent drop.

### Refusal 3 — the module boundary, already tested

`tests/phase0/test_market_isolation.py` AST-scans every module under
`app/core/` and fails on any import of `app.market.*`, and separately asserts
that mutating market data for a fixture event leaves `CompanyImpact`
byte-identical.

**So the six market orphans could not become V5 records under any of the
three.** V4 renders them into the `OTHER_LABEL` bucket beside genuine
fundamental mechanisms; V5 cannot represent them at all.

---

## WHAT THIS DOES NOT SAY

* It does **not** say these channels are false. "Higher crude raises the
  required equity risk premium for an oil importer" is a defensible
  macro statement. It is Axis B/C material, and §2 says Axis C modulates
  *ranking, urgency and UI prominence* — never direction or magnitude.
  Nothing here forecloses surfacing them on their own axis.
* It does **not** propose adding a market family to the vocabulary. That
  would be the collapse §2 forbids.
* It does **not** propose a V4 fix. The V4 orphan fall-through is logged as
  a measurement (`app/market/orphan_metrics.py`) and dies at cutover —
  V5 SERVING CUTOVER CHECKLIST item 6.

---

## FOLLOW-ON

The remaining 39 orphans are classified in `DATA_GAPS.md` §15. Five of them
are a genuine registry gap (the administered-price fertilizer complex) and
are authored as candidate rows in
`backend/config/mechanism_edges_authored.yaml`, awaiting the owner.
