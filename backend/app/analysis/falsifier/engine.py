"""The falsification stage itself (spec §12).

    Falsifier(client=..., policy=...).run(record_set) -> FalsifierResult

The engine holds no severity, no question and no model name: all three come
from `config/falsifier.yaml`. What it holds is the DISCIPLINE:

  * an objection defaults to SUSTAINED. §12.3 puts the burden of proof on
    publication, so nothing here ever emits `sustained: False`. Only a
    rebuttal from another stage, folded by the reducer, can unsustain one;
  * SEVERITY IS OURS. Whatever the response claims is ignored; the severity
    comes from the taxonomy table;
  * THE TAXONOMY IS CLOSED. An objection type outside it is discarded and
    the discard is recorded -- not coerced into a neighbouring type, which
    would be inventing a criticism, and not passed through, which the signal
    bus would refuse anyway;
  * PROVIDER AND MODEL ARE RECORDED ON EVERY OBJECTION (§12.4). Without
    them the eval harness cannot separate cross-model precision from
    same-model precision, and correlated generator/checker error becomes
    invisible.

NO CLOCK. `created_at` is supplied by the caller, so a replay of the same
analysis emits the same content-addressed signal ids.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence

import json
import logging

from app.analysis.falsifier.checklist import ChecklistAnswer, parse_response
from app.analysis.falsifier.config import FalsifierPolicy, validate_policy
from app.analysis.falsifier.prompts import build_prompt

logger = logging.getLogger(__name__)

STAGE = "FALSIFICATION"

# The limitation names §12.4 requires on the record. Both are facts about the
# RUN, not judgements about the result.
SAME_MODEL = "SAME_MODEL_AS_GENERATOR"
SAME_PROMPT_LINEAGE = "SAME_PROMPT_LINEAGE_AS_GENERATOR"


class JSONClient(Protocol):
    """The one method this package is allowed to call."""

    def generate(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class ModelDiscipline:
    """Who generated the candidate, who attacked it, and how correlated the
    two are. Recorded whether or not the answer is flattering."""
    generator_provider: str | None
    generator_model_id: str | None
    generator_prompt_lineage: str | None
    falsifier_provider: str | None
    falsifier_model_id: str | None
    falsifier_prompt_lineage: str

    @property
    def cross_model(self) -> bool:
        return bool(self.falsifier_model_id
                    and self.falsifier_model_id != self.generator_model_id)

    @property
    def limitations(self) -> tuple[str, ...]:
        out = []
        if not self.cross_model:
            out.append(SAME_MODEL)
        if (self.generator_prompt_lineage
                and self.generator_prompt_lineage == self.falsifier_prompt_lineage):
            out.append(SAME_PROMPT_LINEAGE)
        return tuple(out)


@dataclass(frozen=True)
class Objection:
    """One typed criticism. There is no free-text field: an objection is a
    record before it is a sentence, exactly as a claim is (§11.1)."""
    objection_id: str
    type: str
    severity: str
    sustained: bool
    raised_by: str
    provider: str | None
    model_id: str | None
    prompt_lineage: str
    checklist_question: int | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "objection_id": self.objection_id, "type": self.type,
            "severity": self.severity, "sustained": self.sustained,
            "raised_by": self.raised_by, "provider": self.provider,
            "model_id": self.model_id, "prompt_lineage": self.prompt_lineage,
            "checklist_question": self.checklist_question,
        }


@dataclass(frozen=True)
class FalsifierResult:
    objections: tuple[Objection, ...]
    checklist: tuple[ChecklistAnswer, ...]
    discipline: ModelDiscipline
    response_malformed: bool
    discarded: tuple[str, ...]


class Falsifier:
    def __init__(self, *, client: JSONClient, policy: FalsifierPolicy,
                 generator_provider: str | None = None,
                 generator_model_id: str | None = None,
                 generator_prompt_lineage: str | None = None):
        self.client = client
        self.policy = validate_policy(policy)
        self.generator_provider = generator_provider
        self.generator_model_id = generator_model_id
        self.generator_prompt_lineage = generator_prompt_lineage

    # -- identity ---------------------------------------------------------
    @property
    def discipline(self) -> ModelDiscipline:
        """§12.4. With no cross-model provider configured the falsifier runs
        on the GENERATOR's model -- and says so. Falling back silently is the
        one thing that would make the eval split meaningless."""
        return ModelDiscipline(
            generator_provider=self.generator_provider,
            generator_model_id=self.generator_model_id,
            generator_prompt_lineage=self.generator_prompt_lineage,
            falsifier_provider=self.policy.provider or self.generator_provider,
            falsifier_model_id=self.policy.model_id or self.generator_model_id,
            falsifier_prompt_lineage=self.policy.prompt_lineage)

    @property
    def created_by(self) -> str:
        discipline = self.discipline
        return (f"llm:{discipline.falsifier_provider or 'unnamed-provider'}:"
                f"{discipline.falsifier_model_id or 'unnamed-model'}:"
                f"{discipline.falsifier_prompt_lineage}")

    # -- the run ----------------------------------------------------------
    def run(self, record_set: Mapping[str, Any]) -> FalsifierResult:
        prompt = build_prompt(
            json.dumps(record_set, sort_keys=True, indent=2, default=str),
            self.policy.checklist, tuple(self.policy.severities))
        parsed = parse_response(self.client.generate(prompt), self.policy.checklist)

        discipline = self.discipline
        discarded = list(parsed.discarded)
        objections: dict[str, Objection] = {}

        def add(objection_type: str, question: int | None) -> None:
            if objection_type not in self.policy.severities:
                discarded.append(
                    f"objection type {objection_type!r} is outside the closed "
                    f"taxonomy and was discarded")
                return
            objection_id = (f"falsifier:q{question}:{objection_type}"
                            if question is not None
                            else f"falsifier:{objection_type}")
            objections.setdefault(objection_id, Objection(
                objection_id=objection_id, type=objection_type,
                # SEVERITY IS OURS, not the response's.
                severity=self.policy.severity_for(objection_type),
                # DEFAULT IS THAT THE OBJECTION STANDS (§12.3).
                sustained=True, raised_by="falsifier",
                provider=discipline.falsifier_provider,
                model_id=discipline.falsifier_model_id,
                prompt_lineage=discipline.falsifier_prompt_lineage,
                checklist_question=question))

        # §12.2: "Unanswerable => objection", every time, with the type this
        # question governs.
        for answer in parsed.answers:
            if not answer.answerable:
                add(self.policy.checklist_objection_type(answer.question),
                    answer.question)

        for entry in parsed.raw_objections:
            add(str(entry["type"]), entry.get("question"))

        if parsed.malformed:
            logger.warning(
                "[falsifier] unreadable response; all %s checklist questions "
                "counted unanswered (fail-closed)", len(parsed.answers))

        return FalsifierResult(
            objections=tuple(objections[key] for key in sorted(objections)),
            checklist=parsed.answers, discipline=discipline,
            response_malformed=parsed.malformed, discarded=tuple(discarded))

    # -- signals ----------------------------------------------------------
    def signals(self, result: FalsifierResult, *, event_id: str,
                company_id: int | None, analysis_version: str,
                created_at: datetime) -> tuple:
        """The OBJECTION signals, and nothing else.

        NO REBUTTAL IS EMITTED HERE, ever (the phase file's first DO NOT).
        The falsifier may not answer itself, so the answering signal comes
        from the stage that holds the cited datum -- `app.analysis.rebuttal`.
        """
        from app.core.signals import make_signal

        return tuple(
            make_signal(event_id=event_id, company_id=company_id, stage=STAGE,
                        kind="OBJECTION", payload=objection.payload(),
                        created_by=self.created_by,
                        analysis_version=analysis_version,
                        created_at=created_at)
            for objection in result.objections)


def unanswered_questions(result: FalsifierResult) -> Sequence[ChecklistAnswer]:
    return tuple(answer for answer in result.checklist if not answer.answerable)
