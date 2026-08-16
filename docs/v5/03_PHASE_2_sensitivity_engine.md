# PHASE 2 — SENSITIVITY ENGINE
## Materiality becomes a computed number with an uncertainty band.

**Fixes:** HIGH/MEDIUM/LOW assigned by vibe · identical confidence across candidates · inability to defend a magnitude.

**Prerequisite:** Phase 1 done, Tier 1 ledger populated with real rows.

---

## OBJECTIVE

Compute ΔEBITDA per company per shock from ledger data, with a Monte Carlo uncertainty band and driver attribution. **Remove LLM materiality assignment entirely.**

---

## TASK 2.1 — Channel computation

`newsflo/analysis/sensitivity/channels.py`. Implement each channel type per spec §5.1:

```python
def cost_channel(exposure, shock, params, horizon_days) -> ChannelResult:
    delta = -(exposure.base_value_inr
              * exposure.share_of_base
              * shock.delta_pct
              * (1 - params.pass_through(horizon_days))
              * (1 - params.hedge_ratio(horizon_days))
              * exposure.segment_ownership_fraction)
    return ChannelResult(delta_ebitda_inr=delta, ...)
```

Implement: `cost_channel`, `revenue_realization_channel`, `volume_demand_channel`, `fx_transaction_channel`, `fx_translation_channel`, `interest_rate_channel`.

Every `ChannelResult` carries: `exposure_id`, `evidence_ids`, `param_sources` (per parameter: FILED | DISCLOSED_CALL | SECTOR_PROXY | MODELLED), `horizon`, and `mechanism_id`.

**Missing parameter policy — no defaults:**

```python
def resolve_param(company_id, tag, param_name) -> ResolvedParam:
    # 1. company-specific value from ledger        -> source=FILED/DISCLOSED_CALL
    # 2. sector median from ledger aggregate       -> source=SECTOR_PROXY, widen band
    # 3. NOTHING AVAILABLE                          -> raise InsufficientParameterData
    #    Caller marks the channel UNCOMPUTABLE. It does not publish.
```

There is no step 4. A channel that cannot be computed is not a channel.

---

## TASK 2.2 — Parameter distributions

`newsflo/analysis/sensitivity/params.py`.

Every parameter resolves to a distribution, not a scalar:

```python
@dataclass(frozen=True)
class ParamDist:
    name: str
    point: float
    lo: float
    hi: float
    dist: Literal["triangular","normal","uniform"]
    source: Literal["FILED","DISCLOSED_CALL","SECTOR_PROXY","MODELLED"]
    evidence_id: UUID | None
```

Band width rules (config, not hardcoded):
- `FILED` → narrow (±10% relative)
- `DISCLOSED_CALL` → moderate (±20%)
- `SECTOR_PROXY` → wide (±40%), and caps evidence grade at C
- Widen further when a policy modifier state is UNKNOWN (Phase 4 hook — leave the multiplier parameter in place now)

---

## TASK 2.3 — Monte Carlo

`newsflo/analysis/sensitivity/monte_carlo.py`.

```python
def simulate(channels, n=2000, seed=None) -> MaterialityResult:
    """
    seed = stable_hash(event_id, company_id, analysis_version)
    => reproducible. Same inputs always yield the same band.
    """
```

Emit exactly:

```python
@dataclass
class MaterialityResult:
    delta_ebitda_pct: Percentiles        # p10, p50, p90
    sign_consistency: float              # fraction of draws sharing p50's sign
    bucket: Literal["HIGH","MEDIUM","LOW","NO_MATERIAL_IMPACT"]
    driver_ranking: list[DriverContribution]  # variance attribution per parameter
    uncomputable_channels: list[str]
```

Driver attribution: variance-based (Sobol first-order, or a simple correlation-ratio approximation — document which). `driver_ranking` is a **product feature** and must reach the API and UI, not just logs.

Bucketing thresholds live in `config/materiality.yaml`, single source of truth:

```yaml
buckets:
  HIGH:   {min_abs_pct: 5.0}
  MEDIUM: {min_abs_pct: 2.0}
  LOW:    {min_abs_pct: 0.5}
  # below LOW => NO_MATERIAL_IMPACT
sign_consistency:
  directional_claim_min: 0.90     # required for PRIMARY
  secondary_min: 0.60             # below this => MIXED or UNCERTAIN
```

---

## TASK 2.4 — Wire into the reducer, remove LLM materiality

- Sensitivity engine emits `CHANNEL` signals; reducer folds them.
- **Delete** every code path where an LLM assigns materiality, confidence, or magnitude. Grep for the prompts and remove them.
- Add the sign-consistency rule to net-effect resolution:

```
sign_consistency >= 0.90  -> directional claim permitted
0.60 <= sc < 0.90         -> direction = UNCERTAIN, max tier SECONDARY_RIPPLE
sc < 0.60 with material magnitude both sides -> MIXED
```

---

## TASK 2.5 — API and UI surface

Expose per company: `delta_ebitda_pct` band, `bucket`, `sign_consistency`, top 3 drivers with their source and value.

UI contract — never a bare number:

```
NEGATIVE · NEAR TERM · −3.2% EBITDA (range −6.0% to −1.1%)
Most sensitive to: pass-through 55% (Q2 FY26 earnings call)
```

---

## TESTS

```
test_channel_math.py
  - 20 hand-computed worked examples reproduce within 0.1% tolerance
    (fixtures with explicit expected values, computed by hand and documented)
  - missing parameter raises InsufficientParameterData, never returns a default
  - channel with SECTOR_PROXY param carries widened band and grade cap

test_monte_carlo.py
  - same (event, company, version) => byte-identical band across runs
  - sign_consistency == 1.0 when all params share sign
  - sign_consistency < 0.6 when band straddles zero symmetrically
  - driver_ranking sums to ~1.0 and identifies the injected dominant parameter

test_no_llm_materiality.py
  - ast scan: newsflo/analysis/sensitivity/* imports no provider module
  - grep assertion: no prompt template contains materiality assignment language

test_sign_consistency_gate.py
  - candidate with sc=0.55 and material both sides publishes MIXED, not a direction
  - candidate with sc=0.75 cannot reach PRIMARY

test_confidence_variance.py
  - across the fixture corpus, materiality values have stdev > threshold
    (regression guard against the V4 near-constant-confidence bug)
```

---

## DEFINITION OF DONE

- [ ] 20 worked examples reproduce within tolerance
- [ ] Monte Carlo deterministic under fixed seed
- [ ] No LLM assigns materiality, confidence, or magnitude anywhere in the codebase
- [ ] Sign-consistency rule enforced in the reducer
- [ ] Materiality variance test passes — values are no longer near-constant
- [ ] Missing parameters produce abstention, never defaults
- [ ] Band and drivers exposed through API and rendered in UI
- [ ] Full suite green

---

## DO NOT

- Do not invent elasticities, pass-through ratios, or hedge ratios to make a channel computable.
- Do not fall back to a "reasonable default" anywhere. Raise and abstain.
- Do not present a p50 without its band in any user-facing surface.
- Do not let sector proxies reach PRIMARY.
