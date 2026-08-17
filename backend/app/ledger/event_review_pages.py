"""TASK 6.3 -- the review console PAGES.

Mounted ADDITIVELY onto the standalone review console under `tools/`, exactly
the way Phase 3's `edge_review_pages` and Phase 5's `divergence_review_pages`
were. ONE CONSOLE, FOUR QUEUES:

    /                    exposure proposals          (Phase 1)
    /graph/gaps          coverage gaps               (Phase 3)
    /divergence/queue    empirical / market divergence (Phase 5)
    /events              events awaiting review and labelling (this phase)

Plain HTML, plain forms, no JavaScript, no build step -- the phase file's
instruction for the exposure console applies here unchanged. Everything
user-supplied or model-supplied goes through `html.escape`.

WHAT A REVIEWER SEES, per event: the event and its shocks; the PRIMARY
candidates; the ripple candidates; the macro context; THE FULL REJECTED SET
WITH REASONS; the evidence behind each claim with links to the stored source;
the causal path per company; the materiality band and its driver ranking; the
applied policy modifiers; the empirical comparison; and every objection with
its resolution.

WHAT THEY CAN DO: attach one of the phase file's nine labels, signed with
their name, which lands in the Gate Zero eval corpus.

WHAT THEY CANNOT DO: change a verdict. This console holds no reducer
capability, so the database refuses it -- a console that let a reviewer edit
the record they are judging would make the corpus a measurement of the
reviewer's patience.
"""
import html
from typing import Any, Mapping, Sequence

from fastapi import Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.eval.schema import DIRECTIONS, EXPECTED_TIERS, STRATA
from app.ledger.event_review import (
    DISPLAY_TIERS, EventReviewError, REVIEW_LABELS, event_detail, event_index,
    record_label,
)


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _options(values: Sequence[str], blank: bool = False) -> str:
    head = "<option value=''></option>" if blank else ""
    return head + "".join(f"<option value='{_esc(v)}'>{_esc(v)}</option>"
                          for v in values)


def _band(sensitivity: Mapping[str, Any] | None) -> str:
    """The computed band and its top drivers, or an honest absence.

    Never a placeholder number: a record nobody could size says so in words.
    """
    if not sensitivity:
        return "<span class='meta'>no computed band on this record</span>"
    band = sensitivity.get("delta_ebitda_pct") or {}
    drivers = "".join(
        f"<li>{_esc(driver.get('param'))} &mdash; "
        f"{_esc(driver.get('contribution'))} "
        f"({_esc(driver.get('source'))})</li>"
        for driver in (sensitivity.get("driver_ranking") or [])[:5])
    return (f"p10 {_esc(band.get('p10'))} &middot; p50 {_esc(band.get('p50'))} "
            f"&middot; p90 {_esc(band.get('p90'))}"
            + (f"<ul>{drivers}</ul>" if drivers else ""))


def _evidence_list(entries: Sequence[Mapping[str, Any]]) -> str:
    if not entries:
        return "<span class='meta'>no evidence cited</span>"
    items = []
    for entry in entries:
        record = entry.get("record")
        if record is None:
            items.append(
                f"<li class='warn'><code>{_esc(entry['evidence_id'])}</code> "
                f"&mdash; no stored artefact resolves this id</li>")
            continue
        url = record.get("source_url")
        link = (f"<a href='{_esc(url)}'>{_esc(record.get('source_name'))}</a>"
                if url else _esc(record.get("source_name")))
        items.append(
            f"<li><code>{_esc(entry['evidence_id'])}</code> {link} "
            f"<span class='meta'>{_esc(record.get('source_type'))} &middot; "
            f"{_esc(record.get('source_date'))}</span></li>")
    return f"<ul>{''.join(items)}</ul>"


def _objections(entries: Sequence[Mapping[str, Any]]) -> str:
    if not entries:
        return "<span class='meta'>no objection was raised</span>"
    rows = []
    for entry in entries:
        answered = "".join(
            f"<div class='meta'>rebutted by <code>{_esc(r['rebuttal_id'])}</code>"
            f" ({_esc(r.get('stage'))}) citing "
            f"{_esc(r.get('cites_record_field') or r.get('cites_evidence_id'))}"
            f"</div>" for r in (entry.get("rebuttals") or ()))
        state = "sustained" if entry.get("sustained") else "not sustained"
        rows.append(
            f"<tr><td><code>{_esc(entry.get('type'))}</code></td>"
            f"<td>{_esc(entry.get('severity'))}</td>"
            f"<td>{state}{answered}</td>"
            f"<td class='meta'>{_esc(entry.get('raised_by'))} "
            f"{_esc(entry.get('model_id'))}</td></tr>")
    return ("<table><tr><th>type</th><th>severity</th><th>resolution</th>"
            "<th>raised by</th></tr>" + "".join(rows) + "</table>")


def _channels(entries: Sequence[Mapping[str, Any]]) -> str:
    if not entries:
        return "<span class='meta'>no channel recorded</span>"
    rows = "".join(
        f"<tr><td><code>{_esc(c.get('channel_id'))}</code></td>"
        f"<td>{_esc(c.get('mechanism_id'))}</td>"
        f"<td>{_esc(c.get('horizon'))}</td>"
        f"<td>{_esc(c.get('direction'))}</td>"
        f"<td>{_esc(c.get('materiality'))}</td>"
        f"<td>{_esc(c.get('material'))}</td></tr>" for c in entries)
    return ("<table><tr><th>channel</th><th>mechanism</th><th>horizon</th>"
            "<th>direction</th><th>materiality</th><th>material</th></tr>"
            + rows + "</table>")


def _company_block(view: Mapping[str, Any], event_id: str) -> str:
    """One company, with everything a reviewer needs to argue with it.

    The four separation fields are FOUR CELLS. They are never joined into one
    string -- master-context invariant 4, and the Phase 0 lint runs over this
    file to keep it that way.
    """
    modifiers = ", ".join(_esc(m) for m in (view.get("policy_modifiers") or ())) \
        or "<span class='meta'>none applied</span>"
    horizons = "".join(
        f"<tr><td>{_esc(name)}</td><td>{_esc(entry.get('direction'))}</td>"
        f"<td>{_esc(entry.get('materiality'))}</td>"
        f"<td>{_esc(entry.get('evaluated'))}</td></tr>"
        for name, entry in (view.get("direction_by_horizon") or {}).items())
    failed = "".join(
        f"<li><code>{_esc(rule.get('rule'))}</code> &mdash; "
        f"{_esc(rule.get('detail'))}</li>"
        for rule in (view.get("failed_gate_rules") or ()))

    return f"""
<div class='doc'>
 <h3>{_esc(view['ticker'])} <span class='meta'>company {_esc(view['company_id'])}
  &middot; trace {_esc(view['decision_trace_id'])}</span></h3>
 <table>
  <tr><th>tier</th><td>{_esc(view['publication_tier'])}</td>
      <th>directness</th><td>{_esc(view['directness'])}</td></tr>
  <tr><th>graph distance</th><td>{_esc(view['graph_distance'])}</td>
      <th>discovery source</th><td>{_esc(view['discovery_source'])}</td></tr>
  <tr><th>net effect</th><td>{_esc(view['net_effect'])}</td>
      <th>headline horizon</th><td>{_esc(view['headline_horizon'])}</td></tr>
  <tr><th>materiality</th><td>{_esc(view['materiality_bucket'])}</td>
      <th>mechanism</th><td>{_esc(view['mechanism_id'])}</td></tr>
  <tr><th>evidence grade</th><td>{_esc(view['evidence_grade'])}</td>
      <th>weakest link</th><td>{_esc(view['weakest_link'])}</td></tr>
  <tr><th>empirical</th><td>{_esc(view['empirical_status'])}</td>
      <th>needs reanalysis</th><td>{_esc(view['needs_reanalysis'])}</td></tr>
  {"<tr><th>rejection reason</th><td colspan='3'>"
   + _esc(view['rejection_reason']) + "</td></tr>"
   if view['rejection_reason'] else ""}
 </table>
 <h4>Causal path</h4>
 {_channels(view.get('channels') or ())}
 <h4>Horizon vector</h4>
 <table><tr><th>horizon</th><th>direction</th><th>materiality</th>
 <th>evaluated</th></tr>{horizons}</table>
 <h4>Materiality band and drivers</h4>
 {_band(view.get('sensitivity'))}
 <h4>Applied policy modifiers</h4>
 <p>{modifiers}</p>
 <h4>Evidence</h4>
 {_evidence_list(view.get('evidence') or ())}
 <h4>Objections and their resolution</h4>
 {_objections(view.get('objections') or ())}
 {"<h4>Gate rules that failed</h4><ul>" + failed + "</ul>" if failed else ""}
 {_label_form(event_id, view)}
</div>
"""


def _label_form(event_id: str, view: Mapping[str, Any]) -> str:
    """One click, one signature. `expected_tier` is pre-selected to what the
    system published, so CORRECT is a single click and a disagreement is an
    explicit change."""
    tiers = "".join(
        f"<option value='{_esc(t)}'"
        f"{' selected' if t == view['publication_tier'] else ''}>{_esc(t)}</option>"
        for t in EXPECTED_TIERS)
    return f"""
<form method='post' action='/event/label'>
 <input type='hidden' name='event_id' value='{_esc(event_id)}'>
 <input type='hidden' name='company_ref' value='{_esc(view['ticker'])}'>
 <label>label <select name='label'>{_options(REVIEW_LABELS)}</select></label>
 <label>expected tier <select name='expected_tier'>{tiers}</select></label>
 <label>expected direction
  <select name='expected_direction'>{_options(DIRECTIONS, blank=True)}</select></label>
 <label>expected mechanism <input type='text' name='expected_mechanism'></label>
 <label>stratum (optional, records the event in the corpus)
  <select name='stratum'>{_options(STRATA, blank=True)}</select></label>
 <label>labeler <input type='text' name='labeler' placeholder='human:name'></label>
 <label>rationale <input type='text' name='rationale'></label>
 <button type='submit' class='secondary'>Label</button>
</form>
"""


def register(app, engine, page) -> None:
    """Attach the Phase 6 routes to an existing console `app`."""

    @app.get("/events", response_class=HTMLResponse)
    def events() -> HTMLResponse:
        with engine.connect() as connection:
            rows = event_index(connection)

        body = "".join(
            f"<tr><td><a href='/event?event_id={_esc(row['event_id'])}'>"
            f"{_esc(row['event_id'])}</a><div class='meta'>"
            f"{_esc(row.get('title'))}</div></td>"
            f"<td>{_esc(row['PRIMARY'])}</td>"
            f"<td>{_esc(row['SECONDARY_RIPPLE'])}</td>"
            f"<td>{_esc(row['REJECTED'])}</td>"
            f"<td>{_esc(row['labels'])}</td></tr>" for row in rows)

        return page("Events", f"""
<h1>Events</h1>
<p class='meta'>Every event with a canonical record, with what published and
 what did not. The rejected column is the one worth watching: a run that
 rejects nothing is not exercising judgement.</p>
<table><tr><th>event</th><th>primary</th><th>ripple</th><th>rejected</th>
<th>labels</th></tr>
{body or "<tr><td colspan='5'>no canonical record has been written yet. "
         "company_impact is populated by the reducer, and V5 has no serving "
         "path -- see DATA_GAPS section 10.</td></tr>"}</table>
""")

    @app.get("/event", response_class=HTMLResponse)
    def event(event_id: str = "") -> HTMLResponse:
        with engine.connect() as connection:
            detail = event_detail(connection, event_id)
        if not detail["counts"]["companies"]:
            return page("Event", f"<h1 class='warn'>No canonical record for "
                                 f"{_esc(event_id)}</h1>", status_code=404)

        article = detail["article"]
        header = (f"<p class='meta'>{_esc(article['source'])} &middot; "
                  f"<a href='{_esc(article['url'])}'>{_esc(article['url'])}</a>"
                  f" &middot; {_esc(article['published_at'])}</p>"
                  f"<h2>{_esc(article['title'])}</h2>") if article else (
            "<p class='warn'>This event id resolves to no stored article.</p>")

        shocks = "".join(
            f"<li><code>{_esc(s['shock_variable'])}</code> {_esc(s['shock_sign'])}"
            f" at {_esc(s['horizon'])} &mdash; {_esc(s['status'])}</li>"
            for s in detail["shocks"]) or (
            "<li class='meta'>no shock variable is recorded for this event; "
            "the empirical stage has not run (DATA_GAPS section 10)</li>")

        sections = "".join(
            f"<li>{_esc(s['label'])} <span class='meta'>"
            f"{_esc(s['key']['horizon_bucket'])} &middot; median "
            f"{_esc(s['median_materiality'])}</span> &mdash; "
            + ", ".join(_esc(c["ticker"]) for c in s["companies"]) + "</li>"
            for s in detail["sections"])

        zero = ""
        if detail["zero_primary_text"]:
            zero = (f"<div class='doc'><pre>"
                    f"{_esc(detail['zero_primary_text'])}</pre></div>")

        groups = []
        for tier in DISPLAY_TIERS:
            views = detail["by_tier"][tier]
            if not views:
                continue
            groups.append(f"<h2>{_esc(tier)} &mdash; {len(views)}</h2>"
                          + "".join(_company_block(v, event_id) for v in views))

        rejected_count = len(detail["rejected"])
        rejected = "".join(_company_block(v, event_id) for v in detail["rejected"])

        return page("Event", f"""
<h1>Event review</h1>
{header}
<h3>Shocks</h3><ul>{shocks}</ul>
<h3>Sections</h3>
<ul>{sections or "<li class='meta'>nothing published</li>"}</ul>
{zero}
{"".join(groups)}
<h2>Rejected candidates &mdash; {rejected_count}</h2>
<p class='meta'>Every candidate that did not publish, with the reason and the
 gate rules that failed. A rejected candidate is retained, never deleted and
 never hidden.</p>
{rejected or "<p class='meta'>nothing was rejected for this event</p>"}
""")

    @app.post("/event/label")
    def label(event_id: str = Form(...), company_ref: str = Form(""),
              labeler: str = Form(""), label: str = Form(""),
              expected_tier: str = Form(""),
              expected_direction: str = Form(""),
              expected_mechanism: str = Form(""),
              rationale: str = Form(""), stratum: str = Form("")):
        try:
            with engine.begin() as connection:
                record_label(
                    connection, event_id=event_id, company_ref=company_ref,
                    labeler=labeler, label=label, expected_tier=expected_tier,
                    expected_direction=expected_direction or None,
                    expected_mechanism=expected_mechanism or None,
                    rationale=rationale or None, stratum=stratum or None)
        except EventReviewError as error:
            return page("Label", f"<h1 class='warn'>Not recorded</h1>"
                                 f"<p>{_esc(error)}</p><p>Nothing was written.</p>",
                        status_code=400)
        return RedirectResponse(f"/event?event_id={event_id}", status_code=303)
