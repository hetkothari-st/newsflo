# PHASE 1 — COMPANY EXPOSURE LEDGER
## The durable asset. Everything downstream computes on this.

**Fixes:** materiality being an LLM guess · near-constant confidence · inability to answer "where does this number come from".

**Prerequisite:** Phase 0 DEFINITION OF DONE passing.

---

## OBJECTIVE

Build the schema, extraction pipeline, and human review workflow for company exposure data sourced from filings. **You are building the machinery. You are not producing the data.**

---

## TASK 1.1 — Schema

Implement `company`, `company_exposure`, `company_modifier` exactly as specified in `NEWSFLO_V5_BUILD_SPEC.md` §4.1, plus:

```sql
CREATE TABLE company_segment (
  segment_id uuid PRIMARY KEY,
  company_id uuid NOT NULL REFERENCES company,
  segment_name text NOT NULL,
  revenue_inr numeric, ebitda_inr numeric,
  revenue_share numeric, ebitda_share numeric,
  fiscal_year int NOT NULL,
  source_url text NOT NULL, source_page text,
  as_of_date date NOT NULL
);

CREATE TABLE company_financials (
  company_id uuid NOT NULL REFERENCES company,
  fiscal_period text NOT NULL,        -- 'FY26Q1'
  revenue_inr numeric, ebitda_inr numeric, pat_inr numeric,
  cogs_inr numeric, raw_material_inr numeric,
  power_fuel_inr numeric, freight_inr numeric, employee_inr numeric,
  gross_debt_inr numeric, floating_debt_inr numeric,
  fx_earnings_inr numeric, fx_expenditure_inr numeric,
  source_url text NOT NULL, as_of_date date NOT NULL,
  PRIMARY KEY (company_id, fiscal_period)
);

CREATE TABLE pass_through_curve (
  curve_id uuid PRIMARY KEY,
  company_id uuid REFERENCES company,   -- NULL = sector-level curve
  sector_id text,
  exposure_tag text NOT NULL,
  points jsonb NOT NULL,                -- [{"lag_days":0,"fraction":0.0}, ...]
  ceiling numeric,
  basis text NOT NULL,                  -- DISCLOSED_CALL|FILED|ESTIMATED|SECTOR_MEDIAN
  evidence_id uuid,
  as_of_date date NOT NULL,
  reviewed_by text,
  CONSTRAINT curve_needs_review CHECK (basis <> 'ESTIMATED' OR reviewed_by IS NOT NULL)
);
```

Enforce the `no_selfcertify` CHECK from §4.1. Add `freshness_days` defaults per `exposure_kind` in `config/freshness.yaml` (suggested: INPUT_COST 400, REVENUE_REALIZATION 400, FX 200, INTEREST_RATE 200, REGULATORY 120).

---

## TASK 1.2 — Company master and entity resolution

`newsflo/entities/resolver.py`.

- Load listed universe from exchange bhavcopy / security master. ISIN is the primary key. Ticker and name are lookup aliases only.
- Maintain `company_alias` (alias, kind: TICKER|LEGAL|COMMON|FORMER, valid_from, valid_to).
- Corporate action handling: merger, demerger, name change, delisting. A claim on an entity outside its validity window returns `ENTITY_WRONG`.
- Parent/subsidiary chain via `parent_isin`. Implement:

```python
def attach_exposure_to_listco(exposure, company) -> AttachResult:
    """
    Exposure in an unlisted subsidiary attaches to the listed parent ONLY IF
    consolidated segment data evidences it. Materiality is then computed
    against consolidated EBITDA with ownership_fraction applied.
    A holdco whose operating exposure sits in a listed subsidiary is capped
    at SECONDARY_RIPPLE with a HOLDCO_DISCOUNT modifier.
    """
```

- Name collision across exchanges/countries must fail closed with `ENTITY_AMBIGUOUS`.

---

## TASK 1.3 — Filing extraction pipeline

`newsflo/ingest/filings/`.

Stage A — acquisition: fetch annual reports and quarterly results (PDF/XBRL) for the target universe. Store raw artefacts with URL and retrieval timestamp. Never discard the source document.

Stage B — deterministic extraction where structure permits:
- XBRL where available (preferred — it is structured and unambiguous)
- Ind AS 108 segment note → `company_segment`
- P&L schedule lines (raw material consumed, power & fuel, freight, employee benefits) → `company_financials`
- Borrowings note → fixed vs floating split
- Forex earnings & expenditure note → FX exposure

Stage C — LLM extraction for unstructured content (raw material *breakup* by commodity, hedging policy statements, pricing/pass-through commentary in MD&A and earnings calls). Output must be a proposal, not a write:

```python
@dataclass
class ExposureProposal:
    company_id: UUID
    exposure_kind: str
    exposure_tag: str
    share_of_base: float
    base_kind: str
    source_url: str
    source_page: str          # MANDATORY — page/section locating the claim
    excerpt: str              # MANDATORY — verbatim supporting text from the filing
    extraction_confidence: float
    model_id: str
```

**Rule: an `ExposureProposal` without a non-empty `excerpt` that literally appears in the source document is discarded.** Implement a verbatim containment check against the extracted document text. This is the anti-hallucination gate for the ledger itself.

Stage D — proposals land in `exposure_proposal` table with status `PENDING_REVIEW`. Nothing enters `company_exposure` without review.

---

## TASK 1.4 — Review workflow

Minimal internal review UI (FastAPI + server-rendered templates is fine — do not build a SPA):

- Queue of `PENDING_REVIEW` proposals, sorted by (company market cap × extraction uncertainty)
- Each row shows: proposed value, exposure tag, verbatim excerpt, link to source PDF at the cited page
- Actions: APPROVE, EDIT+APPROVE, REJECT (with reason)
- Approval writes to `company_exposure` with `reviewed_by` set and `created_by` recording the model that proposed it
- Bulk approve permitted only for proposals from deterministic extractors (XBRL/segment note), never for LLM proposals

Track reviewer throughput and model precision (approve rate, edit rate) per extractor version in a `extractor_quality` view. Falling precision is your signal that an extraction prompt regressed.

---

## TASK 1.5 — Staleness and coverage instrumentation

- Nightly job flags exposures past `freshness_days` as `STALE`. Stale exposures are excluded from PRIMARY per gate rules.
- `coverage` view reporting, per exposure_tag and per sector: companies tagged, % of sector market cap tagged, median exposure age.
- Prometheus metrics + alert at p90 exposure age exceeding threshold.

---

## TESTS

```
test_ledger_schema.py
  - no_selfcertify constraint rejects MODELLED without reviewed_by
  - curve_needs_review constraint rejects ESTIMATED without reviewed_by
  - freshness defaults load from config

test_entity_resolution.py
  - ticker collision across exchanges => ENTITY_AMBIGUOUS
  - claim on merged-away entity after effective date => ENTITY_WRONG
  - unlisted subsidiary exposure without consolidated segment evidence
    does not attach to parent
  - holdco route caps tier at SECONDARY_RIPPLE

test_extraction_verbatim.py
  - proposal whose excerpt does not appear in source document is discarded
  - proposal without source_page is discarded
  - approved proposal writes company_exposure with reviewed_by populated

test_no_direct_write.py
  - LLM extractor cannot write company_exposure (role/permission test)
  - exposure_proposal is the only path into company_exposure

test_staleness.py
  - exposure older than freshness_days is flagged STALE
  - STALE exposure blocks PRIMARY in the gate
  - pipeline with an empty ledger abstains and publishes nothing
```

---

## DEFINITION OF DONE

- [ ] Schema migrated, all constraints enforced at DB level
- [ ] Entity resolver handles collision, corporate action, and subsidiary cases per tests
- [ ] Extraction pipeline runs end to end on 5 real annual reports and produces reviewable proposals with verbatim excerpts
- [ ] Verbatim containment check rejects fabricated excerpts (proven with an adversarial fixture)
- [ ] Review UI functional; approval is the only write path
- [ ] Coverage and staleness views live with metrics exported
- [ ] **Empty-ledger test passes: with no exposure data, the system publishes nothing rather than guessing**
- [ ] `DATA_GAPS.md` lists the ledger population work with scope and owner

---

## DO NOT

- Do not populate `company_exposure` with values from your own knowledge. Not for a demo. Not for a test outside `tests/fixtures/`. Not "temporarily".
- Do not default a missing `share_of_base` to a plausible number. Missing is missing.
- Do not let an LLM extractor write directly to the ledger under any circumstance.
- Do not build a React front-end for the review tool. Server-rendered, minimal, functional.
- Do not proceed to Phase 2 with an empty Tier 1 ledger — Phase 2's tests are meaningless without real rows.
