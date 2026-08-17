"""The adversary's prompt, and nothing else.

ITS OWN LINEAGE. `prompt_lineage` lives in `config/falsifier.yaml` and is
deliberately unlike any generator lineage: the failure mode §12.4 names is a
checker that agrees with the generator because it was told the same story in
the same words. The template below therefore shares no wording, no persona
and no ordering with the candidate-generation prompts in
`app/analysis/impact_graph/prompts.py`.

WHAT THE PROMPT MAY NOT DO, and does not: it never asks for a severity (ours,
from config), never asks for a number, and never asks for an argument. It
asks for ten structured answers, each with a citation into the record set it
was handed, plus typed objections drawn from a closed list. Everything it
returns that is not one of those is discarded by `engine.py`.

STATIC PREFIX THEN DYNAMIC SUFFIX (V5 Phase 7, spec section 18). The template
below is split in two so the property can be CHECKED rather than promised:
`_STATIC` holds the persona, the rules, the questions, the closed objection
taxonomy and the response schema -- all of which come from
`config/falsifier.yaml` and are identical for every candidate -- and
`_DYNAMIC` holds the record set, which is different every time. Placing the
record set first would destroy the provider's prefix cache and nothing would
fail; `eval/prompt_audit.py` is what makes that visible.

The split is a REFACTOR, not a prompt change: `_STATIC + _DYNAMIC` is
byte-identical to the template that shipped in Phase 6, and a test pins that.
"""

_STATIC = """You are the ADVERSARY on a research desk.

A colleague has produced the record below, claiming that one listed company
is materially affected by one event. Your job is NOT to agree with it. Your
job is to try to DESTROY it, and to be honest about the parts you cannot
destroy.

You may use ONLY the record set below. Anything you believe about this
company from elsewhere is inadmissible here.

PART 1 -- answer all {question_count} questions. For each one:
  * `answerable`: true only if the RECORD SET answers it. If you have to
    reason from outside the record, the answer is false.
  * `answer`: one short sentence. No numerals -- cite the field instead.
  * `cites`: one or more field paths or evidence ids FROM THE RECORD SET
    below. An answer with no citation will be read as unanswered.

{questions}

PART 2 -- raise every objection that stands. Use ONLY these type names:

{objection_types}

Do not grade them; severity is not yours to set. If a question in Part 1 is
what prompted an objection, put its number in `question`.

Return JSON and nothing else:

{{"checklist": [{{"question": 1, "answerable": true, "answer": "...",
                 "cites": ["..."]}}],
  "objections": [{{"type": "...", "question": 1}}]}}

RECORD SET
"""

_DYNAMIC = """{record_set}
"""

#: The whole prompt, kept as one name for anything that reads the template.
CHECKLIST_PROMPT = _STATIC + _DYNAMIC


def build_prompt_parts(record_set_json: str, questions,
                       objection_types) -> tuple[str, str]:
    """(cacheable static prefix, dynamic suffix). Concatenating them in this
    order is the prompt; concatenating them in the other order is a bill."""
    numbered = "\n".join(f"{q.question}. {q.text}" for q in questions)
    types = "\n".join(f"  {name}" for name in objection_types)
    static = _STATIC.format(question_count=len(questions), questions=numbered,
                            objection_types=types)
    return static, _DYNAMIC.format(record_set=record_set_json)


def build_prompt(record_set_json: str, questions, objection_types) -> str:
    static, dynamic = build_prompt_parts(record_set_json, questions,
                                         objection_types)
    return static + dynamic
