# PHASE 4 — POLICY MODIFIERS & HORIZON VECTOR
## The India-specific credibility layer.

**Fixes:** "ONGC POSITIVE on crude" with no windfall levy · OMC direction instability · Oil India three-way contradiction · single flattened direction.

**Prerequisite:** Phase 3 done.

---

## OBJECTIVE

Apply regulatory and contractual transfer functions deterministically, and emit direction at three horizons instead of one.

---

## TASK 4.1 — Policy Modifier Registry

`config/policy_modifiers.yaml` + `newsflo/analysis/policy/`.

Modifier types to implement:

| Type | Effect |
|---|---|
| `THRESHOLD_CAPTURE` | above a level, a fraction of the channel transfers away |
| `HARD_CAP` | channel magnitude clipped at an administered ceiling |
| `STATE_DEPENDENT` | parameters overridden by a tracked policy state variable |
| `SUBSIDY_SHARE` | gain/loss split across parties |
| `FORMULA_PRICING` | channel replaced by an administered formula |
| `REGIONAL_MULTIPLIER` | scaled by geography mix |

Schema:

```sql
CREATE TABLE policy_modifier (
  modifier_id text PRIMARY KEY,
  applies_to_tag text NOT NULL,
  jurisdiction text NOT NULL,
  modifier_type text NOT NULL,
  parameters jsonb NOT NULL,
  effective_from date NOT NULL,
  effective_to date,
  source_url text NOT NULL,
  owner text NOT NULL,              -- named human responsible for currency
  review_interval_days int NOT NULL,
  last_reviewed_at date NOT NULL
);

CREATE TABLE policy_state (
  state_key text PRIMARY KEY,       -- e.g. 'retail_fuel_revision_active'
  state_value jsonb NOT NULL,
  as_of date NOT NULL,
  freshness_days int NOT NULL,
  source_url text NOT NULL,
  owner text NOT NULL
);
```

**Minimum India registry to scaffold** (schema + loader; values supplied by the owner, not by you):
SAED/windfall levy on crude and product exports · APM/administered gas pricing · retail fuel price revision state · fuel excise and state VAT · export duties (steel, rice, sugar) · import duties · PLI schemes · MSP announcements · sugar export quotas · telecom AGR/spectrum · banking risk weights.

---

## TASK 4.2 — Application order

Modifiers run **after** channel computation and **before** net-effect resolution. Never LLM-applied. Deterministic ordering by `modifier_id`.

```python
def apply_modifiers(channels, as_of_date, policy_state) -> ModifiedChannels:
    for mod in registry.active_for(channel.exposure_tag, as_of_date):
        if mod.requires_state and policy_state.is_unknown_or_stale(mod.state_key):
            channel.widen_uncertainty(config.unknown_regime_multiplier)
            channel.cap_evidence_grade("C")
            channel.add_note(f"regime state unknown: {mod.state_key}")
            continue
        channel = mod.transform(channel, policy_state)
        applied.append(mod.modifier_id)
```

Rules:
- Every applied modifier is recorded in `policy_modifiers_applied[]` and **surfaced in the UI**. Showing the user you modelled the windfall levy is worth more than the impact call itself.
- Unknown or stale regime state ⇒ widen band + cap evidence grade at C. Never assume a default regime.
- Stale `policy_state` past `freshness_days` blocks PRIMARY for affected companies.

---

## TASK 4.3 — Horizon vector

Replace single-direction output with three horizons, computed independently:

| Horizon | Window | Dominated by |
|---|---|---|
| `IMMEDIATE` | 0–5 trading days | inventory revaluation, mark-to-market, hedge gains |
| `NEAR_TERM` | current + next quarter | margin transmission, pass-through lag, contract resets |
| `STRUCTURAL` | 2–4 quarters | capex, competitive position, demand destruction |

Each horizon evaluates `pass_through(horizon_days)` and `hedge_ratio_effective(horizon_days)` at that horizon — this is why Phase 1 stored pass-through as a curve.

Add an inventory-revaluation channel type (dominates IMMEDIATE for commodity processors and is the specific mechanism your OMC contradiction was missing).

`headline_horizon` selection: largest `|delta_ebitda_pct_p50| * materiality_weight`, tie-break toward `NEAR_TERM`.

**All three horizons are persisted and rendered. Never discard the non-headline horizons** — discarding them is precisely how V4 produced three contradictory Oil India representations.

Expected OMC output on crude +6.4%:

```
IMMEDIATE  : POSITIVE  (MEDIUM)  inventory gain
NEAR_TERM  : NEGATIVE  (HIGH)    marketing margin squeeze, price frozen
STRUCTURAL : UNCERTAIN (LOW)     depends on revision permission
net_effect : MIXED,  headline = NEAR_TERM
```

---

## TASK 4.4 — Reducer and UI integration

- Reducer folds per-horizon channels into `direction_by_horizon`.
- Net effect across horizons: conflicting material directions ⇒ `MIXED`.
- UI leads with headline horizon; other two on expand.
- `policy_modifiers_applied` rendered as visible chips with links to the source notification.

---

## TESTS

```
test_policy_modifiers.py
  - THRESHOLD_CAPTURE: realization channel above threshold is reduced by
    capture_fraction (hand-verified fixture)
  - HARD_CAP clips at ceiling
  - STATE_DEPENDENT with unknown state widens band and caps grade at C
  - stale policy_state blocks PRIMARY
  - modifier application order is deterministic across runs
  - applied modifiers appear in output payload

test_upstream_realization.py
  - crude +6% with windfall levy active: upstream company does NOT print
    naive POSITIVE·HIGH; realization upside is materially capped
  - with levy repealed (effective_to set), full upside restores

test_horizon_vector.py
  - OMC fixture produces POSITIVE immediate / NEGATIVE near / UNCERTAIN structural
  - net_effect == MIXED, headline_horizon == NEAR_TERM
  - all three horizons persisted and returned by API
  - single-horizon collapse is impossible (schema requires all three)

test_no_llm_policy.py
  - ast scan: newsflo/analysis/policy/* imports no provider module

test_contradiction_regression.py
  - the Oil India fixture from the V4 incident yields exactly one canonical
    fundamental truth with no field-level contradiction
```

---

## DEFINITION OF DONE

- [ ] Registry schema live with owner and review interval per modifier
- [ ] Modifiers applied deterministically, never by LLM
- [ ] Applied modifiers surfaced in API and UI
- [ ] Unknown regime widens uncertainty rather than assuming
- [ ] Upstream-on-crude test reflects the levy correctly
- [ ] OMC three-horizon split reproduces
- [ ] Oil India contradiction regression test passes
- [ ] `policy_state` staleness alerting live
- [ ] `DATA_GAPS.md` lists every modifier awaiting real parameter values and names its owner

---

## DO NOT

- Do not populate modifier parameters (levy rates, thresholds, ceilings) from your own knowledge. Scaffold the entry, leave parameters null, log the gap, name the owner.
- Do not assume a default regime when state is unknown. Widen and cap.
- Do not collapse three horizons into one for UI simplicity.
- Do not let an LLM decide whether a modifier applies.
