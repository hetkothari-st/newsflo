# Impact Charts — Phase 4 (`graph` API block) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose Phase 3's persisted `ImpactEdge`/`CascadeGap` rows as a `graph` block on `GET /api/alerts/{id}`, without touching the existing `companies[]` array (the 6 grouping charts depend on that shape unchanged) or the list endpoint's response size.

**Architecture:** A pure function `_build_graph(alert, held_company_ids) -> dict` in `routers/alerts.py` assembles `{"nodes": [...], "edges": [...], "gaps": [...]}` from an already-loaded `Alert`'s `companies`, `impact_edges`, and `cascade_gaps` relationships (two new relationships added to the `Alert` model — no new query threading needed through the private serializer). `_serialize_alert` gets an `include_graph: bool = False` param; only `get_alert` (single-alert endpoint) passes `True`.

**Tech Stack:** Python, SQLAlchemy, FastAPI, pytest.

## Global Constraints

- `companies[]`'s existing shape in `_serialize_alert`'s output is byte-for-byte unchanged — every field, every order. The 6 grouping charts (`ImpactTree`, `LevelTree`, `ConfidenceTree`, `SplitTree`, `TimelineTree`, `SectorTree`) all consume this array today and must keep working unmodified.
- `list_alerts` (`GET /api/alerts`) does NOT include `graph` — building it for up to 200 alerts on every feed load is wasted work nothing consumes yet. Only `get_alert` (`GET /api/alerts/{id}`) does.
- **No 500s, ever, on this endpoint.** A legacy alert with zero `ImpactEdge` rows (any alert created before Phase 3 shipped, or a narrow story that only produced sector-attachment edges) must still return a valid `graph` — at minimum the `news` node plus one node per company in `companies[]`, per this plan's degrade-safely design below.
- Node id scheme (verified against Phase 3's actual persisted data, not assumed): `mech:<slug>` (mechanism), `sector:<value>` (a real `SECTORS` value), `company:<company_id>`. Mechanism labels are slugified deterministically: lowercase, `↓`/`↑` become `_down`/`_up` before the rest, everything else non-alphanumeric collapses to a single `_`, leading/trailing `_` stripped.
- De-duplicate nodes by id — a sector/mechanism reached by more than one edge in the same alert appears once in `nodes`, not once per edge.
- Every edge in the output must reference an id that's actually present in `nodes` — an edge whose company endpoint isn't in this alert's `companies[]` (shouldn't happen given Phase 3's own resolution, but defensively) is dropped and logged, never left dangling.
- Verified current code this plan is grounded against (read directly): `backend/app/routers/alerts.py` (`_serialize_alert`, `list_alerts`, `get_alert`, `_held_company_ids` — confirmed `_serialize_alert` currently receives no `db`/`Session` argument at all, only the already-loaded `alert` object and precomputed lookup dicts), `backend/app/models.py`'s current `Alert`/`ImpactEdge`/`CascadeGap` (Phase 1/3 — confirmed neither `ImpactEdge` nor `CascadeGap` currently has a matching collection relationship declared on `Alert` itself, only the reverse `alert = relationship("Alert")` on each of them).

---

### Task 1: `Alert` relationships + `_build_graph`

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/routers/alerts.py`
- Test: `backend/tests/test_alerts_router.py` (or the existing alerts-router test file — implementer confirms the exact filename first, see Step 0)

**Interfaces:**
- Produces: `Alert.impact_edges` and `Alert.cascade_gaps` (new relationships, `app.models`). `_build_graph(alert: Alert, held_company_ids: set[int]) -> dict` (`app.routers.alerts`), pure — no DB session param, reads only the already-loaded `alert` object's relationships.

- [ ] **Step 0: Confirm the existing alerts-router test file**

Run (from `backend/`): `ls tests/ | grep -i alert` (or `Get-ChildItem tests | Select-String alert` on PowerShell) to find the real filename (e.g. `test_alerts_router.py`, `test_alerts.py`, or similar) — use that exact file for all test additions in this plan instead of guessing. Skim its existing tests for the fixture/setup pattern (how it builds an `Alert`+`Article`+`Company`+`AlertCompany` and calls `get_alert`/`list_alerts` — likely via FastAPI's `TestClient` or a direct function call) so new tests match the established pattern rather than inventing a new one.

- [ ] **Step 1: Add `Alert.impact_edges`/`Alert.cascade_gaps` relationships**

In `backend/app/models.py`, add two lines to the `Alert` class's existing relationship block (currently `article = relationship("Article", back_populates="alerts")` / `companies = relationship("AlertCompany", back_populates="alert")`):

```python
    article = relationship("Article", back_populates="alerts")
    companies = relationship("AlertCompany", back_populates="alert")
    impact_edges = relationship("ImpactEdge", order_by="ImpactEdge.id")
    cascade_gaps = relationship("CascadeGap", order_by="CascadeGap.id")
```

(`order_by` makes iteration order deterministic — insertion order, not DB-engine-dependent row order — which `_build_graph`'s root-detection logic in Step 3 depends on.)

- [ ] **Step 2: Write the failing tests for `_build_graph`**

Add to the test file identified in Step 0 (adjust imports to match that file's existing style — it will already import `Alert`, `AlertCompany`, `Article`, `Company` from `app.models`; add `ImpactEdge`, `CascadeGap` to that import, and `from app.routers.alerts import _build_graph`):

```python
def _make_alert_with_companies(db_session, companies_spec):
    """companies_spec: list of (ticker, name, sector, direction) tuples.
    Returns the persisted Alert with .companies populated (matches this
    file's existing fixture style -- adjust to it if it differs)."""
    article = Article(source="test", url=f"https://example.com/{id(companies_spec)}", title="Test article", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas", event_type="repo_rate_change")
    db_session.add(alert)
    db_session.flush()
    for ticker, name, sector, direction in companies_spec:
        company = db_session.query(Company).filter_by(ticker=ticker).one_or_none()
        if company is None:
            company = Company(ticker=ticker, name=name, sector=sector, index_tier="NIFTY50", market_cap=1.0)
            db_session.add(company)
            db_session.flush()
        db_session.add(AlertCompany(
            alert_id=alert.id, company_id=company.id, direction=direction,
            magnitude_low=1.0, magnitude_high=2.0, rationale="r",
            confidence_score=70, impact_level="direct",
        ))
    db_session.commit()
    db_session.refresh(alert)
    return alert


def test_build_graph_legacy_alert_with_no_edges_still_has_news_and_company_nodes(db_session):
    alert = _make_alert_with_companies(db_session, [("RELIANCE.NS", "Reliance Industries", "oil_gas", "bullish")])

    graph = _build_graph(alert, held_company_ids=set())

    node_ids = {n["id"] for n in graph["nodes"]}
    assert "news" in node_ids
    assert "company:" + str(alert.companies[0].company_id) in node_ids
    assert graph["gaps"] == []
    # Degrade-safely fallback: news connects straight to the company when
    # there are no real ImpactEdge rows to derive a richer path from.
    assert any(e["from"] == "news" and e["to"] == f"company:{alert.companies[0].company_id}" for e in graph["edges"])


def test_build_graph_dedupes_sector_node_reached_by_multiple_edges(db_session):
    alert = _make_alert_with_companies(db_session, [
        ("HDFCBANK.NS", "HDFC Bank", "banking", "bullish"),
        ("ICICIBANK.NS", "ICICI Bank", "banking", "bullish"),
    ])
    for ac in alert.companies:
        db_session.add(ImpactEdge(
            alert_id=alert.id,
            from_node_kind="sector", from_label="banking", from_company_id=None,
            to_node_kind="company", to_label=ac.company.ticker, to_company_id=ac.company_id,
            relation="demand", direction="bullish", note="n", source="llm_only",
        ))
    db_session.commit()
    db_session.refresh(alert)

    graph = _build_graph(alert, held_company_ids=set())

    sector_nodes = [n for n in graph["nodes"] if n["id"] == "sector:banking"]
    assert len(sector_nodes) == 1
    assert len(graph["edges"]) == 2  # both edges present, only the node deduped


def test_build_graph_mechanism_labels_slugified_deterministically(db_session):
    alert = _make_alert_with_companies(db_session, [("HDFCBANK.NS", "HDFC Bank", "banking", "bullish")])
    db_session.add(ImpactEdge(
        alert_id=alert.id,
        from_node_kind="mechanism", from_label="Repo Rate ↓", from_company_id=None,
        to_node_kind="mechanism", to_label="Borrowing Costs ↓", to_company_id=None,
        relation="credit_cost", direction="bullish", note="n", source="rulebook_verified",
    ))
    db_session.commit()
    db_session.refresh(alert)

    graph = _build_graph(alert, held_company_ids=set())

    node_ids = {n["id"] for n in graph["nodes"]}
    assert "mech:repo_rate_down" in node_ids
    assert "mech:borrowing_costs_down" in node_ids


def test_build_graph_root_mechanism_connects_to_news(db_session):
    alert = _make_alert_with_companies(db_session, [("HDFCBANK.NS", "HDFC Bank", "banking", "bullish")])
    db_session.add(ImpactEdge(
        alert_id=alert.id,
        from_node_kind="mechanism", from_label="Repo Rate ↓", from_company_id=None,
        to_node_kind="sector", to_label="banking", to_company_id=None,
        relation="credit_cost", direction="bullish", note="n", source="rulebook_verified",
    ))
    db_session.add(ImpactEdge(
        alert_id=alert.id,
        from_node_kind="sector", from_label="banking", from_company_id=None,
        to_node_kind="company", to_label="HDFCBANK.NS", to_company_id=alert.companies[0].company_id,
        relation="demand", direction="bullish", note="n2", source="llm_only",
    ))
    db_session.commit()
    db_session.refresh(alert)

    graph = _build_graph(alert, held_company_ids=set())

    # "Repo Rate ↓" is never a `to` anywhere in this alert -- it's the root,
    # and must be the thing news connects to (not "banking", which IS a
    # `to` of the first edge and therefore not a root).
    news_edges = [e for e in graph["edges"] if e["from"] == "news"]
    assert len(news_edges) == 1
    assert news_edges[0]["to"] == "mech:repo_rate_down"
    assert news_edges[0]["direction"] == "bullish"  # inherited from the root's own outbound edge


def test_build_graph_includes_gaps(db_session):
    alert = _make_alert_with_companies(db_session, [("RELIANCE.NS", "Reliance Industries", "oil_gas", "bullish")])
    db_session.add(CascadeGap(
        alert_id=alert.id, sector="consumer_durables", impact_level="indirect_l1",
        parent_ticker=None, attempts=2, last_error="rate limited",
    ))
    db_session.commit()
    db_session.refresh(alert)

    graph = _build_graph(alert, held_company_ids=set())

    assert graph["gaps"] == [{"sector": "consumer_durables", "impact_level": "indirect_l1", "reason": "rate limited"}]


def test_build_graph_company_node_carries_in_my_holdings(db_session):
    alert = _make_alert_with_companies(db_session, [("RELIANCE.NS", "Reliance Industries", "oil_gas", "bullish")])
    company_id = alert.companies[0].company_id

    graph = _build_graph(alert, held_company_ids={company_id})

    company_node = next(n for n in graph["nodes"] if n["id"] == f"company:{company_id}")
    assert company_node["in_my_holdings"] is True
    assert company_node["ticker"] == "RELIANCE.NS"
    assert company_node["direction"] == "bullish"


def test_build_graph_drops_edge_referencing_a_company_not_in_this_alert(db_session, caplog):
    alert = _make_alert_with_companies(db_session, [("RELIANCE.NS", "Reliance Industries", "oil_gas", "bullish")])
    # from_company_id points at a real company row, but one that is NOT
    # among this alert's own companies -- must be dropped, not crash.
    other_company = Company(ticker="TCS.NS", name="TCS", sector="it", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(other_company)
    db_session.commit()
    db_session.add(ImpactEdge(
        alert_id=alert.id,
        from_node_kind="company", from_label="TCS.NS", from_company_id=other_company.id,
        to_node_kind="sector", to_label="it", to_company_id=None,
        relation="competitor", direction="bearish", note="n", source="llm_only",
    ))
    db_session.commit()
    db_session.refresh(alert)

    graph = _build_graph(alert, held_company_ids=set())

    assert not any(e["from"] == f"company:{other_company.id}" for e in graph["edges"])
    node_ids = {n["id"] for n in graph["nodes"]}
    assert f"company:{other_company.id}" not in node_ids
```

- [ ] **Step 3: Run tests to verify they fail**

Run (from `backend/`): `python -m pytest tests/<the file found in Step 0> -k build_graph -v`
Expected: FAIL (`ImportError: cannot import name '_build_graph'`).

- [ ] **Step 4: Implement `_build_graph` in `routers/alerts.py`**

Add `import re` and `import logging` to the top of `backend/app/routers/alerts.py`. Add `ImpactEdge` to the existing `from app.models import Alert, AlertCompany, Holding, User` import:

```python
from app.models import Alert, AlertCompany, Holding, ImpactEdge, User
```

Add this module-level logger near the top (after imports, before `router = APIRouter(...)`):

```python
logger = logging.getLogger(__name__)
```

Add these functions right after `_finite_or_none` (before `_serialize_alert`):

```python
def _slugify_mechanism(label: str) -> str:
    text = label.replace("↓", " down").replace("↑", " up").lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _graph_node_id(node_kind: str, label: str, company_id: int | None) -> str:
    if node_kind == "company":
        return f"company:{company_id}"
    if node_kind == "sector":
        return f"sector:{label}"
    return f"mech:{_slugify_mechanism(label)}"


def _build_graph(alert: Alert, held_company_ids: set[int]) -> dict:
    """Assembles the news -> mechanism -> sector -> company graph from
    already-loaded relationships (alert.companies, alert.impact_edges,
    alert.cascade_gaps) -- no DB session needed here, everything was
    eager-loaded by the caller. Never raises: a legacy alert with zero
    ImpactEdge rows still gets a minimal, valid graph (news connected
    directly to each company), never a 500 or an empty/broken response.
    """
    nodes: dict[str, dict] = {"news": {"id": "news", "kind": "news", "label": alert.article.title}}

    for ac in alert.companies:
        node_id = f"company:{ac.company_id}"
        nodes[node_id] = {
            "id": node_id, "kind": "company", "company_id": ac.company_id,
            "ticker": ac.company.ticker, "name": ac.company.name,
            "direction": ac.direction, "confidence_score": ac.confidence_score,
            "impact_level": ac.impact_level,
            "in_my_holdings": ac.company_id in held_company_ids,
        }

    graph_edges: list[dict] = []
    to_ids: set[str] = set()

    for edge in alert.impact_edges:
        from_id = _graph_node_id(edge.from_node_kind, edge.from_label, edge.from_company_id)
        to_id = _graph_node_id(edge.to_node_kind, edge.to_label, edge.to_company_id)

        # A company-kind endpoint must already be one of THIS alert's own
        # companies (added above) -- if it isn't (shouldn't happen given
        # Phase 3's own resolution, but defensively), drop the edge rather
        # than reference a node id that was never added.
        if edge.from_node_kind == "company" and from_id not in nodes:
            logger.warning("alert %s: ImpactEdge %s references a from-company not in this alert's companies[], dropping", alert.id, edge.id)
            continue
        if edge.to_node_kind == "company" and to_id not in nodes:
            logger.warning("alert %s: ImpactEdge %s references a to-company not in this alert's companies[], dropping", alert.id, edge.id)
            continue

        if edge.from_node_kind != "company" and from_id not in nodes:
            nodes[from_id] = {"id": from_id, "kind": edge.from_node_kind, "label": edge.from_label, "direction": None}
        if edge.to_node_kind != "company" and to_id not in nodes:
            nodes[to_id] = {"id": to_id, "kind": edge.to_node_kind, "label": edge.to_label, "direction": None}

        graph_edges.append({
            "from": from_id, "to": to_id, "relation": edge.relation,
            "direction": edge.direction, "note": edge.note, "source": edge.source,
        })
        to_ids.add(to_id)

    if graph_edges:
        # Roots: a non-company node that is a `from` somewhere but never a
        # `to` anywhere in this alert -- the true entry point(s) of the
        # chain. Connect news to each, inheriting the root's OWN first
        # outbound edge's direction (a root has no direction of its own --
        # this is the closest honest proxy: "this news triggered a chain
        # that starts out net bullish/bearish").
        seen_roots: set[str] = set()
        # Snapshot via list(...) -- the loop body appends to graph_edges
        # itself below, and iterating a list while mutating it is a real
        # hazard. (An earlier draft of this function zipped graph_edges
        # against alert.impact_edges directly, which breaks the moment any
        # edge was dropped above -- the two lists can have different
        # lengths, silently misaligning which raw edge a root's direction
        # gets attributed to. Iterate graph_edges alone; only its own
        # "from"/"direction" keys are needed here.)
        for edge_dict in list(graph_edges):
            root_id = edge_dict["from"]
            if root_id in to_ids or root_id in seen_roots or root_id == "news":
                continue
            if nodes.get(root_id, {}).get("kind") == "company":
                continue  # a company is never treated as a chain root here
            seen_roots.add(root_id)
            graph_edges.append({
                "from": "news", "to": root_id, "relation": "correlation",
                "direction": edge_dict["direction"], "note": "This news is the origin of this transmission chain.",
                "source": "llm_only",
            })
    else:
        # Degrade-safely fallback: no persisted edges at all (legacy alert,
        # or a narrow story with nothing beyond company rows) -- connect
        # news directly to every company so the graph is still minimally
        # connected and renderable, never bare/disconnected nodes.
        for ac in alert.companies:
            graph_edges.append({
                "from": "news", "to": f"company:{ac.company_id}", "relation": "correlation",
                "direction": ac.direction, "note": "This news directly names this company.",
                "source": "llm_only",
            })

    gaps = [
        {"sector": g.sector, "impact_level": g.impact_level, "reason": g.last_error or "resolution failed after retries"}
        for g in alert.cascade_gaps
    ]

    return {"nodes": list(nodes.values()), "edges": graph_edges, "gaps": gaps}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/<the file found in Step 0> -v`
Expected: PASS, all 7 new tests plus every pre-existing test in that file.

- [ ] **Step 6: Run the full backend suite**

Run (from `backend/`): `python -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/app/routers/alerts.py backend/tests/<the file found in Step 0>
git commit -m "feat: add _build_graph, assembles the news/mechanism/sector/company graph for one alert"
```

---

### Task 2: Wire `graph` into `GET /api/alerts/{id}`

**Files:**
- Modify: `backend/app/routers/alerts.py`
- Test: `backend/tests/<the file found in Task 1 Step 0>`

**Interfaces:**
- Consumes: `_build_graph(alert, held_company_ids) -> dict` (Task 1).
- Produces: `_serialize_alert(..., include_graph: bool = False)` — new optional param; when `True`, the returned dict gains a `"graph"` key. `get_alert` passes `include_graph=True` and eager-loads `Alert.impact_edges`/`Alert.cascade_gaps`. `list_alerts` is unchanged (no `include_graph` argument passed, defaults to `False`, no `graph` key in its response items).

- [ ] **Step 1: Write the failing tests**

Add to the test file:

```python
def test_get_alert_response_includes_graph(client, db_session):
    # Adjust this test's setup to match the file's established pattern for
    # driving GET /api/alerts/{id} through the actual FastAPI route (a
    # TestClient fixture named `client` is assumed here -- rename to match
    # whatever this file's other route-level tests actually use).
    alert = _make_alert_with_companies(db_session, [("RELIANCE.NS", "Reliance Industries", "oil_gas", "bullish")])

    response = client.get(f"/api/alerts/{alert.id}")

    assert response.status_code == 200
    body = response.json()
    assert "graph" in body
    assert "nodes" in body["graph"]
    assert "edges" in body["graph"]
    assert "gaps" in body["graph"]
    assert any(n["id"] == "news" for n in body["graph"]["nodes"])
    # companies[] is completely unaffected by this change.
    assert body["companies"][0]["ticker"] == "RELIANCE.NS"


def test_list_alerts_response_has_no_graph_key(client, db_session):
    _make_alert_with_companies(db_session, [("RELIANCE.NS", "Reliance Industries", "oil_gas", "bullish")])

    response = client.get("/api/alerts")

    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 1
    assert "graph" not in body[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/<file> -k "includes_graph or no_graph_key" -v`
Expected: FAIL — `get_alert`'s response has no `graph` key yet.

- [ ] **Step 3: Wire `include_graph` into `_serialize_alert` and `get_alert`**

In `backend/app/routers/alerts.py`, change `_serialize_alert`'s signature (currently ending `mentions_index,`) to:

```python
def _serialize_alert(
    alert: Alert,
    held_company_ids: set[int],
    article_titles: dict[int, str],
    ac_translations: dict[int, tuple[str, list[str]]],
    category_labels: dict[str, str],
    mentions_index,
    include_graph: bool = False,
) -> dict:
```

Change the function's `return` statement (currently ending `"companies": companies,\n    }`) to:

```python
    result = {
        "id": alert.id,
        "category": alert.category,
        "category_label": category_labels.get(alert.category, alert.category),
        "event_type": alert.event_type,
        "created_at": alert.created_at.isoformat(),
        "article": {
            "id": alert.article.id,
            "title": article_titles.get(alert.article_id, alert.article.title),
            "url": alert.article.url,
            "image_url": alert.article.image_url,
        },
        "companies": companies,
    }
    if include_graph:
        result["graph"] = _build_graph(alert, held_company_ids)
    return result
```

(Every field above `"companies": companies` is copy-pasted unchanged from the existing function — only the final `return {...}` becomes `result = {...}` + the conditional `graph` key + `return result`.)

In `get_alert`, add eager-loading for the two new relationships to the existing `.options(...)` call (currently `selectinload(Alert.article), selectinload(Alert.companies).selectinload(AlertCompany.company)`):

```python
    alert = (
        db.query(Alert)
        .options(
            selectinload(Alert.article),
            selectinload(Alert.companies).selectinload(AlertCompany.company),
            selectinload(Alert.impact_edges),
            selectinload(Alert.cascade_gaps),
        )
        .filter(Alert.id == alert_id)
        .first()
    )
```

Change `get_alert`'s final `return` statement (currently `return _serialize_alert(alert, held_company_ids, article_titles, ac_translations, category_labels, mentions_index)`) to:

```python
    return _serialize_alert(
        alert, held_company_ids, article_titles, ac_translations, category_labels, mentions_index,
        include_graph=True,
    )
```

`list_alerts`'s call site is left completely unchanged — `include_graph` defaults to `False`, so no `graph` key appears in its response items, and `Alert.impact_edges`/`Alert.cascade_gaps` are never eager-loaded there (no wasted query work for a 200-alert list).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/<file> -v`
Expected: PASS, both new tests plus every pre-existing test in that file.

- [ ] **Step 5: Run the full backend suite**

Run (from `backend/`): `python -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/alerts.py backend/tests/<file>
git commit -m "feat: expose graph on GET /api/alerts/{id}, list endpoint unaffected"
```

---

## Explicitly out of scope (this plan)

The frontend graph model/selectors that consume this API (Phase 5). Mounting any chart (Phases 6-7). Backfilling `ImpactEdge`/`CascadeGap` for alerts created before Phase 3 shipped — those alerts permanently get the degrade-safely fallback graph (news directly to each company) unless a future one-off script re-analyzes them, which is not part of this plan.

## Definition of done (this plan only)

1. `GET /api/alerts/{id}` response has a `graph` key with `nodes`/`edges`/`gaps`; `GET /api/alerts` response items do not.
2. `companies[]` is byte-for-byte unchanged in shape.
3. A legacy alert (zero `ImpactEdge` rows) still returns a valid, non-empty `graph` — news node + one node per company, connected — never a 500.
4. Every edge's `from`/`to` id exists in `nodes`; no edge ever references a missing node id.
5. Sector/mechanism nodes reached by multiple edges appear once, not once per edge.
6. Full backend test suite green.
