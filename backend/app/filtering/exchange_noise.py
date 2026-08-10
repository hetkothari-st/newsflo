"""Deterministic noise gate for exchange corporate-announcement feeds
(NSE/BSE providers only -- never applied to press or API sources).

Exchange filings are saturated with mechanically produced non-news: NAV
declarations, trading-window closures, newspaper-publication copies,
record-date notices. Routing those through the general prefilter would not
work -- its market-signal veto fires on the exchange vocabulary ("NAV",
"record date", percentages) present in every single one -- so this is a
separate gate, the same reasoning that makes app.filtering.junk a separate
module rather than more prefilter rules.

Primary signal is the STRUCTURED category both exchanges attach (NSE's
"|SUBJECT:" suffix, BSE's LODR NEWSSUB suffix -- parsed into
Article.source_category at ingestion). Structured categories are far less
false-positive-prone than headline regex; the title patterns below are
only a fallback for rows whose category didn't parse.

Same admit-by-default asymmetry as junk.py: a false negative costs one
cheap LLM classification call, a false positive silently deletes a real
disclosure from the feed. Uncertain => ADMIT. Rollout follows the
prefilter's shadow/enforce playbook via settings.exchange_noise_mode.
"""
import logging

from app.filtering.junk import JunkPattern, financial_signal_in

logger = logging.getLogger(__name__)

NOISE = "noise"
ADMIT = "admit"

# Structured categories that are noise by their own definition. Lowercased
# substring match: exchanges phrase these with minor variations
# ("Trading Window", "Closure of Trading Window", "Trading Window-XBRL").
NOISE_CATEGORIES = (
    "declaration of nav",
    "trading window",
    "copy of newspaper publication",
    "newspaper publication",
    "record date",
    "book closure",
    "certificate under",
    "compliance certificate",
    "share certificate",
    "loss of share certificate",
    "duplicate share certificate",
    "notice of shareholders meeting",
    "shareholders meeting",
    "shareholder meeting",
    "postal ballot",
    "investor complaint",
    "investor grievance",
    "reg. 74 (5)",
    "regulation 74",
    "spdis",
)

# Structured categories that are signal by their own definition -- checked
# BEFORE the noise list so a compound category ("Outcome of Board Meeting /
# Record Date") admits. Never rejected regardless of any other rule.
SIGNAL_CATEGORIES = (
    "outcome of board meeting",
    "financial result",
    "acquisition",
    "amalgamation",
    "merger",
    "demerger",
    "credit rating",
    "awarding of order",
    "bagging",
    "contract",
    "press release",
    "fund raising",
    "alteration of capital",
    "issuance of securities",
    "buyback",
    "delisting",
    "open offer",
    "insolvency",
    "litigation",
    "default",
    "joint venture",
    "divestment",
    "disinvestment",
    "expansion",
    "new project",
)

# Headline fallback for rows with no parsed category. Reuses junk.py's
# JunkPattern shape: headline-anchored regex + optional financial-signal
# veto (via junk.financial_signal_in).
NOISE_TITLE_PATTERNS = [
    JunkPattern(
        name="exchange_nav_declaration",
        pattern=r"\bnet\s+asset\s+value\b|\bnav\b.*\bas\s+on\b",
        veto_on_financial_signal=False,
    ),
    JunkPattern(
        name="exchange_trading_window",
        pattern=r"\btrading\s+window\b",
        veto_on_financial_signal=False,
    ),
    JunkPattern(
        name="exchange_newspaper_copy",
        pattern=r"\bnewspaper\s+(?:publication|advertisement|clipping)s?\b",
        veto_on_financial_signal=False,
    ),
    JunkPattern(
        name="exchange_record_date",
        pattern=r"\brecord\s+date\b",
        veto_on_financial_signal=True,
    ),
    JunkPattern(
        name="exchange_book_closure",
        pattern=r"\bbook\s+closure\b|\bclosure\s+of\s+register\b",
        veto_on_financial_signal=True,
    ),
]

# Article.provider values this gate applies to. Everything else bypasses it
# entirely -- a Moneycontrol story mentioning "record date" is real news.
EXCHANGE_PROVIDERS = frozenset({"nse", "bse"})


def exchange_noise_verdict(source_category: str | None, title: str, content: str = "") -> tuple[str, str]:
    """(verdict, reason); verdict is NOISE or ADMIT. Admit-by-default."""
    if source_category:
        category = source_category.strip().lower()
        for signal in SIGNAL_CATEGORIES:
            if signal in category:
                return ADMIT, f"signal category {source_category!r}"
        for noise in NOISE_CATEGORIES:
            if noise in category:
                return NOISE, f"noise category {source_category!r}"
        return ADMIT, f"unrecognised category {source_category!r}"

    for pattern in NOISE_TITLE_PATTERNS:
        if pattern.regex.search(title or ""):
            if pattern.veto_on_financial_signal:
                signal = financial_signal_in(f"{title}\n{content}")
                if signal is not None:
                    return ADMIT, f"{pattern.name} vetoed by financial signal {signal!r}"
            return NOISE, f"headline matched {pattern.name!r}"
    return ADMIT, "no noise category or pattern"


def is_exchange_noise(provider: str | None, source_category: str | None,
                      title: str, content: str = "", mode: str = "shadow") -> bool:
    """True when the article should be FILTERED without an LLM call.

    ``mode`` follows the prefilter's semantics: "off" skips entirely,
    "shadow" logs the would-be verdict but never rejects, "enforce" acts.
    Only ever fires for EXCHANGE_PROVIDERS articles.
    """
    if mode == "off" or provider not in EXCHANGE_PROVIDERS:
        return False
    verdict, reason = exchange_noise_verdict(source_category, title, content)
    if verdict != NOISE:
        return False
    if mode == "enforce":
        logger.info("exchange noise FILTERED (%s): %r", reason, title)
        return True
    logger.info("exchange noise SHADOW would-filter (%s): %r", reason, title)
    return False
