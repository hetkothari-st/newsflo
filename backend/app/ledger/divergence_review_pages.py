"""TASK 5.2 / 5.5 -- the divergence review PAGES (review round 1, I-4).

Mounted ADDITIVELY onto the standalone Phase 1 review console under `tools/`,
exactly the way Phase 3's `edge_review_pages` was: a reviewer approving an
exposure, a reviewer approving a mechanism edge and a reviewer adjudicating a
disagreement with history are the same person doing the same kind of work, and
three consoles on three ports would be three habits.

THIS IS INTERNAL TOOLING, NOT V5 SERVING. The standing "V5 has no serving
path" ruling covers the PRODUCT surface; it does not cover the console that
lets a human do the job §10.3 requires a human to do. Without this page the
`divergence_review` queue is a table nobody can empty and `REGIME_CHANGED` is
an annotation nobody can write -- which would make "conflict routes to a human
reviewer" a claim with no human in it.

Plain HTML, plain forms, no JavaScript, no build step -- the phase file's
instruction for the exposure console applies here unchanged. Nothing under
`app/` imports the console; the console imports this and passes its own layout
function in.

WHAT A REVIEWER CAN DO HERE, AND WHAT THEY CANNOT:

  * see every OPEN disagreement, of both kinds, with the sample behind it;
  * resolve one as UPHELD / MODEL_WRONG / NOISE / REGIME_CHANGED, always with
    a reason and a name;
  * REGIME_CHANGED additionally requires an EXPIRY, and the form refuses
    without one -- there is no permanent option (§10.3).

They cannot edit a CAR, a median or a p-value: those are measurements, and a
console that let a reviewer adjust the evidence they disagree with would be
the opposite of a falsifier.
"""
import html
from datetime import date, datetime, timezone

from fastapi import Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.analysis.empirical.divergence import (
    RESOLUTION_REGIME_CHANGED, RESOLUTIONS, open_reviews, resolve,
)
from app.analysis.empirical.regime import RegimeChangeRefused, listed_regime_changes


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _pct(value) -> str:
    """A stored CAR is a FRACTION; a reviewer reads percent. Converted here,
    at the only place a human sees it, rather than in the table."""
    if value is None:
        return ""
    return f"{float(value) * 100:.2f}%"


def register(app, engine, page) -> None:
    """Attach the Phase 5 routes to an existing console `app`."""
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)

    @app.get("/divergence/queue", response_class=HTMLResponse)
    def divergence_queue() -> HTMLResponse:
        with Session() as session:
            queue = open_reviews(session)
            annotations = listed_regime_changes(session,
                                                as_of=datetime.now(timezone.utc).date())

        rows = "".join(
            "<tr>"
            f"<td>{_esc(row['kind'])}</td>"
            f"<td>{_esc(row['company_id'])}</td>"
            f"<td>{_esc(row['shock_variable'])} {_esc(row['shock_sign'])} "
            f"{_esc(row['horizon'])}</td>"
            f"<td>{_esc(row['fundamental_direction'])}</td>"
            f"<td>{_pct(row['median_car'])}</td>"
            f"<td>{_esc(row['n_events'])}</td>"
            f"<td>{_esc(row['p_value'])}</td>"
            f"<td><a href='/divergence/review?review_id={_esc(row['review_id'])}'>"
            "review</a></td></tr>" for row in queue)

        annotated = "".join(
            "<tr>"
            f"<td>{_esc(row['company_id'])}</td>"
            f"<td><code>{_esc(row['shock_class'])}</code></td>"
            f"<td>{_esc(row['reviewed_by'])}</td>"
            f"<td>{_esc(row['expires_on'])}</td>"
            f"<td>{'active' if row['active'] else 'lapsed'}</td>"
            f"<td>{_esc(row['reason'])}</td></tr>" for row in annotations)

        return page("Divergence review", f"""
<h1>Divergence review &mdash; where history and the model disagree</h1>
<p class='meta'>An EMPIRICAL_CONFLICT is capped at SECONDARY_RIPPLE and sent
 here; it is <strong>never auto-rejected</strong>. Empirical history can be
 dominated by a regime that no longer applies, and the market may simply have
 been wrong &mdash; that is the alpha this product claims. A MARKET_DIVERGENCE
 changes nothing at all: it is a monitoring signal, never a correction.</p>
<table><tr><th>kind</th><th>company</th><th>shock</th><th>our read</th>
<th>median CAR</th><th>n</th><th>p</th><th></th></tr>
{rows or "<tr><td colspan='8'>nothing is waiting for review. The transmission "
         "matrix is empty -- the event study has no price history to run on, "
         "see DATA_GAPS section 9.</td></tr>"}</table>
<h2>Regime-change annotations</h2>
<p class='meta'>Each one lets a company make a PRIMARY call against its own
 measured history, for a limited time. There is no permanent option: an
 annotation nobody re-affirms lapses, and the conflict caps the tier again.</p>
<table><tr><th>company</th><th>shock class</th><th>reviewer</th>
<th>expires</th><th>state</th><th>reason</th></tr>
{annotated or "<tr><td colspan='6'>none recorded</td></tr>"}</table>
""")

    @app.get("/divergence/review", response_class=HTMLResponse)
    def divergence_detail(review_id: str = "") -> HTMLResponse:
        with Session() as session:
            match = [row for row in open_reviews(session)
                     if row["review_id"] == review_id]
        if not match:
            return page("Not found", "<h1>No such open review</h1>",
                        status_code=404)
        row = match[0]
        options = "".join(
            f"<option value='{_esc(name)}'>{_esc(name)}</option>"
            for name in RESOLUTIONS)

        return page("Divergence", f"""
<h1>{_esc(row['kind'])} &mdash; company {_esc(row['company_id'])}</h1>
<div class='doc'>
<p class='meta'>{_esc(row['review_id'])} &middot; opened
 {_esc(row['created_at'])}</p>
<table>
<tr><th>event</th><td>{_esc(row['event_id'])}</td></tr>
<tr><th>shock</th><td>{_esc(row['shock_variable'])} {_esc(row['shock_sign'])}
 at {_esc(row['horizon'])}</td></tr>
<tr><th>our fundamental read</th><td>{_esc(row['fundamental_direction'])}</td></tr>
<tr><th>empirical status</th><td>{_esc(row['empirical_status'])}</td></tr>
<tr><th>median abnormal return</th><td>{_pct(row['median_car'])}</td></tr>
<tr><th>comparable shocks</th><td>{_esc(row['n_events'])}</td></tr>
<tr><th>p-value</th><td>{_esc(row['p_value'])}</td></tr>
<tr><th>excess move</th><td>{_esc(row['excess_move_pct'])}%</td></tr>
</table>
<p class='meta'>You cannot edit the measurement. If you believe the history no
 longer describes this company, say so as REGIME_CHANGED with a reason and a
 date it must be re-argued.</p>
<form method='post' action='/divergence/resolve'>
<input type='hidden' name='review_id' value='{_esc(row['review_id'])}'>
<label>resolution</label>
<select name='resolution'>{options}</select>
<label>reviewer</label><input type='text' name='reviewed_by' required>
<label>reason (mandatory)</label><input type='text' name='reason' required>
<label>expires on (YYYY-MM-DD, REQUIRED for {_esc(RESOLUTION_REGIME_CHANGED)})
</label><input type='text' name='expires_on'>
<button type='submit'>Resolve</button>
</form>
</div>
""")

    @app.post("/divergence/resolve")
    def divergence_resolve(review_id: str = Form(...), resolution: str = Form(...),
                           reviewed_by: str = Form(""), reason: str = Form(""),
                           expires_on: str = Form("")):
        now = datetime.now(timezone.utc)
        try:
            expiry: date | None = (date.fromisoformat(expires_on.strip())
                                   if expires_on.strip() else None)
        except ValueError:
            return page("Refused", "<h1>Refused</h1><p class='warn'>"
                                   "expires_on must be YYYY-MM-DD</p>",
                        status_code=400)
        with Session() as session:
            try:
                resolve(session, review_id, resolution=resolution, reason=reason,
                        reviewed_by=reviewed_by, resolved_at=now,
                        expires_on=expiry)
            except (RegimeChangeRefused, ValueError) as error:
                session.rollback()
                return page("Refused", f"<h1>Refused</h1><p class='warn'>"
                                       f"{_esc(error)}</p>", status_code=400)
            session.commit()
        return RedirectResponse("/divergence/queue", status_code=303)
