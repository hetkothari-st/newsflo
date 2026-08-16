"""Exposure-ledger review console -- a STANDALONE server-rendered app.

    python tools/ledger_ui.py                  # http://127.0.0.1:8601
    python tools/ledger_ui.py --port 8601 --db sqlite:///./newsflo.db

DELIBERATELY NOT PART OF THE PRODUCT, exactly like tools/eval_ui.py: its own
FastAPI application with its own uvicorn, never a router mounted on
app/main.py. It is internal tooling that can WRITE THE LEDGER, so it must not
be reachable from the deployed service. Nothing under app/ imports this
module (tests/phase1/test_ledger_ui.py pins that).

Plain HTML, plain forms, no JavaScript, no build step (phase file: "Do not
build a React front-end for the review tool. Server-rendered, minimal,
functional."). Templates are inline f-strings with everything user-supplied
passed through html.escape().

Pages:
  GET  /                     the queue: PENDING_REVIEW, most valuable first
  GET  /ledger/proposal      one proposal: value, tag, verbatim excerpt,
                             link to the source document at the cited page
  POST /ledger/approve       APPROVE / EDIT+APPROVE  (the only write path)
  POST /ledger/reject        REJECT with a mandatory reason
  POST /ledger/bulk-approve  deterministic extractors only
  GET  /ledger/quality       extractor precision + reviewer throughput
  GET  /ledger/coverage      coverage by sector and tag, ledger age
  GET  /ledger/coverage.json the same, as JSON
  GET  /ledger/metrics       Prometheus text format
"""
from __future__ import annotations

import argparse
import html
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import sqlalchemy as sa  # noqa: E402
from fastapi import FastAPI, Form, Request  # noqa: E402
from fastapi.responses import (  # noqa: E402
    HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse,
)

from app.ledger import review as review_api  # noqa: E402
from app.ledger.coverage import (  # noqa: E402
    age_alert, coverage_rows, extractor_quality, ledger_stats, metrics_text,
)
from app.ledger.review import (  # noqa: E402
    EDITABLE_FIELDS, LedgerReviewError, approve_proposal, bulk_approve,
    get_proposal, pending_queue, reject_proposal, reviewer_throughput,
)

DEFAULT_PORT = 8601

_STYLE = """
<style>
 body { font: 15px/1.55 ui-serif, Georgia, serif; margin: 0 auto; max-width: 62rem;
        padding: 2rem 1.5rem 6rem; color: #111; background: #fbfbf9; }
 h1, h2 { font-weight: 600; letter-spacing: -0.01em; }
 h1 { font-size: 1.4rem; border-bottom: 1px solid #ddd; padding-bottom: .5rem; }
 .doc { border: 1px solid #ddd; background: #fff; padding: 1.25rem 1.5rem; margin: 1rem 0 2rem; }
 .excerpt { border-left: 3px solid #111; padding: .6rem .9rem; background: #fff;
        font: 14px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace; }
 .meta { font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; color: #666; }
 label { display: block; margin: 1rem 0 .2rem; font-weight: 600; font-size: .9rem; }
 input[type=text], textarea { width: 100%; padding: .45rem .55rem; font: inherit;
        border: 1px solid #bbb; background: #fff; }
 table { border-collapse: collapse; width: 100%; font-size: .9rem; }
 th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #e4e4e0; }
 th { font-size: .75rem; text-transform: uppercase; letter-spacing: .05em; color: #666; }
 button { margin-top: 1.2rem; padding: .55rem 1.4rem; font: inherit; cursor: pointer;
          border: 1px solid #111; background: #111; color: #fff; }
 button.secondary { background: #fff; color: #111; }
 .warn { border-left: 3px solid #b00; padding-left: .9rem; color: #700; }
 a { color: #111; }
 nav { font-size: .85rem; margin-bottom: 1rem; }
</style>
"""

_NAV = ("<nav><a href='/'>queue</a> &middot; <a href='/ledger/quality'>extractor "
        "quality</a> &middot; <a href='/ledger/coverage'>coverage</a> &middot; "
        "<a href='/ledger/metrics'>metrics</a></nav>")


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>{_STYLE}</head><body>{_NAV}{body}"
        f"</body></html>", status_code=status_code)


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _today() -> date:
    return datetime.now(timezone.utc).date()


def build_app(engine) -> FastAPI:
    """Build the review app over `engine`. Injected rather than global so
    tests can drive it against a throwaway database."""
    app = FastAPI(title="NewsFlo exposure ledger review", docs_url=None,
                  redoc_url=None)

    # ---------------------------------------------------------------- queue
    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        with engine.connect() as connection:
            rows = pending_queue(connection)
            stats = ledger_stats(connection, as_of=_today())
        header = (f"<p class='meta'>ledger: {stats['exposure_rows']} exposure row(s) "
                  f"across {stats['companies_tagged']} company(ies) &middot; "
                  f"{stats['stale_rows']} stale &middot; "
                  f"{stats['unverbatim_proposals']} proposal(s) discarded by the "
                  f"verbatim gate</p>")
        if not rows:
            return _page("Ledger review", (
                "<h1>Exposure ledger review</h1>" + header +
                "<p>No proposals are waiting. Nothing is invented to fill this "
                "queue: run an extraction over an acquired filing to produce "
                "proposals.</p>"))

        body = ["<h1>Exposure ledger review</h1>", header,
                f"<p class='meta'>{len(rows)} PENDING_REVIEW, ordered by market cap "
                f"&times; extraction uncertainty.</p>",
                "<form method='post' action='/ledger/bulk-approve'>",
                "<table><tr><th></th><th>company</th><th>tag</th><th>share</th>"
                "<th>kind</th><th>extractor</th><th>conf.</th><th></th></tr>"]
        for row in rows:
            deterministic = str(row["created_by"]).startswith(
                review_api.DETERMINISTIC_PREFIX)
            box = (f"<input type='checkbox' name='proposal_ids' "
                   f"value='{_esc(row['proposal_id'])}'>" if deterministic
                   else "<span class='meta' title='LLM proposals are never bulk "
                        "approved'>&mdash;</span>")
            body.append(
                f"<tr><td>{box}</td>"
                f"<td>{_esc(row['ticker'])}<div class='meta'>"
                f"{_esc(row['company_name'])}</div></td>"
                f"<td><code>{_esc(row['exposure_tag'])}</code></td>"
                f"<td>{_esc(row['share_of_base'])}</td>"
                f"<td>{_esc(row['exposure_kind'])}</td>"
                f"<td class='meta'>{_esc(row['created_by'])}</td>"
                f"<td>{_esc(row['extraction_confidence'])}</td>"
                f"<td><a href='/ledger/proposal?proposal_id="
                f"{quote(str(row['proposal_id']))}'>review</a></td></tr>")
        body += ["</table>",
                 "<label>Bulk approve as <input type='text' name='reviewed_by' "
                 "placeholder='human:name'></label>",
                 "<button type='submit' class='secondary'>Bulk approve selected "
                 "(deterministic extractors only)</button></form>"]
        return _page("Ledger review", "\n".join(body))

    # --------------------------------------------------------------- detail
    @app.get("/ledger/proposal", response_class=HTMLResponse)
    def proposal_detail(proposal_id: str = "") -> HTMLResponse:
        with engine.connect() as connection:
            proposal = get_proposal(connection, proposal_id)
        if proposal is None:
            return _page("Proposal", f"<h1 class='warn'>No such proposal "
                                     f"{_esc(proposal_id)}</h1>", status_code=404)

        page = _esc(proposal["source_page"])
        link = (f"<a href='{_esc(proposal['source_url'])}'>"
                f"{_esc(proposal['source_url'])}</a>")
        edits = "".join(
            f"<label>{field}<input type='text' name='edit_{field}' "
            f"value='' placeholder='{_esc(proposal.get(field))}'></label>"
            for field in EDITABLE_FIELDS)
        status_note = ""
        if proposal["status"] != "PENDING_REVIEW":
            status_note = (f"<p class='warn'>This proposal is "
                           f"{_esc(proposal['status'])}"
                           + (f" ({_esc(proposal['reject_reason'])})"
                              if proposal["reject_reason"] else "")
                           + ". It cannot be approved.</p>")

        body = f"""
<h1>{_esc(proposal['ticker'])} &mdash; <code>{_esc(proposal['exposure_tag'])}</code></h1>
<p class='meta'>proposal {_esc(proposal['proposal_id'])} &middot; proposed by
 {_esc(proposal['created_by'])} ({_esc(proposal['extractor_version'])}) &middot;
 status {_esc(proposal['status'])}</p>
{status_note}
<div class='doc'>
 <h2>Proposed value</h2>
 <table>
  <tr><th>share_of_base</th><td>{_esc(proposal['share_of_base'])}</td></tr>
  <tr><th>base_kind</th><td>{_esc(proposal['base_kind'])}</td></tr>
  <tr><th>base_value_inr</th><td>{_esc(proposal['base_value_inr'])}</td></tr>
  <tr><th>exposure_kind</th><td>{_esc(proposal['exposure_kind'])}</td></tr>
  <tr><th>measurement</th><td>{_esc(proposal['measurement'])}</td></tr>
  <tr><th>as_of_date</th><td>{_esc(proposal['as_of_date'])}</td></tr>
  <tr><th>source</th><td>{link} &mdash; page {page}</td></tr>
  <tr><th>document sha256</th><td class='meta'>{_esc(proposal['document_sha256'])}</td></tr>
 </table>
 <h2>Verbatim excerpt</h2>
 <p class='excerpt'>{_esc(proposal['excerpt'])}</p>
 <p class='meta'>This text was checked against the extracted document before the
  proposal was stored. Open the source at page {page} and confirm it says what the
  value claims.</p>
</div>
<form method='post' action='/ledger/approve'>
 <input type='hidden' name='proposal_id' value='{_esc(proposal['proposal_id'])}'>
 <label>Approve as <input type='text' name='reviewed_by' placeholder='human:name'></label>
 <details><summary class='meta'>edit before approving (leave blank to accept as
  proposed)</summary>{edits}</details>
 <button type='submit'>Approve</button>
</form>
<form method='post' action='/ledger/reject'>
 <input type='hidden' name='proposal_id' value='{_esc(proposal['proposal_id'])}'>
 <label>Reject as <input type='text' name='reviewed_by' placeholder='human:name'></label>
 <label>Reason <span class='meta'>(mandatory -- the rejection is kept and
  counted)</span><input type='text' name='reason'></label>
 <button type='submit' class='secondary'>Reject</button>
</form>
"""
        return _page("Proposal", body)

    # -------------------------------------------------------------- actions
    @app.post("/ledger/approve")
    async def approve(request: Request):
        form = await request.form()
        proposal_id = str(form.get("proposal_id", "")).strip()
        reviewed_by = str(form.get("reviewed_by", "")).strip()
        edits = {key[len("edit_"):]: value for key, value in form.items()
                 if key.startswith("edit_") and str(value).strip()}
        try:
            with engine.begin() as connection:
                approve_proposal(connection, proposal_id, reviewed_by=reviewed_by,
                                 edits=edits or None)
        except LedgerReviewError as exc:
            return _page("Approve", f"<h1 class='warn'>Not approved</h1>"
                                    f"<p>{_esc(exc)}</p><p>Nothing was written.</p>",
                         status_code=400)
        return RedirectResponse("/", status_code=303)

    @app.post("/ledger/reject")
    def reject(proposal_id: str = Form(...), reviewed_by: str = Form(""),
               reason: str = Form("")):
        try:
            with engine.begin() as connection:
                reject_proposal(connection, proposal_id.strip(),
                                reviewed_by=reviewed_by, reason=reason)
        except LedgerReviewError as exc:
            return _page("Reject", f"<h1 class='warn'>Not rejected</h1>"
                                   f"<p>{_esc(exc)}</p>", status_code=400)
        return RedirectResponse("/", status_code=303)

    @app.post("/ledger/bulk-approve")
    async def bulk(request: Request):
        form = await request.form()
        ids = [str(value).strip() for key, value in form.multi_items()
               if key == "proposal_ids" and str(value).strip()]
        reviewed_by = str(form.get("reviewed_by", "")).strip()
        if not ids:
            return _page("Bulk approve", "<h1 class='warn'>Nothing selected</h1>",
                         status_code=400)
        try:
            with engine.begin() as connection:
                bulk_approve(connection, ids, reviewed_by=reviewed_by)
        except LedgerReviewError as exc:
            return _page("Bulk approve",
                         f"<h1 class='warn'>Not approved</h1><p>{_esc(exc)}</p>"
                         f"<p>Nothing in the batch was written.</p>",
                         status_code=400)
        return RedirectResponse("/", status_code=303)

    # ------------------------------------------------------------ reporting
    @app.get("/ledger/quality", response_class=HTMLResponse)
    def quality() -> HTMLResponse:
        with engine.connect() as connection:
            extractors = extractor_quality(connection)
            reviewers = reviewer_throughput(connection)
        rows = "".join(
            f"<tr><td>{_esc(row['extractor'])}</td>"
            f"<td>{_esc(row['extractor_version'])}</td>"
            f"<td>{row['proposed']}</td><td>{row['approved']}</td>"
            f"<td>{row['edited']}</td><td>{row['rejected']}</td>"
            f"<td>{row['unverbatim']}</td>"
            f"<td>{_esc(row['approve_rate'])}</td>"
            f"<td>{_esc(row['edit_rate'])}</td></tr>" for row in extractors)
        who = "".join(
            f"<tr><td>{_esc(row['reviewer'])}</td><td>{row['reviewed']}</td>"
            f"<td>{row['approved']}</td><td>{row['edited']}</td></tr>"
            for row in reviewers)
        return _page("Extractor quality", f"""
<h1>Extractor quality</h1>
<p class='meta'>A falling approve rate, or a rising edit rate, is the signal that an
 extraction prompt regressed.</p>
<table><tr><th>extractor</th><th>version</th><th>proposed</th><th>approved</th>
<th>edited</th><th>rejected</th><th>unverbatim</th><th>approve rate</th>
<th>edit rate</th></tr>{rows or "<tr><td colspan='9'>no proposals yet</td></tr>"}</table>
<h2>Reviewer throughput</h2>
<table><tr><th>reviewer</th><th>reviewed</th><th>approved</th><th>edited</th></tr>
{who or "<tr><td colspan='4'>nobody has reviewed anything yet</td></tr>"}</table>
""")

    @app.get("/ledger/coverage", response_class=HTMLResponse)
    def coverage() -> HTMLResponse:
        as_of = _today()
        with engine.connect() as connection:
            rows = coverage_rows(connection, as_of=as_of)
            stats = ledger_stats(connection, as_of=as_of)
            alert = age_alert(connection, as_of=as_of)
        table = "".join(
            f"<tr><td>{_esc(row['sector'])}</td>"
            f"<td><code>{_esc(row['exposure_tag'])}</code></td>"
            f"<td>{row['companies_tagged']}</td>"
            f"<td>{_esc(row['pct_sector_market_cap_tagged'])}</td>"
            f"<td>{_esc(row['median_exposure_age_days'])}</td></tr>" for row in rows)
        return _page("Coverage", f"""
<h1>Coverage</h1>
{"<p class='warn'>" + _esc(alert) + "</p>" if alert else ""}
<p class='meta'>as of {as_of.isoformat()} &middot; p50 age
 {_esc(stats['age_p50_days'])} &middot; p90 age {_esc(stats['age_p90_days'])} &middot;
 {stats['stale_rows']} stale row(s)</p>
<table><tr><th>sector</th><th>tag</th><th>companies tagged</th>
<th>% of sector market cap</th><th>median age (days)</th></tr>
{table or "<tr><td colspan='5'>the ledger is empty -- no sector is reported as "
          "0% covered, because no sector has been looked at</td></tr>"}</table>
""")

    @app.get("/ledger/coverage.json")
    def coverage_json() -> JSONResponse:
        with engine.connect() as connection:
            return JSONResponse(coverage_rows(connection, as_of=_today()))

    @app.get("/ledger/metrics", response_class=PlainTextResponse)
    def metrics() -> PlainTextResponse:
        with engine.connect() as connection:
            return PlainTextResponse(metrics_text(connection, as_of=_today()))

    return app


def _default_db_url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite:///./newsflo.db")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Standalone exposure-ledger review console.")
    parser.add_argument("--db", default=None,
                        help="SQLAlchemy URL (default: $DATABASE_URL, else "
                             "sqlite:///./newsflo.db)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (default 127.0.0.1 -- this tool can "
                             "WRITE the ledger; do not expose it)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    import uvicorn

    url = args.db or _default_db_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = sa.create_engine(url, connect_args=connect_args)
    print(f"[ledger-ui] reviewing {url} on http://{args.host}:{args.port}/")
    uvicorn.run(build_app(engine), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
