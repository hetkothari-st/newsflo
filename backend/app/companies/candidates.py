"""Real-company candidate retrieval for the analysis prompts.

Without this the model names companies purely from parametric memory: it has
no list to select from, so it both invents links (a food-delivery company on
a crude-oil story) and returns nothing at all when it cannot recall a name
(61% of alerts had zero companies). Giving it the actual DB rows -- ticker,
name, sub-sector, and one-line business description -- converts the task from
recall to selection, and lets the tool schema enum-constrain `ticker` to
tickers that provably resolve.

Ordering is by real size (market cap), same as app.companies.resolution's
fan-out branch, so that when a sector has more companies than the limit, the
ones that survive are the prominent, liquid names an analyst would actually
consider -- and so the candidate list an analyst sees agrees with which
companies the fan-out could actually pick.
"""
from sqlalchemy.orm import Session

from app.companies.integrity import DEMO_TICKERS
from app.models import Company

# Per sector. Large enough that a real answer is almost always present,
# small enough that ONE sector's block fits the tightest per-minute token
# budget the app has to live inside (openai/gpt-oss-20b, 8,000 TPM).
#
# Raised 40 -> 60 for breadth: the model can only name companies that appear
# here, so a genuine aerospace-component or forgings supplier sitting at rank
# 45 of its sector was unreachable no matter how thorough the framing asked
# the model to be. Ordering is still market cap (see module docstring) --
# that decides which companies are VISIBLE, never which are SELECTED; the
# size-ranked fan-out that actually picked companies by size is a separate,
# deliberately constrained mechanism in cascade.py.
#
# KEPT at 60 through the 2026-08 prompt-size fix: every company stage now
# sends ONE SECTOR PER CALL (cascade._identify_companies_per_sector), so this
# limit bounds the whole candidate block, and 60 without business_desc
# measures ~4.4-5.3k tokens for the slim prompt against that 8,000 ceiling.
# Breadth is the product goal, so the per-candidate LINE was trimmed
# (LONG_LIST_THRESHOLD below) rather than the candidate COUNT.
MAX_CANDIDATES_PER_SECTOR = 60

# Above this many candidates in one prompt, format_candidates drops
# business_desc and emits ticker + name + sub_sector only. See its docstring
# for the measured token budget this defends.
#
# Lowered 80 -> 40 (2026-08) so that a full 60-candidate single-sector block
# lands on the short LINE, not the long one: with descriptions those 60 rows
# measure ~6.5-8.3k tokens for the slim prompt, which brushes or breaks
# gpt-oss-20b's 8,000 TPM ceiling; without them, ~4.4-5.3k.
LONG_LIST_THRESHOLD = 40

# Ceiling on the WHOLE prompt's candidate list, across every sector in one
# call. Every company stage now passes exactly ONE sector (see
# cascade._identify_companies_per_sector), so at 60 per sector this never
# binds in the pipeline -- it survives as a backstop for any future caller
# that does bundle sectors, because that is precisely what broke production:
# 6 primary sectors bundled into one direct-company call carried 6 x 60 = 360
# candidates and billed 17,607 tokens (11,888 with the rulebook dropped),
# over the per-minute ceiling of BOTH models (gpt-oss-20b 8,000,
# llama-3.3-70b-versatile 12,000). A 413 there is not a degraded answer, it
# is ZERO companies for the article, which is far worse than a shorter list.
#
# Trimming the per-candidate line is still done FIRST and does most of the
# work (dropping business_desc cuts a 360-candidate block from 60.8k to 25.1k
# chars).
MAX_CANDIDATES_PER_PROMPT = 200

# Never starve a sector below this, even when many sectors share the prompt
# budget -- a sector represented by 3 companies may as well not be there.
MIN_CANDIDATES_PER_SECTOR = 20


def candidate_companies(
    session: Session, sectors: list[str], limit_per_sector: int = MAX_CANDIDATES_PER_SECTOR,
) -> list[Company]:
    """Every plausible company for the given sectors, most prominent first,
    deduplicated by ticker across sectors and with demo/seed and non-
    tradeable-Indian rows excluded. Order is stable (market cap, then
    ticker) so the same inputs always produce the same prompt -- a prompt
    that reshuffles between runs makes a regression impossible to
    attribute.

    With enough sectors to threaten MAX_CANDIDATES_PER_PROMPT, the per-sector
    limit is reduced so the shortfall is shared evenly rather than letting
    the first sectors spend the whole budget and the last ones arrive empty.
    An explicit `limit_per_sector` from the caller is honoured as-is -- the
    caller has said what it wants. The analysis pipeline now always passes a
    single sector (see cascade._identify_companies_per_sector), so that
    sharing path is a backstop for other callers, not the normal case.
    """
    if limit_per_sector == MAX_CANDIDATES_PER_SECTOR and len(sectors) > 1:
        limit_per_sector = max(
            MIN_CANDIDATES_PER_SECTOR,
            min(limit_per_sector, MAX_CANDIDATES_PER_PROMPT // len(sectors)),
        )
    seen: set[str] = set()
    result: list[Company] = []
    for sector in sectors:
        rows = (
            session.query(Company)
            .filter_by(sector=sector)
            .filter(Company.ticker.notin_(DEMO_TICKERS))
            # Same market/tradeability restriction as
            # app.companies.resolution.resolve_companies' fan-out branch --
            # without it, RESTRICTED/SME/SUSPENDED/GLOBAL rows are eligible
            # both for the prompt text and for the tool schema's ticker
            # enum, so the model can be enum-constrained into a set with no
            # real Indian companies in it at all.
            .filter(Company.market == "INDIA")
            .filter(Company.tradeability == "NORMAL")
            .order_by(Company.market_cap.desc().nullslast(), Company.ticker.asc())
            .limit(limit_per_sector)
            .all()
        )
        for company in rows:
            if company.ticker in seen:
                continue
            seen.add(company.ticker)
            result.append(company)
    return result


def format_candidates(companies: list[Company], include_desc: bool | None = None) -> str:
    """One line per company for prompt injection. A missing sub_sector or
    business_desc is omitted rather than rendered as "None" -- a literal
    "None" in the prompt reads as a real value to the model.

    business_desc is the expensive part of the line (~100 chars against ~68
    for ticker + name + sub_sector), and every candidate also appears a
    second time inside the tool schema's ticker enum. Measured on the
    reassembled one-sector direct-stage prompt (system + user + tool JSON),
    priced with the two ratios the production 413s calibrate -- 4.9
    chars/token for the prose blocks (the full/slim pair differ by exactly
    the 27,887-char rulebook block and by 5,719 tokens) and 2.0-2.8
    chars/token for the ticker/JSON-dense blocks:

        60 candidates, desc kept    -> slim prompt ~6.5-8.3k tokens
        60 candidates, desc dropped -> slim prompt ~4.4-5.3k tokens

    openai/gpt-oss-20b allows 8,000 tokens/minute (llama-3.3-70b-versatile
    12,000), and the direct stage falls back to the slim prompt, so the slim
    path against the 8,000 ceiling is what has to fit -- and it has to fit
    with margin, not by a rounding error, which is why the threshold sits
    below MAX_CANDIDATES_PER_SECTOR rather than above it.

    Above LONG_LIST_THRESHOLD the description goes rather than the company: a
    candidate the model never sees cannot be selected at all, whereas one
    listed as ticker + name + sub_sector is still selectable -- the model
    knows what these companies do, the list is there to tell it which ones
    exist and resolve.

    include_desc forces the choice either way (tests, and any caller that has
    already sized its own prompt); None auto-decides on list length.
    """
    if include_desc is None:
        include_desc = len(companies) <= LONG_LIST_THRESHOLD
    lines = []
    for company in companies:
        parts = [f"- {company.ticker} ({company.name}"]
        if company.sub_sector:
            parts.append(f", {company.sub_sector}")
        parts.append(")")
        line = "".join(parts)
        if include_desc and company.business_desc:
            line += f": {company.business_desc}"
        lines.append(line)
    return "\n".join(lines)


def candidate_tickers(companies: list[Company]) -> list[str]:
    return [c.ticker for c in companies]
