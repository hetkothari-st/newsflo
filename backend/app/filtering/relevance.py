from sqlalchemy.orm import Session

from app.analysis.claude_client import FALLBACK_MODEL
from app.models import Article

_PROMPT_TEMPLATE = (
    "Does this news plausibly affect any financial, business, or economic "
    "sector -- directly or indirectly -- anywhere in the world? Consider "
    "stock markets, companies, government spending, infrastructure, "
    "policy, trade, or the broader economy relevant. Answer with exactly "
    "one word: YES or NO.\n\n"
    "Title: {title}\n\n"
    "Content: {content}"
)


def classify_relevance(client, title: str, content: str) -> bool:
    """Ask a cheap, fast model whether this article could plausibly
    affect any financial/business/economic sector, directly or
    indirectly, anywhere. Never raises -- any failure (API error,
    unparseable response) fails OPEN (returns True, admit the article):
    silently dropping a real story is worse than one wasted downstream
    analysis call on a false positive.
    """
    try:
        response = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=[{"role": "user", "content": _PROMPT_TEMPLATE.format(title=title, content=content)}],
            max_tokens=5,
        )
        answer = response.choices[0].message.content
    except Exception:
        return True

    return "yes" in (answer or "").strip().lower()


def filter_new_articles(session: Session, client) -> None:
    from app.pipeline import article_text

    for article in session.query(Article).filter_by(status="NEW").all():
        if classify_relevance(client, article.title, article_text(article)):
            article.status = "CATEGORIZED"
        else:
            article.status = "FILTERED"
    session.commit()
