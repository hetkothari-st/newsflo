# Back-test: can a gross-margin regression recover a known exposure?

Run 2026-08-17 · Feasibility probe, **scratch only** · Referenced by
[`ADR-001`](../decisions/ADR-001-econometric-exposure.md)

Nothing was written to the repo, no migration was created, and **nothing was
written to `pass_through_curve`**. Scripts live in the session scratchpad
(`backtest_probe.py`, `backtest_run.py`).

## Answer

**No. The method does not recover a known quantity.**

It fails on the easiest possible case — Savita Oil, 86.1% base oil, a
near-pure-play blender — and it fails in the most dangerous way available: not
by returning nothing, but by returning a **significant coefficient with the
wrong sign**, whose implied pass-through is greater than 1 (impossible), and
which **flips sign when the sample window changes**.

Per ADR-001's own criterion — *"If the method cannot recover Savita's 86%
base-oil exposure — a near pure-play, the easiest possible case — the redirect
is dead and we look elsewhere for curves"* — the regression route to curves
is **dead as specified**.

---

## What was fitted

`g` = gross-margin ratio = 1 − (cost of materials + purchases of stock-in-trade
+ change in inventories) / revenue, per quarter, from NSE Ind-AS result XBRL.
Regressor: ln(Brent), quarterly mean.

The identity being tested. With `s` = crude-linked share of materials (the
number already in the ledger), `m` = materials/revenue, `k` = total
cost/revenue, `φ` = pass-through:

```
dg/dlnP  =  -s·m·(1 - φ·k)          →  φ = (1 + β/(s·m)) / k
```

`φ = 0` gives `β = -s·m`. `φ = 1` does **not** give `β = 0`: passing the whole
cost increase through preserves the absolute margin but still dilutes the
ratio, because the denominator grew. So the filed share makes a **falsifiable
prediction about β**, and that is what the probe checks.

## Quarters actually available — the first finding

Asked for explicitly, and it is a result in its own right.

| | CEAT | Savita Oil |
|---|---|---|
| periods the NSE index lists | 67 | 80 (standalone) / 13 (consolidated) |
| of those, XBRL URL returns **HTTP 404** | **42** | **52** / 0 |
| resolves (HTTP 200) | 25 | 28 / 13 |
| **strict** — context declared in the document | **9** | **10** / 10 |
| **relaxed** — + facts pointing at an undeclared context id | **25** | **28** / 13 |
| earliest usable | 2018-09-30 | 2018-03-31 |
| yfinance, the only quarterly source wired into this repo | 5 | 5 |

Two distinct failure modes, and neither is a parser defect:

1. **Dead links.** NSE lists the filing and no longer serves the file. Over
   half the index is unusable.
2. **Malformed XBRL.** Older files carry `RevenueFromOperations` and
   `CostOfMaterialsConsumed` with `contextRef="OneD"` and **never declare a
   context with that id**. The numbers are there; the period they belong to is
   not. The "relaxed" rows read them under the naming convention observed in
   newer files — an inference about the document, not a statement in it.
   Fine for a probe, never acceptable as ledger provenance.

*A methodological note worth keeping:* the first version of the parser used
regex over `<xbrli:context>` and silently lost 16 of CEAT's 25 resolvable
files. That would have been reported as **missing data** when it was a tooling
limit. It was caught only by inspecting a specific failing file. Any
production acquisition needs a test that distinguishes "the document does not
contain it" from "we could not read it".

## Results

`s(CEAT) = 0.3100` (a floor), `s(Savita) = 0.8608`.

### Savita Oil — the easy case

| spec | n | β (lnBrent) | se | p | 95% CI | R² | implied φ |
|---|---|---|---|---|---|---|---|
| **filed share predicts (φ=0)** | | **−0.70** | | | | | 0 |
| A, consolidated, strict | 10 | **+0.274** | 0.075 | 0.007 | [+0.100, +0.447] | 0.62 | **+1.47** |
| A, standalone, relaxed | 28 | **−0.089** | 0.035 | 0.017 | [−0.160, −0.017] | 0.20 | +0.93 |
| C, standalone, + yoy ln revenue | 24 | −0.164 | 0.039 | 0.000 | [−0.245, −0.084] | 0.47 | — |
| **D, first differences, standalone** | 27 | **−0.007** | 0.049 | 0.881 | [−0.109, +0.094] | **0.001** | — |
| D, first differences, consolidated | 12 | +0.126 | 0.108 | 0.270 | [−0.115, +0.367] | 0.12 | — |

* The filed share predicts β ≈ **−0.70**. Nothing observed is within an order
  of magnitude of it.
* On the basis the ledger row actually uses (consolidated), β is
  **positive and significant** — gross margin *rises* when crude rises, for a
  company whose cost is 86% base oil. Implied φ = **1.47**, which is not a
  pass-through; it is a number outside the parameter's domain.
* The sign **flips** between the 10-quarter and 28-quarter windows on the same
  company.
* Adding one crude volume control (yoy log revenue) nearly **doubles** β, and
  the control is itself highly significant (t = +3.19). The coefficient is
  specification-dependent, exactly as the confounding objection predicted.
* **In first differences there is nothing at all.** R² = 0.001, p = 0.88.

### CEAT

| spec | n | β (lnBrent) | se | p | 95% CI | R² | implied φ |
|---|---|---|---|---|---|---|---|
| **filed floor predicts (φ=0)** | | **−0.188** | | | | | 0 |
| A, strict | 9 | −0.109 | 0.138 | 0.453 | [−0.435, +0.216] | 0.08 | +0.45 |
| A, relaxed | 25 | **−0.081** | 0.024 | 0.002 | [−0.131, −0.032] | 0.33 | **+0.59** |
| C, + yoy ln revenue | 21 | −0.088 | 0.029 | 0.008 | [−0.150, −0.026] | 0.35 | — |
| **D, first differences** | 24 | **+0.022** | 0.037 | 0.557 | [−0.055, +0.099] | **0.016** | — |

CEAT's relaxed-levels result *looks* like a success: right sign, significant,
R² = 0.33, implied φ = 0.59 [0.32, 0.87] — a thoroughly plausible pass-through
for a tyre maker, and stable when a volume control is added. **It does not
survive first-differencing.** R² collapses to 0.016 and the sign reverses.

## Why it fails — three reasons, in order of how much they matter

**1. Spurious regression.** Both companies' levels results vanish in first
differences. Regressing a bounded ratio on a trending price over 25 quarters
is the textbook setup for co-trending to masquerade as response. The one
specification robust to that critique returns nothing for either company. A
levels R² of 0.33 is not evidence here, and it would have been reported as
evidence.

**2. The cost channel and the inventory channel are not separable at this
frequency.** Savita's positive coefficient is probably not noise. A base-oil
blender books **inventory gains** when crude rises — stock bought earlier,
sold at prices marked to current crude — and spec §8 says exactly this:
inventory revaluation dominates the IMMEDIATE horizon for commodity
processors. A single coefficient on a quarterly margin cannot decompose
`INPUT_COST` from `INVENTORY_REVALUATION`; it returns their sum, and for a
processor that sum can be positive while the cost exposure is large and
negative. **This is an identification problem, not a sample-size problem, and
more quarters do not fix it.**

**3. The lag structure is not a curve.** SPEC B, the distributed lag that a
pass-through curve would have to come from:

* Savita standalone: lnB(t) = +0.005 (ns), lnB(t−1) = +0.036 (ns),
  lnB(t−2) = **−0.199** (p < 0.001)
* Savita consolidated: lnB(t) = +0.130 (ns), lnB(t−1) = **+0.211** (p = 0.03),
  lnB(t−2) = **−0.256** (p = 0.003)
* CEAT relaxed: lnB(t) = −0.020 (ns), lnB(t−1) = −0.105 (p = 0.07),
  lnB(t−2) = +0.039 (ns)

§4.2 requires a curve of *cumulative fraction recovered* — monotone
non-decreasing from 0. These profiles are non-monotone and sign-alternating,
and the two Savita bases disagree with each other on the sign of the
one-quarter lag. **No well-formed curve can be read off them.** Moving the
target from `company_exposure` to `pass_through_curve` does not rescue the
method; the estimator fails on its own terms before the destination matters.

## Limitations of the probe, stated

* Brent **futures** (BZ=F) monthly closes, quarterly mean, not daily spot.
  FRED's `DCOILBRENTEU` — the series a production implementation should use —
  is unreachable from this machine (connection reset, repeatably, via both
  curl and requests).
* **Base oil is not Brent.** Savita's input is Group I/II base oil, which
  tracks crude with a lag and its own refining spread. No free base-oil series
  exists. A production version would need a paid series, and the attenuation
  from using a proxy biases β toward zero — which does not explain a
  *positive* coefficient.
* n = 9–28. Small. But the failure is a sign error and a differencing
  collapse, not a width problem, and the small-n specs are the ones that
  looked *most* significant.
* Univariate plus one control. A properly specified model would carry other
  input prices, FX and mix. That is the recommendation for anyone who revisits
  this — and it needs degrees of freedom the 25-quarter ceiling does not have.

## What this closes and what it leaves open

**Closed:** regression on quarterly gross margin as a route to either exposure
shares or pass-through curves, at the history depth available today. The
redirect in ADR-001 is not merely unproven; it is contradicted on its own
nominated test case.

**Open, and now more attractive by comparison** — routes that produce a curve
with an excerpt and a page, and therefore pass the existing verbatim gate
unchanged: earnings-call commentary on lag-to-recover, stated pricing policy,
and contractual formula terms. See `docs/v5/CURVE_BOOTSTRAP.md`.
