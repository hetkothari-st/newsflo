# DATA GAPS — The administered-price fertilizer complex

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

---

## 15. The administered-price fertilizer complex has no mechanism, no tag and no shock variable — OPEN

**This gap survives the V5 cutover.** It is not a V4 rendering defect: V5
reads `mechanism_edge` rows and there are no fertilizer rows to read either.

### How it was found

Audit of stored V4 node ids, runtime ingestion corpus, 2026-08-17: **45 of 58
distinct mechanism ids resolve to no `knowledge.MECHANISMS` entry**, and every
alert in that corpus carries at least one. Classified:

| bucket | ids | what it means |
|---|---|---|
| not a mechanism by construction (event root, trigger variables, sector slugs, V3 rulebook residue) | 19 | a category error, not a vocabulary gap |
| noise — event-specific or over-broad | 14 | 6 of these are price-driven channels the decoupling doctrine refuses; see `docs/v5/decisions/ADR-002` |
| synonym of an existing registry entry | 5 | recoverable by mapping |
| **registry gap — real, reusable, absent** | **7 ids → 5 mechanisms** | **this section** |

The registry's 42 entries cover crude, rates, FX, consumption, trade and
infra. Administered prices, subsidy receivables and nutrient policy are
absent entirely — a standing feature of Indian markets, not one story. The
five were observed on a real alert (alert 21, *"Cost Of Cheap Urea: India's
Fertiliser Strategy Under Strain As Subsidy Burden Mounts"*), which rendered
**three sections, all titled "other verified mechanisms", two of them
identically**, with no section note on the first.

### What was authored, and what blocks it

`backend/config/mechanism_edges_authored.yaml` — five candidate
`mechanism_edge` rows, `derivation: AUTHORED`, `reviewed_by: null`,
**not loaded and not loadable**. `app/graph/authored_edges.py` refuses every
one of them by name.

| edge_id | from_node | needs exposure leaf | blocked on |
|---|---|---|---|
| `fertilizer_subsidy_receivable_wc` | `FERTILIZER_SUBSIDY_OUTLAY` | `revenue:subsidy_realization_share` | tag + shock variable + confidence |
| `administered_farmgate_price_squeeze` | `FERTILIZER_SUBSIDY_OUTLAY` | `revenue:administered_price_share` | tag + shock variable + confidence |
| `nutrient_subsidy_mix_shift` | `FERTILIZER_SUBSIDY_OUTLAY` | `revenue:complex_fertilizer_volume_share` | tag + shock variable + confidence |
| `gas_ammonia_feedstock` | `NATURAL_GAS` ✔ already modelled | `input:gas_feedstock` | tag + confidence |
| `subsidised_volume_rationing` | `FERTILIZER_SUBSIDY_OUTLAY` | `revenue:allocated_volume_share` | tag + shock variable + confidence |

**The gap is three layers deep, and each layer is a different file with a
different rule for changing it:**

1. **`config/discovery.yaml::modelled_shock_variables`** has no
   `FERTILIZER_SUBSIDY_OUTLAY`. Four of the five edges have no graph entry
   point without it. `NATURAL_GAS` is already there, which is why
   `gas_ammonia_feedstock` is the cleanest of the five.
2. **`config/exposure_tags.yaml`** has none of the five leaves. Its own
   header makes extending it a review of that file plus a loader re-run,
   never a side effect of another change — so no tag was added here. The
   `mechanism_edge_valid_tag_insert` trigger refuses the rows regardless.
   `rate:floating_debt_share` is **not** a substitute for
   `revenue:subsidy_realization_share`: it describes how the borrowing
   reprices, not how much of the revenue is a government receivable.
3. **`mechanism_edge`** itself, which ships empty (§7) and stays that way.

`confidence` is `null` on all five with a `_required` list, in the same shape
`config/policy_modifiers.yaml` uses. A confidence is a judgement and the
loader will not invent one. **Owner: repo owner.**

### Two semantic conflicts to settle before approving

* `derivation: AUTHORED` edges are **not** in the `edge_review` queue —
  `edge_review.pending_edges` selects `IO_TABLE`/`EMPIRICAL` only, on the
  grounds that AUTHORED edges "were written by a person in the first place".
  These were proposed by a model and authored into a file, which is not the
  case that rule was written for.
* `graph/traverse.usable()` walks an AUTHORED edge while `review_status` is
  still `PENDING`. Inserting these as AUTHORED makes them **live**, not
  queued.

Consequently the approval act for this file is **running the loader under the
owner's own name**, not clicking approve in a console. If the owner would
rather they sit in the review queue proper, the derivation must change — that
is the owner's call, and `AUTHORED` is recorded because it is what these are.
