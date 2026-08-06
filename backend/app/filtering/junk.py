"""A deterministic junk gate that runs before ANY LLM call in the relevance
path. Pure functions: no LLM, no network, no database, no configuration --
the same title always gets the same verdict.

Scope is deliberately tiny. This module recognises document FORMATS that
are mechanically produced and cannot, by their own definition, carry
market-moving information. It is not a general "is this interesting?"
filter -- that judgement stays with
app.filtering.relevance.classify_relevance, and everything this module does
not positively recognise is handed straight to it, unchanged.

The asymmetry that governs every choice here: a false negative (junk that
slips through) costs exactly one cheap classification call. A false
positive (real news marked FILTERED) silently removes a story from the
user's feed with nothing at all to notice it by. So when a rule is
uncertain, it ADMITS. Two mechanisms enforce that:

1. Structural anchoring. Patterns match the SHAPE of a wire-service
   document title -- "Form 8.3" at the very start of the headline, or
   immediately after the discloser's name and a colon -- not loose
   keywords. The bare word "form" is never matched, and the dot in
   "Form 8.3" is load-bearing: SEC "Form 8-K" and "Form 10-K" are hyphenated
   and never match.
2. A financial-event veto. Any pattern whose shape could also plausibly
   appear in a real story carries ``veto_on_financial_signal=True``: a
   concrete financial signal anywhere in the headline or body then admits
   the article regardless of the match. The veto list is deliberately
   over-broad, because a spurious veto costs one LLM call and a missing one
   costs a story.

TO ADD A CASE: append a JunkPattern to JUNK_PATTERNS below (and, if it needs
one, extend JUNK_VETO_EXTRA_SIGNALS). No logic in this file has to change.
"""
import logging
import re

from app.config import RELEVANCE_PREFILTER_MARKET_SIGNALS
from app.filtering.prefilter import compile_signal_matcher

logger = logging.getLogger(__name__)

JUNK = "junk"
ADMIT = "admit"


class JunkPattern:
    """One recognised non-news document format.

    ``name``   -- stable identifier, used in log lines and test assertions.
    ``pattern``-- regex matched case-insensitively against the HEADLINE only.
                  A body mention proves nothing: a real story about the
                  Takeover Panel legitimately says "Form 8.3" in its body,
                  and a real earnings story legitimately says "award".
    ``veto_on_financial_signal`` -- when True, a financial signal anywhere in
                  the article (headline or body) overrides the match and
                  admits the article.
    """

    def __init__(self, name: str, pattern: str, veto_on_financial_signal: bool):
        self.name = name
        self.pattern = pattern
        self.veto_on_financial_signal = veto_on_financial_signal
        self.regex = re.compile(pattern, re.IGNORECASE)


JUNK_PATTERNS = [
    JunkPattern(
        name="uk_takeover_code_form_8",
        # TARGETS: UK Takeover Code Rule 8 dealing disclosures -- "Form 8.1"
        # (by a party to the offer), "Form 8.3" (by any person with 1%+ of a
        # party), "Form 8.5" (by an exempt principal trader). Anyone holding
        # 1% or more of a company in an offer period must file one on every
        # day they deal.
        #
        # WHY IT CAN NEVER MOVE A MARKET: it is a position-reporting
        # obligation, not an announcement. The document exists only because
        # an offer is ALREADY public -- Rule 8 disclosures cannot be filed
        # before the offer period opens -- and its entire content is a fixed
        # table stating that a named holder's stake in that already-public
        # situation changed by some fraction of a percent. There is no new
        # fact in it about the company, the offer, or the price. These are
        # also extremely high volume: a single contested bid generates
        # dozens of them per day across the wires.
        #
        # STRUCTURE, NOT KEYWORD: anchored to the start of the headline or to
        # the position right after the discloser's name and a colon, which
        # are the only two shapes the wires emit ("Form 8.3 - [TARGET PLC -
        # 04 08 2026] - (CGWL)" and "Man Group PLC : Form 8.3 - JTC Plc").
        # An article ABOUT these filings ("Takeover Panel probes late Form
        # 8.3 disclosures") is not anchored and passes untouched. The literal
        # dot keeps SEC Form 8-K -- a material-events filing that very much
        # is news -- and Form 10-K out of range.
        pattern=r"(?:^|:\s*)\s*Form\s*8\.\d+\b",
        # NO VETO, deliberately: a Rule 8 disclosure by construction names a
        # target company, a shareholding and a percentage, so a financial
        # signal appears in literally every one of them ("Ordinary Shares" is
        # in the headline of the second example above). A veto here would
        # make the rule a permanent no-op. Safety comes from the anchoring
        # instead, which is strong enough to stand alone.
        veto_on_financial_signal=False,
    ),
    JunkPattern(
        name="award_named_best",
        # TARGETS: award/ranking press releases -- "<Firm> Named Best Family
        # Law Firm in Texas Lawyer's Best Of", "Named One of the Top 100
        # Workplaces".
        #
        # WHY IT CAN NEVER MOVE A MARKET: the underlying event is a third
        # party's editorial or survey opinion. Nothing about the company's
        # cash flows, obligations, regulation or supply has changed; the
        # release exists for recruiting and marketing. The company itself
        # usually is not even listed.
        pattern=r"\bnamed\s+(?:one\s+of\s+)?(?:the\s+|a\s+)?(?:[\w'’-]+\s+){0,3}?(?:best|top)\b",
        veto_on_financial_signal=True,
    ),
    JunkPattern(
        name="award_recognized_as",
        # TARGETS: "<Firm> Recognized as a Leader in ...", "Honored for
        # Excellence in ...". Same class as above, different verb.
        #
        # WHY IT CAN NEVER MOVE A MARKET: an accolade conferred by an
        # analyst house, trade magazine or industry body is a statement
        # about reputation, not about the business. It changes no price, no
        # contract and no obligation.
        #
        # STRUCTURE, NOT KEYWORD: "recognised as" on its own is NOT enough
        # and an earlier version of this pattern that stopped there was a
        # real false positive -- "recognised as systemically important,
        # faces higher capital rules" is a regulatory designation and one of
        # the most market-moving things that can happen to a bank. An
        # accolade NOUN must follow within the same phrase.
        pattern=(
            r"\b(?:recognized|recognised|honored|honoured)\s+(?:as|for|with|among|by|at)\s+"
            r"(?:one\s+of\s+)?(?:the\s+|a\s+|an\s+)?(?:[\w'’-]+[\s-]+){0,3}?"
            r"(?:best|top|leader|leaders|leading|excellence|award|awards|winner|"
            r"finalist|honou?ree|outstanding|elite|premier)\b"
        ),
        veto_on_financial_signal=True,
    ),
    JunkPattern(
        name="award_wins_award",
        # TARGETS: "<Firm> Wins 2026 Best Workplace Award", "Takes Home Top
        # Prize at ...".
        #
        # WHY IT CAN NEVER MOVE A MARKET: as above -- a trophy.
        #
        # STRUCTURE, NOT KEYWORD: the award noun alone is far too loose (a
        # real story says "award-winning fund manager", or "awarded a $400m
        # contract"), so a winning VERB must appear within the same clause
        # as the award noun. "wins"/"win" are matched but "winning" is not,
        # which is what keeps "Award-winning ..." headlines out of range;
        # "awarded a contract" has no matching verb and is vetoed anyway.
        pattern=(
            r"\b(?:wins?|won|receives?|earns?|garners?|bags?|takes\s+home|sweeps?)\b"
            r"[^.;:]{0,60}?\b(?:award|awards|prize|prizes|accolade|accolades|"
            r"recognition|honou?rs?)\b"
        ),
        veto_on_financial_signal=True,
    ),
    JunkPattern(
        name="award_ranked_number",
        # TARGETS: list-placement PR -- "Ranked #1 in Customer Satisfaction",
        # "Ranked No. 7 on the Fastest-Growing Companies list".
        #
        # WHY IT CAN NEVER MOVE A MARKET: a position on somebody else's
        # published list is a survey result. It is also the pattern here
        # most likely to collide with a real story ("Ranked #1 exporter
        # reports record quarter"), which is exactly why the veto below is
        # not optional for it.
        pattern=r"\branked\s+(?:#|no\.?\s*|number\s+)?\d+\b",
        veto_on_financial_signal=True,
    ),
]

# Generic business vocabulary that is NOT evidence of a financial event.
# These words appear in the market-signal list because that list is used
# elsewhere to admit anything vaguely commercial, but they are the ordinary
# furniture of an award headline ("Best Company to Work For", "Best Family
# Law Firm", "Industry Leader"), so leaving them in would make the award
# veto fire on every single award release and neuter the rule.
JUNK_VETO_EXEMPT_SIGNALS = {
    "firm", "company", "companies", "business", "industry", "industries", "sector",
}

# Event words the broad market-signal list happens not to carry (it holds
# "quarterly" but not "quarter", "results" but not "report"). Added so the
# veto errs further toward admitting -- every entry here can only ever turn
# a would-be junk verdict into an admit.
JUNK_VETO_EXTRA_SIGNALS = [
    "quarter", "half-year", "fiscal", "report", "reported", "reporting",
    "record", "beat", "miss", "warn", "warning", "forecast", "outlook",
    "surge", "plunge", "slump", "rally", "rebound", "raise", "cut", "hike",
    "sue", "sued", "lawsuit", "settlement", "probe", "investigation", "fine",
    "penalty", "recall", "approval", "approve", "reject", "fda", "sec", "ftc",
    "resign", "resigns", "appoint", "appoints", "appointed", "steps down",
    "strike", "shortage", "delay", "outage", "breach", "cyberattack",
    "dividend", "spin-off", "divest", "takeover", "bid", "offer",
    # Sell-side language. "Named top pick", "ranked #1 by analysts" and
    # "named best performing fund" ARE market signals -- an analyst rating
    # or a fund ranking moves flows -- and they are the most plausible real
    # stories the award patterns above could ever collide with.
    "analyst", "top pick", "price target", "target price", "outperform",
    "overweight", "underweight", "coverage", "fund", "etf", "portfolio",
    "performer", "performing", "returns", "aum", "inflow", "outflow",
    # Regulatory designation language. Being "designated"/"listed"/"named"
    # something by a REGULATOR is the opposite of an accolade and is among
    # the most market-moving events there is (systemic-importance status,
    # a sanctions listing, a capital requirement).
    "capital", "rule", "rules", "requirement", "requirements", "compliance",
    "systemic", "systemically", "designation", "designated", "blacklist",
    "watchlist", "moratorium", "ban", "banned",
]

_veto_signal_in = compile_signal_matcher(
    [s for s in RELEVANCE_PREFILTER_MARKET_SIGNALS if s.lower() not in JUNK_VETO_EXEMPT_SIGNALS]
    + JUNK_VETO_EXTRA_SIGNALS
)


def financial_signal_in(text: str) -> str | None:
    """The first financial-event signal found in ``text``, or None.

    Returned rather than a bool so a log line can say WHICH signal admitted
    an article, which is what makes a review of these rules against real
    traffic possible at all.
    """
    return _veto_signal_in(text)


def matching_junk_pattern(title: str) -> JunkPattern | None:
    """The first JUNK_PATTERNS entry whose regex matches ``title``, or None."""
    for pattern in JUNK_PATTERNS:
        if pattern.regex.search(title or ""):
            return pattern
    return None


def junk_verdict(title: str, content: str = "") -> tuple[str, str]:
    """Returns ``(verdict, reason)`` where verdict is JUNK or ADMIT.

    JUNK is returned ONLY when a pattern matches the headline AND, for
    patterns that carry a veto, no financial signal appears anywhere in the
    article. Every other outcome -- an empty headline, an unrecognised
    headline, a recognised headline on an article whose body mentions a real
    financial event -- is ADMIT, meaning "carry on to the LLM exactly as
    before".
    """
    pattern = matching_junk_pattern(title)
    if pattern is None:
        return ADMIT, "no junk pattern in headline"

    if pattern.veto_on_financial_signal:
        signal = financial_signal_in(f"{title}\n{content}")
        if signal is not None:
            return ADMIT, f"{pattern.name} vetoed by financial signal {signal!r}"

    return JUNK, f"headline matched junk pattern {pattern.name!r}"


def is_junk(title: str, content: str = "") -> bool:
    """True when this article can be marked FILTERED without an LLM call.

    Thin bool wrapper over :func:`junk_verdict` for call sites that do not
    need the reason. The verdict is logged here so production can be audited
    for false positives -- a filtered article is otherwise invisible.
    """
    verdict, reason = junk_verdict(title, content)
    if verdict == JUNK:
        logger.info("junk prefilter FILTERED (%s): %r", reason, title)
        return True
    return False
