# PHASE 7 — EVALUATION HARNESS, SHIPPING GATES & MONITORING
## Where "is it good?" stops being an opinion.

**Prerequisite:** Phase 6 done. Corpus labeling should have been running in parallel since Phase 1.

---

## TASK 7.1 — Labeled corpus

`eval/corpus/`.

**300 historical events**, stratified:

| Stratum | Count |
|---|---|
| Commodity shocks | 60 |
| Policy / regulatory | 50 |
| Company actions (M&A, capex, orders, guidance) | 50 |
| Macro data releases | 40 |
| Geopolitical | 30 |
| Earnings | 20 |
| **Null events** — financial news with no material listed-company impact | **50** |

The null slice is the most valuable and the most commonly omitted. It is the only thing that measures whether the system can say nothing.

Labeling protocol:
- Labelers see the **event only** when producing expected sets. Never system output first — anchoring destroys the label's value.
- **Two independent labelers minimum.** Report Cohen's κ.
- Disagreements → `DISPUTED`, excluded from precision denominators, tracked separately. An honest system reports its own ambiguity rate.
- Labels stored with labeler identity, timestamp, and rationale.

Schema:

```sql
CREATE TABLE eval_event (event_id uuid PRIMARY KEY, stratum text, article_ref text, notes text);
CREATE TABLE eval_label (
  event_id uuid, company_id uuid, labeler text,
  expected_tier text,            -- PRIMARY|SECONDARY_RIPPLE|MACRO_CONTEXT|ABSENT
  expected_direction text, expected_mechanism text, expected_materiality text,
  label text, rationale text, labeled_at timestamptz,
  PRIMARY KEY (event_id, company_id, labeler)
);
```

---

## TASK 7.2 — Metric suite

`eval/harness.py`. Runs in CI on every PR touching analysis code.

```
PRIMARY precision / recall            SECONDARY_RIPPLE precision / recall
wrong-direction rate                  economic-effect accuracy
mechanism accuracy                    directness accuracy
distance accuracy                     materiality accuracy
evidence accuracy                     section accuracy
abstention precision (null events)    calibration ECE / Brier
ripple family recall (vs expected map)   firewall deletion rate
fabricated-numeral rate               internal contradiction rate
same-model vs cross-model verification precision
```

Report per stratum and per sector, not just aggregate. An aggregate number hides that you are excellent on crude and useless on policy.

---

## TASK 7.3 — Shipping gates

CI-enforced. A PR failing any gate cannot merge.

| Metric | Gate |
|---|---|
| PRIMARY precision | >= 0.95 |
| PRIMARY wrong-direction rate | <= 0.02 |
| **PRIMARY false-positive on null events** | **== 0 (hard)** |
| SECONDARY_RIPPLE recall | >= 0.70 |
| SECONDARY_RIPPLE precision | >= 0.80 |
| Ripple family recall (expected map) | >= 0.80 |
| **Fabricated-numeral rate** | **== 0 (hard)** |
| Firewall deletion rate on PRIMARY prose | == 0 |
| **Internal contradiction rate** | **== 0 (hard)** |
| Calibration ECE | <= 0.05 |
| Section assignment accuracy | >= 0.98 |
| Reducer determinism (10k permutations) | 100% |
| Market/fundamental isolation | pass |
| p95 publish latency (cached template) | <= 90s |

The three hard-zero gates are the definition of defensible. Everything else is quality; those three are integrity.

Add a **no-regression rule**: no merge may reduce PRIMARY precision or ripple recall versus the current main branch baseline, even if absolute gates still pass.

---

## TASK 7.4 — Production monitoring

Dashboards and alerts:

| Signal | Why it matters |
|---|---|
| Firewall deletion rate | spike = model or prompt regression |
| Divergence queue volume | spike = broken channel, or alpha |
| Exposure staleness p90 | the ledger rots silently |
| `policy_state` staleness | a stale levy rate is a correctness bug |
| Calibration drift by month | refit quarterly |
| Rejection-reason histogram | `NO_MATERIAL_IMPACT` collapsing toward zero = misconfigured threshold |
| Coverage gap queue depth | should trend down |
| p95 publish latency | the product promise |
| Frontier LLM calls per event | cost control; deterministic layers must eliminate >= 90% of candidates pre-LLM |

---

## TASK 7.5 — Cost cascade verification

Assert the §18 cascade is real:

```
1. deterministic short-circuit (index, cached template, prior identical event) -> 0 tokens
2. stage-result cache keyed (stage, input_hash, model_id, prompt_version)
3. small/fast model — extraction, classification, entailment judging
4. frontier model — only marginal gate-boundary candidates, MIXED resolution,
                    and PRIMARY-eligible falsification
```

Test: a 250-candidate event must not produce 250 frontier calls. Assert `frontier_calls / candidates <= 0.10`.

Prompt structure: cacheable static prefix (safety rules, taxonomy, schema) then dynamic suffix (event, candidate, evidence, graph context). Never dynamic-before-static — it destroys the prefix cache. Add a test asserting prompt assembly order.

---

## TESTS

```
test_corpus_integrity.py
  - >= 300 events, all strata represented, >= 50 null events
  - every label has >= 2 independent labelers
  - Cohen's kappa computed and reported
  - DISPUTED excluded from precision denominators

test_shipping_gates.py
  - all gates evaluated; hard-zero gates fail the build on any violation
  - no-regression rule compares against main baseline

test_cost_cascade.py
  - frontier_calls / candidates <= 0.10 on the corpus
  - prompt static prefix precedes dynamic suffix
  - cache hit on identical repeated event

test_null_events.py
  - zero PRIMARY published across all 50 null events
  - system renders the zero-PRIMARY state correctly
```

---

## DEFINITION OF DONE

- [ ] 300-event corpus complete with >= 2 labelers per event and κ reported
- [ ] Full metric suite in CI, reported per stratum and per sector
- [ ] All shipping gates green, including the three hard zeros
- [ ] No-regression rule enforced
- [ ] Monitoring dashboards live with alerting
- [ ] Cost cascade verified at <= 0.10 frontier calls per candidate
- [ ] `DATA_GAPS.md` reduced to genuinely outstanding items with named owners

---

## DO NOT

- Do not label using system output as the starting point.
- Do not use a single labeler.
- Do not drop the null-event slice because it is boring to build. It is the most important stratum.
- Do not relax a hard-zero gate to unblock a release.
- Do not report only aggregate metrics.
