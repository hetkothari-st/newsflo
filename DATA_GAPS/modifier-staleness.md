# DATA GAPS — Parameter staleness, and the disclosure states the ledger cannot express

Section §17. Split out per the index rule in [`../DATA_GAPS.md`](../DATA_GAPS.md).

Raised out of the CEAT proof-of-life run ([§16](ceat-proof-of-life.md)),
2026-08-17. Both items are **policy gaps the owner must close**, not code
defects — the code defects from that run are in
[`docs/v5/defects/DEFECTS-001-ceat-proof-of-life.md`](../docs/v5/defects/DEFECTS-001-ceat-proof-of-life.md).

---

## 17. Parameter staleness and the missing disclosure states — OPEN

### 17.1 `company_modifier` has no staleness control of any kind

The two tables that carry company parameters are governed differently, and only
one of them is governed at all:

| | `company_exposure` | `company_modifier` |
|---|---|---|
| freshness policy | `freshness_days` per `exposure_kind`, from `config/freshness.yaml` (INPUT_COST 400, FX 200, REGULATORY 120…) | **none** |
| checker | `app.ledger.staleness.company_exposure_is_stale`, nightly job flags `STALE` | **none** |
| gate | HARD rule `exposure_freshness`; a stale exposure is excluded from PRIMARY | **none** |
| what the query filters on | `as_of_date`, plus the staleness flag | `effective_from <= as_of AND (effective_to IS NULL OR effective_to >= as_of)` — nothing else |

`params._modifier_rows` reads `effective_from` / `effective_to` and nothing more.
`company_modifier.as_of_date` exists on the row and **is never consulted**. So a
hedge ratio, a pass-through commitment or a contract floor read off a five-year-old
filing is indistinguishable, to every downstream consumer, from one read off last
week's — provided its effective window is open.

**Why this is a policy gap and not a bug to be patched:** the correct freshness
window for a hedging policy is not the same as for an input-cost share, and
nobody has decided what it is. A hedging *policy* changes less often than a
hedging *position*; a contractual pass-through commitment may hold for years; a
regulatory capture fraction changes when the regulation does. Copying
`freshness.yaml`'s exposure numbers across would be a guess.

**What must be decided:** a freshness policy per `modifier_kind`
(`HEDGE`, `PASS_THROUGH`, `CONTRACT_FLOOR`, `PRICE_CAP`, `SUBSIDY_SHARE`,
`WINDFALL_LEVY`, `TAKE_OR_PAY`, `FORMULA_PRICING`), whether staleness blocks or
merely widens the band, and whether it is a HARD rule or a tier rule.
**Owner: repo owner.**

The same question is open for `pass_through_curve`, which also has an
`as_of_date` nobody reads.

### 17.2 The admission this gap came out of

The CEAT run wrote both `company_modifier` rows with `effective_to = NULL`
**so that the run would compute**. That was a choice made by the implementer, not
a statement in the source.

The disclosure — SEBI LODR Reg 34(3), CEAT Integrated Annual Report 2025-26 —
says: *"The Company does not have any exposure hedged through commodity during
**FY 2025-26**."* Written faithfully, that is
`effective_from = 2025-04-01, effective_to = 2026-03-31`. With that window, an
analysis run at today's date (2026-08-17) finds no modifier, `hedge_ratio`
resolves to `MISSING_ROW`, the channel is UNCOMPUTABLE and **CEAT abstains.**

The rows have since been corrected to `effective_to = 2026-03-31`
(see [§16](ceat-proof-of-life.md) rollback), so the honest window is now what is
stored. This means:

> **A company that filed a clear, mandatory, unambiguous disclosure four months
> ago cannot be sized today, because no policy says how long that disclosure
> speaks for.**

That is the gap, stated as concretely as it can be. It is not solved by writing
`NULL` — writing `NULL` is asserting the disclosure is open-ended, which nobody
disclosed. It is solved by a freshness policy per §17.1, at which point
`effective_to` can carry what the document says and freshness can carry how long
we are willing to believe it.

### 17.3 ANSWERED — the defensible freshness window for `modifier_kind = HEDGE` from an annual LODR disclosure

Asked because §17.2 now blocks CEAT. Argued from what the disclosure claims.

#### What the disclosure actually claims

CEAT's Corporate Governance Report carries two different statements, and they are
not the same kind of object:

1. **A retrospective statement of fact about a closed period.** *"The Company does
   not have any exposure hedged through commodity during **FY 2025-26**."* This is
   a report on a completed year. It claims **nothing** about 1 April 2026 onward,
   and no reading of it can be stretched to.
2. **A present-tense statement of policy, with no stated period.** *"The Company
   manages commodity price volatility through a price forecast mechanism and a
   buying model that includes spot, forward and long-term contracts, with
   inventory levels aligned accordingly."* Plus, from note 45(iv): *"The Company's
   Board of Directors has reviewed and approved a risk management strategy
   regarding commodity price risk and its mitigation."*

Statement 2 is the one that speaks about the future, and it says CEAT manages
commodity risk **through procurement, not through derivatives** — which is the
mechanism that produced the zero in statement 1. It is Board-approved, structural,
and not period-bounded on its face.

**So the honest answer is neither of the two the brief offered.** The *fact*
speaks only for the period it covers — `effective_to = 2026-03-31` is correct and
should stay. But the fact is not the only evidence in the document, and the
company is not un-sizeable between March and the next filing, because a
present-tense policy statement is also on the record.

#### The proposal

**`effective_to` carries the period. A separate freshness policy carries how long
we are willing to treat that period as evidence about now, and at what strength.**

Three states rather than two:

| condition | measurement | band | grade | tier |
|---|---|---|---|---|
| `as_of` inside `[effective_from, effective_to]` | `FILED` | as filed | uncapped by this axis | PRIMARY eligible |
| `as_of` after `effective_to`, inside the freshness window | **`CARRIED_FORWARD`** | see the asymmetry rule below | **capped at D** | **SECONDARY only** |
| beyond the freshness window | absent | — | — | abstain |

**Window length, argued from the disclosure regime rather than convenience.** The
next equivalent statement arrives with the next annual report. For a 31 March
year-end the AGM must be held within six months of year end and the report is
circulated before it; CEAT's FY26 report was filed **23 July 2026, ~114 days after
period end**. A window that expires before the successor arrives creates a
guaranteed annual blackout for every company in the universe — not because
anything became unknown, but because we declined to read a document that is still
the latest one in existence. So the window must at minimum reach the next filing,
and should survive one late or missed filing so that a genuinely stale company is
distinguishable from a slow one.

**Proposed: `freshness_days = 550` (~18 months) measured from `effective_to`,
for `modifier_kind = HEDGE` sourced from `ANNUAL_REPORT`.** That covers the
~4–6 month filing gap twice over, and expires a company that has stopped filing.
It is a claim about **how often the evidence is refreshed**, which is a fact about
the disclosure regime — not a claim about how long a hedging policy lasts, which
nobody knows.

#### The asymmetry rule — the part that makes carrying forward defensible

**Carry forward only where the staleness error runs in the conservative
direction, and let the direction be a property of the value rather than of the
`modifier_kind`.**

In the COST channel, ΔEBITDA scales with `(1 − hedge_ratio)`. So:

* **A carried-forward `hedge_ratio = 0.0`** — if the company has since started
  hedging, the true impact is **smaller** than computed. We overstate the
  magnitude. We never flip the sign (a hedge ratio in [0,1] scales, it cannot
  invert) and we never miss a real impact.
* **A carried-forward `hedge_ratio = 0.8`** — if the company has since stopped
  hedging, the true impact is up to **five times larger** than computed. We
  understate, and we may miss a material impact entirely. **That is the dangerous
  direction and it must not be carried forward silently.**

Stated as a rule: **on carry-forward, a hedge ratio's band becomes `[0, filed
value]`** — widening toward *less* hedging, i.e. toward a larger impact. For a
filed 0.8 this is a real and honest widening. For a filed **0.0 the band cannot
widen**, because it is already at the bound; the only error possible is
overstatement, and the correct treatment is to say so rather than to manufacture
width. Hence the grade cap and the explicit `CARRIED_FORWARD` label doing the work
in that case, not the band.

This also answers a question §17.1 left open: the freshness policy cannot be a
single number per `modifier_kind`, because the safe direction depends on the value
and on which channel consumes it. `PASS_THROUGH`, `PRICE_CAP` and `SUBSIDY_SHARE`
each need the same analysis before a number is written for them, and none has been
done.

#### What the system should do in the window — and what it must not do

**Must not:** silently abstain. Under the strict reading the entire universe goes
dark from 1 April until each company's report lands — four to six months of empty
feed every year, produced not by an absence of knowledge but by a policy that
refuses to read the most recent document in existence. That is not conservatism;
it is a coverage failure that looks like one.

**Should:**

1. **Size the company at SECONDARY with the parameter labelled.** UI copy in the
   §5.2 register — *"hedging: none, per FY2025-26 annual disclosure (carried
   forward; FY2026-27 not yet filed)"*. That is answerable to a W11 objection in a
   way that both silence and an unlabelled number are not.
2. **Never let a carried-forward parameter reach PRIMARY.** The grade cap does this
   structurally, in the same way `ESTIMATED` exposure rows are capped at D today.
3. **Record it on the impact, not only in the log**, so the review console and the
   contradiction audit can both see it. The existing `exposure_stale` flag is the
   precedent; `policy_state_stale` is the Phase 4 analogue. A third flag of the
   same shape is the consistent design.
4. **Measure the blackout.** A coverage metric — *companies currently sizeable
   only via a carried-forward parameter*, and *companies blocked outright by an
   expired one* — so that the annual filing cycle is a visible seasonal effect on
   coverage rather than an unexplained dip.
5. **Prefer a fresher source when one exists.** Some companies restate hedging
   position in quarterly results or investor presentations; a `QUARTERLY` or
   `EARNINGS_CALL` source would re-open the `FILED` state mid-year. That is a
   reason to raise the earnings-call extraction ticket, not a reason to widen the
   annual window further.

#### What this does for CEAT specifically

With the policy above, and `effective_to` left at the honest `2026-03-31`: CEAT is
sizeable today at **`CARRIED_FORWARD`, grade D, SECONDARY only** — which is the
tier it was already capped to by its `ESTIMATED` exposure rows, so **this policy
costs CEAT nothing it had not already lost.** It remains blocked on
`pass_through_curve`, which is a different gap.

**Status: PROPOSED, not implemented.** No `freshness.yaml` key was added, no
checker written, no gate rule changed. **Owner: repo owner.**

---

### 17.4 There is no state for "asked, and the company declines to say"

The ledger can express three things about a parameter today. It needs a fourth.

| state | how it is stored | what `resolve_param` does |
|---|---|---|
| **disclosed value** | row present, parameter named, `measurement` set | resolves; bands by `measurement` |
| **disclosed zero** | row present, value `0.0`, `measurement` set | resolves with a **zero-width band** — the only one of these that publishes |
| **row exists but unbandable** | parameter named, `measurement` absent | `MISSING_MEASUREMENT` — unusable, but flagged in the reason string as *"a data-entry defect somebody can fix"* |
| **nothing known** | no row | `MISSING_ROW` → sector median → `InsufficientParameterData` → abstain |
| **⟵ MISSING: looked, and the disclosure does not say** | *no representation* | collapses into `MISSING_ROW` |

The fourth state is the common one for Indian mid-caps. A filing that discusses
hedging policy in prose without quantifying it, an earnings call where the
question is asked and deflected, a segment note that stops one level above what
is needed — all of these are **evidence that the number is not obtainable from
this source**, and all of them are currently stored as the same silence as a
company nobody has looked at.

**Why it matters:**

* **Work is repeated.** Nothing records that a document was read and came up
  empty, so the next extraction pass reads it again. The bootstrap's 43 unsourced
  companies (§14) have this problem already — `AGGREGATED_SINGLE_LINE` was
  recorded as a *finding classification* in the run artefacts, not as a durable
  ledger state.
* **Coverage metrics lie in the optimistic direction.** A coverage view cannot
  distinguish "we have 9 of 52 and 43 are unattempted" from "we have 9 of 52 and
  43 are attempted-and-unavailable". The second is a much worse number and the
  true one.
* **It is the honest answer to a W11 `MISSING_COMPANY` objection.** "We looked at
  their FY26 report and they do not disclose it" is answerable. Silence is not.
* **It is the input to the build-or-buy decision.** Knowing which parameters are
  systematically undisclosed is what tells you whether a data ticket is worth
  raising at all — which is exactly the question ADR-001 turned on.

**What must be decided:** whether this is a status on the proposal record
(`REJECTED_NOT_DISCLOSED`, retained and visible per invariant 12), a row in the
parameter table with an explicit `not_disclosed` marker and no value, or a
separate `disclosure_attempt` table keyed `(company, document, parameter)`. The
third is the most useful and the most work. **It must not resolve to a value, and
it must not un-abstain anything** — the point is bookkeeping about what is
knowable, not a new way to compute. **Owner: repo owner.**
