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
