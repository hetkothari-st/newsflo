# PHASE 6 — FALSIFICATION, SECTIONS & REVIEW CONSOLE
## An adversary, deterministic sectioning, and a human window into every decision.

**Fixes:** every stage being a confirmer · Reliance grouped with OMC despite MIXED economics · no way for a human to audit or label.

**Prerequisite:** Phase 5 done.

---

## TASK 6.1 — Falsification stage

`newsflo/analysis/falsifier/`. Runs before the reducer, as a signal producer. Its objective is to **destroy** the candidate.

Objection taxonomy with default severities:

| Type | Severity |
|---|---|
| `ENTITY_WRONG` | BLOCKING |
| `MECHANISM_INVALID` | BLOCKING |
| `EXPOSURE_NOT_IN_LISTCO` | BLOCKING |
| `OFFSET_IGNORED` | MAJOR |
| `REGIME_MODIFIER_MISSING` | MAJOR |
| `MAGNITUDE_IMMATERIAL` | MAJOR |
| `HORIZON_MISMATCH` | MAJOR |
| `EVIDENCE_STALE` | MAJOR |
| `ALREADY_PRICED` | WARN |
| `BASE_RATE_VIOLATION` | WARN |
| `SECOND_ORDER_OVERREACH` | WARN |

**Mandatory analyst checklist** — the falsifier answers all ten in structured form with the record set in context. Any unanswerable item raises an objection:

1. Which exact segment is exposed, and what share of consolidated EBITDA is it?
2. Which P&L or balance-sheet line moves, and in which direction?
3. What is the transmission lag, and what evidence sets it?
4. What contractual, hedging, formula-pricing, or regulatory mechanism blunts this?
5. Is the exposure inside the listed entity, or in an unlisted/JV/associate arm?
6. Is there an offsetting channel of comparable magnitude?
7. Was this already visible in forward curves, consensus, or prior reporting?
8. Does direction hold at all three horizons? Which dominates and why?
9. Is any parameter driving >50% of the result a sector proxy?
10. If the event reversed, would the effect substantially reverse?

**Sustaining logic:** an objection is `sustained` unless a rebuttal signal exists citing a specific record field or evidence id. Rebuttals come from the sensitivity/evidence stages, never from the falsifier arguing with itself, and never from free-form text. **Default is that the objection stands** — the burden sits on publication.

**Model discipline:** run the falsifier with a different prompt lineage and, where cost permits, a different model or provider than the candidate generator. Record `provider/model` on both. The eval harness must report precision separately for same-model vs cross-model runs — correlated generator/checker error is the standard failure mode of LLM self-verification.

---

## TASK 6.2 — Deterministic section engine

`newsflo/output/sections.py`. Pure function. No LLM.

```python
section_key = (publication_tier, economic_effect, mechanism_id, horizon_bucket)
```

Labels from `config/section_taxonomy.yaml`, keyed by `mechanism_id`. Ordering: tier → `|median materiality|` desc → alphabetical.

Invariants (each a test):
- A section contains only companies whose `(tier, effect, mechanism, horizon)` matches its key exactly.
- MIXED companies get their own section. **Reliance is never inside "NEGATIVE — OIL MARKETING & REFINING".**
- Empty sections omitted. Never fabricate a section for visual completeness.
- No UI string may concatenate a directness value with a tier value (lint test from Phase 0 extended here).

**Zero-PRIMARY is a designed state, not an error:**

```
NO PRIMARY IMPACT IDENTIFIED
No company shows a direct, evidenced, material exposure to this event.
  • 3 second-order effects below   • 2 macro channels   • 14 candidates rejected (view)
```

Rejection visibility is the clearest signal to a professional user that the system has judgement rather than enthusiasm.

---

## TASK 6.3 — Review console

Internal tool. Server-rendered, minimal.

Per event, display: the event and its shocks · PRIMARY candidates · ripple candidates · macro context · **the full rejected set with reasons** · evidence per claim with source links · causal path per company · materiality band and driver ranking · applied policy modifiers · empirical comparison · objections raised and their resolution.

One-click labels writing to the eval corpus:

```
CORRECT | WRONG_COMPANY | WRONG_DIRECTION | WRONG_MECHANISM |
WRONG_MATERIALITY | WRONG_TIER | WRONG_SECTION | INSUFFICIENT_EVIDENCE | DISPUTED
```

Also: the `coverage_gap` queue (Phase 3), the `divergence_review` queue (Phase 5), and the exposure proposal queue (Phase 1) — one console, four queues.

---

## TESTS

```
test_falsifier.py
  - BLOCKING objection without rebuttal => REJECTED
  - objection with a rebuttal citing a record field => not sustained
  - objection with free-text-only rebuttal => still sustained
  - checklist item unanswerable => objection raised
  - falsifier model_id differs from generator model_id when configured

test_sections.py
  - MIXED company never placed in a directional section
  - Reliance crude fixture lands in MIXED — INTEGRATED ENERGY
  - section contains only key-matching companies
  - empty sections omitted
  - zero-PRIMARY renders the explicit state with rejected count
  - determinism: same impacts => same section structure across 1000 runs

test_review_console.py
  - rejected candidates visible with reasons
  - labels persist to the eval corpus with labeler identity
  - evidence links resolve to stored source URLs
```

---

## DEFINITION OF DONE

- [ ] Falsifier runs cross-model where configured, and its objections can block publication
- [ ] Burden-of-proof default verified: unrebutted objections stand
- [ ] Section engine deterministic and LLM-free
- [ ] Reliance MIXED regression passes
- [ ] Zero-PRIMARY state renders correctly
- [ ] Review console live with all four queues and one-click labeling
- [ ] PRIMARY precision holds or improves while false-positive rate drops on holdout

---

## DO NOT

- Do not let the falsifier rebut itself.
- Do not accept free-form argument as a rebuttal. Record citation or nothing.
- Do not run generator and falsifier on the same prompt lineage without recording it as a limitation.
- Do not let an LLM name or assign a section.
- Do not hide the rejected set.
