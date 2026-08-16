# PHASE 5 — EMPIRICAL CROSS-CHECK, CALIBRATION & SURPRISE
## Making claims falsifiable and confidence meaningful.

**Fixes:** causal graph asserting untested relationships · confidence as an arbitrary number · no answer to "isn't this already priced in?".

**Prerequisite:** Phase 4 done.

---

## TASK 5.1 — Event-study transmission matrix

`newsflo/analysis/empirical/event_study.py`. Offline, rebuilt weekly.

1. Build historical shock series per economic variable, >= 8 years.
2. Shock instance = `|move| > 1.5σ` of the variable's daily distribution, deduplicated to one per 5-day window.
3. CAR at +1d, +5d, +20d using a market-and-sector-adjusted return model. Start with sector-beta residual; document the estimator and version it. Handle: thin trading, corporate actions, listing date, circuit limits.
4. Persist:

```sql
CREATE TABLE transmission_empirical (
  company_id uuid, shock_variable text, shock_sign text, horizon text,
  n_events int, median_car numeric, iqr_lo numeric, iqr_hi numeric,
  p_value numeric, sign_consistency numeric,
  estimator_version text, computed_at timestamptz,
  PRIMARY KEY (company_id, shock_variable, shock_sign, horizon, estimator_version)
);
```

---

## TASK 5.2 — The check and conflict handling

```python
def empirical_check(impact, row) -> Literal["AGREE","CONFLICT","WEAK","NO_DATA"]:
    if row is None or row.n_events < 10:  return "NO_DATA"
    if row.p_value > 0.10:                return "WEAK"
    return "AGREE" if sign(row.median_car) == sign(impact.headline_direction) else "CONFLICT"
```

**Conflict is not auto-reject.** Empirical history can reflect a regime that no longer applies (pre-windfall-tax upstream behaved differently), and the market may simply have been wrong — that is the alpha the product claims.

```
CONFLICT  -> cap tier at SECONDARY_RIPPLE
          -> attach objection severity MAJOR
          -> route to divergence_review queue
Human reviewer may mark REGIME_CHANGED with a reason; PRIMARY then becomes
available for that (company, shock_class) going forward, recorded with an
expiry date.
```

Surface in UI — this is a feature, not an apology:

> Our fundamental read is positive. In 34 comparable historical shocks this name's 5-day abnormal return was −1.4% (IQR −3.2 to +0.1). We are taking the other side of history here.

---

## TASK 5.3 — Calibrated confidence

`newsflo/analysis/calibration/`.

Delete LLM-emitted confidence entirely. Define:

> `calibrated_p` = P(published directional call at headline horizon is judged CORRECT by expert review)

Feature vector (all deterministic, no LLM score): `materiality_p50`, `band_width`, `sign_consistency`, `graph_distance`, `directness`, `evidence_grade`, `weakest_link_kind`, `n_bound_claims`, `param_proxy_fraction`, `empirical_status`, `empirical_n`, `empirical_p`, objection counts by severity, `event_status`, `shock_magnitude_confidence`, `surprise_score`, `sector_id`, `exposure_freshness_days`.

Fit isotonic regression on the Phase 7 labeled corpus. Version the model. Report reliability diagram, ECE, Brier score — overall, per tier, per sector.

**Out-of-distribution gate:** Mahalanobis distance or isolation forest over the training manifold. `in_distribution=false` ⇒ cap tier at SECONDARY_RIPPLE. Novel event types must not inherit confidence from unrelated history.

**Bootstrapping note:** until the corpus exists, ship with calibration disabled and `calibrated_p = null`. The UI shows evidence grade and band instead. **Do not ship a fitted-looking model trained on synthetic labels.**

---

## TASK 5.4 — Surprise engine (Axis C)

`newsflo/analysis/surprise/`.

```python
@dataclass
class Surprise:
    consensus_gap_sigma: float | None    # (actual - consensus)/σ where consensus exists
    forward_curve_implied: float | None  # fraction already in futures pre-event
    novelty_score: float                 # 1 - max cosine similarity to prior 7d events
    dissemination_stage: str             # EARLY|SPREADING|SATURATED
    first_seen_at: datetime
    latency_ms_from_first_seen: int
    information_value: float             # config-weighted composite
```

Rules:
- Axis C **never** alters direction or materiality. Enforce with an ast-scan test: sensitivity and policy modules import nothing from `surprise`.
- Drives feed ranking, an `ALREADY WIDELY REPORTED` badge, and the `ALREADY_PRICED` objection at WARN severity.
- `latency_ms_from_first_seen` is the core product SLO. Target **p95 <= 90s** ingest-to-publish for cached shock templates. Degrade gracefully: publish event + macro context immediately, companies as they clear the gate. Never block the feed on a slow candidate.

---

## TASK 5.5 — Market reaction engine isolation (Axis B)

Formalise the existing market branch as a fully isolated module: price, benchmark, excess move, volume z-score, reaction significance, session state, data quality.

Hard boundary: `newsflo/market/*` is import-forbidden from `newsflo/core/*` and `newsflo/analysis/*`. Enforce in CI.

**Divergence is a monitoring signal, never a correction.** When fundamental direction and excess move disagree beyond a threshold, write to `divergence_review` and alert. Do not resolve silently in either direction.

---

## TESTS

```
test_event_study.py
  - CAR computation matches a hand-computed fixture
  - thin-trading and corporate-action edge cases handled
  - estimator version recorded on every row

test_empirical_check.py
  - n < 10 => NO_DATA;  p > 0.10 => WEAK
  - opposite sign with significance => CONFLICT
  - CONFLICT caps tier at SECONDARY, does not reject
  - REGIME_CHANGED annotation restores PRIMARY eligibility with expiry

test_calibration.py
  - ECE <= 0.05 on holdout (skipped until corpus exists)
  - OOD feature vector sets in_distribution=false and caps tier
  - no LLM-sourced confidence value exists anywhere (grep + ast scan)
  - with calibration disabled, calibrated_p is null and UI degrades correctly

test_surprise_isolation.py
  - ast scan: analysis/sensitivity and analysis/policy import nothing from surprise
  - mutating surprise fields leaves direction and materiality byte-identical
  - ALREADY_PRICED objection raised at WARN when forward_curve_implied is high

test_market_isolation.py
  - ast scan: core and analysis import nothing from market
  - divergence writes to review queue and never mutates CompanyImpact
```

---

## DEFINITION OF DONE

- [ ] Transmission matrix built over >= 8 years for the top 10 shock variables
- [ ] CONFLICT handling downgrades and queues rather than rejecting or ignoring
- [ ] Empirical context rendered in UI including disagreement cases
- [ ] All LLM-sourced confidence removed
- [ ] Calibration harness complete; disabled and null until the corpus exists
- [ ] OOD gate functional
- [ ] Surprise engine live and provably unable to affect Axis A
- [ ] Market isolation enforced in CI
- [ ] p95 publish latency instrumented and dashboarded

---

## DO NOT

- Do not auto-reject on empirical conflict. Downgrade and queue.
- Do not fit calibration on synthetic or self-generated labels. Disabled beats fake.
- Do not let surprise or market data touch direction or materiality.
- Do not publish a confidence number without its band and dominant driver.
