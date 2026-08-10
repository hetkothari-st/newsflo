import json
import logging
import time

from openai import RateLimitError
from sqlalchemy.orm import Session

from app.analysis.claude_client import FALLBACK_MODEL, tier_kwargs
from app.config import settings
from app.models import Article

logger = logging.getLogger(__name__)

# Article.provider slugs whose every item is financial news by
# construction (curated aggregators) -- they skip the per-article LLM
# relevance call and are admitted straight to analysis. Deterministic
# gates (language, junk) still apply to them.
PRE_CURATED_PROVIDERS = frozenset({"pulse_zerodha"})


class RelevanceRateLimited(Exception):
    """The relevance call failed because the provider is rate-limited or out
    of quota -- as opposed to any other failure.

    This distinction exists because the two failure modes want opposite
    handling. For a genuine error (a malformed response, a transient 500)
    admitting the article is right: the article is probably fine and one
    wasted analysis is cheap. For a rate limit it is actively harmful --
    admitting sends the article on to full analysis, which is ~7 more calls
    against the very quota that just ran out, so they fail too and the
    article lands in ANALYSIS_FAILED, which nothing revisits. Measured in
    production: 31 of 117 articles in one day were lost exactly this way.
    Leaving the article NEW instead costs nothing and lets the next
    scheduler tick classify it once quota returns.
    """


# Substrings that identify a rate-limit/quota failure in a provider error
# whose TYPE we can't match on. Necessary because this client layer talks to
# three providers through adapters (see app.analysis.claude_client): Groq
# raises openai.RateLimitError, but AnthropicAPIError and GeminiAPIError are
# both flat exception types that cover every provider-level failure --
# 429s included -- and carry the distinction only in their message. Matching
# the message is the only signal available for those two.
_RATE_LIMIT_MARKERS = (
    "rate limit", "rate_limit", "ratelimit", "too many requests",
    "quota", "resource_exhausted", "resource exhausted", "insufficient_quota",
    "429",
)


def is_rate_limit_error(exc: BaseException) -> bool:
    """True when ``exc`` represents a provider rate limit / exhausted quota.

    Errs toward False on purpose: a misread here sends the article down the
    fail-open path, which admits it. Reading a rate limit as an ordinary
    error costs LLM calls; reading an ordinary error as a rate limit would
    delay a real article, so False is the safer default when unsure.
    """
    if isinstance(exc, RateLimitError):
        return True
    if getattr(exc, "status_code", None) == 429 or getattr(exc, "code", None) == 429:
        return True
    message = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in message for marker in _RATE_LIMIT_MARKERS)

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
    Raises exactly one exception, RelevanceRateLimited, and only when the
    provider is rate-limited or out of quota -- see that class for why that
    single case must not be admitted. EVERY other failure (API error,
    unparseable response, missing tool call) still fails OPEN (returns True,
    admit the article): silently dropping a real story is worse than one
    wasted downstream analysis call on a false positive.
    """
    tool = build_relevance_tool()
    try:
        response = client.chat.completions.create(
            model=FALLBACK_MODEL,
            max_tokens=300,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_relevance"}},
            messages=[{"role": "user", "content": _PROMPT_TEMPLATE.format(title=title, content=content)}],
            **tier_kwargs("classify_relevance"),
        )
        message = response.choices[0].message
        tool_call = next((tc for tc in (message.tool_calls or []) if tc.function.name == "record_relevance"), None)
        if tool_call is None:
            return True
        arguments = json.loads(tool_call.function.arguments)
        return bool(arguments.get("relevant", True))
    except Exception as exc:
        if is_rate_limit_error(exc):
            raise RelevanceRateLimited(str(exc)) from exc
        return True


def filter_new_articles(session: Session, client, throttle_seconds: float = 0) -> None:
    """Classify every NEW article. ``throttle_seconds`` exists for the same
    rate-limit reason as ``process_new_articles``'s throttle -- one Groq call
    per article here too.

    Non-English articles (foreign-language wire mirrors of the same press
    release, see app.filtering.language_gate) are FILTERED before the LLM
    call -- the feed is English-only by default; other languages come from
    the user's translation picker, never from the source mix.

    Two further deterministic gates run after the language one, both free:

    * app.filtering.junk -- recognises a narrow set of mechanically produced
      non-news document formats (UK Takeover Code Rule 8 dealing
      disclosures, award/recognition PR) and FILTERS them outright. Always
      enforcing, because each pattern is anchored to a document shape rather
      than a topic.
    * app.filtering.prefilter -- short-circuits articles that are
      unambiguously not market news. Defaults to shadow mode, where it only
      reports what it would have rejected and every article still reaches
      the LLM.

    See both modules for why their rules are built to err only toward
    admitting.

    A rate-limited relevance call leaves the article in NEW rather than
    admitting or filtering it, and stops this run from making any further
    relevance calls: once the provider's quota is gone every subsequent call
    in the same run would fail too, and each admitted article would go on to
    burn ~7 more analysis calls before landing in ANALYSIS_FAILED. The
    remaining articles keep their NEW status and are picked up by the next
    scheduler tick, which is the retry. The loop still runs the free
    deterministic gates over them -- those cost nothing and their verdicts
    do not depend on the provider being up.
    """
    from app.filtering.exchange_noise import is_exchange_noise
    from app.filtering.junk import is_junk
    from app.filtering.language_gate import is_english_text
    from app.filtering.prefilter import PrefilterCounters, apply_prefilter
    from app.pipeline import article_text

    counters = PrefilterCounters()
    rate_limited = False
    deferred = 0
    # .all() materialises the NEW rows once, up front. An article left as
    # NEW below is therefore never revisited within this run -- the loop is
    # iterating a fixed snapshot, not a live query. Newest published first:
    # when a backlog exists (fresh deployment, provider burst, quota
    # recovery), current news must not wait behind stale news for its LLM
    # call -- the tail still drains, just after the fresh stories.
    for article in (
        session.query(Article)
        .filter_by(status="NEW")
        .order_by(Article.published_at.desc().nullslast(), Article.id.desc())
        .all()
    ):
        if not is_english_text(article.title, article_text(article)):
            article.status = "FILTERED"
            continue  # deterministic gate -- no LLM call, no throttle needed
        if is_junk(article.title, article_text(article)):
            article.status = "FILTERED"
            continue  # deterministic gate -- no LLM call, no throttle needed
        if is_exchange_noise(
            article.provider, article.source_category,
            article.title, article_text(article),
            mode=settings.exchange_noise_mode,
        ):
            article.status = "FILTERED"
            continue  # deterministic gate (NSE/BSE announcement noise) -- no LLM call
        if apply_prefilter(article.title, article_text(article), counters):
            article.status = "FILTERED"
            continue  # deterministic gate -- no LLM call, no throttle needed
        if article.provider in PRE_CURATED_PROVIDERS:
            # Pulse aggregates exclusively financial/market news -- every
            # item is by construction the kind of article the LLM gate
            # exists to find. Admitting it directly saves one LLM call per
            # article and removes the gate's latency; the deterministic
            # gates above (language/junk) still apply.
            article.status = "CATEGORIZED"
            continue
        if rate_limited:
            deferred += 1
            continue  # left NEW on purpose -- the next tick retries it
        try:
            relevant = classify_relevance(client, article.title, article_text(article))
        except RelevanceRateLimited as exc:
            rate_limited = True
            deferred += 1
            logger.warning(
                "relevance classification rate-limited on article_id=%s (%s) -- "
                "leaving it and the rest of this run's articles in NEW for the next tick",
                article.id, exc,
            )
            continue  # left NEW on purpose -- neither filtered nor admitted
        article.status = "CATEGORIZED" if relevant else "FILTERED"
        time.sleep(throttle_seconds)
    counters.log_summary()
    if deferred:
        logger.warning("relevance: %s article(s) left in NEW for a later tick (provider rate limit)", deferred)
    session.commit()
