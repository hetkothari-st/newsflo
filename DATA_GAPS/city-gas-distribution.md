# DATA GAPS — City gas distribution

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

---

## 13. City gas distribution has no mechanism and no policy modifier — OPEN

CGD (IGL, MGL, Adani Total Gas, Gujarat Gas, IRM Energy) was **deliberately
excluded** from the Phase 1 crude ripple-exposure bootstrap rather than
sourced badly. It is not an INPUT_COST ripple family and modelling it as one
would produce a confidently wrong sign.

**Why the input-cost framing fails for CGD:**

* **The sign is plausibly positive, not negative.** A crude rise raises petrol
  and diesel pump prices, which widens CNG's discount to the liquid fuels it
  substitutes for and improves conversion economics. The dominant first-order
  channel is *volume demand*, not input cost.
* **The input side is a regime, not a price.** Gas procurement mixes
  administered domestic allocation (APM, priority-allocated to CNG and
  domestic PNG at an administered ceiling) with Brent-indexed and Henry
  Hub-indexed imported LNG. The crude sensitivity of the input therefore
  depends on the allocation mix at that moment and on where the APM ceiling
  sits — both regime variables, neither a company exposure.
* **Both effects are regime-dependent and can reverse.** An allocation cut
  moves a company from mostly-administered to mostly-indexed input in one
  announcement, without any change in the company.

Recording a `share_of_base` against `input:*` for these companies would encode
a mechanism the business does not have. Recording a sector-average one would
be fabrication on top of that.

**What must be authored instead — two separate artefacts, neither of which
exists:**

| Artefact | Where | What it needs | Owner |
|---|---|---|---|
| A `VOLUME_DEMAND` mechanism edge, crude → CGD volumes, with the substitution channel named | `mechanism_edge` (§7) and a leaf in `config/exposure_tags.yaml` — the current 25-tag vocabulary has no volume/substitution leaf, so this is a **vocabulary change first** | domain judgement, then the edge; **repo owner** |
| A Phase 4 policy modifier for the APM allocation and ceiling regime | `backend/config/policy_modifiers.yaml` — `IN_APM_GAS_CEILING` exists as a `HARD_CAP` scaffold on `revenue:gas_realization_apm`, which is the **producer** side (ONGC/OIL realisation). The CGD **buyer** side — allocation share and the administered input price — has no entry at all | **repo owner** |

Until both exist, a crude shock produces nothing for CGD companies, which is
the correct output. **Do not proxy this family from the tyres/paints
input-cost template because the machinery happens to accept a number.**
