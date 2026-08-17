"""Deliberately IMPURE sibling of the engine: reads `config/falsifier.yaml`
off disk and freezes it into the policy `engine.py` evaluates.

`engine.py` holds NO severity, NO question and NO model name of its own, so
policy cannot drift between the file and the code -- the same split as
`gates.py`/`config_loader.py` and `event_study.py`/`empirical/config.py`.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import yaml

FALSIFIER_CONFIG_PATH = (Path(__file__).resolve().parents[3] / "config"
                         / "falsifier.yaml")


class FalsifierConfigError(ValueError):
    """A falsifier policy that is not usable as written."""


@dataclass(frozen=True)
class ChecklistQuestion:
    """One of §12.2's ten, and the objection that stands when nobody can
    answer it."""
    question: int
    text: str
    objection_type: str


@dataclass(frozen=True)
class FalsifierPolicy:
    version: str
    severities: Mapping[str, str]
    checklist: tuple[ChecklistQuestion, ...]
    prompt_lineage: str
    # NULL in the deployed file: nobody has signed off a second provider.
    # None here means "run on the generator's model and RECORD that", never
    # a silently substituted default.
    provider: str | None
    model_id: str | None

    def severity_for(self, objection_type: str) -> str:
        try:
            return self.severities[objection_type]
        except KeyError as exc:
            raise FalsifierConfigError(
                f"no severity is configured for objection type "
                f"{objection_type!r}; the taxonomy is closed and this file is "
                f"where it is graded") from exc

    def question(self, number: int) -> ChecklistQuestion:
        for entry in self.checklist:
            if entry.question == number:
                return entry
        raise FalsifierConfigError(f"question {number} is not in the checklist")

    def checklist_objection_type(self, number: int) -> str:
        return self.question(number).objection_type


def validate_policy(policy: FalsifierPolicy) -> FalsifierPolicy:
    """Refuse a policy that is half-configured rather than half-honouring it.

    A `model_id` with no `provider` is not a cross-model run; it is a
    configuration somebody started and did not finish, and running it would
    record a cross-model limitation that is not true.
    """
    if policy.model_id is not None and not policy.provider:
        raise FalsifierConfigError(
            "falsifier.yaml: model_discipline.model_id is set but provider is "
            "not. A model with no provider cannot be dispatched, and recording "
            "the run as cross-model would be a claim nobody can check.")
    if policy.provider is not None and not policy.model_id:
        raise FalsifierConfigError(
            "falsifier.yaml: model_discipline.provider is set but model_id is "
            "not. Half a routing decision is not a routing decision.")
    if not policy.prompt_lineage:
        raise FalsifierConfigError(
            "falsifier.yaml: model_discipline.prompt_lineage is required -- "
            "§12.4's whole point is that the two lineages are COMPARABLE, and "
            "an unnamed one cannot differ from anything.")
    if not policy.checklist:
        raise FalsifierConfigError("falsifier.yaml: the checklist is empty")
    return policy


@lru_cache(maxsize=4)
def load_falsifier_config(path: Path | None = None) -> FalsifierPolicy:
    raw = yaml.safe_load((path or FALSIFIER_CONFIG_PATH).read_text(encoding="utf-8"))
    discipline = raw.get("model_discipline") or {}
    policy = FalsifierPolicy(
        version=str(raw["version"]),
        severities=MappingProxyType(
            {str(k): str(v) for k, v in (raw["severities"] or {}).items()}),
        checklist=tuple(
            ChecklistQuestion(question=int(entry["question"]),
                              text=" ".join(str(entry["text"]).split()),
                              objection_type=str(entry["objection_type"]))
            for entry in sorted(raw["checklist"] or (),
                                key=lambda e: int(e["question"]))),
        prompt_lineage=str(discipline.get("prompt_lineage") or ""),
        provider=(str(discipline["provider"])
                  if discipline.get("provider") else None),
        model_id=(str(discipline["model_id"])
                  if discipline.get("model_id") else None))
    return validate_policy(policy)
