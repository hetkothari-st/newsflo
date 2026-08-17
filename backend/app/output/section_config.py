"""Deliberately IMPURE sibling of `sections.py`: reads
`config/section_taxonomy.yaml` off disk and freezes it into the taxonomy the
section engine renders with.

`sections.py` must import nothing that touches a disk -- it is a pure
function of (records, taxonomy) and
`tests/phase6/test_sections.py::test_the_section_engine_calls_no_llm_and_
reads_no_disk` enforces that. Same split as `gates.py`/`config_loader.py`.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import yaml

SECTION_TAXONOMY_PATH = (Path(__file__).resolve().parents[2] / "config"
                         / "section_taxonomy.yaml")


class SectionTaxonomyError(ValueError):
    """A taxonomy that cannot render a label."""


@dataclass(frozen=True)
class SectionTaxonomy:
    version: str
    separator: str
    labels: Mapping[str, str]
    no_mechanism_label: str
    unknown_label: str
    unknown_label_word: str
    zero_primary: Mapping[str, str]
    plurals: Mapping[str, tuple[str, str]]

    def mechanism_label(self, mechanism_id: str | None) -> str:
        """The rendered label for one mechanism.

        Three cases, all keyed and none of them prose anybody wrote about a
        mechanism they had not described:

          * a named mechanism -> its label;
          * no mechanism at all (a company the event names directly) ->
            `no_mechanism_label`;
          * a mechanism this file does not name -> `unknown_label` with the
            ID substituted verbatim, so two unknown mechanisms stay two
            sections rather than collapsing into one.
        """
        if mechanism_id is None:
            return self.no_mechanism_label
        known = self.labels.get(str(mechanism_id))
        if known:
            return known
        return self.unknown_label.format(mechanism_id=str(mechanism_id))

    def label_for(self, economic_effect: str, mechanism_id: str | None) -> str:
        return (f"{economic_effect}{self.separator}"
                f"{self.mechanism_label(mechanism_id)}")

    def plural(self, name: str, count: int) -> str:
        try:
            singular, plural = self.plurals[name]
        except KeyError as exc:                          # pragma: no cover
            raise SectionTaxonomyError(
                f"no singular/plural pair is configured for {name!r}") from exc
        return singular if count == 1 else plural


@lru_cache(maxsize=4)
def load_section_taxonomy(path: Path | None = None) -> SectionTaxonomy:
    raw = yaml.safe_load((path or SECTION_TAXONOMY_PATH).read_text(encoding="utf-8"))
    zero = raw.get("zero_primary") or {}
    taxonomy = SectionTaxonomy(
        version=str(raw["version"]),
        separator=str(raw["separator"]),
        labels=MappingProxyType(
            {str(k): str(v) for k, v in (raw.get("labels") or {}).items()}),
        no_mechanism_label=str(raw["no_mechanism_label"]),
        unknown_label=str(raw["unknown_label"]),
        unknown_label_word=str(raw["unknown_label_word"]),
        zero_primary=MappingProxyType({
            "headline": " ".join(str(zero["headline"]).split()),
            "body": " ".join(str(zero["body"]).split()),
            "bullets": str(zero["bullets"]),
        }),
        plurals=MappingProxyType({
            str(name): (str(pair[0]), str(pair[1]))
            for name, pair in (zero.get("plurals") or {}).items()}))

    if "{mechanism_id}" not in taxonomy.unknown_label:
        raise SectionTaxonomyError(
            "section_taxonomy.yaml: unknown_label must substitute "
            "{mechanism_id} -- a label that drops the id would fold every "
            "unnamed mechanism into one section and misplace its companies")
    if taxonomy.unknown_label_word not in taxonomy.unknown_label:
        raise SectionTaxonomyError(
            "section_taxonomy.yaml: unknown_label_word must appear in "
            "unknown_label")
    return taxonomy
