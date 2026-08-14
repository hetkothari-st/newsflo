"""Offline labeled regression benchmark (corrective-v4 Task 21, spec §57-§59).

Replays every fixture in ``benchmarks/regression_events/`` through the REAL
engine + publication gate + section builder and scores the result against
hand-labeled ground truth.

ZERO live LLM calls, zero network, zero writes to newsflo.db:

* every stage response comes from the fixture's own ``router_responses``
  block, replayed by :class:`ReplayRouter` (a duck-typed StageRouter, same
  contract as tests/test_impact_graph.py's FakeRouter);
* each fixture gets its own throwaway in-memory SQLite DB, seeded from the
  fixture's ``universe`` block;
* the pipeline's four network side effects (market measurement, og:image
  fetch, e-mail notification, websocket broadcast) are stubbed exactly as
  tests/conftest.py stubs them.

``settings.impact_engine_v4_strict`` is forced ON for the run. This is the
SHADOW EVALUATION the spec's release gate requires (§54) -- an offline
measurement of what the strict engine would publish, never a live
enablement: the flag is restored on exit and nothing here touches the
deployed configuration.

Usage::

    python tools/offline_benchmark.py                    # whole corpus
    python tools/offline_benchmark.py --only crude_supply_shock
    python tools/offline_benchmark.py --out-dir benchmarks/out

Exit status is non-zero when ``primary_feed_precision`` is below 1.0. These
are LABELED fixtures designed so the deterministic gate can be exactly
right on them; a genuinely-failing fixture gets documented in the task
report, never bought off by lowering the bar.
"""
import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Bound BEFORE app.config/app.db import: app.db builds a module-level engine
# from settings.database_url at import time. Every fixture uses its own
# in-memory engine (see _fixture_session), so that engine is never connected
# -- this is belt-and-braces so a stray SessionLocal() can never open the
# real newsflo.db file.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402,F401  register models on Base
from app.analysis.impact_graph.budget import ArticleBudget  # noqa: E402
from app.analysis.impact_graph.engine import analyze_article_v3  # noqa: E402
from app.analysis.impact_graph.router import StageRouterError  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.market.ripple_layers import compute_ripple_layers  # noqa: E402
from app.models import (  # noqa: E402
    Article, Company, CompanyExposure, CompanyNodeExposure, MarketMove, SupplyLink, utcnow,
)

FIXTURE_DIR = _BACKEND_DIR / "benchmarks" / "regression_events"
DEFAULT_OUT_DIR = _BACKEND_DIR / "benchmarks" / "out"

# Reviewer-label vocabulary (spec §59): the slots a human reviewer ticks on
# each per-event markdown artifact. The harness never fills these in -- an
# automated score is not a review.
REVIEWER_LABELS = (
    "CORRECT", "WRONG_COMPANY", "WRONG_DIRECTION", "WRONG_MECHANISM",
    "WRONG_MATERIALITY", "WRONG_SECTION", "INSUFFICIENT_EVIDENCE", "DISPUTED",
)

# economic_effect -> the icon _strict_sections renders for it.
_EFFECT_ICON = {"positive": "win", "negative": "lose"}

# Every non-primary DISPLAYED tier: the current spellings (final blueprint
# §3) plus the legacy ones a replayed/persisted row may still carry.
DEEP_DIVE_TIERS = ("secondary_ripple", "macro_context",
                   "secondary_deep_dive", "secondary")


# --- router ----------------------------------------------------------------

class ReplayRouter:
    """Duck-types StageRouter.call, replaying the fixture's canned stage
    responses. Same contract as tests/test_impact_graph.py's FakeRouter,
    plus per-node keying.

    A response key is either the bare stage name (``"map_companies"``) or
    ``"<stage>@<parent_node>"``, matched against the ``context["parent_node"]``
    the engine passes for the mapping/ripple stages -- the broad path issues
    several ``map_companies`` calls per article and a positional list would
    silently mis-assign them the moment the graph shape changed.

    A list value is popped in order and then FALLS BACK to the stage default
    (never to an error): an extra call the fixture did not anticipate must
    read as "the model declined", not as a harness crash.

    ``quality`` is authoritative because a fixture's canned output is, by
    construction, exactly what the premium chain returned -- the degradation
    ladder has its own tests (tests/test_impact_graph.py).
    """

    def __init__(self, responses: dict, provider: str = "gemini",
                 quality: str = "authoritative"):
        self._responses = {k: (list(v) if isinstance(v, list) else v)
                           for k, v in (responses or {}).items()}
        self.calls: list[str] = []
        self.provider = provider
        self.quality = quality
        self.budget = ArticleBudget()

    def call(self, stage, **kwargs):
        self.calls.append(stage)
        parent_node = (kwargs.get("context") or {}).get("parent_node")
        response = None
        for key in ([f"{stage}@{parent_node}"] if parent_node else []) + [stage]:
            if key not in self._responses:
                continue
            held = self._responses[key]
            if isinstance(held, list):
                if held:
                    response = held.pop(0)
                    break
                continue          # exhausted -- fall through to the default
            response = held
            break
        if response is None:
            return self._default(stage, kwargs)
        if isinstance(response, dict) and response.get("__raise__"):
            raise StageRouterError(response["__raise__"])
        return response

    @staticmethod
    def _default(stage, kwargs):
        if stage == "ripple_discovery":
            return {"children": []}
        if stage in ("map_companies", "narrow_companies"):
            return {"companies": []}
        if stage == "verify_companies":
            # Accepting nothing is the fail-closed default: silence at the
            # verifier is REJECT_UNVERIFIED at the gate, never a free pass.
            return {"accept": [], "reject": []}
        if stage == "verify_edges":
            return {"verdicts": []}
        if stage == "rank_companies":
            return {"ranked": []}
        if stage == "completeness_audit":
            # "The audit found no further material branch" -- the honest
            # default for a fixture whose graph is complete by construction,
            # and quieter than letting the engine log a validator outage.
            return {"missing_branches": []}
        # map_companies_escalation and anything else: no canned answer means
        # "escalation unavailable", which _judge_candidates handles by
        # keeping the medium-thinking result.
        raise StageRouterError(f"no canned response for {stage}")


# --- fixture loading / seeding ---------------------------------------------

def load_fixtures(only: str | None = None) -> list[dict]:
    paths = sorted(FIXTURE_DIR.glob("*.json"))
    fixtures = []
    for path in paths:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        fixture["_path"] = str(path)
        fixture.setdefault("id", path.stem)
        if only and fixture["id"] != only:
            continue
        fixtures.append(fixture)
    return fixtures


def _fixture_session():
    """One isolated in-memory DB per fixture -- same StaticPool recipe as
    tests/conftest.py so the schema survives across connections."""
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed_universe(session, universe: list[dict]) -> None:
    """Company rows + their exposure priors, supply links and node-exposure
    cache rows. Two passes: SupplyLink rows reference other companies by
    ticker, so every company must exist first."""
    for spec in universe:
        session.add(Company(
            ticker=spec["ticker"], name=spec["name"], sector=spec["sector"],
            sub_sector=spec.get("sub_sector"),
            index_tier=spec.get("index_tier", "NIFTY500"),
            market_cap=spec.get("market_cap", 5e11),
            business_desc=spec.get("business_desc"),
            market="INDIA", tradeability="NORMAL",
        ))
    session.commit()

    by_ticker = {c.ticker: c for c in session.query(Company).all()}
    for spec in universe:
        row = by_ticker[spec["ticker"]]
        for exposure in spec.get("exposures", []):
            session.add(CompanyExposure(
                company_id=row.id, dimension=exposure["dimension"],
                level=exposure["level"], source=exposure.get("source", "manual"),
            ))
        for cached in spec.get("node_exposures", []):
            session.add(CompanyNodeExposure(
                company_id=row.id, node_key=cached["node_key"],
                exposure_exists=int(cached.get("exposure_exists", 1)),
                strength=cached.get("strength"), mechanism=cached.get("mechanism"),
                verified_at=utcnow(), review_after=utcnow() + timedelta(days=90),
                provenance_type=cached.get("provenance_type", "MODEL_VERIFIED"),
                source_url=cached.get("source_url"),
            ))
        for link in spec.get("supply_links", []):
            counterparty = by_ticker.get(link["counterparty_ticker"])
            session.add(SupplyLink(
                company_id=row.id,
                counterparty_company_id=counterparty.id if counterparty else None,
                counterparty_name=(counterparty.name if counterparty
                                   else link["counterparty_ticker"]),
                relation=link.get("relation", "SUPPLIER"),
                evidence=link["evidence"], source_url=link["source_url"],
                source_agency=link.get("source_agency", "CRISIL"),
                as_of=date.today(),
            ))
    session.commit()


def stub_network() -> None:
    """Every side effect _persist_alert would otherwise take off-box.
    Patched on the app.pipeline module object exactly as tests/conftest.py
    patches them, and never restored -- this process only ever runs the
    benchmark.

    ``get_or_fetch_financial_snapshot`` is on this list because it is NOT
    obvious from the call site: _build_alert_company reaches it through the
    confidence/contradiction path and it makes a live yfinance quote call
    per company. It was caught here by a 404 for a delisted-looking ticker
    in a fixture universe -- exactly the kind of accidental network the
    "no live calls" contract exists to forbid, so it is stubbed rather than
    tolerated.
    """
    import app.pipeline as pipeline

    def _no_move(session_, company, **kwargs):
        return MarketMove(company_id=company.id, benchmark_ticker="^NSEI",
                          measurement_status="no_data", measured_at=utcnow())

    pipeline.measure_company_move = _no_move
    pipeline.get_or_fetch_financial_snapshot = lambda session_, ticker: None
    pipeline.fetch_og_image = lambda url: None
    pipeline.fetch_pending_full_text = lambda session_: None
    pipeline.send_pending_notifications = lambda *a, **k: None
    pipeline.manager.broadcast_sync = lambda *a, **k: None


# --- one fixture -----------------------------------------------------------

def run_fixture(fixture: dict) -> dict:
    """Engine -> gate -> persistence -> sections for one fixture. Returns the
    raw observation record the scorer and the markdown artifact both read."""
    from app.pipeline import _persist_alert, _v3_edges, _v3_entries

    session = _fixture_session()
    try:
        seed_universe(session, fixture.get("universe", []))
        article_spec = fixture["article"]
        article = Article(
            source="benchmark", provider="offline_benchmark",
            url=f"https://benchmark.local/{fixture['id']}",
            title=article_spec["title"], content=article_spec["text"],
            status="CATEGORIZED",
        )
        session.add(article)
        session.commit()

        router = ReplayRouter(fixture.get("router_responses", {}))
        error = None
        try:
            result = analyze_article_v3(
                router, article_spec["title"], article_spec["text"],
                session=session, article_id=article.id)
        except Exception as exc:  # noqa: BLE001 -- a fixture crash is a datum
            return {
                "id": fixture["id"], "error": f"{type(exc).__name__}: {exc}",
                "entries": [], "sections": [], "stages": router.calls,
                "ground_truth": fixture.get("ground_truth", {}),
                "universe_tickers": [c["ticker"] for c in fixture.get("universe", [])],
                "facts": "", "unresolved_eligible": [],
            }

        entries = _v3_entries(session, result)
        alert = _persist_alert(
            session, article, result.category, list(entries),
            event_type=result.event_type, gaps=result.gaps,
            edges=_v3_edges(result), client=None, facts=result.facts,
            analysis_provider=result.analysis_provider,
            analysis_quality=result.analysis_quality,
            ambiguous_entities=list(result.ambiguous_entities or []),
        )
        sections = compute_ripple_layers(session, alert, set(), include_secondary=True)

        graph_by_ticker = {c.ticker: c for c in result.companies}
        observed_entries = []
        for entry in entries:
            ticker = entry.get("ticker")
            if ticker is None and entry.get("company_id") is not None:
                row = session.get(Company, entry["company_id"])
                ticker = row.ticker if row else None
            graph_company = graph_by_ticker.get(ticker)
            observed_entries.append({
                "ticker": ticker,
                "display_tier": entry.get("display_tier"),
                "gate_state": entry.get("gate_state"),
                "rejection_reason": entry.get("rejection_reason"),
                "gates_passed": entry.get("gates_passed") or [],
                "evidence_class": entry.get("evidence_class"),
                "evidence_tier": entry.get("evidence_tier"),
                "materiality_grade": entry.get("materiality_grade"),
                "economic_effect": entry.get("economic_effect"),
                "causal_distance": entry.get("causal_distance"),
                "causal_parent_type": entry.get("causal_parent_type"),
                "causal_parent_id": entry.get("causal_parent_id"),
                "mechanism": entry.get("mechanism"),
                "rationale": entry.get("rationale"),
                "materiality": entry.get("materiality"),
                "confidence": entry.get("confidence_f"),
                "discovery_source": entry.get("discovery_source"),
                "causal_directness": entry.get("causal_directness"),
                "counterfactual": getattr(graph_company, "counterfactual", "") if graph_company else "",
                "resolved": entry.get("company_id") is not None,
                "decision_notes": entry.get("decision_notes"),
            })

        # Entity integrity (INV: nothing unresolved or off-universe may
        # ever be published). Read back from the PERSISTED rows, not from
        # the in-memory entries, so a persistence bug is visible too.
        from app.models import AlertCompany, CompanyDecisionRecord

        universe_tickers = {c["ticker"] for c in fixture.get("universe", [])}
        persisted = (
            session.query(AlertCompany, Company)
            .join(Company, Company.id == AlertCompany.company_id)
            .filter(AlertCompany.alert_id == alert.id).all()
        )
        ghost_tickers = sorted({c.ticker for _, c in persisted} - universe_tickers)
        unresolved_eligible = sorted({
            r.ticker for r in session.query(CompanyDecisionRecord)
            .filter_by(alert_id=alert.id).all()
            if r.company_id is None and r.display_tier != "excluded"
        })

        # Explanation faithfulness: the closed-world validator run over the
        # exact strings a strict-mode alert publishes as its "why".
        from app.analysis.refinement import validate_closed_world

        allowed_names = {c.name for _, c in persisted}
        faithful, checked = 0, 0
        for alert_company, company in persisted:
            for text in (alert_company.mechanism, alert_company.rationale):
                if not text:
                    continue
                checked += 1
                if validate_closed_world(text, result.facts, allowed_names, session) is not None:
                    faithful += 1

        return {
            "id": fixture["id"],
            "error": None,
            "title": article_spec["title"],
            "facts": result.facts,
            "event_label": result.event_label,
            "analysis_quality": result.analysis_quality,
            "stages": router.calls,
            "entries": observed_entries,
            "edges": [
                {"parent_type": e.parent_type, "parent_id": e.parent_id,
                 "child_type": e.child_type, "child_id": e.child_id,
                 "causal_distance": e.causal_distance, "mechanism": e.mechanism}
                for e in result.edges
            ],
            "sections": [
                {"title": s["title"], "icon": s["icon"],
                 "relationship": s["relationship"],
                 "tickers": [r["ticker"] for r in s["rows"]]}
                for s in sections
            ],
            "ghost_tickers": ghost_tickers,
            "unresolved_eligible": unresolved_eligible,
            "universe_tickers": sorted(universe_tickers),
            "explanation_checked": checked,
            "explanation_faithful": faithful,
            "ground_truth": fixture.get("ground_truth", {}),
        }
    finally:
        session.close()


# --- scoring ---------------------------------------------------------------

def _displayed(observation) -> dict:
    return {e["ticker"]: e for e in observation["entries"]
            if e["display_tier"] in ("primary",) + DEEP_DIVE_TIERS}


def _primary(observation) -> dict:
    return {e["ticker"]: e for e in observation["entries"]
            if e["display_tier"] == "primary"}


class Counter:
    """A (hits, total) accumulator that reports N/A instead of a fake 1.0
    when nothing was labeled -- an unmeasured metric is not a passing one
    (this is the shape that made the old `mixed_accuracy` auto-pass: an
    empty denominator scored 100%)."""

    def __init__(self):
        self.hits = 0
        self.total = 0

    def add(self, hit: bool) -> None:
        self.total += 1
        self.hits += 1 if hit else 0

    @property
    def value(self):
        return None if self.total == 0 else self.hits / self.total

    def as_dict(self):
        return {"value": self.value, "hits": self.hits, "total": self.total}


def score(observations: list[dict]) -> dict:
    """Every metric in the Task-21 suite, computed over the whole corpus.

    Company-level metrics count one observation per (fixture, ticker)
    decision, so a fixture with five candidates weighs five times a fixture
    with one -- the corpus measures DECISIONS, not articles.
    """
    company_tp = company_fp = 0
    expected_total = expected_found = 0
    candidates_total = 0
    primary_hits = primary_total = 0
    direction = Counter()
    mixed = Counter()
    mechanism = Counter()
    distance = Counter()
    materiality = Counter()
    evidence = Counter()
    sections = Counter()
    abstention = Counter()
    entity = Counter()
    rejection = Counter()
    # §32 batch-A additions: the three tiers/dimensions expected_primary
    # never covered -- secondary_ripple and macro_context are DISPLAY TIERS
    # of their own (blueprint §6/§7), not primary-adjacent noise, and
    # directness (§3/§11) is a dimension independent of causal_distance.
    # Each is asserted ONLY when a fixture declares the corresponding
    # ground_truth key -- an absent key is unmeasured, not a free pass
    # (Counter already reports N/A on an empty denominator), which is what
    # keeps the 23 pre-existing fixtures (none of which carry these keys)
    # passing unchanged.
    secondary_ripple = Counter()
    macro_context = Counter()
    directness = Counter()
    explanation_checked = explanation_faithful = 0
    per_event = []

    for obs in observations:
        truth = obs.get("ground_truth") or {}
        expected_primary = truth.get("expected_primary") or {}
        allow_secondary = set(truth.get("allow_secondary") or [])
        expected_rejected = list(truth.get("expected_rejected") or [])
        allowed = set(expected_primary) | allow_secondary

        displayed = _displayed(obs)
        primary = _primary(obs)
        candidates_total += len(obs["entries"])

        event = {"id": obs["id"], "error": obs.get("error"), "failures": []}

        # company precision / recall / false-positive rate
        for ticker in displayed:
            if ticker in allowed:
                company_tp += 1
            else:
                company_fp += 1
                event["failures"].append(f"published unexpected company {ticker}")
        for ticker in expected_primary:
            expected_total += 1
            if ticker in displayed:
                expected_found += 1
            else:
                event["failures"].append(f"missed expected company {ticker}")

        # primary_feed_precision -- THE release metric, primary tier only,
        # and a published primary is correct only when its FUNDAMENTAL
        # EFFECT is right too (a right company with a wrong direction is a
        # wrong published claim).
        for ticker, entry in primary.items():
            primary_total += 1
            if (ticker in expected_primary
                    and entry["economic_effect"] == expected_primary[ticker]):
                primary_hits += 1
            else:
                event["failures"].append(
                    f"primary {ticker} effect={entry['economic_effect']} "
                    f"expected={expected_primary.get(ticker, '<not primary>')}")

        # direction / mixed accuracy over every labeled company that the
        # system actually published (a missed company is a recall failure,
        # already counted; scoring it here too would double-punish).
        for ticker, effect in expected_primary.items():
            entry = displayed.get(ticker)
            if entry is None:
                continue
            direction.add(entry["economic_effect"] == effect)
            if effect == "mixed":
                # NO AUTO-PASS: a "mixed" label demands a "mixed"
                # prediction; a confident directional call on a genuinely
                # two-sided story is wrong, not "close enough".
                mixed.add(entry["economic_effect"] == "mixed")

        # rejection recall: an expected_rejected ticker must not be published
        for ticker in expected_rejected:
            hit = ticker not in displayed
            rejection.add(hit)
            if not hit:
                event["failures"].append(f"expected-rejected {ticker} was published")

        for ticker, expected in (truth.get("expected_mechanism") or {}).items():
            entry = displayed.get(ticker)
            observed = "" if entry is None else " ".join(filter(None, [
                entry.get("causal_parent_id"), entry.get("discovery_source")]))
            mechanism.add(expected in observed)
        for ticker, expected in (truth.get("expected_causal_distance") or {}).items():
            entry = displayed.get(ticker)
            distance.add(entry is not None and entry["causal_distance"] == expected)
        for ticker, expected in (truth.get("expected_materiality_grade") or {}).items():
            entry = next((e for e in obs["entries"] if e["ticker"] == ticker), None)
            materiality.add(entry is not None and entry["materiality_grade"] == expected)
        for ticker, expected in (truth.get("expected_evidence_tier") or {}).items():
            entry = next((e for e in obs["entries"] if e["ticker"] == ticker), None)
            evidence.add(entry is not None and entry["evidence_tier"] == expected)

        # secondary_ripple / macro_context: asserted EXACTLY like
        # primary_feed_precision above -- presence at the SPECIFIC tier the
        # label names, plus the fundamental effect matching. A ticker the
        # label expects at secondary_ripple that instead published as
        # primary, macro_context, excluded or not at all is a miss: the
        # tier IS the claim (blueprint §6/§7 -- these are governed display
        # tiers, not "close enough to primary").
        for ticker, effect in (truth.get("expected_secondary_ripple") or {}).items():
            entry = next((e for e in obs["entries"] if e["ticker"] == ticker), None)
            hit = (entry is not None and entry["display_tier"] == "secondary_ripple"
                   and entry["economic_effect"] == effect)
            secondary_ripple.add(hit)
            if not hit:
                observed_tier = entry["display_tier"] if entry is not None else "<absent>"
                event["failures"].append(
                    f"expected secondary_ripple {ticker} effect={effect} "
                    f"observed_tier={observed_tier}")
        for ticker, effect in (truth.get("expected_macro_context") or {}).items():
            entry = next((e for e in obs["entries"] if e["ticker"] == ticker), None)
            hit = (entry is not None and entry["display_tier"] == "macro_context"
                   and entry["economic_effect"] == effect)
            macro_context.add(hit)
            if not hit:
                observed_tier = entry["display_tier"] if entry is not None else "<absent>"
                event["failures"].append(
                    f"expected macro_context {ticker} effect={effect} "
                    f"observed_tier={observed_tier}")

        # directness (§3/§11): a SEPARATE dimension from causal_distance and
        # from tier -- checked against whichever entry the ticker resolved
        # to, regardless of its tier, since a gate decision carries a
        # directness verdict even for a rejected candidate.
        for ticker, expected in (truth.get("expected_directness") or {}).items():
            entry = next((e for e in obs["entries"] if e["ticker"] == ticker), None)
            directness.add(entry is not None and entry["causal_directness"] == expected)
            if entry is None or entry["causal_directness"] != expected:
                observed = entry["causal_directness"] if entry is not None else "<absent>"
                event["failures"].append(
                    f"expected directness {ticker}={expected} observed={observed}")

        # sections: the expected section must exist AND every member must be
        # a company the label allows (a right-looking title full of wrong
        # companies is not a correct section).
        for expected_section in (truth.get("expected_sections") or []):
            wanted_icon = _EFFECT_ICON.get(expected_section["effect"], "side")
            needle = expected_section.get("label_contains", "").lower()
            hit = any(
                s["icon"] == wanted_icon
                and needle in s["title"].lower()
                and all(t in allowed for t in s["tickers"])
                for s in obs["sections"]
            )
            sections.add(hit)
            if not hit:
                event["failures"].append(
                    f"missing/contaminated section {expected_section['effect']}"
                    f"/{expected_section.get('label_contains')}")

        if truth.get("expect_abstention"):
            hit = not primary
            abstention.add(hit)
            if not hit:
                event["failures"].append(
                    f"abstention fixture published {sorted(primary)} as primary")

        entity_ok = not obs.get("ghost_tickers") and not obs.get("unresolved_eligible")
        entity.add(entity_ok)
        if not entity_ok:
            event["failures"].append(
                f"entity integrity: ghosts={obs.get('ghost_tickers')} "
                f"unresolved_eligible={obs.get('unresolved_eligible')}")

        explanation_checked += obs.get("explanation_checked", 0)
        explanation_faithful += obs.get("explanation_faithful", 0)

        if obs.get("error"):
            event["failures"].append(f"engine error: {obs['error']}")
        event["primary"] = sorted(primary)
        event["secondary"] = sorted(t for t, e in displayed.items() if t not in primary)
        per_event.append(event)

    displayed_total = company_tp + company_fp
    metrics = {
        "company_precision": {
            "value": None if displayed_total == 0 else company_tp / displayed_total,
            "hits": company_tp, "total": displayed_total},
        "company_recall": {
            "value": None if expected_total == 0 else expected_found / expected_total,
            "hits": expected_found, "total": expected_total},
        "false_positive_rate": {
            "value": None if candidates_total == 0 else company_fp / candidates_total,
            "hits": company_fp, "total": candidates_total},
        "primary_feed_precision": {
            "value": None if primary_total == 0 else primary_hits / primary_total,
            "hits": primary_hits, "total": primary_total},
        "fundamental_direction_accuracy": direction.as_dict(),
        "mixed_accuracy": mixed.as_dict(),
        "mechanism_accuracy": mechanism.as_dict(),
        "causal_distance_accuracy": distance.as_dict(),
        "materiality_accuracy": materiality.as_dict(),
        "section_accuracy": sections.as_dict(),
        "abstention_precision": abstention.as_dict(),
        "entity_accuracy": entity.as_dict(),
        "evidence_accuracy": evidence.as_dict(),
        "rejection_recall": rejection.as_dict(),
        "secondary_ripple_accuracy": secondary_ripple.as_dict(),
        "macro_context_accuracy": macro_context.as_dict(),
        "directness_accuracy": directness.as_dict(),
        "explanation_faithfulness": {
            "value": None if explanation_checked == 0 else explanation_faithful / explanation_checked,
            "hits": explanation_faithful, "total": explanation_checked},
        # Market measurement is a SEPARATE truth (INV-001/INV-002): it is
        # deterministic, it never feeds the publication gate, and it needs
        # real price bars this corpus deliberately does not carry. Measured
        # by tests/test_measure.py + tests/test_v4_market_integrity.py,
        # asserted N/A here rather than faked from a stubbed no_data move.
        "market_measurement_accuracy": {
            "value": None, "hits": 0, "total": 0,
            "reason": "N/A offline -- price-bar layer is deterministic and covered by "
                      "tests/test_measure.py and tests/test_v4_market_integrity.py; "
                      "this corpus carries no market data by design (INV-002)",
        },
    }
    return {"metrics": metrics, "per_event": per_event}


# --- artifacts -------------------------------------------------------------

def _md_escape(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ") if value is not None else ""


def review_markdown(obs: dict, event_score: dict) -> str:
    """Per-event review artifact (spec §59): everything a human needs to
    disagree with the machine, plus the reviewer-label slots."""
    truth = obs.get("ground_truth") or {}
    lines = [f"# {obs['id']}", ""]
    if obs.get("error"):
        lines += [f"**ENGINE ERROR:** `{obs['error']}`", ""]
    lines += [
        f"**Event:** {_md_escape(obs.get('title'))}",
        "",
        f"**Extracted facts:** {_md_escape(obs.get('facts'))}",
        "",
        f"**Analysis quality:** {obs.get('analysis_quality')} | "
        f"**stages called:** {', '.join(obs.get('stages') or []) or '(none)'}",
        "",
        "## Published (primary)",
        "",
    ]
    primary = [e for e in obs["entries"] if e["display_tier"] == "primary"]
    deep = [e for e in obs["entries"] if e["display_tier"] in DEEP_DIVE_TIERS]
    excluded = [e for e in obs["entries"] if e["display_tier"] == "excluded"]

    header = ("| ticker | effect | d | evidence | materiality | counterfactual | mechanism |\n"
              "|---|---|---|---|---|---|---|")
    def _rows(entries):
        if not entries:
            return "_(none)_"
        return "\n".join([header] + [
            f"| {_md_escape(e['ticker'])} | {_md_escape(e['economic_effect'])} | "
            f"{_md_escape(e['causal_distance'])} | "
            f"{_md_escape(e['evidence_class'])}/{_md_escape(e['evidence_tier'])} | "
            f"{_md_escape(e['materiality_grade'])} | {_md_escape(e['counterfactual'])} | "
            f"{_md_escape((e['mechanism'] or '')[:90])} |"
            for e in entries])

    lines += [_rows(primary), "", "## Published (secondary deep dive)", "", _rows(deep), ""]
    lines += ["## Rejected", ""]
    if excluded:
        lines += ["| ticker | gate_state | evidence | last gate passed |", "|---|---|---|---|"]
        for e in excluded:
            lines.append(
                f"| {_md_escape(e['ticker'])} | {_md_escape(e['gate_state'])} | "
                f"{_md_escape(e['evidence_class'])}/{_md_escape(e['evidence_tier'])} | "
                f"{_md_escape((e['gates_passed'] or ['-'])[-1])} |")
    else:
        lines.append("_(none)_")

    lines += ["", "## Causal paths", ""]
    if obs.get("edges"):
        for edge in obs["edges"]:
            lines.append(f"- d{edge['causal_distance']} `{edge['parent_type']}:{edge['parent_id']}` -> "
                         f"`{edge['child_type']}:{edge['child_id']}` — {_md_escape(edge['mechanism'][:110])}")
    else:
        lines.append("_(no edges)_")

    lines += ["", "## Sections rendered", ""]
    if obs.get("sections"):
        for section in obs["sections"]:
            lines.append(f"- **{_md_escape(section['title'])}** ({section['icon']}, "
                         f"{section['relationship']}): {', '.join(section['tickers'])}")
    else:
        lines.append("_(none)_")

    lines += [
        "", "## Ground truth", "",
        "```json", json.dumps(truth, indent=2, ensure_ascii=False), "```",
        "", "## Automated verdict", "",
    ]
    if event_score["failures"]:
        lines += [f"- FAIL: {f}" for f in event_score["failures"]]
    else:
        lines.append("- all labeled expectations met")
    lines += [
        "", "## Reviewer label (tick exactly one, add notes)", "",
        *[f"- [ ] {label}" for label in REVIEWER_LABELS],
        "", "Notes:", "", "> ", "",
    ]
    return "\n".join(lines)


def summary_table(metrics: dict) -> str:
    width = max(len(name) for name in metrics)
    lines = [f"{'metric'.ljust(width)}  {'value':>8}  {'hits/total':>12}",
             f"{'-' * width}  {'-' * 8}  {'-' * 12}"]
    for name, payload in metrics.items():
        value = payload["value"]
        rendered = "  N/A" if value is None else f"{value * 100:6.1f}%"
        fraction = "{}/{}".format(payload["hits"], payload["total"])
        lines.append(f"{name.ljust(width)}  {rendered:>8}  {fraction:>12}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="run a single fixture by id")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    fixtures = load_fixtures(args.only)
    if not fixtures:
        print(f"no fixtures found in {FIXTURE_DIR}", file=sys.stderr)
        return 2

    stub_network()
    previous_strict = settings.impact_engine_v4_strict
    settings.impact_engine_v4_strict = True   # SHADOW evaluation, restored below
    try:
        observations = [run_fixture(fixture) for fixture in fixtures]
    finally:
        settings.impact_engine_v4_strict = previous_strict

    scored = score(observations)
    out_dir = Path(args.out_dir)
    reviews_dir = out_dir / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)

    by_id = {event["id"]: event for event in scored["per_event"]}
    for obs in observations:
        (reviews_dir / f"{obs['id']}.md").write_text(
            review_markdown(obs, by_id[obs["id"]]), encoding="utf-8")

    payload = {
        "fixtures": len(fixtures),
        "strict_mode": True,
        "metrics": scored["metrics"],
        "per_event": scored["per_event"],
        "observations": observations,
    }
    results_path = out_dir / "offline_results.json"
    results_path.write_text(json.dumps(payload, indent=2, default=str, ensure_ascii=False),
                            encoding="utf-8")

    if not args.quiet:
        print(f"offline regression corpus: {len(fixtures)} fixture(s)\n")
        print(summary_table(scored["metrics"]))
        print()
        failing = [e for e in scored["per_event"] if e["failures"]]
        if failing:
            print("failing events:")
            for event in failing:
                print(f"  {event['id']}:")
                for failure in event["failures"]:
                    print(f"    - {failure}")
        else:
            print("every labeled expectation met on every event.")
        print(f"\nresults: {results_path}")
        print(f"reviews: {reviews_dir}")

    precision = scored["metrics"]["primary_feed_precision"]["value"]
    expected_primaries = sum(
        len((obs.get("ground_truth") or {}).get("expected_primary") or {})
        for obs in observations
    )
    if precision is None:
        # No primary was published at all. That is CORRECT when the corpus
        # under test expects none (an abstention-only selection, e.g.
        # --only on a single abstention fixture) and a total recall failure
        # otherwise -- the two must not share an exit status.
        if expected_primaries == 0:
            print("\nprimary_feed_precision: N/A (this selection expects no primary "
                  "companies; abstention was the labeled answer)")
            return 0
        print(f"\nFAIL: nothing published as primary, but {expected_primaries} primary "
              f"companies are labeled on this corpus", file=sys.stderr)
        return 1
    if precision < 1.0:
        print(f"\nFAIL: primary_feed_precision={precision} (< 1.0 on a labeled corpus)",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
