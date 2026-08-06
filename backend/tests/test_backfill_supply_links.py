"""backfill_supply_links.py's drain_extraction_queue -- same extraction
contract as app.scheduler._run_supply_links_refresh (see that module's
docstring), tested independently here since it is a distinct entry point
(no time budget, driven by a caller-supplied session rather than
SessionLocal) that duplicated the same logic pre-fix and must not
regress independently of the scheduler job.

2026-08-06 review, round 2: C2 circuit breaker + I3/I7/M3 honest
provenance (never default a fabricated value -- date.today(), an empty
source_url, or meta={} -- just to force a write through).
"""
import json
from datetime import date

import backfill_supply_links
from app.companies.supply_links import extract as supply_extract
from app.companies.supply_links import loader as supply_loader
from app.models import Company, Listing


def _write_doc(tmp_path, scrip_code, meta=None, write_url=True):
    url = f"https://x/AttachLive/{scrip_code}.pdf"
    pdf_path = backfill_supply_links.snapshot.doc_path(str(tmp_path), scrip_code, url)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    if write_url:
        backfill_supply_links.snapshot.url_sidecar_path(pdf_path).write_text(url, encoding="utf-8")
    if meta is None:
        meta = {
            "scrip_code": scrip_code, "company_name": "x", "agency": "CRISIL",
            "news_date": "2026-08-06T00:00:00",
        }
    if isinstance(meta, str):
        backfill_supply_links.snapshot.meta_sidecar_path(pdf_path).write_text(meta, encoding="utf-8")
    else:
        backfill_supply_links.snapshot.meta_sidecar_path(pdf_path).write_text(
            json.dumps(meta), encoding="utf-8",
        )
    return pdf_path


def test_drain_extraction_queue_circuit_breaker_stops_after_consecutive_llm_failures(
    monkeypatch, tmp_path, db_session,
):
    """C2: 6 pending docs that all come back llm_failed must stop the drain
    after SUPPLY_LLM_FAILURE_BREAKER (5) consecutive failures -- the 6th
    doc's extract_profile is never even attempted this run."""
    from app import config

    monkeypatch.setattr(backfill_supply_links, "build_client", lambda *a, **kw: object())
    monkeypatch.setattr(backfill_supply_links.snapshot, "DEFAULT_ROOT", str(tmp_path))

    for i in range(6):
        company = Company(ticker=f"FAIL{i}.NS", name=f"Fail {i} Ltd", sector="other", index_tier="OTHER")
        db_session.add(company)
        db_session.flush()
        db_session.add(Listing(
            company_id=company.id, exchange="BSE", symbol=f"FAIL{i}", scrip_code=str(900 + i),
            source="test", as_of=date(2026, 1, 1),
        ))
        _write_doc(tmp_path, str(900 + i))
    db_session.commit()

    monkeypatch.setattr(supply_extract, "pdf_text", lambda _p: "some rationale text")
    calls = []

    def always_fail(client, name, text):
        calls.append(name)
        return None

    monkeypatch.setattr(supply_extract, "extract_profile", always_fail)

    backfill_supply_links.drain_extraction_queue(db_session)

    assert len(calls) == config.SUPPLY_LLM_FAILURE_BREAKER  # 6th doc never attempted
    pending = backfill_supply_links.snapshot.pending_docs(str(tmp_path))
    assert len(pending) == 6  # nothing marked extracted


def test_drain_extraction_queue_unparsable_news_date_never_stamped_today(monkeypatch, tmp_path, db_session):
    """I3: a missing/unparsable news_date must count "errored" and leave the
    doc pending -- never default to date.today()."""
    monkeypatch.setattr(backfill_supply_links, "build_client", lambda *a, **kw: object())
    monkeypatch.setattr(backfill_supply_links.snapshot, "DEFAULT_ROOT", str(tmp_path))

    company = Company(ticker="STALE.NS", name="Stale Ltd", sector="other", index_tier="OTHER")
    db_session.add(company)
    db_session.flush()
    db_session.add(Listing(
        company_id=company.id, exchange="BSE", symbol="STALE", scrip_code="950",
        source="test", as_of=date(2026, 1, 1),
    ))
    db_session.commit()

    pdf_path = _write_doc(tmp_path, "950", meta={
        "scrip_code": "950", "company_name": "Stale Ltd", "agency": "CRISIL",
        "news_date": "not-a-real-date",
    })

    monkeypatch.setattr(supply_extract, "pdf_text", lambda _p: "some rationale text")
    monkeypatch.setattr(
        supply_extract, "extract_profile",
        lambda client, name, text: {"business_summary": None, "suppliers": [], "customers": []},
    )
    apply_calls = []
    monkeypatch.setattr(
        supply_loader, "apply_extraction",
        lambda *a, **kw: apply_calls.append(kw) or {"links_written": 0},
    )

    backfill_supply_links.drain_extraction_queue(db_session)

    assert apply_calls == []
    assert not backfill_supply_links.snapshot.done_marker_path(pdf_path).exists()


def test_drain_extraction_queue_unreadable_url_sidecar_stays_pending(monkeypatch, tmp_path, db_session):
    """I7: an unreadable .url sidecar must count "errored" and leave the doc
    pending, never fall back to source_url=""."""
    monkeypatch.setattr(backfill_supply_links, "build_client", lambda *a, **kw: object())
    monkeypatch.setattr(backfill_supply_links.snapshot, "DEFAULT_ROOT", str(tmp_path))

    company = Company(ticker="NOURL.NS", name="No URL Ltd", sector="other", index_tier="OTHER")
    db_session.add(company)
    db_session.flush()
    db_session.add(Listing(
        company_id=company.id, exchange="BSE", symbol="NOURL", scrip_code="951",
        source="test", as_of=date(2026, 1, 1),
    ))
    db_session.commit()

    pdf_path = _write_doc(tmp_path, "951", write_url=False)

    extract_calls = []
    monkeypatch.setattr(supply_extract, "pdf_text", lambda _p: extract_calls.append(1) or "text")
    apply_calls = []
    monkeypatch.setattr(supply_loader, "apply_extraction", lambda *a, **kw: apply_calls.append(kw))

    backfill_supply_links.drain_extraction_queue(db_session)

    assert extract_calls == []
    assert apply_calls == []
    assert not backfill_supply_links.snapshot.done_marker_path(pdf_path).exists()


def test_drain_extraction_queue_corrupt_meta_sidecar_stays_pending_not_unmatched(
    monkeypatch, tmp_path, db_session,
):
    """M3: a corrupt/unreadable meta.json must count "errored" and leave the
    doc pending, NOT fall through to meta={} -> unmatched_scrip ->
    mark_extracted."""
    monkeypatch.setattr(backfill_supply_links, "build_client", lambda *a, **kw: object())
    monkeypatch.setattr(backfill_supply_links.snapshot, "DEFAULT_ROOT", str(tmp_path))

    pdf_path = _write_doc(tmp_path, "952", meta="{not valid json")

    extract_calls = []
    monkeypatch.setattr(supply_extract, "pdf_text", lambda _p: extract_calls.append(1) or "text")

    backfill_supply_links.drain_extraction_queue(db_session)

    assert extract_calls == []
    assert not backfill_supply_links.snapshot.done_marker_path(pdf_path).exists()
