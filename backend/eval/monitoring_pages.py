"""TASK 7.4 -- the monitoring signals, readable by a human today.

ADDITIVE, and READ-ONLY. One GET route mounted on the standalone ledger
console, exactly the way Phase 3's `edge_review_pages`, Phase 5's
`divergence_review_pages` and Phase 6's `event_review_pages` were mounted.
Nothing above the registration line in `tools/ledger_ui.py` changes.

WHY JSON AND NOT A DASHBOARD. There is no metrics stack in this repo and
Phase 7 is not the phase that buys one (DATA_GAPS section 11 names the gap
and its owner). A dashboard drawn here would be a dashboard nobody scrapes,
with no history and no alerting -- and it would look, on a screenshot, like
monitoring exists. A JSON endpoint is honestly what it is: the current value
of every Task 7.4 signal, refusals included, for whoever asks.

THIS MODULE LIVES UNDER `eval/`, NOT `app/`. The product does not import the
harness; the console does. Same rule the rest of the review console follows.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi.responses import JSONResponse

from eval.monitoring import alerting_signals, all_signals, as_json


def _today() -> date:
    return datetime.now(timezone.utc).date()


def register(app, engine, page) -> None:
    """Attach `/monitoring.json` to an existing console `app`.

    `page` (the console's layout function) is accepted for signature parity
    with every other `register` in the console and is deliberately unused:
    this route renders no HTML.
    """

    @app.get("/monitoring.json")
    def monitoring_json() -> JSONResponse:
        as_of = _today()
        with engine.connect() as connection:
            signals = all_signals(connection, as_of=as_of)
        return JSONResponse({
            "as_of": as_of.isoformat(),
            "signals": as_json(signals),
            "alerting": list(alerting_signals(signals)),
            "note": ("Dashboards and alerting are DEFERRED (DATA_GAPS section "
                     "11). A null value with a refusal means UNMEASURED, never "
                     "zero."),
        })
