# ADR-DRAFT: a shock→derivative elasticity-and-lag curve

**Status:** PROPOSED · **Date:** 2026-08-17
**Raised by:** defect **D5** in `docs/v5/defects/DEFECTS-001-ceat-proof-of-life.md`
**Related:** `ADR-001-econometric-exposure.md` (REJECTED) — read the §A3.2 section
below before citing this document in support of reopening that one.

**Nothing here is implemented.** No table, no estimator, no data fetched. No HS
code below was queried; every factual claim about trade codes, import shares and
Indian market structure in this document is **from the author's background
knowledge and is explicitly marked as unverified**. The feasibility probe in §5 is
the thing that would verify it, and it has not been run.

---

## THE DEFECT THIS ANSWERS

Spec §5.1 multiplies `shock_delta_pct` — a move in **Brent** — by
`share_of_base` — the company's spend on **a derivative of Brent**. There is no
term between them. The formula therefore asserts, nowhere in writing, that every
crude derivative moves 1:1 with crude and does so instantly.

That is a hardcoded coefficient of 1.0 with no source, no band, no basis and no
review, sitting multiplicatively in every ripple magnitude the system will ever
publish. **The choice in front of us is not "coefficient or no coefficient". It is
"a sourced, banded, grade-capped coefficient" against "an unsourced hardcoded
1.0".** That framing is the strongest thing this proposal has and it should be
kept in view through everything that follows.

---

## THE PROPOSAL

A new table, keyed on `(shock_variable, exposure_tag)` — **never on company**:

```
derivative_linkage
  linkage_id, shock_variable, exposure_tag,
  points      jsonb   -- [{"lag_days": 0, "elasticity": 0.15}, ...]
  basis       text    -- AUTHORED | FILED | DISCLOSED_CALL | ESTIMATED
  band, r2, n, window, specification, estimator_version, source_url,
  as_of_date, reviewed_by
```

applied **before** §5.1, never inside it:

```
effective_delta_pct = shock_delta_pct × elasticity(horizon_days)
ΔEBITDA_inr = − base × share_of_base × effective_delta_pct
              × (1 − passthrough(h)) × (1 − hedge_ratio(h)) × ownership
```

Estimated, where estimation is the chosen basis, by regressing **customs import
unit values** for the derivative's HS code against the shock variable's price
series.

Missing linkage → `InsufficientParameterData` → UNCOMPUTABLE → abstain. There is
no step 4, exactly as for pass-through.

---

# PART 1 — THE CASE FOR

## 1.1 It replaces an unsourced constant, which is the only defect on the D-list that makes the numbers wrong

D1, D2, D3, D4, D6, D7, D9 all concern how a number is written, reviewed, grouped
or labelled. D5 concerns whether the number is right. The CEAT run's headline —
**−12.7% of EBITDA at the IMMEDIATE (5-day) horizon** — was computed with
elasticity 1.0 and lag 0, which is the least defensible pair available: it assumes
carbon black repriced fully within five days of a Brent move. Nobody believes that,
and nothing in the record says we assumed it.

## 1.2 It is cheap per unit of coverage

The parameter is a property of a commodity chain, not of a company. **One row
serves every company carrying the tag.** For the crude ripple families that is
roughly six to nine rows against a target universe of ~250 companies — the
inverse of the economics that sank ADR-001, where every company needed its own
20–40 quarters.

## 1.3 The failure it fixes is the one an analyst reaches for first

`WRONG_MAGNITUDE` in the §6 objection taxonomy is *"the number is off by an order
that changes the conclusion"*. A missing elasticity is exactly that, and `NAIVE`
follows immediately: an analyst covering tyres knows carbon black contracts
reprice quarterly on a formula, and a system that moves them 10% in five days
reads as someone who has never seen a purchase order.

## 1.4 It is expressible as a curve, which the architecture already supports

`evaluate_curve` in `params.py` interpolates piecewise-linearly, holds the
endpoints and never extrapolates. The horizon vector already samples every
parameter at its own day count. The elasticity slots into machinery that exists.

## 1.5 The regressor is free and long

Brent and WTI daily series are available at no cost and ~19–26 years deep
(verified in ADR-001's appendix: `BZ=F` 4,741 bars from 2007-07-30, `CL=F` 6,523
from 2000-08-23). Indian customs trade statistics are published monthly and are
public. Neither side of this regression requires a purchase, which is not true of
any other route considered so far.

---

# PART 2 — THE CASE AGAINST

Argued at the same length and with the same intent as ADR-001's Part 2.

## 2.1 HS code granularity — the codes mix grades with different crude linkage

**Unverified; this is the author's understanding and the probe in §5 exists to
check it.**

| Tag | Likely heading | The granularity problem |
|---|---|---|
| `input:crude_derivative_rubber` (CEAT: carbon black + rubber chemicals) | **HS 2803** — carbon (carbon blacks and other forms of carbon, n.e.s.) | One heading covers **rubber-grade furnace blacks** (N330, N550, N660 — feedstock CBFS, a refinery residual), **acetylene black** (feedstock acetylene/calcium carbide — *not* a crude residual in the same way), and **specialty/pigment blacks** at several times the unit value. India's ITC-HS 8-digit splits exist (carbon black / acetylene black / other) but the value share between them moves, so a UV series over the whole heading is a **moving weighted average of chemically different products**. Mix shift is indistinguishable from price change. |
| same tag, "rubber chemicals" half | scattered across **HS 2902 / 2921 / 2925 / 3812** (accelerators, antioxidants, antiozonants, vulcanisation packages) | **There is no single code.** The ledger row merges carbon black (₹1,43,495 lakh) with chemicals (₹66,050 lakh) because the filing merges them. No HS aggregation reproduces that basket without an authored weighting — which is itself a parameter nobody has. |
| `input:crude_derivative_petchem` (CEAT: tyre cord fabric) | **HS 5902** — tyre cord fabric of high-tenacity yarn | Splits nylon / polyester / **viscose rayon**. Viscose is cellulosic — **not crude-linked at all**. A UV over the heading contains a component whose true elasticity is ~0. |
| synthetic rubber, if the "Rubber" line is ever split | **HS 4002** | SBR (styrene + butadiene), BR (butadiene), IIR/halobutyl (isobutylene + isoprene), NBR (butadiene + acrylonitrile), EPDM (ethylene + propylene). **Five different monomer chains, five different crude linkages, one heading.** And HS 4001 next door is natural rubber, which is agricultural. |
| `input:base_oil` | **HS 2710.19** | Group I / II / III base oils have materially different premia and the mix has shifted structurally toward Group II/III over the past decade — a **trend in the mix that a regression will read as a trend in price**. |

**The general form of the objection:** an HS code is a *tariff* classification, not
a *chemistry* one. It is designed to make customs collectable, not to isolate a
feedstock. Every code above bundles products whose elasticity to crude genuinely
differs, and the bundle weights move over exactly the horizon the regression needs.

**And note where this bites hardest: the tag CEAT actually carries.** The two rows
in the ledger are the merged carbon-black-plus-chemicals row and the tyre-cord row.
Neither maps cleanly onto one code. The proposal is weakest precisely on the
company it was raised from.

## 2.2 THE CENTRAL PROBLEM — import unit values are landed costs, and the confounds are same-signed

A customs unit value is `assessable (CIF) value ÷ quantity`. Inside it:

1. **The commodity's own FOB price** — the thing we want.
2. **Ocean freight and insurance** — and ocean freight is **bunker fuel**, which is
   a crude derivative.
3. **The exchange rate**, if the series is read in rupees.
4. **Origin mix** — a shift from Korean to Chinese supply changes the UV with no
   price change.
5. **Grade mix within the code** — §2.1.
6. **Contract-versus-spot mix**, and the lag between contract date and bill-of-entry
   date.
7. **Antidumping and safeguard duties**, where they change assessable value
   treatment or reroute origin.

**Why this is worse than ordinary measurement error, and why it is the reason to
be sceptical rather than merely careful:**

> **Confounds 2 and 3 are both positively correlated with crude.** Bunker prices
> rise with crude. The rupee depreciates against the dollar when crude rises,
> because India imports ~85% of its oil. So a naive fit of a rupee-denominated
> import UV on Brent will attribute freight inflation *and* FX depreciation to the
> commodity's crude linkage. **The bias is not zero-mean and it is not
> conservative — it inflates the elasticity, in the same direction, every time.**

This is the mirror image of ADR-001 §2.5(4), where measurement error attenuated
toward zero and the error was at least in the safe direction. Here it is not.

**Partial mitigations, and what each costs:**

* **Fit in USD, not INR.** Indian trade statistics are published in both. This
  removes confound 3 from the regressor side — but the company pays in rupees, so
  the rupee elasticity is what the P&L feels. Putting the FX back in means either
  double-counting against the existing `fx:usd_cost_share` channel or deciding,
  explicitly, which channel owns the currency. **That decision does not currently
  exist anywhere in the spec.**
* **Control for freight** with a Baltic index or a bunker series. Adds a regressor,
  and the control is itself crude-driven, so it is collinear with the variable of
  interest. Collinearity inflates the standard error rather than the point
  estimate — which at least shows up in the band.
* **Restrict to a single origin and a single 8-digit line** to kill mix. Costs
  sample size, and the surviving series may be thin or discontinuous.

None of these is free, all of them add regressors, and §2.5 explains why regressors
are expensive here.

## 2.3 Import share — which tags this breaks

If domestic production dominates consumption, an import UV describes the marginal
importer, not the market.

**Author's understanding, unverified, ordered from worst to best:**

| Tag | Import share of Indian consumption | Verdict |
|---|---|---|
| **`input:crude_derivative_rubber`** (carbon black) | **Low.** India is broadly self-sufficient — Phillips Carbon Black, Birla Carbon, Himadri — and has run **antidumping duties on Chinese and Russian carbon black**. Imports are a protected, distorted residual. | **Breaks.** The UV reflects duty-inclusive marginal supply, not what CEAT pays a domestic supplier on a quarterly formula. And this is CEAT's largest tag. |
| **packaging films (BOPET/BOPP)**, HS 3920 | India is a **net exporter**. | **Breaks.** The import tail is thin and unrepresentative by construction. |
| **`input:crude_derivative_petchem`** (tyre cord) | Mixed; substantial domestic capacity (SRF, Century Enka). | **Doubtful.** |
| **synthetic rubber**, HS 4002 | Higher — butyl and EPDM are largely imported; SBR/PBR partly domestic. | **Plausible**, grade-by-grade. |
| **`input:base_oil`**, HS 2710.19 | **High.** India is a large structural importer of base oil. | **Best case.** This is why it is the positive control in §5. |

**So the two tags the CEAT run actually used are the two the method is least
likely to serve.** That is not a detail; it is close to disqualifying for the
crude-ripple families as a whole, and it is discoverable only by looking, which
§5 proposes to do.

## 2.4 Domestic pricing is formula or negotiated, not import parity

Even where import share is adequate, the transaction price a listed company pays
may not track it:

* **Carbon black** in India is sold to tyre makers on **quarterly negotiated
  formulae** referenced to CBFS, with volume commitments. The formula is the
  transmission mechanism; the import UV is a different market.
* **Base oil** is closer to import parity, which again makes it the good case.
* **Tyre cord** is sold on annual contracts with periodic resets.

Where a published formula exists, **an authored linkage built from the formula is
better evidence than a fitted one** — it is a stated mechanism rather than an
inferred correlation, it needs no sample, and it survives regime changes that
break a fit. This is a real argument that the *estimator* is the wrong default
even if the *table* is right.

## 2.5 Lag estimation — distributed lag versus fixed offset, and the noise trap

The horizon vector needs elasticity at 5, 90 and 270 days. Monthly trade data
gives ~3 usable points across that span, and the IMMEDIATE horizon (5 days) is
**below the sampling frequency of the regressand entirely** — a monthly series
cannot speak about a five-day response, and the IMMEDIATE number is the one the
CEAT run led with.

* **A fixed offset** (one lag, chosen) is cheap and honest but assumes the whole
  response arrives at once, which contradicts why we wanted a curve.
* **A distributed lag** (0–3 or 0–6 months, unrestricted) spends a degree of
  freedom per lag on a noisy regressand and will produce a wiggly, alternating-sign
  lag profile that is mostly sampling noise. Polynomial (Almon) restriction tames
  it at the cost of imposing a shape nobody sourced.
* **Searching over lag length and picking the best fit is the classic way to fit
  noise here**, and with one tag × one shock the multiple-testing problem is small
  enough to be invisible and large enough to matter.

**The only defensible discipline:** pre-register the lag structure per tag from
contract knowledge (quarterly formula → 90-day centre of mass; annual contract →
longer), fit only that, and report the fit as a **check on an authored shape**
rather than as the source of it. Which is, again, an argument for authoring first
and fitting second.

## 2.6 Markets and regimes — naming every tag, because fitting an elasticity on a regime models a policy as a price

This is the objection I raised against myself in D5 and it deserves the explicit
list the brief asked for. **Classification is the author's; each needs the owner's
confirmation.**

### Markets — an elasticity is the right object

| Tag | Note |
|---|---|
| `input:crude_derivative_rubber` | market-priced, but see §2.3 — domestic formula pricing behind an ADD wall |
| `input:crude_derivative_petchem` | market-priced along the PX/PTA/MEG chain |
| `input:base_oil` | market, import-parity linked — the cleanest case in the ledger |
| `input:aluminium`, `input:copper` | LME-linked. Genuine markets, but the shock variable is the LME price, **not crude** — they need their own linkage rows, not crude ones |
| `input:steel_flat`, `input:steel_long` | market, with an antidumping/safeguard overlay that is a regime element inside a market |
| `input:palm_oil` | market price, **but Indian import duty is changed frequently as policy** — a hybrid |

### Regimes — an elasticity would be a category error

| Tag | Why it is a regime |
|---|---|
| **`input:freight_diesel`** | Retail diesel is nominally deregulated and in practice **managed**: OMC price revisions are suspended around elections and during crude spikes, and excise is adjusted to absorb moves. The crude→pump-price relation is a **policy function**, not an elasticity, and fitting one would estimate the average of past political decisions and call it physics. **Phase 4 modifier, not a linkage row.** |
| **`input:atf`** | Set monthly by OMCs on a published import-parity formula. Because the formula is *published*, this is the one regime where an **authored, exact** linkage is available — and it must be authored from the formula, never fitted. |
| **`revenue:gas_realization_apm`** | Administered ceiling, government-set. Already Phase 4's territory. |
| **`revenue:marketing_margin_retail_fuel`** | The regime *is* the mechanism — this is the OMC MIXED case §8 exists for. |
| **`revenue:crude_realization`** | Market price with the **SAED windfall levy** on top, which is a threshold-capture regime already registered in `policy_modifiers.yaml`. |
| **`input:sugar`, `input:wheat`** | FRP/MSP and OMSS releases. Administered floors and government stock policy. |
| **`input:milk`** | Cooperative-set procurement prices; semi-administered, regionally. |
| **`input:fuel_furnace_pet_coke`** | Market price under a **judicially constrained import regime**. Hybrid; the binding constraint has at times been legal, not economic. |

### Neither

| Tag | |
|---|---|
| `input:crude_direct` | elasticity 1.0 **by definition**. Must carry an explicit row saying so rather than inheriting silence — that is the difference between a stated identity and an unstated default, and it is the whole point of the proposal. |
| `input:bought_in_freight`, `input:intermediated_air_capacity` | intermediated services — a purchased freight rate is a supplier's *price*, containing that supplier's own fuel cost, pass-through and margin. Neither a commodity elasticity nor a policy regime. **A third category the proposal does not handle**, and four of the eleven ledger rows sit in it. |

**The consequence of this table:** the proposal covers perhaps six of the twenty-eight
registered tags well, three by authored formula, and leaves the rest to Phase 4 or
to a category that does not exist yet. It is not a general solution to §5.1's gap.
It is a solution for market-priced physical commodities, which is a subset.

## 2.7 The §A2.4 objection, which cuts against this proposal too

ADR-001 was rejected partly on §A2.4: *"Coefficients inform the graph; they do not
set company materiality — that still comes from the filed exposure ledger."*

**Read literally, that sentence forbids this proposal as well.** A fitted
elasticity does not merely inform the graph. It multiplies straight into ΔEBITDA
and therefore sets company materiality, for every company carrying the tag, from a
statistical estimate.

I do not think that reading is fatal, and here is the honest version of why —
including the part that does not favour the proposal:

* **The favourable half.** §A2.4's concern is *substitution*: an industry-level
  coefficient standing in for a company-level disclosure the ledger should have
  had. This does not substitute. The company-level filed share is still required,
  still does all the company-specific work, and the company still abstains without
  it. The elasticity supplies a fact about a commodity that no company-level
  disclosure was ever going to contain.
* **The unfavourable half.** It is still true that a number nobody filed becomes a
  multiplicative determinant of a published magnitude. §A2.4 does not distinguish
  "sets materiality on its own" from "scales a materiality that was otherwise
  sourced", and reading that distinction into it is an interpretation, not a
  quotation.
* **The practical resolution, which is a decision and not an argument:** an
  `ESTIMATED` linkage must cap the channel's evidence grade exactly as an
  `ESTIMATED` exposure row does today (→ D, below PRIMARY), and an `AUTHORED`
  linkage built from a published formula should not. That keeps a fitted
  coefficient out of the tier where precision is promised. **The owner must decide
  whether that is enough; I cannot argue it away.**

## 2.8 Why this genuinely escapes §A3.2 and Phase 5 — stated so it cannot be used to reopen ADR-001

The brief asks for precision here, because the risk is that this document is cited
in six months as "the elasticity ADR shows the objections were soft".

**§A3.2 forbids one specific thing:** an *empirically-discovered relationship*
becoming the reason a company appears on screen, without a human-authored
mechanism. The workflow it mandates is `empirical signal → gap queue → human
authors mechanism → edge reviewed → companies tagged in ledger → publishable`.

**Four properties make the elasticity a different object. All four must hold, and
each is a testable constraint on any implementation:**

1. **It names no company.** The estimated object is a relation between **two
   prices**. The regressand is a customs unit value for an HS code; the regressor
   is a commodity price. Neither is a company, a return, or a margin.
2. **It cannot create a `(company, exposure_tag)` pair.** Tag membership comes from
   the company's own filing and from nowhere else. **Delete every elasticity row
   and exactly the same companies are candidates** — they simply abstain. Delete
   the exposure rows and no elasticity brings anyone back. That asymmetry is the
   test: the elasticity has no discovery power.
3. **It cannot create or authorise a `mechanism_edge`.** The edge remains
   hand-authored and reviewed. The elasticity attaches to an edge that already
   exists; it never justifies one.
4. **Phase 5 stays independent.** `transmission_empirical` fits **a company's
   response** (returns/margins) to a shock. The linkage fits **a commodity price**
   to a shock. Different regressand, different dataset, different frequency,
   different unit of observation. If crude→carbon-black elasticity is 0.6 and
   CEAT's realised historical response still contradicts the fundamental read, the
   CONFLICT still fires and still blocks PRIMARY. ADR-001's decisive objection —
   that checker and checked would be estimated from the same data by the same
   means — **does not arise, because the linkage is not an estimate of what the
   company did.**

**The tripwire, which must be a hard constraint if this is ever built:**

> **`derivative_linkage` may not have a `company_id` column, and no row may be
> conditioned on a company.** The moment a linkage is fitted per company, every
> property above fails at once, Phase 5's independence collapses, and all of
> ADR-001's objections return in full force.

**What this document does NOT establish, stated plainly so it cannot be
mis-cited:** it does not show that ADR-001's objections were weak. ADR-001 was
rejected on (a) §A3.2 tag-assignment silence, (b) §A2.4, and (c) zero quarters of
company margin history. Property 2 above is precisely the thing ADR-001's proposal
lacked, and (c) is untouched — company-level quarterly margin history is still
absent and still not needed here, because this regression never looks at a
company. **A commodity-to-commodity fit being acceptable is not evidence that a
company-level fit is.**

## 2.9 What it does not fix even if it works

The linkage sizes the move in the input price. It says nothing about
`input:bought_in_freight` and `input:intermediated_air_capacity` (§2.6), nothing
about pass-through, nothing about hedging, and nothing about the seven-link chain
in `DATA_GAPS/ceat-proof-of-life.md`. **Adding it to today's database changes no
output at all**, because `pass_through_curve` is empty and CEAT abstains before
the elasticity is ever reached. It is the second parameter needed on a channel
that currently cannot compute for want of the first.

---

# PART 3 — ALTERNATIVES

Because the brief for ADR-001 established that the choice is rarely binary.

### 3.1 Authored cost build-ups — the strongest alternative

Most of these linkages are **known chemistry with known yields**, and the
elasticity follows arithmetically from a feedstock cost share rather than from a
fit. Carbon black is produced from carbon black feedstock oil at a published
approximate yield, and CBFS is a heavy refinery stream that tracks fuel oil. If
the feedstock is a stated fraction of production cost and the feedstock's own
crude linkage is near unity, the derived elasticity is a stated number with a
mechanism, not an inferred one — reviewable by a chemist, stable across regimes,
requiring no sample and no significance test.

**This is `basis = AUTHORED` and it is what §A2.4 would prefer.** It needs the
same table. **Estimated 1–2 pw for the crude families**, versus a data programme
for the fitted route. Its weakness is that the yield and cost-share figures must
themselves be sourced, and they are trade knowledge rather than filings.

### 3.2 Published administered formulae

For `input:atf` and the APM gas tags the transmission is a **published formula**.
Transcribing a formula is not estimation; it is the highest-grade evidence
available for those tags and there is no reason to fit anything. Covers few tags,
completely.

### 3.3 Domestic price series instead of import UVs

Indian domestic price series exist for several of these — industry association
indices, published producer price notifications, and the WPI sub-indices MOSPI
publishes at commodity level. A WPI sub-index for carbon black or synthetic rubber
would sidestep §2.2 entirely: no freight, no FX, no origin mix, because it is a
domestic price. Its weaknesses are its own (index construction, revision, lower
granularity) but they are **different weaknesses from the landed-cost confounds**,
which makes it a genuine cross-check rather than a substitute. **This should be
tested alongside the customs route in the probe, not after it.**

### 3.4 Commercial price assessments

ICIS, Argus, Platts assess exactly these chains at exactly the right granularity.
Paid, and the licence usually forbids redistribution — which collides with the One
Rule's requirement that a published number trace to a source a reader can open.
Worth pricing before assuming it is out of reach.

### 3.5 Do nothing, and say so

Make the 1.0 **explicit** — an `AUTHORED` row per tag with `elasticity = 1.0`,
`basis = ASSUMED_UNITY`, capped at grade D, and rendered in the UI as *"assumes
the input moves one-for-one with crude"*. Costs almost nothing, changes no
number, and converts a silent fabrication into a disclosed assumption an analyst
can argue with. **It is strictly better than today** and it is the floor any of
the above should be measured against.

---

# PART 4 — A FEASIBILITY PROBE, NOT RUN

Three codes, in this order. **No data was fetched. These are proposals.**

### Probe 1 — HS 2710.19, base oil. **The positive control.**

High import share, a direct refinery product one step from crude, market-priced at
import parity. **If crude→base-oil does not fit cleanly here, the customs-UV method
does not work anywhere and the route should be abandoned.**

**Falsifies the approach if:** R² below ~0.5 on monthly USD unit values against
lagged Brent over 2015–2026; or the coefficient is unstable across 2020 and 2022
subsamples; or the implied elasticity lands far outside a plausible structural
range. Cross-check available: `input:base_oil` already has a filed exposure row
(Savita Oil, 86.1% of COGS, near pure-play), so a fitted elasticity can be tested
against Savita's own margin behaviour without any company-level regression.

### Probe 2 — HS 2803, carbon black. **The case that matters and the case most likely to fail.**

CEAT's largest tag. Tests §2.1 (grade mix), §2.3 (low import share, antidumping)
and §2.4 (domestic formula pricing) simultaneously.

**Falsifies it if:** the 8-digit lines cannot separate rubber-grade from acetylene
and specialty blacks; or the series shows a level break at the antidumping
imposition that dominates the crude signal; or the fitted elasticity differs
materially from what Probe 1's base-oil result and a CBFS cost build-up (§3.1)
jointly imply. **A disagreement between the fitted and the authored route here is
the single most informative result the probe can produce** — it tests the method
against a mechanism rather than against a p-value.

### Probe 3 — HS 5902.20, polyester tyre cord fabric.

CEAT's second tag; tests whether a downstream, contract-priced, part-domestic
product retains any readable crude signal.

**Falsifies it if:** the fitted elasticity is indistinguishable from zero with a
wide band — which would be the correct finding for an annually-contracted input
and would mean the tag needs an authored linkage, not a fitted one.

### The meta-criterion

**If Probe 1 fails, stop.** If Probe 1 succeeds and Probe 2 fails, the method
works for refinery streams and not for chemical derivatives, which is a real and
useful boundary — and it means the crude *ripple* families need §3.1's authored
build-ups while the direct families can be fitted.

**Cost: 3–5 days**, mostly acquiring and cleaning three monthly series. It should
be run before any table is designed.

---

# PART 5 — RECOMMENDATION

**Adopt the table. Do not adopt the estimator as the default basis. Do not build
either until the probe has run.**

Precisely:

1. **Accept `derivative_linkage` as a schema gap and specify it** — keyed
   `(shock_variable, exposure_tag)`, **no `company_id`, ever** (§2.8 tripwire),
   applied before §5.1, **never folded into `pass_through`**, abstaining when
   absent. The table is right regardless of how it is populated, and the argument
   for it does not depend on any estimation succeeding.
2. **Ship §3.5 first — the explicit unity row.** One `AUTHORED` row per crude tag
   with `elasticity = 1.0`, `basis = ASSUMED_UNITY`, grade-capped, surfaced in the
   UI. It changes no number and converts today's silent hardcoded constant into a
   disclosed assumption. **This is the only part I would do immediately**, and it
   is nearly free.
3. **Author before you fit.** §3.1 cost build-ups and §3.2 published formulae are
   better evidence, cheaper, regime-stable, and consistent with §A2.4. Fit only
   where neither exists.
4. **Run the probe (§4) before designing the estimator**, and let Probe 1 decide
   whether there is an estimator at all.
5. **Classify every tag as market / regime / intermediated (§2.6) and record the
   classification**, because fitting an elasticity on `input:freight_diesel` would
   model a policy as a price, and because four of the eleven current ledger rows
   are intermediated services that neither category handles.

**What I am not recommending:** a customs-UV estimator as the primary route. §2.2
is a serious identification problem with a **same-signed, inflating** bias, §2.3
suggests the two tags CEAT actually carries are the two the method serves worst,
and §2.5 says the IMMEDIATE horizon is below the data's sampling frequency — while
the IMMEDIATE horizon is where the CEAT run's headline came from.

**What would change my mind:** Probe 1 succeeding cleanly, and Probe 2's fitted
elasticity landing close to an independently authored CBFS build-up. That would
show the method recovers a quantity we can derive another way, and the
extrapolation to codes we cannot derive would stop being an article of faith.
It is the same test ADR-001 asked for and never got.

**What I do not know:** every HS code, import share and market-structure claim in
Part 2 is unverified background knowledge, flagged as such throughout. Whether
MOSPI's WPI publishes usable commodity-level sub-indices for these specific
products (§3.3). Whether commercial assessments can be licensed compatibly with
the One Rule (§3.4). Whether `input:bought_in_freight` and
`input:intermediated_air_capacity` — four of eleven ledger rows — have any
tractable treatment at all; §2.6 identifies them as a third category and this
document does not solve them.
