# ADR-001: Exposure is not estimated econometrically

Date: 2026-08-17 · Status: **REJECTED AS PROPOSED** · Supersedes:
`docs/v5/amendments/AMENDMENT-002-econometric-exposure.md` (retained as the
working argument, not as the record)

Root cause axis: **`data`**. Under EXECUTION_CONTRACT §7.2 that is sufficient
on its own: *"If ROOT CAUSE AXIS is anything other than architecture, the
change is rejected and the corresponding data ticket is raised instead."*
Three substantive objections stand behind the procedural one, and objection 3
is decisive.

**Both parts are now rejected.** The amendment as proposed
(`measurement = 'ECONOMETRIC'` on `company_exposure`), and the redirect that
aimed the same estimator at `pass_through_curve`. The redirect was recorded as
DEFERRED-PENDING-BACKTEST when this ADR was first written; the back-test ran
the same day and failed on its own nominated test case, so the status was
amended to REJECTED on the owner's ruling. See
[The redirect — REJECTED](#the-redirect--rejected).

---

## Context

The crude ripple-exposure bootstrap (DATA_GAPS §14) acquired the latest
annual report for **52 listed companies across 6 ripple families** — 52 of 52,
no acquisition failures — and produced a usable input-cost share for **9**.
Seven of those nine are logistics, where the base is `TOTAL_COST` against
Schedule III expense lines that are mandatory. Outside logistics the result is
**2 companies of 45** (CEAT, Savita Oil), or **4 rows of a possible ~45**.

The cause is structural and is not an extraction defect. Schedule III of the
Companies Act 2013 requires "Cost of materials consumed" as one line; the
Schedule VI-era disclosure of consumption by class of raw material is gone.
A company that itemises rubber, carbon black and fabric is volunteering, and
~96% of the sample does not.

The proposal: add `measurement = 'ECONOMETRIC'` to `company_exposure`;
estimate exposure by regressing a company's quarterly gross-margin ratio on
the relevant commodity price; read the coefficient as the net elasticity
already after pass-through and hedging; take the band from the standard
error; map a CI crossing zero onto the existing Phase 2 sign-consistency rule.

**A correction to the amendment that must not be lost.** The amendment's §6
compared "an econometric estimate" against "a filed figure" and concluded the
filing wins on provenance. That comparison is wrong about this repo.
**`company_exposure` contains ZERO rows with `measurement = 'FILED'`.** All
eleven rows, CEAT and Savita Oil included, are `ESTIMATED`: a ratio computed
from two printed figures, not a share any company stated. The real comparison
is *an estimate built from two printed accounting figures* against *an
estimate built from a fitted coefficient* — closer than the amendment
claimed, and it strengthens the proposal rather than weakening it. The
rejection does not rest on that comparison.

---

## Decision

**Do not add `measurement = 'ECONOMETRIC'`. Do not build the estimator
against `company_exposure`.** The V5 architecture is unchanged. The
corresponding data ticket (DATA_GAPS §14) stays open.

### Objection 1 — the dependency inversion

The proposal buys a new route to the input that has **stopped binding**. Run
against the live database on 2026-08-17, before any curve existed:

```
[v5-sensitivity] ABSTAINED company_id=186 tags=input:crude_derivative_rubber
                 uncomputable=input:crude_derivative_rubber=MISSING_ROW(pass_through)
channels 0
```

The exposure row was present. The system still said nothing, because
`pass_through_curve` was empty. Exposure shares are no longer the constraint;
pass-through curves are. See the postscript.

### Objection 2 — it requires more data than the route it replaces, and the history is not there

`company_financials` was empty when this was raised. The regressor needs
20–40 quarters of P&L per company. What actually exists, measured rather than
assumed:

| source | quarters for CEAT | quarters for Savita Oil |
|---|---|---|
| yfinance — **the only quarterly fundamentals source wired into this repo** (`app/companies/`) | **5** | 5 |
| NSE result XBRL, contexts declared in the document (strict) | **9** | **10** |
| NSE result XBRL, plus facts pointing at an **undeclared** context id, read under a naming convention | **25** | **28** (standalone) / 13 (consolidated, the basis the ledger row uses) |
| NSE index *claims* | 67 | 80 |

The gap between the last two rows is not a parser defect. **42 of CEAT's 67
listed XBRL URLs and 52 of Savita's 80 return HTTP 404** — NSE lists the
filing and no longer serves the file. Of those that do resolve, roughly two
thirds reference a context id (`OneD`) that the document never declares: the
numbers are present, the period they belong to is not. Reading them means
assuming a naming convention observed in newer files, which is an inference
about the document rather than a statement in it. **Nothing before 2018 is
retrievable at all.**

So the honest ceiling on this method today is ~25 quarters per company, of
which ~two thirds rest on a convention assumption — and the wired-in source
gives 5.

### Objection 3 — DECISIVE — it collapses Phase 5's independence, and it is the correlation-miner the addendum forbids

Two halves, both structural.

**(a) Checker and checked would share data and method.** Phase 5's
`transmission_empirical` exists to be an *independent* cross-check: it fits
history and asks whether the fundamental read AGREES with it, and a CONFLICT
blocks PRIMARY (spec §10.2–10.3, `config/gates.yaml`
`allowed_empirical_status: [AGREE, NO_DATA]`). If Phase 1's exposures are
themselves fitted from overlapping history by similar means, the two estimates
stop being independent. `empirical_status` trends to **AGREE by
construction**, the four-outcome cross-check stops discriminating, and the
system loses its only mechanism for noticing that its fundamental story is
contradicted by what actually happened. Agreement between an estimate and
itself is not evidence, and it would *look* exactly like corroboration in
every published record.

This is not a schema conflict to be engineered around. It deletes a control
while appearing to add coverage, and it does so invisibly — which is the worst
property a change can have in this system.

**(b) It is the thing NEWSFLO_V5_ADDENDUM_RIPPLE_COVERAGE §A3.2 exists to
prohibit.** A3.2: *"An empirically-discovered relationship may never publish
until a named mechanism exists... Skipping the middle steps turns the product
into a correlation miner. A ripple company published with a CAR statistic and
no mechanism is exactly the 'faulty finding' a senior analyst would destroy
you for — 'you're showing me a chart, not a reason.'"* And the hard rule:
`SECONDARY_RIPPLE` requires a non-null `mechanism_id`.

An econometric exposure row IS a discovered correlation. A3.2 routes such a
thing through a gap queue to a human-authored mechanism edge before it may
publish; the proposal routes it straight into the ledger, where it becomes
the authorising record for a channel. And `mechanism_edge` is empty
(DATA_GAPS §7), so even a perfectly-fitted coefficient could not legally
publish at the only tier it would be eligible for.

### What is NOT wrong with the proposal

Recorded so the rejection is not read as a dismissal.

* It respects invariant 3. Regressing *share prices* on crude would breach
  "market price movement never influences fundamental direction"; regressing
  the **gross-margin ratio**, an accounting quantity, does not. Whoever
  drafted it understood the constraint.
* It replaces a *stipulated* band (`band_width[source]`, one policy constant
  for every FILED parameter in the system) with a measured sampling
  distribution. That is a real improvement in kind.
* Simultaneity is genuinely not a problem: one Indian mid-cap does not move
  Brent.
* Quarterly XBRL is structured where the raw-material breakup is unstructured
  and mostly absent. Acquiring it is worth doing on its own merits, which is
  why the data ticket is raised rather than closed.

### W-criteria

Only **W6** (ripple family recall) moves materially, by making axis `C`
depend on data that can be bought rather than data companies choose to print.
**W1** is mixed: the band improves, "source URL" degrades to a dataset id.
**W11** — the real goal — is ambiguous and plausibly negative: it trades an
unanswerable *silence* ("you have no view on paints") for an unanswerable
*number* ("your elasticity is 0.34 — over what window, and does it survive
dropping FY21?"). **W4/W5/W8 cannot improve**, because such rows would be
capped below PRIMARY by design. W7 (ripple precision) is an unbounded risk:
more ripple companies on weaker evidence is the classic way a recall gain
buys a precision loss.

---

## Consequences

* No change to `MEASUREMENTS`, no new column, no estimator. The V5 phase order
  and the frozen architecture stand.
* DATA_GAPS §14 remains the open ticket, and gains a sub-ticket: **acquire
  quarterly financials into `company_financials`** (BSE/NSE result XBRL). It
  is a prerequisite for every version of this idea and it is useful without
  any of them — `ebitda_ttm()` reads that table and returns `None` today,
  which abstains every company on its own.
* **Cost avoided: 11–15 person-weeks** (revised up from the amendment's 9–12,
  because `company_financials` is empty and the wired-in quarterly source
  returns five quarters, so the acquisition block is larger than estimated).
* This decision may be reopened only under §7.3, and only on a *second*
  failing measurement — specifically, curves populated and W6 still failing.

### Spec defect to fix regardless of this decision

**`share_of_base` must never hold a net elasticity, and that must be enforced
by a database CHECK, not by a docstring.**

This is independent of whether an econometric route is ever built. §5.1's cost
formula is

```
-base × share × delta × (1 - pass_through) × (1 - hedge_ratio) × ownership
```

Any value placed in `share_of_base` that is *already net of pass-through and
hedging* is then discounted by `(1 - pass_through)` and `(1 - hedge_ratio)` a
second time. The failure is silent, it biases toward smaller and therefore
more plausible-looking numbers, and nothing in the output reveals it. The
same trap is open today to any future measurement class, any import script,
and any reviewer who edits `share_of_base` in the review console believing it
means "sensitivity".

Required, as a Phase 2 ticket:

1. A DB-level CHECK — the same trigger substitution 0012/0013 use for SQLite —
   binding `share_of_base` to the interval a *share* can occupy and refusing
   any `measurement` outside the set that means "a fraction of a stated base".
2. Should a net-sensitivity class ever be admitted, it takes a **separate
   column and a separate channel formula**, never `share_of_base` with a
   convention attached.
3. A test that a row whose measurement denotes a net elasticity cannot
   resolve `pass_through` or `hedge_ratio` at all.

**Owner: Phase 2.** Recorded here because it was found by this analysis and
would otherwise be lost with the rejected proposal.

### The redirect — REJECTED

*Status amended 2026-08-17, later the same day, on the owner's ruling. It was
recorded as DEFERRED-PENDING-BACKTEST when this ADR was written; the back-test
was the stated reopening condition, it has since run, and it failed. The
earlier status is left visible here rather than overwritten, because the
sequence — deferred, tested, rejected — is the part worth keeping.*

The proposal was to point the same machinery at `pass_through_curve` instead
of `company_exposure`. It remains the better-aimed idea: that table already
has `basis: ESTIMATED` and a `curve_needs_review` CHECK, so it needs no
amendment — no new enum, no `share_of_base` semantics change, no
double-discount, no collision with the verbatim gate, and much less Phase 5
contamination, because a pass-through parameter is one factor inside the
fundamental read rather than the whole of it. Roughly 4–5 person-weeks against
11–15.

**It is rejected anyway, because the estimator fails before the destination
matters.** Evidence: `docs/v5/amendments/AMENDMENT-002-BACKTEST.md`, run on
CEAT and Savita Oil — the two companies in the ledger with a share derived
from named commodity lines, and Savita the easiest case that exists at 86.1%
base oil in a near pure-play.

**Reason 1 — DECISIVE — the fitted lag profile is not a curve and cannot be
made into one.** §4.2 requires *cumulative fraction recovered*: monotone
non-decreasing from zero. What the distributed-lag specification returns is
neither monotone nor consistently signed:

* Savita standalone: lnB(t) +0.005 (ns), lnB(t−1) +0.036 (ns),
  lnB(t−2) **−0.199** (p < 0.001)
* Savita consolidated: lnB(t) +0.130 (ns), lnB(t−1) **+0.211** (p = 0.03),
  lnB(t−2) **−0.256** (p = 0.003)
* CEAT relaxed: lnB(t) −0.020 (ns), lnB(t−1) −0.105 (p = 0.07),
  lnB(t−2) +0.039 (ns)

The two Savita bases disagree on the sign of the one-quarter lag. A cumulative
recovery fraction cannot go up, then down, then up. **No §4.2-conformant curve
can be read off these fits at all** — not a noisy one, not a wide one. This is
what makes the redirect dead rather than merely unproven: moving the target
from `company_exposure` to `pass_through_curve` changes where the output would
be stored and changes nothing about whether the estimator can produce it.

**Reason 2 — it does not recover a known quantity on the easiest available
case.** Savita's filed share predicts β ≈ −0.70. The fit on the basis the
ledger row actually uses returns **+0.274, p = 0.007** — significant, and the
wrong sign, for a company whose cost is 86% base oil — with an implied
pass-through of **1.47**, outside the parameter's domain. The sign flips to
−0.089 on the 28-quarter standalone window. A method that returns a confident
wrong-signed answer on the easiest case cannot be trusted on the hard ones,
and there is no diagnostic available at scale that would have caught it: only
the filed share revealed it, and the filed share is exactly what is missing
for the companies this was meant to cover.

**Reason 3 — the levels results are spurious.** Both companies' coefficients
vanish under first-differencing — CEAT R² 0.33 → 0.016 with the sign
reversing, Savita R² 0.20 → 0.001, p = 0.88. Regressing a bounded ratio on a
trending price over ~25 quarters is the textbook co-trending setup. The one
specification robust to that critique returns nothing for either company.

Underneath reasons 2 and 3 is an identification problem that more data does
not fix: at quarterly frequency a single coefficient cannot separate the
`INPUT_COST` channel from `INVENTORY_REVALUATION`, which spec §8 says
dominates the immediate horizon for exactly this kind of commodity processor.
Savita's positive coefficient is probably a real inventory gain, correctly
measured and wrongly attributed.

**The parser bug is part of this record, not an aside.** The first version of
the back-test's XBRL reader used regex over `<xbrli:context>` and silently
dropped **16 of CEAT's 25 resolvable filings**. Had it not been caught by
opening a specific failing file, the run would have reported those quarters as
*missing data* — a false finding about the world produced by a tooling limit —
and CEAT's levels R² of 0.33 with a plausible implied pass-through of 0.59
would very nearly have been reported as **evidence that the method works**.

That is not merely an embarrassment to disclose. It is a property of the
method. An econometric estimate's value is contingent on the whole chain that
produced it — which files resolved, which contexts parsed, which window was
chosen, which specification was run — and every link is silently substitutable
by a bug. **A filed figure is not fragile in this way.** CEAT's ₹1,43,495
lakhs of carbon black is checkable against a page by a human in ten seconds,
and a parser defect that mangles it produces a number that fails the verbatim
gate rather than a number that looks reasonable. The fabrication guard has a
mechanical test for a bad excerpt; it has none for a bad regression, and this
run is the demonstration of why that asymmetry matters more than the
provenance argument the amendment made.

**Consequences of rejecting the redirect.** Curves must come from sources that
carry an excerpt and a page, so they pass the gate that already exists:
contractual and formula pricing (`FILED`, uncapped), earnings-call commentary
(`DISCLOSED_CALL`, uncapped), dated exchange price-increase announcements
(`FILED`). Enumerated with costs in `docs/v5/CURVE_BOOTSTRAP.md`. Reopening
this requires a *different* estimator with a stated answer to reason 1, not
more quarters of the same one.

---

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| Accept `ECONOMETRIC` capped below PRIMARY | Does not answer objection 3. A capped row still enters `company_exposure`, still authorises a channel, and still contaminates the Phase 5 cross-check that gates the tier above it. |
| Accept it as a *cross-check* against filed rows, never as a publishing basis | Genuinely attractive, and it is the sensible end state — but it is Phase 5's job, not Phase 1's. Building it into the ledger is the wrong table for the right idea. |
| Sector-median exposure shares instead of fitted ones | Already available (`params._sector_median`) and already capped at SECTOR_PROXY / grade C, `allow_sector_proxy: false` at PRIMARY. It needs peers with rows, and with 11 rows across 2 sector buckets there are effectively no peers. Not a substitute for coverage. |
| Earnings-call transcript extraction for shares | Not rejected — **untried and cheaper than a regression**. Managements do state raw-material basket splits verbally. Weaker provenance than a filing, stronger than a fit, and it reuses the existing verbatim gate unchanged, because a transcript has an excerpt and a page. Recorded as the alternative worth trying next. |
| Do nothing about coverage | Rejected. W6 fails and the ticket is real. The disagreement is about which table to aim at. |

---

## Postscript — what actually blocks output, traced through the code

Written the same day, after the decision, because the trace is what makes the
dependency inversion concrete.

A `COST` channel needs **three** things, and `params.resolve_param` has no
step 4 — "nothing" raises rather than defaults:

1. `pass_through` — from `pass_through_curve`, company-level, or a
   sector-level curve, or the median of sector peers' curves.
2. `hedge_ratio` — from `company_modifier` (`parameters` JSON carrying both
   the value and a `measurement`), own or peer-median.
3. `EBITDA_ttm` — `engine.ebitda_ttm()` reads `company_financials`, and
   returns `None` with no substitute.

With all three present for one company on one tag, the pipeline runs. Measured
on CEAT after a hand-authored proof-of-life (EBITDA row + two FILED
hedge_ratio modifiers at 0.0, each carrying its filing excerpt + two ESTIMATED
curves with `reviewed_by` set):

```
horizon   0d  delta_ebitda = -2,095,450,000  grade_cap=D
horizon  30d  delta_ebitda =   -942,952,500  grade_cap=D
horizon  60d  delta_ebitda =   -471,476,250  grade_cap=D
horizon  90d  delta_ebitda =             -0  grade_cap=D
horizon 180d  delta_ebitda =             -0  grade_cap=D
```

Three things this proves, none of which needed an amendment:

* **The end-to-end path works.** From a filing page to a signed rupee delta
  with a horizon profile, on real data, in hours.
* **`grade_cap = D` binds**, from two independent axes — the exposure's
  `measurement = ESTIMATED` and the curve's `basis = ESTIMATED` → `MODELLED`.
  PRIMARY admits `[A, B, C]`. These rows cannot lead a publication, as
  intended.
* **The curve is the whole answer.** This one reaches 1.0 by 90 days, so the
  90-day and 180-day impacts are exactly zero and emit no signal. Change the
  curve and every published number changes. That is why a curve must be
  sourced and not chosen — and why the redirect's back-test mattered.

**State note.** The two proof-of-life curves were **removed from
`pass_through_curve` after this run** (the table is empty again as of the same
day), so the numbers above are a *measurement taken on 2026-08-17*, not a
description of what the database now holds. Removing them is the right call:
they were `basis = ESTIMATED`, hand-drawn, and holding a shape nobody sourced
is what `docs/v5/CURVE_BOOTSTRAP.md` §5 argues against. The measurement stands
regardless — the path works; the input is missing.
