# PROPOSED SPEC AMENDMENT 2 — an econometric exposure route

> ## SUPERSEDED — 2026-08-17
>
> **Status: REJECTED and SUPERSEDED by
> [`docs/v5/decisions/ADR-001-econometric-exposure.md`](../decisions/ADR-001-econometric-exposure.md).**
> Read the ADR instead. This document is retained as the working argument, not as a
> current record, and **should not be cited independently**. Three things in it are
> superseded:
>
> 1. **§6 discusses "the 2-in-52 that do disclose" as though those rows were `FILED`.
>    They are not. There are ZERO `FILED` rows in `company_exposure`.** All eleven rows
>    — CEAT and Savita Oil included — are `measurement = 'ESTIMATED'`: a ratio computed
>    from two printed figures, not a share any company stated. The real comparison is
>    *estimate from two printed accounting figures* vs *estimate from a fitted
>    coefficient*.
> 2. **The 9–12 person-week cost estimate is revised to 11–15** in the ADR, because
>    `company_financials` is empty and the only quarterly source wired into this repo
>    returns five quarters.
> 3. **Three things this document does not cover and the ADR does:** the §A3.2
>    correlation-without-mechanism objection, the real quarters-of-history distribution
>    queried from the DB, and the alternative routes to exposure data.
>
> The ADR also records the **`pass_through_curve` redirect (this document's §7) as
> DEFERRED, not rejected** — 4–5 pw, needs no amendment — and adds a postscript tracing
> what actually blocks output through the code.

**Status: PROPOSED — NOT IMPLEMENTED. NOT ACCEPTED.**
Nothing in this document is in the code. `MEASUREMENTS` in
`app/ledger/vocabulary.py` is unchanged, no column was added, no estimator
exists. This is the §7.2 form and the argument on both sides of it.

Raised: 2026-08-17, out of the crude ripple-exposure bootstrap.
Numbering follows PROPOSED SPEC AMENDMENT 1 (DATA_GAPS.md §9.9).

**Recommendation, up front: REJECT AS PROPOSED.** Root cause axis is `data`,
not `architecture`, and §7.2 rejects on that alone. But the underlying
instinct is right and is aimed at the wrong table — see
[The redirect](#the-redirect), which is the part worth acting on.

---

## THE §7.2 FORM

```
PROPOSED CHANGE:      Add measurement = 'ECONOMETRIC' to company_exposure.
                      Exposure estimated by regressing a company's quarterly
                      gross-margin ratio on the relevant commodity price over
                      the available quarters, per company. The coefficient is
                      read as the NET elasticity, already after pass-through
                      and hedging. The standard error supplies the band. A
                      confidence interval crossing zero maps to the existing
                      Phase 2 sign-consistency rule (publish MIXED or
                      UNCERTAIN).

FAILING METRIC:       Ledger coverage of INPUT_COST exposure outside the
                      logistics family.
                      current: 2 companies of 45 (4.4%); 4 rows.
                      target:  the spec's Tier 1 — Nifty 200 + all F&O
                               names, ~250 companies.
                      (Note on the brief's "4 of 52": 4 is the ROW count
                      outside logistics — CEAT x2, Savita Oil x2. The COMPANY
                      count is 2, and the correct denominator is 45, not 52,
                      since the 7 logistics companies are the ones that DID
                      work. Both readings are recorded so the metric is not
                      quietly flattering.)

ROOT CAUSE AXIS:      data
                      (argued at length below; the honest answer is not
                      `architecture`, and it is not close)

EVIDENCE THIS IS ARCHITECTURAL, not a data gap:
                      NONE THAT SURVIVES EXAMINATION. The strongest version
                      of the claim is: "the ledger's schema presumes a
                      structural share that Indian disclosure does not
                      publish, so the SCHEMA is what is wrong." That is a
                      real observation and it is still a data statement. The
                      schema is not failing to express something; the
                      documents are failing to contain it. A schema that
                      accepted an estimate would not have more information in
                      it — it would have the same absence, differently
                      labelled.

WHY A DATA FIX WON'T WORK:
                      It works for logistics (7 of 7) and it will not scale
                      to manufacturing, because Schedule III does not require
                      a commodity breakup and ~96% of the sampled filings do
                      not volunteer one (DATA_GAPS §14). So the honest
                      sentence is: a data fix of THE SAME KIND will not work.
                      A data fix of a DIFFERENT kind — quarterly XBRL, or
                      earnings-call transcripts — has not been tried and is
                      what this amendment actually requires as a
                      prerequisite. See "The dependency inversion" below.

COST OF THE CHANGE:   9-12 person-weeks, and the largest block of it is data
                      acquisition, not code:
                        * quarterly financials for the universe (20-40
                          quarters x company; company_financials has 0 rows
                          today)                              3-4 pw
                        * commodity price series, quarterly averages
                          aligned to Indian fiscal quarters   0.5 pw
                        * estimator, diagnostics, break tests, multiple-
                          testing discipline                  2-3 pw
                        * schema + Phase 2 formula rework + Phase 5
                          independence rework                 3-4 pw
                        * validation against the handful of FILED rows
                                                              1 pw

WHAT IT INVALIDATES:  The verbatim containment gate (Phase 1 Task 1.3) — the
                      ledger's entire anti-fabrication mechanism — does not
                      apply to a row with no excerpt. The review UI's premise
                      is void. share_of_base's meaning changes, which
                      silently double-counts pass-through in the §5.1
                      formula. Phase 5's independence from Phase 1 collapses.
                      Full list in "What it invalidates" below.
```

**Verdict under §7.2 as written: rejected.** "If `ROOT CAUSE AXIS` is
anything other than `architecture`, the change is rejected and the
corresponding data ticket is raised instead." The data ticket is
DATA_GAPS §14 and it is already open.

The rest of this document is the argument, because a one-word rejection of a
good idea is how a project loses a good idea.

---

## 1. WHICH W-CRITERIA IT WOULD IMPROVE, AND BY WHAT MECHANISM

Per §7.4 step 1. Only four of the twelve are plausibly touched.

| W | Criterion | Effect | Mechanism |
|---|---|---|---|
| **W6** | Ripple family recall on crude ≥ 80% | **Large improvement, and this is the whole case** | Recall is `V x M x C x G`. `C` — companies carrying the exposure tag — is the axis that is zero for paints, specialty chemicals and packaging films, because no filing states the share. An econometric route needs no disclosure at all, only a price series and a P&L history, so `C` becomes a function of data we can buy rather than data companies choose to print. This is the only criterion the amendment moves a lot. |
| **W1** | Every published company has mechanism + magnitude + band + source URL | **Mixed** | The band gets BETTER: a regression standard error is a real sampling distribution, where today's band is `band_width[source]` — a policy constant in `materiality.yaml`, the same relative half-width for every FILED parameter in the system. Substituting a measured band for a stipulated one is a genuine gain. The `source URL` gets WORSE: an estimate's provenance is a dataset, an estimator version and a sample window, not a page in a document a reader can open. W1 is measured as a 100% target on an automated audit; what "source URL" means for a fitted row has to be redefined before the audit can pass, and redefining a criterion to pass it is the failure mode §7 exists to prevent. |
| **W11** | Unanswerable external analyst objections ≤ 2 per 20 events — *"the real goal"* | **Ambiguous, and I lean NEGATIVE** | Positive: it answers `MISSING_SECTOR` objections, which today have no reply for five of seven ripple families. Negative: it manufactures a new class of objection that is much harder to answer. "Your Asian Paints crude elasticity is 0.34 — over what window, and does it survive dropping FY21?" is a question a competent analyst asks in one sentence and that a single stored coefficient cannot answer. Compare the objection it retires: "you have no view on paints." Trading a silence for a contestable number is not obviously progress against a criterion that scores *unanswerable* objections. `FALSE_PRECISION` and `NAIVE` are both live labels here. |
| **W4/W5** | PRIMARY precision ≥ 95%, wrong-direction ≤ 2% | **Neutral by construction, if the caps hold** | An ECONOMETRIC row would be capped below PRIMARY exactly as ESTIMATED is today (`exposure_measurement_grade_cap`), so it cannot move PRIMARY precision in either direction. That is the correct design and it is also the point: **the amendment buys ripple coverage and buys nothing at the tier that matters most.** |

**Not improved: W2, W3, W7, W8, W9, W10, W12.** W7 (ripple precision ≥ 80%)
is worth flagging as an unquantified risk rather than a neutral: more ripple
companies with weaker evidence is the classic way a recall gain buys a
precision loss, and nothing in this proposal bounds that trade.

One point strongly in its favour, and it deserves stating plainly: **the
proposal is careful about invariant 3.** "Market price movement never
influences fundamental direction, materiality, evidence, or tier." Regressing
*share prices* on crude would breach that invariant outright. Regressing the
*gross-margin ratio* — an accounting quantity out of the P&L — does not: it is
a fundamental measured against a commodity price, which is what the sensitivity
engine is trying to estimate anyway. Whoever drafted this understood the
constraint. **If it is ever implemented, a test must pin the regressand to
accounting data, because the drift from "gross margin" to "returns" is one
line of code and it destroys the invariant.**

---

## 2. THE FAILING MEASUREMENT

Measured 2026-08-17, full method and artefacts in DATA_GAPS §14.

| | |
|---|---|
| Companies attempted | 52, across 6 ripple families |
| Annual reports acquired | 52/52 from NSE/BSE, no acquisition failures |
| Companies with a usable INPUT_COST share | 9 |
| — of which logistics | **7 of 7** |
| — of which everything else | **2 of 45** (CEAT, Savita Oil) — 4.4% |
| Rows outside logistics | 4 |
| Unsourced | 43, of which 26 `AGGREGATED_SINGLE_LINE` |

Per family outside logistics: paints **0/6**, tyres **1/7**, specialty
chemicals (incl. adhesives) **0/10**, packaging films **0/8**, lubricants
**1/6**, FMCG distribution **0/8**.

This is a real failing measurement and it does trace to a real cause.
Schedule III of the Companies Act 2013 requires "Cost of materials consumed"
as one line. The Schedule VI-era disclosure of consumption by class of raw
material is gone. A company that itemises rubber, carbon black and fabric —
CEAT does — is volunteering, and almost none volunteer. **No amount of
better extraction recovers a number that is not printed.**

So the premise is sound. The question §7.2 asks is whether the *cause* is
architectural, and it is not.

---

## 3. ROOT CAUSE AXIS — THE ARGUMENT, BOTH WAYS

### 3.1 The case that it IS architectural

Stated as strongly as it can be:

> The V5 ledger encodes a specific theory of exposure — that a company's
> sensitivity decomposes into a *structural share* of a base, times a
> *pass-through curve*, times a *hedge ratio*. That decomposition is an
> architectural choice, made in spec §4.1 and §5.1, and it is only estimable
> if all three factors are separately observable. In Indian disclosure they
> are not: the share is unprinted, the pass-through is never quantified, the
> hedge is quantified only sporadically. The architecture therefore requires
> three observations to publish one claim, in a market that supplies zero of
> the three for most companies. An econometric route needs ONE observation —
> the joint response — and it is exactly the product the other three multiply
> to. The multiplicative decomposition is the architectural defect: it is
> more granular than the evidence base can support, and granularity you
> cannot populate is not precision, it is a shape.

That argument is not silly. It is the best case and it deserved to be written
out.

### 3.2 Why it fails anyway

**Three reasons, in increasing order of severity.**

**(a) The decomposition is load-bearing for things other than sizing.**
`pass_through` and `hedge_ratio` are not only multipliers. Spec §12's
falsification checklist raises `OFFSET_IGNORED` when a pass-through was not
considered, and `app/analysis/rebuttal.py` answers it by pointing at the
stored curve. Phase 4's policy modifiers act on *specific factors* — a
windfall levy captures a share of realisation, an APM ceiling caps a price —
and a modifier cannot be applied to a coefficient that has already absorbed
everything. Collapsing the decomposition does not simplify the architecture;
it removes the seams the adversary and the policy layer attach to. The
granularity is not decoration, and that is a genuine architectural argument
*against* the amendment rather than a data one.

**(b) The dependency inversion — this is the decisive point.**
`analyse_company` was run against the live database for CEAT with a 10% crude
shock on 2026-08-17. Result:

```
[v5-sensitivity] ABSTAINED company_id=186 tags=input:crude_derivative_rubber
                 uncomputable=input:crude_derivative_rubber=MISSING_ROW(pass_through)
channels 0
```

The exposure row exists. The system still says nothing, because
`pass_through_curve` is empty. **Exposure shares are no longer the binding
constraint — pass-through curves are.** The amendment proposes an expensive
new route to the input that has stopped binding, and it proposes it *before*
the run that would have revealed which input binds. That is the shape of a
change chasing the previous bottleneck.

**(c) It needs more data than the thing it replaces, of a kind we have none of.**
The regressor is the quarterly gross-margin ratio. `company_financials` holds
**0 rows**. The amendment's precondition is 20-40 quarters of P&L per company
for the target universe — a strictly larger acquisition than the 52 annual
reports that produced this measurement, and one whose absence is not
mentioned in the proposal. A change whose stated purpose is to escape a data
gap, and whose first requirement is a bigger data gap, has answered §7.2's
`ROOT CAUSE AXIS` question against itself.

**Honesty about (c):** quarterly results are filed as XBRL with BSE and NSE
and are *structured*, where the raw-material breakup is unstructured and
mostly absent. So the new dataset is plausibly CHEAPER PER COMPANY than the
one that just failed, and it is available for the whole universe rather than
4% of it. That is the single best argument the amendment has, and it is an
argument that the data ticket should be *quarterly XBRL acquisition* — which
is a data ticket, which is what §7.2 says to raise.

---

## 4. IDENTIFICATION PROBLEMS THAT WOULD HAVE TO BE SOLVED

None of these is fatal on its own. Together they are why the coefficient is
not the clean object the proposal treats it as.

### 4.1 Confounding — volume, mix, and every other input

The regressand, gross-margin ratio, is moved by: output prices, volume,
product and geography mix, every *other* input cost, operating leverage, FX,
inventory accounting lag, and one-offs. Crude is not orthogonal to any of
them. Crude spikes cluster with global demand strength and with generalised
inflation, so a naive univariate coefficient absorbs demand and inflation
effects with the *wrong sign relative to the cost channel* in some sectors
and the right sign in others. Omitted-variable bias here is not small and is
not consistently signed, which means it cannot be argued away as
conservative.

Minimum credible specification: multivariate, with at least the other major
input for the sector, a volume or revenue-growth control, and an FX term for
importers. That is 4-6 regressors, which collides directly with 4.2.

Two things genuinely in its favour, and they should be said: **simultaneity
is not a problem** (one Indian mid-cap does not move Brent, so the regressor
is exogenous in the way that matters), and **the regressand is accounting
data**, which keeps invariant 3 intact.

### 4.2 Minimum quarters — the arithmetic does not work for a large slice

A usable standard error on one coefficient wants ~20 observations; 4-6
regressors per 4.1 wants meaningfully more. 20 quarters is 5 years. Against
the actual universe:

* Delhivery listed in 2022 — about 16 quarters exist, full stop.
* Recent IPOs across the roster (IRM Energy, Honasa, JSW Dulux post-restructure)
  have fewer.
* Segment-level quarterly data barely exists in India; only consolidated
  gross margin is reliably available, which forces 4.4 on every diversified
  name.

So the method is unavailable for young companies and thin for many others,
and it is *least* available for exactly the newly-listed, poorly-covered
names where a filings route also fails. The two methods fail on an
overlapping population rather than complementary ones — which weakens the
"they complement each other" defence.

A stated minimum (say ≥ 24 quarters, refused below that, as
`config/empirical.yaml` already refuses a series shorter than 2,000
observations) is mandatory. It will exclude a material fraction of the
universe and that fraction must be reported, not silently dropped.

### 4.3 Structural breaks

A single coefficient over 8 years averages regimes that no longer exist:
capacity additions, acquisitions and demergers (Blue Dart, Delhivery,
JSW Dulux, Jubilant), product-mix shifts, contract renegotiations, changes in
hedging POLICY, GST, COVID, the 2022 spike. A Chow or Bai-Perron test needs
either candidate break dates — which is another dataset, and a judgement one —
or a data-driven search, which spends degrees of freedom that 4.2 says are
not there.

The uncomfortable version: the periods most informative about crude
sensitivity (2020-2022) are the periods most contaminated by everything else
that happened in them.

### 4.4 Low R² on diversified companies

SRF is chemicals plus packaging films plus technical textiles. ITC is
cigarettes plus FMCG plus hotels plus paper. Consolidated gross margin is a
blend; crude moves one part of it. The coefficient is attenuated toward zero
and its standard error is wide, so the CI crosses zero and — correctly, per
the mapping the proposal itself specifies — the row publishes MIXED or
UNCERTAIN.

That is the right behaviour and it is also a problem, because **it fails
precisely where the ledger is emptiest.** The conglomerates and diversified
mid-caps are a large share of the untagged universe. So the coverage gain in
§1 is overstated: the method will decline to speak about a meaningful slice
of the companies it was adopted to cover.

A related trap: a low-R² regression that nonetheless returns a *significant*
coefficient is more dangerous than an insignificant one, because the
significance survives into the ledger while the R² does not. Any
implementation must store R², n, the window and the specification alongside
the coefficient, and the gate must be able to read them.

### 4.5 Attenuation from the wrong price series

Companies buy on formulae, contracts and lags, not spot. Regressing on spot
Brent when the company prices off a lagged import parity introduces classical
measurement error in the regressor, which biases the coefficient toward zero.
Combined with 4.4 this pushes systematically toward under-stating exposure —
which is the safe direction, but it means the numbers are not unbiased and
must not be described as if they were.

### 4.6 Multiple testing

This is the same hazard `DATA_GAPS §9.7` already records for Phase 5:
thousands of company x commodity regressions at conventional significance
produce hundreds of spurious "exposures". Phase 5 handles it by refusing to
let an empirical row publish anything on its own — it may only cap a tier and
queue a human. An econometric EXPOSURE row does not have that safety valve:
it *is* the claim. Either the same discipline is imposed (an ECONOMETRIC row
may never be the sole basis of a published company) — which removes most of
the W6 benefit — or a false-discovery-rate correction is applied and the
surviving set will be much smaller than the coverage projection assumes.

### 4.7 Keeping ECONOMETRIC and FILED from ever mixing in one channel

The proposal asks how the schema would separate them. Four things are needed
and only the first is easy.

1. **The enum.** `MEASUREMENTS` in `app/ledger/vocabulary.py` gains
   `'ECONOMETRIC'`; `exposure_measurement_grade_cap` gains a grade for it.
   Trivial.

2. **A different field, because it is not a share.** `share_of_base` is a
   fraction of a base. A net elasticity is not. Worse, §5.1's cost formula is

   ```
   -base x share x delta x (1 - pass_through) x (1 - hedge_ratio) x ownership
   ```

   An elasticity that is *already net of pass-through and hedging* placed in
   `share_of_base` would then be multiplied by `(1 - pass_through)` and
   `(1 - hedge_ratio)` a second time. **Silent double-discounting, in the
   safe direction, invisible in the output.** This is the single most
   dangerous detail in the proposal: it fails quietly and it fails toward
   plausible-looking smaller numbers. Either a separate column
   (`net_elasticity`) plus a separate channel formula, or a DB-level CHECK
   that an ECONOMETRIC row forbids `pass_through` and `hedge_ratio`
   resolution entirely. A convention in a docstring is not sufficient.

3. **A precedence rule and a uniqueness constraint.** If a company has both a
   FILED share and an ECONOMETRIC elasticity on the same tag, the engine
   today would build TWO channels and the reducer would sum two estimates of
   the same delta. That is a double-count of the impact itself. Needs a
   unique constraint on `(company_id, exposure_tag, horizon)` across
   measurement classes plus an explicit precedence — and the precedence is a
   policy decision (my view: FILED wins, ECONOMETRIC is retained as a
   cross-check and surfaced when the two disagree by more than the band,
   which is a genuinely valuable signal).

4. **Provenance that is not a URL.** `company_exposure.source_url` is NOT
   NULL and the review UI links to a page. An estimate's provenance is
   `(dataset id, sample window, specification, estimator version, fit id,
   R², n)`. That is perfectly recordable — and it is a schema change plus a
   redefinition of what W1's "source URL" means.

---

## 5. WHAT IT INVALIDATES IN THE EXISTING DESIGN

### Phase 1

* **The verbatim containment gate — the ledger's whole anti-fabrication
  mechanism — does not apply.** Task 1.3: "an `ExposureProposal` without a
  non-empty `excerpt` that literally appears in the source document is
  discarded... This is the anti-hallucination gate for the ledger itself."
  A fitted coefficient has no excerpt. Nothing to contain, nothing to check.
  The replacement guarantee would have to be **reproducibility** — re-running
  the stored specification over the stored data returns the same number to
  the bit — which is a good control and a *different* one. Swapping the
  ledger's core control is not an additive change and should not be presented
  as one.
* **The review UI's premise is void.** Task 1.4 specifies a queue where "each
  row shows: proposed value, exposure tag, verbatim excerpt, link to source
  PDF at the cited page". None of those four exist for an ECONOMETRIC row.
  What a human would review instead is a diagnostic panel — coefficient, SE,
  R², n, window, residual plot, break test — which is a different tool for a
  different skill.
* **`extractor_quality` becomes meaningless** for these rows. Approve-rate
  and edit-rate per extractor version measure whether a prompt regressed.
  There is no prompt.
* **Bulk approve.** Task 1.4 permits bulk approval only for deterministic
  extractors. A regression IS deterministic given its inputs, so it would
  qualify on the letter — and bulk-approving thousands of unexamined
  coefficients is exactly what that rule exists to stop. The rule would need
  rewriting around *reviewability*, not determinism.
* **`no_selfcertify`** currently reads `measurement <> 'MODELLED' OR
  reviewed_by IS NOT NULL`. It would need extending to ECONOMETRIC, or the
  strongest structural protection in the schema silently does not cover the
  new class.

### Phase 2

* **`share_of_base` semantics and the double-discount in §5.1** — §4.7(2)
  above. The most serious item on this list.
* **Band construction changes source.** `dist_for` bands a parameter by
  `band_width[source]` from `materiality.yaml`. An econometric row arrives
  with its own SE and must not be re-banded by a policy constant. Two band
  regimes now coexist, and `evidence_grade_cap` is keyed by source in a way
  that assumes one.
* **Monte Carlo independence.** `DATA_GAPS §6` records that different
  parameters are drawn independently because no correlation structure exists.
  An econometric coefficient has already *integrated over* pass-through and
  hedging, so drawing them alongside it is not merely uncorrelated — it is
  double-counting the same uncertainty. The MC would need to know which rows
  are joint estimates.
* **`driver_ranking` degenerates.** Attribution across parameters is
  meaningless when there is one parameter. The published "what drives this"
  block would be empty or trivially "the elasticity", for the very rows that
  most need explaining.
* **Phase 3's threshold walk.** `exposure_index` and discovery select on
  `share_of_base` magnitude. Shares and elasticities are not on the same
  scale; a single numeric threshold across both is a category error.

### Phase 5 — the independence collapse

The most under-appreciated consequence. Phase 5's `transmission_empirical`
exists to be an **independent** cross-check: it fits history and asks whether
the fundamental read AGREES with it, and a CONFLICT blocks PRIMARY. If Phase
1's exposures are themselves fitted from history, the checker and the checked
are estimated from overlapping data by similar means. `empirical_status`
would trend to AGREE by construction, the four-outcome cross-check would stop
discriminating, and the system would lose its only mechanism for noticing
that its fundamental story is contradicted by what actually happened.

This is not a schema conflict that can be engineered around. It is the
amendment quietly deleting a control while appearing to add coverage, and on
its own it is close to disqualifying.

### The gates and the contract

`primary.evidence_grades`, `min_evidence_grade` and `allow_sector_proxy` all
need a stated position on ECONOMETRIC. My view: it must be capped below
PRIMARY, like ESTIMATED — which means, restating §1, **the amendment buys
ripple coverage only.** It cannot improve W4, W5 or W8, and W6 is the single
criterion it moves.

---

## 6. IS IT WEAKER THAN FILINGS FOR THE COMPANIES THAT DO DISCLOSE?

Asked directly, so answered directly: **yes as a fact, arguably no as a
predictor, and the two are not the same thing.**

**Weaker as a fact.** CEAT's note 29 states that carbon black was ₹1,43,495
lakhs of a ₹9,19,712 lakh basket. That is not an estimate of anything. It has
no standard error, no window, no specification, and it does not stop being
true when the sample changes. A regression coefficient is a summary of one
sample under one specification and moves when either moves. For provenance —
which is the entire premise of this system, per the One Rule — a printed
figure is categorically better evidence, and the gap is not close.

**Arguably stronger as a predictor.** What the engine ultimately needs is
"how much does EBITDA move when crude moves", and the filed share is only the
first of three factors, the other two of which do not exist for any company
in this repo (`pass_through_curve`: 0 rows). A net elasticity answers the
question the product asks, in one number, without the two missing inputs.

**The two concrete cases from this run:**

* **Savita Oil** — 86.1% base oil, near pure-play, a clean single-commodity
  input. Its regression would almost certainly be well-identified and high
  R², and would *add* an implied pass-through the filing does not disclose.
  Here the econometric route is genuinely complementary and the disagreement
  between the two, if any, would be informative.
* **CEAT** — the filed row is a FLOOR of 0.2278, because the 53% "Rubber"
  line merges natural (not crude) with synthetic (crude) and the filing does
  not split them. A well-identified regression might well be *better* than a
  floor of unknown tightness. This is the strongest single case in the run
  for the amendment.

**Which is why substitution is the wrong frame.** Running both where both are
available, and treating a material disagreement as a review trigger, is worth
more than either alone — and it is also the design that keeps FILED as the
publishable basis and ECONOMETRIC as evidence about it, which is where §4.7(3)
landed independently.

---

## 7. THE REDIRECT

The measurement in §3.2(b) is the thing to act on: **exposure shares are no
longer the binding constraint. Pass-through curves are.** The ledger now has
11 exposure rows and produces zero channels, because `pass_through_curve` is
empty.

Point the same econometric machinery at `pass_through_curve` instead of at
`company_exposure`, and almost every objection in this document dissolves:

* **No new measurement enum.** `pass_through_curve.basis` already has
  `ESTIMATED`, and `curve_needs_review` already CHECKs that an ESTIMATED
  curve carries a `reviewed_by`. The schema was built for this.
* **No `share_of_base` semantics change, and no double-discount.** A fitted
  pass-through goes exactly where the formula already expects a pass-through.
* **No collision with the verbatim gate.** A curve was never expected to have
  an excerpt; §4.2 of the spec says pass-through is a curve, never a scalar,
  and the review constraint already exists.
* **Much less Phase 5 contamination.** A pass-through parameter is one factor
  inside the fundamental read, not the whole of it, so the empirical
  cross-check retains real independence.
* **It unblocks the rows that already exist**, including the two families
  that DID source cleanly.
* **Cheaper.** Roughly 4-5 person-weeks against 9-12, because the schema, the
  review constraint and the Phase 2 integration are all already built.

It still needs the quarterly-financials dataset, and it still faces §4.1-4.6
in full — identification does not get easier because the target moved. But
it targets the constraint that actually binds, inside a schema that already
admits it, and it is a **data ticket plus an estimator**, not an amendment to
a frozen architecture.

**Recommended disposition:**

1. **REJECT** this amendment as proposed. `ROOT CAUSE AXIS = data`; §7.2
   rejects on that. No architecture change.
2. **RAISE the data ticket**: acquire quarterly financials (BSE/NSE XBRL) into
   `company_financials`. It is the prerequisite for every version of this idea
   and it is useful without any of them.
3. **RAISE the redirected proposal separately** as an estimator for
   `pass_through_curve` with `basis = ESTIMATED`, reviewed per the existing
   CHECK. That needs no amendment at all.
4. **Re-open this amendment** only if the redirect ships, curves populate, and
   W6 still fails — at which point there will be a second failing measurement
   and §7.3's three-strike rule can start counting properly.

---

## 8. WHAT WOULD CHANGE MY MIND

Recorded so that the rejection is falsifiable rather than a matter of taste:

* **A populated `pass_through_curve` and W6 still below target.** That would
  show the missing exposure shares, not the missing curves, are what bounds
  ripple recall — and §3.2(b), my decisive objection, would be dead.
* **A back-test on the companies that DO disclose.** Fit the coefficient for
  CEAT and Savita Oil, and for any Tier 1 company with a FILED share, and
  compare. If the econometric estimate lands inside the filed row's band on
  most of them, the method has demonstrated it recovers a known quantity, and
  the extrapolation to undisclosed companies stops being an article of faith.
  This is cheap — a handful of companies — and it should be done before any
  larger commitment. It is the single highest-value next step of anything in
  this document.
* **A worked answer to §4.7(2)** that keeps the double-discount structurally
  impossible rather than conventionally avoided.
* **A worked answer to the Phase 5 independence collapse** that is not "we
  will be careful".
