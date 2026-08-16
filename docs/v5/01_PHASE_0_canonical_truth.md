# PHASE 0 — CANONICAL TRUTH & ANTI-FABRICATION
## Highest value per unit effort. Do this before any new analytics.

**Fixes:** Oil India three-way contradiction · stale worker mutation · fabricated pass-through/pricing-power claims · `DIRECT EXPOSURE · RIPPLE` semantic collapse.

**Prerequisite:** read `00_MASTER_CONTEXT.md`.

---

## OBJECTIVE

Make it structurally impossible for (a) two components to disagree about a company, (b) a non-reducer process to write impact data, (c) an unsupported sentence to reach the user.

No new analytical capability is added in this phase. Existing V4 analysis is rewired to flow through a single deterministic reducer and a single output compiler.

---

## TASK 0.1 — Signal bus

Convert every analysis stage from a verdict-writer to a signal-emitter.

Create `newsflo/core/signals.py`:

```python
class SignalKind(StrEnum):
    CHANNEL = "CHANNEL"                  # an economic transmission channel
    MODIFIER = "MODIFIER"                # policy/contract/hedge adjustment
    EVIDENCE_BINDING = "EVIDENCE_BINDING"
    OBJECTION = "OBJECTION"
    EMPIRICAL_CHECK = "EMPIRICAL_CHECK"
    ENTITY_RESOLUTION = "ENTITY_RESOLUTION"
    DISCOVERY = "DISCOVERY"

@dataclass(frozen=True)
class Signal:
    signal_id: UUID
    event_id: UUID
    company_id: UUID | None
    stage: str
    kind: SignalKind
    payload: dict          # JSON-serialisable, schema-validated per kind
    created_by: str        # 'sensitivity_engine' | 'llm:claude-…' | 'human:naman'
    analysis_version: str
    created_at: datetime
```

Migration: `signal` table, append-only. Add a DB rule or trigger rejecting UPDATE and DELETE. Index `(event_id, company_id)`.

Refactor existing V4 stages so each returns `list[Signal]` instead of mutating company rows. Do not delete V4 logic — wrap it.

---

## TASK 0.2 — Canonical Reducer

Create `newsflo/core/reducer.py`:

```python
REDUCER_VERSION = "r5.0.0"

def reduce_company_impact(
    signals: Sequence[Signal],
    config: ReducerConfig,
) -> CompanyImpact:
    """
    PURE. No I/O. No network. No LLM. No clock reads. No randomness
    except seeded RNG passed in via config.
    Same input set (in any order) => byte-identical output.
    """
```

Implementation order inside the reducer:
1. Resolve entity from `ENTITY_RESOLUTION` signals. Ambiguity ⇒ `REJECTED / ENTITY_AMBIGUOUS`.
2. Collect channels. Aggregate by horizon (Phase 4 adds three horizons; Phase 0 uses a single `NEAR_TERM` bucket).
3. Apply modifiers in deterministic order (sorted by `modifier_id`).
4. Resolve net effect: positive-only → POSITIVE; negative-only → NEGATIVE; both material → MIXED; none material → NO_MATERIAL_IMPACT; unresolved → UNCERTAIN.
5. Grade evidence, compute `weakest_link`.
6. Fold objections, determine which are sustained.
7. Evaluate publication gate (Task 0.4).
8. Emit `CompanyImpact` with `decision_trace_id`.

`CompanyImpact` dataclass per `NEWSFLO_V5_BUILD_SPEC.md` §7.3. Include `rejection_reason`, `reducer_version`, `analysis_version`.

**Phase 0 scope note:** materiality still arrives from existing V4 logic as a channel payload. Phase 2 replaces the source. The reducer's contract does not change.

---

## TASK 0.3 — Single-writer enforcement

Migration `V5_0003_single_writer.sql`:

```sql
-- 1. roles
CREATE ROLE newsflo_reducer;
CREATE ROLE newsflo_readonly;

REVOKE INSERT, UPDATE, DELETE ON company_impact FROM PUBLIC;
GRANT  INSERT, UPDATE          ON company_impact TO newsflo_reducer;
GRANT  SELECT                  ON company_impact TO newsflo_readonly;

-- 2. version fencing
CREATE TABLE supported_version (
  reducer_version text PRIMARY KEY,
  active boolean NOT NULL DEFAULT true
);

ALTER TABLE company_impact
  ADD COLUMN reducer_version text NOT NULL,
  ADD COLUMN reducer_run_seq bigint NOT NULL,
  ADD CONSTRAINT fk_reducer_version
    FOREIGN KEY (reducer_version) REFERENCES supported_version(reducer_version);

-- 3. idempotency
ALTER TABLE company_impact
  ADD CONSTRAINT uq_impact UNIQUE (event_id, company_id, analysis_version);
```

Writer uses monotonic-sequence upsert:

```sql
INSERT INTO company_impact (...) VALUES (...)
ON CONFLICT (event_id, company_id, analysis_version) DO UPDATE
SET ... WHERE company_impact.reducer_run_seq < EXCLUDED.reducer_run_seq;
```

The application connects as `newsflo_reducer` **only** in the reducer persistence module. All other modules use `newsflo_readonly`. Add a startup assertion that the API process cannot write `company_impact`.

---

## TASK 0.4 — Publication gate as config-driven code

Create `newsflo/core/gates.py` + `config/gates.yaml`. Implement the ordered evaluation from spec §7.4. Phase 0 implements the gate structure with whatever inputs exist today; later phases supply better inputs.

Requirements:
- Gate is a pure function `evaluate(impact_draft, config) -> GateResult`.
- `GateResult` carries `tier`, `rejection_reason`, and `gate_trace` (which rules were evaluated, which failed).
- **No LLM call inside this module.** Add a test asserting the module imports no provider code.
- PRIMARY failure and SECONDARY evaluation are separate function calls over the same draft.

---

## TASK 0.5 — Claim records

Migration + `newsflo/core/claims.py`. Schema per spec §11.1.

Binding rules to implement:

```python
EVIDENCE_REQUIRED_TYPES = {"PASS_THROUGH", "HEDGE", "COMPETITIVE", "TIMING"}
ACCEPTED_SOURCES = {"ANNUAL_REPORT", "QUARTERLY", "EARNINGS_CALL", "EXCHANGE_FILING"}

def binding_status(claim, evidence) -> Literal["BOUND","SECTOR_PROXY","UNBOUND"]:
    if claim.claim_type in EVIDENCE_REQUIRED_TYPES:
        if not any(e.source_type in ACCEPTED_SOURCES and e.names_company(claim.company_id)
                   for e in evidence):
            return "UNBOUND"
    ...
```

Any company with an `UNBOUND` claim is a hard REJECT in the gate.

---

## TASK 0.6 — Claim Compiler and Entailment Firewall

Create `newsflo/output/compiler.py` and `newsflo/output/firewall.py`.

**Compiler:** deterministic Jinja templates keyed by `(claim_type, direction, materiality_bucket)`. Renders base prose purely from `CompanyImpact` + `Claim` records. Every numeral inserted via template variable, never free text.

**Optional LLM fluency pass:** prompt constrains to rewriting only. Prompt must state that adding any fact, number, entity, causal step, or qualifier is forbidden. This pass is skippable via config; the system must be fully functional with it off.

**Firewall — two stages:**

```python
def firewall(sentences: list[str], record_set: RecordSet) -> FirewallResult:
    # STAGE 1 — deterministic, runs always
    #   - every numeral in sentence ∈ record_set.numerals (tolerance 0.5% for rounding)
    #   - every capitalised entity ∈ record_set.entities
    #   - every date ∈ record_set.dates
    # STAGE 2 — LLM entailment judge (different prompt lineage than the rewriter)
    #   binary entailed/not-entailed, record_set as context
    # Failing sentences are DELETED, never repaired.
```

Deleted sentences logged to `firewall_deletion` table with sentence, reason, stage, model_id. If deletion leaves output under `MIN_PROSE_CHARS`, fall back to the deterministic template output verbatim.

Expose deletion rate as a Prometheus metric.

---

## TASK 0.7 — Field separation cleanup

Purge merged semantics repo-wide.

- `company_impact` gets four distinct columns: `directness` (DIRECT|INDIRECT|REMOTE), `graph_distance` (int), `discovery_source` (MENTION|MECHANISM|SUPPLY_CHAIN|PEER_CLOSURE), `publication_tier`.
- Data migration: backfill from existing V4 fields with a documented mapping. Where the mapping is ambiguous, set NULL and mark the row `needs_reanalysis = true`. **Do not guess.**
- Delete any UI string, serializer, or template that concatenates a directness value with a tier value.
- Add a lint test (Task 0.8) preventing reintroduction.

---

## TESTS — WRITE THESE FIRST

`tests/phase0/`

```
test_reducer_purity.py
  - reducer imports no I/O modules (ast scan of imports)
  - property test (hypothesis): 10_000 random permutations of a signal set
    produce byte-identical CompanyImpact
  - reducer given identical input twice returns equal objects

test_single_writer.py
  - integration: connection as newsflo_readonly attempting INSERT on
    company_impact raises InsufficientPrivilege
  - simulated stale worker with unregistered reducer_version is rejected by FK
  - out-of-order upsert with lower reducer_run_seq does not overwrite

test_single_truth.py
  - for a fixture event, exactly one CompanyImpact row exists per
    (event_id, company_id, analysis_version)
  - no field combination within a CompanyImpact implies opposite directions
    (assert direction consistent with sign of aggregate channel value)

test_firewall.py
  - sentence containing a numeral absent from record_set is deleted
  - sentence naming an entity absent from record_set is deleted
  - sentence fully entailed survives
  - firewall deletion leaves valid output (fallback path)
  - PRIMARY prose on the fixture corpus has deletion rate == 0

test_claims_binding.py
  - PASS_THROUGH claim without company-named filing evidence => UNBOUND
  - company with any UNBOUND claim => gate returns REJECTED

test_gates_no_llm.py
  - ast scan: newsflo/core/gates.py imports nothing from newsflo/providers
  - PRIMARY failure does not produce SECONDARY without independent evaluation

test_field_separation.py
  - lint: no source file contains a template/f-string joining a directness
    literal with a tier literal
  - CompanyImpact serializer emits four distinct fields

test_market_isolation.py
  - ast scan: newsflo/core/* imports nothing from newsflo/market/*
  - mutating market data for a fixture event leaves CompanyImpact byte-identical
```

---

## DEFINITION OF DONE

All of the following, verified in CI:

- [ ] Zero internal contradictions on the fixture event set
- [ ] Reducer determinism property test passes at 10k permutations
- [ ] A process without the reducer role cannot write `company_impact` — proven by integration test, not by inspection
- [ ] Firewall deletion rate on PRIMARY prose == 0 for fixtures
- [ ] No numeral reaches output prose without a record-set source
- [ ] Four separation fields present, populated, and never concatenated
- [ ] Market isolation test passes
- [ ] Full pre-existing test suite passes with no regressions
- [ ] `DATA_GAPS.md` created and honest

---

## DO NOT

- Do not populate any exposure, coefficient, or empirical table in this phase. Phase 0 touches no financial data.
- Do not "improve" analysis quality here. Wrong-but-consistent is the correct Phase 0 outcome.
- Do not delete V4 analysis modules. Wrap them as signal emitters.
- Do not resolve the backfill ambiguity in Task 0.7 by guessing. NULL + `needs_reanalysis` is correct.
- Do not add an LLM call anywhere in `newsflo/core/`.
