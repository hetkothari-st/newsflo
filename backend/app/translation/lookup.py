import json

from sqlalchemy.orm import Session

from app.models import AlertCompanyTranslation, ArticleTranslation, CategoryTranslation

# Every lookup here silently falls back to the English value when no
# translation row exists (not yet translated, or translation permanently
# failed) -- callers never need their own missing-translation branch.


def bulk_article_titles(session: Session, article_ids: list[int], lang: str) -> dict[int, str]:
    if lang == "en" or not article_ids:
        return {}
    rows = (
        session.query(ArticleTranslation)
        .filter(ArticleTranslation.article_id.in_(article_ids), ArticleTranslation.lang == lang)
        .all()
    )
    return {row.article_id: row.title for row in rows}


def bulk_alert_company_translations(
    session: Session, alert_company_ids: list[int], lang: str
) -> dict[int, tuple[str, list[str]]]:
    if lang == "en" or not alert_company_ids:
        return {}
    rows = (
        session.query(AlertCompanyTranslation)
        .filter(
            AlertCompanyTranslation.alert_company_id.in_(alert_company_ids),
            AlertCompanyTranslation.lang == lang,
        )
        .all()
    )
    return {row.alert_company_id: (row.rationale, json.loads(row.key_points_json)) for row in rows}


def bulk_category_labels(session: Session, categories: list[str], lang: str) -> dict[str, str]:
    if lang == "en" or not categories:
        return {}
    rows = (
        session.query(CategoryTranslation)
        .filter(CategoryTranslation.category.in_(categories), CategoryTranslation.lang == lang)
        .all()
    )
    return {row.category: row.label for row in rows}
