# Final blueprint — §37 self-audit + final report

Plan: `docs/superpowers/plans/2026-08-14-final-blueprint.md`
Specs: `docs/specs/NEWSFLO_FINAL_SYSTEM_BLUEPRINT.md` +
`docs/specs/NEWSFLO_FINAL_CLAUDE_CODE_EXECUTION_PROMPT.txt`
Branch: `final-blueprint`, audited at `22f8ba1c` (12 task commits, 21 counting review-fix
rounds; plus five foreign UI commits from a concurrent session — see item 1).
Date: 2026-08-14. Author: Task 13 (SDD).

**Safety posture of this audit.** Read-only over the code; the only commands run were
`pytest` subsets, `tools/offline_benchmark.py` and `git`, all with `ENABLE_SCHEDULER=false`
(see risk 1). Zero live model calls, zero writes to `newsflo.db`, no push, no flag flipped.
`IMPACT_ENGINE_V4_STRICT` was never set anywhere: the whole V4 strict path audited below is
**dormant in this repository's runtime defaults** (`backend/app/config.py:318`).

**What this document does NOT claim.** Per blueprint §33: the offline benchmark being green
is **not** evidence of real-world accuracy. Every number below comes from a hand-authored,
replayed fixture corpus with canned model output. No labeled corpus of real ingested
articles with real model responses exists yet, so no accuracy claim about production is made
anywhere in this report — including where a metric reads 100%.

---

## Part A — §37 self-audit (20 questions)

Safe answer is **NO** for questions 1-19 and **YES** for question 20. Score: **19 NO + 1 YES
= 20/20 safe**, with three qualified answers (Q3, Q19, Q2) whose caveats are stated in full
below and carried into Part C's risk register. Nothing was forced to a YES.

| # | Question | Answer | Safe? |
|---|---|---|---|
| 1 | Oil India bearish on a bullish-only validated channel? | NO | ✅ |
| 2 | Direct company gets "indirect" semantics merely for being SECONDARY? | NO (1 caveat) | ✅ |
| 3 | Valid paint/tyre/cement ripple sectors disappear solely for not being PRIMARY? | NO in the engine; **YES on one UI surface** (owner-ruled) | ⚠️ documented |
| 4 | Weak ripple company enters SECONDARY without evidence/materiality? | NO | ✅ |
| 5 | Generic sector membership becomes a company result? | NO | ✅ |
| 6 | d3+ reaches PRIMARY? | NO | ✅ |
| 7 | Article stock mentions become fundamental evidence? | NO | ✅ |
| 8 | Market movement affects company existence or tier? | NO | ✅ |
| 9 | MODEL_INFERENCE reaches PRIMARY? | NO | ✅ |
| 10 | Self-certified relationships bypass verification? | NO | ✅ |
| 11 | A legacy section path affects a gated alert? | NO | ✅ |
| 12 | A raw node ID reaches the UI? | NO | ✅ |
| 13 | A non-demand mechanism is labeled DEMAND at the company edge? | NO | ✅ |
| 14 | Contradictory company-level fundamental states persist? | NO (SQLite backstop only) | ✅ / risk 2 |
| 15 | Stale workers mutate gated rows? | NO | ✅ |
| 16 | Two processes create duplicate alert results? | NO | ✅ |
| 17 | Incompatible cache versions / provider outputs mix? | NO | ✅ |
| 18 | HIGH confidence without appropriate evidence? | NO | ✅ |
| 19 | A secondary/rejected company becomes the headline? | NO for rejected and NO over a primary; **owner-ruled exception** when zero primaries exist | ⚠️ documented |
| 20 | Valid SECONDARY_RIPPLE sectors shown even when PRIMARY is empty? | **YES** | ✅ |

### 1. Can Oil India ever become bearish when its only validated channel is bullish? — **NO**

Four independent layers, any one of which alone stops the shape:

1. **Direction is derived, never carried.** On a gated row the persisted `direction` is
   `DIRECTION_FROM_EFFECT[economic_effect]` and the model's own `direction` is discarded
   (`backend/app/pipeline.py:1808-1818`; map at
   `backend/app/analysis/impact_graph/publication_gate.py:187-196`).
2. **The gate rejects effect/direction disagreement** — `_check_contradiction_free`
   (`publication_gate.py:653-661`) → `REJECT_CONTRADICTORY`.
3. **The §4 net-effect validator** blocks a company whose effect has zero same-side
   validated channels (`publication_gate.py:504-547`, escalated at
   `consistency.py:65-103`), run at persistence (`pipeline.py:1061-1067`, raising
   `ConsistencyError` → per-article `ANALYSIS_FAILED`) and again pre-serve
   (`app/routers/feed_v2.py:402`).
4. **A DB trigger** refuses the write even from a process that never imports this code
   (`backend/alembic/versions/0008_three_tier_blueprint.py:126-155`, mirrored in
   `backend/app/models.py`).

Tests: `tests/test_consistency_gate.py::test_oil_india_shape_is_blocked`,
`::test_direction_contradicting_the_effect_is_blocked`,
`tests/test_three_tier_policy.py::test_net_effect_validator_blocks_oil_india_shape`,
`::test_net_effect_validator_rejects_a_directional_claim_with_no_channel`,
`tests/test_gated_row_immutability.py::test_trigger_blocks_direction_contradiction_on_gated_row`,
`::test_trigger_blocks_negative_effect_turned_bullish`. Corpus fixture:
`benchmarks/regression_events/oil_india_direction_inconsistency.json` (§32 scenario 7).

### 2. Can direct companies incorrectly receive an "indirect" semantic merely because they are SECONDARY? — **NO**

Directness and publication tier are separate fields computed by separate functions.
`derive_directness` (`publication_gate.py:419-461`) resolves explicit classification →
knowledge-registry verdict for the mechanism → distance, and never reads the tier;
`_display_tier` (`publication_gate.py:845-862`) never reads directness. The wire carries both
independently (`causal_directness` + `publication_tier`) and the UI prints them as two
tokens (`frontend/src/v4/FeedV4.tsx:134-142, 365-373`).

Tests: `tests/test_three_tier_policy.py::test_directness_is_not_derived_from_distance_when_the_registry_knows`,
`::test_explicit_directness_outranks_the_registry`,
`::test_a_sector_or_company_parent_is_never_looked_up_as_a_mechanism`,
`tests/test_pipeline.py::test_registry_directness_survives_a_long_causal_distance`,
`tests/test_v4_feed_truth.py::test_explicit_causal_directness_column_wins_over_distance`,
`frontend/src/v4/FeedTruth.test.tsx` ("directness + tier row line"). Fixture pair pinning
both sides: `inr_it_multihop_macro_context` (DIRECT at d3) and
`coking_coal_infra_cost_macro_context` (REMOTE at d3).

**Caveat (risk 5).** A gated row with NULL `causal_distance`, no explicit directness and an
unknown parent falls back to `DIRECTNESS_UNKNOWN = "INDIRECT"`
(`publication_gate.py:170, 452-461`) — an *unknown* rendered as *indirect*. Parked at T2
review; the honest label would be a fourth value (`UNKNOWN`) or omission of the token.

### 3. Can valid paint/tyre/cement ripple sectors disappear solely because they are not PRIMARY? — **NO in the engine and section builder; YES on the card-back surface when the alert also has a primary (owner ruling, pre-existing)**

Engine/gate/sections: failing PRIMARY on evidence tier alone lands the candidate in
SECONDARY_RIPPLE (`_secondary_authorized`, `publication_gate.py:809-831`), and the generic
`SECONDARY — INDIRECT EXPOSURE` bucket is gone — ripple rows now group by the same controlled
taxonomy as primaries and render as `Secondary — <label>` sections
(`app/market/ripple_layers.py:352-540`, esp. 505-510). Pinned by
`tests/test_ripple_taxonomy_sections.py::test_two_secondary_parents_render_two_taxonomy_sections`,
`::test_generic_secondary_bucket_absent_repo_wide`,
`::test_secondary_sections_follow_all_primary_sections`, and by the three dedicated corpus
fixtures `paint_ripple_secondary`, `tyre_ripple_secondary`, `cement_ripple_secondary`
(§32 scenarios 8-10; `secondary_ripple_accuracy` 16/16 on the offline corpus).

**The honest exception.** The article card-back route passes
`include_secondary=(exposure != "primary")` (`app/routers/feed_v2.py:750-752`), so on an
alert that *does* have a primary company the RIPPLE and MACRO sections are withheld from
that surface; they are served only by `GET /api/feed-v2/{id}/deep-dive`
(`feed_v2.py:656`), which currently has **no frontend consumer** (risk 8). That is the
corrective-V4 owner decision ("/api/feed-v2 → PRIMARY only; secondary is a separate explicit
retrieval path"), carried forward deliberately by this plan (plan line 280), but it is in
tension with blueprint §29 ("Secondary ripple sections must remain visible on the article
page"). **Recommendation, owner decision required:** either flip the detail route to
`include_secondary=True` (one argument) or build the deep-dive consumer. Not changed here —
it reverses a standing owner ruling and is a product call, not a defect fix.

### 4. Can a weak ripple company enter SECONDARY without evidence/materiality? — **NO**

Every one of the 13 gates runs *before* tier grading (`evaluate_candidate`,
`publication_gate.py:726-772`), so a secondary row has already cleared entity validity,
mechanism quality, event specificity, distance policy, materiality, evidence, contradiction,
counterfactual, quality and independent verification. On top of that
`_secondary_authorized` requires a displayable effect, evidence tier ∈ {A,B,C,D,SUBJECT},
distance ≤ 2 and grade ∈ {HIGH, MEDIUM} — LOW only under an explicit owner flag
(`publication_gate.py:809-831`). Gates-passed-but-no-tier is recorded as
`REJECT_BELOW_SECONDARY_POLICY`, not published (`publication_gate.py:757-765`).

Tests: `tests/test_three_tier_policy.py::test_low_materiality_gates_reject_before_secondary`,
`::test_low_materiality_ripple_needs_explicit_owner_policy`,
`::test_gates_passed_but_below_secondary_policy_is_recorded_rejection`,
`tests/test_publication_gate.py::test_unknown_materiality_excluded`. Fixture:
`low_materiality_ripple_rejected` (§32 scenario 13, with a published control on the same
mechanism so the fixture cannot pass by rejecting everything).

### 5. Can generic sector membership become a company result? — **NO**

`_check_company_specific_exposure_valid` (`publication_gate.py:591-598`) rejects
interchangeable sector prose at tier D/E (`REJECT_GENERIC_EXPOSURE`);
`_check_business_model_valid` (574-580) refuses a claim about a company with no profile and
no exposure record unless the evidence is structured (A/B); `_check_event_applicability_valid`
(600-606) requires the causal path to root in *this* event's shock. Deterministic
sector fan-out rows are structurally confined to the SECTOR_WIDE bucket on the legacy path
(`ripple_layers.py:650-661`).

Tests: `tests/test_publication_gate.py::test_generic_sector_rationale_rejected_at_tier_e`,
`::test_generic_sector_rationale_rejected_at_tier_d`,
`::test_generic_rationale_tolerated_with_verified_relationship` (the negative control),
`::test_missing_trigger_shock_is_the_fail_closed_default`. Fixtures:
`semantic_similarity_false_positive`, `generic_macro_false_positive` (§32 scenarios 5, 12);
corpus `false_positive_rate` 0/92.

### 6. Can d3+ reach PRIMARY? — **NO**

Two independent bars: `_check_causal_path_valid` rejects d4+ outright and lets d3 through
only with relationship-grade evidence *and* HIGH materiality
(`publication_gate.py:609-619`); `_primary_authorized` then refuses any candidate with
`causal_distance >= 3` (`publication_gate.py:793`), so a surviving d3 can only land in
MACRO_CONTEXT (`_macro_context_authorized`, 833-843). d2 additionally needs HIGH grade
(line 804) and relationship-tier evidence (line 801).

Tests: `tests/test_publication_gate.py::test_distance_three_with_strong_evidence_is_macro_context`,
`::test_d3_without_strong_evidence_is_low_priority_reject`, `::test_distance_four_excluded`,
`tests/test_v4_invariants.py::test_inv013_causal_distance_policy_is_exact`,
`tests/test_three_tier_policy.py::test_d3_with_evidence_lands_macro_context`.

### 7. Can article stock mentions become fundamental evidence? — **NO**

Three separated semantics (§22): `discovery_source` (how we found the company —
`ARTICLE_MENTION` is one value, `pipeline.py:303-318`), `causal_directness`, and
`evidence_source` (`pipeline.py:321-...`). A rationale that argues from a price move is
classified `ARTICLE_MARKET_OBSERVATION` / tier `MARKET_OBS` *before any stronger class can
rescue it* (`app/analysis/impact_graph/evidence.py:46-55, 147-149`), and `MARKET_OBS` is in
`NON_AUTHORIZING_TIERS` → `REJECT_INSUFFICIENT_EVIDENCE`
(`publication_gate.py:128, 636-646`). Being the article's *subject* is separate and genuine
evidence, and even then it authorizes PRIMARY only at d1 (`publication_gate.py:801-803`).

Tests: `tests/test_v4_invariants.py::test_inv003_market_observation_is_never_fundamental_evidence`,
`tests/test_audit_bypasses.py::test_bypass_market_observation_paraphrase` (+ the
`_keeps_real_mechanisms` control), `tests/test_publication_gate.py::test_article_market_observation_never_authorizes`,
`::test_article_subject_is_d1_evidence_only_at_d3`. Fixture:
`mentioned_losers_not_fundamental_casualties` (§32 scenario 4).

### 8. Can market movement affect company existence or tier? — **NO**

The measurement path writes its own columns and skips any row carrying gate output —
structurally, not behind the flag (`pipeline.py:757-770` and the scheduler-driven
remeasure path `pipeline.py:855-870`). Reaction is classified into its own field
(`reaction_direction`, `ripple_layers.py:...`), the fundamental call stays on
`economic_effect`, and the divergence sentence states the disagreement rather than
resolving it. The gate never reads a price field: `CandidateInput`
(`publication_gate.py:250-306`) has no market member.

Tests: `tests/test_v4_invariants.py::test_inv001_measurement_never_overwrites_the_fundamental_call`,
`::test_inv001_gated_rows_survive_reconciliation_with_the_flag_OFF`,
`::test_inv002_fundamental_analysis_is_never_derived_from_price`,
`tests/test_audit_bypasses.py::test_bypass_price_confidence_floor`, `::test_bypass_price_calibration`,
`tests/test_price_fundamental_decoupling.py`,
`tests/test_feed_primary_only.py::test_new_fields_present_including_divergence_for_apollo_case`.
Fixture: `market_fundamental_divergence` (§32 scenario 20).

### 9. Can MODEL_INFERENCE reach PRIMARY? — **NO**

`classify_evidence` returns `MODEL_INFERENCE` / tier `E` as its terminal fall-through
(`evidence.py:240`); `E` is in `NON_AUTHORIZING_TIERS` so it is rejected at the gate, never
merely demoted (`publication_gate.py:128, 640-641`). Independently, `_primary_authorized`
admits only tiers A/B/C (or SUBJECT at d1) (`publication_gate.py:801-803`), so tier D
(`CURATED_ARCHETYPE`, `MODEL_VERIFIED_PRIOR`, `LEGACY_UNVERIFIED`) caps at SECONDARY_RIPPLE.

Tests: `tests/test_publication_gate.py::test_model_inference_alone_is_insufficient_evidence`,
`::test_curated_archetype_is_deep_dive_never_primary`,
`tests/test_v4_invariants.py::test_inv004_archetype_and_tier_d_evidence_never_reach_primary`,
`tests/test_three_tier_policy.py::test_tier_d_never_reaches_primary_at_any_distance_or_materiality`.
Fixture pair: `primary_evidence_promotion_tier_c` / `_tier_d` (§32 scenario 14 — identical
articles, the exposure record is the only difference and it alone decides the tier).

### 10. Can self-certified relationships bypass verification? — **NO**

Three cuts. (a) A `CompanyNodeExposure` row the system itself wrote is `MODEL_VERIFIED_PRIOR`
/ tier D, never `VERIFIED_RELATIONSHIP` (`evidence.py:225-239`); only
`SUPPLY_LINK`/`MANUAL`/`CURATED` provenance earns tier C (`evidence.py:60-62, 194-215`).
(b) The self-echo guard drops even that D-tier credit for a ticker whose cache row *this
run* just wrote (`evidence.py:98-138, 232-239`). (c) `_check_verified`
(`publication_gate.py:688-702`) checks verifier *availability* first and unconditionally, so
a defaulted `independently_verified=True` cannot authorize anything.

Tests: the 20 cases in `tests/test_exposure_self_certification.py` (notably
`::test_prior_llm_acceptance_cannot_self_certify`,
`::test_fresh_cache_ticker_subject_classifies_article_subject_not_prior`,
`::test_genuinely_prior_row_still_classifies_as_d_prior`),
`tests/test_audit_bypasses.py::test_bypass_self_certifying_cache`,
`tests/test_publication_gate.py::test_verified_flag_cannot_outrank_an_absent_verifier`,
`tests/test_v4_invariants.py::test_inv005_unavailable_validator_fails_closed`.

### 11. Can a legacy section path affect a gated alert? — **NO**

`is_gated` (`publication_gate.py:214-244`) is the single structural signal — any row with
`gate_state` **or** `display_tier` non-NULL — and it reads no settings, so flipping the
strict flag off cannot resurrect the legacy renderer for already-gated rows.
`compute_ripple_layers` returns `_strict_sections(...) or []`, never falling through
(`ripple_layers.py:749-762`), and `refine_alert` leaves gated rows untouched
(`app/analysis/refinement.py`, T7).

Tests: `tests/test_sections_structural.py::test_gated_alert_never_renders_legacy_layers`,
`::test_gated_alert_legacy_unreachable_even_flag_off`, `::test_ungated_alert_keeps_three_tier`
(the legacy-preservation control), `::test_legacy_secondary_spellings_stay_isolated_from_the_renamed_tiers`,
`tests/test_v4_invariants.py::test_inv008_llm_section_layer_ignored_for_gated_alert`,
`tests/test_audit_bypasses.py::test_bypass_legacy_section_resurrection`,
`tests/test_refinement_gated_guard.py::test_refine_alert_leaves_a_gated_row_byte_identical`
(§32 scenario 16).

### 12. Can a raw node ID reach the UI? — **NO**

Section labels resolve through controlled tables only — `_SECTOR_LABELS` for sector parents,
`"linked to <company name>"` for company parents, `knowledge.section_label_for` for the 42
registry mechanisms, then `_TAXONOMY_LABELS`, then the controlled `OTHER_LABEL`
(`ripple_layers.py:421-437`, `knowledge.py:514-527`, `OTHER_LABEL` at
`ripple_layers.py:153`). `causal_parent_id` is used only for lookup and is never emitted on
the wire (`grep` shows it only at `ripple_layers.py:427, 453, 485`); no v4 component
references any parent/node id.

Tests: `tests/test_ripple_taxonomy_sections.py::test_no_section_title_ever_contains_a_raw_node_id`
(asserts no snake_case in any title), `::test_unknown_secondary_parent_falls_back_to_other_label`,
`::test_unknown_macro_parent_falls_back_to_other_label`,
`tests/test_sections_structural.py::test_unknown_mechanism_uses_controlled_fallback_label`,
`::test_all_42_mechanisms_have_labels`. Narrow residual: when a company-parent's row is not
in the alert, the label falls back to the parent **ticker** string
(`ripple_layers.py:430-432`) — a real, reader-meaningful identifier, not an LLM-invented node
id, but a fallback worth noting.

### 13. Can a non-demand mechanism be labeled DEMAND at the company edge? — **NO**

Every company edge takes its relation from the mechanism registry via `_edge_relation`
(`pipeline.py:294-300`), which returns the registry's controlled `relation` or the controlled
`"OTHER"` — never a guess and never a blanket `"demand"`; node→node edges get
`"correlation"` (`pipeline.py:1947-1953, 1966-1969`). The vocabulary is closed
(`EDGE_RELATIONS`, `knowledge.py:488-493`) and each of the 42 mechanisms carries an explicit
relation/directness/label triple (`knowledge.py:114-483`, registry version `kg-3`).

Tests: `tests/test_knowledge_taxonomy.py::test_every_mechanism_has_relation_directness_and_label`,
`::test_normative_relation_examples`,
`tests/test_pipeline.py::test_an_unknown_parent_edge_gets_other_not_demand`,
`::test_a_genuine_demand_mechanism_still_gets_the_demand_relation` (the control),
`::test_company_attachment_edges_carry_the_registry_relation`. Verified by grep at T12: no
hardcoded `"demand"` remains in `_v3_edges` (two comment hits only).

### 14. Can contradictory company-level fundamental states persist? — **NO** (SQLite backstop; app-layer only on Postgres — risk 2)

Direction is derived from the effect at write time (Q1.1), the §24 gate blocks the write
(`pipeline.py:1061-1067`) and blocks the serve (`feed_v2.py:402, 374-414`), and migration
0008 installs BEFORE-INSERT and BEFORE-UPDATE triggers that abort a contradictory gated row
at the database (`0008_three_tier_blueprint.py:126-155`). 0008 also repairs the pre-existing
corpus **before** creating the triggers (ordering ruled at plan time).

Tests: `tests/test_gated_row_immutability.py` (6 trigger cases incl. the
`test_ungated_legacy_row_updates_still_allowed` control),
`tests/test_migrations.py::test_0008_installs_gated_consistency_triggers`,
`::test_models_and_0008_trigger_ddl_are_byte_identical`,
`::test_batch_recreating_alert_companies_drops_the_triggers` (the hazard is loud, not silent),
`tests/test_consistency_gate.py` (23 cases). **Limitation:** the triggers are SQLite DDL;
production Postgres has no ported equivalent, so there the guarantee rests on the two
app-layer gates plus derived direction (risk 2).

### 15. Can stale workers mutate gated rows? — **NO**

Application half: `refine_alert` and both repo-root maintenance scripts skip gated rows
(`app/analysis/refinement.py`, `backend/reanalyze_recent.py`,
`backend/fix_direction_contradiction.py`, T7 + fix `726c72d0`); the measurement/remeasure
paths skip them structurally (`pipeline.py:769, 866`). Database half: the 0008 triggers hold
even for a writer that never imports this code, including the "NULL out the rationale" shape
(`0008:126-141`).

Tests (§32 scenario 15's indexed set):
`tests/test_refinement_gated_guard.py::test_refine_alert_leaves_a_gated_row_byte_identical`,
`::test_reanalyze_recent_skips_a_gated_row`, `::test_fix_direction_contradiction_skips_a_gated_row`,
plus the two positive controls proving the legacy path still works for ungated rows;
`tests/test_gated_row_immutability.py::test_trigger_blocks_rationale_nulling_on_gated_row`.

### 16. Can two processes create duplicate alert results? — **NO**

`alerts.content_key` + a partial unique index `uq_alerts_article_content`
(`app/models.py:380-390`; `0008:188-243`) makes a second identical analysis an
`IntegrityError` that the persist path converts into "return the existing alert"
(`pipeline.py:1104-1126`); the key itself is the run's versioned content hash
(`pipeline.py:2202`). Legacy rows (NULL key) are deliberately unconstrained.

Tests: `tests/test_pipeline.py::test_two_sessions_racing_one_content_key_converge_on_one_alert`
(a real two-connection race on a file-backed SQLite DB, with an anti-false-pass log
assertion), `::test_a_second_persist_with_the_same_content_key_returns_the_existing_alert`,
`::test_the_dedup_reuse_path_claims_no_content_key`,
`tests/test_gated_row_immutability.py::test_duplicate_content_key_insert_rejected`,
`::test_null_content_key_alerts_are_not_constrained` (§32 scenario 17).

### 17. Can incompatible cache versions / provider outputs mix? — **NO**

Both cache keys carry every version axis. The v3 result cache key is
`v3:<POLICY_VERSION>:<PROMPT_VERSION>:<SCHEMA_VERSION>:<KNOWLEDGE_VERSION>:<strict_flag>:<content_hash>`
(`pipeline.py:134-153`) plus a TTL (155-171); the stage-cache fingerprint adds provider,
model, static prefix, schema JSON and the `full|compact` variant
(`app/analysis/impact_graph/router.py:250-278`). Fallback-tainted and malformed results are
never written at all.

Tests (§32 scenario 18): `tests/test_provider_cache_isolation.py` (4),
`tests/test_provider_policy.py::test_fingerprint_includes_provider_and_model`,
`::test_fallback_does_not_repoint_later_cache_keys_at_groq`,
`tests/test_fallback_quality.py::test_fingerprint_includes_policy_version_and_strict_flag`,
and scenario 19's degradation set (`test_groq_is_never_authoritative`, …).

### 18. Can HIGH confidence exist without appropriate evidence? — **NO**

`confidence_band` (`publication_gate.py:465-503`) is deterministic and requires **all** of:
a displayable tier, an authoritative (not fallback/degraded/failed) run, an available
verifier, a known materiality grade, evidence tier ∈ {A,B,C,SUBJECT}, HIGH materiality and a
SUPPORTED counterfactual. Tier D/E can never be HIGH; a non-displayed candidate is `UNKNOWN`,
never LOW. The numeric score is gone from the v4 wire (ruling R4;
`feed_v2.py:344` strips it) — the reader sees the band only
(`frontend/src/v4/FeedV4.tsx:381-386`).

Tests: `tests/test_three_tier_policy.py::test_confidence_band_never_high_on_curated_evidence`,
`::test_confidence_band_high_needs_every_contributor`,
`::test_confidence_band_is_unknown_when_the_pipeline_could_not_answer`,
`::test_confidence_band_is_deterministic`,
`tests/test_evidence_records.py::test_llm_evidence_refs_cannot_raise_confidence`,
`tests/test_v4_feed_truth.py::test_no_numeric_confidence_score_on_any_feed_v2_payload`.

### 19. Can a secondary/rejected company become the headline? — **NO for rejected rows and NO over any primary; owner-ruled exception for zero-primary alerts**

Excluded/rejected rows never enter the headline set or any section
(`feed_v2.py:234-266`, `_strict_displayable` 264-284). Where a primary exists the headline
comes only from primaries — a bigger-moving secondary cannot outrank it
(`tests/test_feed_primary_only.py::test_peak_ticker_ignores_bigger_secondary_mover`). Macro
context is never headline-eligible (`feed_v2.py:247-256`;
`consistency.py:180-196`).

**The exception (owner ruling R1, recorded in the plan and the ledger):** an alert whose gate
produced zero primaries but ≥1 SECONDARY_RIPPLE row is listed and headlined from its ripple
movers, explicitly badged `exposure="indirect_only"`
(`feed_v2.py:256-261`; UI badge at `frontend/src/v4/FeedV4.tsx:590-600`). Blueprint §29's
literal line ("do not promote secondary companies to the main headline; the primary feed
contains only PRIMARY") is therefore enforced as headline *discipline* (never over a primary,
never a rejected or macro row) rather than as feed suppression — the trade the owner chose in
favour of §1's breadth requirement. Reversible in one predicate if the owner prefers the
literal reading. Tests: `tests/test_consistency_gate.py::test_headline_may_be_a_secondary_company_when_there_is_no_primary`,
`::test_headline_outside_the_secondary_set_is_blocked_when_there_is_no_primary`,
`tests/test_audit_bypasses.py::test_bypass_headline_ignores_tier`,
`tests/test_feed_primary_only.py::test_secondary_only_alert_listed_as_indirect_only`,
`::test_excluded_only_alert_still_absent_from_list`.

### 20. Can the system show valid SECONDARY_RIPPLE sectors even when PRIMARY is empty? — **YES** (the one question whose safe answer is YES)

A zero-primary alert with validated ripple rows is listed, badged `indirect_only`, and its
card back renders the RIPPLE (and MACRO) taxonomy sections — `include_secondary` is True
precisely in that case (`feed_v2.py:750-752`, `_strict_sections` 352-540).

Tests: `tests/test_feed_primary_only.py::test_secondary_only_alert_listed_as_indirect_only`,
`tests/test_v4_feed_truth.py::test_strict_deep_dive_only_alert_listed_as_indirect_only`,
`tests/test_ripple_taxonomy_sections.py::test_two_secondary_parents_render_two_taxonomy_sections`.
Fixture: `crude_macro_decline_no_primary` (§32 scenario 1).

---

## Part B — final report (execution prompt's 15 items)

### 1. Files changed

21 plan commits (12 task commits + 9 review-fix/doc rounds). The whole branch range
`853912e5..22f8ba1c` is **69 files, +9,492 / −439**, which also contains the five foreign UI
commits listed at the end of this item. Plan-scope files:

*Engine / policy:* `backend/app/analysis/impact_graph/knowledge.py`,
`publication_gate.py`, `consistency.py` (new), `evidence.py`;
`backend/app/pipeline.py`; `backend/app/market/ripple_layers.py`;
`backend/app/routers/feed_v2.py`; `backend/app/analysis/refinement.py`;
`backend/app/models.py`; `backend/app/main.py`; `backend/app/config.py`.
*Schema:* `backend/alembic/versions/0008_three_tier_blueprint.py` (new),
`backend/tools/migrate_on_boot.py`.
*Scripts/tools:* `backend/reanalyze_recent.py`, `backend/fix_direction_contradiction.py`,
`backend/tools/offline_benchmark.py`, `backend/benchmark_impact_graph.py`,
`backend/.gitignore`.
*Frontend:* `frontend/src/v4/FeedV4.tsx`, `DeepDiveV4.tsx`, `v4.css`, `FeedTruth.test.tsx`,
`frontend/src/v3/api.ts` (legacy type union comments only).
*Tests:* 21 backend test modules — `test_audit_bypasses`, `test_blueprint_fixture_index`
[new], `test_consistency_gate` [new], `test_evidence_claims` [new], `test_fallback_quality`,
`test_feed_primary_only`, `test_gated_row_immutability` [new], `test_knowledge_taxonomy`
[new], `test_migrations`, `test_offline_benchmark`, `test_pipeline`,
`test_price_fundamental_decoupling`, `test_publication_gate`, `test_refinement_gated_guard`
[new], `test_ripple_taxonomy_sections` [new], `test_sections_structural`, `test_three_tier_policy`
[new], `test_v4_feed_truth`, `test_v4_invariants`, `test_v4_strict_gate_wiring`,
`test_v4_strict_sections`.
*Corpus:* 23 fixture files touched under `backend/benchmarks/regression_events/` — **17 new**
plus tier-vocabulary respellings on 6 existing ones; the corpus now holds 40 fixtures.

**Foreign work on this branch — NOT plan scope, not attributed to this work:** five commits
from a concurrent session doing v4 card UI (`8b504754`, `2be265c8`, `f86a65ef`, `f5529e72`,
`b6cd8310` — story-card slimming, clamped summary, inline MORE button; all
`frontend/src/v4/*`). Note the dispatch brief named only the last two; there are five. All
are green under tsc/vitest/build. Additionally the working tree carries that session's
**uncommitted** fact-provenance/geography work (`engine.py`, `prompts.py`, `schemas.py`,
`db.py`, `models.py`, `pipeline.py` hunks, `tests/test_migrations.py`, untracked
`tests/test_fact_provenance.py` and `alembic/versions/0009_*.py`). None of it was staged,
edited, or judged by any plan task.

### 2. Schema / migrations

`0008_three_tier_blueprint` (down_revision `0007`), one migration, four phases, all
inspector-guarded and re-runnable:

1. **Columns (nullable, additive):** `alert_companies.causal_directness`,
   `.discovery_source`, `.evidence_source`, `.edge_relation`;
   `company_decision_records.causal_directness`; `alerts.content_key` (`0008:100-196`).
2. **Tier value rewrite (ruling R3):** `secondary_deep_dive` / `secondary` →
   `secondary_ripple` in both tables (`0008:198-215`); legacy spellings remain readable
   forever via `is_secondary_tier` (`publication_gate.py:92-101`).
3. **Contradiction repair** of the pre-existing corpus — deliberately ordered *before*
   trigger creation so the repair cannot trip its own trigger.
4. **Backstops:** the two gated-row consistency triggers (SQLite) and the partial unique
   index `uq_alerts_article_content` on `(article_id, content_key) WHERE content_key IS NOT
   NULL` (`0008:126-155, 234-243`).

Downgrade drops the additive objects; it cannot restore rewritten tier strings. Trigger DDL
is duplicated in `models.py` on purpose and kept honest by
`test_models_and_0008_trigger_ddl_are_byte_identical`. `migrate_on_boot.py`'s three-state
contract is unchanged and re-verified for 0008.

### 3. PRIMARY / SECONDARY_RIPPLE / MACRO_CONTEXT architecture

One 13-gate validity walk, then a three-way tier cascade — validity and policy never mix
(`publication_gate.py:705-862`):

- **PRIMARY** (`_primary_authorized`, 776-806): displayable effect, grade ≠ LOW,
  counterfactual not UNCERTAIN, authoritative (or owner-permitted fallback) quality,
  distance ≤ 2, evidence tier A/B/C at any allowed distance or SUBJECT at d1 only (ruling
  R2), and HIGH grade at d2.
- **SECONDARY_RIPPLE** (809-831): the governed breadth tier — distance ≤ 2, tier
  A/B/C/D/SUBJECT, grade ≥ MEDIUM (LOW only under explicit policy). Failing PRIMARY on
  evidence alone lands here, exactly as §6 demands; failing validity still rejects.
- **MACRO_CONTEXT** (833-843): the surviving d3, never a company-specific claim — never
  headline-eligible, never counted for feed listing, rendered as its own trailing
  `Macro context — <label>` sections.
- **Alert-level finalization** (875-935): dedup on the *resolved* company, primary cap with
  deterministic ranking, overflow **demoted to secondary_ripple** (never deleted).
- Tier vocabulary is closed and shared (`primary` / `secondary_ripple` / `macro_context` /
  `excluded`, `POLICY_VERSION = "pol-2"`).

### 4. Evidence changes

- **Curated evidence records for displayed rows** — a displayed tier-D row backed by a
  registry mechanism now persists a `CURATED_ARCHETYPE` record instead of leaving the claim
  unsourced (`evidence.py:550-620`, T8).
- **Claim hygiene** — `contains_company_specific_claim` / `sanitize_company_claim`
  (`evidence.py:387-436`) strip unsupported quantitative, superlative, balance-sheet and
  spelled-out-quantity claims from displayed explanations, falling back to the controlled
  registry sentence; the raw text is retained on excluded rows for audit.
- **Direction guard on registry prose** — a registry sentence is served only when it agrees
  with the section's member-derived effect (`ripple_layers._note_for` / `_registry_note`),
  so a blank explanation can never sit under a contradicting note.
- **Evidence class/tier ladder unchanged in spirit, tightened in fact:** SupplyLink and
  provenanced exposure = tier C with a real payload; model-written cache rows = tier D; the
  self-echo guard; `MARKET_OBS`/`E` non-authorizing (`evidence.py:65-241`).
- No fabricated evidence is constructible: `test_evidence_claims.py::test_evidence_records_are_only_constructed_in_known_places`
  and `::test_no_evidence_record_source_url_is_llm_provided` are AST-level scans.

### 5. Confidence / materiality changes

Confidence became **evidence-aware and deterministic** (§18): `confidence_band`
(`publication_gate.py:465-503`) replaces the effectively-constant numeric score on the
reader surface; the numeric score is audit-only (ruling R4) and stripped from feed-v2 rows
(`feed_v2.py:344`). Materiality logic itself is deliberately **unchanged** (§19 says keep
it): the composite grade continues to come from
`app/analysis/impact_graph/materiality.py` and is now read off the persisted
`materiality_grade` column rather than recomputed from the naked float. Counterfactual logic
(§20) is likewise unchanged; the gate keeps `NOT_SUPPORTED` → reject and `UNCERTAIN` →
never-primary.

### 6. Consistency validator

New module `app/analysis/impact_graph/consistency.py` (205 lines, zero DB/LLM/settings
dependencies) implementing §24: per-company net-effect vs channels, derived-direction
equality, closed tier vocabulary, and the headline-subset rule. Two boundaries:
**pre-persistence** (`pipeline.py:1061-1067`, raising `ConsistencyError` → per-article
`ANALYSIS_FAILED`, the tick continues — including on the dedup-reuse path, fix `060f7e21`)
and **pre-serve** (`feed_v2.py:374-414`, which withholds the offending row, logs the
violation, and re-derives the alert headline over the survivors, degrading to the
unavailable-measurement placeholder when none remain). Severity is calibrated
(`consistency.py:65-103`): an unsupported claim is blocked; an acknowledged minor offset is
not (controller ruling — channel materiality is unmodelled, and blocking would refuse the
system's own correct output).

### 7. Taxonomy / section changes

The generic `SECONDARY — INDIRECT EXPOSURE` bucket is **deleted** and repo-wide-pinned as
absent. Sections are assembled deterministically from `(economic_effect, controlled label)`
in three ordered families — `MECH:` primaries, `RIPPLE:` secondaries, `MACRO:` context
(`ripple_layers.py:352-540`) — with invariants asserted at build time
(`_assert_section_invariants`: no ticker in two sections, no mixed effects inside one
mechanism section, no cross-tier row in the wrong family). Labels come from the 42-mechanism
registry (`knowledge.py:114-527`, `kg-3`), with sector/company tables and a controlled
`OTHER_LABEL` fallback; two distinct unknown parents merge into one section rather than
producing duplicate titles. The frontend styles `MACRO:` layers distinctly (`macro4`) and
prints the per-row `DIRECTNESS · TIER` line.

### 8. Stale-worker / concurrency changes

App layer: gated rows are immune to `refine_alert`, `reanalyze_recent.py`,
`fix_direction_contradiction.py`, and both measurement/remeasure paths — structurally, not
behind the flag. DB layer: 0008's BEFORE-INSERT/UPDATE triggers (sign contradiction and
rationale-nulling) plus the partial unique index for idempotency. Boot layer: `app/main.py`
refuses to start the scheduler when the schema is confirmed behind head
(`test_maybe_start_scheduler_refuses_when_schema_is_confirmed_behind`). Concurrency:
`content_key` + `IntegrityError` → return-existing, proven by a genuine two-session race
test.

### 9. Provider / cache changes

**None to the provider layer** — Claude remains the configured reasoning provider, the
router, prompts (`IMPACT_PROMPT_VERSION` still `kg-6`) and schemas
(`IMPACT_SCHEMA_VERSION` still `kg-1`) were not touched by any plan commit; prompt caching,
application caching and the compact-variant policy are untouched. The only cache-relevant
change is that two constants moved: `KNOWLEDGE_REGISTRY_VERSION` `kg-2 → kg-3` and
`POLICY_VERSION` `pol-1 → pol-2`. Both already participate in the v3 result key
(`pipeline.py:148-153`) and the stage fingerprint (`router.py:270-278`), so the bumps are
explicit, self-invalidating cache misses rather than silent mixing. (The uncommitted foreign
work in the tree raises `IMPACT_PROMPT_VERSION` to `kg-7`; that is not this plan's change.)

### 10. Tests added / results

**212 new test functions** (many parametrized, so the executed-case delta is larger) across
21 backend test modules and the v4 frontend suite — **+4,503 lines** of test code under
`backend/tests` alone — plus 17 new corpus fixtures and a rot-proof §32 index. Verified
numbers (Task 12, reproduced in part by this task):

| suite | result |
|---|---|
| `backend` full (`ENABLE_SCHEDULER=false pytest -q`) | **2478 passed, 2 skipped**, 7 pre-existing warnings, 134s |
| frontend `npx tsc --noEmit` | exit 0, no diagnostics |
| frontend `npx vitest run` | **772 passed**, 4 skipped, 113 files |
| frontend `npm run build` | clean, exit 0 |
| `tools/run_offline_suite.py` | **6/6 PASS** (schema, unit, invariants, bypasses, regression, audit_report) |
| Task-13 re-run of the audit-cited subset (20 modules) | **285 + 267 = 552 passed**, 0 failed |

New this pass: `test_blueprint_fixture_index.py` — §32's twenty scenarios mapped to real
fixtures/tests, every pointer resolved by import so a rename or deletion fails *there*
instead of silently orphaning a scenario.

### 11. Benchmark results

`tools/offline_benchmark.py`, re-run by this task at `22f8ba1c` — **40 fixtures**, exit 0:

```
company_precision 65/65 · company_recall 39/39 · false_positive_rate 0/92
primary_feed_precision 39/39 · fundamental_direction_accuracy 39/39
mixed 6/6 · mechanism 6/6 · causal_distance 60/60 · materiality 14/14
section 31/31 · abstention 15/15 · entity 40/40 · evidence 63/63
rejection_recall 34/34 · rejection_reason 9/9 · secondary_ripple 16/16
macro_context 2/2 · directness 26/26 · explanation_faithfulness 129/129
market_measurement_accuracy  N/A (0/0)
```

**Read this as "no labeled expectation in the offline corpus is currently violated", not as
an accuracy claim** (§33). The corpus is hand-authored replay with canned model output; it
carries no market-measurement labels (hence the honest `N/A`), `macro_context` rides only two
observations, and the harness's exit code gates on `primary_feed_precision` alone.

### 12. Cost / latency impact

- **Zero added LLM stages and zero added prompt tokens.** Every change is deterministic
  Python or SQL: the gate, the consistency validator, the section assembler, the evidence
  classifier/sanitizer, the taxonomy registry and the serializers make no model calls, and
  no prompt file was modified by this plan. Per-article call *count* is unchanged.
- **One-time re-analysis cost.** The `kg-3` and `pol-2` bumps invalidate both the v3 result
  cache and the stage cache, so the first time each article is processed after this lands it
  pays a full fresh analysis instead of a replay. That cost is bounded (once per article),
  intentional (a policy/knowledge change must not be served from a cache judged under the old
  policy), and cannot be avoided without accepting stale semantics.
- **Latency:** the added work per alert is O(companies) dictionary/regex work plus two extra
  DB reads (materiality grade column, evidence records) and, at serve time, one pass of the
  consistency validator per alert. The measured backend suite got *faster* end to end than
  the baseline scheduler-on run; nothing in the durations profile is network-shaped.
- **No live telemetry exists.** Any real cost/latency delta is unknown until a canary runs.

### 13. Remaining risks

1. **Test-suite hermeticity.** `backend/.env` sets `ENABLE_SCHEDULER=true` and
   `app/main.py` starts the scheduler at *import* time, so a bare `pytest` run (20+ modules
   import `app.main`) starts a real `BackgroundScheduler` that opened live TLS to Yahoo and
   `api.anthropic.com` during Task 12's first run. Pre-existing, not a blueprint regression.
   Blast radius checked: **zero `llm_call_usage` rows, zero articles fetched, no alert newer
   than 2026-08-05** — no spend, no DB writes. Every recorded number was taken with
   `ENABLE_SCHEDULER=false`. **Recommendation:** a session-scoped `conftest` guard forcing
   `settings.enable_scheduler = False` before `app.main` import.
2. **No Postgres port of the 0008 triggers.** They are SQLite DDL; production Postgres
   relies on the two app-layer gates plus derived direction. A writer that bypasses the app
   has no database-level backstop there.
3. **Dual `confidence_band` vocabulary residual.** A pre-V4 gated row storing the old-vocab
   `"LOW"` is indistinguishable at the serializer from a new-vocab `LOW`. Structurally
   contained (ungated rows never carry a band on the wire), but only a data migration closes
   it.
4. **The entire V4 strict path is dormant.** `IMPACT_ENGINE_V4_STRICT` defaults false and
   appears in no deploy artifact, so none of this is exercised by production traffic; all
   evidence above is offline. This is also why risk items below are "reachable" rather than
   "observed".
5. **`DIRECTNESS_UNKNOWN` is spelled `INDIRECT`.** A gated row with NULL `causal_distance`,
   no explicit directness and an unknown parent serves "INDIRECT EXPOSURE" for what is
   actually unknown (`publication_gate.py:170`). Parked at T2 review.
6. **`macro_context_accuracy` rides two observations.** Deliberately two different archetypes
   with opposite effect signs and opposite directness verdicts, but two is two.
7. **Evidence records are conditional on registry coverage.** A displayed row whose causal
   parent is a sector or a company (not a registry mechanism) and which has no SupplyLink can
   persist with **zero** evidence records. Reachable, logged, and currently absent from the
   corpus; ratified as a limitation at T8 review with a benchmark counter / gate-demotion
   idea parked for post-canary.
8. **The alert deep-dive endpoint has no frontend consumer.** `GET
   /api/feed-v2/{id}/deep-dive` is an API/audit surface only; macro sections reach readers
   through the detail layers in `FeedV4`. Combined with item 9 this is what makes Q3's
   caveat real.
9. **§29 tension on the card back** (see Q3): with a primary present, RIPPLE/MACRO sections
   are withheld from the article surface by the standing corrective-V4 owner decision
   (`feed_v2.py:750-752`). Owner decision needed: flip the flag or build the deep-dive UI.
10. **Mechanism-id alias-map duplication** across `pipeline.py`, `ripple_layers.py` and
    `evidence.py` — three copies of one rewrite, all derived from `MECHANISMS` at import (no
    drift risk today). Right home is a `knowledge.py` accessor.
11. **The benchmark's exit code gates on `primary_feed_precision` only.** Every other metric
    prints but does not fail the run; a regression in, say, `secondary_ripple_accuracy` would
    show in the table and still exit 0. Parked at T10 review.
12. **Labeled-corpus work is entirely open (§33/§34).** No real-article corpus, no human
    review sample filled in, no `SECONDARY_RIPPLE` recall measured against reality.

### 14. Why live mode remains OFF

Because the blueprint says so (§36: "Do not enable live mode… Only after the implementation
and offline benchmark pass may an owner-authorized canary occur") and because four release
conditions are unmet:

| condition | status |
|---|---|
| safety invariants + bypass pins green | **MET** (offline) — 25 invariant + 11 bypass tests, 552-test audit subset re-run clean |
| PRIMARY false-positive target on a *real labeled* corpus | **NOT MET** — the corpus is hand-authored replay (§33) |
| cost/latency acceptable on live telemetry | **NOT MET** — no live telemetry exists |
| human review sample | **NOT MET** — `benchmarks/out/reviews` artifacts exist, none filled in |
| owner authorization | **NOT MET** — not requested, not given |

Mechanically: `impact_engine_v4_strict` defaults `false` (`config.py:318`);
`IMPACT_ENGINE_V4_STRICT` appears in no `Dockerfile`, no `.github/`, and not in
`backend/.env`; no scheduler wiring was added for the new engine; every tool and test used in
this pass runs offline against fixtures. No plan task enabled a flag, backfilled data, or
made a paid call.

### 15. Exact future canary procedure (NOT executed)

Adapted from the corrective-V4 canary (`docs/superpowers/reports/2026-08-13-corrective-v4-self-audit.md`
§19) with the additions this pass requires. **None of these commands has been run.**

**Preconditions.** (a) A labeled corpus from real ingested articles with real model
responses, scored on §34's metric list — not this offline fixture corpus. (b) At least one
filled-in human review sample. (c) The hermeticity guard (risk 1) landed, so a canary
service's test/CI runs cannot start a rogue scheduler. (d) Explicit owner authorization.
(e) Acknowledgement of risks 2, 7, 9 — Postgres has no trigger backstop, zero-evidence
displayed rows are reachable, and the card back currently withholds ripple sections on
primary-carrying alerts.

1. **Back up first, then rehearse the migration** (the 0006 precedent: rehearse on a restored
   copy before touching prod):
   ```
   railway ssh --service <service>
   pg_dump "$DATABASE_URL" -n public -f /tmp/pre-0008-$(date +%Y%m%d).sql
   # restore that dump into a scratch DB and run the upgrade there FIRST
   cd backend && python -m alembic upgrade head && python -m alembic current   # expect 0008
   ```
   Verify on the rehearsal DB: (i) the four new `alert_companies` columns exist and are
   nullable; (ii) `SELECT display_tier, count(*) FROM alert_companies GROUP BY 1` shows zero
   `secondary_deep_dive` / `secondary` rows; (iii) the contradiction repair left no gated row
   with `economic_effect='positive' AND direction='bearish'` (or the mirror); (iv)
   `uq_alerts_article_content` exists. **Note:** the triggers are SQLite-only — do not expect
   them on Postgres; that is risk 2, and it is why (iii) must be re-checked after the canary
   window too.
2. **Apply to production with the flag still off** (schema is additive and guarded), then
   confirm `alembic current` = `0008` and the app boots (the boot check refuses to start the
   scheduler on a behind-head schema).
3. **Enable strict mode on exactly ONE service**, never the project:
   ```
   railway variables --service <canary-service> --set IMPACT_ENGINE_V4_STRICT=true
   ```
   Leave `IMPACT_ALLOW_FALLBACK_PRIMARY` and `IMPACT_ALLOW_LOW_MATERIALITY_DEEP_DIVE` unset.
   Consider lowering `IMPACT_MAX_PRIMARY_COMPANIES` for day one.
4. **First article by hand, before any bulk run.** Process a single controlled article
   through the `ingest_one_url` path with the flag on, then verify on that alert:
   - `alert_companies` rows carry `gate_state`, `display_tier`, `causal_directness`,
     `discovery_source`, `evidence_source`, `edge_relation`, `materiality_grade`,
     `confidence_band`, and a `direction` equal to `DIRECTION_FROM_EFFECT[economic_effect]`;
   - `check_alert_consistency` over the served payload returns **zero** violations, and the
     serve log shows no withheld rows;
   - sections: titles are controlled labels (no snake_case, no raw ids), primaries first,
     `RIPPLE:`/`MACRO:` families separate, no company in two sections;
   - evidence: every **primary** row has ≥1 `EvidenceRecord`; note any displayed row with
     zero records (risk 7) — expected-but-undesired, log it rather than treating it as a
     stop;
   - `alerts.content_key` is populated; re-running the same article creates no second alert;
   - `CompanyDecisionRecord` exists for every candidate with a machine-readable
     `rejection_reason`.
   Any failure here stops the canary at one article.
5. **Then monitor for a minimum of one full trading day**, watching: `final_state` histogram
   (all-reject = starved feed; all-eligible = an inert check); `display_tier` distribution
   and `primary_cap_overflow` note volume; `rejection_reason` breakdown, especially
   `REJECT_VALIDATOR_UNAVAILABLE`; `evidence_class` distribution; `analysis_quality` /
   provider fallback rate; token spend per article vs the pre-canary baseline for the same
   service; served-vs-analyzed alert counts; and the ratio of `exposure="indirect_only"`
   alerts (ruling R1's surface — if it dominates, PRIMARY is too strict).
6. **Rollback triggers (any one, immediately):** a raw node id or LLM-authored string in a
   section title; a published company whose `evidence_class` is `MODEL_INFERENCE` or
   `ARTICLE_MARKET_OBSERVATION`; a served row failing `check_alert_consistency`; a gated row
   observed with a sign contradiction (Postgres has no trigger — this is the manual check
   standing in for it); served-alert count below the agreed floor for two consecutive
   cycles; token spend over the agreed cap; any unhandled exception from `_gate_candidates`,
   `_strict_sections` or the pre-serve validator.
7. **Rollback.** `railway variables --service <canary-service> --set
   IMPACT_ENGINE_V4_STRICT=false` — instant, no deploy. **Asymmetry by design:** rows already
   persisted with gate output keep rendering through the strict path (`is_gated` is
   structural, flag-independent). Reverting those requires deleting them or nulling
   `gate_state`/`display_tier` with an explicit reviewed script — there is none today.
   Schema rollback is `alembic downgrade 0007`; it drops the additive objects and **cannot**
   restore the rewritten tier strings — restore from step 1's dump if that matters. Code
   rollback: `git revert` the plan commits individually and **preserve the five foreign v4 UI
   commits** (`8b504754`, `2be265c8`, `f86a65ef`, `f5529e72`, `b6cd8310`).

---

## Part C — §38 definition-of-done walk

| §38 condition | status |
|---|---|
| PRIMARY is highly precise | **MET offline, unproven in production** — 13 gates + R2 evidence bar; `primary_feed_precision` 39/39 and `false_positive_rate` 0/92 on the fixture corpus only (§33) |
| valid ripple sectors/companies preserved and separately governed | **MET in the engine** (§6 policy + taxonomy sections + 3 ripple fixtures); **partial on the UI** — card back withholds them when a primary exists (risk 9) |
| macro context available without becoming a company hallucination engine | **MET** — d3-only tier, never headline, never feed-listed alone, own section family |
| one canonical fundamental truth | **MET** — `economic_effect` is canonical, direction derived, §24 validator at both boundaries |
| market reaction independent | **MET** — separate columns, structural gated-row skip, INV-001/002 |
| evidence auditable | **MET with a documented hole** — records + decision records + AST-level anti-fabrication scans; zero-record displayed rows remain reachable (risk 7) |
| confidence evidence-aware | **MET** — deterministic band, HIGH impossible on D/E |
| sections deterministic | **MET** — labels from a closed registry, invariants asserted at build time |
| legacy and V4 paths cannot mix | **MET** — `is_gated` is structural and flag-independent, pinned both ways |
| stale/concurrent workers cannot corrupt results | **MET on SQLite; app-layer only on Postgres** (risk 2) |
| provider/cache isolation correct | **MET** — every version axis in both keys; scenario 18/19 test sets |
| the system can abstain | **MET** — `REJECT_*` vocabulary with no dead states, `abstention_precision` 15/15, `UNKNOWN` bands, unavailable-measurement placeholder |
| all known current regressions covered by tests | **MET for the §32 list** — the fixture index maps all twenty scenarios to real, import-checked artifacts |
| live mode OFF until owner authorization | **MET** — flag false everywhere, absent from every deploy artifact |

---

*Prepared under the §33 rule: nothing in this document asserts real-world accuracy. Two
§37 answers (3, 19) are qualified by standing owner rulings and are recorded as such rather
than argued into a clean YES/NO; both are reversible in a single predicate if the owner
prefers the literal blueprint reading.*
