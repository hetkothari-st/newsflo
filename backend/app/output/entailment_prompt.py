"""The STAGE-2 entailment judge's prompt (spec section 11.3), and nothing else.

Phase 0 built the firewall with an INJECTED judge -- an object exposing
`entails(sentence, record_set) -> bool` -- and deliberately built no prompt,
because nothing in this repo constructs a client. That left the section 18
prompt-order rule unenforceable for half of V5's model surface: an adapter
author would write the prompt themselves, in their own order, and the prefix
cache would be lost silently.

So the prompt lives here, split into a cacheable STATIC prefix and a DYNAMIC
suffix, and `eval/prompt_audit.py` checks the order. An adapter that uses
`build_judge_prompt` inherits a checked prompt; one that writes its own does
not, and that is a choice somebody made rather than a default.

THIS MODULE CONSTRUCTS NO CLIENT AND MAKES NO CALL. It builds a string.

WHAT THE PROMPT ASKS FOR, and what it refuses to ask for:

  * a BINARY verdict, entailed or not. Not a score, not a confidence, not a
    rewrite -- the firewall DELETES a failing sentence and never repairs it,
    so a judge that suggested a fix would be offering a second chance to
    fabricate;
  * no numeral in the response. The judge's answer never reaches a user, but
    a judge asked for numbers is a judge invited to compute;
  * a DIFFERENT prompt lineage from the fluency rewriter (section 11.3's
    requirement), which is why this file shares no wording with
    `app/output/compiler.py`.
"""

PROMPT_LINEAGE = "firewall-entailment-judge-v1"

_STATIC = """You are an ENTAILMENT JUDGE.

You will be shown one SENTENCE and the RECORD SET it is supposed to come
from. Answer one question: is every claim in the sentence entailed by the
record set?

Rules:
  * the record set is the ONLY admissible source. Anything you know about
    these companies from elsewhere is inadmissible here.
  * a sentence that is TRUE in the world but not supported by the record set
    is NOT entailed. That is the whole point of the question.
  * a sentence that hedges a claim the record set does not contain is not
    entailed either. Hedging is not sourcing.
  * do not rewrite the sentence, do not suggest a correction, and do not
    explain how it could be made acceptable. A failing sentence is deleted.
  * do not emit any numeral.

Return JSON and nothing else:

{"entailed": true}

"""

_DYNAMIC = """SENTENCE
{sentence}

RECORD SET
{record_set}
"""


def _record_set_text(record_set) -> str:
    """The record set as the judge sees it: the three closed sets stage 1
    checks against, spelled out. Deterministic ordering, so two identical
    record sets produce one cache key."""
    numerals = ", ".join(_format_numeral(value)
                         for value in sorted(record_set.numerals))
    entities = ", ".join(sorted(record_set.entities))
    dates = ", ".join(sorted(record_set.dates))
    facts = "\n".join(f"  - {fact}" for fact in record_set.facts)
    return (f"numerals: {numerals or '(none)'}\n"
            f"entities: {entities or '(none)'}\n"
            f"dates: {dates or '(none)'}\n"
            f"facts:\n{facts or '  (none)'}")


def _format_numeral(value: float) -> str:
    """Rendered from the stored value, never re-derived. `repr` of a float
    would leak binary representation noise into the cache key."""
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text or "0"


def build_judge_prompt_parts(sentence: str, record_set) -> tuple[str, str]:
    """(cacheable static prefix, dynamic suffix), in that order. Section 18:
    "Never place dynamic content before static content"."""
    return _STATIC, _DYNAMIC.format(sentence=sentence,
                                    record_set=_record_set_text(record_set))


def build_judge_prompt(sentence: str, record_set) -> str:
    static, dynamic = build_judge_prompt_parts(sentence, record_set)
    return static + dynamic
