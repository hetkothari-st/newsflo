import logging
import math
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import get_current_user_optional
from app.companies.branding import logo_url
from app.companies.history import bulk_past_mentions, mentions_before
from app.companies.market import infer_market
from app.i18n import get_lang
from app.ist_time import day_utc_window, today_ist
from app.models import Alert, AlertCompany, Holding, ImpactEdge, User
from app.pipeline import _decode_json_list, decode_key_points
from app.routers.articles import get_db
from app.translation.lookup import (
    bulk_alert_company_translations,
    bulk_article_titles,
    bulk_category_labels,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

# The feed has no use for unbounded history, and returning every alert ever
# created means this endpoint's response size (and, before the eager-loading
# fix below, its query count) grows forever as alerts accumulate.
ALERTS_LIMIT = 200


def _finite_or_none(value: float | None) -> float | None:
    # yfinance-derived columns (price_at_analysis/return_1m/return_3m) can
    # already hold NaN/Infinity in the DB from a since-fixed division-by-zero
    # bug in app.outcomes.price_fetcher (a zero/missing close price). NaN is
    # valid Python but not valid JSON -- Starlette's JSONResponse raises
    # ValueError and 500s the whole endpoint on the first row that has one.
    # Sanitizing here, not just at the source, means old corrupted rows
    # (already persisted before that fix) can't take the feed down either.
    if value is None or not math.isfinite(value):
        return None
    return value


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
            # Every node kind carries "label" (mechanism/sector/news nodes
            # already do) so frontend code can read node.label uniformly
            # without a kind check -- redundant with "name" here, but a
            # real type-safety gap otherwise (GraphNode.label is required,
            # not optional, on the frontend).
            "label": ac.company.name,
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


def _serialize_alert(
    alert: Alert,
    held_company_ids: set[int],
    article_titles: dict[int, str],
    ac_translations: dict[int, tuple[str, list[str]]],
    category_labels: dict[str, str],
    mentions_index,
    include_graph: bool = False,
) -> dict:
    companies = []
    for ac in alert.companies:
        rationale, key_points = ac_translations.get(ac.id, (ac.rationale, decode_key_points(ac)))
        companies.append({
            "company_id": ac.company_id, "ticker": ac.company.ticker, "name": ac.company.name,
            "index_tier": ac.company.index_tier, "sector": ac.company.sector,
            "sub_sector": ac.company.sub_sector, "logo_url": logo_url(ac.company),
            "direction": ac.direction,
            "magnitude_low": ac.magnitude_low, "magnitude_high": ac.magnitude_high,
            "rationale": rationale, "key_points": key_points,
            "confidence_score": ac.confidence_score, "time_horizon": ac.time_horizon,
            "basis": ac.basis, "confidence": ac.confidence,
            "confidence_band": ac.confidence_band,
            "confidence_contributors": _decode_json_list(ac.confidence_contributors_json),
            "confidence_penalties": _decode_json_list(ac.confidence_penalties_json),
            "reasons": _decode_json_list(ac.reasons_json),
            "evidence_refs": _decode_json_list(ac.evidence_refs_json),
            "risks": _decode_json_list(ac.risks_json),
            "assumptions": _decode_json_list(ac.assumptions_json),
            "unknowns": _decode_json_list(ac.unknowns_json),
            "alternative_hypothesis": ac.alternative_hypothesis,
            "price_at_analysis": _finite_or_none(ac.price_at_analysis),
            "return_1m": _finite_or_none(ac.return_1m),
            "return_3m": _finite_or_none(ac.return_3m),
            "contradiction_note": ac.contradiction_note,
            "impact_level": ac.impact_level,
            "parent_company_id": ac.parent_company_id,
            "market": infer_market(ac.company.ticker),
            "in_my_holdings": ac.company_id in held_company_ids,
            "past_mentions": mentions_before(mentions_index, ac.company_id, alert.created_at),
        })
    result = {
        "id": alert.id,
        # `category` stays the raw, canonical, untranslated slug -- it's
        # a matching/storage key (watchlist filtering, color swatch
        # lookup), not just display text. `category_label` is the
        # additive, purely-for-display translated field.
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


def _held_company_ids(db: Session, current_user: User | None) -> set[int]:
    # Anonymous requests get an empty set -> every company is in_my_holdings=False.
    if current_user is None:
        return set()
    return {h.company_id for h in db.query(Holding).filter_by(user_id=current_user.id).all()}


@router.get("")
def list_alerts(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
    lang: str = Depends(get_lang),
):
    held_company_ids = _held_company_ids(db, current_user)

    # The feed shows only today's (IST) news now that the calendar exists as
    # the dedicated way to browse prior days -- older alerts are still
    # reachable there (GET /api/calendar/day) and individually via
    # GET /api/alerts/{id} (e.g. a calendar day's "Charts"/full-detail link),
    # just no longer mixed into this list.
    start_utc, end_utc = day_utc_window(today_ist())

    # selectinload replaces what used to be one lazy-load query per alert for
    # .article, one per alert for .companies, and one per AlertCompany for
    # .company -- each collapses into a single batched IN-query regardless
    # of how many alerts/companies are in this page.
    alerts = (
        db.query(Alert)
        .options(
            selectinload(Alert.article),
            selectinload(Alert.companies).selectinload(AlertCompany.company),
        )
        .filter(Alert.created_at >= start_utc, Alert.created_at < end_utc)
        .order_by(Alert.created_at.desc())
        .limit(ALERTS_LIMIT)
        .all()
    )

    # Four bulk lookups total, regardless of alert count, keyed by lang for
    # the first three -- empty dicts (and every .get() below falling back to
    # English) when lang == "en" or nothing's been translated yet.
    article_titles = bulk_article_titles(db, [a.article_id for a in alerts], lang)
    ac_translations = bulk_alert_company_translations(
        db, [ac.id for a in alerts for ac in a.companies], lang
    )
    category_labels = bulk_category_labels(db, list({a.category for a in alerts}), lang)
    mentions_index = bulk_past_mentions(db, {ac.company_id for a in alerts for ac in a.companies})

    return [
        _serialize_alert(alert, held_company_ids, article_titles, ac_translations, category_labels, mentions_index)
        for alert in alerts
    ]


@router.get("/{alert_id}")
def get_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
    lang: str = Depends(get_lang),
):
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
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    held_company_ids = _held_company_ids(db, current_user)
    article_titles = bulk_article_titles(db, [alert.article_id], lang)
    ac_translations = bulk_alert_company_translations(db, [ac.id for ac in alert.companies], lang)
    category_labels = bulk_category_labels(db, [alert.category], lang)
    mentions_index = bulk_past_mentions(db, {ac.company_id for ac in alert.companies})

    return _serialize_alert(
        alert, held_company_ids, article_titles, ac_translations, category_labels, mentions_index,
        include_graph=True,
    )
