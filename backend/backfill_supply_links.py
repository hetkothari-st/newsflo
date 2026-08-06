"""Historical supply-links bootstrap.

    python backfill_supply_links.py --months 24     # walk the announcement archive
    python backfill_supply_links.py --extract-only  # just drain pending docs

Walks BSE credit-rating announcements backwards month-by-month, fetches
rationale PDFs (news-active companies first), then drains the extraction
queue with no time budget. Resumable at every stage; safe to rerun.

Fetching and extraction are deliberately two passes, not interleaved: a
partial/interrupted fetch pass still leaves every already-fetched PDF sane
on disk (resumable via the .url sidecar, same as the daily
rating_filings_poll job), and a rerun of `--extract-only` alone will always
pick up wherever the previous extraction pass stopped.
"""
import argparse
import json
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app import config
from app.analysis.claude_client import build_client
from app.companies.market_caps import alert_referenced_tickers
from app.companies.supply_links import extract, fetchers, loader, snapshot
from app.config import settings
from app.db import SessionLocal
from app.models import Company, Listing

_THROTTLE_SECONDS = 1.0
_PROGRESS_EVERY = 25
# BSE's own cap is ~30 days (fetchers.py); 28 keeps every window comfortably
# under it, same margin fetchers._MAX_WINDOW_DAYS uses for a single call.
_WINDOW_DAYS = 28


def _month_windows(months: int, today: date | None = None) -> list[tuple[date, date]]:
    """[from, to] windows walking backward from today, most-recent first --
    an interrupted run has already fetched the freshest (most useful)
    history before an older window is even attempted."""
    today = today or date.today()
    windows = []
    end = today
    for _ in range(months):
        start = end - timedelta(days=_WINDOW_DAYS - 1)
        windows.append((start, end))
        end = start - timedelta(days=1)
    return windows


def _partition_news_active_first(session: Session, targets: list[dict]) -> list[dict]:
    """News-active companies' rationales first -- these are the companies
    whose alerts actually render a KNOWN RELATIONSHIPS block
    (app.companies.supply_links.prompting), so their documents deliver
    value immediately instead of waiting behind however much of a 24-month
    backlog sits ahead of them alphabetically/chronologically."""
    active_tickers = alert_referenced_tickers(session, days=3650)
    if not active_tickers:
        return targets

    active_scrip_codes = {
        code
        for (code,) in (
            session.query(Listing.scrip_code)
            .join(Company, Listing.company_id == Company.id)
            .filter(Company.ticker.in_(active_tickers), Listing.scrip_code.isnot(None))
            .all()
        )
    }
    if not active_scrip_codes:
        return targets

    active = [t for t in targets if t.get("scrip_code") in active_scrip_codes]
    inactive = [t for t in targets if t.get("scrip_code") not in active_scrip_codes]
    return active + inactive


def fetch_history(session: Session, months: int) -> None:
    root = snapshot.DEFAULT_ROOT
    windows = _month_windows(months)
    for i, (start, end) in enumerate(windows, start=1):
        print(f"[{i}/{len(windows)}] announcements {start.isoformat()}..{end.isoformat()}")
        try:
            # Keyed by the window's own end date (not "today") so each
            # window's index snapshot survives a later window's fetch in
            # the same run, and a rerun of an already-covered window is a
            # cheap metadata refetch rather than lost history.
            rows = fetchers.fetch_announcements(root, end, start, end)
        except Exception as exc:
            print(f"  announcements fetch failed: {exc}")
            continue

        targets = fetchers.parse_announcements(rows)
        targets = _partition_news_active_first(session, targets)
        result = fetchers.fetch_documents(root, targets, throttle_seconds=_THROTTLE_SECONDS)
        print(
            f"  docs: fetched={result['fetched']} skipped={result['skipped']} "
            f"failed={len(result['failed'])}"
        )


def drain_extraction_queue(session: Session) -> None:
    """Same extraction logic as app.scheduler._run_supply_links_refresh,
    but budget-free -- this is a one-time bootstrap over whatever backlog
    fetch_history() (or a prior partial run of this function) left on
    disk. loader.apply_extraction commits internally, so a crash partway
    through leaves every document processed so far correctly written and
    the interrupted document still pending (no .done marker) for the next
    run to pick back up.

    Each document's body runs inside its own try/except -- a poisoned
    document (e.g. the LLM naming the same counterparty twice, which
    pre-dates extract.py's gate() dedupe fix, hitting
    uq_supply_link_company_relation_counterparty on the loader's flush)
    must not crash the whole backlog drain. On any exception the session is
    rolled back, the doc is counted "errored" and printed, and the drain
    continues to the next document -- mark_extracted is deliberately NOT
    called on this path, so the doc is retried on the next run instead of
    being silently skipped forever or permanently re-poisoning the same
    glob position.

    A corrupt/unreadable meta sidecar, an unreadable .url sidecar, and a
    missing/unparsable news_date are ALSO left pending (counted "errored",
    no mark_extracted) rather than defaulted through -- see
    app.scheduler._run_supply_links_refresh's docstring for the reproduced
    damage each of those defaults did (I3/I7/M3, 2026-08-06 review). A
    readable meta whose scrip genuinely matches no company is a different,
    correct case: unmatched_scrip + mark_extracted, unchanged.

    Circuit breaker: same discipline as
    app.scheduler._run_supply_links_refresh -- SUPPLY_LLM_FAILURE_BREAKER
    CONSECUTIVE llm_failed docs stops the drain for this run (a
    rate-limited/quota-exhausted provider will not un-limit mid-run), reset
    by any successful extraction.
    """
    client = build_client(settings.groq_api_keys, settings.gemini_api_key or None)
    counts = {
        "extracted": 0, "unmatched_scrip": 0, "unextractable": 0,
        "llm_failed": 0, "errored": 0,
    }
    consecutive_llm_failures = 0

    docs = snapshot.pending_docs(snapshot.DEFAULT_ROOT)
    total = len(docs)
    print(f"draining {total} pending documents")

    for i, pdf_path in enumerate(docs, start=1):
        breaker_tripped = False
        try:
            try:
                meta = json.loads(
                    snapshot.meta_sidecar_path(pdf_path).read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                meta = None

            if meta is None:
                counts["errored"] += 1
                print(f"  [{i}/{total}] unreadable meta sidecar, left pending: {pdf_path}")
            else:
                try:
                    source_url = (
                        snapshot.url_sidecar_path(pdf_path).read_text(encoding="utf-8").strip()
                    )
                except OSError:
                    source_url = None

                if source_url is None:
                    counts["errored"] += 1
                    print(f"  [{i}/{total}] unreadable .url sidecar, left pending: {pdf_path}")
                else:
                    scrip_code = meta.get("scrip_code")
                    listing = (
                        session.query(Listing).filter(Listing.scrip_code == scrip_code).first()
                        if scrip_code else None
                    )
                    company = (
                        session.query(Company).filter(Company.id == listing.company_id).first()
                        if listing is not None else None
                    )

                    if company is None:
                        snapshot.mark_extracted(pdf_path)
                        counts["unmatched_scrip"] += 1
                    else:
                        text = extract.pdf_text(pdf_path)
                        if text is None:
                            snapshot.mark_extracted(pdf_path)
                            counts["unextractable"] += 1
                        else:
                            profile = extract.extract_profile(client, company.name, text)
                            if profile is None:
                                # Left pending -- retried the next time this drain runs.
                                counts["llm_failed"] += 1
                                consecutive_llm_failures += 1
                                if consecutive_llm_failures >= config.SUPPLY_LLM_FAILURE_BREAKER:
                                    breaker_tripped = True
                                    print(
                                        f"  [{i}/{total}] circuit breaker tripped after "
                                        f"{consecutive_llm_failures} consecutive llm_failed "
                                        "docs -- stopping drain, remaining docs stay pending."
                                    )
                            else:
                                as_of = snapshot.parse_news_date(meta.get("news_date"))
                                if as_of is None:
                                    # Never default to date.today() -- see the
                                    # docstring above (I3).
                                    counts["errored"] += 1
                                    print(
                                        f"  [{i}/{total}] unparsable/missing news_date, "
                                        f"left pending: {pdf_path}"
                                    )
                                else:
                                    loader.apply_extraction(
                                        session, company, profile,
                                        source_url=source_url,
                                        source_agency=meta.get("agency") or "",
                                        as_of=as_of,
                                    )
                                    snapshot.mark_extracted(pdf_path)
                                    counts["extracted"] += 1
                                    consecutive_llm_failures = 0
        except Exception as exc:
            session.rollback()
            counts["errored"] += 1
            print(f"  [{i}/{total}] ERROR on {pdf_path}: {exc}")

        if i % _PROGRESS_EVERY == 0 or i == total:
            print(
                f"  [{i}/{total}] extracted={counts['extracted']} "
                f"unmatched_scrip={counts['unmatched_scrip']} "
                f"unextractable={counts['unextractable']} llm_failed={counts['llm_failed']} "
                f"errored={counts['errored']}"
            )

        if breaker_tripped:
            break

    print(f"done: {counts}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--months", type=int, default=24,
        help="how many ~28-day windows back from today to fetch (default: 24)",
    )
    parser.add_argument(
        "--extract-only", action="store_true",
        help="skip fetching; just drain whatever is already pending on disk",
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        if not args.extract_only:
            fetch_history(session, args.months)
        drain_extraction_queue(session)
    finally:
        session.close()


if __name__ == "__main__":
    main()
