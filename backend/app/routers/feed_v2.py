"""Level 0/1 feed endpoints for the measurement-first UI rebuild
(docs/NEWS_IMPACT_APP_SPEC.md §2, §9) -- a new, parallel set of routes
alongside the existing GET /api/alerts (kept untouched; see this plan's
Global Constraints). Returns only alerts with at least one measured
company (excess_move_pct computed, measurement_status == "ok") -- an
alert with nothing measured has no headline number and is omitted
entirely (Ground Rules: never fabricate, omit rather than invent).
"""
import json
import logging
from datetime import date as date_cls

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.analysis.impact_graph.consistency import check_alert_consistency
from app.analysis.impact_graph.publication_gate import (
    TIER_MACRO_CONTEXT,
    TIER_PRIMARY,
    TIER_SECONDARY_RIPPLE,
    derive_directness,
    is_displayable_tier,
    is_gated,
    is_secondary_tier,
)
from app.auth.dependencies import get_current_user, get_current_user_optional
from app.config import settings
from app.companies.branding import logo_url
from app.filtering.language_gate import is_english_text
from app.i18n import get_lang
from app.ingestion.image_filter import displayable_image_url, repeated_image_urls
from app.translation.lookup import (
    bulk_alert_company_whys,
    bulk_alert_summaries,
    bulk_article_titles,
    bulk_category_labels,
)
from app.ist_time import day_utc_window, today_ist
from app.market.alert_measurement import compute_alert_measurement
from app.market.discovery import (
    compute_materiality_feed,
    compute_related_to_holdings,
    compute_unusual_activity,
)
from app.market.cap_tier import cap_tier_map
from app.market.ripple_layers import compute_ripple_layers
from app.market.timeline_entries import get_timeline_entries
from app.models import Alert, AlertCompany, Article, Company, CompanyDecisionRecord, Holding, User
from app.routers.articles import get_db

# -- COMMENTED OUT (superseded by compute_ripple_layers, spec v2 §5/§7's
# layered card back -- the flat ripple list + separate impact_companies
# split is the old, pre-swipe-card UI's shape):
# from app.market.alert_measurement import compute_impact_companies
# from app.market.ripple import compute_ripple_companies

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feed-v2", tags=["feed-v2"])

ALERTS_LIMIT = 200


def _held_company_ids(db: Session, current_user: User | None) -> set[int]:
    if current_user is None:
        return set()
    return {h.company_id for h in db.query(Holding).filter_by(user_id=current_user.id).all()}


def _serialize(
    alert: Alert,
    measurement: dict,
    held_company_ids: set[int],
    repeated_images: set[str],
    translations: dict | None = None,
) -> dict:
    """``translations`` (optional): {"titles": {article_id: str},
    "summaries": {alert_id: (short, long)}, "categories": {category: str}}
    -- the bulk-lookup results for the request's lang; every field falls
    back silently to English (same discipline as routers/alerts.py)."""
    translations = translations or {}
    translated_title = translations.get("titles", {}).get(alert.article_id)
    summary_short, summary_long = translations.get("summaries", {}).get(
        alert.id, (None, None),
    )
    in_my_holdings = any(ac.company_id in held_company_ids for ac in alert.companies)
    return {
        "id": alert.id,
        "category": alert.category,
        # Translated display label for the category chip; English slug
        # (prettified frontend-side) when no translation exists.
        "category_label": translations.get("categories", {}).get(alert.category),
        "created_at": alert.created_at.isoformat(),
        "summary_short": summary_short or alert.summary_short,
        "summary_long": summary_long or alert.summary_long,
        "article": {
            "id": alert.article.id,
            # Generic publisher artwork (wire-service logos, newspaper
            # default banners) is nulled out -- the card shows no image
            # rather than a wrong one. See app.ingestion.image_filter.
            "image_url": displayable_image_url(alert.article.image_url, repeated_images),
            "title": translated_title or alert.article.title,
            "url": alert.article.url,
            "source": alert.article.source,
            "published_at": alert.article.published_at.isoformat() if alert.article.published_at else None,
        },
        "in_my_holdings": in_my_holdings,
        **measurement,
    }


def _unavailable_measurement() -> dict:
    """Measurement placeholder for a strict-mode alert whose price feed
    failed (spec §49, INV-015): the fundamental analysis stays visible;
    every market field is honestly null and the reaction object says
    'unavailable' -- never fabricated, never hidden."""
    return {
        "excess_move_pct": None, "direction": None, "raw_move_pct": None,
        "sector_move_pct": None, "volume_multiple": None,
        "benchmark_ticker": None, "is_fallback_benchmark": False,
        "peak_ticker": None, "peak_company_id": None, "peak_company_name": None,
        "verdict": None, "intensity": None, "breadth_score": None,
        "market_reaction": {
            "status": "unavailable", "direction": "unknown", "bar_complete": None,
            "raw_move_pct": None, "excess_move_pct": None, "benchmark_ticker": None,
            "benchmark_is_fallback": False, "data_quality": None,
            "session_state": None, "reaction_significance": "unknown",
        },
    }


# --- tier vocabulary (final blueprint §3/§7, Task 6) ----------------------
# This module used to keep its own `_SECONDARY_TIERS` literal tuple, which
# (a) had to be edited by hand every time a spelling was added or retired
# and (b) lumped `macro_context` in with the ripple tiers, which is exactly
# the conflation §7 forbids ("macro context must not become a company
# impact"). Membership is now read ONLY through the publication gate's own
# helpers -- `is_secondary_tier` (current + legacy ripple spellings) and
# `is_displayable_tier` -- the single place read-compat for the dead
# spellings lives.
#
# Section-kind prefixes T5 writes onto `relationship` (MECH:/RIPPLE:/MACRO:
# -- see app.market.ripple_layers._KIND_*). Restated here as literals
# because they are a WIRE contract, not an implementation detail: these
# three strings are what the API promises its clients, so this module must
# keep saying them even if the producer renames its internal constants.
# test_deep_dive_kinds_match_ripple_layers pins the two together, so such a
# rename surfaces as a failing test instead of a silently mis-filed section.
_KIND_PRIMARY = "MECH"
_KIND_RIPPLE = "RIPPLE"
_KIND_MACRO = "MACRO"

# Confidence-band read-compat (blueprint §18, ruling R4). Gated rows written
# by the V4 gate already speak the new four-value vocabulary; LEGACY rows
# carry the old Confidence-Engine vocabulary (LOW | MODERATE | HIGH |
# VERY_HIGH). The WIRE only ever speaks the new one, so the old values are
# mapped on the way out -- never rewritten in the database (the legacy
# /api/alerts surface still serves the raw legacy band next to its numeric
# confidence_score, which ruling R4 keeps for the old UI).
_BAND_ON_THE_WIRE = {
    "HIGH": "HIGH", "VERY_HIGH": "HIGH",
    "MEDIUM": "MEDIUM", "MODERATE": "MEDIUM",
    "LOW": "LOW", "UNKNOWN": "UNKNOWN",
}


def _wire_band(value: str | None) -> str:
    """The row's confidence band in the ONE vocabulary the API speaks.
    Anything absent or unrecognized is UNKNOWN -- "no band to display" is a
    real, honest state (§18), never a guess at LOW."""
    return _BAND_ON_THE_WIRE.get((value or "").strip().upper(), "UNKNOWN")


def _publication_tier(display_tier: str | None) -> str | None:
    """The row's tier in the canonical §3 spelling (T9's binding wire
    contract: primary | secondary_ripple | macro_context). A legacy
    ripple spelling ("secondary_deep_dive", "secondary") is normalized to
    `secondary_ripple` HERE so the frontend never has to know the dead
    names; None for an ungated/excluded row, which has no tier to claim.

    Case- and whitespace-insensitive, same as `_wire_band`: a persisted
    " Primary" from some hand-repaired row must serve the canonical tier,
    not silently degrade to None (which the frontend reads as "ungated")."""
    tier = (display_tier or "").strip().lower()
    if tier == TIER_PRIMARY:
        return TIER_PRIMARY
    if is_secondary_tier(tier):
        return TIER_SECONDARY_RIPPLE
    if tier == TIER_MACRO_CONTEXT:
        return TIER_MACRO_CONTEXT
    return None


def _event_scope(alert: Alert) -> str | None:
    """Blueprint §15's controlled article-level descriptor: "multi_sector"
    when this alert's analysis reaches more than one SECTOR, or carries ANY
    macro-context row (validated broad economic context is multi-sector by
    definition, §7); None otherwise. The frontend chooses the copy -- this
    is a label, not a sentence.

    Sectors, NOT mechanism taxonomy labels (review round 1, I3). The first
    implementation counted distinct section labels, and those are
    mechanism-grained: `upstream_realization` and `refiner_marketing_margin`
    are two labels inside ONE sector, so a pure oil story badged itself
    "Multi-sector impact". `Company.sector` is the grain the badge actually
    claims, and it is already loaded on every row -- this stays a
    deterministic in-memory read with no extra query, which is what lets the
    LIST route carry the label without assembling sections per alert.

    Computed over every DISPLAYABLE row (the deep-dive-complete view), not
    over whichever sections a given surface happens to render, so the list
    card, the detail card back and the deep dive all agree on one value for
    one alert. Ungated (legacy) alerts have no displayable tiers at all and
    always read None.
    """
    displayable = [ac for ac in alert.companies if is_displayable_tier(ac.display_tier)]
    if not displayable:
        return None
    if any(ac.display_tier == TIER_MACRO_CONTEXT for ac in displayable):
        return "multi_sector"
    # A row whose company carries no sector at all contributes nothing --
    # "unknown" is not a second sector (never fabricate breadth).
    sectors = {ac.company.sector for ac in displayable if ac.company.sector}
    return "multi_sector" if len(sectors) >= 2 else None


def _primary_company_ids(alert: Alert) -> set[int]:
    """The gate-authorized PRIMARY company ids on this alert (corrective-v4
    Task 16, spec §52). Empty for an alert with no primary company at all
    (ripple-only, macro-only or excluded-only)."""
    return {ac.company_id for ac in alert.companies if ac.display_tier == TIER_PRIMARY}


def _headline_company_ids(alert: Alert) -> tuple[set[int], str | None]:
    """(company ids the headline/peak calc may use, exposure label).

    Owner decision 2026-08-14 (supersedes the Task 16 "PRIMARY only, hide
    the rest" feed rule for the no-primary case): a gated alert whose gate
    produced ZERO primary companies but >=1 SECONDARY_RIPPLE company IS
    shown in the feed, headlined from its ripple movers, and explicitly
    labeled exposure="indirect_only" so the UI can badge it. The original
    discipline is fully preserved wherever a primary exists: ripple
    companies still never outrank or headline over a primary row
    (test_peak_ticker_ignores_bigger_secondary_mover pins that), and
    excluded-tier rows never surface anywhere.

    MACRO_CONTEXT rows are NEVER headline-eligible (blueprint §7, ruling
    R1): letting broad economic context supply the peak ticker/verdict IS
    "macro context becoming a company impact". A macro-only alert therefore
    yields an EMPTY id set (no measurement, so no headline number) and no
    exposure label at all -- it is not a company-exposure claim of either
    kind. It stays out of the feed list (`_strict_displayable` below) and
    remains reachable through detail / deep-dive.
    """
    primary = _primary_company_ids(alert)
    if primary:
        return primary, "primary"
    ripple = {ac.company_id for ac in alert.companies if is_secondary_tier(ac.display_tier)}
    if ripple:
        return ripple, "indirect_only"
    return set(), None


def _strict_displayable(alert: Alert) -> bool:
    """Owner ruling (corrective-v4 Task 16, carrying forward Task 12's
    structural discipline): once the gate's tier output is persisted on a
    row it is authoritative REGARDLESS of settings.impact_engine_v4_strict
    -- the same "structural, not modal" rule
    app.analysis.impact_graph.publication_gate.is_gated already applies to
    section rendering. Tier values only exist on rows the gate itself set,
    so this check is gate-scoped by construction; an ungated (legacy,
    all-NULL display_tier) alert always reads False, unchanged. Owner
    decision 2026-08-14: ripple rows count as displayable too (the feed
    labels those alerts exposure="indirect_only").

    MACRO_CONTEXT is deliberately NOT counted (blueprint §7, ruling R1): an
    alert whose ONLY gate output is macro context has no company-specific
    claim to headline, so it never enters the FEED LIST. It is not hidden --
    `_detail_servable` below keeps it reachable on the detail and deep-dive
    surfaces, where macro sections render as context and nothing else."""
    return any(
        ac.display_tier == TIER_PRIMARY or is_secondary_tier(ac.display_tier)
        for ac in alert.companies
    )


def _detail_servable(alert: Alert) -> bool:
    """Anything the gate authorized for display, macro context INCLUDED --
    the detail route's wider door (see `_strict_displayable`)."""
    return any(is_displayable_tier(ac.display_tier) for ac in alert.companies)


# --- ripple-layer row payloads (blueprint §22/§28, rulings R1/R4) ---------

def _row_channel_effects(alert_company) -> list[str]:
    """The EFFECTS behind one row's net call, for §24's net-effect validator
    (the serving-boundary twin of `app.pipeline._entry_channel_effects` --
    same rule, read off the persisted row instead of a pre-persist entry
    dict; deliberately not imported, because a request handler must not pull
    in the whole analysis pipeline module to read one JSON column).
    `channels_json` stores channel DESCRIPTIONS in two signed buckets, so
    each channel's effect is the bucket it sits in; no channels at all is
    silence, which §24 abstains on rather than reading as a contradiction."""
    raw = getattr(alert_company, "channels_json", None)
    if not raw:
        return []
    try:
        channels = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(channels, dict):
        return []
    return (["positive"] * len(channels.get("positive_channels") or [])
            + ["negative"] * len(channels.get("negative_channels") or []))


def _decorate_rows(alert: Alert, layers: list[dict]) -> list[dict]:
    """Add the five-dimension display fields (§3/§22/§28) to every GATED
    ripple-layer row, in place, and return `layers`.

    Rows on an UNGATED (legacy) alert are left byte-identical: they carry no
    tier, no directness and no edge relation, and inventing "INDIRECT" for
    them would be fabricating the very dimension §11 exists to keep honest.
    """
    alert_company_by_id = {ac.id: ac for ac in alert.companies}
    for layer in layers:
        for row in layer.get("rows") or []:
            alert_company = alert_company_by_id.get(row.get("alert_company_id"))
            if alert_company is None or alert_company.display_tier is None:
                continue
            # §11: directness is a SEPARATE dimension from causal distance.
            # `derive_directness` is the gate's own resolution order
            # (explicit column -> mechanism registry -> distance), so the
            # served value can never disagree with the graded one.
            row["causal_directness"] = derive_directness(alert_company)
            row["publication_tier"] = _publication_tier(alert_company.display_tier)
            row["edge_relation"] = alert_company.edge_relation
            row["confidence_band"] = _wire_band(alert_company.confidence_band)
            # Ruling R4: the band IS the confidence on this surface. A
            # numeric score (the 49-for-everyone fake precision) must never
            # ride along on a feed-v2 row; the legacy /api/alerts payload
            # keeps it for the old UI. Defensive: no producer sets it today,
            # and this is what stops one from quietly starting to.
            row.pop("confidence_score", None)
    return layers


def _consistency_shape(alert: Alert, layers: list[dict], headline_ticker: str | None) -> dict:
    """§24's alert-shaped input, built from the rows ABOUT TO BE SERVED (not
    from the DB rows in the abstract) -- the serving half of "before
    persistence and before serving". Only gate-evaluated rows are described:
    a legacy row has no tier and no economic effect to be inconsistent
    with, and reporting the whole pre-gate corpus as violations would block
    exactly the alerts the check protects."""
    alert_company_by_id = {ac.id: ac for ac in alert.companies}
    companies = []
    for layer in layers:
        for row in layer.get("rows") or []:
            alert_company = alert_company_by_id.get(row.get("alert_company_id"))
            if alert_company is None or not alert_company.display_tier:
                continue
            companies.append({
                "ticker": row.get("ticker"),
                "economic_effect": row.get("economic_effect"),
                "direction": row.get("direction"),
                "display_tier": alert_company.display_tier,
                "channel_effects": _row_channel_effects(alert_company),
            })
    return {"companies": companies, "headline_ticker": headline_ticker,
            "headline_tier_source": None}


def _validated_layers(alert: Alert, layers: list[dict],
                      headline_ticker: str | None = None) -> tuple[list[dict], set[str]]:
    """Pre-serve consistency enforcement (blueprint §24): run the SAME
    deterministic gate the pipeline runs before persistence, now over the
    serialized rows, and refuse to serve any COMPANY row it finds
    contradictory -- the Oil India shape (company bearish, every validated
    channel bullish) never reaches a reader even if it somehow reached the
    database (a stale worker, a hand-edited row, a restore from a pre-0008
    backup whose triggers were dropped).

    Dropped, not repaired and not fatal: a contradiction means the system
    does not know which of two claims is true, so the wrong claim is
    withheld and everything else on the alert still serves. Every violation
    is logged at ERROR verbatim -- silence here would turn a data-integrity
    incident into a mysteriously short card.

    A HEADLINE violation is logged but drops nothing: the headline is
    chosen from the tier sets by `_headline_company_ids`, so a violation
    there is a bug in THIS module, and blanking the card would hide it.

    Returns (layers, dropped tickers). The caller MUST act on the second
    element when it is non-empty (review round 1, I1): the alert-level
    measurement was computed from a company set that still contained the
    withheld row, so a dropped PEAK company would otherwise leave the
    payload headlining a company whose row is not being served -- the same
    claim, withheld in one place and shouted in another.
    """
    if not is_gated(alert.companies):
        return layers, set()
    violations = check_alert_consistency(_consistency_shape(alert, layers, headline_ticker))
    if not violations:
        return layers, set()
    bad_tickers = {v.split(":", 1)[0].strip() for v in violations} - {"HEADLINE"}
    logger.error(
        "PRE-SERVE CONSISTENCY VIOLATION alert_id=%s dropped_rows=%s violations=%s",
        alert.id, sorted(bad_tickers), "; ".join(violations),
    )
    if not bad_tickers:
        return layers, set()
    kept = []
    for layer in layers:
        rows = [row for row in (layer.get("rows") or []) if row.get("ticker") not in bad_tickers]
        if not rows:
            continue                       # a section emptied by the drop
        layer["rows"] = rows
        kept.append(layer)
    return kept, bad_tickers


def _measurement_without(db: Session, alert: Alert, company_ids: set[int] | None,
                         dropped_tickers: set[str]) -> dict:
    """The alert-level headline number RE-DERIVED over the rows that
    survived §24's pre-serve gate (review round 1, I1/M7).

    The headline is a claim about a company, so it may only ever come from
    a company whose row is actually being served. When every survivor is
    ineligible (or the whole alert was withheld) the honest answer is the
    unavailable-measurement placeholder: a card with no rows must not carry
    a peak ticker, an excess move or a verdict."""
    dropped_ids = {ac.company_id for ac in alert.companies
                   if ac.company.ticker in dropped_tickers}
    eligible = ({ac.company_id for ac in alert.companies} if company_ids is None
                else set(company_ids)) - dropped_ids
    remeasured = (compute_alert_measurement(db, alert, company_ids=eligible)
                  if eligible else None)
    return remeasured if remeasured is not None else _unavailable_measurement()


def _query_with_relations(db: Session):
    return db.query(Alert).options(
        selectinload(Alert.article),
        selectinload(Alert.companies).selectinload(AlertCompany.company),
    )


def _bulk_translations(db: Session, alerts: list[Alert], lang: str) -> dict:
    """Three bulk lookups total regardless of alert count (same pattern as
    routers/alerts.py) -- all empty (silent English) when lang == 'en'."""
    return {
        "titles": bulk_article_titles(db, [a.article_id for a in alerts], lang),
        "summaries": bulk_alert_summaries(db, [a.id for a in alerts], lang),
        "categories": bulk_category_labels(db, list({a.category for a in alerts}), lang),
    }


@router.get("")
def list_feed_v2_alerts(
    date: str | None = None,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
    lang: str = Depends(get_lang),
):
    """The card feed. ``date`` (YYYY-MM-DD, IST day) reopens a previous
    day's news -- the calendar mechanism (spec v2 keeps it: any day is a
    complete feed). Defaults to today."""
    if date is not None:
        try:
            day = date_cls.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    else:
        day = today_ist()
    start_utc, end_utc = day_utc_window(day)
    query = (
        _query_with_relations(db)
        .filter(Alert.created_at >= start_utc, Alert.created_at < end_utc)
    )
    # Demo-seeded stories (seed_feed_v2_demo.py's URL marker) never reach
    # the production feed. ALLOW_DEMO_FEED=true opts a non-production
    # service (e.g. a UI-preview deployment sharing this database) back
    # in for testing.
    if not settings.allow_demo_feed:
        query = query.join(Alert.article).filter(~Article.url.like("https://demo.feed-v2.local/%"))
    alerts = query.order_by(Alert.created_at.desc()).limit(ALERTS_LIMIT).all()
    held_company_ids = _held_company_ids(db, current_user)
    translations = _bulk_translations(db, alerts, lang)

    # Peak company's cap tier -- drives the top-bar cap filter on the card
    # feed (spec v2 §6: "Provide a cap-tier filter (All / Large / Mid /
    # Small / Micro)") without computing full layers per alert. One ranking
    # pass for the whole list, derived fresh (spec §3.2).
    cap_tiers = cap_tier_map(db)

    repeated_images = repeated_image_urls(db, [a.article.image_url for a in alerts if a.article.image_url])

    results = []
    for alert in alerts:
        # English-only feed (the base language is uniform; other languages
        # come from the user's translation picker) -- drops the foreign-
        # language wire mirrors ingested before the language gate shipped.
        if not is_english_text(alert.article.title):
            continue
        # Headline scope (spec §52 as amended by the 2026-08-14 owner
        # decision): a gated alert's peak/verdict/intensity/breadth comes
        # from its PRIMARY companies when any exist; a no-primary gated
        # alert headlines from its secondary/deep-dive movers and is
        # labeled exposure="indirect_only". Excluded rows never headline.
        # Ungated (legacy) alerts pass None (unchanged: every measured
        # company is still eligible) and carry no exposure label.
        exposure = None
        company_ids = None
        if is_gated(alert.companies):
            company_ids, exposure = _headline_company_ids(alert)
        measurement = compute_alert_measurement(db, alert, company_ids=company_ids)
        if measurement is None and _strict_displayable(alert):
            measurement = _unavailable_measurement()
        if measurement is not None:
            row = _serialize(alert, measurement, held_company_ids, repeated_images, translations)
            row["exposure"] = exposure
            # §15's controlled breadth descriptor -- computed from the rows
            # already loaded on the alert, never by assembling sections (the
            # list route must stay one measurement pass per alert).
            row["event_scope"] = _event_scope(alert)
            row["peak_cap_tier"] = cap_tiers.get(measurement["peak_ticker"])
            # Distinct tiers across ALL tagged companies -- the top-bar cap
            # filter shows a story when any affected company sits in the
            # chosen tier, not only the peak mover. Companies without an
            # honest tier (stale/absent cap) contribute nothing.
            row["cap_tiers"] = sorted(
                {tier for ac in alert.companies if (tier := cap_tiers.get(ac.company.ticker))}
            )
            results.append(row)
    # PREVIEW-ONLY (this branch): in-memory demo stories appended when
    # ALLOW_DEMO_FEED=true -- set only on the newsflo-v2 preview service.
    # No demo rows exist in the shared database; the main service never
    # sets the flag and master never carries this code path.
    if settings.allow_demo_feed and date is None:
        from app.routers.feed_v2_demo_inject import demo_feed_rows

        results.extend(demo_feed_rows(db))
    return results


# NOTE: static paths (/discovery/..., /portfolio) are declared BEFORE the
# catch-all /{alert_id} route -- FastAPI matches in declaration order, and
# "/portfolio" would otherwise 422 against the int alert_id parser.
@router.get("/discovery/{tab}")
def get_discovery(
    tab: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Discovery paths (spec v2 §6): materiality / holdings / unusual.
    Factual framing only -- "most affected by news", never "best to buy"."""
    if tab == "materiality":
        return compute_materiality_feed(db)
    if tab == "holdings":
        return compute_related_to_holdings(db, current_user)
    if tab == "unusual":
        return compute_unusual_activity(db)
    raise HTTPException(status_code=404, detail="Unknown discovery tab")


@router.get("/portfolio")
def get_portfolio_overlay(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Portfolio overlay (spec v2 §2 portfolio dot / §8): the user's
    holdings and which of today's alerts touches each. Requires login --
    holdings are sensitive (spec §9)."""
    start_utc, end_utc = day_utc_window(today_ist())
    holdings = (
        db.query(Holding, Company)
        .join(Company, Holding.company_id == Company.id)
        .filter(Holding.user_id == current_user.id)
        .order_by(Company.name.asc())
        .all()
    )
    todays_alert_companies = (
        db.query(AlertCompany, Alert)
        .join(Alert, AlertCompany.alert_id == Alert.id)
        .filter(Alert.created_at >= start_utc, Alert.created_at < end_utc)
        .order_by(Alert.created_at.desc())
        .all()
    )
    latest_alert_by_company_id: dict[int, Alert] = {}
    for alert_company, alert in todays_alert_companies:
        latest_alert_by_company_id.setdefault(alert_company.company_id, alert)

    results = []
    for holding, company in holdings:
        alert = latest_alert_by_company_id.get(company.id)
        results.append({
            "ticker": company.ticker,
            "name": company.name,
            "quantity": holding.quantity,
            "logo_url": logo_url(company),
            "affected_alert_id": alert.id if alert else None,
            "affected_headline": (alert.summary_short or alert.article.title) if alert else None,
        })
    return {
        "holdings": results,
        "affected_count": sum(1 for r in results if r["affected_alert_id"] is not None),
    }


# NOTE: declared before the catch-all /{alert_id} for the same reason as
# /discovery/{tab} and /portfolio above -- though in this case it wouldn't
# actually collide anyway (the extra "/deep-dive" segment means /{alert_id}
# alone never matches this URL shape), declaring the more specific path
# first keeps the file's ordering convention consistent and obviously safe.
@router.get("/{alert_id}/deep-dive")
def get_feed_v2_deep_dive(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Explicit deep-dive surface (spec §52, corrective-v4 Task 16, owner
    decision, verbatim): "/api/feed-v2 -> PRIMARY only; /api/feed-v2/{id}/
    deep-dive -> optional PRIMARY + SECONDARY_DEEP_DIVE + rejected-summary."
    A gated-analysis-only surface: an ungated (legacy, pre-gate) alert has
    no gate/tier/rejection data to show here at all, so it 404s rather than
    silently returning an empty shell -- the normal feed-v2 detail route
    stays the place a legacy alert is served from. {primary, secondary,
    macro} reuse compute_ripple_layers' section shape (same "title"/
    "relationship"/"icon"/"note"/"rows" dicts the card back already
    renders), split out of ONE ripple-layers computation rather than
    re-fetched, so the three families are guaranteed mutually consistent.
    rejected_summary is the machine-readable audit trail (why a candidate
    never reached ANY display tier) from CompanyDecisionRecord -- REJECT_*
    rows for this alert only.

    Task 6: the split now keys on T5's section KIND prefix. It used to test
    `relationship != "SECONDARY"` against the single anonymous bucket T5
    deleted -- with that bucket gone, every RIPPLE: and MACRO: section fell
    into "primary", i.e. the deep dive presented indirect and macro-context
    rows as the alert's primary claim. "secondary" is now the (plural)
    RIPPLE: sections and "macro" is the new MACRO: family, which §7 keeps
    separate precisely so it is never read as a company-specific claim."""
    alert = _query_with_relations(db).filter(Alert.id == alert_id).first()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not is_gated(alert.companies):
        raise HTTPException(status_code=404, detail="Deep dive is only available for gate-analyzed alerts")

    held_company_ids = _held_company_ids(db, current_user)
    # No headline number on this surface, so nothing to re-derive when the
    # §24 gate withholds a row -- the dropped-ticker set is deliberately
    # unused here (the detail route below is where it matters).
    sections, _dropped = _validated_layers(
        alert,
        _decorate_rows(
            alert, compute_ripple_layers(db, alert, held_company_ids, include_secondary=True),
        ),
    )

    def _kind(section: dict) -> str:
        return (section.get("relationship") or "").split(":")[0]

    primary_sections = [s for s in sections if _kind(s) == _KIND_PRIMARY]
    secondary_sections = [s for s in sections if _kind(s) == _KIND_RIPPLE]
    macro_sections = [s for s in sections if _kind(s) == _KIND_MACRO]

    rejected = (
        db.query(CompanyDecisionRecord)
        .filter(
            CompanyDecisionRecord.alert_id == alert_id,
            CompanyDecisionRecord.final_state.like("REJECT_%"),
        )
        .order_by(CompanyDecisionRecord.ticker.asc())
        .all()
    )
    return {
        "primary": primary_sections,
        "secondary": secondary_sections,
        "macro": macro_sections,
        "event_scope": _event_scope(alert),
        "rejected_summary": [
            {
                "ticker": r.ticker,
                "rejection_reason": r.rejection_reason,
                "materiality_grade": r.materiality_grade,
            }
            for r in rejected
        ],
    }


@router.get("/{alert_id}")
def get_feed_v2_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
    lang: str = Depends(get_lang),
):
    # PREVIEW-ONLY (this branch): negative ids are in-memory demo alerts.
    if alert_id < 0 and settings.allow_demo_feed:
        from app.routers.feed_v2_demo_inject import demo_alert_detail

        payload = demo_alert_detail(db, alert_id)
        if payload is not None:
            return payload
    alert = _query_with_relations(db).filter(Alert.id == alert_id).first()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    # Headline scope -- same discipline as the list route above (spec §52
    # as amended by the 2026-08-14 owner decision: no-primary gated alerts
    # headline from secondary movers, labeled exposure="indirect_only").
    exposure = None
    company_ids = None
    if is_gated(alert.companies):
        company_ids, exposure = _headline_company_ids(alert)
    measurement = compute_alert_measurement(db, alert, company_ids=company_ids)
    if measurement is None:
        # Wider than the list route's `_strict_displayable` on purpose
        # (§7/ruling R1): a MACRO-CONTEXT-only alert never enters the feed
        # list -- it has no company-specific claim to headline -- but it is
        # not hidden either. It serves here, and on the deep dive, as
        # context with an honestly unavailable measurement.
        if _detail_servable(alert):
            measurement = _unavailable_measurement()
        else:
            raise HTTPException(status_code=404, detail="Alert has no measured companies")

    held_company_ids = _held_company_ids(db, current_user)
    # Layered card back (spec v2 §5/§7): every affected company, grouped by
    # relationship into ordered winners/losers layers. For a gated alert
    # WITH a primary the card back stays PRIMARY-only (corrective-v4 Task
    # 16, spec §52) -- secondary companies live on GET
    # /api/feed-v2/{id}/deep-dive. For a no-primary gated alert (owner
    # decision 2026-08-14) the card back IS the ripple/macro sections --
    # without include_secondary the card would be an empty shell. Keyed on
    # "this alert has no primary row" rather than on exposure ==
    # "indirect_only", so a MACRO-CONTEXT-only alert (which carries no
    # exposure label at all, §7) still renders its context sections instead
    # of an empty card back. No effect on an ungated (legacy) alert's
    # 3-tier rendering, which ignores the flag entirely.
    #
    # Then, in order: the five-dimension row fields (§22/§28) and the §24
    # pre-serve consistency gate, which withholds any row whose served
    # claim contradicts itself. The list route deliberately runs neither --
    # it serves no rows, and row consistency is already enforced at
    # persistence (pipeline) and at the DB (0008's gated-row triggers).
    layers, dropped_tickers = _validated_layers(
        alert,
        _decorate_rows(alert, compute_ripple_layers(
            db, alert, held_company_ids, include_secondary=(exposure != "primary"),
        )),
        headline_ticker=measurement.get("peak_ticker"),
    )
    if dropped_tickers:
        # I1: the headline was computed BEFORE the gate ran, from a company
        # set that still contained the withheld row. Re-derive it over the
        # survivors so the payload can never headline a company whose row it
        # is refusing to serve (and so an all-rows-withheld alert carries no
        # peak/verdict at all, M7).
        measurement = _measurement_without(db, alert, company_ids, dropped_tickers)

    repeated_images = repeated_image_urls(
        db, [alert.article.image_url] if alert.article.image_url else [],
    )
    translations = _bulk_translations(db, [alert], lang)
    result = _serialize(alert, measurement, held_company_ids, repeated_images, translations)
    result["exposure"] = exposure
    result["event_scope"] = _event_scope(alert)
    # Alert-level quality ladder (corrective-v4 Task 15): authoritative |
    # fallback | degraded | failed | budget_exhausted, or None on a
    # pre-v3 alert. Frontend consumption is a later task; this is the
    # minimal, honest wire-through.
    result["analysis_quality"] = alert.analysis_quality
    result["layers"] = layers
    # Translated per-company `why` overlay (silent English fallback).
    whys = bulk_alert_company_whys(
        db, [row["alert_company_id"] for layer in result["layers"] for row in layer["rows"]], lang,
    )
    for layer in result["layers"]:
        for row in layer["rows"]:
            translated_why = whys.get(row["alert_company_id"])
            if translated_why and row["why"]:
                row["why"] = translated_why
    result["timeline"] = get_timeline_entries(db, alert)
    # Derivation edges for the ripple network chart: who each company was
    # derived FROM in the cascade (AlertCompany.parent_company_id) --
    # direct companies hang off the news event itself. Real analysed
    # relationships only, never invented pairings.
    result["edges"] = [
        {
            "source": ac.parent_company.ticker if ac.parent_company_id else None,
            "target": ac.company.ticker,
            "relation": ac.impact_level or "direct",
        }
        for ac in alert.companies
    ]
    # -- COMMENTED OUT (superseded by result["layers"] above -- the old flat
    # ripple + impact_companies split served the pre-swipe-card UI):
    # result["ripple"] = compute_ripple_companies(
    #     db, alert, exclude_company_id=measurement["peak_company_id"], held_company_ids=held_company_ids,
    # )
    # result["impact_companies"] = compute_impact_companies(db, alert)
    return result
