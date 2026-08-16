"""Ripple-family vocabulary: analyst wording -> taxonomy slugs.

A labeler writes "refiners"; ``companies.sub_sector`` says
``refining_marketing``. Measured against the live universe on 2026-08-17,
plain string comparison matched almost nothing, so ripple-family recall was
measuring our vocabulary rather than the engine. This module closes that
gap in the only honest way available: an explicit, reviewable term map
(``backend/config/eval_family_map.yaml``) plus the universe's own
vocabulary, with anything it cannot translate REPORTED rather than scored
as a miss.

Three outcomes for a family term, and the scorer treats each differently:

  ``mapped``   the term is in the map -> the mapped slugs are the targets
  ``direct``   the term matches a slug already in the universe's vocabulary
               (exact, or normalized substring either way) -> those slugs
  ``unknown``  neither -> MISMATCHED FAMILIES in BASELINE.md, and EXCLUDED
               from the recall denominator. Scoring it 0 would blame the
               engine for a word we simply cannot interpret.

The map file carries no data -- only "this is another name for that group".

PyYAML is used when importable, but is NOT declared in requirements.txt and
this session may not edit that file, so a strict fallback parser handles the
restricted format the map actually uses (``term: slug`` /
``term: [a, b]`` / comments). The fallback raises on any line it cannot
parse rather than skipping it -- a silently dropped mapping would show up
much later as an unexplained recall drop.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

FAMILY_MAP_PATH = Path(__file__).resolve().parents[2] / "config" / "eval_family_map.yaml"

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_family(value: str | None) -> str:
    """Lower-case, punctuation-to-space, collapsed. ``refining_marketing``
    and ``Refining Marketing`` normalize identically."""
    return " ".join(_NON_ALNUM_RE.sub(" ", (value or "").lower()).split())


def _yaml_module():
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    return yaml


def _parse_fallback(text: str, source: Path) -> dict[str, Any]:
    """Strict parser for the map's restricted subset of YAML."""
    out: dict[str, Any] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"{source}:{number}: expected 'term: value', got {raw!r}")
        term, _, value = line.partition(":")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        elif value:
            items = [value]
        else:
            raise ValueError(f"{source}:{number}: term {term.strip()!r} has no value")
        out[term.strip()] = items
    return out


def _validate(mapping: Any, source: Path) -> dict[str, list[str]]:
    if not isinstance(mapping, dict):
        raise ValueError(f"{source}: expected a mapping of term -> slug(s)")
    out: dict[str, list[str]] = {}
    for term, value in mapping.items():
        slugs = [value] if isinstance(value, str) else list(value or [])
        if not slugs or not all(isinstance(s, str) and s.strip() for s in slugs):
            raise ValueError(f"{source}: term {term!r} must map to one or more slugs")
        out[normalize_family(term)] = [s.strip() for s in slugs]
    return out


@lru_cache(maxsize=4)
def load_family_map(path: str | None = None) -> dict[str, list[str]]:
    """Load and validate the term map. Cached -- the file is read once per
    process, and the scorer touches it for every family of every event."""
    source = Path(path) if path else FAMILY_MAP_PATH
    text = source.read_text(encoding="utf-8")
    yaml = _yaml_module()
    raw = yaml.safe_load(text) if yaml is not None else _parse_fallback(text, source)
    return _validate(raw, source)


def resolve_family(term: str, vocabulary: dict[str, list[str]],
                   family_map: dict[str, list[str]] | None = None
                   ) -> tuple[list[str], str]:
    """-> (target slugs normalized, one of mapped/direct/unknown).

    ``vocabulary`` is :func:`app.eval.store.load_family_vocabulary`'s output
    -- the slugs the universe actually holds. A mapped term whose slugs are
    all absent from the universe is reported as ``unknown`` too: pretending
    to look for a group nobody is classified into would score a guaranteed
    miss against the engine.
    """
    family_map = load_family_map() if family_map is None else family_map
    known = {normalize_family(v) for v in
             list(vocabulary.get("sub_sectors", [])) + list(vocabulary.get("sectors", []))}
    normalized = normalize_family(term)
    if not normalized:
        return [], "unknown"

    mapped = family_map.get(normalized)
    if mapped:
        targets = [normalize_family(s) for s in mapped if normalize_family(s) in known]
        if targets:
            return targets, "mapped"

    direct = [candidate for candidate in known
              if candidate == normalized
              or normalized in candidate or candidate in normalized]
    if direct:
        return sorted(direct), "direct"
    return [], "unknown"
