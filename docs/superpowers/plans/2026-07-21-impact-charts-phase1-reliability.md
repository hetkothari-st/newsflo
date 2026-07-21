# Impact Charts — Phase 1 (Reliability: determinism cache + kill the silent skip) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Same article → byte-identical analysis output on re-run (content-hash cache), and no ripple-hop failure is ever silently dropped (`CascadeGap` recording). Pure backend, no UI. This is Phase 1 of a larger 7-phase "10 impact charts" effort (source task: `C:\Users\ST269\Downloads\CLAUDE_TASK_impact_charts.md`); later phases (structured rulebook chains, edge generation, graph API, frontend graph model, chart mounting) are separate plans written after this one ships.

**Architecture:** A new `AnalysisCache` table keyed by a SHA-256 hash of `(title, content)` sits in front of the LLM call in `pipeline.py`'s `process_new_articles` loop (and is reused, via shared helpers, by the two standalone `reanalyze_*.py` scripts with a new `--force` flag to bypass it). A new `CascadeGap` table records any per-sector cascade-company lookup that still fails after one retry, instead of the current silent `logger.warning`-and-drop.

**Tech Stack:** Python, SQLAlchemy, pydantic, pytest.

## Global Constraints

- No Alembic in this repo. Brand-new tables need **no** `app/db.py::_ADDED_COLUMNS` entry — `Base.metadata.create_all(engine)` (called by `init_db()`) creates any missing table automatically. `_ADDED_COLUMNS` is only for adding a column to a table that already exists in production.
- Do not change `AlertCompany`'s or `Alert`'s existing columns, or `_build_alert_company`'s existing behavior — only additive changes.
- `analyze_article(client, title: str, content: str) -> AnalysisOutput` keeps this exact signature — do not change its call contract, only what `AnalysisOutput` carries.
- Existing tests must keep passing unmodified unless a test's own assumption is what's being extended (e.g. a fixture `AnalysisOutput(...)` construction that doesn't pass `gaps=` must still validate, since `gaps` defaults to `[]`).
- Verified current code this plan is grounded against (read directly, not assumed): `backend/app/pipeline.py` (`process_new_articles`, `_persist_alert`, `_find_reusable_alert`, `_build_alert_company`), `backend/app/models.py`, `backend/app/analysis/schemas.py` (`AnalysisOutput` currently has exactly `category`, `companies`, `event_type`), `backend/app/analysis/cascade.py` (`_identify_cascade_companies_per_sector`, `analyze_article`), `backend/reanalyze_recent.py`, `backend/reanalyze_cascade.py`.

---

### Task 1: `AnalysisCache` — content-hash determinism cache

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/pipeline.py`
- Modify: `backend/reanalyze_recent.py`
- Modify: `backend/reanalyze_cascade.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Produces: `AnalysisCache` model (`app.models`). `get_cached_analysis(session: Session, article: Article) -> AnalysisOutput | None`, `store_analysis_cache(session: Session, article: Article, analysis: AnalysisOutput) -> None`, `clear_analysis_cache(session: Session, article: Article) -> None` (all in `app.pipeline`) — three small helpers built around a shared `_content_hash(article: Article) -> str`, used by both `process_new_articles` and the two `reanalyze_*.py` scripts so the cache behaves identically everywhere it's consulted, not reimplemented three times.

- [ ] **Step 1: Add the `AnalysisCache` model**

In `backend/app/models.py`, add after the `Company`/`CompanyIndexMembership` classes (right before `class Article(Base):`, so it groups near the other simple lookup-style tables):

```python
class AnalysisCache(Base):
    """Determinism cache: the same article content (title + body) always
    produces the same analyze_article() output. Keyed by a content hash,
    not article id, so a republished/duplicate article with identical text
    hits the same cache row. See app.pipeline.get_cached_analysis."""
    __tablename__ = "analysis_cache"
    __table_args__ = (UniqueConstraint("content_hash", name="uq_analysis_cache_content_hash"),)

    id = Column(Integer, primary_key=True)
    content_hash = Column(String, nullable=False)
    output_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
```

- [ ] **Step 2: Write the failing tests**

Add to `backend/tests/test_pipeline.py`:

```python
def test_process_new_articles_analysis_cache_deterministic(db_session, monkeypatch):
    """Same content -> the LLM is called at most once; a second article
    with byte-identical (title, content) reuses the cached output instead
    of calling analyze_article again, even if analyze_article would have
    returned something different on a second call."""
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article1 = Article(source="test", url="https://example.com/a1", title="Crude oil spikes", content="Oil prices jump 5%.")
    article2 = Article(source="test", url="https://example.com/a2", title="Crude oil spikes", content="Oil prices jump 5%.")
    db_session.add_all([article1, article2])
    db_session.commit()

    call_count = {"n": 0}
    outputs = [
        AnalysisOutput(category="oil_gas", companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            key_points=["Crude eases"], time_horizon="Short-Term",
        )]),
        AnalysisOutput(category="other", companies=[]),  # DIFFERENT output -- must never be reached
    ]

    def fake_analyze(client, title, content):
        result = outputs[call_count["n"]]
        call_count["n"] += 1
        return result

    monkeypatch.setattr(pipeline_module, "analyze_article", fake_analyze)

    created = process_new_articles(db_session, claude_client=object())

    assert created == 2
    assert call_count["n"] == 1  # second article hit the cache, never called analyze_article again

    alerts = db_session.query(Alert).order_by(Alert.id).all()
    assert alerts[0].category == "oil_gas"
    assert alerts[1].category == "oil_gas"  # cached output, NOT the second scripted "other" output
    assert len(alerts[0].companies) == 1
    assert len(alerts[1].companies) == 1


def test_get_cached_analysis_returns_none_on_miss(db_session):
    article = Article(source="test", url="https://example.com/miss", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    assert pipeline_module.get_cached_analysis(db_session, article) is None


def test_store_then_get_cached_analysis_round_trips(db_session):
    article = Article(source="test", url="https://example.com/rt", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    output = AnalysisOutput(category="oil_gas", companies=[])
    pipeline_module.store_analysis_cache(db_session, article, output)
    db_session.commit()

    cached = pipeline_module.get_cached_analysis(db_session, article)
    assert cached is not None
    assert cached.category == "oil_gas"


def test_clear_analysis_cache_removes_the_row(db_session):
    article = Article(source="test", url="https://example.com/clr", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    pipeline_module.store_analysis_cache(db_session, article, AnalysisOutput(category="oil_gas", companies=[]))
    db_session.commit()
    assert pipeline_module.get_cached_analysis(db_session, article) is not None

    pipeline_module.clear_analysis_cache(db_session, article)
    db_session.commit()
    assert pipeline_module.get_cached_analysis(db_session, article) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run (from `backend/`): `python -m pytest tests/test_pipeline.py -k "cache" -v`
Expected: FAIL (`AttributeError: module 'app.pipeline' has no attribute 'get_cached_analysis'`, etc.)

- [ ] **Step 4: Implement the cache helpers in `app/pipeline.py`**

Add `import hashlib` to the top-of-file imports (after `import json`). Change the `app.models` import line to add `AnalysisCache`:

```python
from app.models import Alert, AlertCompany, AnalysisCache, Article, Company, utcnow
```

Add `AnalysisOutput` to the existing `app.analysis.schemas` import:

```python
from app.analysis.schemas import AnalysisOutput, CATEGORIES
```

Add these functions right after `article_text` (which already exists at line 51-52):

```python
def _content_hash(article: Article) -> str:
    return hashlib.sha256((article.title + "\n" + article_text(article)).encode()).hexdigest()


def get_cached_analysis(session: Session, article: Article) -> AnalysisOutput | None:
    """Look up a prior analyze_article() result for this EXACT article
    content (title + body), so a re-run (whether the live pipeline seeing
    a republished duplicate, or a one-off reanalyze_*.py script re-run)
    never has to spend a fresh LLM call to reproduce the same result --
    and always reproduces the SAME result, not a fresh one that may differ
    slightly (LLMs are not literally deterministic across calls)."""
    cached = session.query(AnalysisCache).filter_by(content_hash=_content_hash(article)).one_or_none()
    if cached is None:
        return None
    return AnalysisOutput.model_validate_json(cached.output_json)


def store_analysis_cache(session: Session, article: Article, analysis: AnalysisOutput) -> None:
    session.add(AnalysisCache(content_hash=_content_hash(article), output_json=analysis.model_dump_json()))


def clear_analysis_cache(session: Session, article: Article) -> None:
    """The only intentional way to force a fresh LLM call for content
    that's already cached -- used by reanalyze_*.py's --force flag."""
    session.query(AnalysisCache).filter_by(content_hash=_content_hash(article)).delete()
```

- [ ] **Step 5: Wire the cache into `process_new_articles`**

Replace this block in `process_new_articles` (currently lines 329-346):

```python
        analysis = None
        for attempt in range(2):  # try once, retry once
            try:
                analysis = analyze_article(claude_client, article.title, article_text(article))
                break
            except Exception:
                if attempt == 0:
                    time.sleep(throttle_seconds)
                continue
        time.sleep(throttle_seconds)  # stay under the provider's rate limit before the next article

        if analysis is None:
            article.status = "ANALYSIS_FAILED"
            session.commit()
            continue

        resolved = resolve_companies(session, analysis.companies)
        _persist_alert(session, article, analysis.category, resolved, event_type=analysis.event_type)
        alerts_created += 1
```

with:

```python
        analysis = get_cached_analysis(session, article)
        if analysis is None:
            for attempt in range(2):  # try once, retry once
                try:
                    analysis = analyze_article(claude_client, article.title, article_text(article))
                    break
                except Exception:
                    if attempt == 0:
                        time.sleep(throttle_seconds)
                    continue
            time.sleep(throttle_seconds)  # stay under the provider's rate limit before the next article

            if analysis is None:
                article.status = "ANALYSIS_FAILED"
                session.commit()
                continue

            store_analysis_cache(session, article, analysis)

        resolved = resolve_companies(session, analysis.companies)
        _persist_alert(session, article, analysis.category, resolved, event_type=analysis.event_type)
        alerts_created += 1
```

(A cache hit skips both the retry loop and the throttle sleep entirely — no LLM call was made, so there's nothing to rate-limit against.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS, including the 4 new tests and every pre-existing test in this file.

- [ ] **Step 7: Add `--force` to `reanalyze_recent.py`**

In `backend/reanalyze_recent.py`, update the import line:

```python
from app.pipeline import article_text
```

to:

```python
from app.pipeline import article_text, clear_analysis_cache, get_cached_analysis, store_analysis_cache
```

Replace the `main` function body's analysis call (currently):

```python
        article = alert.article
        print(f"\n=== Alert {alert.id}: {article.title} ===")
        try:
            result = analyze_article(client, article.title, article_text(article))
        except Exception as exc:
            print(f"  SKIPPED (analysis call failed: {exc})")
            continue
```

with:

```python
        article = alert.article
        print(f"\n=== Alert {alert.id}: {article.title} ===")
        if force:
            clear_analysis_cache(session, article)
        result = get_cached_analysis(session, article)
        if result is not None:
            print("  (using cached analysis -- pass --force for a fresh LLM call)")
        else:
            try:
                result = analyze_article(client, article.title, article_text(article))
            except Exception as exc:
                print(f"  SKIPPED (analysis call failed: {exc})")
                continue
            store_analysis_cache(session, article, result)
```

Update `main`'s signature and the `if __name__ == "__main__":` block:

```python
def main(limit: int, force: bool) -> None:
```

```python
if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    limit = int(args[0]) if args else 3
    main(limit, force)
```

Update the module docstring's `Usage` line to mention the flag:

```python
    .venv/Scripts/python reanalyze_recent.py [N] [--force]
```

- [ ] **Step 8: Add `--force` to `reanalyze_cascade.py`**

In `backend/reanalyze_cascade.py`, update the import line:

```python
from app.pipeline import _build_alert_company, article_text
```

to:

```python
from app.pipeline import _build_alert_company, article_text, clear_analysis_cache, get_cached_analysis, store_analysis_cache
```

Replace the analysis call (currently):

```python
        try:
            result = analyze_article(client, article.title, article_text(article))
        except Exception as exc:
            print(f"  SKIPPED (analysis call failed: {exc})")
            continue
```

with:

```python
        if force:
            clear_analysis_cache(session, article)
        result = get_cached_analysis(session, article)
        if result is not None:
            print("  (using cached analysis -- pass --force for a fresh LLM call)")
        else:
            try:
                result = analyze_article(client, article.title, article_text(article))
            except Exception as exc:
                print(f"  SKIPPED (analysis call failed: {exc})")
                continue
            store_analysis_cache(session, article, result)
```

Update `main`'s signature and the `if __name__ == "__main__":` block the same way as Step 7:

```python
def main(limit: int, force: bool) -> None:
```

```python
if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    limit = int(args[0]) if args else 5
    main(limit, force)
```

Update the module docstring's `Usage` line the same way as Step 7.

- [ ] **Step 9: Verify both scripts still import cleanly**

Run (from `backend/`):
```bash
python -c "import reanalyze_recent"
python -c "import reanalyze_cascade"
```
Expected: no output, exit code 0 (both are scripts, not packages, but this confirms no syntax/import errors — they're excluded from the test suite by convention, per their own docstrings).

- [ ] **Step 10: Run the full backend suite**

Run: `python -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 11: Commit**

```bash
git add backend/app/models.py backend/app/pipeline.py backend/reanalyze_recent.py backend/reanalyze_cascade.py backend/tests/test_pipeline.py
git commit -m "feat: add AnalysisCache determinism cache, wire into pipeline + reanalyze scripts"
```

---

### Task 2: `CascadeGap` — record failed cascade hops instead of silently dropping them

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/analysis/schemas.py`
- Modify: `backend/app/analysis/cascade.py`
- Modify: `backend/app/pipeline.py`
- Test: `backend/tests/test_cascade.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: nothing from Task 1 directly (independent change), but lands in the same `analyze_article`/`_persist_alert` call chain Task 1 touched — apply Task 1 first to avoid a merge conflict on `pipeline.py`.
- Produces: `CascadeGap` model (`app.models`). `_identify_cascade_companies_per_sector(...) -> tuple[list[CompanyMention], list[dict]]` (signature change: now returns `(mentions, gaps)`, was `mentions` alone). `AnalysisOutput.gaps: list[dict] = []` (new field). `_persist_alert(..., gaps: list[dict] | None = None)` (new optional param, appended after the existing `event_type` param).

- [ ] **Step 1: Add the `CascadeGap` model**

In `backend/app/models.py`, add after the `AlertCompany` class (right before `class CalibrationSample(Base):`):

```python
class CascadeGap(Base):
    """A cascade-company lookup (app.analysis.cascade) that failed even
    after a retry -- recorded instead of silently dropped, so the user can
    always see "this ripple path was considered and could not be
    resolved" rather than a difference between runs that looks like a
    missing feature. See app.analysis.cascade._identify_cascade_companies_per_sector."""
    __tablename__ = "cascade_gaps"

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    sector = Column(String, nullable=False)
    impact_level = Column(String, nullable=False)
    # The per-sector cascade call chains from a POOL of parent companies,
    # not one -- null here, not misleadingly picking just the first parent.
    # See the comment at the call site in _identify_cascade_companies_per_sector.
    parent_ticker = Column(String, nullable=True)
    attempts = Column(Integer, nullable=False)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    alert = relationship("Alert")
```

- [ ] **Step 2: Add `gaps` to `AnalysisOutput`**

In `backend/app/analysis/schemas.py`, change `AnalysisOutput` (currently lines 130-137):

```python
class AnalysisOutput(BaseModel):
    category: str
    companies: list[CompanyMention]
    # Article-level event classification, parallel to `category`. Optional
    # at the pydantic layer (defaults to None) for backward compatibility;
    # the tool schema sent to the LLM (RECORD_ANALYSIS_TOOL) still requires
    # it on every real call.
    event_type: Optional[str] = None
```

to:

```python
class AnalysisOutput(BaseModel):
    category: str
    companies: list[CompanyMention]
    # Article-level event classification, parallel to `category`. Optional
    # at the pydantic layer (defaults to None) for backward compatibility;
    # the tool schema sent to the LLM (RECORD_ANALYSIS_TOOL) still requires
    # it on every real call.
    event_type: Optional[str] = None
    # Cascade sectors whose company lookup failed even after a retry (see
    # app.analysis.cascade._identify_cascade_companies_per_sector). Each
    # dict has keys: sector, impact_level, parent_ticker, attempts,
    # last_error. Defaults to [] so every existing caller (older tests,
    # the dedup-reuse path in pipeline.py) still validates without change.
    gaps: list[dict] = []
```

- [ ] **Step 3: Write the failing cascade tests**

Add to `backend/tests/test_cascade.py`:

```python
def test_identify_cascade_companies_per_sector_retries_then_records_gap():
    sectors = [
        SectorFinding(sector="banking", direction="bullish", mechanism="m1", parent_sector="oil_gas"),
        SectorFinding(sector="auto", direction="bullish", mechanism="m2", parent_sector="oil_gas"),
    ]
    parent_pool = [CompanyMention(
        name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
    )]

    call_log = []

    class FlakyThenGoodClient:
        @property
        def chat(self):
            return SimpleNamespace(completions=self)

        def create(self, **kwargs):
            # Which sector this call is for isn't directly inspectable from
            # kwargs (the tool schema doesn't echo it back); key off call
            # order instead -- sectors are processed in list order (banking,
            # then auto), and each sector gets up to 2 attempts, so calls
            # 1-2 are banking's two attempts (both fail) and call 3 is
            # auto's first attempt (succeeds).
            call_log.append(kwargs["tool_choice"]["function"]["name"])
            if len(call_log) <= 2:
                raise RuntimeError("transient failure")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                tool_calls=[FakeToolCall("record_sector_companies", {"sector_companies": [
                    {"sector": "auto", "companies": [{
                        "name": "Maruti Suzuki", "ticker": "MARUTI.NS", "direction": "bullish",
                        "magnitude_low": 1.0, "magnitude_high": 2.0, "rationale": "r",
                        "key_points": [], "time_horizon": "Short-Term", "reasons": [],
                        "evidence_refs": [], "risks": [], "assumptions": [], "unknowns": [],
                        "alternative_hypothesis": "none", "parent_ticker": "RELIANCE.NS",
                    }]},
                ]}))],
            )))

    mentions, gaps = _identify_cascade_companies_per_sector(
        FlakyThenGoodClient(), facts="f", sectors=sectors, impact_level="indirect_l1", parent_pool=parent_pool,
    )

    assert len(gaps) == 1
    assert gaps[0]["sector"] == "banking"
    assert gaps[0]["impact_level"] == "indirect_l1"
    assert gaps[0]["attempts"] == 2
    assert gaps[0]["last_error"]
    assert len(mentions) == 1
    assert mentions[0].ticker == "MARUTI.NS"  # the "auto" sector still succeeded
```

- [ ] **Step 4: Run tests to verify they fail**

Run (from `backend/`): `python -m pytest tests/test_cascade.py -k gap -v`
Expected: FAIL — `_identify_cascade_companies_per_sector` currently returns a bare list, not a `(mentions, gaps)` tuple, and never retries.

- [ ] **Step 5: Implement retry + gap recording in `cascade.py`**

In `backend/app/analysis/cascade.py`, replace `_identify_cascade_companies_per_sector` (currently lines 558-581) with:

```python
def _identify_cascade_companies_per_sector(
    client, facts: str, sectors: list[SectorFinding], impact_level: str, parent_pool: list[CompanyMention],
) -> tuple[list[CompanyMention], list[dict]]:
    """Calls _identify_companies ONCE PER SECTOR rather than bundling every
    cascade sector into one call. Confirmed in production: bundling 5-7
    cascade sectors (each company requires a long rationale/key_points/
    reasons/evidence_refs/risks/assumptions/unknowns block, easily 500+
    tokens) into a single max_tokens=8192 tool call made the model return a
    degenerate empty response (no exception, just `{}` -- silently zero
    companies) even though every sector had a genuine, findable answer. The
    SAME sectors, called one at a time, reliably produced rich, correct,
    multi-company results. Direct/primary companies (stage 3) do not use
    this -- that stage empirically has few enough sectors (the article's
    own direct subject, not a wide cascade fan-out) that bundling is fine.

    A failure on one sector is retried once (2 attempts total) before being
    recorded as a gap dict in the returned gaps list -- never silently
    dropped, so a genuine transient failure (rate limit, malformed
    response) is distinguishable from "this sector genuinely has no
    cascade companies" (which returns normally with an empty list, not a
    gap). A gap on one sector does not lose another sector's results.
    """
    mentions: list[CompanyMention] = []
    gaps: list[dict] = []
    for sector in sectors:
        last_error: str | None = None
        succeeded = False
        for attempt in range(2):  # try once, retry once
            try:
                mentions.extend(_identify_companies(client, facts, [sector], impact_level=impact_level, parent_pool=parent_pool))
                succeeded = True
                break
            except Exception as exc:
                last_error = str(exc)
        if not succeeded:
            logger.warning("cascade company lookup for sector %r failed after retry, recording gap: %s", sector.sector, last_error)
            gaps.append({
                "sector": sector.sector,
                "impact_level": impact_level,
                # parent_pool is a POOL of companies this sector's lookup
                # chains from, not a single one -- there is no single
                # correct parent_ticker to attribute a whole-sector
                # failure to, so this is intentionally left None rather
                # than picking (and thereby misrepresenting) just the
                # first entry.
                "parent_ticker": None,
                "attempts": 2,
                "last_error": last_error,
            })
    return mentions, gaps
```

- [ ] **Step 6: Update `analyze_article`'s two call sites + return shape**

In `backend/app/analysis/cascade.py`, replace `analyze_article` (currently lines 584-643) with:

```python
def analyze_article(client, title: str, content: str) -> AnalysisOutput:
    """Runs the sector-cascade chain (see module docstring for why the call
    count now scales with cascade sector count) and composes the result into the
    same AnalysisOutput shape app.pipeline.py already consumes. Failure
    handling (see docs/superpowers/specs/2026-07-20-sector-cascade-
    reasoning-design.md): a facts (stage 1) or primary-sector (stage 2)
    failure propagates, failing the whole article -- identical to the old
    single-call analyze_article's behavior. A failure at any later stage
    truncates the pipeline there: everything produced by stages that
    already succeeded is still returned. Per-sector cascade-company
    failures (stages 5/7) are retried and, if still unresolved, recorded
    as gaps rather than truncating the pipeline (see
    _identify_cascade_companies_per_sector).
    """
    facts_result = _extract_facts(client, title, content)
    primary_sectors = _identify_sectors(client, facts_result.facts, parent_sectors=None)

    all_companies: list = []
    all_gaps: list[dict] = []
    if not primary_sectors:
        return AnalysisOutput(
            category=facts_result.category, event_type=facts_result.event_type,
            companies=all_companies, gaps=all_gaps,
        )

    try:
        primary_companies = _identify_companies(
            client, facts_result.facts, primary_sectors, impact_level="direct", parent_pool=None,
        )
    except Exception as exc:
        logger.warning("cascade stage 3 (primary companies) failed, truncating: %s", exc)
        primary_companies = []
    all_companies.extend(primary_companies)

    l1_parent_tickers_present = [c for c in primary_companies if c.ticker]
    if l1_parent_tickers_present:
        try:
            l1_sectors = _identify_sectors(client, facts_result.facts, parent_sectors=primary_sectors)
        except Exception as exc:
            logger.warning("cascade stage 4 (L1 cascade sectors) failed, truncating: %s", exc)
            l1_sectors = []
        if l1_sectors:
            l1_companies, l1_gaps = _identify_cascade_companies_per_sector(
                client, facts_result.facts, l1_sectors, impact_level="indirect_l1",
                parent_pool=l1_parent_tickers_present,
            )
        else:
            l1_companies, l1_gaps = [], []
        all_companies.extend(l1_companies)
        all_gaps.extend(l1_gaps)

        l2_parent_tickers_present = [c for c in l1_companies if c.ticker]
        if l1_sectors and l2_parent_tickers_present:
            try:
                l2_sectors = _identify_sectors(client, facts_result.facts, parent_sectors=l1_sectors)
            except Exception as exc:
                logger.warning("cascade stage 6 (L2 cascade sectors) failed, truncating: %s", exc)
                l2_sectors = []
            if l2_sectors:
                l2_companies, l2_gaps = _identify_cascade_companies_per_sector(
                    client, facts_result.facts, l2_sectors, impact_level="indirect_l2",
                    parent_pool=l2_parent_tickers_present,
                )
            else:
                l2_companies, l2_gaps = [], []
            all_companies.extend(l2_companies)
            all_gaps.extend(l2_gaps)

    return AnalysisOutput(
        category=facts_result.category, event_type=facts_result.event_type,
        companies=all_companies, gaps=all_gaps,
    )
```

- [ ] **Step 7: Fix two pre-existing tests that call `_identify_cascade_companies_per_sector` directly**

These two tests in `backend/tests/test_cascade.py` break under the new signature -- one merely needs unpacking, the other has a real behavioral trap: with the old code, `PerSectorScriptedClient`'s failing sector consumed exactly one scripted response (the `ValueError`); with the new retry-twice logic, that sector now makes a SECOND call on retry, which would silently pop and consume the NEXT sector's scripted success response instead of failing again -- masking the sector as "succeeded" with the wrong sector's data, then leaving the real next sector's call with no scripted response left (`IndexError`). Fix by scripting the failure twice.

Replace `test_identify_cascade_companies_per_sector_makes_one_call_per_sector` (currently lines 330-349):

```python
def test_identify_cascade_companies_per_sector_makes_one_call_per_sector():
    banking = SectorFinding(sector="banking", direction="bearish", mechanism="m", parent_sector="oil_gas")
    auto = SectorFinding(sector="auto", direction="bearish", mechanism="m", parent_sector="oil_gas")
    parent_pool = [CompanyMention(
        name="Reliance", ticker="RELIANCE.NS", is_direct=True, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        impact_level="direct",
    )]
    client = PerSectorScriptedClient([
        {"sector_companies": [{"sector": "banking", "companies": [_full_company("HDFC Bank", "HDFCBANK.NS", parent_ticker="RELIANCE.NS")]}]},
        {"sector_companies": [{"sector": "auto", "companies": [_full_company("Maruti", "MARUTI.NS", parent_ticker="RELIANCE.NS")]}]},
    ])

    result, gaps = _identify_cascade_companies_per_sector(
        client, facts="f", sectors=[banking, auto], impact_level="indirect_l1", parent_pool=parent_pool,
    )

    assert client.calls == ["record_sector_companies", "record_sector_companies"]
    assert {c.ticker for c in result} == {"HDFCBANK.NS", "MARUTI.NS"}
    assert all(c.impact_level == "indirect_l1" for c in result)
    assert gaps == []
```

Replace `test_identify_cascade_companies_per_sector_skips_a_failing_sector_not_the_others` (currently lines 352-369):

```python
def test_identify_cascade_companies_per_sector_skips_a_failing_sector_not_the_others():
    banking = SectorFinding(sector="banking", direction="bearish", mechanism="m", parent_sector="oil_gas")
    auto = SectorFinding(sector="auto", direction="bearish", mechanism="m", parent_sector="oil_gas")
    parent_pool = [CompanyMention(
        name="Reliance", ticker="RELIANCE.NS", is_direct=True, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        impact_level="direct",
    )]
    client = PerSectorScriptedClient([
        ValueError("boom"),
        ValueError("boom again"),  # banking's retry attempt also fails
        {"sector_companies": [{"sector": "auto", "companies": [_full_company("Maruti", "MARUTI.NS", parent_ticker="RELIANCE.NS")]}]},
    ])

    result, gaps = _identify_cascade_companies_per_sector(
        client, facts="f", sectors=[banking, auto], impact_level="indirect_l1", parent_pool=parent_pool,
    )

    assert [c.ticker for c in result] == ["MARUTI.NS"]
    assert len(gaps) == 1
    assert gaps[0]["sector"] == "banking"
    assert gaps[0]["attempts"] == 2
```

- [ ] **Step 8: Run cascade tests to verify they pass**

Run: `python -m pytest tests/test_cascade.py -v`
Expected: PASS, including the new gap test, the two fixed tests, and every other pre-existing test in this file.

- [ ] **Step 9: Write the failing `_persist_alert` gap-persistence test**

Add to `backend/tests/test_pipeline.py`:

```python
def test_persist_alert_writes_cascade_gap_rows(db_session):
    article = Article(source="test", url="https://example.com/gap", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    alert = pipeline_module._persist_alert(
        db_session, article, category="oil_gas", entries=[], event_type="crude_oil",
        gaps=[{"sector": "banking", "impact_level": "indirect_l1", "parent_ticker": None, "attempts": 2, "last_error": "boom"}],
    )

    gap_rows = db_session.query(CascadeGap).filter_by(alert_id=alert.id).all()
    assert len(gap_rows) == 1
    assert gap_rows[0].sector == "banking"
    assert gap_rows[0].impact_level == "indirect_l1"
    assert gap_rows[0].attempts == 2
    assert gap_rows[0].last_error == "boom"


def test_persist_alert_with_no_gaps_writes_no_gap_rows(db_session):
    article = Article(source="test", url="https://example.com/nogap", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    alert = pipeline_module._persist_alert(db_session, article, category="oil_gas", entries=[], event_type="crude_oil")

    assert db_session.query(CascadeGap).filter_by(alert_id=alert.id).count() == 0
```

Add `CascadeGap` to this test file's `app.models` import.

- [ ] **Step 10: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline.py -k gap -v`
Expected: FAIL — `_persist_alert` doesn't accept a `gaps` kwarg yet.

- [ ] **Step 11: Wire gap persistence into `_persist_alert` and its caller**

In `backend/app/pipeline.py`, add `CascadeGap` to the `app.models` import (already updated in Task 1 to include `AnalysisCache` — extend the same line):

```python
from app.models import Alert, AlertCompany, AnalysisCache, Article, CascadeGap, Company, utcnow
```

Change `_persist_alert`'s signature (currently `session: Session, article: Article, category: str, entries: list[dict], event_type: str | None = None`) to:

```python
def _persist_alert(
    session: Session, article: Article, category: str, entries: list[dict], event_type: str | None = None,
    gaps: list[dict] | None = None,
) -> Alert:
```

Add gap-row creation right after the existing `for entry in entries:` loop (currently lines 268-269 -- keep that loop exactly as-is, add this immediately after it):

```python
    for gap in (gaps or []):
        session.add(CascadeGap(
            alert_id=alert.id, sector=gap["sector"], impact_level=gap["impact_level"],
            parent_ticker=gap.get("parent_ticker"), attempts=gap["attempts"], last_error=gap.get("last_error"),
        ))
```

In `process_new_articles`, update the fresh-analysis `_persist_alert` call site (the one inside the `analysis = get_cached_analysis(...)` block from Task 1, currently `_persist_alert(session, article, analysis.category, resolved, event_type=analysis.event_type)`) to:

```python
        _persist_alert(session, article, analysis.category, resolved, event_type=analysis.event_type, gaps=analysis.gaps)
```

The dedup-reuse call site (`_persist_alert(session, article, reusable_alert.category, entries, event_type=reusable_alert.event_type)`, inside the `_find_reusable_alert` branch) is left unchanged — that path never calls `analyze_article`, so there is nothing to have gaps about; `gaps` defaults to `None`.

- [ ] **Step 12: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py tests/test_cascade.py -v`
Expected: PASS, all tests including the new gap tests.

- [ ] **Step 13: Run the full backend suite**

Run: `python -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 14: Commit**

```bash
git add backend/app/models.py backend/app/analysis/schemas.py backend/app/analysis/cascade.py backend/app/pipeline.py backend/tests/test_cascade.py backend/tests/test_pipeline.py
git commit -m "feat: record failed cascade-company lookups as CascadeGap instead of silently dropping them"
```

---

## Explicitly out of scope (this plan)

Everything in Phases 2-7 of the source task doc (`CLAUDE_TASK_impact_charts.md`): structured `CHAINS` rulebook data, `ImpactEdge` generation, the `graph` API block, the frontend graph model/selectors, mounting the 6 grouping charts, and building the 4 new graph charts. Each becomes its own plan, written and executed after this one ships and is verified, per that doc's own phase-gated structure.

## Definition of done (this plan only)

1. Re-analyzing the same `(title, content)` twice never calls the LLM a second time and produces byte-identical `companies` (Task 1's test proves this with a scripted client that would return DIFFERENT output on a second call).
2. A cascade-company lookup that fails twice in a row for one sector produces a `CascadeGap` row on the resulting alert, and does not affect other sectors' results (Task 2's tests).
3. `reanalyze_recent.py --force` and `reanalyze_cascade.py --force` both bypass the cache for a fresh LLM call; without `--force`, a re-run of either script against unchanged content reuses the cached analysis.
4. Full backend test suite green.
