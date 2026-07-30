import json
import time

from sqlalchemy.orm import Session

from app.analysis.claude_client import FALLBACK_MODEL
from app.models import Article

_PROMPT_TEMPLATE = (
    "Does this news have a SPECIFIC, STATED economic mechanism that would "
    "genuinely move a real company's stock, a sector, or a market -- "
    "something a market-impact analyst could point to and name (a price/"
    "rate/policy change, an earnings or deal event, a regulatory action, a "
    "supply/demand shift, a credit or currency move)? Being loosely "
    "'related to the economy' is not enough on its own.\n\n"
    "Answer NO for: accidents, disasters, crime, deaths, or casualties with "
    "no stated financial angle (e.g. a bus collision, a natural disaster "
    "recap) -- even though tragic, these move no market unless the article "
    "itself states a concrete economic consequence; human-interest or "
    "personal-profile stories (a farmer, a small business owner, a "
    "biography) with no market mechanism; general lifestyle, sports, "
    "entertainment, or celebrity news; and vague scene-setting that "
    "gestures at 'the economy' without naming a real mechanism.\n\n"
    "Answer YES for: anything with a specific, nameable economic "
    "mechanism, even indirect (e.g. an oil-price move, a rate decision, a "
    "trade/tariff policy, a company's earnings or deal, a regulatory "
    "ruling) -- indirect reach is fine as long as the mechanism itself is "
    "concrete and stated, not merely plausible in the abstract.\n\n"
    "Title: {title}\n\n"
    "Content: {content}"
)


def build_relevance_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_relevance",
            "description": "Record whether this article has a genuine economic mechanism worth market-impact analysis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "relevant": {
                        "type": "boolean",
                        "description": (
                            "True if the article states a specific, nameable "
                            "economic mechanism that could move a company, "
                            "sector, or market. False for accidents, "
                            "disasters, crime, or human-interest/lifestyle "
                            "stories with no stated financial angle."
                        ),
                    },
                },
                "required": ["relevant"],
            },
        },
    }


def classify_relevance(client, title: str, content: str) -> bool:
    """Ask a cheap, fast model whether this article has a genuine economic
    mechanism worth analyzing. Uses a forced tool call rather than a plain
    content completion -- this client may route through AnthropicAdapter
    (see app.analysis.claude_client.FallbackClient), which only implements
    the tool-calling shape, not a bare content completion; a plain-content
    call would raise a TypeError on every call once ANTHROPIC_API_KEY is
    configured (confirmed in production: this previously made the filter a
    silent no-op, always failing open via the broad except below and
    admitting every article regardless of content). max_tokens is generous
    (not a tight 5-token budget) because reasoning models (e.g. Groq's
    openai/gpt-oss-20b, this function's FALLBACK_MODEL) emit hidden
    reasoning tokens before the final answer -- a too-small budget starves
    the answer itself, producing an empty response (also confirmed live:
    max_tokens=5 reliably returned '' even for an unambiguous headline).
    Never raises -- any failure (API error, unparseable response) fails
    OPEN (returns True, admit the article): silently dropping a real story
    is worse than one wasted downstream analysis call on a false positive.
    """
    tool = build_relevance_tool()
    try:
        response = client.chat.completions.create(
            model=FALLBACK_MODEL,
            max_tokens=300,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_relevance"}},
            messages=[{"role": "user", "content": _PROMPT_TEMPLATE.format(title=title, content=content)}],
        )
        message = response.choices[0].message
        tool_call = next((tc for tc in (message.tool_calls or []) if tc.function.name == "record_relevance"), None)
        if tool_call is None:
            return True
        arguments = json.loads(tool_call.function.arguments)
        return bool(arguments.get("relevant", True))
    except Exception:
        return True


def filter_new_articles(session: Session, client, throttle_seconds: float = 0) -> None:
    """Classify every NEW article. ``throttle_seconds`` exists for the same
    rate-limit reason as ``process_new_articles``'s throttle -- one Groq call
    per article here too.

    Non-English articles (foreign-language wire mirrors of the same press
    release, see app.filtering.language_gate) are FILTERED before the LLM
    call -- the feed is English-only by default; other languages come from
    the user's translation picker, never from the source mix.
    """
    from app.filtering.language_gate import is_english_text
    from app.pipeline import article_text

    for article in session.query(Article).filter_by(status="NEW").all():
        if not is_english_text(article.title, article_text(article)):
            article.status = "FILTERED"
            continue  # deterministic gate -- no LLM call, no throttle needed
        if classify_relevance(client, article.title, article_text(article)):
            article.status = "CATEGORIZED"
        else:
            article.status = "FILTERED"
        time.sleep(throttle_seconds)
    session.commit()
