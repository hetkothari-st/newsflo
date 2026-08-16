"""TASK 3.4 / 3.5 -- the mechanism-edge and coverage-gap review PAGES.

Mounted ADDITIVELY onto the Phase 1 review console under `tools/` rather
than given a server of its own: a reviewer approving an exposure and a
reviewer approving a mechanism edge is the same person doing the same kind
of work, and two consoles on two ports would be two habits.

Kept as a separate module for the same reason Phase 1 kept `review.py` out
of the console: the console is presentation, this is the route set, and
`app/ledger/edge_review.py` is the only thing that writes. Nothing here
imports the console -- the console imports this, and passes its own layout
function in.

Plain HTML, plain forms, no JavaScript, no build step -- the phase file's
instruction for the exposure console applies here unchanged.
"""
import html

from fastapi import Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.ledger.edge_review import (
    EdgeReviewError, approve_edge, edge_queue_stats, get_edge,
    open_coverage_gaps, pending_edges, reject_edge, rejected_edges,
)


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def register(app, engine, page) -> None:
    """Attach the Phase 3 routes to an existing console `app`.

    `page(title, body, status_code=200)` is the console's own layout
    function, passed in so the two sets of pages cannot drift apart visually.
    """
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)

    @app.get("/graph/edges", response_class=HTMLResponse)
    def edge_queue() -> HTMLResponse:
        with Session() as session:
            queue = pending_edges(session)
            rejected = rejected_edges(session, limit=50)
            stats = edge_queue_stats(session)

        rows = "".join(
            "<tr>"
            f"<td><code>{_esc(row['edge_id'])}</code></td>"
            f"<td>{_esc(row['from_node'])} &rarr; {_esc(row['to_node'])}</td>"
            f"<td><code>{_esc(row['exposure_tag'])}</code></td>"
            f"<td>{_esc(row['relationship_type'])}</td>"
            f"<td>{_esc(row['derivation'])}</td>"
            f"<td>{_esc(row['io_total_coeff'])}</td>"
            f"<td><a href='/graph/edge?edge_id={_esc(row['edge_id'])}'>review</a>"
            "</td></tr>" for row in queue)

        gone = "".join(
            "<tr>"
            f"<td><code>{_esc(row['edge_id'])}</code></td>"
            f"<td>{_esc(row['from_node'])} &rarr; {_esc(row['to_node'])}</td>"
            f"<td>{_esc(row['reviewed_by'])}</td>"
            f"<td>{_esc(row['review_note'])}</td></tr>" for row in rejected)

        return page("Mechanism edge review", f"""
<h1>Mechanism edge review</h1>
<p class='meta'>{stats['pending']} pending &middot; {stats['approved']} approved
 &middot; {stats['rejected']} rejected &middot; {stats['authored']} authored</p>
<p class='meta'>An IO_TABLE or EMPIRICAL edge is a <strong>hypothesis</strong>.
 Discovery will not walk one until somebody here says what the mechanism is,
 so an unreviewed queue is a graph that does not grow -- and a rejected edge
 is kept, with its reason, so the same coefficient is not re-proposed and
 re-argued next quarter.</p>
<table><tr><th>edge</th><th>path</th><th>exposure tag</th><th>relationship</th>
<th>derivation</th><th>total coeff</th><th></th></tr>
{rows or "<tr><td colspan='7'>nothing is waiting for review. The input-output "
         "tables have not been loaded -- see DATA_GAPS section 7.</td></tr>"}</table>
<h2>Rejected</h2>
<table><tr><th>edge</th><th>path</th><th>reviewer</th><th>reason</th></tr>
{gone or "<tr><td colspan='4'>nothing has been rejected</td></tr>"}</table>
""")

    @app.get("/graph/edge", response_class=HTMLResponse)
    def edge_detail(edge_id: str = "") -> HTMLResponse:
        with Session() as session:
            edge = get_edge(session, edge_id)
        if edge is None:
            return page("Not found", "<h1>No such edge</h1>", status_code=404)

        return page("Mechanism edge", f"""
<h1>{_esc(edge['from_node'])} &rarr; {_esc(edge['to_node'])}</h1>
<div class='doc'>
<p class='meta'>{_esc(edge['edge_id'])} &middot; {_esc(edge['derivation'])}
 &middot; status {_esc(edge['review_status'])}</p>
<table>
<tr><th>exposure tag</th><td><code>{_esc(edge['exposure_tag'])}</code></td></tr>
<tr><th>relationship</th><td>{_esc(edge['relationship_type'])}</td></tr>
<tr><th>authored distance</th><td>{_esc(edge['distance'])}</td></tr>
<tr><th>io total coeff</th><td>{_esc(edge['io_total_coeff'])}</td></tr>
<tr><th>table year</th><td>{_esc(edge['table_year'])}</td></tr>
<tr><th>source</th><td><a href='{_esc(edge['source_url'])}'>
{_esc(edge['source_url'])}</a></td></tr>
<tr><th>reviewed by</th><td>{_esc(edge['reviewed_by'])}</td></tr>
</table>
<p class='meta'>The coefficient tells you the size of the requirement. It does
 NOT tell you the mechanism, and it never sets a company's materiality -- that
 stays with the filed exposure ledger.</p>
<form method='post' action='/graph/approve'>
<input type='hidden' name='edge_id' value='{_esc(edge['edge_id'])}'>
<label>reviewer</label><input type='text' name='reviewed_by' required>
<label>mechanism note (what does this edge actually mean?)</label>
<textarea name='note' rows='3'></textarea>
<button type='submit'>Approve</button>
</form>
<form method='post' action='/graph/reject'>
<input type='hidden' name='edge_id' value='{_esc(edge['edge_id'])}'>
<label>reviewer</label><input type='text' name='reviewed_by' required>
<label>reason (mandatory)</label><input type='text' name='reason' required>
<button class='secondary' type='submit'>Reject</button>
</form>
</div>
""")

    @app.post("/graph/approve")
    def approve(edge_id: str = Form(...), reviewed_by: str = Form(""),
                note: str = Form("")):
        with Session() as session:
            try:
                approve_edge(session, edge_id, reviewed_by=reviewed_by,
                             note=note or None)
            except EdgeReviewError as error:
                session.rollback()
                return page("Refused", f"<h1>Refused</h1><p class='warn'>"
                                       f"{_esc(error)}</p>", status_code=400)
            session.commit()
        return RedirectResponse("/graph/edges", status_code=303)

    @app.post("/graph/reject")
    def reject(edge_id: str = Form(...), reviewed_by: str = Form(""),
               reason: str = Form("")):
        with Session() as session:
            try:
                reject_edge(session, edge_id, reviewed_by=reviewed_by,
                            reason=reason)
            except EdgeReviewError as error:
                session.rollback()
                return page("Refused", f"<h1>Refused</h1><p class='warn'>"
                                       f"{_esc(error)}</p>", status_code=400)
            session.commit()
        return RedirectResponse("/graph/edges", status_code=303)

    @app.get("/graph/gaps", response_class=HTMLResponse)
    def gap_queue() -> HTMLResponse:
        with Session() as session:
            gaps = open_coverage_gaps(session)

        rows = "".join(
            "<tr>"
            f"<td>{_esc(row['industry'])}</td>"
            f"<td>{_esc(row['variable'])} {_esc(row['sign'])}</td>"
            f"<td>{_esc(row['median_car'])}</td>"
            f"<td>{_esc(row['n'])}</td>"
            f"<td>{_esc(row['sign_consistency'])}</td>"
            f"<td>{_esc(row['p_value'])}</td>"
            f"<td>{_esc(row['priority'])}</td></tr>" for row in gaps)

        return page("Coverage gaps", f"""
<h1>Coverage gaps &mdash; industries that move and we cannot explain</h1>
<p class='meta'>Each row is an industry whose returns react to a shock
 variable consistently and significantly, and which the causal graph cannot
 reach. It is a <strong>work queue for graph authoring</strong>, ranked by how
 much it costs to keep ignoring it.</p>
<p class='warn'>None of this publishes. A row here is a statistic with no
 mechanism, and SECONDARY_RIPPLE requires a mechanism_id. The route out is:
 propose a mechanism &rarr; author the edge &rarr; have it reviewed &rarr; tag
 the companies. Skipping the middle turns this product into a correlation
 miner.</p>
<table><tr><th>industry</th><th>shock</th><th>median CAR</th><th>n</th>
<th>sign consistency</th><th>p</th><th>priority</th></tr>
{rows or "<tr><td colspan='7'>no gaps computed. The reverse event study needs "
         "price history the repo does not have -- see DATA_GAPS section 7."
         "</td></tr>"}</table>
""")
