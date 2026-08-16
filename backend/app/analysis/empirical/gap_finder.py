"""TASK 3.5 -- reverse event studies as a blind-spot detector (addendum A3).

    for each shock variable V and sign:
      1. CAR (+1d, +5d, +20d) for EVERY listed company across all historical
         instances of V
      2. aggregate by industry: median CAR, IQR, n, sign consistency, p
      3. keep industries with n >= 15, p < 0.05, sign consistent in >= 65%
      4. diff against what the graph can reach for V
      5. write the remainder to `coverage_gap`, ranked by
         |median CAR| x n x industry market cap

This is how the system stops discovering its own gaps by reading complaints.

THE DISCIPLINE (A3.2, invariant 7). Nothing here publishes. A `coverage_gap`
row is a statistic with NO MECHANISM, and `SECONDARY_RIPPLE` requires a
non-null `mechanism_id` that only a reviewed `mechanism_edge` can supply. The
route out of this queue is: a human proposes a mechanism, the edge is
authored and reviewed, the companies are tagged in the ledger, and only THEN
is anything publishable -- with a reason to show the user. Skipping the middle
turns the product into a correlation miner, and a ripple company published
with a CAR statistic and no mechanism is exactly the finding a senior analyst
would destroy you for: you are showing them a chart, not a reason.

ZERO NETWORK, BY CONSTRUCTION. This module NEVER fetches a price. It computes
over a `PriceHistory` object the caller hands it. The repo's own price access
is yfinance-based and therefore a live socket; wiring that in here would make
every test and every scheduler tick a network call waiting to happen. An ast
scan in `tests/phase3/test_gap_finder.py` refuses any import that could open
one.

WHAT DOES NOT EXIST YET. Eight-plus years of daily returns for the listed
universe, and a dated list of historical shock instances per variable. Both
are acquisition work and both are the owner's (DATA_GAPS §7). Until they
exist this module runs only on histories a test wrote, and no gap it produces
describes anything real.
"""
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Protocol, Sequence

from sqlalchemy import text

# Addendum A3.1's retention rule, verbatim. These are POLICY: how much
# evidence is enough before an industry earns a reviewer's attention.
MIN_INSTANCES = 15
MAX_P_VALUE = 0.05
MIN_SIGN_CONSISTENCY = 0.65

# The event windows §10 specifies. The finder aggregates on one of them at a
# time -- mixing horizons in a single median would be averaging two different
# questions.
CAR_WINDOWS = (1, 5, 20)
DEFAULT_WINDOW = 5


class PriceHistory(Protocol):
    """Everything this module needs from the market, and nothing more.

    One method, deliberately: `None` means "this company has no usable return
    for this event", which is the answer for a company that had not listed
    yet, was suspended, or simply has no data. A missing return is MISSING --
    it is never zero-filled, because a zero is a claim that the company did
    not move.
    """

    def cumulative_abnormal_return(self, company_id: int, event_date: date,
                                   window_days: int) -> float | None:
        ...


@dataclass(frozen=True)
class IndustryReaction:
    industry: str
    n: int
    median_car: float
    iqr_low: float
    iqr_high: float
    sign_consistency: float
    p_value: float
    industry_mcap: float | None
    companies: int


@dataclass(frozen=True)
class CoverageGapRow:
    industry: str
    variable: str
    sign: str
    window_days: int
    n: int
    median_car: float
    iqr_low: float
    iqr_high: float
    sign_consistency: float
    p_value: float
    industry_mcap: float | None
    priority: float


# --- statistics -------------------------------------------------------------

def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """Linear interpolation between order statistics (numpy's default), so a
    small sample does not jump between two neighbouring observations."""
    if not sorted_values:
        raise ValueError("no values")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = q * (len(sorted_values) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return float(sorted_values[int(position)])
    return float(sorted_values[low] * (high - position)
                 + sorted_values[high] * (position - low))


def sign_test_p_value(positive: int, negative: int) -> float:
    """Two-sided exact binomial sign test at p=0.5.

    Chosen over a t-test on purpose: abnormal returns are fat-tailed and a
    handful of crisis observations would dominate a mean. The question here is
    only "does this industry move the SAME WAY more often than a coin would",
    which is what the sign test answers, exactly, with no distributional
    assumption. Zero-return observations are excluded by the caller (a company
    that did not move casts no vote).
    """
    n = positive + negative
    if n == 0:
        return 1.0
    extreme = max(positive, negative)
    tail = sum(math.comb(n, k) for k in range(extreme, n + 1)) / (2 ** n)
    return min(1.0, 2.0 * tail)


def summarise(values: Sequence[float]) -> tuple[float, float, float, float, float]:
    """(median, iqr_low, iqr_high, sign_consistency, p_value)."""
    ordered = sorted(values)
    median = _quantile(ordered, 0.5)
    low = _quantile(ordered, 0.25)
    high = _quantile(ordered, 0.75)
    positive = sum(1 for v in values if v > 0)
    negative = sum(1 for v in values if v < 0)
    voting = positive + negative
    if voting == 0 or median == 0:
        # No direction is consistent with nothing. Phase 2 spells a p50 of
        # exactly zero the same way, and for the same reason.
        return median, low, high, 0.0, 1.0
    agreeing = positive if median > 0 else negative
    return (median, low, high, agreeing / voting,
            sign_test_p_value(positive, negative))


# --- the study --------------------------------------------------------------

def _universe(session) -> list[dict]:
    """Every listed company with an industry, and its market cap.

    `sub_sector` first, `sector` as the fallback: the finer grouping is the
    one a mechanism is authored against. A company with neither is skipped --
    it cannot be aggregated into anything."""
    return [dict(row) for row in session.execute(text(
        "SELECT id AS company_id, "
        "       COALESCE(sub_sector, sector) AS industry, "
        "       market_cap AS market_cap "
        "FROM companies "
        "WHERE COALESCE(sub_sector, sector) IS NOT NULL "
        "ORDER BY id ASC")).mappings().all()]


def industry_reactions(session, *, event_dates: Sequence[date],
                       history: PriceHistory,
                       window_days: int = DEFAULT_WINDOW
                       ) -> tuple[IndustryReaction, ...]:
    """Steps 1 and 2: CAR for the whole universe, aggregated by industry."""
    by_industry: dict[str, list[float]] = {}
    caps: dict[str, float] = {}
    members: dict[str, set[int]] = {}

    for row in _universe(session):
        company_id = int(row["company_id"])
        industry = str(row["industry"])
        for event_date in event_dates:
            car = history.cumulative_abnormal_return(
                company_id, event_date, window_days)
            if car is None:
                # No history is no observation. It is NEVER a zero: a zero
                # would say the company did not move, and would drag every
                # median in the table towards nothing.
                continue
            by_industry.setdefault(industry, []).append(float(car))
            members.setdefault(industry, set()).add(company_id)
        if row["market_cap"] is not None:
            caps[industry] = caps.get(industry, 0.0) + float(row["market_cap"])

    out = []
    for industry, values in sorted(by_industry.items()):
        median, low, high, consistency, p_value = summarise(values)
        out.append(IndustryReaction(
            industry=industry, n=len(values), median_car=median,
            iqr_low=low, iqr_high=high, sign_consistency=consistency,
            p_value=p_value, industry_mcap=caps.get(industry),
            companies=len(members.get(industry, ()))))
    return tuple(out)


def retain(reactions: Sequence[IndustryReaction], *, min_n: int = MIN_INSTANCES,
           max_p: float = MAX_P_VALUE,
           min_sign_consistency: float = MIN_SIGN_CONSISTENCY
           ) -> tuple[IndustryReaction, ...]:
    """Step 3. Everything that fails one of the three bars is dropped, not
    weakened."""
    return tuple(r for r in reactions
                 if r.n >= min_n and r.p_value < max_p
                 and r.sign_consistency >= min_sign_consistency)


def explained_industries(session, variable: str, *, as_of: date,
                         max_depth: int = 3) -> set[str]:
    """Step 4: the industries the graph can already reach for this variable.

    An industry counts as explained when a usable edge reaches an exposure
    tag AND a company in that industry actually carries it in the ledger.
    Both halves are required: an edge reaching a tag nobody is tagged with
    explains nothing about any company.
    """
    from app.graph.traverse import traverse

    tags = {edge.exposure_tag for edge in
            traverse(session, variable, as_of=as_of, max_depth=max_depth)}
    if not tags:
        return set()
    placeholders = ", ".join(f":t{i}" for i in range(len(tags)))
    parameters = {f"t{i}": tag for i, tag in enumerate(sorted(tags))}
    return {str(row[0]) for row in session.execute(text(
        "SELECT DISTINCT COALESCE(c.sub_sector, c.sector) "
        "FROM exposure_index e JOIN companies c ON c.id = e.company_id "
        f"WHERE e.exposure_tag IN ({placeholders})"), parameters)
        if row[0] is not None}


def priority_of(reaction: IndustryReaction) -> float:
    """|median CAR| x n x industry market cap (A3.1).

    An industry with no recorded market cap gets the |CAR| x n part only,
    rather than being multiplied by an invented cap. It therefore sorts below
    an equally-reacting industry whose size is known, which is the right
    default: we cannot argue it is expensive to ignore.
    """
    return abs(reaction.median_car) * reaction.n * float(
        reaction.industry_mcap if reaction.industry_mcap is not None else 1.0)


def find_coverage_gaps(session, *, variable: str, sign: str,
                       event_dates: Sequence[date], history: PriceHistory,
                       as_of: date, window_days: int = DEFAULT_WINDOW,
                       persist: bool = True) -> tuple[CoverageGapRow, ...]:
    """The whole procedure, steps 1-5. Returns the queue, highest first.

    Idempotent: the row is keyed on (variable, sign, industry), so running
    the study again refreshes the statistics instead of growing a log.
    """
    reactions = retain(industry_reactions(
        session, event_dates=event_dates, history=history,
        window_days=window_days))
    explained = explained_industries(session, variable, as_of=as_of)

    gaps = [
        CoverageGapRow(
            industry=r.industry, variable=variable, sign=sign,
            window_days=window_days, n=r.n, median_car=r.median_car,
            iqr_low=r.iqr_low, iqr_high=r.iqr_high,
            sign_consistency=r.sign_consistency, p_value=r.p_value,
            industry_mcap=r.industry_mcap, priority=priority_of(r))
        for r in reactions if r.industry not in explained]
    gaps.sort(key=lambda g: (-g.priority, g.industry))

    if persist:
        for gap in gaps:
            _persist(session, gap)
    return tuple(gaps)


def _persist(session, gap: CoverageGapRow) -> None:
    gap_id = f"gap:{gap.variable}:{gap.sign}:{gap.industry}"
    session.execute(text(
        "INSERT INTO coverage_gap (gap_id, variable, sign, industry, "
        "window_days, n, median_car, iqr_low, iqr_high, sign_consistency, "
        "p_value, industry_mcap, priority, status, computed_at) VALUES "
        "(:gap_id, :variable, :sign, :industry, :window_days, :n, :median_car, "
        ":iqr_low, :iqr_high, :sign_consistency, :p_value, :industry_mcap, "
        ":priority, 'OPEN', :computed_at) "
        "ON CONFLICT (variable, sign, industry) DO UPDATE SET "
        " window_days = excluded.window_days, n = excluded.n, "
        " median_car = excluded.median_car, iqr_low = excluded.iqr_low, "
        " iqr_high = excluded.iqr_high, "
        " sign_consistency = excluded.sign_consistency, "
        " p_value = excluded.p_value, industry_mcap = excluded.industry_mcap, "
        " priority = excluded.priority, computed_at = excluded.computed_at"), {
            "gap_id": gap_id, "variable": gap.variable, "sign": gap.sign,
            "industry": gap.industry, "window_days": gap.window_days,
            "n": gap.n, "median_car": gap.median_car, "iqr_low": gap.iqr_low,
            "iqr_high": gap.iqr_high, "sign_consistency": gap.sign_consistency,
            "p_value": gap.p_value, "industry_mcap": gap.industry_mcap,
            "priority": gap.priority,
            "computed_at": datetime.now(timezone.utc).isoformat()})
