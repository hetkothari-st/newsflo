# PHASE 3 — RIPPLE DISCOVERY & COVERAGE
## The phase that fixes "it only finds direct companies".

**Fixes:** paints/tyres/chemicals never surfacing · discovery anchored on article mentions · recall being asked of a language model.

**Prerequisite:** Phase 2 done. Ledger has real rows for at least the top 3 priority tags.

**Reference:** `NEWSFLO_V5_ADDENDUM_RIPPLE_COVERAGE.md` — read it fully before starting.

---

## OBJECTIVE

Turn ripple discovery from LLM recall into a deterministic index query, bootstrap mechanism coverage from input–output tables, and make coverage measurable per axis.

---

## TASK 3.1 — Exposure tag vocabulary

`config/exposure_tags.yaml` — closed, versioned, hierarchical set per spec §6.1. Extending it is a code review, never a runtime decision.

Add a validator: every `exposure_tag` written to `company_exposure` or `mechanism_edge` must exist in the vocabulary. DB-level CHECK against a `valid_exposure_tag` table populated from the YAML at migration time.

---

## TASK 3.2 — Exposure tag index

```sql
CREATE MATERIALIZED VIEW exposure_index AS
SELECT e.exposure_tag, e.exposure_kind, e.company_id, e.share_of_base,
       e.base_value_inr, e.confidence, e.as_of_date, c.adv_20d_inr, c.status
FROM company_exposure e JOIN company c USING (company_id)
WHERE e.share_of_base >= 0.02
  AND c.status = 'ACTIVE';

CREATE INDEX ON exposure_index (exposure_tag, share_of_base DESC);
```

Refresh concurrently on ledger write. Add staleness metric on the view.

---

## TASK 3.3 — Discovery rewrite

`newsflo/discovery/engine.py`. Replace mention-anchored discovery with the four-source model:

```python
def discover(event) -> CandidatePool:
    pool = CandidatePool(max_size=250)

    # 1. MENTION — companies named in the article
    pool.extend(resolve_mentions(event.facts), source="MENTION")

    # 2. MECHANISM — the recall fix
    for shock in event.shocks:
        for edge in graph.traverse(shock.variable, max_depth=3):
            for row in exposure_index.query(edge.exposure_tag,
                                            min_share=THRESH[edge.distance]):
                pool.add(row.company_id, source="MECHANISM",
                         via_tag=edge.exposure_tag,
                         mechanism_id=edge.edge_id,
                         graph_distance=edge.distance)

    # 3. SUPPLY_CHAIN — customer/supplier edges, 1 hop from current pool
    # 4. PEER_CLOSURE — if >=2 members of an industry are in pool,
    #    sweep that industry at a higher share threshold

    return pool.bounded(rank_by=expected_materiality_prior)
```

```yaml
# config/discovery.yaml
distance_thresholds: {1: 0.02, 2: 0.05, 3: 0.10}
max_candidates_per_event: 250
peer_closure_min_members: 2
peer_closure_threshold: 0.08
```

Record `discovery_source`, `via_tag`, `mechanism_id`, `graph_distance` on every candidate as separate fields. These are distinct from `directness` (Phase 0 invariant 4).

---

## TASK 3.4 — Input–output bootstrap

`newsflo/graph/io_bootstrap/`.

1. Ingest India's Supply-Use / Input-Output Transaction Tables (MOSPI; RBI KLEMS for industry series). Store raw with source URL and table year.
2. Normalise to direct input coefficients `a(A→B)`.
3. Compute the **Leontief inverse** `(I − A)⁻¹` → total requirement matrix. This captures indirect transmission rounds and is the core of ripple breadth.
4. Map IOTT/NIC industry codes → internal `sector_id` → candidate `exposure_tag`. Store the mapping in `config/industry_mapping.yaml`; it is hand-authored and reviewable.
5. Emit candidate `mechanism_edge` rows with `derivation='IO_TABLE'`, `io_total_coeff` populated, `reviewed_by=NULL`.

```sql
-- mechanism_edge per addendum A2.3
-- CONSTRAINT: derivation IN ('IO_TABLE','EMPIRICAL') requires reviewed_by NOT NULL
--             before the edge may be used in discovery
```

Prune `total_coeff < 0.02`. Provide a review queue for edges, same pattern as Phase 1 exposure review.

**IO tables inform graph structure only. They never set company materiality — that stays with the filed ledger.**

Note the coverage limit honestly in code comments and `DATA_GAPS.md`: IO tables generate INPUT_COST and DEMAND edges. REVENUE_REALIZATION, FX, rate, and regulatory edges must be hand-authored (~60–100 edges).

---

## TASK 3.5 — Reverse event-study gap detection

`newsflo/analysis/empirical/gap_finder.py`.

For each shock variable and sign:
1. Compute CAR (+1d, +5d, +20d) for the entire listed universe across all historical shock instances.
2. Aggregate by industry: median CAR, IQR, n, sign consistency, p-value.
3. Retain industries with `n >= 15`, `p < 0.05`, sign consistent in >= 65% of instances.
4. Diff against industries the current graph can reach for that variable.
5. Write unexplained industries to `coverage_gap` table, ranked by `|median_car| * n * industry_mcap`.

Output is a **prioritised work queue for graph authoring**, surfaced in the review UI.

**Hard discipline — enforce in the gate:**

```
SECONDARY_RIPPLE requires mechanism_id IS NOT NULL
```

An empirically discovered relationship may never publish until a human authors and reviews a mechanism explaining it. Add a test asserting no publication path exists for empirical-only relationships.

---

## TASK 3.6 — Ripple-specific gates

Split `config/gates.yaml` per addendum A5.1:

```yaml
primary:
  materiality_floor_pct: 2.0
  max_distance: 2
  min_sign_consistency: 0.90
  allow_sector_proxy: false
  min_evidence_grade: C
secondary_ripple:
  materiality_floor_pct: 0.75
  max_distance: 3
  min_sign_consistency: 0.60
  allow_sector_proxy: true
  min_evidence_grade: D
  require_mechanism_id: true
```

Sector coherence rule: when >=3 companies in an industry clear the ripple gate, publish the section. When only one clears and peers were rejected on *data gaps* rather than economics, publish the section with an explicit coverage note rather than a lone name.

---

## TASK 3.7 — Coverage audit harness

`tests/coverage/` + `fixtures/expected_ripple_map.yaml`.

For 12–15 canonical shock classes, a domain expert authors expected families:

```yaml
- shock: {variable: BRENT_CRUDE, sign: UP, magnitude_pct: 6}
  expected_primary:  [upstream_oil, oil_marketing, aviation]
  expected_ripple:   [paints, tyres, adhesives, packaging_films, city_gas,
                      logistics, specialty_chemicals]
  expected_macro:    [inr, imported_inflation, cad]
  expected_marginal: [cement, ceramics]           # scored neither way
  expected_absent:   [banks_direct, it_services]  # false positive if present
```

**Per-axis diagnostic — this is the key deliverable.** When a family is missing, report which axis failed:

```
MISSING: tyres
  V shock variable modelled ....... PASS
  M mechanism edge exists ......... FAIL   no edge crude -> carbon_black -> input tag
  C companies tagged .............. FAIL   0/6 tagged
  G would pass gates .............. n/a
  ROOT CAUSE: mechanism gap (M).  Owner: graph.  7 listed names.
```

`expected_marginal` families are excluded from both numerator and denominator. Do not tune thresholds to capture them.

---

## TESTS

```
test_tag_vocabulary.py
  - unknown exposure_tag rejected at DB level

test_discovery_sources.py
  - crude shock fixture surfaces MECHANISM candidates absent from article text
  - discovery_source, directness, graph_distance, tier remain 4 distinct fields
  - candidate pool respects max_size and distance thresholds

test_io_bootstrap.py
  - Leontief inverse correct on a known 3x3 toy matrix (hand-verified)
  - IO_TABLE edge without reviewed_by cannot be used by discovery
  - coefficients below prune threshold are excluded

test_gap_finder.py
  - synthetic history with an injected reacting industry appears in coverage_gap
  - empirical-only relationship has no publication path (assert REJECTED)

test_ripple_gates.py
  - SECONDARY without mechanism_id => REJECTED
  - ripple materiality floor differs from primary floor
  - sector coherence: 1-of-6 case emits coverage note

test_coverage_audit.py
  - crude shock: ripple family recall >= 0.80 vs expected map
  - SECONDARY precision >= 0.80 maintained
  - expected_absent families do not appear
  - per-axis diagnostic correctly attributes an injected M-gap and an injected C-gap
```

---

## DEFINITION OF DONE

- [ ] Ripple family recall >= 0.80 on the expected-ripple map
- [ ] SECONDARY precision >= 0.80 (never trade this away for recall)
- [ ] Every published ripple carries a `mechanism_id`
- [ ] Per-axis diagnostic reports zero unexplained M-gaps for the top 5 shock classes
- [ ] Crude regression test surfaces paints and tyres
- [ ] Leontief inverse verified against a hand-computed toy matrix
- [ ] `coverage_gap` queue populated and visible in review UI
- [ ] Tag coverage >= 80% of industry market cap for the top 3 priority tags

---

## DO NOT

- Do not publish empirically-discovered relationships without an authored mechanism. Ever.
- Do not loosen ripple thresholds to hit a recall number if it costs precision. Precision floor 0.80 is hard.
- Do not force `expected_marginal` families (cement on crude) into the output. If the math says LOW, LOW is correct.
- Do not populate `io_coefficient` from memory. It comes from published tables or the table stays empty.
- Do not merge discovery_source into directness. This is the exact bug you are fixing.
