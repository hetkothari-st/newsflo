import re
from sqlalchemy.orm import Session

from app.models import Article

CATEGORY_KEYWORDS = {
    "oil_energy": ["crude", "oil", "opec", "brent", "petroleum", "refinery"],
    "banking": ["rbi", "repo rate", "interest rate", "npa"],
    "auto_ev": ["ev subsidy", "electric vehicle", "fame scheme", "auto sales"],
    "geopolitics": ["sanction", "strike", "conflict", "tariff", "export ban", "war"],
}


def classify_category(title: str, content: str) -> str | None:
    text = f"{title} {content}".lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if " " in keyword:
                # Multi-word phrase: use substring matching
                if keyword in text:
                    return category
            else:
                # Single word: use word-boundary matching on both sides to avoid false
                # positives (e.g. "war" inside "warning"/"warehouse"/"ward"), while still
                # allowing a single trailing "s" for plural/inflected forms (e.g.
                # "sanction" matches "sanctions", "tariff" matches "tariffs").
                if re.search(rf"\b{re.escape(keyword)}s?\b", text):
                    return category
    return None


def filter_new_articles(session: Session) -> None:
    for article in session.query(Article).filter_by(status="NEW").all():
        category = classify_category(article.title, article.content)
        if category is None:
            article.status = "FILTERED"
        else:
            article.status = "CATEGORIZED"
            article.category = category
    session.commit()
