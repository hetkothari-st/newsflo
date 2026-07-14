from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Alert, AlertCompany, Article

PAST_MENTIONS_LIMIT = 3
HISTORY_PAGE_DEFAULT_LIMIT = 20
HISTORY_PAGE_MAX_LIMIT = 50


def _mentions_query(session: Session, company_id: int):
    return (
        session.query(AlertCompany, Alert, Article)
        .join(Alert, AlertCompany.alert_id == Alert.id)
        .join(Article, Alert.article_id == Article.id)
        .filter(AlertCompany.company_id == company_id)
    )


def _format_mention(ac: AlertCompany, alert: Alert, article: Article) -> dict:
    return {
        "alert_id": alert.id,
        "article_title": article.title,
        "article_url": article.url,
        "created_at": alert.created_at.isoformat(),
        "direction": ac.direction,
        "category": alert.category,
    }


def get_past_mentions(session: Session, company_id: int, before: object, limit: int = PAST_MENTIONS_LIMIT) -> list[dict]:
    """Most recent prior alerts that also named this company, strictly
    before ``before`` (the current alert's created_at) so a company never
    lists itself or a later alert as its own history.

    Not filtered by category/topic -- the model's category text is free-form
    (e.g. "oil_energy", "IPO and competitive positioning", "market_commentary")
    with no fixed taxonomy, so exact-match filtering would silently miss
    genuinely related prior coverage worded slightly differently. Showing
    all prior mentions of the same company is the reliable version of "give
    the user a broad idea and a way to track this company over time".

    One query per call -- fine for a single company, but rendering a page of
    N alerts with a fresh call per (alert, company) pair is the exact N+1
    pattern ``bulk_past_mentions``/``mentions_before`` exist to replace.
    """
    rows = (
        _mentions_query(session, company_id)
        .filter(Alert.created_at < before)
        .order_by(Alert.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_format_mention(ac, alert, article) for ac, alert, article in rows]


def get_company_history_page(
    session: Session,
    company_id: int,
    before: str | datetime | None,
    limit: int = HISTORY_PAGE_DEFAULT_LIMIT,
) -> dict:
    """Paginated view of every alert that has ever named this company, newest
    first -- unlike ``get_past_mentions`` this is NOT anchored to a specific
    alert (``before`` is an optional pagination cursor, not "this alert's own
    timestamp"), so it powers a standalone company history page rather than
    an inline reasoning panel.

    ``before`` is the ``created_at`` of the last item on the previous page
    (a plain ISO string, as returned in each row's ``created_at`` -- callers
    can pass either that string or a ``datetime`` straight through); ``None``
    fetches the first page. Fetches ``limit + 1`` rows to derive ``has_more``
    without a second COUNT query.
    """
    limit = min(limit, HISTORY_PAGE_MAX_LIMIT)
    query = _mentions_query(session, company_id).order_by(Alert.created_at.desc())
    if before is not None:
        if isinstance(before, str):
            before = datetime.fromisoformat(before)
        query = query.filter(Alert.created_at < before)
    rows = query.limit(limit + 1).all()
    has_more = len(rows) > limit
    return {
        "items": [_format_mention(ac, alert, article) for ac, alert, article in rows[:limit]],
        "has_more": has_more,
    }


def bulk_past_mentions(
    session: Session, company_ids: set[int] | list[int]
) -> dict[int, list[tuple[AlertCompany, Alert, Article]]]:
    """One query fetching every (AlertCompany, Alert, Article) row for the
    given companies, newest-first per company. Pair with ``mentions_before``
    to slice one company's list down to entries strictly before a given
    alert's ``created_at`` -- together, the bulk equivalent of calling
    ``get_past_mentions`` once per (alert, company) pair, collapsed into a
    single query regardless of how many alerts/companies are being
    rendered. No per-alert time filter here (unlike ``get_past_mentions``)
    because different alerts for the same company need different cutoffs;
    that filtering happens in ``mentions_before`` instead, in Python, over
    this already-fetched, already-sorted list.
    """
    if not company_ids:
        return {}
    rows = (
        session.query(AlertCompany, Alert, Article)
        .join(Alert, AlertCompany.alert_id == Alert.id)
        .join(Article, Alert.article_id == Article.id)
        .filter(AlertCompany.company_id.in_(company_ids))
        .order_by(AlertCompany.company_id, Alert.created_at.desc())
        .all()
    )
    by_company: dict[int, list[tuple[AlertCompany, Alert, Article]]] = {}
    for row in rows:
        by_company.setdefault(row[0].company_id, []).append(row)
    return by_company


def mentions_before(
    index: dict[int, list[tuple[AlertCompany, Alert, Article]]],
    company_id: int,
    before: object,
    limit: int = PAST_MENTIONS_LIMIT,
) -> list[dict]:
    """Slice a ``bulk_past_mentions`` index down to one company's mentions
    strictly before ``before``, formatted identically to
    ``get_past_mentions``'s return value."""
    candidates = index.get(company_id, [])
    matched = [row for row in candidates if row[1].created_at < before][:limit]
    return [_format_mention(ac, alert, article) for ac, alert, article in matched]
