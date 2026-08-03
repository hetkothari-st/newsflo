"""Snapshot layout for the universe ingest (spec §4). Stage 1 (fetchers)
writes raw source responses here verbatim; stage 2 (normalize + loader)
reads only from here. That split is what makes the loader testable with no
network and replayable against any past day.

Pure path/filesystem logic -- no network, no DB, no app.models import.
"""
from datetime import date
from pathlib import Path

DEFAULT_ROOT = "data/universe"
DETAIL_DIRNAME = "bse_detail"


def snapshot_dir(root: str, day: date) -> Path:
    return Path(root) / day.isoformat()


def master_path(root: str, day: date, name: str) -> Path:
    return snapshot_dir(root, day) / name


def detail_path(root: str, day: date, scrip_code: str) -> Path:
    return snapshot_dir(root, day) / DETAIL_DIRNAME / f"{scrip_code}.json"


def fetched_scrip_codes(root: str, day: date) -> set[str]:
    """Scrip codes already on disk for ``day``. The resume set: a rerun
    skips these, so a rate-limit at scrip 3,000 costs the remaining 2,000
    rather than the whole run."""
    directory = snapshot_dir(root, day) / DETAIL_DIRNAME
    if not directory.is_dir():
        return set()
    return {p.stem for p in directory.glob("*.json")}


def latest_snapshot_day(root: str) -> date | None:
    """Newest snapshot day present, or None. Directories whose names aren't
    ISO dates are ignored rather than raising -- the root may hold scratch
    dirs."""
    base = Path(root)
    if not base.is_dir():
        return None
    days = []
    for child in base.iterdir():
        if not child.is_dir():
            continue
        try:
            days.append(date.fromisoformat(child.name))
        except ValueError:
            continue
    return max(days) if days else None


def latest_detail_day(root: str) -> date | None:
    """Newest snapshot day whose bse_detail/ directory exists AND is
    non-empty, or None.

    Distinct from latest_snapshot_day on purpose: the daily master refresh
    (_run_universe_master_refresh) creates a fresh dated directory every day
    with an empty bse_detail/ (the ~5,000-request official-classification
    pass is a separate monthly job, _run_universe_detail_refresh, that
    writes into whatever day was latest AT THE TIME IT RAN). Without this
    function, an ingest that always reads details from latest_snapshot_day
    would find an empty bse_detail/ every single day after the first, and
    the monthly detail pass's output would never be consumed by any ingest.
    ingest_universe.run_ingest calls this (falling back to its own ``day``
    when it returns None) instead of assuming the detail pass landed in
    today's directory.
    """
    base = Path(root)
    if not base.is_dir():
        return None
    days = []
    for child in base.iterdir():
        if not child.is_dir():
            continue
        try:
            day = date.fromisoformat(child.name)
        except ValueError:
            continue
        detail_dir = child / DETAIL_DIRNAME
        if detail_dir.is_dir() and any(detail_dir.glob("*.json")):
            days.append(day)
    return max(days) if days else None
