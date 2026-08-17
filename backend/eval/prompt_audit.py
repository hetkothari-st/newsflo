"""TASK 7.5 -- prompt assembly order, checked rather than promised.

Spec section 18: "cacheable static prefix (safety rules, taxonomy, schema,
reasoning rules) + dynamic suffix (event, candidate, evidence, graph
context). Never place dynamic content before static content -- it destroys
the prefix cache."

A violation of that rule is INVISIBLE. Nothing fails, no test goes red, the
output is identical -- the bill just goes up on every call, forever. So it
needs a check, and the check needs to be able to fail: this module's own
test feeds it a deliberately violating builder.

THE CONTRACT A BUILDER MUST OFFER. `parts_for(payload) -> (static, dynamic)`,
where `static + dynamic` is the prompt actually sent. Splitting the builder
in two is what makes the property checkable at all; a builder that returns
one string can only be inspected by guessing where the boundary is.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence


class PromptOrderError(AssertionError):
    """A prompt builder that would destroy the provider's prefix cache."""


def check_prompt_order(parts_for: Callable[[Any], tuple[str, str]],
                       samples: Sequence[Any]) -> None:
    """Raise unless `parts_for` puts a genuinely static prefix first.

    Four things are checked, and each one is a way the rule is broken in
    practice:

      1. at least two samples -- a "static" prefix derived from one payload
         is not evidence of anything;
      2. the prefix is BYTE-IDENTICAL across payloads. A prefix that mentions
         the company, the date or the event is not a prefix, it is a cache
         miss with extra steps;
      3. the prefix is non-empty. A builder that declares everything dynamic
         passes rule 2 trivially;
      4. no payload's own content appears in the prefix, and every payload's
         content appears in the suffix. This is what catches the actual
         section 18 failure: dynamic content placed BEFORE the rules.
    """
    if len(samples) < 2:
        raise PromptOrderError(
            "the order check needs at least two payloads: a prefix derived "
            "from a single payload cannot be shown to be static")

    parts = [parts_for(sample) for sample in samples]
    statics = {static for static, _ in parts}
    if len(statics) != 1:
        raise PromptOrderError(
            "the 'static' prefix differs between payloads, so it is not "
            "cacheable. Differences begin at character "
            f"{_first_divergence(sorted(statics))}.")

    static = next(iter(statics))
    if not static.strip():
        raise PromptOrderError(
            "the static prefix is empty -- every byte of this prompt is "
            "dynamic, so the provider caches nothing")

    for sample, (_, dynamic) in zip(samples, parts):
        text = sample if isinstance(sample, str) else str(sample)
        if text and text in static:
            raise PromptOrderError(
                "payload content appears INSIDE the static prefix, which "
                "means dynamic content precedes the rules: "
                f"{text[:80]!r}")
        if text and text not in dynamic:
            raise PromptOrderError(
                "payload content is in neither part of the assembled prompt; "
                f"the builder dropped it: {text[:80]!r}")


def _first_divergence(values: Sequence[str]) -> int:
    first, second = values[0], values[-1]
    for index, (left, right) in enumerate(zip(first, second)):
        if left != right:
            return index
    return min(len(first), len(second))
