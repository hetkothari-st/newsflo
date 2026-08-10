"""Snapshot layout for the description backfill. Pure path logic -- no
network, no DB.

One file per Wikipedia article, named by a filesystem-safe encoding of the
title. Article titles contain ``/``, ``:``, ``?`` and other characters that
are illegal or meaningful in paths on at least one of the platforms this
runs on (Windows dev, Linux prod), so the name is quoted rather than used
raw.
"""
import urllib.parse
from datetime import date
from pathlib import Path

DEFAULT_ROOT = "data/descriptions"
PAGES_DIRNAME = "pages"
SEARCH_DIRNAME = "search"


def snapshot_dir(root: str, day: date) -> Path:
    return Path(root) / day.isoformat()


def pages_dir(root: str, day: date) -> Path:
    return snapshot_dir(root, day) / PAGES_DIRNAME


def title_to_filename(title: str) -> str:
    """Reversible, filesystem-safe. ``quote`` with an empty safe set escapes
    ``/`` and ``:``; the ``%`` escapes it produces are themselves legal in a
    filename on both platforms."""
    return urllib.parse.quote(title, safe="") + ".json"


def filename_to_title(filename: str) -> str:
    return urllib.parse.unquote(filename[:-len(".json")] if filename.endswith(".json") else filename)


def page_path(root: str, day: date, title: str) -> Path:
    return pages_dir(root, day) / title_to_filename(title)


def fetched_titles(root: str, day: date) -> set[str]:
    """Titles already on disk for ``day`` -- the resume set. A run
    interrupted at article 600 of 900 costs the remaining 300."""
    directory = pages_dir(root, day)
    if not directory.is_dir():
        return set()
    return {filename_to_title(p.name) for p in directory.glob("*.json")}


FULL_DIRNAME = "full"


def full_dir(root: str, day: date) -> Path:
    return snapshot_dir(root, day) / FULL_DIRNAME


def full_path(root: str, day: date, title: str) -> Path:
    return full_dir(root, day) / title_to_filename(title)


def fetched_full_titles(root: str, day: date) -> set[str]:
    """Titles whose FULL extract (Stage B) is already on disk for ``day``."""
    directory = full_dir(root, day)
    if not directory.is_dir():
        return set()
    return {filename_to_title(p.name) for p in directory.glob("*.json")}


def search_dir(root: str, day: date) -> Path:
    return snapshot_dir(root, day) / SEARCH_DIRNAME


def search_path(root: str, day: date, ticker: str) -> Path:
    """One file per company searched. Its presence -- even holding an empty
    result list -- means "already searched", so the expensive pass resumes
    without re-asking about companies Wikipedia has never heard of."""
    return search_dir(root, day) / (urllib.parse.quote(ticker, safe="") + ".json")


def searched_tickers(root: str, day: date) -> set[str]:
    directory = search_dir(root, day)
    if not directory.is_dir():
        return set()
    return {urllib.parse.unquote(p.stem) for p in directory.glob("*.json")}


def latest_snapshot_day(root: str) -> date | None:
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
