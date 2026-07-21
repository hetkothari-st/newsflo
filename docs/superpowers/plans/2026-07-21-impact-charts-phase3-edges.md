# Impact Charts — Phase 3 (`ImpactEdge` table + edge generation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and persist a verified edge set per alert — the deterministic `CHAINS` (Phase 2) proposes, one LLM call per article verifies (never invents new mechanism/sector edges), and every resolved company is connected to its sector node so the graph is fully traversable news → mechanism → sector → company.

**Architecture:** A new `_generate_edges(client, facts, event_type, companies) -> list[dict]` in `cascade.py`, called from `analyze_article` after the company cascade completes. Edge dicts round-trip through `AnalysisOutput.edges` (cached by Phase 1's `AnalysisCache`, same as `companies`/`gaps`) and are persisted as `ImpactEdge` rows by `_persist_alert`.

**Tech Stack:** Python, SQLAlchemy, pydantic, pytest.

## Global Constraints

- No Alembic — `ImpactEdge` is a brand-new table, needs no `app/db.py::_ADDED_COLUMNS` entry.
- **The LLM verifies, never invents.** The verify call's tool schema can only mark a PROPOSED edge applicable/not-applicable (with an optional `pruned_reason`), plus optionally add company↔company edges whose BOTH endpoints are enum-constrained to already-resolved company tickers (same `enum: [...]` trick already used for `parent_ticker` in `build_company_tool`, `cascade.py:382`). The model can never introduce a company, sector, or mechanism name that isn't already in `CHAINS`/the resolved company list.
- **Pruned edges are kept, not dropped.** A proposed edge marked not-applicable persists with `source="rulebook_pruned"` and the reason appended to `note` — never silently omitted.
- **Degrade safely.** If the verify LLM call fails outright, fall back to the proposed chain as `rulebook_verified`, tagged `[UNVERIFIED: ...]` in `note` — never an empty/broken edge list. If the model's response omits a verification for one of the proposed edges (a partial response, not a full failure), that specific edge gets the same unverified-but-kept treatment, not a crash and not a silent drop.
- Edge dict shape (used everywhere edges pass between functions — `_generate_edges`'s return, `AnalysisOutput.edges`, `_persist_alert`'s new `edges` param): `{"from": {"kind": "sector"|"mechanism"|"company", "label": str}, "to": {"kind": ..., "label": str}, "relation": str, "direction": "bullish"|"bearish", "note": str, "source": "rulebook_verified"|"rulebook_pruned"|"llm_only"}`. This is the SAME `{"kind", "label"}` shape `app.reasoning.rulebook`'s `_mech`/`_sector` helpers already produce for `CHAINS` edges — no reshaping needed between a proposed edge and a persisted one.
- **`source="llm_only"` covers two genuinely different things, by design of the doc this plan implements**: (a) a real company↔company edge the LLM verify call actually proposed, and (b) the purely-programmatic company→sector "attachment" edges this plan generates unconditionally to keep the graph connected (no LLM involved in producing them at all). The `source` column's enum is fixed at 3 values (`rulebook_verified|rulebook_pruned|llm_only`) — introducing a 4th value for (b) is out of scope for this plan. Both are commented in the code explaining this is a naming compromise, not a mislabeling bug.
- `cascade.py` has no database access anywhere in the file (confirmed: zero `Session`/`Company` imports in the module) — `_generate_edges` works with `CompanyMention` objects (ticker/name/sector/direction, as already identified by the cascade, NOT yet DB-resolved), never with resolved `Company` rows. DB resolution of edge endpoints (ticker → `company_id`) happens later, at persist time in `pipeline.py`, which already has a `Session`.
- `AlertCompany`/`Alert` columns, `_build_alert_company`, and `resolve_companies` are untouched by this plan — only additive changes to `_persist_alert`'s parameter list (same append-after-existing-params pattern Phase 1 Task 2 already used for `gaps`).
- Verified current code this plan is grounded against (read directly): `backend/app/analysis/cascade.py`'s `analyze_article` (current state, post-Phase-1/2), `backend/app/analysis/schemas.py`'s `AnalysisOutput` (currently `category`, `companies`, `event_type`, `gaps`), `backend/app/reasoning/rulebook.py`'s `CHAINS`/`get_chain`/`EDGE_RELATIONS` (Phase 2), `backend/app/companies/resolution.py`'s `resolve_companies` (confirmed: its returned dicts carry `company_id`, NOT `ticker` — edge persistence resolves tickers independently via a direct `Company` query, not by threading ticker info through `resolve_companies`'s output).

---

### Task 1: `ImpactEdge` model + `_generate_edges` (cascade.py)

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/analysis/schemas.py`
- Modify: `backend/app/analysis/cascade.py`
- Test: `backend/tests/test_cascade.py`

**Interfaces:**
- Produces: `ImpactEdge` model (`app.models`). `_generate_edges(client, facts: str, event_type: str | None, companies: list[CompanyMention]) -> list[dict]` (`app.analysis.cascade`), returning edge dicts in the shape defined in Global Constraints. `AnalysisOutput.edges: list[dict] = []` (new field).
- Consumes: `get_chain`, `CHAINS`, `EDGE_RELATIONS` from `app.reasoning.rulebook` (Phase 2).

- [ ] **Step 1: Add the `ImpactEdge` model**

In `backend/app/models.py`, add after the `CascadeGap` class (right before `class CalibrationSample(Base):` — `CascadeGap` was added there by Phase 1 Task 2, right before this same class):

```python
class ImpactEdge(Base):
    """One verified or pruned edge in an alert's transmission-chain graph
    (see app.analysis.cascade._generate_edges). from_company_id/
    to_company_id are set only when the corresponding node is a company AND
    that ticker resolved to a real Company row at persist time -- null
    otherwise (the edge still renders with its label, just without a
    company link). See app.reasoning.rulebook.EDGE_RELATIONS for valid
    `relation` values."""
    __tablename__ = "impact_edges"

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    from_company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    from_node_kind = Column(String, nullable=False)  # company | sector | mechanism
    from_label = Column(String, nullable=False)
    to_company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    to_node_kind = Column(String, nullable=False)
    to_label = Column(String, nullable=False)
    relation = Column(String, nullable=False)
    direction = Column(String, nullable=False)  # bullish | bearish
    note = Column(Text, nullable=False)
    source = Column(String, nullable=False)  # rulebook_verified | rulebook_pruned | llm_only
    confidence_score = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    alert = relationship("Alert")
```

- [ ] **Step 2: Add `edges` to `AnalysisOutput`**

In `backend/app/analysis/schemas.py`, change `AnalysisOutput` (currently ending with the `gaps` field Phase 1 added):

```python
class AnalysisOutput(BaseModel):
    category: str
    companies: list[CompanyMention]
    event_type: Optional[str] = None
    gaps: list[dict] = []
```

to:

```python
class AnalysisOutput(BaseModel):
    category: str
    companies: list[CompanyMention]
    event_type: Optional[str] = None
    gaps: list[dict] = []
    # Verified/pruned transmission-chain edges for this article (see
    # app.analysis.cascade._generate_edges). Each dict has keys: from, to
    # (each {"kind", "label"}), relation, direction, note, source. Defaults
    # to [] so every existing caller (older tests, the dedup-reuse path in
    # pipeline.py) still validates without change.
    edges: list[dict] = []
```

- [ ] **Step 3: Write the failing cascade tests**

Add to `backend/tests/test_cascade.py` (needs a new import at the top: `from app.reasoning.rulebook import CHAINS`):

```python
def test_generate_edges_keeps_a_pruned_edge():
    proposed = CHAINS["repo_rate_change"]  # real chain, 6 edges, from Phase 2

    verifications = [{"index": 0, "applicable": False, "pruned_reason": "no lending angle in this specific article"}]
    verifications += [{"index": i, "applicable": True} for i in range(1, len(proposed))]

    client = ScriptedClient({
        "record_edge_verification": {"verifications": verifications, "llm_only_edges": []},
    })

    edges = _generate_edges(client, facts="Repo rate cut announced.", event_type="repo_rate_change", companies=[])

    pruned = [e for e in edges if e["source"] == "rulebook_pruned"]
    assert len(pruned) == 1
    assert pruned[0]["from"] == proposed[0]["from"]
    assert pruned[0]["to"] == proposed[0]["to"]
    assert "no lending angle in this specific article" in pruned[0]["note"]
    verified = [e for e in edges if e["source"] == "rulebook_verified"]
    assert len(verified) == len(proposed) - 1


def test_generate_edges_connects_every_company_to_its_sector():
    companies = [
        CompanyMention(
            name="HDFC Bank", ticker="HDFCBANK.NS", is_direct=True, sector="banking",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        ),
        CompanyMention(
            name="Maruti Suzuki", ticker="MARUTI.NS", is_direct=False, sector="auto",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
            impact_level="indirect_l1",
        ),
    ]
    # earnings has no CHAINS entry -- no verify call should even be attempted.
    client = ScriptedClient({})

    edges = _generate_edges(client, facts="f", event_type="earnings", companies=companies)

    sector_edges = {e["to"]["label"]: e for e in edges if e["from"]["kind"] == "sector"}
    assert sector_edges["HDFCBANK.NS"]["from"]["label"] == "banking"
    assert sector_edges["HDFCBANK.NS"]["direction"] == "bullish"
    assert sector_edges["HDFCBANK.NS"]["source"] == "llm_only"
    assert sector_edges["MARUTI.NS"]["from"]["label"] == "auto"


def test_generate_edges_no_chain_event_type_produces_only_sector_attachment_edges():
    companies = [CompanyMention(
        name="Reliance", ticker="RELIANCE.NS", is_direct=True, sector="oil_gas",
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
    )]
    client = ScriptedClient({})  # asserts nothing gets called -- earnings has no CHAINS entry

    edges = _generate_edges(client, facts="f", event_type="earnings", companies=companies)

    assert len(edges) == 1
    assert all(e["source"] == "llm_only" for e in edges)


def test_generate_edges_llm_only_company_edge_enum_constrained_to_resolved_tickers():
    companies = [
        CompanyMention(
            name="HDFC Bank", ticker="HDFCBANK.NS", is_direct=True, sector="banking",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        ),
        CompanyMention(
            name="Maruti Suzuki", ticker="MARUTI.NS", is_direct=False, sector="auto",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
            impact_level="indirect_l1",
        ),
    ]
    proposed = CHAINS["repo_rate_change"]
    verifications = [{"index": i, "applicable": True} for i in range(len(proposed))]
    client = ScriptedClient({
        "record_edge_verification": {
            "verifications": verifications,
            "llm_only_edges": [{
                "from_ticker": "HDFCBANK.NS", "to_ticker": "MARUTI.NS", "relation": "credit_cost",
                "direction": "bullish", "note": "Auto financing flows through HDFC Bank's lending book.",
            }],
        },
    })

    edges = _generate_edges(client, facts="f", event_type="repo_rate_change", companies=companies)

    llm_company_edges = [
        e for e in edges
        if e["source"] == "llm_only" and e["from"]["kind"] == "company" and e["to"]["kind"] == "company"
    ]
    assert len(llm_company_edges) == 1
    assert llm_company_edges[0]["from"]["label"] == "HDFCBANK.NS"
    assert llm_company_edges[0]["to"]["label"] == "MARUTI.NS"

    # The tool schema actually sent must enum-constrain both ticker fields
    # to the resolved companies -- verify the real constraint was sent, not
    # just that the scripted response happened to be accepted.
    sent_tool = client.last_tool
    props = sent_tool["function"]["parameters"]["properties"]["llm_only_edges"]["items"]["properties"]
    assert set(props["from_ticker"]["enum"]) == {"HDFCBANK.NS", "MARUTI.NS"}
    assert set(props["to_ticker"]["enum"]) == {"HDFCBANK.NS", "MARUTI.NS"}


def test_generate_edges_verify_call_failure_falls_back_to_unverified_proposed_chain():
    proposed = CHAINS["crude_oil"]

    class FailingClient:
        @property
        def chat(self):
            return SimpleNamespace(completions=self)

        def create(self, **kwargs):
            raise RuntimeError("provider down")

    edges = _generate_edges(FailingClient(), facts="f", event_type="crude_oil", companies=[])

    rulebook_edges = [e for e in edges if e["source"] == "rulebook_verified"]
    assert len(rulebook_edges) == len(proposed)
    assert all("[UNVERIFIED" in e["note"] for e in rulebook_edges)


def test_generate_edges_missing_verification_for_one_index_kept_unverified_not_dropped():
    proposed = CHAINS["inflation"]  # 3 edges
    # Only verify index 0 and 2 -- index 1 is missing from the response entirely.
    client = ScriptedClient({
        "record_edge_verification": {
            "verifications": [
                {"index": 0, "applicable": True},
                {"index": 2, "applicable": True},
            ],
            "llm_only_edges": [],
        },
    })

    edges = _generate_edges(client, facts="f", event_type="inflation", companies=[])

    assert len(edges) == len(proposed)  # nothing silently dropped
    missing = [e for e in edges if "[UNVERIFIED" in e["note"]]
    assert len(missing) == 1
    assert missing[0]["from"] == proposed[1]["from"]
```

`ScriptedClient` needs one small extension to support this task's tests: capture the last tool schema sent, so a test can assert the enum constraint was real. Add a `last_tool` attribute to the existing `ScriptedClient` class in `backend/tests/test_cascade.py` (currently defined around line 18-47):

Change:
```python
    def __init__(self, responses: dict):
        self._responses = responses
        self.calls = []
```
to:
```python
    def __init__(self, responses: dict):
        self._responses = responses
        self.calls = []
        self.last_tool = None
```
and inside `_Completions.create`, right after `self._outer.calls.append(...)`, add:
```python
            self._outer.last_tool = kwargs["tools"][0]
```

- [ ] **Step 4: Run tests to verify they fail**

Run (from `backend/`): `python -m pytest tests/test_cascade.py -k generate_edges -v`
Expected: FAIL (`ImportError: cannot import name '_generate_edges'`, or `NameError`, since the function/import doesn't exist yet).

- [ ] **Step 5: Implement `_generate_edges` in `cascade.py`**

In `backend/app/analysis/cascade.py`, change the `app.reasoning.rulebook` import (currently `from app.reasoning.rulebook import RULEBOOK_TEXT`) to:

```python
from app.reasoning.rulebook import CHAINS, EDGE_RELATIONS, NODE_SECTOR, RULEBOOK_TEXT, get_chain
```

(`NODE_SECTOR` is used below by `_sector_attachment_edges` — this single import line covers everything this task's new code needs from `rulebook.py`, no further changes to this import later in this task.)

Add this new function after `_identify_cascade_companies_per_sector` (right before `def analyze_article`):

```python
_EDGE_VERIFY_FRAMING = (
    "For each proposed transmission-chain edge below, decide whether it "
    "genuinely applies to THIS specific article -- return applicable=true "
    "if the mechanism it describes is genuinely at play here, or "
    "applicable=false with a one-line pruned_reason if it does not "
    "(e.g. the article doesn't actually support that specific link, or "
    "explicitly contradicts it). Do NOT invent a new mechanism, sector, or "
    "edge beyond what's proposed below -- your job here is to verify, not "
    "to expand the chain.\n\n"
    "You MAY additionally propose direct company-to-company edges, but "
    "ONLY between the companies listed below (using their exact ticker "
    "strings) and ONLY where you have a specific, genuine economic link "
    "(supplier, customer, or close competitor) between those two named "
    "companies -- never a company not in this list, and never a vague or "
    "generic connection. Zero additional edges is the correct, honest "
    "answer when no genuine company-to-company link exists -- do not force "
    "one to look thorough."
)


def build_edge_verify_tool(valid_tickers: list[str]) -> dict:
    """valid_tickers: every already-resolved company's ticker in this
    article's cascade -- both endpoints of any llm_only company edge are
    enum-constrained to this list (same enum-constraint discipline as
    build_company_tool's parent_ticker), so the model can never invent a
    company. Omitted entirely when fewer than 2 tickers are available (no
    two distinct companies to link)."""
    properties = {
        "verifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "applicable": {"type": "boolean"},
                    "pruned_reason": {"type": "string"},
                },
                "required": ["index", "applicable"],
            },
        },
    }
    required = ["verifications"]
    if len(valid_tickers) >= 2:
        properties["llm_only_edges"] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from_ticker": {"type": "string", "enum": valid_tickers},
                    "to_ticker": {"type": "string", "enum": valid_tickers},
                    "relation": {"type": "string", "enum": EDGE_RELATIONS},
                    "direction": {"type": "string", "enum": ["bullish", "bearish"]},
                    "note": {"type": "string"},
                },
                "required": ["from_ticker", "to_ticker", "relation", "direction", "note"],
            },
        }
    return {
        "type": "function",
        "function": {
            "name": "record_edge_verification",
            "description": "Verify proposed transmission-chain edges and optionally add company-to-company edges.",
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def _sector_attachment_edges(companies: list[CompanyMention]) -> list[dict]:
    """Purely programmatic -- no LLM call. Connects every resolved company
    to its own sector node so the graph is fully traversable news ->
    mechanism -> sector -> company, regardless of whether this article's
    event_type has a CHAINS entry at all. Tagged source="llm_only" per this
    plan's Global Constraints (the source enum has no 4th value for
    "programmatic", not a claim the LLM produced these specific edges)."""
    edges = []
    for company in companies:
        if not company.sector or not company.ticker:
            continue
        edges.append({
            "from": {"kind": NODE_SECTOR, "label": company.sector},
            "to": {"kind": "company", "label": company.ticker},
            "relation": "demand",
            "direction": company.direction,
            "note": f"{company.name} is one of the companies the {company.sector} sector's cascade reaches.",
            "source": "llm_only",
        })
    return edges


def _generate_edges(client, facts: str, event_type: str | None, companies: list[CompanyMention]) -> list[dict]:
    """Propose (via CHAINS), verify (via one LLM call, never invents), and
    always attach every company to its sector node. See this plan's Global
    Constraints for the edge dict shape and the degrade-safely contract."""
    edges: list[dict] = []
    proposed = get_chain(event_type)

    if proposed:
        valid_tickers = [c.ticker for c in companies if c.ticker]
        tool = build_edge_verify_tool(valid_tickers)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"{_EDGE_VERIFY_FRAMING}\n\n"
                    f"Facts: {facts}\n\n"
                    "Proposed edges:\n" + "\n".join(
                        f'{i}. {e["from"]["label"]} -[{e["relation"]}]-> {e["to"]["label"]} ({e["direction"]}): {e["note"]}'
                        for i, e in enumerate(proposed)
                    ) + "\n\n"
                    "Companies available for llm_only edges:\n" + "\n".join(
                        f"- {c.ticker} ({c.name}, {c.sector})" for c in companies if c.ticker
                    )
                ),
            },
        ]
        try:
            response = client.chat.completions.create(
                model=FALLBACK_MODEL, max_tokens=2048, tools=[tool],
                tool_choice={"type": "function", "function": {"name": "record_edge_verification"}},
                messages=messages,
            )
            message = response.choices[0].message
            tool_call = next((tc for tc in (message.tool_calls or []) if tc.function.name == "record_edge_verification"), None)
            if tool_call is None:
                raise ValueError("No record_edge_verification tool_use block")
            arguments = json.loads(tool_call.function.arguments)
            verifications = {v["index"]: v for v in arguments.get("verifications", [])}

            for i, proposed_edge in enumerate(proposed):
                v = verifications.get(i)
                if v is None:
                    edges.append({
                        **proposed_edge, "source": "rulebook_verified",
                        "note": f"{proposed_edge['note']} [UNVERIFIED: model returned no verification for this edge]",
                    })
                elif v.get("applicable", True):
                    edges.append({**proposed_edge, "source": "rulebook_verified"})
                else:
                    pruned_reason = v.get("pruned_reason") or "marked not applicable"
                    edges.append({
                        **proposed_edge, "source": "rulebook_pruned",
                        "note": f"{proposed_edge['note']} [PRUNED: {pruned_reason}]",
                    })

            for llm_edge in arguments.get("llm_only_edges", []):
                edges.append({
                    "from": {"kind": "company", "label": llm_edge["from_ticker"]},
                    "to": {"kind": "company", "label": llm_edge["to_ticker"]},
                    "relation": llm_edge["relation"], "direction": llm_edge["direction"],
                    "note": llm_edge["note"], "source": "llm_only",
                })
        except Exception as exc:
            logger.warning("edge verification call failed, falling back to unverified proposed chain: %s", exc)
            edges = [
                {**e, "source": "rulebook_verified", "note": f"{e['note']} [UNVERIFIED: verification call failed]"}
                for e in proposed
            ]

    edges.extend(_sector_attachment_edges(companies))
    return edges
```

- [ ] **Step 6: Wire `_generate_edges` into `analyze_article`**

In `backend/app/analysis/cascade.py`, `analyze_article`'s final `return` statement currently reads:

```python
    return AnalysisOutput(
        category=facts_result.category, event_type=facts_result.event_type,
        companies=all_companies, gaps=all_gaps,
    )
```

Replace it with:

```python
    try:
        edges = _generate_edges(client, facts_result.facts, facts_result.event_type, all_companies)
    except Exception as exc:
        logger.warning("edge generation failed entirely, returning no edges: %s", exc)
        edges = []

    return AnalysisOutput(
        category=facts_result.category, event_type=facts_result.event_type,
        companies=all_companies, gaps=all_gaps, edges=edges,
    )
```

(This is the ONLY `return AnalysisOutput(...)` call site that changes — the early-return path for `if not primary_sectors:` is left untouched: zero companies means the sector-attachment step would produce nothing anyway, and generating/verifying edges with no company context adds risk for no real benefit on an already-truncated analysis.)

- [ ] **Step 7: Run cascade tests to verify they pass**

Run: `python -m pytest tests/test_cascade.py -v`
Expected: PASS, including all 6 new tests and every pre-existing test in this file.

- [ ] **Step 8: Run the full backend suite**

Run (from `backend/`): `python -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 9: Commit**

```bash
git add backend/app/models.py backend/app/analysis/schemas.py backend/app/analysis/cascade.py backend/tests/test_cascade.py
git commit -m "feat: add ImpactEdge model + _generate_edges (propose/verify/attach)"
```

---

### Task 2: Persist `ImpactEdge` rows (`pipeline.py`)

**Files:**
- Modify: `backend/app/pipeline.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `ImpactEdge` (Task 1, `app.models`), `AnalysisOutput.edges` (Task 1).
- Produces: `_persist_alert(..., edges: list[dict] | None = None)` — new optional param appended after Phase 1 Task 2's `gaps` param, writes one `ImpactEdge` row per edge dict, resolving company-kind endpoints to `company_id` via a direct ticker lookup (nullable, never blocks persistence if a ticker doesn't resolve).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_pipeline.py` (needs `ImpactEdge` added to the `app.models` import):

```python
def test_persist_alert_writes_impact_edge_rows_resolving_company_tickers(db_session):
    company_a = Company(ticker="HDFCBANK.NS", name="HDFC Bank", sector="banking", index_tier="NIFTY50", market_cap=1.0)
    company_b = Company(ticker="MARUTI.NS", name="Maruti Suzuki", sector="auto", index_tier="NIFTY50", market_cap=1.0)
    db_session.add_all([company_a, company_b])
    db_session.commit()

    article = Article(source="test", url="https://example.com/edge1", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    edges = [
        {
            "from": {"kind": "mechanism", "label": "Repo Rate ↓"},
            "to": {"kind": "sector", "label": "banking"},
            "relation": "credit_cost", "direction": "bullish", "note": "n1", "source": "rulebook_verified",
        },
        {
            "from": {"kind": "sector", "label": "banking"},
            "to": {"kind": "company", "label": "HDFCBANK.NS"},
            "relation": "demand", "direction": "bullish", "note": "n2", "source": "llm_only",
        },
        {
            "from": {"kind": "company", "label": "HDFCBANK.NS"},
            "to": {"kind": "company", "label": "MARUTI.NS"},
            "relation": "credit_cost", "direction": "bullish", "note": "n3", "source": "llm_only",
        },
        {
            # A ticker that doesn't resolve to any real Company -- must
            # still persist (with a null company_id), never dropped and
            # never crash.
            "from": {"kind": "company", "label": "NOTAREALTICKER.NS"},
            "to": {"kind": "sector", "label": "auto"},
            "relation": "competitor", "direction": "bearish", "note": "n4", "source": "llm_only",
        },
    ]

    alert = pipeline_module._persist_alert(
        db_session, article, category="banking", entries=[], event_type="repo_rate_change", edges=edges,
    )

    rows = db_session.query(ImpactEdge).filter_by(alert_id=alert.id).order_by(ImpactEdge.id).all()
    assert len(rows) == 4

    assert rows[0].from_node_kind == "mechanism"
    assert rows[0].from_company_id is None
    assert rows[0].to_node_kind == "sector"
    assert rows[0].to_company_id is None

    assert rows[1].from_node_kind == "sector"
    assert rows[1].to_node_kind == "company"
    assert rows[1].to_company_id == company_a.id

    assert rows[2].from_company_id == company_a.id
    assert rows[2].to_company_id == company_b.id
    assert rows[2].relation == "credit_cost"
    assert rows[2].source == "llm_only"

    assert rows[3].from_node_kind == "company"
    assert rows[3].from_label == "NOTAREALTICKER.NS"
    assert rows[3].from_company_id is None  # unresolved ticker -- kept, not dropped, no crash


def test_persist_alert_with_no_edges_writes_no_edge_rows(db_session):
    article = Article(source="test", url="https://example.com/edge2", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    alert = pipeline_module._persist_alert(db_session, article, category="oil_gas", entries=[], event_type="crude_oil")

    assert db_session.query(ImpactEdge).filter_by(alert_id=alert.id).count() == 0


def test_process_new_articles_persists_edges_from_analysis(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(source="test", url="https://example.com/edge3", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_gas",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector="oil_gas",
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="r",
            key_points=["k"], time_horizon="Short-Term",
        )],
        edges=[{
            "from": {"kind": "sector", "label": "oil_gas"}, "to": {"kind": "company", "label": "RELIANCE.NS"},
            "relation": "demand", "direction": "bullish", "note": "n", "source": "llm_only",
        }],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    process_new_articles(db_session, claude_client=object())

    alert = db_session.query(Alert).one()
    assert db_session.query(ImpactEdge).filter_by(alert_id=alert.id).count() == 1
```

Add `ImpactEdge` to `backend/tests/test_pipeline.py`'s `app.models` import line.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline.py -k edge -v`
Expected: FAIL — `_persist_alert` doesn't accept an `edges` kwarg yet, and doesn't write any `ImpactEdge` rows.

- [ ] **Step 3: Implement edge persistence in `_persist_alert`**

In `backend/app/pipeline.py`, add `ImpactEdge` to the `app.models` import (currently `from app.models import Alert, AlertCompany, AnalysisCache, Article, CascadeGap, Company, utcnow`):

```python
from app.models import Alert, AlertCompany, AnalysisCache, Article, CascadeGap, Company, ImpactEdge, utcnow
```

Change `_persist_alert`'s signature (currently ending `event_type: str | None = None, gaps: list[dict] | None = None`) to:

```python
def _persist_alert(
    session: Session, article: Article, category: str, entries: list[dict], event_type: str | None = None,
    gaps: list[dict] | None = None, edges: list[dict] | None = None,
) -> Alert:
```

Add a helper right above `_persist_alert`:

```python
def _resolve_edge_endpoint_company_id(session: Session, node_kind: str, label: str) -> int | None:
    """label is a ticker string when node_kind=="company" -- resolve it to
    a real Company row's id via a direct exact-match query (same
    ticker-first discipline as app.companies.resolution._find_direct_company,
    but simpler since an edge label is always a ticker string, never a
    company name). Returns None (never raises, never drops the edge) if the
    node isn't a company or the ticker doesn't resolve -- the edge still
    persists with a null company id, matching this codebase's "omit rather
    than mismatch" resolution discipline applied to a link field, not the
    whole row."""
    if node_kind != "company":
        return None
    company = session.query(Company).filter_by(ticker=label).one_or_none()
    return company.id if company else None
```

Add gap+edge persistence right after the existing gap-writing loop (Phase 1 Task 2's `for gap in (gaps or []):` block, itself right after the `for entry in entries:` loop):

```python
    for edge in (edges or []):
        session.add(ImpactEdge(
            alert_id=alert.id,
            from_company_id=_resolve_edge_endpoint_company_id(session, edge["from"]["kind"], edge["from"]["label"]),
            from_node_kind=edge["from"]["kind"], from_label=edge["from"]["label"],
            to_company_id=_resolve_edge_endpoint_company_id(session, edge["to"]["kind"], edge["to"]["label"]),
            to_node_kind=edge["to"]["kind"], to_label=edge["to"]["label"],
            relation=edge["relation"], direction=edge["direction"], note=edge["note"], source=edge["source"],
        ))
```

In `process_new_articles`, update the fresh-analysis `_persist_alert` call site (currently `_persist_alert(session, article, analysis.category, resolved, event_type=analysis.event_type, gaps=analysis.gaps)`) to:

```python
        _persist_alert(
            session, article, analysis.category, resolved,
            event_type=analysis.event_type, gaps=analysis.gaps, edges=analysis.edges,
        )
```

The dedup-reuse call site is left unchanged (same reasoning as Phase 1 Task 2's `gaps` — that path never calls `analyze_article`, so there are no edges to persist; `edges` defaults to `None`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS, all tests including the 3 new edge tests and every pre-existing test in this file.

- [ ] **Step 5: Run the full backend suite**

Run (from `backend/`): `python -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: persist ImpactEdge rows, resolving company-kind endpoints to real companies"
```

---

## Explicitly out of scope (this plan)

The `graph` API block in `GET /api/alerts/{id}` (Phase 4) — `ImpactEdge` rows exist in the DB after this plan but nothing serves them yet. The frontend graph model/selectors (Phase 5). Mounting any chart (Phases 6-7). Populating `ImpactEdge.confidence_score` — left `None` for every row generated by this plan; nothing in the source task doc's Phase 3 spec says how it should be computed, and the doc's own later aesthetic-bar text says "Magnitude/confidence numbers come only from the existing engines... never from a fresh LLM guess at edge time" — there is no existing engine that scores an EDGE (only `compute_confidence` for a company), so leaving it `None` here is the honest, non-inventing choice; a real scoring approach is a future decision, not a Phase 3 default to guess at now.

## Definition of done (this plan only)

1. A proposed chain edge the verify call marks not-applicable persists with `source="rulebook_pruned"` and its reason visible in `note` — never absent.
2. Every resolved company with a sector and ticker has at least one inbound `ImpactEdge` from its sector node.
3. `event_type="earnings"` (no `CHAINS` entry) produces edges only from the sector-attachment step, no crash, no verify call attempted.
4. A verify-call failure (total, or a partial response missing one edge's verification) never drops a proposed edge — it persists unverified, clearly marked, not silently absent and not a crash.
5. An `ImpactEdge`'s company-kind endpoint whose ticker doesn't resolve to a real `Company` still persists (label intact, `*_company_id` null) — never blocks or drops the whole edge.
6. Full backend test suite green.
