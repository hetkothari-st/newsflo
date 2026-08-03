"""A deterministic rule pass in front of the relevance LLM call
(app.filtering.relevance.classify_relevance), so an article that is
unambiguously not market news never costs a call at all.

The whole design turns on an asymmetry: admitting an article that should
have been rejected costs one cheap classification call, while rejecting one
that should have been admitted loses a real market story from the feed with
nothing to notice it by. So this module is built to be wrong in only the
first direction. Two mechanisms enforce that:

1. A veto. Any market signal anywhere in the article -- headline or body --
   admits it outright, whatever else matched. The signal list
   (RELEVANCE_PREFILTER_MARKET_SIGNALS) is deliberately over-broad.
2. Headline-only noise matching. The noise patterns describe article
   FORMATS that are never market news (a horoscope, a recipe, a match
   report), and they are matched against the headline alone, because a body
   mention proves nothing -- a sponsorship story says "cricket", a
   plant-closure story says "accident".

Both must agree before anything is rejected. Everything else -- including
every borderline case -- goes to the LLM exactly as it did before.
"""
import logging
import re

from app.config import (
    RELEVANCE_PREFILTER_MARKET_SIGNALS, RELEVANCE_PREFILTER_NOISE_PATTERNS, settings,
)

logger = logging.getLogger(__name__)

PASS = "pass"
REJECT = "reject"

# Compiled once at import. Case-insensitive throughout: headlines are
# routinely title-cased or shouted, and no rule here depends on case.
_NOISE_RES = [re.compile(pattern, re.IGNORECASE) for pattern in RELEVANCE_PREFILTER_NOISE_PATTERNS]

# Symbols ("₹", "%") can't take a word boundary, so they stay plain
# substring checks. Everything else is matched on word boundaries with an
# optional plural -- a bare substring search is far too loose to be useful
# here: "oil" matches "boil water", "share" matches "widely shared", and a
# veto that fires on every recipe and every viral clip vetoes the whole
# pre-filter. Inflections a plural rule can't reach (companies, trading)
# are listed in their own right in config.
_SYMBOL_SIGNALS = [s.lower() for s in RELEVANCE_PREFILTER_MARKET_SIGNALS if not s[:1].isalnum()]
_WORD_SIGNALS = [s.lower() for s in RELEVANCE_PREFILTER_MARKET_SIGNALS if s[:1].isalnum()]
_WORD_SIGNAL_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(s) for s in sorted(_WORD_SIGNALS, key=len, reverse=True)) + r")(?:s|es)?\b",
    re.IGNORECASE,
)


def market_signal_in(text: str) -> str | None:
    """The first market signal found in ``text``, or None. Returned rather
    than a bool so a shadow-mode log line can say WHICH signal admitted an
    article -- that is what makes a shadow review reviewable."""
    lowered = (text or "").lower()
    for symbol in _SYMBOL_SIGNALS:
        if symbol in lowered:
            return symbol
    match = _WORD_SIGNAL_RE.search(lowered)
    return match.group(0) if match else None


def noise_pattern_in(title: str) -> str | None:
    """The first noise pattern matching ``title``, or None."""
    for regex in _NOISE_RES:
        if regex.search(title or ""):
            return regex.pattern
    return None


def prefilter_verdict(title: str, content: str) -> tuple[str, str]:
    """Returns ``(verdict, reason)`` where verdict is PASS or REJECT.

    REJECT is returned ONLY when a noise pattern matches the headline AND
    no market signal appears anywhere in the article. Every other
    outcome -- including an empty headline, an unrecognised headline, or a
    noise headline on an article whose body mentions anything financial --
    is PASS, meaning "the LLM decides", which is exactly the behavior this
    module replaced for those articles.
    """
    noise = noise_pattern_in(title)
    if noise is None:
        return PASS, "no noise pattern in headline"

    signal = market_signal_in(f"{title}\n{content}")
    if signal is not None:
        return PASS, f"noise headline vetoed by market signal {signal!r}"

    return REJECT, f"headline matched noise pattern {noise!r} and article carries no market signal"


class PrefilterCounters:
    """Per-run tally, so the saving is measured rather than guessed (phase
    3 step 2). ``rejected`` counts articles the rules short-circuited in
    enforce mode; ``shadow_rejected`` counts the ones they only claimed
    they would."""

    def __init__(self):
        self.seen = 0
        self.passed = 0
        self.rejected = 0
        self.shadow_rejected = 0

    @property
    def llm_calls_saved(self) -> int:
        return self.rejected

    def log_summary(self) -> None:
        logger.info(
            "relevance prefilter (mode=%s): %s articles seen, %s passed to the LLM, "
            "%s short-circuited, %s shadow-rejects (would have been short-circuited)",
            settings.relevance_prefilter_mode, self.seen, self.passed,
            self.rejected, self.shadow_rejected,
        )


def apply_prefilter(title: str, content: str, counters: PrefilterCounters) -> bool:
    """Returns True when the caller should short-circuit this article as
    irrelevant WITHOUT an LLM call, False when it must still classify it.

    Only ever returns True in "enforce" mode. In "shadow" mode (the
    default) a reject is counted and logged with its reason and headline --
    everything a human needs to review the rules against real traffic --
    but the article still goes to the LLM, so the feed is identical to a
    run with the pre-filter off. In "off" mode the rules do not run at all.
    """
    counters.seen += 1
    mode = settings.relevance_prefilter_mode
    if mode == "off":
        counters.passed += 1
        return False

    verdict, reason = prefilter_verdict(title, content)
    if verdict == PASS:
        counters.passed += 1
        return False

    if mode == "enforce":
        counters.rejected += 1
        logger.info("relevance prefilter REJECT (%s): %r", reason, title)
        return True

    counters.shadow_rejected += 1
    counters.passed += 1
    logger.info("relevance prefilter SHADOW-REJECT (%s): %r", reason, title)
    return False
