"""Weekly rebuild of `transmission_empirical` (spec §10.1: "offline, rebuilt
weekly").

    python -m scripts.rebuild_transmission_matrix --help

NOT REGISTERED WITH THE SCHEDULER, deliberately. There is nothing to rebuild:
the price history this study computes over does not exist in this repo, so a
weekly job would do nothing but log an error every Sunday. When the data lands,
registering this module is a one-line change in the scheduler and the operator
decides the cadence.

WHAT YOU MUST SUPPLY. This script REFUSES to invent a price feed. It takes:

  * a `ReturnHistory` implementation, named as `module:factory` -- the object
    that knows how to read adjusted daily returns, benchmark returns and the
    company/benchmark mapping;
  * a shock series per variable, as `module:factory` returning
    `{variable: [(date, level)]}`.

Both are the owner's to provide (DATA_GAPS §9). Without them the script exits
non-zero and says exactly what is missing -- it does not fall back to a
"reasonable default" history, because a transmission matrix computed on
invented returns is the single most dangerous artifact this system could hold:
it would look like validation.
"""
import argparse
import importlib
import sys
from datetime import datetime, timezone

from sqlalchemy import text

from app.analysis.empirical.config import load_empirical_config
from app.analysis.empirical.event_study import (
    CAR_ESTIMATOR_VERSION, CarPriceHistory, build_transmission_rows,
    detect_shocks, persist_transmission_rows,
)
from app.db import SessionLocal


def _load(reference: str):
    """`package.module:callable` -> the object that callable returns."""
    if ":" not in reference:
        raise SystemExit(
            f"--{reference} must be given as 'package.module:factory'")
    module_name, attribute = reference.split(":", 1)
    return getattr(importlib.import_module(module_name), attribute)()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", required=True,
                        help="module:factory returning a ReturnHistory")
    parser.add_argument("--series", required=True,
                        help="module:factory returning {variable: [(date, level)]}")
    parser.add_argument("--dry-run", action="store_true",
                        help="compute and report, write nothing")
    args = parser.parse_args(argv)

    policy = load_empirical_config()
    history = _load(args.history)
    series_by_variable = _load(args.series)
    if not series_by_variable:
        print("no shock series supplied: nothing to rebuild", file=sys.stderr)
        return 2

    computed_at = datetime.now(timezone.utc)
    session = SessionLocal()
    try:
        company_ids = [int(row[0]) for row in session.execute(
            text("SELECT id FROM companies ORDER BY id ASC"))]
        if not company_ids:
            print("no companies: nothing to rebuild", file=sys.stderr)
            return 2

        prices = CarPriceHistory(history, policy=policy)
        total = 0
        for variable, series in sorted(series_by_variable.items()):
            shocks = detect_shocks(variable, series, policy=policy)
            for sign in ("UP", "DOWN"):
                days = tuple(s.day for s in shocks if s.sign == sign)
                if not days:
                    continue
                rows = build_transmission_rows(
                    prices, company_ids=company_ids, variable=variable,
                    shock_days=days, shock_sign=sign, policy=policy)
                print(f"{variable}/{sign}: {len(days)} shocks -> {len(rows)} rows "
                      f"({CAR_ESTIMATOR_VERSION})")
                if not args.dry_run:
                    total += persist_transmission_rows(session, rows,
                                                       computed_at=computed_at)
        if not args.dry_run:
            session.commit()
        print(f"wrote {total} rows")
        return 0
    finally:
        session.close()


if __name__ == "__main__":                            # pragma: no cover
    raise SystemExit(main())
