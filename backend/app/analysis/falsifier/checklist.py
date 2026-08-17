"""§12.2's ten questions, as a schema over the adversary's response.

THE ONE RULE OF THIS MODULE: it FAILS CLOSED. Every path that cannot read an
answer produces `answerable = False`, which raises the objection that
question governs. There is no branch anywhere below in which a malformed,
missing or uncited answer is treated as an answer, because the direction of
the error matters: a checker that reads its own confusion as agreement is
worse than no checker.

What counts as unanswered:

  * the response is not JSON, or not an object;                (all ten)
  * `checklist` is missing or not a list;                      (all ten)
  * a question has no entry;                                   (that one)
  * an entry is not an object, or its `question` is not one of
    the ten, or `answerable` is not a boolean;                 (that one)
  * `answerable` is true but `answer` is blank;                (that one)
  * `answerable` is true but `cites` is empty or not a list of
    non-blank strings.                                         (that one)

The last is the same discipline §12.3 imposes on rebuttals, applied to the
questions that produce the objections. An assertion nobody can trace to a
record field is exactly what this phase exists to stop treating as knowledge.
"""
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import json


@dataclass(frozen=True)
class ChecklistAnswer:
    question: int
    answerable: bool
    answer: str = ""
    cites: tuple[str, ...] = ()
    # Why it was read as unanswered. None when it was answered.
    unanswered_reason: str | None = None


@dataclass(frozen=True)
class ParsedResponse:
    answers: tuple[ChecklistAnswer, ...]
    # `{"type": ..., "question": int | None}`, already filtered to the closed
    # vocabulary by the caller.
    raw_objections: tuple[Mapping[str, Any], ...]
    malformed: bool
    discarded: tuple[str, ...]


def _blank(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def _citations(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value
                 if isinstance(item, str) and item.strip())


def _unanswered(question: int, reason: str) -> ChecklistAnswer:
    return ChecklistAnswer(question=question, answerable=False,
                           unanswered_reason=reason)


def parse_response(response: str, questions: Sequence[Any]) -> ParsedResponse:
    """The adversary's raw string -> a typed, fail-closed record."""
    numbers = [q.question for q in questions]
    discarded: list[str] = []

    try:
        document = json.loads(response)
    except (TypeError, ValueError) as error:
        return ParsedResponse(
            answers=tuple(_unanswered(n, f"response is not JSON: {error}")
                          for n in numbers),
            raw_objections=(), malformed=True,
            discarded=(f"response is not JSON: {error}",))

    if not isinstance(document, Mapping):
        return ParsedResponse(
            answers=tuple(_unanswered(n, "response is not an object")
                          for n in numbers),
            raw_objections=(), malformed=True,
            discarded=("response is not an object",))

    entries = document.get("checklist")
    if not isinstance(entries, (list, tuple)):
        return ParsedResponse(
            answers=tuple(_unanswered(n, "response carries no checklist")
                          for n in numbers),
            raw_objections=_objection_entries(document, discarded),
            malformed=True,
            discarded=(*discarded, "response carries no checklist"))

    by_question: dict[int, Any] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            discarded.append("a checklist entry is not an object")
            continue
        try:
            number = int(entry["question"])
        except (KeyError, TypeError, ValueError):
            discarded.append("a checklist entry names no question")
            continue
        if number not in numbers:
            discarded.append(f"checklist entry for unknown question {number}")
            continue
        if number in by_question:
            discarded.append(f"question {number} answered twice; the first "
                             f"answer stands")
            continue
        by_question[number] = entry

    answers = []
    for number in numbers:
        entry = by_question.get(number)
        if entry is None:
            answers.append(_unanswered(number, "no answer in the response"))
            continue
        answerable = entry.get("answerable")
        if not isinstance(answerable, bool):
            answers.append(_unanswered(number, "answerable is not a boolean"))
            continue
        if not answerable:
            answers.append(_unanswered(number, "the adversary could not answer it"))
            continue
        if _blank(entry.get("answer")):
            answers.append(_unanswered(number, "answerable with a blank answer"))
            continue
        cites = _citations(entry.get("cites"))
        if not cites:
            answers.append(_unanswered(
                number, "answered without citing a record field or evidence id"))
            continue
        answers.append(ChecklistAnswer(
            question=number, answerable=True,
            answer=str(entry["answer"]).strip(), cites=cites))

    return ParsedResponse(
        answers=tuple(answers),
        raw_objections=_objection_entries(document, discarded),
        malformed=False, discarded=tuple(discarded))


def _objection_entries(document: Mapping[str, Any],
                       discarded: list[str]) -> tuple[Mapping[str, Any], ...]:
    """The response's own objections, structurally validated only. The TYPE
    is checked against the closed vocabulary by the engine, which is where
    the vocabulary lives."""
    raw = document.get("objections")
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        discarded.append("objections is not a list")
        return ()
    out = []
    for entry in raw:
        if not isinstance(entry, Mapping) or _blank(entry.get("type")):
            discarded.append("an objection entry names no type")
            continue
        question = entry.get("question")
        out.append({"type": str(entry["type"]).strip(),
                    "question": int(question) if isinstance(question, int) else None})
    return tuple(out)
