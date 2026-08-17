# SPEC DEFECTS 003 — absence of measurement is published as measured immateriality

**Raised:** 2026-08-17 · **Status:** OPEN, none fixed · **Owner:** repo owner
**Raised by:** the qualitative-tier design trace (`docs/v5/QUALITATIVE_TIER_DESIGN.md` §A)
**Rule for this document:** it describes defects and the shape a fix must have.
**No fix is implemented and none should be written against this list until the
owner has read it.**

**NUMBERING — claimed range `D11`–`D14`**, recorded in `docs/v5/defects/CLAIMS.md`.
The defect register has more than one author and the ids share one namespace:
`DEFECTS-001` holds **D1–D9**, `DEFECTS-002` holds **D10**. This file was drafted
against D10–D13 and **collided with DEFECTS-002 on D10**; every id here was shifted
up by one before commit. `D11.1` is a sub-item of D11, not a separate claim.
Cross-references to `D1`, `D2`, `D4` and `D9` below point at **DEFECTS-001**.

| # | Defect | Layer | Severity |
|---|---|---|---|
| **D11** | A company with no sized channel publishes `NO_MATERIAL_IMPACT` — absence of measurement rendered as measured immateriality | **reducer + gate, ONE RULE** | **P0 — it is a false statement about the world, produced by an absence in our database** |
| **D11.1** | The §A5.2 coverage note undercounts by exactly the population it exists to describe — the system reports that it checked when it did not | **discovery/coherence, ONE RULE** | **P0, inseparable from D11 — must be fixed in the same change** |
| **D12** | The parameter evidence-grade cap is applied only when a computed band exists | reducer, Phase 2 fix-round-1 C1 | High — reopens C1 on every unsized record |
| **D13** | `_uses_sector_proxy` returns `None` for every paramless channel, so the PRIMARY sector-proxy ban never evaluates | reducer + gate | High — same shape as D12, different rule |
| **D14** | `_prior` returns `0.0` for a candidate with no `share_of_base`, which makes it the first thing evicted | discovery | Medium-high — silent, and it would make the qualitative tier look broken rather than starved |

## Relationship to DEFECTS-001 — checked, and D11 is NOT a duplicate of D4

**Verified against `docs/v5/defects/DEFECTS-001-ceat-proof-of-life.md`, all nine
entries (D1–D9). None of D11–D14 is named there.** D12, D13 and D14 have no
counterpart in that register at all.

D11 and **D4** are the same conflation seen from opposite ends, at different code
sites, and **they must be fixed together or the fix will be half a fix**:

| | D4 (DEFECTS-001) | D11 (this file) |
|---|---|---|
| scope | one **horizon** inside a record | the **whole record** |
| field | `direction_by_horizon[h].evaluated` | `materiality_bucket` → `rejection_reason` |
| site | reducer.py:585-596 + UI copy | reducer.py:551-556 → gates.py:229-231 |
| error | an **evaluated zero** is labelled *"not evaluated"* | a **never-evaluated** company is labelled *"no material impact"* |
| direction | understates what we know | **overstates what we know** |
| user-visible as | a missing analysis | a **positive finding of safety** |

D4 hides a finding. **D11 manufactures one.** D4's proposed fix ("at least three
states on `direction_by_horizon`") is the sibling of D11's fix and the two should be
specified as one state vocabulary, not two.

---

# D11 — "we have no pass-through curve" is published as "there is no material impact"

## What is wrong

`app/core/reducer.py:551-556`:

```python
materiality_bucket = "NONE"
for channel in material:
    if _MATERIALITY_RANK[channel["materiality"]] > _MATERIALITY_RANK[materiality_bucket]:
        materiality_bucket = channel["materiality"]
if materiality_bucket == "NONE":
    materiality_bucket = "NO_MATERIAL_IMPACT"
```

The loop iterates `material`, the list of channels. **When there are no channels at
all the loop body never runs, and the bucket falls through to
`NO_MATERIAL_IMPACT`.** There is no branch distinguishing *"every channel was
computed and none was material"* from *"no channel could be built"*.

`app/core/gates.py:229-231` then hard-blocks it:

```python
("materiality_present",
 draft.materiality_bucket in policy.no_impact_buckets,
 "NO_MATERIAL_IMPACT", str(draft.materiality_bucket)),
```

and `config/gates.yaml:54` defines `no_impact_buckets: [NO_MATERIAL_IMPACT, NONE]`.

## How a company gets there — the measured path

This is not hypothetical. It is the state the CEAT proof-of-life ended in and it is
reproducible today:

1. `app/analysis/sensitivity/params.resolve_param` finds no `pass_through_curve` row
   and no sector median → raises `InsufficientParameterData(reason=MISSING_ROW)`
   (params.py:362-367). Correct behaviour — *"There is no step 4."*
2. `engine.analyse_company` records an `UncomputableChannel` and continues
   (engine.py:294-298). Correct.
3. `engine.py:313` — `if not channels or not base:` → returns
   `SensitivityRun(..., signals=())`. Correct, logged as `ABSTAINED`.
4. The reducer receives **zero CHANNEL signals** → `materiality_bucket` falls
   through to `NO_MATERIAL_IMPACT`. **Here the abstention becomes an assertion.**
5. The gate rejects with `rejection_reason = "NO_MATERIAL_IMPACT"`.

Every step but the fourth is correct, and step 4 is one line.

## Why this is P0

`docs/v5/00_MASTER_CONTEXT.md` THE ONE RULE:

> Every statement shown to a user must be reconstructible from stored structured
> records with provenance.

`NO_MATERIAL_IMPACT` is a **statement about the world**: this event does not
materially affect this company. It is reconstructible from nothing. It is produced by
the **absence** of a `pass_through_curve` row — which is a fact about our database,
not about the company. The record asserts the opposite of what the pipeline knows.

The Hollow Implementation Check asks: *"If I truncate all tables, does the pipeline
abstain rather than produce output?"* The pipeline abstains from **publishing**, and
that has been read as passing the check. It does not abstain from **concluding**: it
writes a rejected row that says the impact was assessed and found immaterial, and
that row is what the review console (invariant 12) shows a human.

Every coverage and eval metric that partitions on `rejection_reason` inherits it,
and one consumer inherits it in a way that is worse than a metric error. That is
D11.1, below.

---

## D11.1 — the §A5.2 coverage note undercounts by exactly the population it exists to describe

**This is the traced consequence of D11 and it is recorded as its own item because it
is not a metric error. It is the system reporting that it checked when it did not.**

`app/discovery/coherence.py` exists to separate two things, and its docstring states
the reason in its own words:

> **THE DISTINCTION THAT KEEPS THE NOTE HONEST.** A peer we could not size is a
> coverage gap. A peer we DID size and found immaterial is not — it is an answer.
> Counting the second kind would turn "we checked and it is fine" into "we do not
> know", which is a lie in our own favour.

`DATA_GAP_REASONS` is the closed set of reasons that mean *"we could not look"*:

```python
DATA_GAP_REASONS = frozenset({
    "NO_EXPOSURE_ROW", "EXPOSURE_STALE", "UNCOMPUTABLE_CHANNEL",
    "NO_EBITDA_BASE", "INSUFFICIENT_PARAMETER_DATA", "ENTITY_UNRESOLVED",
})
```

**`NO_MATERIAL_IMPACT` is not in it — correctly, because the name says the opposite.**
But per D11 that is the reason string a parameter-starved company actually carries.
So in `section_decision`:

```python
data_gap = sum(1 for m in rejected if (m.rejection_reason or "") in DATA_GAP_REASONS)
economic = len(rejected) - data_gap
```

every company that abstained for want of a `pass_through_curve` lands in
**`economic`**, and the rendered note —

> *Apollo Tyres, CEAT, JK Tyre — 2 further names in this sector lack company-level
> input data*

— **omits them.** The note that exists to say "we could not look at these" is
**silent about precisely the companies we could not look at**, because D11 renamed
their abstention into an answer three modules upstream.

**Why this is worse than an undercount.** The docstring guards against one direction
of error: turning *"we checked and it is fine"* into *"we do not know"*, which it
calls a lie in our own favour. **D11.1 runs the other way**, and the other way is the
dangerous one:

| | the error the docstring guards | **D11.1** |
|---|---|---|
| we say | "we do not know" | **"we checked"** |
| truth | we checked | **we did not look** |
| reader concludes | our coverage is worse than it is | **the absent names were considered and found immaterial** |
| self-serving? | yes, mildly | **yes, and it is unfalsifiable from the output** |

A reader shown a two-name tyre section with no coverage note reasonably concludes the
other names in the sector were assessed. They were not. **There is no field in the
published output from which the reader could discover this**, which is the property
that makes it a ONE RULE violation rather than a display bug: the statement the
output makes is not reconstructible from the records, and the records do not contain
the correction.

It also **silently defeats A5.2's own purpose.** A5.2 exists because *"a section
containing one paint maker and nothing else does not read as an analysis; it reads
like a bug."* The coverage note is the fix. With D11 in place the note does not fire
for the failure mode it was written for — an empty ledger — so a lone-name section
publishes bare and reads exactly as the bug A5.2 was written to prevent.

**Fix requirement, additional to D11's:** whatever reason string(s) D11 introduces
must be added to `DATA_GAP_REASONS` **in the same change**. Fixing D11 without this
moves the starved companies from a wrong bucket into a bucket nobody counts, which
is not an improvement. **Acceptance test:** a section in which every peer abstained
for a missing parameter must render a coverage note naming all of them.

## The shape a fix must have

**One state vocabulary, specified once, covering D4 and D11 together.** The
distinction to encode is *did we evaluate?* — separate from *what did we find?*

Two implementation shapes; the choice is the owner's, and **the first is
recommended** because it cannot be lost by a consumer that does not know to look:

**(a) A distinct bucket value.** `materiality_bucket` gains `NOT_SIZED`, which is
**not** in `no_impact_buckets`. Cheap and structural:
* migration 0011 declares `materiality_bucket` as a plain nullable `String` with
  **no CHECK constraint** — verified — so this is **not a schema change**;
* it must be added to `config/horizons.yaml::materiality_weight` in the same change
  or `HorizonPolicy.weight_for` raises `ReducerInputError` on any multi-horizon set
  (reducer.py:134-141);
* it must **not** be spelled `NONE`, or `mechanism_id` resolution (reducer.py:612,
  which reads only `material` channels) drops to `None` and invariant 7 fails on the
  record the change was meant to protect.

**(b) A separate `sizing_status` field** — `SIZED | NOT_SIZED | PARTIALLY_SIZED` —
leaving `materiality_bucket` nullable when not sized. Cleaner conceptually, more
surface: it is a new column on `company_impact`, a new key in
`serialize_company_impact`, and a new gate input.

Requirements either shape must satisfy:

* **A rejected row must never say `NO_MATERIAL_IMPACT` unless a channel was actually
  computed and the result was below the floor.** This is the acceptance test.
* **The reason must name the missing input.** `engine.py` already has it —
  `UncomputableChannel(channel_id, reason, param)` carries `MISSING_ROW(pass_through)`
  — and the reducer never receives it, because an abstaining run emits no signals at
  all. Threading it through is the mechanical part; **it may require the engine to
  emit an `ABSTENTION` signal kind rather than nothing**, which is a design call.
* **`coherence.DATA_GAP_REASONS` must gain the new reason(s)**, or the coverage note
  stays wrong in the same direction.
* **`PARTIALLY_SIZED` is a real third state, not a nicety.** `engine.py:328` already
  logs `PARTIAL` when *some* channels computed and others did not; that record today
  carries a band computed from a subset and says nothing about the subset.
* **UI copy must distinguish the three**, per D4: *"no material effect"* vs
  *"not sized — data missing"* vs *"partly sized"*. Settle the wording with D4's.

**What must NOT be built:** a default parameter, a sector-median fallback, or any
path that makes the channel computable. The abstention is correct. **Only its
label is wrong.**

---

# D12 — the evidence-grade cap is applied only when a computed band exists

## What is wrong

`app/core/reducer.py:662-668`:

```python
if sensitivity is not None:
    evidence_grade = cap_evidence_grade(
        evidence_grade, sensitivity.get("evidence_grade_cap"))
    proxy_param = _dominant_proxy_param(sensitivity)
    ...
        weakest_link = f"{proxy_param}:SECTOR_PROXY"
```

**Both halves of fix-round-1 C1 sit inside `if sensitivity is not None`.** A record
with no computed band gets **no grade cap and no weakest-link bridge**, so its
`evidence_grade` is whatever the best `EVIDENCE_BINDING` signal claimed.

## Why it matters

C1's own comment (reducer.py:634-661) states the defect it closed: *"Phase 2 computed
that cap and nothing consumed it: an all-sector-proxy company with an A-graded claim
binding published PRIMARY."* On the **unsized** path that is still exactly true, and
it is true on the path that carries **every row in production today** — the
V4-forwarded path (`signal_adapters.signals_from_entry` with empty
`sensitivity_channels`) never produces a `sensitivity` block.

`config/materiality.yaml::exposure_measurement_grade_cap` (`ESTIMATED → D`,
`MODELLED → D`) is the cap that keeps the eleven crude-bootstrap rows below PRIMARY.
It reaches the reducer **only through the sensitivity block**. An exposure row's
`measurement` is a property of the row, not of whether anybody sized it.

Fixing D11 makes this **worse, not better**: the qualitative tier's whole population
is records with no `sensitivity` block, so it would ship with the cap disabled by
construction for every row.

## The shape a fix must have

* The exposure row's `measurement` cap must reach the draft **independently of
  whether a band was computed**. It is already on the CHANNEL payload's origin
  (`ExposureView.measurement`, channels.py:130) and is folded into
  `ChannelResult.grade_cap` (channels.py:381-385) — the value exists on the channel
  and the reducer reads it only via `sensitivity`.
* The weakest-link bridge needs a non-variance-based trigger when there is no
  `driver_ranking` to rank. A channel whose parameters are all `SECTOR_PROXY` has a
  sector-proxy weakest link whether or not anybody attributed variance.
* Acceptance test: an unsized record with an A-graded `EVIDENCE_BINDING` and an
  `ESTIMATED` exposure row must not reach PRIMARY.

---

# D13 — the PRIMARY sector-proxy ban never evaluates on a paramless channel

## What is wrong

`app/core/reducer.py:395-407`:

```python
def _uses_sector_proxy(signals) -> bool | None:
    reported = False
    for payload in _payloads(signals, SignalKind.CHANNEL):
        sources = payload.get("param_sources")
        if not isinstance(sources, Mapping):
            continue
        reported = True
        ...
    return False if reported else None
```

A channel with no `param_sources` key never sets `reported`, so the function returns
`None` = NOT KNOWN. `config/gates.yaml:140` sets
`unknown_sector_proxy_passes: true` at PRIMARY, so `gates.py:411-418` passes the
rule as an `unknown_escape`.

**`allow_sector_proxy: false` at PRIMARY — the rule §7.4 states and gates.yaml:77
comments as *"A sector-median parameter may never back a PRIMARY call"* — therefore
never evaluates on any record that does not report parameter sources.** That is every
V4-forwarded record in production and would be every qualitative record.

This is the same shape as D12 (a guard reachable only through the sized path) but a
different rule, a different input and a different config key, so fixing one does not
fix the other.

## The shape a fix must have

* A channel must report its parameter provenance **or declare that it has no
  parameters**. `None` must mean "nobody said", and a channel that structurally has
  no parameters is not "nobody said" — it is `False`, positively.
* `gates.yaml`'s two fail-open keys (`unknown_materiality_delta_passes`,
  `unknown_sector_proxy_passes`) are cutover-checklist item 1. This defect is the
  reason the second one cannot simply be flipped: flipping it today would reject
  every record rather than evaluate the rule, because the input is absent rather
  than false. **The input must be made honest before the key is flipped.** Record
  this ordering in the cutover checklist.

---

# D14 — a candidate with no exposure share is the first thing evicted

## What is wrong

`app/discovery/engine.py:202-222`:

```python
def _prior(share_of_base, confidence, graph_distance) -> float:
    if share_of_base is None:
        return 0.0
    ...
```

`CandidatePool.add` evicts `max(..., key=_rank_key)` and `_rank_key` sorts on
`-expected_materiality_prior` first, so a candidate with prior `0.0` is the **worst**
in the pool and the first evicted when the 250-name bound is reached.

Two populations get `0.0` today:

* every `SUPPLY_CHAIN` candidate — `_extend_supply_chain` passes
  `share_of_base=None` unconditionally (engine.py:317);
* every future qualitative candidate, which has no share by construction.

`MENTION` candidates are exempt (prior `inf`).

## Why it matters

The `_prior` docstring already reasons carefully about a **different** missing input:
*"A missing confidence is not a measured 1.0… Rank missing-LAST instead: an absent
input must never outrank a measured one."* That reasoning is right for `confidence`
— a scalar multiplier where missing-vs-zero is genuinely ambiguous. Applied to
`share_of_base` it means something else: a candidate that **cannot have a share**
is ranked as though it had the worst possible one.

The consequence is silent. Coverage would simply be low, with no log line and no
rejected-candidate record, because eviction happens before anything is recorded. The
qualitative tier would look like it does not work rather than like it was starved,
which is the most expensive kind of bug to diagnose.

## The shape a fix must have

* Ranking must be **within-kind**, or the pool must carry **per-source quotas**. The
  `CandidatePool` docstring already anticipates the shape: *"if one is [observed],
  the fix is a per-source quota in the config, not a silent reordering here."* That
  is the sanctioned route and it should be taken rather than inventing a prior.
* Whatever is chosen must **not** assign a share-less candidate a synthetic share.
  A quota is a policy about attention; a synthetic share would be a claim about a
  company.
* Eviction should be **observable**. A pool that drops candidates should report how
  many and from which source, for the same reason `_log_abstention` exists:
  *"A company that silently sizes nothing looks exactly like a company nobody
  considered."*

---

## Evidence and reproduction

* Live DB state, read-only (`backend/newsflo.db`, 2026-08-17): `company_exposure` 11
  rows (all `ESTIMATED`), `pass_through_curve` **0**, `company_financials` 1,
  `mechanism_edge` 2 (both `PENDING`, both with an unreachable `from_node` — see
  `docs/v5/MEASUREMENTS_2026-08-17.md` §3).
* D11 reproduction is the CEAT abstention already recorded in
  `DATA_GAPS/ceat-proof-of-life.md`: `MISSING_ROW(pass_through)` on both tags,
  `no_ebitda=False`. The abstention is documented there; **what that abstention
  publishes as has not been, and is this defect.**
* No fix written. No table touched. No row inserted.
