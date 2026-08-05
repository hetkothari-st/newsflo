"""Scores the CURRENT contents of the database against the golden set.

Reads what each golden alert actually has persisted rather than re-running
analysis, so it is cheap, repeatable, and safe to run after every task. Run
it before and after a change to see what moved.

Run directly (not just under pytest): `python score_golden.py` from the
backend/ directory. pytest.ini's `pythonpath = .` only applies inside
pytest, so a bare `python` invocation needs the backend/ directory on
sys.path itself -- which it already is, since Python always puts the
running script's own directory at sys.path[0]. The extra insert below is
belt-and-suspenders for the case this is invoked with a different cwd or
via `python -m` from elsewhere.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db import SessionLocal
from app.models import Alert, Company
from tests.golden.cases import GOLDEN_CASES
from tests.golden.score import score_all


def main() -> None:
    session = SessionLocal()
    try:
        results = {}
        for case in GOLDEN_CASES:
            alert = session.query(Alert).filter_by(id=case.alert_id).one_or_none()
            if alert is None:
                print(f"WARNING: golden alert {case.alert_id} not in this database")
                continue
            results[case.alert_id] = {
                session.get(Company, ac.company_id).ticker for ac in alert.companies
            }

        run = score_all(results)
        for case_score in run.cases:
            status = "OK " if not case_score.forbidden and not case_score.missing else "FAIL"
            print(f"[{status}] alert {case_score.alert_id}  "
                  f"precision={case_score.precision:.2f} recall={case_score.recall:.2f}")
            if case_score.forbidden:
                print(f"         MUST NOT be present: {sorted(case_score.forbidden)}")
            if case_score.missing:
                print(f"         MISSING:            {sorted(case_score.missing)}")

        print(f"\nmean precision {run.mean_precision:.2f}   "
              f"mean recall {run.mean_recall:.2f}   "
              f"forbidden companies present: {run.total_forbidden}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
