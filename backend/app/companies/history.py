from sqlalchemy.orm import Session

from app.models import Alert, AlertCompany, Article

PAST_MENTIONS_LIMIT = 3


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
    """
    rows = (
        session.query(AlertCompany, Alert, Article)
        .join(Alert, AlertCompany.alert_id == Alert.id)
        .join(Article, Alert.article_id == Article.id)
        .filter(AlertCompany.company_id == company_id)
        .filter(Alert.created_at < before)
        .order_by(Alert.created_at.desc())
        .limit(limit)
        .all()
    )
    return [{
        "alert_id": alert.id,
        "article_title": article.title,
        "article_url": article.url,
        "created_at": alert.created_at.isoformat(),
        "direction": ac.direction,
        "category": alert.category,
    } for ac, alert, article in rows]
