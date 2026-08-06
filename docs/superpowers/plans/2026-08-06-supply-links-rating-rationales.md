# Supply Links from Rating Rationales Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract named supplier/customer relationships and business summaries from credit-rating-agency rationale PDFs (discovered via BSE's announcements API), store them with verbatim-quote provenance, serve them to pipeline prompts as a grounding layer, and keep them fresh with converging daily jobs.

**Architecture:** New package `app/companies/supply_links/` mirroring `descriptions/` — `snapshot.py` (paths/resume sets), `fetchers.py` (network only), `extract.py` (pure: PDF text + LLM-as-reader + evidence gate), `loader.py` (DB only). New `supply_links` table is the source of truth; `supply_chain_*_json` become derived caches; `business_desc` fills only where NULL. Cascade's company-identification prompt gains one capped KNOWN-RELATIONSHIPS block.

**Tech Stack:** Python 3.12 / SQLAlchemy 2.0.35 / pytest; `pypdf` (new dep); existing `build_client` LLM infra; no Alembic (`_ADDED_COLUMNS` + `create_all`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-06-supply-links-rating-rationales-design.md`.
- **No auto-attribution (user-locked):** no code path creates an AlertCompany or ImpactEdge from a stored supply link — links reach the LLM prompt and nothing else. Task 6 carries the named test.
- Evidence gate: a supplier/customer entry is stored ONLY if its `evidence` quote appears in the PDF text under whitespace-normalized substring match. No quote, no row.
- Caps: max 3 suppliers + 3 customers per document; `business_summary` must pass `validate_no_advice_language` (from `app.reasoning.compliance`).
- Counterparty resolution uses `app.companies.matching.matcher.resolve(session, ticker=None, name=<counterparty_name>)` ONLY — never fuzzy, never substring.
- Wikipedia descriptions never overwritten; nothing ever blanked; replace-on-newer / keep-on-older-empty semantics per spec §5.1.
- Prompt block: only when event companies have links; max 8 link lines; max 700 chars; when no links the prompt is byte-identical to today.
- Fetchers RAISE on master-index failure, degrade per-document; snapshots under `data/ratings/` on the volume; resumable; time-budgeted.
- Config over literals: `SUPPLY_LINK_MAX_PER_RELATION = 3`, `SUPPLY_PROMPT_MAX_LINES = 8`, `SUPPLY_PROMPT_MAX_CHARS = 700` in `app/config.py`.
- BSE endpoints verified live 2026-08-06: `AnnSubCategoryGetData/w` works with the universe fetchers' browser headers; attachments live at `https://www.bseindia.com/xml-data/corpfiling/AttachLive/{ATTACHMENTNAME}`. The exact `strCat` value for rating actions is pinned by Task 1's probe (the literal `"Credit Rating"` returned 0 rows; `"Corp. Action"` returned data — the category list endpoint or subcategory param resolves it).

## File Structure

- `backend/app/companies/supply_links/{__init__,snapshot,fetchers,extract,loader}.py` (create)
- `backend/app/models.py` — `SupplyLink` model (modify)
- `backend/app/config.py` — three constants (modify)
- `backend/requirements.txt` — `pypdf` (modify)
- `backend/app/analysis/cascade.py` — KNOWN-RELATIONSHIPS block (modify)
- `backend/app/scheduler.py` — two jobs (modify)
- `backend/backfill_supply_links.py` — bootstrap runbook (create)
- `backend/tests/test_supply_links.py`, `backend/tests/fixtures/ratings/` (create)

---

### Task 1: Discovery probe — pin the announcements query and record fixtures

**Files:**
- Create: `backend/tests/fixtures/ratings/README.md`, `backend/tests/fixtures/ratings/announcements_page.json`, `backend/tests/fixtures/ratings/rationale_sample.pdf`
- Create: `backend/app/companies/supply_links/__init__.py` (package docstring only, from spec §1)

This task is INVESTIGATION with recorded artifacts — no production code. Work interactively with `python -c` against the live API using `app.companies.universe.fetchers.fetch_bytes` (it already carries the browser headers BSE requires).

- [ ] **Step 1: Pin the category.** Fetch `https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=<CAT>&strPrevDate=20260601&strScrip=&strSearch=P&strToDate=20260806&strType=C&subcategory=<SUB>` for candidate values. Start by fetching the category list itself: `https://api.bseindia.com/BseIndiaAPI/api/ddlcategorys/w` (and, if that 404s, `AnnGetCat/w`); look for the rating-related category exactly as BSE spells it. A correct query returns rows whose `NEWSSUB` mentions a rating agency (CRISIL/ICRA/CARE/India Ratings/Acuite/Infomerics). Record the WORKING (strCat, subcategory) pair in the fixtures README.
- [ ] **Step 2: Save one real announcements page** (the working query's JSON, verbatim) as `announcements_page.json`.
- [ ] **Step 3: Fetch one real rationale PDF** from `https://www.bseindia.com/xml-data/corpfiling/AttachLive/{ATTACHMENTNAME}` for a row whose subject names a rating agency. Confirm `pypdf` extracts text from it (`pip install pypdf` if absent; it goes into requirements in Task 3). Save as `rationale_sample.pdf` ONLY if under 500 KB (pick a smaller one otherwise). Record in the README: which company, which agency, the URL, and 2-3 verbatim sentences from it that name a counterparty or describe the business (these seed Task 3's evidence-gate tests).
- [ ] **Step 4: Write the README** — working query params, attachment URL pattern, observed row keys (`SCRIP_CD`, `SLONGNAME`, `NEWSSUB`, `ATTACHMENTNAME`, `NEWS_DT`), any surprises (rate limits, empty attachments, non-PDF attachments), and the fixture provenance.
- [ ] **Step 5: Commit**

```bash
git add backend/tests/fixtures/ratings backend/app/companies/supply_links/__init__.py
git commit -m "chore: pin BSE rating-announcements query, record live fixtures"
```

If NO category/subcategory combination yields rating announcements with attachments, STOP and report BLOCKED with what was tried — the spec's fallback (NSE index) needs a design amendment, not improvisation.

---

### Task 2: Schema + config — `SupplyLink`, constants

**Files:**
- Modify: `backend/app/models.py` (after `CompanyAlias`)
- Modify: `backend/app/config.py` (after the EVENT_VOL constants)
- Test: `backend/tests/test_supply_links.py` (create)

**Interfaces:**
- Produces: `app.models.SupplyLink` with columns `id, company_id, relation, counterparty_name, counterparty_company_id, evidence, source_url, source_agency, as_of, extracted_at`; config `SUPPLY_LINK_MAX_PER_RELATION = 3`, `SUPPLY_PROMPT_MAX_LINES = 8`, `SUPPLY_PROMPT_MAX_CHARS = 700`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_supply_links.py
"""Supply links from rating rationales.

Spec: docs/superpowers/specs/2026-08-06-supply-links-rating-rationales-
design.md. The load-bearing tests are the refusals: no evidence quote ->
no row; no exact name match -> NULL counterparty_company_id; no stored
links -> byte-identical prompt; LLM returns nothing -> zero ripple rows.
"""
from datetime import date, datetime, timezone

from app import config
from app.models import Company, SupplyLink

AS_OF = date(2026, 8, 6)


def _company(session, ticker, name, sector="other"):
    company = Company(ticker=ticker, name=name, sector=sector, index_tier="OTHER")
    session.add(company)
    session.flush()
    return company


def test_supply_link_table_exists(db_session):
    company = _company(db_session, "RELIANCE.NS", "Reliance Industries")
    db_session.add(SupplyLink(
        company_id=company.id, relation="CUSTOMER",
        counterparty_name="Indian Oil Corporation", counterparty_company_id=None,
        evidence="derives a material share of revenue from Indian Oil Corporation",
        source_url="https://www.bseindia.com/xml-data/corpfiling/AttachLive/x.pdf",
        source_agency="CRISIL", as_of=AS_OF,
        extracted_at=datetime.now(timezone.utc),
    ))
    db_session.commit()
    got = db_session.query(SupplyLink).one()
    assert got.relation == "CUSTOMER"
    assert got.counterparty_company_id is None


def test_supply_caps_live_in_config():
    assert config.SUPPLY_LINK_MAX_PER_RELATION == 3
    assert config.SUPPLY_PROMPT_MAX_LINES == 8
    assert config.SUPPLY_PROMPT_MAX_CHARS == 700
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_supply_links.py -q`
Expected: FAIL — `ImportError: cannot import name 'SupplyLink'`

- [ ] **Step 3: Implement**

`backend/app/models.py`, after `class CompanyAlias`:

```python
class SupplyLink(Base):
    """One sourced counterparty relationship per row (docs/superpowers/
    specs/2026-08-06-supply-links-rating-rationales-design.md §5.1),
    extracted from a rating agency's public rationale document. `evidence`
    is the verbatim quote that survived the extraction gate -- a row
    without a provable quote is never written. counterparty_company_id is
    resolved via the EXACT matching ladder only; NULL means "no exact
    match", never "guessed". These rows feed pipeline prompts as grounding;
    they NEVER create AlertCompany/ImpactEdge rows themselves (user-locked
    constraint, tested by name in tests/test_supply_links.py).
    """
    __tablename__ = "supply_links"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "relation", "counterparty_name",
            name="uq_supply_link_company_relation_counterparty",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    relation = Column(String, nullable=False)  # SUPPLIER | CUSTOMER
    counterparty_name = Column(String, nullable=False)
    counterparty_company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    evidence = Column(Text, nullable=False)
    source_url = Column(String, nullable=False)
    source_agency = Column(String, nullable=False)
    as_of = Column(Date, nullable=False)
    extracted_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
```

`backend/app/config.py`, after the EVENT_VOL constants:

```python
# -- Supply links from rating rationales (spec 2026-08-06) ---------------
# Per-document caps: beyond three names a rationale is listing the sector,
# not counterparties (and the user asked for brief).
SUPPLY_LINK_MAX_PER_RELATION = 3
# Prompt-block budget for the KNOWN RELATIONSHIPS grounding section. The
# per-candidate description block that once measured 60.8k chars across
# 360 candidates broke both models' TPM ceilings -- this block is capped
# hard and covers event companies only.
SUPPLY_PROMPT_MAX_LINES = 8
SUPPLY_PROMPT_MAX_CHARS = 700
```

New table → `create_all` covers it; no `_ADDED_COLUMNS` entry.

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_supply_links.py -q`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/config.py backend/tests/test_supply_links.py
git commit -m "feat: supply_links schema + prompt/extraction caps"
```

---

### Task 3: Snapshot + fetchers — announcements index and rationale documents

**Files:**
- Create: `backend/app/companies/supply_links/snapshot.py`, `backend/app/companies/supply_links/fetchers.py`
- Modify: `backend/requirements.txt` (add `pypdf`)
- Test: `backend/tests/test_supply_links.py` (append)

**Interfaces:**
- Consumes: Task 1's fixtures + pinned query params (READ THE FIXTURES README FIRST — it holds the working strCat/subcategory).
- Produces:
  - `snapshot.DEFAULT_ROOT = "data/ratings"`; `snapshot.index_path(root, day) -> Path` (`<root>/index/<iso>.json`); `snapshot.doc_path(root, scrip_code, url) -> Path` (`<root>/docs/<scrip_code>/<sha16(url)>.pdf`); `snapshot.fetched_doc_urls(root) -> set[str]` via a sidecar `<sha16>.url` file written next to each pdf; `snapshot.pending_docs(root) -> list[Path]` (pdfs without a `.done` marker); `snapshot.mark_extracted(pdf_path)` (writes `.done`).
  - `fetchers.fetch_announcements(root, day, from_date, to_date, opener=None) -> list[dict]` — pages through the pinned query, writes the combined rows to `index_path`, returns rows. RAISES on failure (master index).
  - `fetchers.parse_announcements(rows) -> list[dict]` — pure; keeps rows whose `NEWSSUB` names a known agency (case-insensitive: CRISIL, ICRA, CARE, IND-RA, India Ratings, ACUITE, Acuité, INFOMERICS, BRICKWORK); returns `{scrip_code, company_name, agency, news_date, attachment_url}` dicts; rows without an attachment are dropped.
  - `fetchers.fetch_documents(root, targets, opener=None, sleep=None, throttle_seconds=1.0, time_budget_seconds=None, clock=None) -> dict` — per-doc degrade (`failed` list), resumable via `fetched_doc_urls`, budget/`exhausted`/`remaining` semantics copied from `universe.fetchers.fetch_bse_details`. Alongside each fetched pdf it writes TWO sidecars: `<sha16>.url` (the source URL) and `<sha16>.meta.json` (`{scrip_code, company_name, agency, news_date}` from the parsed announcement row) -- Task 7's extraction drain reads both.

- [ ] **Step 1: Write the failing tests** (append; fake openers, no network)

```python
import json
from pathlib import Path

from app.companies.supply_links import fetchers, snapshot

FIXTURES = Path(__file__).parent / "fixtures" / "ratings"


def test_parse_announcements_keeps_only_agency_rows_with_attachments():
    rows = [
        {"SCRIP_CD": "500325", "SLONGNAME": "Reliance", "NEWS_DT": "2026-08-01T10:00:00",
         "NEWSSUB": "Reliance - CRISIL Ratings reaffirms AAA", "ATTACHMENTNAME": "abc.pdf"},
        {"SCRIP_CD": "500002", "SLONGNAME": "ABB", "NEWS_DT": "2026-08-01T10:00:00",
         "NEWSSUB": "Board meeting intimation", "ATTACHMENTNAME": "def.pdf"},
        {"SCRIP_CD": "500003", "SLONGNAME": "NoAttach", "NEWS_DT": "2026-08-01T10:00:00",
         "NEWSSUB": "ICRA assigns rating", "ATTACHMENTNAME": ""},
    ]
    parsed = fetchers.parse_announcements(rows)
    assert len(parsed) == 1
    assert parsed[0]["scrip_code"] == "500325"
    assert parsed[0]["agency"] == "CRISIL"
    assert parsed[0]["attachment_url"].endswith("/AttachLive/abc.pdf")


def test_parse_announcements_handles_the_real_fixture_page():
    rows = json.loads((FIXTURES / "announcements_page.json").read_text(encoding="utf-8"))["Table"]
    parsed = fetchers.parse_announcements(rows)
    # The fixture was chosen because it contains at least one agency row.
    assert parsed, "fixture page must yield at least one rating rationale"
    assert all(p["attachment_url"] for p in parsed)


def test_fetch_documents_resumes_and_respects_budget(tmp_path):
    targets = [
        {"scrip_code": "500325", "attachment_url": f"https://x/AttachLive/{i}.pdf"}
        for i in range(5)
    ]
    calls = []

    def opener(url, timeout=60):
        calls.append(url)
        return b"%PDF-1.4 fake"

    r1 = fetchers.fetch_documents(str(tmp_path), targets[:2], opener=opener,
                                  sleep=lambda _s: None, throttle_seconds=0)
    assert r1["fetched"] == 2
    r2 = fetchers.fetch_documents(str(tmp_path), targets, opener=opener,
                                  sleep=lambda _s: None, throttle_seconds=0)
    assert r2["skipped"] == 2 and r2["fetched"] == 3
    assert len(calls) == 5, "already-fetched docs must not be re-fetched"


def test_fetch_documents_stops_cleanly_on_budget(tmp_path):
    ticks = iter(range(100))
    targets = [{"scrip_code": "1", "attachment_url": f"https://x/AttachLive/{i}.pdf"}
               for i in range(10)]
    result = fetchers.fetch_documents(
        str(tmp_path), targets, opener=lambda u, timeout=60: b"%PDF",
        sleep=lambda _s: None, throttle_seconds=0,
        time_budget_seconds=3, clock=lambda: next(ticks),
    )
    assert result["exhausted"] is True
    assert 0 < result["fetched"] < 10


def test_pending_docs_and_mark_extracted(tmp_path):
    root = str(tmp_path)
    path = snapshot.doc_path(root, "500325", "https://x/AttachLive/a.pdf")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF")
    assert path in snapshot.pending_docs(root)
    snapshot.mark_extracted(path)
    assert path not in snapshot.pending_docs(root)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_supply_links.py -q`
Expected: new tests FAIL — module not found

- [ ] **Step 3: Implement**

`snapshot.py` — pure paths per the Produces block. `doc_path` uses `hashlib.sha256(url.encode()).hexdigest()[:16]`; alongside each fetched pdf, `fetchers` writes `<sha16>.url` (the source URL, for provenance + resume) and extraction writes `<sha16>.done`. `pending_docs` = `*.pdf` without matching `.done`.

`fetchers.py` — reuse `from app.companies.universe.fetchers import fetch_bytes, BROWSER_HEADERS` (import `fetch_bytes` as the default opener; do NOT duplicate header logic). `ANNOUNCEMENTS_URL_TEMPLATE` and `ATTACHMENT_URL_TEMPLATE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{name}"` with the strCat/subcategory values pinned by Task 1 as module constants, commented with the probe date. `_AGENCY_PATTERNS`: list of `(canonical, compiled_regex)` for the agencies in the Produces block. `fetch_announcements` pages `pageno=1..` until a page returns fewer rows than the page size or `Table` empty; concatenates; writes `index_path`; returns rows. `fetch_documents` mirrors `fetch_bse_details`' loop shape: resume set from `fetched_doc_urls`, per-doc try/except appending to `failed`, budget check between docs, `.url` sidecar after each write, returns `{"fetched", "skipped", "failed", "exhausted", "remaining"}`.

Add `pypdf` to `backend/requirements.txt` (alphabetical position).

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_supply_links.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies/supply_links/snapshot.py backend/app/companies/supply_links/fetchers.py backend/requirements.txt backend/tests/test_supply_links.py
git commit -m "feat: rating-announcement discovery + rationale document fetchers"
```

---

### Task 4: Extraction — PDF text, LLM-as-reader, evidence gate

**Files:**
- Create: `backend/app/companies/supply_links/extract.py`
- Test: `backend/tests/test_supply_links.py` (append)

**Interfaces:**
- Consumes: Task 1's `rationale_sample.pdf` + README quotes; `validate_no_advice_language` from `app.reasoning.compliance`; client-call pattern from `app.companies.business_profile._call_business_profile_tool` (same one-outer-try/except, degrade-to-empty discipline); `config.SUPPLY_LINK_MAX_PER_RELATION`.
- Produces (Task 5/6 rely on):
  - `pdf_text(pdf_path) -> str | None` — pypdf extraction, None on failure/empty
  - `build_supply_tool() -> dict` — forced-tool schema `{business_summary: str|null, suppliers: [{name, evidence}], customers: [{name, evidence}]}`
  - `extract_profile(client, company_name, text) -> dict | None` — LLM call; returns `{"business_summary": str|None, "suppliers": [(name, evidence)], "customers": [(name, evidence)]}` AFTER gating, or None on any client failure
  - `_evidence_in_text(evidence, text) -> bool` — whitespace-normalized case-insensitive substring
  - `TEXT_CAP_CHARS = 12_000` — head of the document only

- [ ] **Step 1: Write the failing tests**

```python
from app.companies.supply_links import extract


def test_evidence_gate_is_whitespace_normalized():
    text = "The company  derives ~60% of\nrevenue from Indian Railways."
    assert extract._evidence_in_text("derives ~60% of revenue from Indian Railways", text)
    assert not extract._evidence_in_text("supplies steel to Tata Motors", text)


class _FakeToolClient:
    """Mimics the chat-completions client shape business_profile uses:
    returns a canned tool call regardless of input."""
    def __init__(self, arguments_json):
        self._arguments = arguments_json

    class _Msg:  # minimal shape: response.choices[0].message.tool_calls[0].function.arguments
        pass

    def create(self, **kwargs):
        import json as _json
        from types import SimpleNamespace
        fn = SimpleNamespace(arguments=self._arguments, name="record_supply_profile")
        call = SimpleNamespace(function=fn)
        msg = SimpleNamespace(tool_calls=[call])
        choice = SimpleNamespace(message=msg)
        return SimpleNamespace(choices=[choice])


def _client_returning(payload):
    import json as _json
    # Adapt to however extract.py invokes the client -- see Step 3 note:
    # extract_profile takes a callable `client` compatible with
    # app.analysis.claude_client.build_client's object. The test uses the
    # same seam business_profile's tests use; read tests/test_business_profile.py
    # FIRST and mirror its fake-client fixture exactly.
    return _json.dumps(payload)


def test_entries_without_provable_evidence_are_discarded(monkeypatch):
    text = "Alpha Ltd manufactures castings. It derives most revenue from Indian Railways."
    payload = {
        "business_summary": "Alpha Ltd manufactures castings for rail applications.",
        "suppliers": [],
        "customers": [
            {"name": "Indian Railways", "evidence": "derives most revenue from Indian Railways"},
            {"name": "Tata Motors", "evidence": "supplies castings to Tata Motors"},  # not in text
        ],
    }
    monkeypatch.setattr(extract, "_call_supply_tool", lambda client, name, text: payload)
    result = extract.extract_profile(object(), "Alpha Ltd", text)
    assert [n for n, _e in result["customers"]] == ["Indian Railways"]


def test_caps_are_enforced_after_gating(monkeypatch):
    text = " ".join(f"sells to Customer{i}." for i in range(6))
    payload = {
        "business_summary": None,
        "suppliers": [],
        "customers": [{"name": f"Customer{i}", "evidence": f"sells to Customer{i}."} for i in range(6)],
    }
    monkeypatch.setattr(extract, "_call_supply_tool", lambda client, name, text: payload)
    result = extract.extract_profile(object(), "X", text)
    assert len(result["customers"]) == 3  # config.SUPPLY_LINK_MAX_PER_RELATION


def test_advice_language_summary_is_dropped_but_links_survive(monkeypatch):
    text = "Beta Ltd refines sugar. It sells mainly to Nestle India."
    payload = {
        "business_summary": "Beta Ltd is a strong buy with excellent prospects.",
        "suppliers": [],
        "customers": [{"name": "Nestle India", "evidence": "sells mainly to Nestle India"}],
    }
    monkeypatch.setattr(extract, "_call_supply_tool", lambda client, name, text: payload)
    result = extract.extract_profile(object(), "Beta Ltd", text)
    assert result["business_summary"] is None
    assert result["customers"]


def test_pdf_text_reads_the_real_fixture():
    text = extract.pdf_text(FIXTURES / "rationale_sample.pdf")
    assert text and len(text) > 200


def test_client_failure_degrades_to_none(monkeypatch):
    def boom(client, name, text):
        raise RuntimeError("rate limited to death")
    monkeypatch.setattr(extract, "_call_supply_tool", boom)
    assert extract.extract_profile(object(), "X", "some text") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_supply_links.py -q`
Expected: FAIL — extract module missing

- [ ] **Step 3: Implement**

`extract.py`:

```python
"""Stage 2: pure-ish. PDF text extraction plus the LLM-as-READER call.

The model is handed the rationale's own text and may only report what it
can quote. _evidence_in_text is the anti-hallucination gate (spec §4):
an entry whose evidence is not a whitespace-normalized substring of the
document text is discarded -- the model can propose, the document decides.
Empty lists are the correct answer for most rationales.
"""
import json
import re

from pypdf import PdfReader

from app import config
from app.reasoning.compliance import validate_no_advice_language

TEXT_CAP_CHARS = 12_000  # business/counterparty prose lives in the opening sections


def pdf_text(pdf_path) -> str | None:
    try:
        reader = PdfReader(str(pdf_path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return None
    text = text.strip()
    return text[:TEXT_CAP_CHARS] if text else None


def _normalize_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _evidence_in_text(evidence: str, text: str) -> bool:
    if not evidence or not text:
        return False
    return _normalize_ws(evidence) in _normalize_ws(text)
```

Then `build_supply_tool()` (forced tool schema per Interfaces), `_call_supply_tool(client, company_name, text)` — copy the structure of `business_profile._call_business_profile_tool` (system prompt from `app.analysis.claude_client.SYSTEM_PROMPT`, forced tool_choice, `MODEL` with `FALLBACK_MODEL` retry, one outer try/except returning `{}`— read that function and mirror it; the framing prompt must instruct: "Report ONLY relationships this document states. Copy the supporting sentence verbatim into `evidence`. If the document names none, return empty lists."). Finally:

```python
def extract_profile(client, company_name: str, text: str) -> dict | None:
    try:
        raw = _call_supply_tool(client, company_name, text)
    except Exception:
        return None
    if not raw:
        return None

    summary = raw.get("business_summary") or None
    if summary and not validate_no_advice_language(summary).is_valid:
        summary = None

    def gate(entries):
        kept = []
        for entry in entries or []:
            name = (entry.get("name") or "").strip()
            evidence = (entry.get("evidence") or "").strip()
            if name and _evidence_in_text(evidence, text):
                kept.append((name, evidence))
        return kept[: config.SUPPLY_LINK_MAX_PER_RELATION]

    return {
        "business_summary": summary,
        "suppliers": gate(raw.get("suppliers")),
        "customers": gate(raw.get("customers")),
    }
```

Note for the test file: read `tests/test_business_profile.py` first and reuse its fake-client approach for any test that does not monkeypatch `_call_supply_tool`; delete the unused `_FakeToolClient`/`_client_returning` scaffolding from Step 1 if monkeypatching covers everything (it does — keep the committed tests minimal).

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_supply_links.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies/supply_links/extract.py backend/tests/test_supply_links.py
git commit -m "feat: rationale extraction -- LLM as reader behind a verbatim-evidence gate"
```

---

### Task 5: Loader — supply_links rows, caches, description fill

**Files:**
- Create: `backend/app/companies/supply_links/loader.py`
- Test: `backend/tests/test_supply_links.py` (append)

**Interfaces:**
- Consumes: `SupplyLink` (Task 2); `extract_profile` result shape (Task 4); `app.companies.matching.matcher.resolve(session, ticker, name, isin=None) -> MatchResult | None` (`.company_id` attribute).
- Produces: `apply_extraction(session, company, profile, *, source_url, source_agency, as_of) -> dict` — counts `{"links_written", "links_kept_older", "desc_written", "desc_kept"}`; and `refresh_json_caches(session, company) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
import json as _json

from app.companies.supply_links import loader
from app.models import CompanyAlias, SupplyLink


def _profile(customers=(), suppliers=(), summary=None):
    return {"business_summary": summary, "suppliers": list(suppliers), "customers": list(customers)}


def test_links_are_written_with_provenance_and_caches_refreshed(db_session):
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd")
    counters = loader.apply_extraction(
        db_session, company,
        _profile(customers=[("Indian Railways", "derives most revenue from Indian Railways")],
                 summary="Alpha Ltd manufactures castings."),
        source_url="https://x/AttachLive/a.pdf", source_agency="CRISIL", as_of=AS_OF,
    )
    assert counters["links_written"] == 1
    link = db_session.query(SupplyLink).one()
    assert link.source_agency == "CRISIL" and link.evidence.startswith("derives")
    db_session.refresh(company)
    assert _json.loads(company.supply_chain_customers_json) == ["Indian Railways"]
    assert company.business_desc == "Alpha Ltd manufactures castings."
    assert company.business_desc_source_url == "https://x/AttachLive/a.pdf"
    assert company.business_desc_as_of == AS_OF


def test_counterparty_resolves_via_the_exact_ladder_only(db_session):
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd")
    target = _company(db_session, "IRFC.NS", "Indian Railway Finance Corporation")
    db_session.add(CompanyAlias(company_id=target.id, alias="Indian Railway Finance Corporation",
                                alias_type="LEGAL", normalized="indian railway finance corporation"))
    db_session.flush()
    loader.apply_extraction(
        db_session, company,
        _profile(customers=[("Indian Railway Finance Corporation", "q1"),
                            ("Some Unlisted Trading House", "q2")]),
        source_url="u", source_agency="ICRA", as_of=AS_OF,
    )
    links = {l.counterparty_name: l for l in db_session.query(SupplyLink).all()}
    assert links["Indian Railway Finance Corporation"].counterparty_company_id == target.id
    assert links["Some Unlisted Trading House"].counterparty_company_id is None


def test_newer_document_replaces_older_links(db_session):
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd")
    loader.apply_extraction(db_session, company, _profile(customers=[("Old Buyer", "q")]),
                            source_url="u1", source_agency="CRISIL", as_of=date(2025, 1, 1))
    loader.apply_extraction(db_session, company, _profile(customers=[("New Buyer", "q")]),
                            source_url="u2", source_agency="CRISIL", as_of=AS_OF)
    names = [l.counterparty_name for l in db_session.query(SupplyLink).all()]
    assert names == ["New Buyer"]


def test_older_empty_extraction_never_clobbers_newer_links(db_session):
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd")
    loader.apply_extraction(db_session, company, _profile(customers=[("Buyer", "q")]),
                            source_url="u1", source_agency="CRISIL", as_of=AS_OF)
    result = loader.apply_extraction(db_session, company, _profile(),
                                     source_url="u2", source_agency="ICRA", as_of=date(2025, 1, 1))
    assert result["links_kept_older"] == 1 or db_session.query(SupplyLink).count() == 1


def test_newer_empty_extraction_replaces_aged_out_links(db_session):
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd")
    loader.apply_extraction(db_session, company, _profile(customers=[("Buyer", "q")]),
                            source_url="u1", source_agency="CRISIL", as_of=date(2025, 1, 1))
    loader.apply_extraction(db_session, company, _profile(),
                            source_url="u2", source_agency="CRISIL", as_of=AS_OF)
    assert db_session.query(SupplyLink).count() == 0
    db_session.refresh(company)
    assert company.supply_chain_customers_json == "[]"


def test_wikipedia_description_is_never_overwritten(db_session):
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd")
    company.business_desc = "Wikipedia text."
    company.business_desc_source_url = "https://en.wikipedia.org/wiki/Alpha"
    db_session.flush()
    result = loader.apply_extraction(db_session, company, _profile(summary="Rating summary."),
                                     source_url="u", source_agency="CARE", as_of=AS_OF)
    assert result["desc_kept"] == 1
    db_session.refresh(company)
    assert company.business_desc == "Wikipedia text."


def test_rating_description_updates_an_older_rating_description(db_session):
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd")
    loader.apply_extraction(db_session, company, _profile(summary="Old summary."),
                            source_url="https://x/AttachLive/old.pdf", source_agency="CRISIL",
                            as_of=date(2025, 1, 1))
    loader.apply_extraction(db_session, company, _profile(summary="New summary."),
                            source_url="https://x/AttachLive/new.pdf", source_agency="CRISIL",
                            as_of=AS_OF)
    db_session.refresh(company)
    assert company.business_desc == "New summary."
    assert company.business_desc_as_of == AS_OF
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_supply_links.py -q`
Expected: FAIL — loader missing

- [ ] **Step 3: Implement** `loader.py`:

- `apply_extraction`: existing links' newest `as_of` for the company decides: incoming `as_of` older AND incoming has no links → keep (count `links_kept_older`); incoming `as_of` >= existing → delete company's links, insert incoming (resolving each counterparty via `matcher.resolve(session, ticker=None, name=counterparty_name)`, storing `.company_id` or None). Description: write `business_summary` only when it is non-None AND (`business_desc_source_url` is NULL OR contains `"AttachLive"` — i.e. an earlier rating doc — OR equals the incoming URL) AND incoming `as_of` >= current `business_desc_as_of` (NULL-safe). Wikipedia URLs never match, so never overwritten. Count `desc_written`/`desc_kept`. Always `refresh_json_caches` + `session.commit()` at the end.
- `refresh_json_caches`: `supply_chain_suppliers_json` / `_customers_json` = JSON arrays of `counterparty_name` ordered by name, from the table. Empty list serializes as `"[]"`.

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_supply_links.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies/supply_links/loader.py backend/tests/test_supply_links.py
git commit -m "feat: supply-link loader -- provenance rows, caches, guarded description fill"
```

---

### Task 6: Prompt grounding + the no-auto-attribution guarantee

**Files:**
- Create: `backend/app/companies/supply_links/prompting.py`
- Modify: `backend/app/analysis/cascade.py` (`_identify_companies` composition — read the `_compose` closure around line 887 and its caller `_identify_companies_per_sector` ~line 1003 first)
- Test: `backend/tests/test_supply_links.py` (append), plus the named constraint test

**Interfaces:**
- Consumes: `SupplyLink` rows; `config.SUPPLY_PROMPT_MAX_LINES / SUPPLY_PROMPT_MAX_CHARS` (Task 2).
- Produces: `prompting.known_relationships_block(session, event_tickers: list[str]) -> tuple[str, list[str]]` — `(block_text, extra_candidate_tickers)`; empty string + empty list when no links.

- [ ] **Step 1: Write the failing tests**

```python
from app.companies.supply_links import prompting


def test_no_links_means_empty_block_and_no_candidates(db_session):
    _company(db_session, "AAA.NS", "Alpha")
    block, extras = prompting.known_relationships_block(db_session, ["AAA.NS"])
    assert block == "" and extras == []


def test_block_lists_links_with_agency_and_date(db_session):
    company = _company(db_session, "AAA.NS", "Alpha")
    buyer = _company(db_session, "BBB.NS", "Beta")
    db_session.add(SupplyLink(
        company_id=company.id, relation="CUSTOMER", counterparty_name="Beta",
        counterparty_company_id=buyer.id, evidence="q", source_url="u",
        source_agency="CRISIL", as_of=AS_OF,
        extracted_at=datetime.now(timezone.utc),
    ))
    db_session.flush()
    block, extras = prompting.known_relationships_block(db_session, ["AAA.NS"])
    assert "AAA.NS customers: Beta (BBB.NS)" in block
    assert "[CRISIL 2026-08-06]" in block
    assert "ONLY if THIS news plausibly transmits" in block
    assert extras == ["BBB.NS"]


def test_block_respects_line_and_char_caps(db_session):
    company = _company(db_session, "AAA.NS", "Alpha")
    for i in range(20):
        db_session.add(SupplyLink(
            company_id=company.id, relation="CUSTOMER",
            counterparty_name=f"Counterparty Number {i} With A Long Name",
            counterparty_company_id=None, evidence="q", source_url="u",
            source_agency="CRISIL", as_of=AS_OF,
            extracted_at=datetime.now(timezone.utc),
        ))
    db_session.flush()
    block, _extras = prompting.known_relationships_block(db_session, ["AAA.NS"])
    from app import config
    assert len(block) <= config.SUPPLY_PROMPT_MAX_CHARS + 200  # + fixed instruction text
    assert block.count("\n- ") <= config.SUPPLY_PROMPT_MAX_LINES


def test_supply_links_NEVER_create_alert_companies_without_llm_output(db_session, monkeypatch):
    """USER-LOCKED CONSTRAINT (spec §1): links ground the prompt and do
    nothing else. An event company with stored links plus an LLM that
    returns zero companies must produce zero AlertCompany rows and zero
    ImpactEdges -- the ETERNAL.NS-class fan-out failure must be
    structurally impossible."""
    # Arrange an alert whose event company has links, monkeypatch the
    # company-identification LLM stage to return nothing (reuse
    # tests/test_pipeline.py's persist scaffolding and its stub pattern for
    # the identification stage), run the persist path, then:
    #   assert db_session.query(AlertCompany).count() == 0
    #   assert db_session.query(ImpactEdge).count() == 0
    # The scaffolding comment above must be replaced by REAL setup copied
    # from test_pipeline.py -- committing this comment instead of working
    # code is a spec failure.
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_supply_links.py -q`
Expected: FAIL — prompting missing

- [ ] **Step 3: Implement**

`prompting.py`:

```python
"""The ONLY bridge between supply_links and the analysis pipeline: a
capped, sourced prompt block plus extra candidate tickers. Nothing here
writes AlertCompany/ImpactEdge rows, and nothing else in the pipeline
reads SupplyLink -- that one-way flow IS the user-locked no-auto-
attribution guarantee (spec §1, tested by name in test_supply_links).
"""

_INSTRUCTION = (
    "KNOWN RELATIONSHIPS (sourced from rating documents; historical, not "
    "caused by this news):\n{lines}\nInclude a counterparty ONLY if THIS "
    "news plausibly transmits through the relationship, and say how. A "
    "relationship alone is never a reason."
)
```

`known_relationships_block`: query links for the event tickers' companies, order CUSTOMER before SUPPLIER then by as_of desc; one line per (company, relation) group: `- {ticker} {customers|suppliers}: Name (TICKER), Name2 [AGENCY YYYY-MM-DD]` (agency/date of the newest link in the group); truncate to `SUPPLY_PROMPT_MAX_LINES` lines and hard-stop appending lines once the running line total exceeds `SUPPLY_PROMPT_MAX_CHARS`; extras = resolved counterparties' tickers (deduped, excluding event tickers).

`cascade.py`: in the company-identification composition, append the block to the instructions when non-empty, and extend the candidate list with `extras` (they flow through the existing candidate-line builder and the existing `MAX_CANDIDATES_PER_PROMPT` cap — add extras BEFORE the cap is applied so the cap still binds). Where the per-sector caller assembles candidates, thread `session` — it already has one. Keep the diff minimal; do not restructure `_compose`.

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_supply_links.py tests/test_pipeline.py tests/test_cascade.py -q`
Expected: all pass (cascade suite proves the byte-identical-when-empty property indirectly: its existing prompt-shape tests must not need ANY modification — if one fails, the block leaked into the no-links path; fix the leak, not the test)

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies/supply_links/prompting.py backend/app/analysis/cascade.py backend/tests/test_supply_links.py
git commit -m "feat: sourced KNOWN-RELATIONSHIPS grounding block; links never auto-attribute"
```

---

### Task 7: Jobs + bootstrap runbook

**Files:**
- Modify: `backend/app/scheduler.py`
- Create: `backend/backfill_supply_links.py`
- Test: `backend/tests/test_scheduler_universe.py` (append, same registry pattern)

**Interfaces:**
- Consumes: fetchers/snapshot (Task 3), extract (Task 4), loader (Task 5); `build_client` from `app.analysis.claude_client`; `settings.groq_api_keys`, `settings.gemini_api_key`.
- Produces: scheduler jobs `rating_filings_poll` (24h) and `supply_links_refresh` (24h, budget 30 min); runbook.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_scheduler_universe.py`)

```python
def test_supply_link_jobs_are_registered_daily(monkeypatch):
    monkeypatch.setattr(scheduler.BackgroundScheduler, "start", lambda self: None)
    try:
        scheduler.start_scheduler()
        jobs = {job.id: job for job in scheduler._scheduler.get_jobs()}
        assert "rating_filings_poll" in jobs
        assert jobs["rating_filings_poll"].trigger.interval == timedelta(hours=24)
        assert "supply_links_refresh" in jobs
        assert jobs["supply_links_refresh"].trigger.interval == timedelta(hours=24)
    finally:
        scheduler._scheduler = None


def test_supply_links_refresh_never_raises_without_snapshots(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler.supply_snapshot, "DEFAULT_ROOT", str(tmp_path))
    scheduler._run_supply_links_refresh()  # empty root: no docs, no crash
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_scheduler_universe.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

`scheduler.py` — import `from app.companies.supply_links import snapshot as supply_snapshot` plus fetchers/extract/loader lazily inside the job bodies (match the file's convention).

- `_run_rating_filings_poll`: yesterday→today announcements via `fetch_announcements` + `parse_announcements` + `fetch_documents` (no budget needed — a day's rating filings are dozens). Log counts. Never raises.
- `_run_supply_links_refresh` (budget `_SUPPLY_BUDGET_SECONDS = 30 * 60`, `time.monotonic` deadline): iterate `snapshot.pending_docs(DEFAULT_ROOT)`; for each: `pdf_text` → None ⇒ `mark_extracted` + count `unextractable`; else `extract_profile(client, company_name, text)` — company + name resolved from the doc's scrip_code via `Listing.scrip_code` (one query; docs whose scrip resolves to no company are marked done + counted `unmatched_scrip`); None ⇒ leave pending (retried next run, count `llm_failed`); else `loader.apply_extraction(...)` with `source_url` from the `.url` sidecar, agency+date from the index row cached at fetch time in a `<sha16>.meta.json` sidecar (Task 3's `fetch_documents` writes it — if Task 3 didn't, add it here with a one-line note in the report). `mark_extracted` after successful load. Stop at deadline. Log all counts. Client = `build_client(settings.groq_api_keys, settings.gemini_api_key or None)`.
- Registration: both `trigger="interval", hours=24`; poll at `next_run_time=now+45min`, refresh at `now+1h` (never at boot).

`backfill_supply_links.py`:

```python
"""Historical supply-links bootstrap.

    python backfill_supply_links.py --months 24     # walk the announcement archive
    python backfill_supply_links.py --extract-only  # just drain pending docs

Walks BSE credit-rating announcements backwards month-by-month, fetches
rationale PDFs (news-active companies first), then drains the extraction
queue with no time budget. Resumable at every stage; safe to rerun.
"""
```

Body: month windows back from today (`--months`, default 24); per window `fetch_announcements` + `parse_announcements`; collect targets; partition news-active-first using `alert_referenced_tickers(session, days=3650)` mapped to scrip codes via `Listing`; `fetch_documents` (throttle 1.0s); then the same extraction drain as the scheduler job but budget-free, committing per doc, printing progress every 25 docs.

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_scheduler_universe.py tests/test_supply_links.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/scheduler.py backend/backfill_supply_links.py backend/tests/test_scheduler_universe.py
git commit -m "feat: daily rating-filings poll + budgeted supply-links extraction; bootstrap runbook"
```

---

### Task 8: Full verification + live smoke

- [ ] **Step 1:** `cd backend && python -m pytest tests/ -q` — all pass (baseline 1,353 + new).
- [ ] **Step 2:** Frontend untouched — `cd frontend && npx tsc --noEmit -p tsconfig.json` only (guard against accidental type drift): clean.
- [ ] **Step 3: Live smoke (dev):** `python backfill_supply_links.py --months 1` — expect: announcements fetched, several PDFs on disk under `data/ratings/docs/`, at least one company gaining `supply_links` rows or a counted refusal (`unextractable`/`llm_failed`), zero crashes. Paste the printed counts into the commit message body.
- [ ] **Step 4: Commit any stragglers; report the smoke counts.**
