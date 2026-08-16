"""TASK 3.1 -- the closed exposure-tag vocabulary (spec §6.1).

This module loads `config/exposure_tags.yaml` and registers it into the
`valid_exposure_tag` table. The TABLE, not this module, is the enforcement:
migration 0013 installs triggers on `company_exposure` and `mechanism_edge`
that RAISE(ABORT) when a written tag is not in it. A validator in Python can
be routed around by anything holding a database handle -- an extractor, a
script, a future module written by someone who has not read this file. A
trigger cannot.

WHY `valid_exposure_tag` IS THE ONE PHASE 3 TABLE THAT SHIPS NON-EMPTY.
The fabrication guard forbids populating a table from the model's own
knowledge. A tag name is not knowledge about the world: it is a WORD this
system is permitted to use. `input:crude_derivative_rubber` asserts nothing
about any company, any coefficient or any filing -- it asserts that "tyres
buy synthetic rubber" is a concept the schema can express. The claim that a
specific company carries that exposure lives in `company_exposure`, which
ships empty and is filled only by a human approving a verbatim excerpt.
Recorded in DATA_GAPS §7 and asserted by
`tests/phase3/test_no_fixture_data_reaches_production.py`.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping

import yaml
from sqlalchemy import text

from app.ledger.vocabulary import check_exposure_tag

# backend/config/exposure_tags.yaml
EXPOSURE_TAGS_PATH = Path(__file__).resolve().parents[2] / "config" / "exposure_tags.yaml"

# The provenance string every row the vocabulary loader writes carries. A row
# with any other source came from somewhere else and a test says so.
VOCABULARY_SOURCE = "config/exposure_tags.yaml"


@dataclass(frozen=True)
class ExposureVocabulary:
    """The closed set, plus the hierarchy it was written in.

    `tags` is the wire form (`family:leaf`). `groups` keeps the intermediate
    organisational keys so a reader of the vocabulary can see WHY two leaves
    are siblings; nothing in the tag itself encodes them.
    """
    version: str
    tags: tuple[str, ...]
    families: tuple[str, ...]
    group_of: Mapping[str, str]

    def tags_in_family(self, family: str) -> tuple[str, ...]:
        prefix = f"{family}:"
        return tuple(tag for tag in self.tags if tag.startswith(prefix))

    def __contains__(self, tag: object) -> bool:
        return tag in self.tags


class ExposureVocabularyError(ValueError):
    """The vocabulary file is malformed."""


def _leaves(node, path: tuple[str, ...]) -> Iterable[tuple[tuple[str, ...], str]]:
    """Walk the YAML tree. A leaf is a key whose value is None (the YAML
    spelling `atf:` with nothing under it) -- which is exactly how §6.1
    writes it."""
    if node is None:
        return
    if not isinstance(node, dict):
        raise ExposureVocabularyError(
            f"exposure_tags.yaml: {'.'.join(path)} is {type(node).__name__}, "
            "not a mapping; the vocabulary is a tree of names")
    for key, value in node.items():
        if value is None:
            yield path, str(key)
        else:
            yield from _leaves(value, path + (str(key),))


@lru_cache(maxsize=4)
def load_vocabulary(path: Path | None = None) -> ExposureVocabulary:
    raw = yaml.safe_load((path or EXPOSURE_TAGS_PATH).read_text(encoding="utf-8"))
    version = raw.get("version")
    if not isinstance(version, str) or not version:
        raise ExposureVocabularyError("exposure_tags.yaml: no version")

    tags: list[str] = []
    families: list[str] = []
    group_of: dict[str, str] = {}
    for trail, leaf in _leaves(raw.get("families"), ()):
        if not trail:
            raise ExposureVocabularyError(
                f"exposure_tags.yaml: leaf {leaf!r} has no family")
        family = trail[0]
        tag = f"{family}:{leaf}"
        # Two families cannot own the same leaf spelling by accident.
        if tag in tags:
            raise ExposureVocabularyError(
                f"exposure_tags.yaml: duplicate tag {tag}")
        check_exposure_tag(tag)
        tags.append(tag)
        group_of[tag] = trail[-1]
        if family not in families:
            families.append(family)

    if not tags:
        raise ExposureVocabularyError("exposure_tags.yaml: empty vocabulary")
    return ExposureVocabulary(version=version, tags=tuple(tags),
                              families=tuple(families), group_of=group_of)


def register_tags(session_or_connection, tags: Iterable[str], *,
                  source: str = VOCABULARY_SOURCE) -> int:
    """Insert tags into `valid_exposure_tag`. Idempotent.

    This is the ONLY way the closed set widens. It is used by migration 0013,
    by `app/models.py`'s `after_create` hook (so a `create_all`-built database
    -- every test database and every fresh dev database -- rejects an unknown
    tag for the same reason a migrated one does), and by tests that need a tag
    naming something that does not exist. `source` records which of those it
    was, so "the deployed vocabulary" and "a tag a test invented" are
    distinguishable in the table itself.
    """
    written = 0
    for tag in tags:
        check_exposure_tag(tag)
        session_or_connection.execute(text(
            "INSERT OR IGNORE INTO valid_exposure_tag (exposure_tag, source) "
            "VALUES (:tag, :source)"), {"tag": tag, "source": source})
        written += 1
    return written


def register_vocabulary(session_or_connection, path: Path | None = None) -> int:
    """Register the deployed vocabulary file. What 0013 and `create_all` do."""
    return register_tags(session_or_connection, load_vocabulary(path).tags,
                         source=VOCABULARY_SOURCE)


def is_valid_tag(session, tag: str) -> bool:
    return bool(session.execute(text(
        "SELECT 1 FROM valid_exposure_tag WHERE exposure_tag = :tag"),
        {"tag": tag}).first())
