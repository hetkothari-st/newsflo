# SPEC DEFECTS 001 — raised by the CEAT proof-of-life run

**Raised:** 2026-08-17 · **Status:** OPEN, none fixed · **Owner:** repo owner
**Evidence:** `DATA_GAPS/ceat-proof-of-life.md` §16 · `docs/v5/decisions/ADR-001-econometric-exposure.md`
**Rule for this document:** it describes defects and the shape a fix must have.
**No fix is implemented and none should be written against this list until the
owner has read it.**

All nine were exposed by a single run: CEAT, crude +10%, five hand-sourced links,
end to end to tier / section / prose. The data written for that run has since been
rolled back in part (see §Rollback at the end); the defects are properties of the
spec and the code, not of the data, and survive the rollback.

| # | Defect | Layer | Severity |
|---|---|---|---|
| **D5** | No crude→derivative elasticity anywhere in §5.1 | **spec, §5.1 formula** | **Highest — every number the engine has ever produced for a `crude_derivative_*` tag is wrong by an unknown factor** |
| **D1** | Four of five ledger tables have no reviewed write path | build, Phase 1 | **Blocks all data population, therefore blocks everything** |
| **D2** | An unreviewed `mechanism_edge` published | **gate, §A3.2 guarantee** | **Highest gate defect found** |
| **D3** | Point estimate and Monte-Carlo band contradict each other | engine, Phase 2 | High — latent, ships the moment a ceiling < 1.0 |
| **D4** | "not evaluated" conflated with "nets to zero" | reducer + UI, §8 | High — destroys the distinction §8 exists for |
| **D6** | Raw UUID rendered in a user-facing section label | output | Medium |
| **D7** | Two mechanisms collapsed to one by sort order | reducer, §7.3 | Medium-high — drops the larger channel's mechanism |
| **D9** | `materiality` means two different things in one payload | signal schema | Medium — W3 contradiction risk |
| **D8** | `driver_ranking` degenerates to a single driver | engine, Phase 2 | Low — predicted in ADR-001 §1.5; not in the owner's priority list, recorded for completeness |

---

# D5 — There is no elasticity between the shock variable and the actual input

## What is wrong

Spec §5.1's COST channel is:

```
ΔEBITDA_inr = − base_value_inr × share_of_base × shock_delta_pct
              × (1 − passthrough(h)) × (1 − hedge_ratio(h)) × ownership
```

`shock_delta_pct` is the move in the **shock variable** — Brent. `share_of_base`
is the company's spend on **a derivative of it** — carbon black, rubber chemicals,
polyester tyre cord, paint resins, packaging film. **There is no term connecting
the two.** The formula therefore asserts, silently and everywhere, that:

1. **the derivative's price moves 1:1 with crude** (elasticity = 1.0), and
2. **it does so instantly** (lag = 0).

Neither is stated anywhere as an assumption. It is not in `materiality.yaml`, not
in `exposure_tags.yaml`, not in the spec prose, and not on the published record.
It is a hardcoded 1.0 that exists by omission — which is the exact failure mode
the Hollow Implementation Check asks about: *"is there any code path where a
missing parameter is replaced by a hardcoded plausible value?"* Here the parameter
was never named, so the check could not find it.

## Why this is first, not ninth

Every other defect on this list distorts how a number is reviewed, labelled,
grouped or displayed. **D5 makes the number itself wrong**, by a factor nobody
has bounded, on every `crude_derivative_*` channel the engine will ever compute —
which is the entire ripple half of Crude-Complete: paints, tyres, adhesives,
packaging films, specialty chemicals.

The direction of the error is not even reliably conservative. Carbon black
feedstock is a refinery residual whose price is driven by crude *and* by refinery
run economics and by Chinese supply; polyester chain prices run off paraxylene and
MEG with their own capacity cycles. An elasticity below 1 overstates the impact;
a leveraged or lagged one understates it in the near horizon and overstates it
later. **We do not know which, per tag, and the system currently cannot express
the question.**

## The note 45(iv) agreement does NOT validate this

`DATA_GAPS/ceat-proof-of-life.md` records that the engine's gross figure
(₹28,512 lakh) matches CEAT's own disclosed commodity sensitivity, scaled and
normalised (₹28,745 lakh), to within 0.8%. **That agreement is silent on D5 and
must not be cited as evidence against it.**

CEAT's note 45(iv) states a sensitivity *"to a 5% movement in the input price of
rubber and carbon black"* — a move in the **derivative's own price**, not in
crude. Both the disclosure and the engine start from a move in the input and
multiply by the spend on it. **They share the assumption; they do not test it.**
What the agreement validates is the *arithmetic downstream of the input price* —
that `base × share × delta` is assembled correctly and that the exposure row's
share is right. That is worth having and it is all it is worth.

To actually test D5 you would need CEAT's carbon-black cost against Brent over
time — which is the elasticity itself, i.e. the missing datum.

## The shape a fix must have

**A new parameter, sourced and banded, applied between the shock and the exposure.
Not folded into `pass_through`.**

```
effective_delta_pct = shock_delta_pct × derivative_elasticity(lag_days)
```

then §5.1 unchanged, taking `effective_delta_pct` in place of `shock_delta_pct`.

Requirements a fix must satisfy:

* **It is a separate economic object from `pass_through` and must have its own
  column and its own resolution path.** `pass_through` is *downstream* — how much
  of a cost increase the company recovers from its customers. The elasticity is
  *upstream* — how much of the shock reaches the company's input at all. Folding
  one into the other repeats the double-discount error ADR-001 §2.7(2) identifies,
  and makes both unauditable.
* **Keyed on `(shock_variable, exposure_tag)`, not on company.** It is a statement
  about a commodity chain, identical for every tyre maker. This is what makes it
  cheap: one row serves an entire family.
* **It is a curve, not a scalar**, for the same reason §4.2 makes pass-through a
  curve. Naphtha follows crude within days; carbon black contracts reprice
  monthly or quarterly; tyre-cord contracts annually. A single number cannot carry
  that, and the IMMEDIATE horizon is where it matters most — the CEAT run's
  −12.7% headline is an IMMEDIATE (5-day) number computed with elasticity 1.0 and
  lag 0, which is the least defensible combination available.
* **It must abstain, not default.** No elasticity row → `InsufficientParameterData`
  → UNCOMPUTABLE, exactly like a missing pass-through. **The current behaviour is
  the forbidden step 4: an unnamed default of 1.0.**
* **It must record a basis and a band**, and cap evidence grade the same way every
  other parameter does.
* **Tags that genuinely need no elasticity must say so explicitly, with a row.**
  `input:crude_direct` is 1.0 *by definition* and should carry a row saying that,
  not inherit silence. `input:freight_diesel` is the opposite trap: Indian diesel
  is administered, so the crude→diesel link is a **policy question for Phase 4**,
  not an elasticity — a fix that quietly fits an elasticity there would model a
  regime as if it were a market.

## Where the data could come from — options, not a recommendation

1. **Published derivative price series, regressed on crude.** Free-ish and public
   for some links: DGCI&S / Indian customs **import unit values by HS code**
   (monthly, per commodity, public) give a usable price proxy for carbon black,
   synthetic rubber, PTA/MEG and tyre cord. Commercial series (ICIS, Platts,
   Argus) are better and paid.
   **Note the asymmetry with ADR-001, because it matters:** this is a
   **commodity-to-commodity** relation, not a company-level one. It carries **no
   §A3.2 exposure** (no company is tagged by it — the company's tag comes from its
   own filing), **no Phase 5 independence problem** (it is not the company's
   response to a shock), and n is a long daily or monthly series rather than 25
   contested quarters. **This is the one place in the system where the estimator
   idea ADR-001 rejected is a genuinely good fit, and for reasons that are the
   exact inverse of why it was rejected there.** If any econometric work happens,
   it should happen here first.
2. **Structural / contractual.** Many of these are formula-priced: carbon black
   off CBFS, polyester off PX and MEG, both ultimately off naphtha. Where a
   published formula or a disclosed contract mechanism exists, an authored
   coefficient with a source is better evidence than a fit.
3. **Company disclosure.** Rare, but earnings calls occasionally quantify it
   ("a $10 move in crude is worth ~₹X/kg on our compound cost"). Would be
   `DISCLOSED_CALL`, per company, and would supersede the family-level row.
4. **Industry association series.** ATMA, IRMRA and equivalents publish input
   indices for some families.

**Nothing above is decided. Do not build any of it against this document.**

## Consequence for the crude-complete plan

Until D5 is closed, **no `crude_derivative_*` magnitude is defensible to an
external analyst**, and W11's `WRONG_MAGNITUDE` and `NAIVE` labels are both live
on every ripple company the system would publish. The correct interim posture is
that the ripple half of Crude-Complete is **not measurable yet** — not that it is
measured and merely uncertain.

---

# D1 — Four of the five ledger tables have no reviewed write path

## What is wrong

`app.ledger.review.approve_proposal` is the reviewed write path for
**`company_exposure` only**. For the other four tables the run needed:

| Table | Proposal table | Review function | Loader | How the run wrote it |
|---|---|---|---|---|
| `company_exposure` | `exposure_proposal` | `approve_proposal` | yes | correct path |
| `pass_through_curve` | **none** | **none** | **none** | direct SQL |
| `company_modifier` | **none** | **none** | **none** | direct SQL |
| `company_financials` | **none** | **none** | **none** | direct SQL |
| `mechanism_edge` | **none** | `edge_review.py` reviews rows that already exist | **none** | direct SQL |

`app/ingest/filings/xbrl.py` and `deterministic.py` parse into row dicts shaped for
`company_financials`. **Nothing consumes them.** `params.py` and `engine.py` only
read. So there is currently **no compliant way to put a pass-through curve, a
modifier, a financial row or a mechanism edge into this system**, and the only
reason the fabrication guard held during the run is that the DB-level CHECKs
(`curve_needs_review`) still fired.

## Why it blocks everything

Phase 1's entire anti-fabrication design is *proposal → verbatim gate → human
review → write*, with `reviewed_by` and `created_by` recorded. That design covers
one table out of five. Every plan in `DATA_GAPS/` that says "populate X" is
currently a plan to write X by hand into SQL, unreviewed, unattributed, with no
excerpt and no extractor version. **The data-population programme cannot start
honestly until this exists.**

## What a fix must specify

* **A proposal record per table**, or one polymorphic `ledger_proposal` — the
  choice is a design call, not obvious either way. Each needs at minimum:
  `source_url`, `source_page`, `excerpt`, `extractor_version`, `document_sha256`,
  `status`, `reviewed_by`, `reviewed_at`, `reject_reason`.
* **A verbatim containment gate where an excerpt is meaningful** —
  `company_financials` and `company_modifier` are read off printed statements and
  can carry one. `pass_through_curve` frequently cannot (a curve is assembled from
  several sentences, or derived), which is exactly the seam ADR-001 §1.5 flags:
  the replacement guarantee has to be **reproducibility of a recorded derivation**,
  and that must be designed, not assumed.
* **A review surface that shows what a reviewer actually needs.** Task 1.4's four
  fields (value, tag, excerpt, PDF link) fit an exposure row. A curve needs its
  points, its basis, its derivation and the sentences behind each point. A
  mechanism edge needs the chain in prose plus the tag.
* **Bulk approve must be re-scoped from "deterministic" to "reviewable"** — see
  ADR-001 §1.5. A hand-authored edge is deterministic and must never be
  bulk-approved.
* **`created_by` must distinguish human authorship from extraction**, because for
  `mechanism_edge` the author *is* the evidence.

---

# D2 — An unreviewed mechanism edge published

## What is wrong

Both edges written for the run carried `derivation = 'AUTHORED'`,
`review_status = 'PENDING'`, `reviewed_by = NULL`. CEAT published at
`SECONDARY_RIPPLE`. The gate trace:

```
{"rule": "mechanism_id", "passed": true,
 "detail": "ca78e5c5-049c-4731-931d-b9ab1bedebf9", "tier": "SECONDARY"}
```

The rule tests **presence of a non-null `mechanism_id`**. It does not read
`review_status`, `reviewed_by`, or `derivation`.

## Why it is the highest-severity gate defect

`NEWSFLO_V5_ADDENDUM_RIPPLE_COVERAGE` §A3.2 states the guarantee as structural:
*"An empirically-discovered relationship may never publish until a named mechanism
exists… mechanism reviewed & authored as edge → companies tagged → now
publishable."* §A2.4 is explicit that IO-derived edges *"require `reviewed_by`
before they can publish"*. `gates.yaml` carries `require_mechanism_id: true` with
the comment `# A3.2 — non-negotiable`.

**The implemented rule delivers a weaker guarantee than the one the spec
describes and than the one this project has been told it holds by construction.**
Anything that can write a `mechanism_edge` row can authorise a publication, with
no human in the path. The schema already has `review_status`, `reviewed_by` and
`reviewed_at` — the columns exist and the gate does not read them.

Combined with D1 (nothing controls who writes an edge), the §A3.2 guarantee is
currently enforced by nothing at all.

## What a fix must satisfy

* The SECONDARY `mechanism_id` rule must require **a resolvable edge in a
  reviewed/approved state**, not a non-null string. A `mechanism_id` naming a row
  that does not exist should also fail, and today would not be checked either.
* The rule must state what it does with `derivation = 'AUTHORED'` vs `'IO_TABLE'`
  vs `'EMPIRICAL'`. §A2.4 requires review for the latter two by name; the run
  shows AUTHORED needs it just as much.
* Effective-dating (`effective_from` / `effective_to`) is on the table and is also
  unread by the gate.
* Fixing this will make the CEAT run **stop publishing** until the owner approves
  the two edges. That is the correct outcome and should be the acceptance test.

---

# D3 — The point estimate and the Monte-Carlo band contradict each other

## What is wrong

At NEAR_TERM (90 days), measured:

```
channel point deltas   [-0.0, -0.0]
zero_delta_channels    ('input:crude_derivative_petchem', 'input:crude_derivative_rubber')
signals emitted        0
Monte Carlo band       p10 -3.889  p50 -1.656  p90 -0.274
sign_consistency       1.0
bucket                 LOW
```

The deterministic computation says **exactly zero impact**. The band says
**−1.66% of EBITDA with 100% sign consistency**. Both are produced by the same
engine from the same inputs in the same call.

The mechanism: the point evaluation uses `dist.point` (pass-through 1.0 at the
ceiling → `1 − 1.0 = 0`), while the Monte Carlo samples pass-through over its
band `[0.60, 1.00]`, so almost every draw is strictly below the ceiling and
returns a negative delta. **The band never contains the point.**

## Why it is latent rather than visible

It did not ship here only because a channel whose point delta is zero emits no
signal, so the contradictory band had no carrier. **Change the curve's ceiling to
0.99, or let any parameter's point sit at a boundary of its band, and a
contradictory band publishes** — a headline number the deterministic path says is
zero, with `sign_consistency = 1.0` asserting confidence in its direction.

This also means `sign_consistency` is not measuring what its name implies at a
boundary: it reports agreement among draws that all sit on one side of a point
estimate they exclude.

## What a fix must satisfy

* An invariant that **the point estimate lies within the band**, asserted per
  channel, with a named failure rather than a silent divergence.
* A decision about boundary parameters: either the point is re-derived from the
  same draws (p50 of the simulation) so the two cannot diverge, or clipping is
  applied identically to both paths. Picking one is a design call; having two
  independent computations of the same quantity is the defect.
* `param_bounds` clipping and curve `ceiling` clipping currently apply at
  different stages. That asymmetry is the proximate cause and should be stated
  in one place.

---

# D4 — "not evaluated" is conflated with "nets to zero"

## What is wrong

Rendered output from the run:

```
> IMMEDIATE:  NEGATIVE (HIGH) -12.7%
  NEAR TERM:  not evaluated
  STRUCTURAL: not evaluated
```

and in the record, `direction_by_horizon` sets `"evaluated": false` for both.

**Both horizons were evaluated.** Two channels were built at each, both computed
successfully, and both returned zero. The record and the UI say the opposite of
what happened.

## Why it matters more than a wording bug

§8 exists to keep horizons separate and to stop them being inferred from one
another — *"discarding them is precisely how the current system produced three
contradictory Oil India representations."* The distinction between

* **we could not size this horizon** (missing parameter, abstention), and
* **we sized it and the net effect is nil** (full pass-through by 90 days)

is a *finding* in the second case and a *gap* in the first. Collapsing them means
the strongest thing the run actually learned about CEAT — that management's
disclosed pricing plan fully offsets the cost increase within a quarter, which is
the answer an analyst most wants — is displayed as an absence of analysis.

It also silently hides D3: the contradictory band sits inside the horizon labelled
"not evaluated".

## What a fix must satisfy

* At least three states on `direction_by_horizon`: `NOT_EVALUATED` (no channel
  could be built), `EVALUATED_ZERO` / `NO_MATERIAL_IMPACT` (built, nets below the
  floor), `EVALUATED_MATERIAL`.
* `zero_delta_channels` already carries the information — the reducer receives it
  and drops it. Threading it through is the mechanical part; the naming and the
  UI copy are the part that needs a decision.
* UI copy must not use "not evaluated" for a computed zero. Suggested distinction
  to settle: *"no material effect at this horizon"* vs *"not sized — data
  missing"*.

---

# D6 — Raw UUID rendered in a user-facing section label

## What is wrong

```
NEGATIVE — UNCLASSIFIED MECHANISM (ca78e5c5-049c-4731-931d-b9ab1bedebf9)
```

`config/section_taxonomy.yaml` carries no label for either authored edge, and the
fallback interpolates the raw `mechanism_id`.

## What a fix must satisfy

* A mechanism with no taxonomy label must not reach a user-facing surface with an
  internal identifier in it. Either the section is suppressed, or the fallback
  uses the edge's own `from_node → to_node` description, which exists on the row.
* **The deeper question, which is the reason this is not merely cosmetic:** the
  taxonomy is a hand-authored file and every new mechanism edge needs an entry.
  Nothing currently detects an edge without one — an unlabelled mechanism should
  be a review-console item, not a runtime surprise.

---

# D7 — Two mechanisms collapsed into one by sort order

## What is wrong

CEAT's two channels carry different `mechanism_id`s:

| channel | share of basket | mechanism |
|---|---|---|
| `input:crude_derivative_rubber` (carbon black + chemicals) | **22.8%** | `ed030571…` |
| `input:crude_derivative_petchem` (tyre cord fabric) | **8.2%** | `ca78e5c5…` |

`CompanyImpact` holds a **single** `mechanism_id`. It resolved to `ca78e5c5…` —
the **petchem** edge, the smaller channel — and the section key inherited it. The
rubber edge, carrying nearly three times the exposure, does not appear in the
section key at all. The selection is a consequence of signal sort order, not of
materiality, and nothing in the record says a second mechanism existed.

## Why it matters

* The company is filed under the wrong family. A user looking at a tyre-cord
  section sees CEAT; the carbon-black section does not exist.
* §7.3 requires the four separation fields to be independent and explicit.
  `mechanism_id` is being silently reduced from a set to a scalar, and the
  reduction rule is "whatever sorted first".
* It is not detectable from the output — there is no field that says "this company
  had 2 mechanisms and we published 1".

## What a fix must satisfy

* Either `CompanyImpact` carries the set of mechanism ids and sectioning places the
  company in each relevant section, or the reduction is by an explicit, documented
  rule (largest |Δ| contribution) **and the discarded mechanisms are recorded on
  the impact**. Silent selection by sort order is the defect regardless of which
  is chosen.
* Whatever is chosen must be deterministic and stated, since the reducer's
  contract is byte-identical output for the same signal set in any order.

---

# D9 — `materiality` means two different things in one payload

## What is wrong

From the emitted CHANNEL signal:

```jsonc
{
  "channel_id": "input:crude_derivative_petchem",
  "materiality": "MEDIUM",              // this channel alone, -3.36%
  "delta_ebitda_pct_p50": -3.363738,
  "sensitivity": {
    "bucket": "HIGH",                   // the company, all channels, -12.68%
    "delta_ebitda_pct": {"p50": -12.681887}
  }
}
```

Same object, two scopes, and the channel-level field is named `materiality` while
the company-level one is named `bucket`. A consumer that reads `materiality` off a
channel and renders it beside a company-level band shows `MEDIUM` next to −12.7%.

## What a fix must satisfy

* Distinct names by scope (`channel_materiality` / `company_materiality`), or an
  explicit `scope` field. Naming is the whole fix.
* W3's contradiction test should be extended to cover **two representations of
  materiality within one record**, not only across records.

---

# D8 — `driver_ranking` degenerates to a single driver

Recorded for completeness; **not in the owner's priority list**, and already
predicted in ADR-001 §1.5.

`hedge_ratio` resolved to a disclosed zero with a **zero-width band**
(`band_width × 0 = 0`), so it contributes no variance. Variance attribution
returned `pass_through: 1.0000` and nothing else. Task 2.3 specifies "top 3
drivers" as a product feature; the run produced one, on a company whose magnitude
most needs explaining.

This is not wrong arithmetic — with one varying parameter, one driver is the
correct answer. It is a **product** defect: the feature degrades to uselessness in
exactly the common case (few parameters, some of them precisely known), and the UI
has no copy for "there is only one thing driving this". Note that D5's elasticity,
if added, would itself become a second driver and partly dissolve this.

---

# Rollback of the run's data — what was deleted and what was kept

Executed 2026-08-17 on the owner's instruction. Pre-rollback backup:
`backend/newsflo.db.bak-20260817-prerollback`.

**DELETED — 2 rows.** Both `pass_through_curve` rows. The owner rejected the
`reviewed_by` signature: the curve's *level* rested on an undisclosed whole-book
assumption (that CEAT's 10% replacement price increase represents the full revenue
base) that no filing states, and the derivation had not been read by the person
whose name was on it. **The finding is kept; the data is discarded.**

**CORRECTED — 2 rows.** Both `company_modifier` rows had `effective_to = NULL`,
which was set so the run would compute. That was an assertion beyond the source:
the SEBI LODR disclosure covers **FY 2025-26**. `effective_to` is now
`2026-03-31`, matching the disclosure. The rows are otherwise unchanged and are
genuinely filed-sourced.

**KEPT — 5 rows.**

| Rows | Why kept |
|---|---|
| `company_financials` ×1 | Read straight off the AR MD&A P&L table, standalone, FY2025-26 — printed figures, no derivation, no assumption. |
| `company_modifier` ×2 | `hedge_ratio = 0.0` is a **positive disclosure of zero** under SEBI LODR Reg 34(3), verbatim, corroborated by note 45(iv). Filed-sourced. Now correctly effective-dated. |
| `mechanism_edge` ×2 | `AUTHORED`, `review_status = 'PENDING'`, `reviewed_by = NULL` — queued for the owner's approval exactly as requested. **D2 means these are currently publishable despite being unreviewed; with the curves gone nothing publishes, so the hazard is dormant, not fixed.** |

**Verified after rollback:** CEAT abstains again on both `as_of = 2026-08-17` and
`as_of = 2026-03-31` — `0 channels, 0 signals`, `MISSING_ROW(pass_through)` on both
tags, `no_ebitda=False` (the retained financial row resolves correctly),
`exposure_stale=False`.

**Not touched:** `companies.sector`, every other company, and any sector-median
curve — none was ever written.
