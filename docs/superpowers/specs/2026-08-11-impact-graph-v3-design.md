# Impact Graph v3 — implementation map (2026-08-11)

Source specs (user-supplied, priority order):
1. `claude_code_master_implementation_prompt_v2.md` (execution)
2. `financial_impact_graph_architecture.md` (architecture / routing truth)
3. `gemini_impact_graph_prompts_v2(1).md` (canonical prompt behavior)
4. `financial_impact_graph_prompts.md` (supplementary prompts)

## CURRENT SYSTEM → REQUIRED CHANGE → FILES → RISKS

### 1. Model routing
CURRENT: one Gemini model pair (flash/flash-lite) behind `CallRoutedClient`;
protected calls = {extract_facts, identify_companies}; identify_sectors /
verification / edges ride Groq even for granted pulse articles; Groq
fallback silently equivalent.
CHANGE: stage-typed router. Protected articles: facts → GEMINI_FACT_MODEL
(gemini-3.5-flash-lite), ALL graph reasoning (shocks, graph, companies,
ripple, verification, edges, ranking) → GEMINI_REASONING_MODEL
(gemini-3.1-pro-preview, high thinking). Degradation ladder: retry Pro →
retry compact → GEMINI_FALLBACK_MODEL (gemini-3.6-flash, degraded) → Groq
(marked `analysis_provider=groq`, `analysis_quality=fallback`). Never
silent. Non-protected articles: same stage contracts served by Groq
(explicitly configured, marked provider=groq).
FILES: new `app/analysis/impact_graph/router.py`; `app/config.py` (env
vars); `claude_client.py` gains a structured-output Gemini JSON client.
All model IDs verified live on the paid key 2026-08-11 via ListModels.

### 2. Graph representation
CURRENT: `ImpactEdge(from_node_kind, from_label, to_node_kind, to_label,
relation, direction, note, source)` — no distance, no scores. Ripple
companies REQUIRE `parent_ticker` (enum-forced). `impact_level` in
{direct, indirect_l1, indirect_l2}.
CHANGE: edges gain `parent_type/child_type` in {event, economic_node,
sector, commodity, policy, company}, `causal_distance` int,
`impact_strength/confidence_f/materiality` floats, `time_horizon`,
`mechanism` (rides `note`), `verification_status`. Companies gain
`causal_distance`, `impact_strength`, `materiality`, `confidence_f`,
`parent_type`, `parent_id`, `mechanism`. `parent_ticker` becomes ONE
optional edge kind (company→company only with a real relationship).
`impact_level` KEPT as a derived legacy label (1→direct, 2→indirect_l1,
3→indirect_l2, 4+→indirect_l3plus) so the UI/API keep rendering.
FILES: `models.py`, `db.py::_ADDED_COLUMNS`, `analysis/schemas.py`.

### 3. Cascade → recursive engine
CURRENT: fixed stages direct→L1→L2 in `cascade.analyze_article`;
article-facts-only doctrine; "trade TODAY" test; both-winners framing.
CHANGE: new `app/analysis/impact_graph/engine.py`:
facts → initial shocks (distance-1 anchor) → per-node direct companies →
frontier queue recursion (one hop per Gemini call, MAX_CAUSAL_DEPTH=5,
distance-aware materiality/confidence thresholds, visited-node/edge sets,
per-article token+cost budget, deterministic gates before every call) →
company verification → edge verification → ranking. Prompts verbatim from
spec doc 3 (doc 4 fills gaps). "Analyst-material over stated horizon"
replaces "trade TODAY". Facts stay canonical but relevant article excerpts
+ verified company metadata (business_desc, supply links) ride the dynamic
suffix. ONE authoritative path: `pipeline.process_new_articles` calls the
new engine for every article; the old `cascade.analyze_article` path is
unwired.
FILES: new package `app/analysis/impact_graph/` (engine, stages, router,
schemas, budget); `pipeline.py`; `companies/candidates.py` (metadata
lines); `analysis/verification.py` retired into engine stage.

### 4. Scoring / ranking
CURRENT: magnitude_low/high + confidence_score int; feed sorts by recency;
no materiality on companies.
CHANGE: impact_strength/confidence/materiality ∈ [0,1] proposed by model,
validated+clamped in code; thresholds per distance (config):
d1 .30/.55, d2 .35/.60, d3 .45/.65, d4 .55/.70, d5 .60/.75. Ranking =
Gemini ranking pass proposes; code enforces sort by (impact, materiality,
confidence) — never generation order/market cap. Beneficiary/adverse
buckets may be empty.
FILES: engine + config + persist.

### 5. Telemetry / budget
CURRENT: usage_log per call (tokens, model, tier); no per-article budget,
no cache/thinking-token tracking, no cost.
CHANGE: per-call record gains stage, thinking level, cached_tokens,
thinking_tokens, latency, retries, estimated USD; per-article accumulator
enforces GEMINI_MAX_INPUT/OUTPUT_TOKENS_PER_ARTICLE +
GEMINI_MAX_COST_PER_ARTICLE (stop expansion, keep verified partial graph,
mark budget_exhausted). Cache-friendly prompt: static prefix (system rules,
schemas, sector definitions, graph rules) + dynamic suffix.
FILES: `analysis/usage_log.py`, engine/budget.py, config.

### 6. Persistence / UI compatibility
CURRENT: `_persist_alert` writes AlertCompany + ImpactEdge; ripple_layers /
deck / deep-dive read impact_level + edges; measurement reconciles
direction.
CHANGE: persist new fields; keep every existing consumer working via
derived impact_level + existing edge columns (relation/note filled from
mechanism). Measurement, refinement, translations, feed untouched except
where fields are additive.
RISKS: enumerated after consumer-map exploration (appendix A).

## Execution order
schema → structured-output client + router → engine stages → recursion →
verification/ranking → pipeline wiring → telemetry/budget → tests →
benchmark. Tests green after each phase.

## Known constraint at implementation time
Paid Gemini project is at its monthly spend cap (429 RESOURCE_EXHAUSTED,
verified live) — real-output inspection and the live benchmark can only run
after the cap is raised. Implementation + mocked tests proceed now; live
verification is the explicit final step.

## Appendix A — consumer-map risks and chosen mitigations
1. `frontend impactLevelKey()` coerces unknown labels to "direct" →
   MITIGATED: legacy `impact_level` derived label is capped at
   `indirect_l2` for distance>=3; `causal_distance` column carries truth;
   frontend L3/L4+ labels are a separate follow-up.
2. `LEVEL_CONFIDENCE_MULTIPLIER.get(level, 1.0)` scored unknown levels
   like direct → REPLACED by `_confidence_multiplier(distance, level)`:
   1.0/0.7/0.45 then 0.7-per-hop with a 0.25 floor.
3. Two arrays named "edges" (alerts API from ImpactEdge; feed-v2 synthesized
   from parent_company_id) → UNCHANGED shape; v3 fields are new columns on
   ImpactEdge, feed-v2 synthesis still works off parent_company_id (set
   whenever a company's causal parent IS a company).
4. `basis` axis survives: all v3 companies persist as basis
   "direct_mention" (candidate-grounded); sector fan-out padding is gone by
   design, refinement's basis gate untouched.
5. `parent_ticker` enum guarantee → replaced by node-registry validation in
   engine (_register_edge: parent must exist in the graph) + ticker enums
   in the company schema; `causal_parent_id` is always a validated node id.
6. "Related to holdings" discovery relies on parent_company_id → degrades
   gracefully (only company-parent rows contribute); acceptable, flagged.
7. Legacy cascade module (analysis/cascade.py) is UNWIRED from the live
   pipeline but kept importable for reanalyze_cascade.py and its own unit
   tests; the live path is impact_graph.engine only.
