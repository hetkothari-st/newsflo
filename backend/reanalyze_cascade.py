"""One-off: fully re-analyze the N most recently created alerts using the
current sector-cascade pipeline (app.analysis.cascade), REPLACING each
alert's companies entirely -- including real indirect_l1/indirect_l2
cascade rows the fresh analysis finds that the original alert never had.

Unlike reanalyze_recent.py (which only refreshes rationale/key_points text
on companies already present in the alert and never adds/removes rows),
this script deletes the alert's existing AlertCompany rows and re-persists
a fresh set via app.pipeline._build_alert_company -- the same calibration/
confidence logic process_new_articles uses for a brand new article, reused
directly rather than duplicated, so this can't drift from the live
pipeline's behavior. Existing ImpactEdge/CascadeGap rows for the alert are
also deleted and replaced with the fresh analysis's edges/gaps, using the
same app.pipeline._resolve_edge_endpoint_company_id ticker-resolution
helper _persist_alert itself uses -- without this, the graph API (GET
/api/alerts/{id}) would keep serving edges from before this run.

The Alert row itself (id, created_at, article_id) is left untouched --
only its companies are replaced -- so existing links/bookmarks to this
alert id keep working. Any existing AlertCompanyTranslation rows for the
deleted companies are deleted too (a FK requires it) -- they regenerate
on-demand the next time that alert is viewed in a non-English language.

Prints a before/after company list per alert, including which impact
levels appeared, so there's a console record of what changed.

Grounded the same way the live pipeline is: passes ``session=`` to
analyze_article (candidate list + ticker enum -- without it this script
reanalyzes ungrounded and reproduces the exact pre-fix hallucination
behavior the precision work exists to remove) and builds the same
anchor_sub_sectors map process_new_articles does (via
app.pipeline.build_anchor_sub_sectors) before calling resolve_companies, so
a sector's fan-out is anchored to the sub-sectors of the companies actually
named, not the whole sector.

Not part of the test suite and not imported by the app.

Usage (from the backend/ directory, against whichever DATABASE_URL is
active in the environment -- e.g. `railway run python reanalyze_cascade.py`
to run against production):
    .venv/Scripts/python reanalyze_cascade.py [N] [--days DAYS] [--force] [--allow-empty]
    .venv/Scripts/python reanalyze_cascade.py --alert-id 1447 [--alert-id 1502]

--days restricts to alerts created in the last N days. When --days is given
without an explicit N positional, the count limit is dropped entirely (every
alert in the window is reanalyzed); pass an explicit N alongside --days to
cap both. --force clears the cached analysis first; without it,
get_cached_analysis returns whatever was cached under the article's content
hash by an earlier (possibly pre-fix) run and this script silently changes
nothing.

--alert-id (repeatable) reanalyzes exactly the given alert id(s) and nothing
else, ignoring the positional limit/--days window entirely -- it is a hard
error (argparse) to combine --alert-id with either of them. Because the
whole point of targeting a specific alert is usually to verify a pipeline
fix against it, --alert-id always clears that alert's cached analysis first
(equivalent to an implicit --force for just that alert) -- otherwise
get_cached_analysis would replay the stale pre-fix result under the
article's content hash and this run would silently change nothing. A
nonexistent id is reported and skipped rather than raising.

EMPTY-RESULT GUARD (--allow-empty)
----------------------------------
The replacement is transactional in ordering: the fresh analysis is computed
AND resolved to a concrete company list BEFORE a single existing row is
deleted. Nothing between the entry to reanalyze_alert and the `resolved`
list touches this alert's rows, so any failure in that span -- a raised
stage, a resolution error -- leaves the existing companies fully intact.

On top of that ordering there is a conditional refusal. analyze_article does
NOT raise when a middle stage fails: it truncates and returns whatever the
earlier stages produced. A stage-3 (primary companies) failure therefore
returns a perfectly well-formed AnalysisOutput whose companies list is
empty, which at this call site is indistinguishable from "this article
genuinely affects no listed company". Confirmed in production on alert 1447:
a stochastic forced-tool-call failure (the class app.analysis.cascade's
TOOL_CALL_ATTEMPTS retry now absorbs) made this script replace 3 good
companies -- and their calibration/outcome history -- with 0.

So: a fresh analysis resolving to ZERO companies over an alert that
currently HAS companies is refused. The alert is left exactly as it was and
the skip is printed distinctly from the normal "company count: N -> M" line.
--allow-empty overrides this for the case where zero genuinely is the
correct new answer and the operator wants it written; it is off by default
because a wrong "yes" here is irreversible and a wrong "no" costs one re-run.

PARTIAL/TRUNCATED ANALYSES: a truncation that loses SOME but not all
companies (say stage 4/6 fails, so L1/L2 cascade companies are missing) is
NOT distinguishable from a genuinely smaller correct answer at this call
site. AnalysisOutput carries no truncation marker -- stage failures inside
analyze_article are only logged -- and result.gaps covers only per-sector
cascade-company failures, not whole-stage ones. The conservative choice
taken here is deliberately asymmetric: only the total wipe (N > 0 -> 0) is
blocked, while any smaller shrink is written and merely FLAGGED with a
"NOTE: this alert SHRANK" line. Blocking every shrink was rejected because
shrinking is the intended effect of this script -- the whole precision
effort exists to strip hallucinated companies out of over-broad alerts, so
a rule that refused to write a smaller set would refuse nearly every correct
reanalysis and make the tool useless. Zero is the one size that is almost
never a real improvement over a non-empty set, so it is the one that is
gated. Operators reviewing a bulk run should read the SHRANK lines; a
sharp, unexplained drop is worth re-running with --force before trusting it.

IRREVERSIBLE: reanalyzing an alert (bulk or --alert-id) deletes that
alert's existing AlertCompany rows and everything that references them --
including CalibrationSample and CarOutcome history used for confidence
calibration -- before persisting the fresh analysis. It also deletes the
alert's existing MarketMove rows outright (they key on alert_id/company_id
directly, not alert_company_id, so they are not covered by
ALERT_COMPANY_DEPENDENTS) and re-measures the fresh company set via
app.pipeline.measure_and_reconcile_alert_companies -- the same measure +
direction-reconciliation step _persist_alert runs for a brand new alert,
shared rather than duplicated so this can't drift from the live pipeline.
This is intentional (stale companies -- and stale measurements pointing at
companies this alert no longer has -- must not linger alongside fresh
ones) but there is no undo; the deleted calibration/outcome history is
gone, and the old measurements are replaced by freshly measured ones
(which can differ from the old numbers -- price data moves day to day).
Without the re-measurement, a reanalyzed alert would have zero MarketMove
rows, which drops it out of GET /api/feed-v2 entirely (see
app/routers/feed_v2.py, which requires a peak MarketMove to include an
alert in the feed) -- confirmed happening in production for alert 1447.
"""
import argparse
from datetime import timedelta

from app.analysis.cascade import analyze_article
from app.analysis.claude_client import build_client
from app.companies.integrity import ALERT_COMPANY_DEPENDENTS
from app.companies.resolution import resolve_companies
from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Alert, CascadeGap, Company, ImpactEdge, MarketMove, utcnow
from app.pipeline import (
    _build_alert_company, _resolve_edge_endpoint_company_id, article_text,
    build_anchor_sub_sectors, clear_analysis_cache, get_cached_analysis,
    measure_and_reconcile_alert_companies, store_analysis_cache,
)


def _basis_counts(companies) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in companies:
        counts[c.basis] = counts.get(c.basis, 0) + 1
    return counts


def reanalyze_alert(session, client, alert: Alert, force: bool, allow_empty: bool = False) -> None:
    """Fully re-analyze a single alert via the live pipeline's grounded
    analyze_article + build_anchor_sub_sectors + resolve_companies path,
    replacing its AlertCompany/ImpactEdge/CascadeGap rows in place.

    Shared by both the bulk (limit/--days) loop and the --alert-id path in
    main() below so the two entry points can't drift from each other -- see
    the module docstring for why grounding and the dependents cleanup matter.

    The replacement is transactional and conditional (see the EMPTY-RESULT
    GUARD section of the module docstring): nothing is deleted until the
    fresh analysis has been computed AND resolved all the way to a concrete
    company list, and a resolved list of ZERO companies over an alert that
    currently HAS companies is treated as a suspected stochastic failure and
    skipped unless allow_empty is set.
    """
    article = alert.article
    print(f"\n=== Alert {alert.id}: {article.title} ===")
    before_companies = list(alert.companies)
    before_count = len(before_companies)
    before_basis = _basis_counts(before_companies)
    old_summary = [(c.company.ticker, c.impact_level) for c in before_companies]
    print(f"  BEFORE: {old_summary}")

    # ---- Compute the whole new answer FIRST, before deleting anything. ----
    # Every step from here to the resolved list is read-only with respect to
    # this alert's rows. An exception (or an empty result) below therefore
    # leaves the existing companies exactly as they were: the delete block
    # further down is only reached once `resolved` is a committed decision.
    if force:
        clear_analysis_cache(session, article)
    result = get_cached_analysis(session, article)
    if result is not None:
        print("  (using cached analysis -- pass --force for a fresh LLM call)")
    else:
        try:
            result = analyze_article(client, article.title, article_text(article), session=session)
        except Exception as exc:
            # A raised stage leaves the alert untouched -- nothing has been
            # deleted at this point, by construction.
            print(f"  SKIPPED (analysis call failed: {exc}) -- existing {before_count} compan"
                  f"{'y' if before_count == 1 else 'ies'} left untouched")
            return
        store_analysis_cache(session, article, result)

    anchor_sub_sectors = build_anchor_sub_sectors(session, result.companies)
    resolved = resolve_companies(session, result.companies, anchor_sub_sectors=anchor_sub_sectors)

    if not resolved and before_count > 0 and not allow_empty:
        # THE DATA-LOSS GUARD. analyze_article does not raise when a middle
        # stage fails -- it truncates and returns whatever earlier stages
        # produced, which for a stage-3 (primary companies) failure is an
        # AnalysisOutput with an empty companies list. Indistinguishable, at
        # this call site, from "this article genuinely affects nobody".
        # Confirmed live on alert 1447: a stochastic forced-tool-call failure
        # (see app.analysis.cascade's TOOL_CALL_ATTEMPTS) replaced 3 good
        # companies with 0. Refuse the replacement and say so loudly.
        print(f"  SKIPPED (fresh analysis resolved to ZERO companies but this alert "
              f"has {before_count} -- suspected stage failure, NOT replacing). "
              f"Re-run with --allow-empty if zero is genuinely correct.")
        return

    old_company_ids = [ac.id for ac in alert.companies]
    if old_company_ids:
        # Every table that references alert_companies.id via
        # alert_company_id must be cleared before the alert_companies
        # rows themselves are deleted below -- ALERT_COMPANY_DEPENDENTS
        # is the single source of truth for that table list (see
        # app.companies.integrity's module comment). An earlier version
        # of this loop cleared only AlertCompanyTranslation, leaving
        # CalibrationSample/CarOutcome/EmailNotification rows dangling:
        # invisible on SQLite (FK enforcement off by default), a
        # ForeignKeyViolation mid-run on Postgres.
        for model in ALERT_COMPANY_DEPENDENTS:
            session.query(model).filter(
                model.alert_company_id.in_(old_company_ids),
            ).delete(synchronize_session=False)
    for ac in list(alert.companies):
        session.delete(ac)
    # Edges/gaps from a prior real analysis (Phase 3) must also be
    # replaced, not left stale -- they'd otherwise reference companies
    # this alert no longer has, showing a graph that doesn't match the
    # fresh companies[] list.
    session.query(ImpactEdge).filter_by(alert_id=alert.id).delete(synchronize_session=False)
    session.query(CascadeGap).filter_by(alert_id=alert.id).delete(synchronize_session=False)
    # MarketMove references alert_id/company_id directly, not
    # alert_company_id -- it is NOT in ALERT_COMPANY_DEPENDENTS and is not
    # touched by the AlertCompany delete above. Left alone, a reanalysis
    # that drops a company (or replaces the resolved set entirely) orphans
    # that company's MarketMove row for this alert: no AlertCompany will
    # ever again match its company_id. Confirmed live: reanalyzing alert
    # 1447 left 53 such orphans, one of which crashed
    # compute_alert_measurement's bare next() (app.market.alert_measurement)
    # with StopIteration -- a 500 on GET /api/feed-v2. Deleted here and
    # recreated below via app.pipeline.measure_and_reconcile_alert_companies
    # -- the same measurement call _persist_alert makes for a brand new
    # alert -- so a reanalyzed alert isn't left with no MarketMove rows (and
    # therefore invisible to GET /api/feed-v2, which requires a peak
    # MarketMove to include an alert at all; see app/routers/feed_v2.py).
    session.query(MarketMove).filter_by(alert_id=alert.id).delete(synchronize_session=False)
    session.flush()

    alert_companies = []
    for entry in resolved:
        # _build_alert_company now returns (alert_company,
        # pre_multiplier_score) -- see app.pipeline.CONFIDENCE_FLOOR's
        # comment. This script has never applied the confidence floor
        # (unlike the live pipeline's _persist_alert), so the score is
        # simply discarded here, matching this script's existing
        # behavior of persisting every resolved entry.
        alert_company, _pre_multiplier_score = _build_alert_company(session, alert.id, article, result.category, entry)
        session.add(alert_company)
        alert_companies.append(alert_company)
    # Same measure + reconcile step _persist_alert runs for a brand new
    # alert: measures each fresh company's market reaction and reconciles
    # its `direction` to the REAL measured move (clearing rationale/
    # key_points on a flip) -- see measure_and_reconcile_alert_companies's
    # docstring. Without this, a reanalyzed alert's directions can disagree
    # with a freshly-analyzed alert's, and (per the MarketMove comment
    # above) the alert vanishes from the feed entirely.
    session.flush()
    measure_and_reconcile_alert_companies(session, alert.id, alert_companies)
    for edge in result.edges:
        from_company_id = _resolve_edge_endpoint_company_id(session, edge["from"]["kind"], edge["from"]["label"])
        to_company_id = _resolve_edge_endpoint_company_id(session, edge["to"]["kind"], edge["to"]["label"])
        from_label = edge["from"]["label"]
        # Same ground-truth-sector fix as app.pipeline._persist_alert --
        # see its comment. Duplicated here because this script persists
        # edges independently rather than calling _persist_alert.
        if edge["from"]["kind"] == "sector" and edge["to"]["kind"] == "company" and to_company_id is not None:
            company = session.get(Company, to_company_id)
            if company is not None and company.sector:
                from_label = company.sector
        session.add(ImpactEdge(
            alert_id=alert.id,
            from_company_id=from_company_id,
            from_node_kind=edge["from"]["kind"], from_label=from_label,
            to_company_id=to_company_id,
            to_node_kind=edge["to"]["kind"], to_label=edge["to"]["label"],
            relation=edge["relation"], direction=edge["direction"], note=edge["note"], source=edge["source"],
        ))
    for gap in result.gaps:
        session.add(CascadeGap(
            alert_id=alert.id, sector=gap["sector"], impact_level=gap["impact_level"],
            parent_ticker=gap.get("parent_ticker"), attempts=gap["attempts"], last_error=gap.get("last_error"),
        ))
    session.commit()

    session.refresh(alert)
    after_companies = list(alert.companies)
    after_count = len(after_companies)
    after_basis = _basis_counts(after_companies)
    new_summary = [(c.company.ticker, c.impact_level, c.parent_company_id) for c in after_companies]
    print(f"  AFTER:  {new_summary}")
    print(f"  company count: {before_count} -> {after_count}")
    if after_count < before_count:
        # A shrink is usually the POINT of this script (the precision work
        # exists to remove hallucinated companies), but it is also what a
        # partial/truncated analysis looks like, and the two are genuinely
        # indistinguishable here -- see the module docstring's
        # EMPTY-RESULT GUARD section. Flagged so a bulk run's output can be
        # eyeballed rather than silently trusted.
        print(f"  NOTE: this alert SHRANK ({before_count} -> {after_count}). Expected when the "
              f"fresh analysis drops hallucinated names; also what a truncated analysis "
              f"looks like. Not blocked (only a total wipe to zero is).")
    print(f"  basis before:  {before_basis}")
    print(f"  basis after:   {after_basis}")


def main(
    limit: int | None, days: int | None, force: bool,
    alert_ids: list[int] | None = None, allow_empty: bool = False,
) -> None:
    init_db()
    session = SessionLocal()
    client = build_client(settings.groq_api_keys, settings.gemini_api_key or None)

    if alert_ids:
        # --alert-id mode: exactly these alerts, no date window, cache
        # always cleared (see module docstring for why).
        for alert_id in alert_ids:
            alert = session.get(Alert, alert_id)
            if alert is None:
                print(f"Alert {alert_id}: not found -- skipping")
                continue
            reanalyze_alert(session, client, alert, force=True, allow_empty=allow_empty)
    else:
        query = session.query(Alert).order_by(Alert.created_at.desc())
        if days is not None:
            cutoff = utcnow() - timedelta(days=days)
            query = query.filter(Alert.created_at >= cutoff)
        if limit is not None:
            query = query.limit(limit)
        alerts = query.all()

        for alert in alerts:
            reanalyze_alert(session, client, alert, force=force, allow_empty=allow_empty)

    session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "limit", nargs="?", type=int, default=None,
        help="max number of most-recent alerts to reanalyze (default 5, or "
             "unlimited if --days is given). Mutually exclusive with "
             "--alert-id.",
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="only reanalyze alerts created in the last N days. Mutually "
             "exclusive with --alert-id.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="clear the cached analysis first so a fresh LLM call is made "
             "(bulk mode only -- --alert-id always clears the cache)",
    )
    parser.add_argument(
        "--allow-empty", action="store_true",
        help="write a fresh analysis that resolved to ZERO companies even "
             "over an alert that currently has companies. OFF by default: "
             "such a result is far more often a stochastic stage failure "
             "than a genuine answer (see the module docstring's EMPTY-RESULT "
             "GUARD section), and writing it destroys the alert's companies "
             "and their calibration history irreversibly. Pass this only "
             "when you have confirmed zero is the correct new answer.",
    )
    parser.add_argument(
        "--alert-id", type=int, action="append", dest="alert_ids", default=None,
        help="reanalyze exactly this alert id, ignoring the date window "
             "(repeatable: pass multiple times for several ids). Mutually "
             "exclusive with the positional limit and --days. Always clears "
             "the cached analysis for the targeted alert(s) first. NOTE: "
             "reanalysis deletes the alert's existing AlertCompany rows and "
             "their dependents (including CalibrationSample and CarOutcome "
             "history) -- correct and intentional, but irreversible.",
    )
    parsed = parser.parse_args()
    if parsed.alert_ids and (parsed.limit is not None or parsed.days is not None):
        parser.error("--alert-id cannot be combined with the positional limit or --days")
    if parsed.alert_ids:
        main(None, None, parsed.force, alert_ids=parsed.alert_ids, allow_empty=parsed.allow_empty)
    else:
        limit = parsed.limit if parsed.limit is not None else (None if parsed.days is not None else 5)
        main(limit, parsed.days, parsed.force, allow_empty=parsed.allow_empty)
