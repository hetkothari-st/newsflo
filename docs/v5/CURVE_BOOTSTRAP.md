# Pass-through curves: what is actually required, and the cheapest route to one

Written 2026-08-17, after the crude bootstrap put 11 exposure rows in the
ledger and the pipeline still published nothing. Traced through the code, not
inferred from the spec. Companion to
[`ADR-001`](decisions/ADR-001-econometric-exposure.md) and
[the back-test](amendments/AMENDMENT-002-BACKTEST.md).

---

## 1. The minimum viable curve — and the two things beside it

**A curve alone does not stop a company abstaining.** A `COST` channel needs
three inputs, and `params.resolve_param` has no fallback of last resort —
"nothing" raises rather than defaults:

| # | input | read from | fallback |
|---|---|---|---|
| 1 | `pass_through` | `pass_through_curve` | sector-level curve, else the median of sector peers' curves |
| 2 | `hedge_ratio` | `company_modifier.parameters` JSON (value **and** `measurement`) | median of sector peers' modifiers on the same tag. **No sector-level modifier row exists** — `company_modifier.company_id` is NOT NULL |
| 3 | `EBITDA_ttm` | `company_financials.ebitda_inr` | **none.** `engine.ebitda_ttm()` returns `None` and the company abstains |

Miss any one and the channel is `UNCOMPUTABLE`.

### The curve itself: one point is legal

`params.evaluate_curve` needs a non-empty list, interpolates piecewise-linearly
between points, and **never extrapolates** — before the first point it holds
the first value, after the last it holds the last. So the minimum viable curve
is literally

```json
[{"lag_days": 0, "fraction": 0.30}]
```

which evaluates to 0.30 at every horizon. Nothing checks that a curve is
monotone, that it starts at zero, or that it has more than one point.

**That is worth knowing and worth being uneasy about.** §4.2's "a function,
not a scalar" is enforced by convention, not by the code, and a single-point
curve is a scalar wearing a curve's schema. If the three-horizon engine is to
mean anything, a shape check belongs in the review path: monotone
non-decreasing, first point at `lag_days: 0`, and at least two points before a
curve may claim to distinguish horizons. Recorded as a Phase 2 ticket.

Also note the `curve_needs_review` CHECK covers `basis = 'ESTIMATED'` only. A
`SECTOR_MEDIAN` curve — equally a computed guess — may be written with no
reviewer at all.

### What the curve's shape decides

Everything. Measured on CEAT with the proof-of-life curve
`[0d: 0.00, 30d: 0.55, 90d: 1.00]`, a +10% crude shock:

```
horizon   0d  delta_ebitda = -2,095,450,000
horizon  30d  delta_ebitda =   -942,952,500
horizon  60d  delta_ebitda =   -471,476,250
horizon  90d  delta_ebitda =             -0     <- and so emits no signal
horizon 180d  delta_ebitda =             -0
```

The curve reaching 1.0 at 90 days is the entire reason the 90-day impact is
zero. A curve chosen rather than sourced does not merely add uncertainty; it
picks the answer.

---

## 2. Does a §4.2 sector-median curve satisfy the requirement?

**Yes — the channel computes. And it cannot reach PRIMARY, by two independent
rules.**

`_sector_median` resolves `pass_through` from either a **sector-level curve**
(`company_id IS NULL AND sector_id = …`) or, failing that, the **median of
sector peers' own curves**. Either way the parameter source is
`SECTOR_PROXY` — note the asymmetry: a *company-level* curve's source is
mapped from its `basis`, but anything reached through the sector path is
`SECTOR_PROXY` regardless of the row's basis.

| curve basis (company-level) | param source | evidence grade cap | PRIMARY? |
|---|---|---|---|
| `FILED` | FILED | none | eligible |
| `DISCLOSED_CALL` | DISCLOSED_CALL | none | eligible |
| `SECTOR_MEDIAN` | SECTOR_PROXY | **C** | **blocked** |
| `ESTIMATED` | MODELLED | **D** | blocked |
| *anything, reached via the sector path* | SECTOR_PROXY | **C** | **blocked** |

Two rules block PRIMARY on the sector route, and they are separate:

1. `evidence_grade_cap.SECTOR_PROXY = C`, and `primary.evidence_grades =
   [A, B, C]` — so grade alone does **not** block at C.
2. `primary.allow_sector_proxy: false` — this is what blocks it. A
   SECTOR_PROXY parameter is refused at PRIMARY outright, whatever its grade.

`secondary_ripple` sets `allow_sector_proxy: true` and
`evidence_grades: [A, B, C, D]`, so the ceiling is **SECONDARY_RIPPLE**.

**For the 11 rows now in the ledger this is moot**: every one is
`measurement = ESTIMATED`, which caps the channel at **D** through the
exposure axis regardless of what the curve does. Nothing sourced in the crude
bootstrap can lead a publication under any curve. The curve basis only starts
to matter for the tier the day a `FILED` exposure row exists.

### The sector bucket is not fit for this purpose

`_sector_of` reads `companies.sector`. For the nine companies holding the
eleven rows:

| sector value | companies |
|---|---|
| `oil_gas` | Savita Oil |
| `other` | CEAT, CONCOR, Delhivery, Mahindra Logistics, TCI, TCI Express, VRL, Blue Dart |

**Eight of nine sit in a bucket called `other`.** A "sector median" over that
set pools a tyre maker, a container-train operator and an air-express company.
Today no two of them share a tag, so nothing cross-contaminates — but the
moment anyone adds `input:freight_diesel` to CEAT (plausible; tyre makers
carry freight), CONCOR's or VRL's curve silently becomes CEAT's proxy.

`companies.sector` is also written by two different jobs, so manual repairs
revert (DATA_GAPS §7). **The sector-proxy route should be treated as unusable
until family membership has a stable home** — which is the same gap the ripple
coverage harness already records.

---

## 3. How many distinct curves unblock the eleven rows?

11 rows · 9 companies · 6 distinct tags · **7 distinct (sector, tag) pairs**.

Because one company-level curve in a sector serves its peers on the same tag
through the median path, the pairs are the unit that matters:

| sector | tag | rows covered |
|---|---|---|
| `oil_gas` | `input:base_oil` | 1 |
| `oil_gas` | `input:crude_derivative_petchem` | 1 |
| `other` | `input:crude_derivative_rubber` | 1 |
| `other` | `input:crude_derivative_petchem` | 1 |
| `other` | `input:bought_in_freight` | 4 |
| `other` | `input:freight_diesel` | 2 |
| `other` | `input:intermediated_air_capacity` | 1 |

**7 curves. 7 hedge modifiers. 9 EBITDA rows. 23 records total.**

Five already exist (CEAT's two curves, CEAT's two hedge modifiers, CEAT's
EBITDA row), so **18 records remain** to make every row in the ledger
computable.

Caveat, and it is the same one as above: five of the seven pairs live in the
`other` bucket, so "one curve serves the sector" is only safe while no two
unrelated companies share a tag. Authoring **11 company-level curves** instead
of 7 sector ones costs four more records and removes the risk entirely.
**Do that.**

---

## 4. Sources for a defensible curve that are not regression

The back-test closed the regression route: on both test companies the levels
result vanishes under first-differencing, and the distributed-lag profiles are
non-monotone and sign-alternating, so **no well-formed curve can be read off
them**. What remains is better anyway, because each of these produces an
excerpt and a page and therefore passes the existing verbatim gate unchanged.

**In descending order of what the grade table above rewards:**

1. **Contractual / formula pricing → `FILED`, uncapped.** Where price is
   mechanically indexed, the curve is not estimated at all — it is *read*.
   Fuel-surcharge clauses in freight contracts, tariff formulas, take-or-pay
   and escalation clauses. The reset frequency IS the lag structure: a
   quarterly-reset clause is a curve with a step at 90 days. This is the only
   source that yields a curve nobody has to believe. Directly relevant to the
   four `bought_in_freight` rows, where fuel-surcharge mechanics are the
   mechanism.

2. **Earnings-call commentary → `DISCLOSED_CALL`, uncapped.** Managements
   routinely say the thing the curve needs: *"we took a 3% price increase in
   October to recover raw-material inflation"*, *"we expect full recovery over
   two quarters"*, *"pricing lags input costs by about a quarter"*. Two or
   three such statements across a cycle give lag AND fraction. This is the
   highest-value untried source in the project: it is the only route to an
   uncapped curve for a company with no formula, and `DISCLOSED_CALL` is
   absent from `evidence_grade_cap`, so it does not cap the channel at all.
   Acquisition is a different problem from filings — transcripts are not on
   the exchange sites — and that is the honest cost.

3. **Dated price-increase announcements to the exchange → `FILED`.**
   Underrated and, for some sectors, the single most literal source available.
   A sequence of dated announcements following a dated input-cost move is
   *exactly* a cumulative-recovery-by-lag profile, each point with its own URL
   and date. Paints and tyres announce price increases this way.

4. **MD&A margin-recovery commentary → `FILED`.** Weaker: usually directional
   ("margins recovered in H2 as pricing caught up") rather than quantified,
   and it lives in the annual reports **already on disk** from the bootstrap.
   Cheapest to try because the documents are local; lowest yield.

5. **Regulated / administered pricing → `FILED`.** Where a regulator sets the
   revision cadence, the cadence is the curve. Not relevant to these eleven
   rows, but it is the cleanest source that exists and it should be used first
   wherever it applies.

6. **Sector median → `SECTOR_PROXY`, capped at C, PRIMARY-blocked.** The §4.2
   fallback. Legitimate, cheap, and — see §2 — currently resting on a `sector`
   column that says `other`.

**Not a source: our own reasoning.** A hand-authored curve is `basis:
ESTIMATED`, maps to `MODELLED`, caps the channel at D, and requires
`reviewed_by`. That is the correct treatment and it should stay
uncomfortable. It is what CEAT's proof-of-life curve is.

---

## 5. Is there a route to a first curve that costs hours rather than weeks?

**Yes, and it has already been done once.** The CEAT proof-of-life — an
`company_financials` EBITDA row, two `FILED` hedge_ratio modifiers, two
`ESTIMATED` curves with `reviewed_by` set — took the pipeline from silence to
a signed rupee delta with a horizon profile. Hours, no migration, no new code.

The order that makes it hours rather than weeks, cheapest first:

**Step 1 — EBITDA rows (~10 minutes per company, 8 remaining).** Revenue,
total expenses and EBITDA are on the P&L face of annual reports **already on
disk and already text-indexed** in `data/filings/`. No acquisition. This alone
removes `no_ebitda=True` from every abstention message.

**Step 2 — hedge_ratio at `FILED` quality (~10 minutes per company).** This is
the pleasant surprise of the bootstrap. SEBI LODR Reg 34(3) requires a
commodity-hedging disclosure in the Corporate Governance Report, and it is
usually a plain sentence. Searching the indexed text of the nine companies
holding the eleven rows finds a usable statement in **5 of 9** on the first
pass:

```
CEATLTD    p61   "not have any exposure hedged through commodity during FY 2025-26."
VRLLOG     p147  "not opted for hedging."
DELHIVERY  p67   "The Company considers commodity price risk and currency risk to be
                  low and does not hedge these risks."
CONCOR     p134  "commodity price risks and commodity hedging activities does not
                  apply to the Company."
TCI        p138  "not hedge foreign exchange risk as the exposure is not material."
```

Each is `hedge_ratio = 0.0`, `measurement = FILED`, with an excerpt and a
page. **Unlike pass-through, hedge_ratio is routinely sourceable at the
highest grade from documents we already hold.** Mahindra Logistics and TCI
Express need a second look; Savita and Blue Dart's hits are FX-hedge
accounting language rather than commodity hedging and do not qualify.

**Step 3 — the first *sourced* curve (a day, not hours).** Pick the company
whose mechanism is contractual, not behavioural. Of these eleven rows that is
a `bought_in_freight` name: a fuel-surcharge clause has a stated reset
cadence, and the cadence is the curve. Failing that, one earnings-call
transcript for one company, for one statement about pricing lag.

**What NOT to do, stated because it is the tempting shortcut:** author eleven
`ESTIMATED` curves in an afternoon and call the ledger populated. It would run
end to end, produce plausible numbers, and every published magnitude would be
a shape somebody chose. The grade-D cap contains the damage but does not
remove it — and DATA_GAPS §5 would need to say the system's outputs are
computed on hand-drawn curves, which is close to the failure the whole
fabrication guard exists to prevent. One sourced curve is worth more than
eleven authored ones.
