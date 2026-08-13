# Corrective V4 — final self-audit + implementation report

Date: 2026-08-13
Branch: `ingestion-v2-ui4`
Range audited: `c37999b..abcc864` (Tasks 1–21 of `docs/superpowers/plans/2026-08-13-newsflo-corrective-v4.md`)
Binding spec: `docs/specs/NEWSFLO_FINAL_CORRECTIVE_IMPLEMENTATION_SPEC.md`

**This report does not claim "100% accurate" and does not claim production readiness.**
The spec §63 release gate is **not fully satisfied** (items 4, 11, 12, 13 are unmet — see
§18). `IMPACT_ENGINE_V4_STRICT` remains **OFF** everywhere.

Everything below was re-verified by me against the current tree at HEAD `abcc864`; no
number or claim is carried over from an earlier task report.

---

## 0. Verification actually run for this report

| command | result |
|---|---|
| `backend/.venv/Scripts/python.exe -m pytest tests/ -q` | **2043 passed, 2 skipped**, 7 warnings, 82.53s, exit 0 |
| `backend/.venv/Scripts/python.exe tools/offline_benchmark.py` | 23 fixtures, all 15 scored metrics 100%, exit 0 |
| `backend/.venv/Scripts/python.exe tools/run_offline_suite.py` | 6/6 steps PASS, exit 0 |
| `frontend: npx tsc --noEmit` | exit 0, zero diagnostics |
| `frontend: npm test -- --run` | 113 test files, **757 passed, 4 skipped** (761), 13.57s, exit 0 |
| `pytest tests/test_v4_invariants.py tests/test_audit_bypasses.py -q` | 73 passed (47 invariants + 26 bypass pins) |

---

## 1. Exact files changed

`git diff --stat c37999b..HEAD` reports **122 files, +18138 / −1095**. Five of the commits
in that range are **concurrent-session work by another session on the same branch**, not
part of this plan, and are excluded from every claim in this report:

| commit | subject | files |
|---|---|---|
| `b7773c0` | fix: MORE button only when a headline line is actually hidden | `frontend/src/v4/ExpandableTitle.tsx` |
| `4de9e13` | fix(timeline): collapse stacked generations to latest per horizon | `backend/app/market/timeline_entries.py`, `backend/tests/test_timeline_entries.py` |
| `6d82124` | feat: ANALYSIS_PAUSED freezes the feed while ingestion keeps flowing | `backend/app/config.py` (+5), `backend/app/scheduler.py` (+5) |
| `cebb3fe` | fix: pulse timestamps serialize with their UTC marker | `backend/app/routers/pulse_live.py`, `backend/tests/test_pulse_live.py` |
| `ea9772d` | feat(v4): 'night print' dark theme; v1 palette preserved | `frontend/src/v4/v4.css` |

`backend/app/scheduler.py` appears in the range **only** because of `6d82124`. No
corrective-V4 commit touches the scheduler (`git log c37999b..HEAD -- backend/app/scheduler.py`
returns exactly one commit, `6d82124`).

### Backend — engine / gate / analysis
`app/analysis/impact_graph/publication_gate.py` (+680/−…, near-rewrite),
`app/analysis/impact_graph/engine.py` (+549),
`app/analysis/impact_graph/evidence.py` (**new**, 266),
`app/analysis/impact_graph/materiality.py` (**new**, 75),
`app/analysis/impact_graph/schemas.py` (+214),
`app/analysis/impact_graph/router.py` (+110),
`app/analysis/impact_graph/exposure.py` (+36),
`app/analysis/impact_graph/prompts.py` (+25),
`app/analysis/impact_graph/gemini_json.py` (+6),
`app/analysis/refinement.py` (+258), `app/analysis/cascade.py` (+11).

### Backend — pipeline / market / API / model
`app/pipeline.py` (+890), `app/models.py` (+169),
`app/market/ripple_layers.py` (+244), `app/market/measure.py` (+165),
`app/market/calendar.py` (**new**, 118), `app/market/discovery.py` (+87),
`app/market/alert_measurement.py` (+55), `app/market/sector_indices.py` (+12),
`app/routers/feed_v2.py` (+126), `app/routers/internal_audit.py` (**new**, 83),
`app/routers/stock_deep_dive.py` (+6),
`app/reasoning/confidence.py` (+69), `app/reasoning/compliance.py` (+12),
`app/companies/matching/matcher.py` (+67), `app/config.py` (+26 incl. 5 foreign),
`app/db.py` (+35), `app/main.py` (+4), `benchmark_impact_graph.py` (+14),
`requirements.txt` (+1, alembic).

### Backend — migrations & offline tooling
`alembic.ini`, `alembic/env.py`, `alembic/README`, `alembic/script.py.mako`,
`alembic/versions/0001_baseline.py` … `0006_decision_record.py` (all new),
`tools/offline_benchmark.py` (**new**, 801), `tools/run_offline_suite.py` (**new**, 202),
`tools/generate_audit_report.py` (**new**, 123),
`benchmarks/regression_events/*.json` (**23 new labeled fixtures**).

### Backend — tests (new)
`test_audit_bypasses.py` (772), `test_decision_record_audit.py` (599),
`test_exposure_self_certification.py` (672), `test_market_integrity_v2.py` (470),
`test_migrations.py` (361), `test_sections_structural.py` (327),
`test_offline_benchmark.py` (294), `test_fallback_quality.py` (268),
`test_verifier_revalidation.py` (265), `test_multichannel_merge.py` (250),
`test_event_model.py` (236), `test_entity_business_validation.py` (226),
`test_feed_primary_only.py` (204), `test_evidence_records.py` (193),
`test_explanation_validation.py` (178), `test_price_fundamental_decoupling.py` (171),
`test_materiality_composite.py` (125), `test_matching_matcher.py` (84),
`test_truth_vocabulary.py` (62), `test_discovery.py` (+54).
Substantially extended: `test_v4_invariants.py` (+1246), `test_publication_gate.py` (+574),
`test_pipeline.py` (+216), `test_v4_strict_gate_wiring.py` (+203).

### Frontend
`src/v4/FeedTruth.test.tsx` (**new**, 244), `src/v3/api.ts` (+89),
`src/v4/charts/chartComponents.tsx` (+86), `src/v4/FeedV4.tsx` (+47),
`src/v4/DeepDiveV4.tsx` (+23), `src/v4/SectionsV4.tsx` (+22),
`src/v4/charts/chartsData.ts` (+22), `src/lib/feedV2Api.ts` (+8),
`src/lib/auth.tsx` (+8), `src/components/feed-v2/FeedRowV2.tsx` (+6),
plus 4 test files. (`ExpandableTitle.tsx` and `v4.css` also carry foreign edits.)

---

## 2. Exact migrations / schema changes

Alembic was introduced by this plan (`backend/alembic/`, `requirements.txt` +alembic).
Every data migration is **inspector-guarded**: `models.py` already declares each column, so
a DB built by legacy `create_all()` is upgraded idempotently rather than erroring.

| rev | scope | operations |
|---|---|---|
| `0001_baseline` | whole schema | Baseline capture of the pre-existing schema (650 lines) so later revisions have a root. |
| `0002_evidence` | new table | `evidence_records` (24 columns: `event_id`→alerts, `company_id`→companies, `evidence_class`, `evidence_tier`, `source_type/name/url/date`, `as_of_date`, `quoted_text`, `fact_text`, `quality`, `reliability`, `provenance_type`, `supports_claim/direction/materiality`, `created_at`, `verified_at`, `review_after`) + index `ix_evidence_alert_company(event_id, company_id)`. |
| `0003_exposure_provenance` | `company_node_exposures` | +`review_after` (DateTime tz), `source_type`, `source_url`, `source_date` (Date), `evidence_id` (Integer, no DB-level FK), `verification_version`. |
| `0004_event_model` | `alerts`, `alert_companies` | +`alerts.event_cause`, +`alert_companies.expected_market_sensitivity`. |
| `0005_market_integrity` | `market_moves` | +`data_quality`, `session_state`, `reaction_significance`. |
| `0006_decision_record` | `company_decision_records`, `alert_companies`, `impact_edges` | +7 decision-record columns (`discovery_sources_json`, `gate_inputs_json`, `evidence_ids_json`, `provider`, `model`, `analysis_quality`, `correction_json`); index `ix_decision_alert_ticker(alert_id, ticker)` (**deliberately NOT unique** — REJECT_DUPLICATE rows are the audit trail, ledger ruling); `UNIQUE(alert_id, company_id)` on `alert_companies` with a **FK-safe pre-dedupe** that repoints or drops children in `calibration_samples`, `car_outcomes`, `email_notifications`, `alert_company_translations` before deleting a loser row (SQLite has FK enforcement off — otherwise silent orphans); index `ix_impact_edges_alert_id`. |

`tools/run_offline_suite.py` step 1 runs `alembic upgrade head` on a throwaway DB and then
asserts the migrated schema carries every table/column the ORM declares
(`validate_schema`) — an upgrade returning 0 is not accepted as proof on its own. That step
**PASSED** in this run.

---

## 3. Exact new classes / functions

**`app/analysis/impact_graph/publication_gate.py`** — `CandidateInput`, `GateContext`,
`GateDecision` (dataclasses); `is_gated`, `materiality_grade`, `_effective_grade`,
`evidence_tier_of`, `candidate_identity`; the 13 checks
`_check_entity_valid`, `_check_duplicate_free`, `_check_business_model_valid`,
`_check_mechanism_valid`, `_check_company_specific_exposure_valid`,
`_check_event_applicability_valid`, `_check_causal_path_valid`,
`_check_materiality_valid`, `_check_evidence_valid`, `_check_contradiction_free`,
`_check_counterfactual_valid`, `_check_quality_valid`, `_check_verified`;
the executable `GATE_SEQUENCE` list; `evaluate_candidate`, `_primary_authorized`,
`_display_tier`, `_rank_key`, `_decision_identity`, `finalize_alert_decisions`;
constants `REJECTION_STATES`, `KNOWN_EVIDENCE_TIERS`, `STRONG_TIERS`,
`RELATIONSHIP_TIERS`, `NON_AUTHORIZING_TIERS`, `POLICY_VERSION = "pol-1"`.

**`app/analysis/impact_graph/evidence.py`** (new) — `classify_evidence`, `persist_evidence`,
`_MARKET_OBSERVATION_PHRASES`, `_PROVENANCED_EXPOSURE_TYPES`.

**`app/analysis/impact_graph/materiality.py`** (new) — `materiality_grade` (composite), `_cap`.

**`app/analysis/impact_graph/engine.py`** — `_subject_companies_ex`, `_cached_subjects`,
`_candidate_pool`, `_merge_company`, `_union_preserve_order`, `_final_materiality_prune`,
`_apply_company_correction`, `_write_exposure_cache` (now returns `bool`),
`_GraphState.fresh_cache_tickers`.

**`app/analysis/impact_graph/schemas.py`** — `normalize_effect`, `direction_to_effect`,
`schema_companies_batched`, `EVENT_CAUSES`, `MARKET_SENSITIVITY_LEVELS`,
`IMPACT_SCHEMA_VERSION`.

**`app/pipeline.py`** — `_persist_effect`, `_dedup_reuse_policy_allows`,
`_copy_gate_audit_trail`, `_analysis_model_for_provider`, `_roots_in_event`,
`_company_profile_supports_mechanism`, `_gate_candidates`,
`_exposure_level_for_candidate`, `_gate_quality`.

**`app/market/`** — `calendar.is_trading_day`, `calendar.session_state`,
`calendar.trading_days_between`, `measure.reaction_significance`, `measure._bar_is_valid`,
`alert_measurement.compute_alert_measurement`, `ripple_layers._strict_sections`,
`ripple_layers._TAXONOMY_LABELS` / `OTHER_LABEL`.

**`app/routers/`** — `feed_v2._primary_company_ids`, `feed_v2._strict_displayable`,
`feed_v2.get_feed_v2_deep_dive`; `internal_audit` (new router: `get_decisions`, `_serialize`).

**`app/analysis/refinement.py`** — `validate_closed_world`, `_sanitize_mechanism`,
`_extract_capitalized_ngrams`, `divergence_line`.

**`app/models.py`** — `EvidenceRecord`; `CompanyDecisionRecord` extended by 7 columns.

**Tools** — `tools/offline_benchmark.py` (`ReplayRouter`, `seed_universe`, `stub_network`,
`run_fixture`, scorers), `tools/run_offline_suite.py` (`validate_schema`, `_child_env`,
`_run`), `tools/generate_audit_report.py`.

---

## 4. Removed / bypassed legacy paths

1. **Realized-price magnitude calibration** — `app.calibration.blender.get_calibrated_magnitude`
   now has **zero call sites** in `backend/app` (verified by grep: only doc comments in
   `pipeline.py:373/1414`, `cascade.py:1128`, `backfill_categories.py:11`).
   `_build_alert_company` (`pipeline.py:395`) uses the analysis's own
   `magnitude_low/high` unconditionally.
2. **Price → confidence** — `compute_confidence` (`reasoning/confidence.py:80`) is
   keyword-only over `claim_count, evidence_ref_count, rule_matched, source_credibility,
   article_age_hours`. It has no price/return/market parameter at all. The financial
   snapshot fetched at `pipeline.py:406` is persisted as observation only
   (`price_at_analysis`, `return_1m`, `return_3m`, `contradiction_note`).
3. **LLM `evidence_refs` inflating confidence** — only `matched_rule_ids` (refs that
   resolved against the real rulebook) feed `evidence_ref_count` (`pipeline.py:400,426`).
4. **Exposure self-certification** — the deterministic pre-verification auto-accept in
   `_verify_companies` is deleted (`engine.py:1014-1029`); every candidate faces this
   event's verifier. `_write_exposure_cache` writes `provenance_type=MODEL_VERIFIED`, which
   `classify_evidence` grades **D**, never C (`evidence.py:191,216-219`).
5. **Self-echo** — a `CompanyNodeExposure` row this run's own `_write_exposure_cache` just
   wrote is skipped entirely by the evidence classifier
   (`evidence.py:216` + `engine.py:1126-1128` `fresh_cache_tickers`).
6. **Legacy 3-tier section generator** — structurally unreachable for gated data:
   `ripple_layers.py:481` `if alert_is_gated: return _strict_sections(...) or []`, which
   reads `is_gated` (`publication_gate.py:126`) and **not** the settings flag.
7. **LLM-authored card sections for gated alerts** — `refinement.py:800,857` skip the
   `generate_ripple_layers` call entirely when `is_gated`, so no LLM section title can even
   be produced, let alone read.
8. **Confidence floor as a second persistence authority** — `pipeline.py` applies
   `CONFIDENCE_FLOOR` only when `"gate_state" not in entry` (legacy/ungated entries).
9. **Measurement overwriting `direction` + deleting fundamental prose** —
   `measure_and_reconcile_alert_companies` returns before the reconcile loop in strict mode
   (`pipeline.py:552`). (Flag-off this legacy behavior is intentionally preserved — see §17.)
10. **Dedup-reuse gate bypass** — `_dedup_reuse_policy_allows` (`pipeline.py:295`).
11. **`"neutral"` reaching `economic_effect`** — `_persist_effect` (`pipeline.py:213`)
    normalizes at the persist boundary.

---

## 5. Publication-gate flow

```
analyze_article_v3 (engine)                     -> ImpactGraphResult
  _v3_entries (pipeline.py:1348)
    if settings.impact_engine_v4_strict:
      _gate_candidates (pipeline.py:1172)
        per GraphCompany:
          classify_evidence(session, company, subject_tickers, fresh_cache_tickers)
              -> (evidence_class, evidence_tier, evidence_payloads)
          entity_status  = ambiguous | resolved | unresolved   (pipeline.py:1249-1255)
          grade          = materiality.materiality_grade(float, exposure_level, tier, False)
          trigger_shock  = _roots_in_event(result, company)    (pipeline.py:1132)
          verification_available = not budget_exhausted and not failed
                                   and not metrics["verification_unavailable"]
          evaluate_candidate(CandidateInput(...), GateContext())
              -> walks GATE_SEQUENCE (13 checks, publication_gate.py:473)
                 first non-None terminates -> REJECT_* / excluded
                 all pass -> DISPLAY_ELIGIBLE + _display_tier()
      finalize_alert_decisions (publication_gate.py:576)
         dedup by resolved company_id (loser -> REJECT_DUPLICATE)
         primary cap (overflow DEMOTED to secondary_deep_dive, never deleted)
  _persist_alert
     writes one CompanyDecisionRecord per candidate (incl. rejected + unresolved
       + ambiguous-entity drops)  -> pipeline.py ~830-915
     `entries = [e for e in entries if e.get("display_tier") != "excluded"]`
     _build_alert_company sets display_tier + gate_state on the AlertCompany row
```

Gate ordering is the constant `GATE_SEQUENCE`, not straight-line `if`s — the execution
order **is** the documented order (INV-006 by construction). The gate module imports only
`app.config`: no DB, no LLM, no market field can enter it.

---

## 6. Evidence flow

`classify_evidence` (`evidence.py:60`) is a deterministic ordered walk:

1. market-observation phrasing in rationale/mechanism → `ARTICLE_MARKET_OBSERVATION` /
   **MARKET_OBS**, no record (taints before anything can rescue it);
2. a `SupplyLink` between candidate and its company-parent → `VERIFIED_RELATIONSHIP` /
   **C** with a payload citing `source_agency`, `source_url`, verbatim `evidence`;
3. a fresh `CompanyNodeExposure` row: `provenance_type in (SUPPLY_LINK, MANUAL, CURATED)` →
   **C**; `MODEL_VERIFIED` → **D**; `NULL` → `LEGACY_UNVERIFIED` / **D**; skipped entirely
   when the ticker is in `fresh_cache_tickers` (self-echo guard); a stale row falls through
   like "no row" (`exposure_row_is_fresh`, incl. `review_after` expiry);
4. article subject list → `ARTICLE_SUBJECT` / **SUBJECT**;
5. `discovery_source` startswith `archetype:` → `CURATED_ARCHETYPE` / **D**;
6. otherwise `MODEL_INFERENCE` / **E**.

Payloads become real rows via `persist_evidence` (`evidence.py:238`) once the alert id
exists, deduplicated on `(alert, company, source_url, fact_text)`. Ids are written to
`CompanyDecisionRecord.evidence_ids_json` and to `candidate_json.evidence_ids`.

Gate consumption: `_check_evidence_valid` rejects `E` and `MARKET_OBS` outright and rejects
an unknown tier (fail closed); `_check_business_model_valid` requires A/B when no company
profile/exposure exists; `_primary_authorized` requires `STRONG_TIERS` (A/B/C/SUBJECT) at
d1 and `RELATIONSHIP_TIERS` (A/B/C only) at d2.

---

## 7. Materiality flow

`GraphCompany.materiality` (LLM float) → `materiality.materiality_grade(float,
exposure_level, evidence_tier, shock_magnitude_known)` (`materiality.py:33`), which **only
caps downward**:

- `None` → `UNKNOWN` (unmeasured ≠ small);
- base grade `>=0.6 HIGH`, `>=0.35 MEDIUM`, else `LOW`;
- `exposure_level in {NONE, LOW}` caps at MEDIUM;
- `evidence_tier == "E"` caps at LOW;
- `exposure_level is None` (no prior on file) applies **no** cap — absence of record is not
  evidence of absence.

`exposure_level` comes from `_exposure_level_for_candidate` (`pipeline.py:1306`) — the
company's `CompanyExposure` ordinal at the mechanism's own dimension, only when the
candidate carries an `archetype:<mechanism_id>` discovery source; otherwise honestly `None`.

The composite grade rides on `CandidateInput.materiality_grade` and is what every gate check
reads via `_effective_grade` (`publication_gate.py:278`) — the naked-float
`publication_gate.materiality_grade` survives only as the fallback for callers that computed
no composite. `_check_materiality_valid` rejects `UNKNOWN` and (absent explicit owner policy)
`LOW`; `_primary_authorized` refuses `LOW` and requires `HIGH` at d2.

`shock_magnitude_known` is accepted and **deliberately unused** — no producer of a real
event-magnitude verdict exists, and inventing one would be the naked-float sin this module
exists to prevent.

---

## 8. Market / fundamental separation proof

- **The gate cannot see market data.** `CandidateInput` (`publication_gate.py:161`) has no
  price/return/move/measurement field; the module's only import is `app.config`.
  `test_inv002_gate_input_has_no_market_fields` enforces this structurally.
- **Materiality**: `materiality_grade`'s four parameters are float, exposure ordinal,
  evidence tier, bool — no market input (`materiality.py:33`).
- **Economic effect**: every write to `economic_effect` in `backend/app` originates in
  `engine.py` (merge/archetype/correction) or `schemas.py` (`normalize_effect` /
  `direction_to_effect`) — grep confirms **no** assignment from any market/measurement
  module.
- **Magnitude**: `_build_alert_company` uses the analysis's own values;
  `get_calibrated_magnitude` is uncalled.
- **Confidence**: `compute_confidence` has no market parameter.
- **Reconciliation**: `measure_and_reconcile_alert_companies` returns immediately in strict
  mode (`pipeline.py:552`), leaving `direction` and prose untouched; the measured move lives
  only on the `MarketMove` row.
- **Evidence**: market-observation phrasing is classified `MARKET_OBS` and can never
  authorize (`evidence.py:143`, `publication_gate.py:404`).
- Pinned by `tests/test_price_fundamental_decoupling.py` (171), the INV-001/002/003 tests,
  and `test_audit_bypasses.py::test_bypass_price_confidence_floor` /
  `::test_bypass_price_calibration` / `::test_bypass_market_observation_paraphrase`.

---

## 9. Section proof

- Membership comes from the gate tier only (`_strict_sections`, `ripple_layers.py:184-188`).
- Direction comes from `economic_effect` (`_effect`, line 192), falling back to `direction`
  only when `economic_effect` is NULL.
- Titles are `f"{_EFFECT_PREFIX[effect]} — {label}"` where `label` comes from
  `_SECTOR_LABELS` / `"linked to <company name>"` / `_TAXONOMY_LABELS`, with `OTHER_LABEL`
  ("other verified mechanisms") for anything unknown (`_label_for`, line 208). No LLM string
  reaches a title.
- Grouping key includes the effect (`line 227-232`) and post-merge key is `(effect, label)`
  (`line 240-243`), so incompatible effects can never share a section, and two distinct
  unknown parents that both fall back to `OTHER_LABEL` merge into one section rather than
  rendering duplicate titles.
- `test_all_42_mechanisms_have_labels` pins full taxonomy coverage;
  `tests/test_sections_structural.py` (327 lines) pins structurality.

---

## 10. Cache / version proof

- v3 result cache key is
  `v3:{POLICY_VERSION}:{IMPACT_PROMPT_VERSION}:{IMPACT_SCHEMA_VERSION}:{KNOWLEDGE_REGISTRY_VERSION}:{strict_flag}:{content_hash}`
  (`pipeline._v3_cache_key:133-151`) — five version components plus the strict-mode flag, so
  a v4-strict run can never replay a legacy-gated result and every registry/policy bump is an
  explicit miss. Rows under the old two-part `v3:<hash>` scheme simply never match (zero-code
  invalidation). `POLICY_VERSION = "pol-1"` is bumped whenever gate logic could flip a cached
  outcome (`publication_gate.py:55`).
- `IMPACT_PROMPT_VERSION = "kg-6"` (`prompts.py:16`), `IMPACT_SCHEMA_VERSION = "kg-1"`
  (`schemas.py:21`); the pair is stamped on every `CompanyDecisionRecord.analysis_version`.
- Dedup reuse requires **every** decision record's `analysis_version` to equal the current
  pair, plus non-NULL `gate_state` on every row, plus prior `analysis_quality ==
  "authoritative"` (`pipeline.py:295-326`). Any failure falls through to a fresh analysis,
  never a partial copy.
- Stage-cache fingerprint carries the same version triple (`tests/test_stage_cache.py` +39).

---

## 11. Fallback proof

- `_gate_quality` (`pipeline.py:1335`) maps `budget_exhausted → degraded` and rounds any
  unrecognized value **down** to `failed`.
- `_check_quality_valid` (`publication_gate.py:447`) rejects `failed`/unrecognized with
  `REJECT_VALIDATOR_UNAVAILABLE`.
- `_primary_authorized` (`publication_gate.py:540-543`): `degraded` can never be primary;
  `fallback` can only be primary when the owner explicitly sets
  `IMPACT_ALLOW_FALLBACK_PRIMARY=true` (default false, `config.py:279`).
- Budget exhaustion additionally sets `verification_available=False`
  (`pipeline.py:1232-1235`), and `_check_verified` checks availability **first,
  unconditionally** — a stale `independently_verified=True` default cannot short-circuit it
  (`publication_gate.py:466-469`).
- Pinned by `tests/test_fallback_quality.py` (268) and
  `test_audit_bypasses.py::test_bypass_narrow_budget`.

---

## 12. Test results (exact)

- Backend full suite: **2043 passed, 2 skipped**, 7 warnings, **82.53s**, exit 0.
- Invariants `tests/test_v4_invariants.py`: **47 tests**, all pass (INV-001…INV-020 index).
- Bypass pins `tests/test_audit_bypasses.py`: **26 tests**, all pass.
- Frontend: `tsc --noEmit` clean; **113 test files, 757 passed, 4 skipped** (761), 13.57s.

## 13. Regression results

`tools/run_offline_suite.py` — **6/6 PASS**, exit 0:

| step | result | duration |
|---|---|---|
| schema (`alembic upgrade head` on throwaway DB + ORM-vs-migrated comparison) | PASS | 1.3s |
| unit (full pytest) | PASS | 83.5s |
| invariants | PASS | 7.7s |
| bypasses | PASS | 7.5s |
| regression (labeled corpus) | PASS | 64.1s |
| audit_report (seeded throwaway alert) | PASS | 1.4s |

Safety of the runner is structural, not conventional: every subprocess gets `DATABASE_URL`
pointed into a temp dir, and `IMPACT_ENGINE_V4_STRICT` is **popped** from the child env
(`run_offline_suite.py:63`) so an operator's shell cannot change what the suite measures.

## 14. Offline benchmark results

`tools/offline_benchmark.py` over `benchmarks/regression_events/` — **23 fixtures**, exit 0:

| metric | value | hits/total |
|---|---|---|
| company_precision | 100.0% | 43/43 |
| company_recall | 100.0% | 33/33 |
| false_positive_rate | 0.0% | 0/59 |
| primary_feed_precision | 100.0% | 33/33 |
| fundamental_direction_accuracy | 100.0% | 33/33 |
| mixed_accuracy | 100.0% | 5/5 |
| mechanism_accuracy | 100.0% | 6/6 |
| causal_distance_accuracy | 100.0% | 36/36 |
| materiality_accuracy | 100.0% | 9/9 |
| section_accuracy | 100.0% | 26/26 |
| abstention_precision | 100.0% | 3/3 |
| entity_accuracy | 100.0% | 23/23 |
| evidence_accuracy | 100.0% | 30/30 |
| rejection_recall | 100.0% | 19/19 |
| explanation_faithfulness | 100.0% | 86/86 |
| market_measurement_accuracy | N/A | 0/0 |

**What these numbers are not.** Every stage response is replayed from the fixture's own
`router_responses` block, and the fixtures were hand-authored alongside the gate. They
measure that the deterministic layers (gate, evidence classifier, materiality composite,
section builder, explanation validator) behave exactly as labeled on inputs designed to be
decidable. They are **not** evidence about live model output on real news, and
`market_measurement_accuracy` has a zero denominator (measurement is stubbed offline).
Release-gate item 4 is therefore **not** satisfied by this table (§18).

## 15. Token / cost impact

**No live telemetry exists, by design.** Spec §1 forbids spending paid tokens to validate
code and §60 mandates fixture replay / mocked calls; every measurement in this report comes
from replayed fixtures, so there is no token or rupee figure to report honestly. What can be
stated:

- Prompt surface grew: `IMPACT_PROMPT_VERSION` moved `kg-3 → kg-6` over this plan. The
  qualitative drivers are the added per-stage invention-prohibition lines in
  `NARROW_COMPANIES_PROMPT`, `ESCALATION_PROMPT` and `VERIFY_COMPANIES_PROMPT` (spec §46),
  the counterfactual field in the verify schema, and the path/ancestry lines in the verifier
  listing. Each is a small constant addition per call, not a new call.
- Call-count changes that reduce spend: gated alerts no longer pay for the legacy
  `generate_ripple_layers` LLM call at all (`refinement.py:857`), and the redundant second
  `_subject_companies_ex` pass per article was removed (`pipeline.py:1202`).
- Call-count changes that increase spend: none structurally — verification was always a
  stage; the deleted exposure auto-accept means more candidates now reach the verifier in
  the same single batched call rather than skipping it.
- Cost/version safety is enforced instead of measured: the version-pinned cache
  (`_v3_cache_key`) and the reuse policy prevent a policy bump from silently replaying old
  decisions.

**A real cost delta requires the canary (§19). Release-gate item 11 is unmet.**

## 16. Latency impact

Also offline-only. Observed harness timings on this machine:

- Full backend suite: 82.53s for 2045 tests.
- Labeled-corpus regression: 64.1s for 23 fixtures end-to-end through engine → gate →
  persistence → sections (**~2.8s per fixture**, dominated by per-fixture in-memory DB
  creation and seeding, with zero model latency).
- Invariants 7.7s, bypasses 7.5s, schema 1.3s, audit report 1.4s.

Per-article production latency is **not** measured: model latency dominates it and no model
was called. The deterministic additions (gate walk, evidence classification, materiality
composite, section assembly) are pure in-process work over ≤ tens of candidates plus a
handful of indexed queries per candidate; the one measured pipeline-shaped cost is the
`_gate_candidates` per-candidate DB lookups (`Company`, `CompanyNodeExposure`,
`SupplyLink`, `CompanyExposure`).

## 17. Unresolved risks (complete ledger sweep — nothing dropped)

### Parked items
1. **REJECT_DUPLICATE / REJECT_TOO_DISTANT are engine-unreachable today** (T4 park, restated
   as T21 INFO). `finalize_alert_decisions` dedups on resolved `company_id`, but the engine
   keys `state.companies` by ticker with an effective ticker↔company bijection, so no real
   duplicate arises. The vocabulary is forward preparation; the states are only exercised by
   tests.
2. **`GraphCompany.entity_ambiguous` has no production setter** (T7/T8 park). Ambiguous
   subjects are dropped pre-candidate in `_subject_companies_ex`; the ambiguity is recorded
   only via the `ambiguous_entities` decision records written in `_persist_alert`.
3. **Archetype path can never produce a PRIMARY by construction** (T21 INFO; owner
   acknowledgement wanted). `CURATED_ARCHETYPE` classifies Tier D, and D is capped at
   deep dive. Every archetype-discovered company is therefore secondary at best unless some
   other evidence class rescues it.

### Deferred minors
4. T1: freeze comment paraphrases the quoted string; the legacy-stamp test cannot detect
   schema drift (brief-specified design).
5. T2: `knowledge.py::_EFFECT_INVERSE` retains a dead `"neutral"` key; stale vacuous
   assertion in `test_registry_referential_integrity`.
6. T3: `AlertCompany.confidence` enum value `"calibrated"` is now dead;
   `_build_alert_company(category=...)` is accepted-and-unused.
7. T4: nothing emits tier A/B yet (no producer of structured primary evidence);
   `decision_notes` lives inside `candidate_json` rather than its own column; the benchmark's
   `by_ticker` map is last-write-wins on a hypothetical duplicate.
8. T5: no test pins that `persist_evidence` ids reach `CompanyDecisionRecord.candidate_json`
   through the real `_persist_alert` path (verified by probe only); `ARTICLE_SUBJECT`
   `source_name` is the literal `"article"` and could carry the real `Article.source`.
9. T6: a **stale** provenanced exposure row falls through to `MODEL_INFERENCE` rather than a
   D-prior (real behavior, tested and documented); **nothing currently writes
   SUPPLY_LINK/MANUAL/CURATED provenance onto exposure rows** — that escape is forward
   provisioning, so Tier C is effectively SupplyLink-only in practice; Postgres tz-coercion
   of `review_after` is unexercised.
10. T7/T8: tier-E candidates are intercepted by `MATERIALITY_VALID` before `EVIDENCE_VALID`
    (first-failing-gate semantics; the rejection reason names materiality, not evidence);
    `REJECT_UNKNOWN_COMPANY` decisions for row-less tickers were historically skipped
    pre-T18.
11. T9: legacy `analysis/verification.py` still has omission-is-kept semantics (dead cascade
    path, unwired); the task report's Tier-E cap coverage wording is imprecise.
12. T13: substring percent-grounding can be fooled (`"20"` grounded by `"2024"`); the
    fail-open `except` is broader than DB-only; the report said 21 tests where the file has
    17; the percent-grounding branch is redundant with `validate_or_none` at every wired
    call site (kept deliberately as defence in depth).
13. T14: `FeedRowV2` flat/unknown branch untested; **legacy flag-off per-company direction
    reconciliation is still raw-sign** (intentional pinned legacy path — strict path immune);
    **the NSE 2026 Jan-15 election-closure holiday was dropped pending owner verification**
    and the 2026 calendar is otherwise unverified against an authoritative source.
14. T12: `_dedup_reuse_policy_allows` keys on `gate_state` only, inconsistent with the
    canonical `is_gated` OR; a hypothetical mixed gated/ungated alert would lose `.why` for
    its ungated rows; copied `EvidenceRecord.created_at` is fresh, not verbatim; the
    `relationship` value is now `MECH:{label}` (no known consumer parses it).
15. T15: `_cache_get` legacy-raw-row comment is misleading (that branch is dead code); the
    `call_summary` telemetry line is missing on the plain non-protected `_call_groq` route.
16. T16: **the per-row `materiality_grade` serialized to the UI is the naked-float grade and
    can diverge from the composite grade that actually authorized the tier** (documented
    tradeoff; the composite is not persisted on `AlertCompany`); unmeasured-primary +
    measured-secondary combination untested; `impact_type is None` branch untested.
17. T17: `rowEffectSign` is duplicated in `chartsData` (import-cycle avoidance); the
    `CKnowledge` "Exposure" label was not updated for its broadened bucket.
18. T18: `CompanyDecisionRecord.model` is a best-effort provider→model mapping;
    frontier-vs-`sector_pool` discovery labeling is interpretive.
19. T20: the self-report's "random ordering" claim is unsubstantiated (no `pytest-randomly`
    installed).
20. T21: **`normalize_node_id` silently drops direction-worded `parent_id`s** (log-only, LOW);
    `_persist_alert` contains a non-obvious live yfinance snapshot call
    (`get_or_fetch_financial_snapshot`, stubbed in the harness — a real network call in
    production); a corpus fixture exercising a curated-provenance Tier-C primary is now
    possible and worth adding; the SQLite naive-UTC comparison footgun was noted twice.

### Spec-level partial implementations
21. **§8 FACT / DERIVED / INFERENCE / UNKNOWN is only partially implemented.** What exists is
    `EvidenceRecord.fact_text` vs `supports_claim` typing plus the closed-world explanation
    validator. Full statement-level epistemic tagging of every generated sentence is
    **deferred** and was flagged as partial at plan time.
22. **Legacy (flag-off) behaviors remain live for ungated alerts**, because with the flag off
    that *is* production: LLM-authored `AlertRippleLayer` section titles, the 3-tier ripple
    generator, price-sign direction reconciliation, and the "every measured company is
    headline-eligible" rule all still run for alerts with no gate output. They are
    structurally unreachable for gated rows, but they are the current production path.
23. **Tier A/B evidence has no producer**, so in practice the strongest reachable evidence is
    C (SupplyLink) or SUBJECT. `_check_business_model_valid`'s A/B escape for a
    profile-less company is therefore currently unreachable.

## 18. Why live mode remains disabled — spec §63 release-gate status

`IMPACT_ENGINE_V4_STRICT` is **absent from every environment/deploy artifact** in the repo
(`Dockerfile`, `.dockerignore`, `.railwayignore`, `.github/`, `backend/.env` — checked; no
`railway.json/toml`, `nixpacks`, `Procfile` or `docker-compose` exists). The config default
is `false` (`config.py:270`). No scheduler wiring was added for the new engine. No tool or
test opens the production DB (`newsflo.db` appears only in `config.py`'s default
`DATABASE_URL` and in the two tools' safety comments). The benchmark tools import no
network library and stub every side effect.

| # | gate item | status |
|---|---|---|
| 1 | all safety invariants pass | **MET** — 47 invariant tests green |
| 2 | no known publication bypass exists | **MET for the audited list** — 26 bypass pins green; "known" is bounded by the audit (§Self-audit) |
| 3 | legacy semantic paths cannot affect current production output | **CONDITIONAL** — structurally guaranteed for gated data (`is_gated`, flag-independent), but with the flag off *all* current production output is the legacy path (risk 22). Only observable after the canary |
| 4 | primary-feed FP target met on a real labeled/offline corpus | **NOT MET** — 23 hand-authored replay fixtures, not real news through real models |
| 5 | evidence policy works | **MET offline** — evidence_accuracy 30/30, `test_evidence_records.py`, `test_exposure_self_certification.py` |
| 6 | abstention works | **MET offline** — abstention_precision 3/3, rejection_recall 19/19 |
| 7 | fallback/degraded policy works | **MET offline** — `test_fallback_quality.py` (268 lines) |
| 8 | market/fundamental separation proven | **MET offline** — §8 above + `test_price_fundamental_decoupling.py` |
| 9 | section correctness proven | **MET offline** — section_accuracy 26/26, `test_sections_structural.py` |
| 10 | cache/version safety proven | **MET offline** — §10 above + `test_stage_cache.py` |
| 11 | cost/latency acceptable | **NOT MET** — no live telemetry exists (§15/§16) |
| 12 | professional / human review sample passes | **NOT MET** — the harness writes reviewer artifacts to `benchmarks/out/reviews` with the §59 label vocabulary, but **no human has filled any in** |
| 13 | owner explicitly authorizes a canary | **NOT MET** — not requested, not given |

**Four items (4, 11, 12, 13) are unmet and one (3) is unverifiable pre-canary. Live mode
therefore stays OFF.** This task stops before live enablement, per spec §63.

## 19. Exact future canary procedure (NOT executed)

Commands below are written for the owner. **None of them has been run.**

**Preconditions:** items 4, 11, 12, 13 of §18 addressed — specifically (a) a labeled corpus
built from real ingested articles with real model responses, (b) at least one filled-in
human review sample from `benchmarks/out/reviews`, (c) explicit owner authorization.

1. **Back up the target database first.**
   ```
   railway ssh --service <service>
   pg_dump "$DATABASE_URL" -n public -f /tmp/pre-v4-$(date +%Y%m%d).sql
   ```
2. **Apply migrations** (schema-only; every data migration is inspector-guarded and additive,
   so this is safe with the flag still off):
   ```
   railway ssh --service <service>
   cd backend && python -m alembic upgrade head
   ```
   Then confirm: `python -m alembic current` shows `0006`.
3. **Enable strict mode on exactly ONE service**, never the whole project:
   ```
   railway variables --service <canary-service> --set IMPACT_ENGINE_V4_STRICT=true
   ```
   Leave `IMPACT_ALLOW_FALLBACK_PRIMARY` and `IMPACT_ALLOW_LOW_MATERIALITY_DEEP_DIVE`
   **unset** (both default false). Consider lowering `IMPACT_MAX_PRIMARY_COMPANIES` from 10
   for the first day.
4. **Optionally enable the read-only audit surface** for the canary window:
   `railway variables --service <canary-service> --set DEBUG_AUDIT_API=true`
   (`GET /api/internal/audit/decisions/{alert_id}`), then unset it afterwards.
5. **Monitor, for a minimum of one full trading day:**
   - `CompanyDecisionRecord` volume and the `final_state` histogram — a collapse to
     near-all-`REJECT_*` means the gate is starving the feed; a sudden all-`DISPLAY_ELIGIBLE`
     means a check is inert.
   - `display_tier` distribution: primaries per alert vs `impact_max_primary_companies`, and
     how many carry `decision_notes = primary_cap_overflow`.
   - `rejection_reason` breakdown, watching especially for `REJECT_VALIDATOR_UNAVAILABLE`
     (verifier outages / budget exhaustion) and `REJECT_INSUFFICIENT_EVIDENCE`.
   - `evidence_class` distribution — if `MODEL_INFERENCE` dominates, nothing is publishable;
     if `VERIFIED_RELATIONSHIP` appears without a SupplyLink behind it, investigate.
   - `analysis_quality` on alerts and `provider`/`model` on decision records (fallback rate).
   - Token spend per article vs the pre-canary baseline for the same service.
   - Feed emptiness: alerts served vs alerts analyzed (`_strict_displayable` requires ≥1
     primary).
   - Section titles observed in the UI — any raw node id appearing is an immediate stop.
6. **Rollback triggers (any one, immediately):** a raw node id or LLM-authored string in a
   section title; a company published whose `evidence_class` is `MODEL_INFERENCE` or
   `ARTICLE_MARKET_OBSERVATION`; primary-feed precision on spot-checked alerts below the
   agreed target; served-alert count falling below the agreed floor for two consecutive
   ingestion cycles; token spend exceeding the agreed cap; any unhandled exception traced to
   `_gate_candidates` / `_strict_sections`.

## 20. Rollback procedure

1. **Flag off (instant, no deploy):**
   ```
   railway variables --service <canary-service> --set IMPACT_ENGINE_V4_STRICT=false
   railway variables --service <canary-service> --set DEBUG_AUDIT_API=false
   ```
   New alerts immediately stop being gated. **Note the asymmetry, by design:** alerts already
   persisted with gate output keep rendering through the strict section path and the
   PRIMARY-only headline rule, because `is_gated` / `_strict_displayable` are structural and
   do not read the flag. If those rows must also revert, they have to be deleted or their
   `gate_state`/`display_tier` nulled — do that only with an explicit, reviewed data script;
   there is none today.
2. **Schema rollback (only if required — the columns are additive and harmless):**
   ```
   railway ssh --service <service>
   cd backend && python -m alembic downgrade 0001
   ```
   `0006`'s downgrade drops the `UNIQUE(alert_id, company_id)` constraint and the two
   indexes; it **cannot** restore duplicate `alert_companies` rows or child rows its
   pre-dedupe deleted. Restore from the step-1 `pg_dump` if that data matters.
3. **Code rollback:**
   ```
   git revert --no-commit c37999b..abcc864
   git checkout c37999b -- backend/app backend/tools backend/alembic frontend/src
   ```
   Prefer a `git revert` of the range over a hard reset; the range contains five foreign
   commits (`b7773c0`, `4de9e13`, `6d82124`, `cebb3fe`, `ea9772d`) that must be preserved —
   revert them back in individually, or exclude them from the revert range and revert the
   corrective-V4 commits explicitly.

---

## Self-audit — spec §64, all 20 questions

Every answer below was re-derived by reading the current tree, not by consulting earlier
task reports. **All 20 answers are the safe answer (NO).** Qualifications are stated
precisely where the guarantee is structural-for-gated-data rather than absolute.

| # | question | answer | proof |
|---|---|---|---|
| 1 | Can a nonexistent ticker persist? | **NO** | `publication_gate._check_entity_valid:318` rejects `entity_status != "resolved"` → `REJECT_UNKNOWN_COMPANY`; `entity_status` is computed from a real `Company` row lookup (`pipeline.py:1240,1251-1255`). Independently of the gate, `pipeline._v3_entries:1374` `if row is None: … continue` means no `AlertCompany` is ever built for an unresolved ticker (flag-on and flag-off). The ticker is still recorded as a rejected decision record (`pipeline.py:1386-1405`). |
| 2 | Can a real but wrong company reach PRIMARY? | **NO** *(bounded — see qualification)* | Every audited mechanism is closed: generic sector prose at tier D/E → `_check_company_specific_exposure_valid:359`; no business profile without A/B evidence → `_check_business_model_valid:342`; a claim not rooted in this event's shock → `_check_event_applicability_valid:368` (`_roots_in_event`, `pipeline.py:1132`); `NOT_SUPPORTED` counterfactual → `_check_counterfactual_valid:432`; unverified or unverifiable → `_check_verified:456`; d2 requires a relationship record + HIGH grade (`_primary_authorized:544-550`). **Qualification:** these are structural checks on *how* a claim is supported, not a semantic proof of correctness. A company that is real, verified, article-central and materially exposed but wrong on the economics can still reach primary; the offline corpus (23 labeled fixtures, primary_feed_precision 33/33) bounds this only on replayed inputs, which is exactly why release-gate item 4 is unmet. |
| 3 | Can MODEL_INFERENCE reach PRIMARY? | **NO** | `MODEL_INFERENCE → tier "E"` (`evidence.py:235`, `publication_gate.EVIDENCE_CLASS_TO_TIER:95`); `E ∈ NON_AUTHORIZING_TIERS:84`; `_check_evidence_valid:412` rejects it outright with `REJECT_INSUFFICIENT_EVIDENCE` — it never reaches tier grading at all. Belt and braces: `materiality.materiality_grade:72` caps tier E at LOW, and `_primary_authorized:537` refuses LOW. |
| 4 | Can market move affect company existence? | **NO** | `CandidateInput` (`publication_gate.py:161-199`) declares no market field; the module imports only `app.config`. `pipeline._gate_candidates:1270-1302` constructs it from graph/DB/evidence values only. Persistence authority for gated rows is the gate alone — `CONFIDENCE_FLOOR` is applied only when `"gate_state" not in entry`, and `compute_confidence` (`reasoning/confidence.py:80-87`) takes no price input. Enforced by `test_inv002_gate_input_has_no_market_fields`. |
| 5 | Can market move affect economic_effect? | **NO** *(qualified on the legacy `direction` column)* | Grep of all `economic_effect =` assignments in `backend/app` shows every write originating in `engine.py` (merge/archetype/correction) or `schemas.py` (`normalize_effect`/`direction_to_effect`) — none from a market module; `_persist_effect` (`pipeline.py:213`) only normalizes. `_strict_sections._effect` (`ripple_layers.py:192`) reads `economic_effect` first. **Qualification:** the *legacy* `AlertCompany.direction` column is still overwritten from the measured move when the flag is off (`pipeline.py:554-569`), and `measure_and_reconcile_alert_companies` guards that with a settings check (`:552`), not a structural one — so a gated alert re-run through `reanalyze_cascade.py` with the flag off could have its `direction` (never its `economic_effect`) overwritten. Listed in §17 risk 13/22. |
| 6 | Can market move affect materiality? | **NO** | `materiality.materiality_grade:33` accepts only `(llm_materiality, exposure_level, evidence_tier, shock_magnitude_known)`; its caller `pipeline.py:1260-1269` supplies the LLM float, a `CompanyExposure` ordinal, the evidence tier, and a literal `False`. No market value is reachable. |
| 7 | Can realized-price calibration change fundamental magnitude? | **NO** | `app.calibration.blender.get_calibrated_magnitude` has **zero call sites** in `backend/app` (grep returns only its own definition and doc comments). `_build_alert_company:395` sets `magnitude_low, magnitude_high = entry[...]` unconditionally; `_v3_entries:1419-1420` derives them monotonically from `impact_strength`. Pinned by `test_audit_bypasses.py::test_bypass_price_calibration`. |
| 8 | Can prior LLM acceptance self-certify future evidence? | **NO** | `_verify_companies` (`engine.py:1014-1029`) no longer has a cache-based auto-accept — every candidate faces this event's verifier. `_write_exposure_cache` stamps `provenance_type=MODEL_VERIFIED` (`engine.py:1141-1143`), which `classify_evidence` grades **D**, never C (`evidence.py:216-219`); only `SUPPLY_LINK/MANUAL/CURATED` reach C (`evidence.py:57,191`). Same-run rows are skipped entirely via `fresh_cache_tickers` (`evidence.py:216`, `engine.py:1126-1128`). Priors also expire (`review_after`, `exposure_row_is_fresh`). |
| 9 | Can verifier bypass deterministic checks? | **NO** | The verifier's output enters the gate only as data: `independently_verified` (`engine.py:1085`), `counterfactual` (`:1099-1105`) and field corrections (`:1079-1083`). `evaluate_candidate:494` does nothing but walk `GATE_SEQUENCE:473` — there is no branch, override or short-circuit reachable from model output, and `_display_tier:556` runs only after every check passed, so it can never resurrect a rejection. Counterfactual verdicts are enum-validated and dropped when unrecognized. |
| 10 | Can budget exhaustion pass an unverified company? | **NO** | `pipeline.py:1232-1236`: `budget_exhausted` → `verification_available=False` **and** `_gate_quality:1341` maps it to `degraded`. `_check_verified:466` tests availability **first, unconditionally** — a leftover `independently_verified=True` cannot short-circuit it — yielding `REJECT_VALIDATOR_UNAVAILABLE`. The narrow path sets `verification_unavailable` + `quality="budget_exhausted"` on hard overrun (`engine.py:1601-1615`), the broad path likewise (`:1715-1721`). Pinned by `test_bypass_narrow_budget`. |
| 11 | Can dedup reuse bypass current policy? | **NO** | `_dedup_reuse_policy_allows` (`pipeline.py:295-326`) requires: every prior `AlertCompany.gate_state` non-NULL; prior `analysis_quality == "authoritative"`; at least one `CompanyDecisionRecord`; and **every** record's `analysis_version` equal to the current `kg-6/kg-1` pair. `_find_reusable_alert:355` treats a failing match as no match. Reuse **copies** the prior decision + evidence records rather than synthesizing empty ones (`_copy_gate_audit_trail:656`). Pinned by `test_bypass_dedup_reuse`. |
| 12 | Can an LLM invent a section title? | **NO for gated alerts** *(legacy path survives for ungated ones)* | `_strict_sections` builds titles as `f"{_EFFECT_PREFIX[effect]} — {label}"` where `label` comes only from `_SECTOR_LABELS` / `"linked to <name>"` / `_TAXONOMY_LABELS`, defaulting to the constant `OTHER_LABEL` (`ripple_layers.py:208-216,262`). `refinement.py:800,857` skips the `generate_ripple_layers` LLM call entirely when `is_gated`, so no LLM title is even produced. **Qualification:** for alerts with no gate output, `compute_ripple_layers` still reads LLM-authored `AlertRippleLayer` rows (`ripple_layers.py:494-500`) — structurally unreachable for gated data (`:481`), but live today because the flag is off. |
| 13 | Can internal node IDs reach the UI? | **NO** *(one qualification)* | Unknown `causal_parent_id`s resolve to `OTHER_LABEL`, never the raw id (`_label_for:216`); `relationship` is `f"MECH:{label}"` (`:263`), also label-derived. Grep of `frontend/src` for `causal_parent_id` / `parent_id` returns **no matches** — the field is not serialized to any v4 surface. **Qualification:** the `causal_parent_type == "company"` branch renders `f"linked to {parent_name or parent_id}"` (`:213-215`), where the fallback `parent_id` is a **ticker** (a real, user-meaningful identifier), not an internal node id. |
| 14 | Can legacy section generation be reached in the current new path? | **NO** | `compute_ripple_layers:481` — `if alert_is_gated: return _strict_sections(alert, rows_flat, include_secondary) or []`. The guard reads `is_gated` (`publication_gate.py:126`, an OR over `gate_state`/`display_tier`) and deliberately **not** `settings.impact_engine_v4_strict`, so flipping the flag back off cannot resurrect the legacy renderer for gated rows. `_strict_sections` returning `None` yields `[]`, never a fall-through. Pinned by `test_bypass_legacy_section_resurrection` and `tests/test_sections_structural.py`. |
| 15 | Can fallback/degraded output publish as authoritative? | **NO** *(one owner-controlled override exists)* | `_check_quality_valid:447` rejects `failed` and anything unrecognized; `_gate_quality:1335` rounds unknown values **down** to `failed`. `_primary_authorized:541` refuses `degraded` outright. **Qualification:** `fallback` can become primary if the owner sets `IMPACT_ALLOW_FALLBACK_PRIMARY=true` — default `false` (`config.py:279`), absent from every deploy artifact, and an explicit recorded owner decision by design. |
| 16 | Can fabricated evidence become authoritative? | **NO** | `EvidenceRecord` payloads are produced only by `classify_evidence` from real DB artifacts — a `SupplyLink` row's own `source_agency`/`source_url`/verbatim `evidence` (`evidence.py:164-178`), a provenanced `CompanyNodeExposure` row (`:198-207`), or the article's own subject list (`:222-229`). No LLM-authored string becomes an evidence record. The LLM's free-text `evidence_refs` cannot raise confidence — only rulebook-resolved `matched_rule_ids` count (`pipeline.py:400,426`). Generated prose is closed-world validated against the alert facts (`refinement.validate_closed_world:642`). Pinned by `test_bypass_subject_fallback_fabrication` and `tests/test_explanation_validation.py`. |
| 17 | Can LOW/UNKNOWN materiality enter PRIMARY? | **NO** | `_check_materiality_valid:396-400` rejects `UNKNOWN` outright and rejects `LOW` unless the owner opted into low-materiality deep dives; even then `_primary_authorized:537` returns False for `LOW`. Both read `_effective_grade:278` — the composite grade, not the naked float. |
| 18 | Can d3+ enter PRIMARY? | **NO** | `_primary_authorized:544` — `if candidate.causal_distance >= 3: return False`. Upstream, `_check_causal_path_valid:381-386` rejects d4+ outright (`REJECT_TOO_DISTANT`, no policy override) and demotes d3 to `REJECT_LOW_PRIORITY` unless tier ∈ {A,B,C} **and** grade HIGH. |
| 19 | Can incompatible effects share a primary section? | **NO** | The pass-1 grouping key is `(effect, causal_parent_type, causal_parent_id)` (`ripple_layers.py:227-232`) and the pass-2 merge key is `(effect, label)` (`:240-243`). Effect is a component of both, so two different effects can never land in one section; the title itself is prefixed by the effect (`:262`). |
| 20 | Can a secondary/rejected company become the headline? | **NO for gated alerts** *(legacy behavior for ungated ones)* | `feed_v2.py:216` — `company_ids = _primary_company_ids(alert) if is_gated(alert.companies) else None`, and `_primary_company_ids:124` returns only `display_tier == "primary"` ids, which is what `compute_alert_measurement` uses for peak/verdict/intensity/breadth. `_strict_displayable:144` requires ≥1 primary before the unavailable-measurement placeholder is served. Excluded candidates never become `AlertCompany` rows at all. **Qualification:** an ungated legacy alert still passes `None` (every measured company eligible) — unchanged pre-existing behavior. Pinned by `test_bypass_headline_ignores_tier` and `tests/test_feed_primary_only.py`. |

**No unsafe YES was found.** The historic bypass list from the audit — dedup reuse, narrow
budget, self-echo, price→confidence, price→calibration, legacy section resurrection,
headline tier, fallback-as-authoritative, LOW/UNKNOWN primary, d3+ primary, invented
tickers, MODEL_INFERENCE primary, LLM section titles, node-ids-in-UI, incompatible-effect
sections, secondary headline, fabricated evidence, and market→existence/effect/materiality —
is closed on the gated path and pinned by 26 regression tests in
`backend/tests/test_audit_bypasses.py`, with the qualifications above stated for every case
where the guarantee is structural-for-gated-data rather than absolute.

---

## Definition of done (spec §66) — honest status

| clause | status |
|---|---|
| An unsupported company has no reachable path into the PRIMARY feed | **Holds for gated data** on every audited path; correctness beyond the structural checks is bounded, not proven (Q2) |
| Market movement cannot change fundamental impact, eligibility, materiality, or magnitude | **Holds**; legacy `direction` reconciliation persists on the flag-off path (Q5) |
| Fallback/degraded output cannot become authoritative | **Holds**, subject to the explicit `IMPACT_ALLOW_FALLBACK_PRIMARY` owner switch (Q15) |
| Prior model acceptance cannot self-certify future evidence | **Holds** (Q8) |
| A free-form LLM cannot define section semantics | **Holds for gated data** (Q12/Q14) |
| Every PRIMARY company has an auditable causal/evidence/materiality chain | **Holds** — `CompanyDecisionRecord` + `EvidenceRecord` per candidate, incl. rejections |
| The system can abstain | **Holds** — abstention_precision 3/3, rejection_recall 19/19 offline |
| Live mode remains OFF until separately authorized | **Holds** — verified absent from every env/deploy artifact |
