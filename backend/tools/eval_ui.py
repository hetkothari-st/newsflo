"""Gate Zero labeling UI -- a STANDALONE server-rendered app.

    python tools/eval_ui.py                 # http://127.0.0.1:8600
    python tools/eval_ui.py --port 8601 --db sqlite:///./newsflo.db

DELIBERATELY NOT PART OF THE PRODUCT. This is its own FastAPI application
with its own uvicorn, not a router mounted on app/main.py: it is internal
labeling tooling for two people for about a week, it must never be
reachable from the deployed service, and V5 Session 0 is read-only with
respect to the running system. Nothing in app/ imports this module
(tests/test_gate_zero_tooling.py::test_ui_is_not_wired_into_the_production_app
pins that).

THE ONE RULE OF THIS UI: the labeler sees the EVENT and nothing else.

docs/v5/08_PHASE_7_eval_harness.md's labeling protocol: "Labelers see the
event only when producing expected sets. Never system output first --
anchoring destroys the label's value." So the labeling view reads exactly
two things: the eval_event row and the article it points at (headline +
body). It never reads alerts, per-company rows, tiers, mechanisms,
directions or sectors -- there is no code path in this file that can. A
single leaked ticker turns an independent judgment into agreement with the
machine, and the resulting precision number measures nothing.

Pages:
  GET  /                  index -- every event with labeling progress
  GET  /eval/label        the next event this labeler has not done
                          (?labeler=NAME, optional &event_id=)
  POST /eval/label        save one labeler's expectations for one event
  GET  /eval/adjudicate   both labelers side by side for one event
  POST /eval/adjudicate   record the per-company resolutions

Plain HTML, plain forms, no JavaScript, no build step. Templates are
inline f-strings with everything user-supplied passed through
html.escape() -- adding jinja2 templates (or any dependency) for four
pages would cost more than it buys.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import sqlalchemy as sa  # noqa: E402
from fastapi import FastAPI, Form, Request  # noqa: E402
from fastapi.responses import HTMLResponse, RedirectResponse  # noqa: E402

from app.eval import store  # noqa: E402
from app.eval.schema import DIRECTIONS, EXPECTED_TIERS, RESOLUTIONS  # noqa: E402

DEFAULT_PORT = 8600

_STYLE = """
<style>
 body { font: 15px/1.55 ui-serif, Georgia, serif; margin: 0 auto; max-width: 60rem;
        padding: 2rem 1.5rem 6rem; color: #111; background: #fbfbf9; }
 h1, h2 { font-weight: 600; letter-spacing: -0.01em; }
 h1 { font-size: 1.4rem; border-bottom: 1px solid #ddd; padding-bottom: .5rem; }
 .doc { border: 1px solid #ddd; background: #fff; padding: 1.25rem 1.5rem; margin: 1rem 0 2rem; }
 .doc h2 { margin-top: 0; font-size: 1.15rem; }
 .meta { font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; color: #666; }
 label { display: block; margin: 1rem 0 .2rem; font-weight: 600; font-size: .9rem; }
 .hint { font-size: .8rem; color: #666; font-weight: 400; }
 input[type=text], textarea { width: 100%; padding: .45rem .55rem; font: inherit;
        border: 1px solid #bbb; background: #fff; }
 textarea { min-height: 5rem; }
 table { border-collapse: collapse; width: 100%; font-size: .9rem; }
 th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #e4e4e0; }
 th { font-size: .75rem; text-transform: uppercase; letter-spacing: .05em; color: #666; }
 tr.diff td { background: #fff6e5; }
 button { margin-top: 1.5rem; padding: .55rem 1.4rem; font: inherit; cursor: pointer;
          border: 1px solid #111; background: #111; color: #fff; }
 .warn { border-left: 3px solid #b00; padding-left: .9rem; color: #700; }
 a { color: #111; }
</style>
"""


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>{_STYLE}</head><body>{body}</body></html>",
        status_code=status_code)


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def build_app(engine) -> FastAPI:
    """Build the labeling app over ``engine``. Injected rather than
    global so tests can drive it against a throwaway database."""
    app = FastAPI(title="NewsFlo Gate Zero labeling", docs_url=None, redoc_url=None)

    # ---------------------------------------------------------------- index
    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        with engine.connect() as conn:
            rows = store.event_progress(conn)
        if not rows:
            return _page("Gate Zero", "<h1>Gate Zero labeling</h1>"
                         "<p class='warn'>No events loaded. Import a corpus with "
                         "<code>python tools/eval_import.py --events events.csv</code>. "
                         "This tool never invents events.</p>")
        body = ["<h1>Gate Zero labeling</h1>",
                f"<p class='meta'>{len(rows)} event(s). Two independent labelers per "
                f"event are required before an event can be scored.</p>",
                "<table><tr><th>event</th><th>stratum</th><th>labelers</th>"
                "<th>adjudicated</th><th>disputed</th><th></th></tr>"]
        for row in rows:
            event_id = _esc(row["event_id"])
            body.append(
                f"<tr><td><code>{event_id}</code></td><td>{_esc(row['stratum'])}</td>"
                f"<td>{row['labeler_count']}/2 "
                f"<span class='meta'>{_esc(', '.join(row['labelers']))}</span></td>"
                f"<td>{row['adjudicated']}</td><td>{row['disputed']}</td>"
                f"<td><a href='/eval/adjudicate?event_id={event_id}'>adjudicate</a></td></tr>")
        body.append("</table>")
        return _page("Gate Zero", "\n".join(body))

    # ---------------------------------------------------------------- label
    @app.get("/eval/label", response_class=HTMLResponse)
    def label_form(labeler: str = "", event_id: str = "") -> HTMLResponse:
        if not labeler.strip():
            return _page("Label", "<h1>Who is labeling?</h1><form method='get'>"
                         "<label>Labeler identity<input type='text' name='labeler' "
                         "autofocus></label><button type='submit'>Start</button></form>")
        with engine.connect() as conn:
            target = event_id.strip() or store.next_unlabeled_event(conn, labeler)
            if not target:
                return _page("Label", f"<h1>Nothing left for {_esc(labeler)}</h1>"
                             "<p>Every loaded event has a label from you. "
                             "<a href='/'>Back to the index</a></p>")
            event = store.get_event(conn, target)
            if event is None:
                return _page("Label", f"<h1 class='warn'>No such event "
                             f"{_esc(target)}</h1><p><a href='/'>Index</a></p>")
            # The ONLY other reads in this handler, and the only ones
            # allowed: the article itself, and the GLOBAL family vocabulary.
            # The vocabulary is never filtered to this event -- it is the
            # whole taxonomy, identical on every page, so it tells the
            # labeler how to spell a family without hinting which one
            # applies here.
            article = store.resolve_article(conn, event["article_ref"])
            vocabulary = store.load_family_vocabulary(conn)

        if article is None:
            doc = ("<div class='doc warn'><h2>Article not found</h2>"
                   f"<p>event <code>{_esc(target)}</code> points at "
                   f"<code>{_esc(event['article_ref'])}</code>, which is not in the "
                   "articles table. Label from the source, or fix the reference -- "
                   "nothing is shown in its place.</p></div>")
        else:
            body_text = article.get("full_content") or article.get("content") or ""
            doc = (f"<div class='doc'><h2>{_esc(article['title'])}</h2>"
                   f"<p class='meta'>{_esc(article.get('source'))} &middot; "
                   f"{_esc(article.get('published_at'))} &middot; "
                   f"<a href='{_esc(article.get('url'))}'>source</a></p>"
                   f"<p>{_esc(body_text).replace(chr(10), '<br>')}</p></div>")

        family_terms = list(vocabulary["sub_sectors"]) + list(vocabulary["sectors"])
        families_options = "".join(
            f"<option value='{_esc(term)}'>" for term in family_terms)
        families_inline = _esc(", ".join(family_terms)) or "none — the companies " \
            "table has no sector/sub-sector values yet"
        family_count = len(family_terms)

        form = f"""
<h1>Label event <code>{_esc(target)}</code></h1>
<p class='meta'>labeler: {_esc(labeler)} &middot; stratum: {_esc(event['stratum'])} &middot;
 you are seeing the event only, by protocol -- no system output is loaded on this page.</p>
{doc}
<form method='post' action='/eval/label'>
 <input type='hidden' name='labeler' value='{_esc(labeler)}'>
 <input type='hidden' name='event_id' value='{_esc(target)}'>
 <label>Expected PRIMARY companies
  <span class='hint'>tickers, comma-separated. The companies a reader must be told
  about. Leave blank if there are none -- that is a real answer, and on a null
  event it is the right one.</span>
  <input type='text' name='primary_companies' autofocus></label>
 <label>Expected ripple families
  <span class='hint'>comma-separated family names — families, not companies.
  Type a slug from the list below wherever one fits: the scorer matches against
  this vocabulary, and common analyst wording (refiners, airlines, omc…) is
  translated via <code>config/eval_family_map.yaml</code>. Anything it cannot
  translate is reported, not scored.</span>
  <input type='text' name='ripple_families' list='family_vocabulary'></label>
 <datalist id='family_vocabulary'>{families_options}</datalist>
 <details><summary class='meta'>the {family_count} families this universe
  actually classifies companies into</summary>
  <p class='meta'>{families_inline}</p></details>
 <label>Expected ABSENT companies
  <span class='hint'>companies a reader might expect but that should NOT appear.</span>
  <input type='text' name='absent_companies'></label>
 <label>Expected direction per company
  <span class='hint'>TICKER:direction pairs, comma-separated, e.g.
  ACME:bearish, BETA:bullish. Allowed: {', '.join(DIRECTIONS)}. Omit a company to
  record no directional expectation for it.</span>
  <input type='text' name='directions'></label>
 <label>Rationale
  <span class='hint'>why -- in your own words, before seeing anything the system said.</span>
  <textarea name='rationale'></textarea></label>
 <button type='submit'>Save label</button>
</form>
<p class='meta'>Your PRIMARY and ABSENT lists are read as EXHAUSTIVE for this event: a
company you do not name is scored as one you expected to be absent.</p>
"""
        return _page("Label", form)

    @app.post("/eval/label")
    def label_save(labeler: str = Form(...), event_id: str = Form(...),
                   primary_companies: str = Form(""), absent_companies: str = Form(""),
                   ripple_families: str = Form(""), directions: str = Form(""),
                   rationale: str = Form("")):
        labeler = labeler.strip()
        directions_map = store.parse_direction_map(directions)
        # M5: a direction outside the vocabulary is rejected, not stored and
        # not silently dropped -- a labeler who wrote "sideways" meant
        # something, and the wrong-direction metric must never score against
        # a value nobody can interpret.
        unknown = sorted({d for d in directions_map.values() if d not in DIRECTIONS})
        if unknown:
            return _page("Label", (
                f"<h1 class='warn'>Unrecognized direction: "
                f"{_esc(', '.join(unknown))}</h1>"
                f"<p>Allowed: {', '.join(DIRECTIONS)}. Nothing was saved — press back "
                f"and correct the direction field.</p>"), status_code=400)
        families = store.parse_list(ripple_families)
        with engine.begin() as conn:
            for tier, raw in (("PRIMARY", primary_companies), ("ABSENT", absent_companies)):
                for company in store.parse_list(raw):
                    ref = store.normalize_company_ref(company)
                    store.upsert_label(
                        conn, event_id=event_id, company_ref=ref, labeler=labeler,
                        expected_tier=tier,
                        expected_direction=directions_map.get(ref),
                        rationale=rationale or None)
            # Always written, even with no families and no companies: it is
            # the record that this labeler DID label this event. Without it,
            # a correct "nothing happens here" null-event label would be
            # indistinguishable from an event nobody looked at.
            store.upsert_event_label(conn, event_id=event_id, labeler=labeler,
                                     ripple_families=families,
                                     rationale=rationale or None)
        # M6: a labeler name with a space (or any reserved character) must
        # survive the round trip.
        return RedirectResponse(f"/eval/label?labeler={quote(labeler)}", status_code=303)

    # ----------------------------------------------------------- adjudicate
    @app.get("/eval/adjudicate", response_class=HTMLResponse)
    def adjudicate_form(event_id: str = "") -> HTMLResponse:
        if not event_id.strip():
            return _page("Adjudicate", "<h1>Pick an event</h1><p><a href='/'>Index</a></p>")
        with engine.connect() as conn:
            event = store.get_event(conn, event_id)
            if event is None:
                return _page("Adjudicate",
                             f"<h1 class='warn'>No such event {_esc(event_id)}</h1>")
            labels = store.labels_for_event(conn, event_id)
            event_level = store.event_labels_for_event(conn, event_id)
            existing = store.adjudications_for_event(conn, event_id)
            labelers = store.labelers_for_event(conn, event_id)

        if len(labelers) < 2:
            return _page("Adjudicate",
                         f"<h1>Event <code>{_esc(event_id)}</code></h1>"
                         f"<p class='warn'>Only {len(labelers)} labeler(s) so far "
                         f"({_esc(', '.join(labelers))}). Two independent labels are "
                         f"required before adjudication means anything.</p>"
                         "<p><a href='/'>Index</a></p>")

        by_company: dict[str, dict[str, dict]] = {}
        for row in labels:
            by_company.setdefault(row["company_ref"], {})[row["labeler"]] = row

        rows = []
        for company, per_labeler in sorted(by_company.items()):
            cells = []
            tiers = []
            for who in labelers:
                entry = per_labeler.get(who)
                if entry is None:
                    # Unnamed by this labeler. Their lists are exhaustive by
                    # protocol, so silence means ABSENT -- shown explicitly
                    # as "(unnamed -> ABSENT)" so the adjudicator sees that
                    # it is an inference from the protocol, not typed input.
                    tiers.append("ABSENT")
                    cells.append("<td class='meta'>(unnamed &rarr; ABSENT)</td>")
                else:
                    tiers.append(entry["expected_tier"])
                    cells.append(
                        f"<td><strong>{_esc(entry['expected_tier'])}</strong> "
                        f"{_esc(entry.get('expected_direction') or '')}"
                        f"<div class='meta'>{_esc(entry.get('expected_mechanism') or '')}</div></td>")
            differs = len(set(tiers)) > 1
            current = existing.get(company, {}).get("resolution", "")
            # I4: LABELER_A/LABELER_B are positional (labelers sorted by
            # name). Naming them on the option is what stops an adjudicator
            # picking the wrong one.
            labels_for_option = {
                "": "— unresolved —",
                "LABELER_A": f"LABELER_A ({labelers[0]})",
                "LABELER_B": f"LABELER_B ({labelers[1]})",
                "MERGED": "MERGED", "DISPUTED": "DISPUTED",
            }
            options = "".join(
                f"<option value='{r}'{' selected' if current == r else ''}>"
                f"{_esc(labels_for_option.get(r, r))}</option>"
                for r in ("",) + RESOLUTIONS)
            rows.append(
                f"<tr class='{'diff' if differs else ''}'>"
                f"<td><code>{_esc(company)}</code></td>{''.join(cells)}"
                f"<td><select name='resolution_{_esc(company)}'>{options}</select></td>"
                f"<td><input type='text' name='note_{_esc(company)}' "
                f"value='{_esc(existing.get(company, {}).get('resolved_note') or '')}'></td></tr>")

        families = "".join(
            f"<li><strong>{_esc(row['labeler'])}</strong>: "
            f"{_esc(', '.join(row['ripple_families'])) or '<em>none</em>'}</li>"
            for row in event_level)

        head = "".join(f"<th>{_esc(who)}</th>" for who in labelers)
        page = f"""
<h1>Adjudicate <code>{_esc(event_id)}</code></h1>
<p class='meta'>stratum: {_esc(event['stratum'])} &middot;
 <strong>A = {_esc(labelers[0])}</strong> &middot; <strong>B = {_esc(labelers[1])}</strong>
 (roles are positional: the event's labelers sorted by name)</p>
<h2>Expected ripple families</h2><ul>{families or '<li><em>none recorded</em></li>'}</ul>
<h2>Per-company</h2>
<form method='post' action='/eval/adjudicate'>
 <input type='hidden' name='event_id' value='{_esc(event_id)}'>
 <label>Adjudicated by <input type='text' name='resolved_by'></label>
 <table><tr><th>company</th>{head}<th>resolution</th><th>note</th></tr>
 {''.join(rows)}</table>
 <p class='meta'>{', '.join(RESOLUTIONS)}. Leave a row blank to leave it unresolved --
 the scorer excludes an unresolved disagreement from the denominators and reports it,
 rather than assuming agreement. DISPUTED is a real answer: it is counted as the
 corpus's own ambiguity, never silently dropped.</p>
 <button type='submit'>Save adjudication</button>
</form>
<p><a href='/'>Index</a></p>
"""
        return _page("Adjudicate", page)

    @app.post("/eval/adjudicate")
    async def adjudicate_save(request: Request):
        form = await request.form()
        event_id = str(form.get("event_id", "")).strip()
        resolved_by = str(form.get("resolved_by", "")).strip() or None
        with engine.begin() as conn:
            for key, value in form.items():
                if not key.startswith("resolution_"):
                    continue
                resolution = str(value).strip()
                if not resolution:
                    continue  # left blank == still unresolved, and stays that way
                company = key[len("resolution_"):]
                note = str(form.get(f"note_{company}", "")).strip() or None
                store.upsert_adjudication(
                    conn, event_id=event_id, company_ref=company, resolution=resolution,
                    resolved_by=resolved_by, resolved_note=note)
        return RedirectResponse(f"/eval/adjudicate?event_id={quote(event_id)}",
                                status_code=303)

    return app


def _default_db_url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite:///./newsflo.db")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Standalone Gate Zero labeling UI.")
    parser.add_argument("--db", default=None,
                        help="SQLAlchemy URL (default: $DATABASE_URL, else sqlite:///./newsflo.db)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (default 127.0.0.1 -- internal tooling, "
                             "do not expose this)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    import uvicorn

    url = args.db or _default_db_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = sa.create_engine(url, connect_args=connect_args)
    print(f"[eval-ui] labeling {url} on http://{args.host}:{args.port}/  "
          f"(tiers: {', '.join(EXPECTED_TIERS)})")
    uvicorn.run(build_app(engine), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
