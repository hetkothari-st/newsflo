# DATA GAPS — The CEAT proof-of-life run

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

---

## 16. The CEAT proof-of-life run — MEASURED 2026-08-17

One company taken end to end against the live DB, to test whether the downstream
half works at all. **It does.** A crude +10% shock now produces a published
SECONDARY_RIPPLE record for CEAT with a band, a mechanism, a section and rendered
prose. Nine defects surfaced; they are listed below and none of them is fixed.

### What was written, and from where

Five links, all traced to a named page of a named filed document. Sources:
CEAT Integrated Annual Report 2025-26 (NSE, filed 23-Jul-2026, sha256
`c4433bd6…5310`) and the CEAT Q4 & FY26 earnings call transcript (29-Apr-2026,
sha256 `5f353dc7…4fea`, now stored at
`data/filings/INE482A01020/calls/q4fy26_transcript.pdf`).

| Link | Rows | Basis | Source |
|---|---|---|---|
| `company_financials` | 1 (`FY26`) | filed P&L | AR MD&A P&L table, standalone: revenue 15,21,486 lakh · **EBITDA 2,04,237 lakh (13.42%)** · cost of materials 9,19,712 lakh |
| `company_modifier` | 2 (`HEDGE`) | **`hedge_ratio = 0.0`, measurement FILED** | AR Corporate Governance Report, SEBI LODR Reg 34(3): *"The Company does not have any exposure hedged through commodity during FY 2025-26."* |
| `pass_through_curve` | 2 | **`basis = ESTIMATED`**, reviewed | earnings call, derivation below |
| `mechanism_edge` | 2 | `derivation = AUTHORED`, `review_status = PENDING`, `reviewed_by` NULL | queued for owner approval |

### On the hedge ratio: disclosed zero is not the same as missing

CEAT states a **zero**, under a mandatory SEBI disclosure. That is a fact, not an
absence, so it is recorded as `hedge_ratio = 0.0` with `measurement = FILED`.
Corroborated by AR note 45(iv), whose commodity sensitivity table is computed
*"with all other variables held constant"* and discloses no commodity derivative.

**What the engine does with each case:**

* **Missing row** — `resolve_param` finds nothing, tries the sector median, finds
  nothing, raises `InsufficientParameterData(MISSING_ROW)`. The channel is
  UNCOMPUTABLE, the company abstains, nothing publishes. Correct.
* **Row present, parameter named, `measurement` absent** — `MISSING_MEASUREMENT`.
  Also unusable, but distinguished in the reason string as *"a data-entry defect
  somebody can fix"*. Correct, and the distinction already exists in code.
* **Disclosed zero** — a normal computable parameter with a zero point and a
  **zero-width band** (`band_width` × 0 = 0). It is the only one of the three that
  publishes.

**The gap:** there is no fourth state for *"asked and the company declines to
say"*. That would resolve identically to a missing row, which is the safe
direction but loses the distinction between an unpopulated ledger and a company
that will not answer.

### On the pass-through curve: the disclosure supports a shape, not a level

**Shape — disclosed directly, with dates** (call p.10): *"we need to take overall
10% vis-a-vis March, in replacement. Out of that, about 5% can be considered as
taken already between March and April. That leaves the balance of 5%, which will
be staggered through May and June."* That is a genuine two-step ramp with
anchored dates, so it is **a real multi-point curve, not a scalar dressed as one**
— points at 0 / 30 / 90 days.

**Level — NOT disclosed, and derived.** Management quantifies the price increase
as a % of *selling price* and the cost increase as a % of the *raw-material
basket*. Converting one to the other is arithmetic over two disclosures plus one
filed ratio:

```
cost increase as % of revenue = 15%      (call p.10, Q1 RM cost increase)
                              x 60.45%   (AR MD&A, materials as % of revenue)
                              = 9.07%
price increase as % of revenue = 10%     (call p.10, replacement)
implied recovery = 10 / 9.07 = 1.103  -> clipped by `ceiling` to 1.00
```

**The assumption this embeds, stated so it can be rejected:** that the 10%
replacement price increase is representative of the whole book. It is not
disclosed to be. OEM is *"small single-digit… 1st July will get a big increase"*
and international is *"close to 10%"* behind a 30-day order book (call p.4), and
**no segment revenue split is disclosed in either document.** This is why the
basis is `ESTIMATED` and not `DISCLOSED_CALL`.

**Two further caveats.** It is management's *intended* recovery, stated
prospectively on 29-Apr-2026 — a plan, not a realised pass-through. And the
commentary is about the **raw-material basket**, not about carbon black or tyre
cord, so the same curve is written against both tags. No per-commodity curve is
disclosed by anyone.

### The result — crude +10%, as of 2026-08-17

```
publication_tier    SECONDARY_RIPPLE       rejection_reason  None
headline_horizon    IMMEDIATE              evidence_grade    D  (capped by ESTIMATED exposure)
net_effect          NEGATIVE               sign_consistency  1.000
materiality_bucket  HIGH                   weakest_link      COST_EXPOSURE:BOUND

IMMEDIATE   (5d)   p10 -12.96%  p50 -12.68%  p90 -12.39%   pass_through 0.092
NEAR_TERM  (90d)   channels compute to -0.0, 0 signals emitted
STRUCTURAL (270d)  channels compute to -0.0, 0 signals emitted

driver_ranking      pass_through 1.0000  (the only driver)
PRIMARY failed on   evidence_grade=D, empirical=None, verifier=None
SECONDARY passed    graph_distance d=2 max=3 · evidence_grade D · sign_consistency 1.0
                    floor=0.75% · mechanism_id present

section  "NEGATIVE — UNCLASSIFIED MECHANISM (ca78e5c5-049c-4731-931d-b9ab1bedebf9)"
prose    "NEGATIVE | IMMEDIATE | -12.7% EBITDA (range -13.0% to -12.4%)
          Most sensitive to: pass-through 9% (modelled estimate)"
```

### The arithmetic checks out against CEAT's own disclosed sensitivity

AR note 45(iv) discloses a **5%** commodity price move as ₹24,600 lakh (rubber) +
₹7,200 lakh (carbon black) of profit impact, over 68.6% of the materials basket.
Scaled to 10% and normalised to the 31.0% of the basket this run actually covers:
**₹28,745 lakh**. The engine's gross (pre-pass-through) figure is
**₹28,512 lakh — within 0.8%.** The §5.1 COST formula reproduces a number the
company itself published, from a completely different disclosure. That is the
strongest evidence in this repo that the channel arithmetic is right.

### The nine defects, none fixed

1. **No reviewed write path exists for four of the five tables.**
   `app.ledger.review.approve_proposal` covers `company_exposure` **only**. There
   is no proposal table, no review function and no loader for
   `pass_through_curve`, `company_modifier`, `company_financials` or
   `mechanism_edge` — `params.py` and `engine.py` only read them, and
   `xbrl.py`/`deterministic.py` parse into row dicts nothing writes. These four
   rows were written by direct SQL because no compliant path exists. The DB-level
   CHECKs (`curve_needs_review`) still applied. **This is the largest single gap
   the run found.**
2. **An unreviewed mechanism edge published.** Both edges carry
   `review_status = 'PENDING'` and `reviewed_by IS NULL`. The SECONDARY gate's
   `mechanism_id` rule checks **presence, not review status**, so a
   `PENDING` edge cleared it. §A2.4 requires review before an IO-derived edge can
   publish; nothing enforces the equivalent for an AUTHORED one.
3. **The point estimate and the band contradict each other at NEAR_TERM.** Every
   channel's deterministic delta is exactly `-0.0` (pass-through reaches the 1.0
   ceiling at 90 days) while the Monte Carlo reports `p50 = -1.66%`,
   `sign_consistency = 1.0`, `bucket = LOW`. The band samples pass-through over
   [0.60, 1.00] and never sees the zero the point computation produced. It is
   invisible here only because zero-delta channels emit no signals; move the
   ceiling to 0.99 and a contradictory band publishes.
4. **"not evaluated" is false.** `horizon_lines` renders *"NEAR TERM: not
   evaluated"* and `direction_by_horizon` sets `evaluated: false`. Both horizons
   **were** evaluated and returned zero. The UI cannot distinguish "we did not
   look" from "we looked and it nets to nothing" — which is exactly the
   distinction §8 exists to preserve.
5. **No crude→derivative price elasticity anywhere in §5.1.** The COST formula
   applies `shock.delta_pct` directly to `share_of_base × base_value`, i.e. it
   assumes carbon black, rubber chemicals and polyester tyre cord all move 1:1
   with Brent, instantly. The tag is named `crude_derivative_*`; the derivative
   step has no coefficient. Every number in this run silently assumes unity.
6. **The section label leaks a raw UUID to the user.**
   `NEGATIVE — UNCLASSIFIED MECHANISM (ca78e5c5-049c-4731-931d-b9ab1bedebf9)` —
   `config/section_taxonomy.yaml` has no label for either authored edge.
7. **A company with two mechanisms is filed under one of them, chosen by sort
   order.** The two channels carry different `mechanism_id`s. `CompanyImpact`
   holds a single `mechanism_id`, and the section key took the **petchem** edge —
   the *smaller* channel (8.2% of basket) — leaving the rubber edge (22.8%) out of
   the section key entirely.
8. **`driver_ranking` degenerates to one driver.** `hedge_ratio` is a disclosed
   zero with a zero-width band, so it contributes no variance; `pass_through` gets
   1.0000. The "top 3 drivers" product feature shows one. Predicted in ADR-001 §1.5
   and now observed.
9. **`materiality` means two different things in one payload.** The channel-level
   field reads `MEDIUM` (that channel's −3.36%) while the company-level
   `bucket` reads `HIGH` (−12.68%), same JSON object, same word. A W3
   contradiction risk if either reaches a surface.

### Two more empty links the chain in ADR-001 did not count

Reaching tier and section required **three hand-supplied signals** —
`ENTITY_RESOLUTION`, `DISCOVERY` and `EVIDENCE_BINDING` — because no populated
table produces them. `evidence_records` has 0 rows and Phase 3 discovery has no
data, so `graph_distance`, `directness`, `discovery_source` and the claim binding
were all asserted by hand for this run. The publishable chain is therefore
**seven** links, not five. **Owner: repo owner.**

### Staleness asymmetry

`company_exposure` has `freshness_days` plus a staleness checker and a HARD gate
rule. `company_modifier` has **neither** — `_modifier_rows` filters only on
`effective_from` / `effective_to`. The CEAT hedging disclosure covers FY2025-26;
it was written with `effective_to = NULL` so the run would compute. Written
honestly as `effective_to = 2026-03-31` it expires and the company abstains today.
There is no freshness policy that makes that choice for a reviewer.

### Reversal

Four `INSERT`s, one company. To undo: delete the two `pass_through_curve` rows,
the two `company_modifier` rows, the two `PENDING` `mechanism_edge` rows and the
`(186, 'FY26')` `company_financials` row. Pre-run backup at
`backend/newsflo.db.bak-20260817-ceat`. **Nothing was extrapolated to any other
company, no sector-median curve was written, and `companies.sector` was not
touched.**
