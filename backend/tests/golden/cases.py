"""Hand-labelled golden alerts.

`must_include` / `must_exclude` are deliberately PARTIAL: they name only the
companies a human is confident about. A ticker in neither set is treated as
unknown and does not count for or against a run -- so adding a case is cheap
and never punishes the pipeline for a judgement call nobody made.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GoldenCase:
    alert_id: int
    title: str
    must_include: set[str] = field(default_factory=set)
    must_exclude: set[str] = field(default_factory=set)


GOLDEN_CASES: list[GoldenCase] = [
    GoldenCase(
        alert_id=9020,
        title="Crude oil supply shock hits refiners",
        # HPCL.NS -> HINDPETRO.NS: the stock-universe merge (commit
        # e4b39bf, "fix broken tickers") renamed this company's ticker.
        # HINDPETRO is the correct NSE symbol for Hindustan Petroleum --
        # HPCL.NS never was a real NSE ticker. Same company, same row on
        # alert 9020; this is not a re-labelling of what belongs on the
        # alert, just a stale ticker string.
        must_include={"HINDPETRO.NS", "BPCL.NS", "INDIGO.NS", "ASIANPAINT.NS"},
        must_exclude={
            # Food delivery / quick commerce -- no crude mechanism. The
            # original reported bug.
            "ETERNAL.NS",
            # Reached only via the L1/L2 fan-out, which had no article-
            # specific mechanism for any of them.
            "BAJAJ-AUTO.NS", "MARUTI.NS", "EICHERMOT.NS", "M&M.NS", "TMPV.NS",
            "HDFCBANK.NS", "AXISBANK.NS", "BAJFINANCE.NS", "BAJAJFINSV.NS",
            "HDFCLIFE.NS", "NTPC.NS", "POWERGRID.NS", "ULTRACEMCO.NS",
            # Demo seed row that should not exist in production at all.
            "SOMETEXTILE.NS",
        },
    ),
]
