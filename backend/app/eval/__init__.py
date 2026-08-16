"""Gate Zero evaluation harness (V5 Session 0).

Schema and storage helpers for the labeled-corpus tooling described in
docs/v5/EXECUTION_CONTRACT.md §2 and docs/v5/08_PHASE_7_eval_harness.md
Task 7.1.

NOTHING in this package participates in the running application. It is
imported only by the standalone labeling UI (backend/tools/eval_ui.py),
the offline importer (backend/tools/eval_import.py) and the baseline
scorer (backend/scripts/score_baseline.py). app/main.py does not import it,
and the eval tables deliberately live on their own MetaData so
app.db.init_db()'s create_all() never touches them.
"""
