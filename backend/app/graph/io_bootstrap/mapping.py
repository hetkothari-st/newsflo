"""IOTT/NIC industry code -> internal sector_id -> exposure_tag.

The mapping is HAND-AUTHORED (phase file, Task 3.4 step 4) and this module
loads it. It refuses three things, each for a reason worth stating:

  * a row marked `_example: true` -- `config/industry_mapping.yaml` ships as
    documentation of the shape, with no usable content, because deciding
    which listed industry an IOTT code refers to is domain judgement and not
    something an implementer may invent (DATA_GAPS §7);
  * a row with no `reviewed_by` -- the mapping is where arithmetic turns
    into a claim, so it carries a name;
  * a row whose `exposure_tag` is outside `config/exposure_tags.yaml` -- the
    vocabulary is closed, and a mapping is not a way around it.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from app.ledger.exposure_tags import load_vocabulary


class IndustryMappingError(ValueError):
    """The industry mapping is unusable, and says so rather than degrading."""


@dataclass(frozen=True)
class IndustryMapping:
    industry_code: str
    sector_id: str
    exposure_tag: str
    reviewed_by: str
    source_url: str


def load_mapping(path: Path | str) -> Mapping[str, IndustryMapping]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    rows = raw.get("mappings") or []
    if not rows:
        raise IndustryMappingError(f"{path}: no mappings")

    vocabulary = load_vocabulary().tags
    out: dict[str, IndustryMapping] = {}
    for row in rows:
        code = str(row.get("industry_code") or "")
        if row.get("_example"):
            raise IndustryMappingError(
                f"{path}: row {code!r} is an EXAMPLE. This file ships as "
                "structure only; the real IOTT-code-to-industry mapping is "
                "hand-authored by the owner (DATA_GAPS §7). Nothing is "
                "loaded until it is.")
        if not code:
            raise IndustryMappingError(f"{path}: a row has no industry_code")
        if not row.get("reviewed_by"):
            raise IndustryMappingError(
                f"{path}: {code} has no reviewed_by. Mapping an industry code "
                "to an exposure tag is a judgement, and a judgement carries a "
                "name.")
        tag = str(row.get("exposure_tag") or "")
        if tag not in vocabulary:
            raise IndustryMappingError(
                f"{path}: {code} maps to {tag!r}, which is not in the closed "
                "vocabulary (config/exposure_tags.yaml)")
        if not row.get("source_url"):
            raise IndustryMappingError(f"{path}: {code} has no source_url")
        if code in out:
            raise IndustryMappingError(f"{path}: duplicate industry_code {code}")
        out[code] = IndustryMapping(
            industry_code=code, sector_id=str(row["sector_id"]),
            exposure_tag=tag, reviewed_by=str(row["reviewed_by"]),
            source_url=str(row["source_url"]))
    return out
