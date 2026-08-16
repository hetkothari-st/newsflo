"""TASK 0.6 -- the claim COMPILER (spec §11.2).

Prose is compiled from records, never written by a model. Templates are
keyed by `(claim_type, direction, materiality_bucket)` and every numeral
enters through a template VARIABLE whose value came out of a stored numeric
field. There is not one digit in any template string -- pinned by
`tests/phase0/test_firewall.py::test_compiler_templates_contain_no_literal_
numerals`.

DETERMINISTIC PLAIN-PYTHON TEMPLATES, NOT JINJA. The phase file says
"deterministic Jinja templates"; this repo has no jinja2 dependency and the
controller ruled plain `str.format` templates instead. The property that
matters -- rendering is a total function of the records -- is unchanged.

The optional LLM fluency pass is an INJECTED callable (`rewriter=`). It may
only rewrite; the entailment firewall then deletes anything it added. With
`rewriter=None` the system is fully functional, which is the required
default.
"""
from typing import Any, Callable, Iterable, Mapping, Sequence

# One base sentence per (claim_type, direction). `{degree}` is filled at
# import time from the materiality bucket, which is what makes the key a
# 3-tuple: the same claim reads differently at HIGH and at LOW, and picking
# the adjective at render time would hide that behind a variable.
_BASE: dict[tuple[str, str], str] = {
    ("COST_EXPOSURE", "NEGATIVE"):
        "{ticker} has {degree} cost exposure to {tag}, at {share_pct} percent "
        "of {base_kind}.",
    ("COST_EXPOSURE", "POSITIVE"):
        "{ticker} benefits from {degree} cost exposure to {tag}, at "
        "{share_pct} percent of {base_kind}.",
    ("COST_EXPOSURE", "MIXED"):
        "{ticker} has {degree} cost exposure to {tag}, at {share_pct} percent "
        "of {base_kind}, with offsetting channels in both directions.",
    ("COST_EXPOSURE", "UNCERTAIN"):
        "{ticker} has {degree} cost exposure to {tag}, at {share_pct} percent "
        "of {base_kind}, but the net effect is not resolved.",
    ("REVENUE_EXPOSURE", "POSITIVE"):
        "{ticker} has {degree} revenue exposure to {tag}, at {share_pct} "
        "percent of {base_kind}.",
    ("REVENUE_EXPOSURE", "NEGATIVE"):
        "{ticker} has {degree} revenue exposure to {tag}, at {share_pct} "
        "percent of {base_kind}.",
    ("PASS_THROUGH", "NEGATIVE"):
        "{ticker} passes through {share_passed_pct} percent of the change, "
        "with a lag of about {lag_months} months.",
    ("PASS_THROUGH", "POSITIVE"):
        "{ticker} passes through {share_passed_pct} percent of the change, "
        "with a lag of about {lag_months} months.",
    ("MATERIALITY", "NEGATIVE"):
        "The effect on {ticker} is {degree} and negative.",
    ("MATERIALITY", "POSITIVE"):
        "The effect on {ticker} is {degree} and positive.",
    ("MATERIALITY", "MIXED"):
        "The effect on {ticker} is {degree} and points in both directions.",
    ("MATERIALITY", "UNCERTAIN"):
        "The effect on {ticker} is {degree} and its direction is unresolved.",
}

_DEGREE = {"HIGH": "large", "MEDIUM": "moderate", "LOW": "small"}

TEMPLATES: dict[tuple[str, str, str], str] = {
    (claim_type, direction, bucket): sentence.replace("{degree}", degree)
    for (claim_type, direction), sentence in _BASE.items()
    for bucket, degree in _DEGREE.items()
}

# Which structured field feeds which template variable, and how it renders.
# A share stored as a fraction renders as a percentage; the firewall's
# record set carries BOTH forms, so the rendered numeral still traces to the
# stored one.
_VARIABLE_SOURCES: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "share_pct": ("share_of_base", lambda v: _number(float(v) * 100)),
    "share_passed_pct": ("share_passed", lambda v: _number(float(v) * 100)),
    "lag_months": ("lag_months", lambda v: _number(v)),
    "tag": ("tag", str),
    "base_kind": ("base_kind", str),
}

MECHANISM_SENTENCE = "{ticker} is exposed through the {mechanism} channel."


def _number(value: Any) -> str:
    """Render a number without inventing precision: 28.0 -> '28'."""
    number = float(value)
    return str(int(number)) if number == int(number) else f"{number:g}"


def _variables(claim, ticker: str) -> dict[str, Any] | None:
    variables: dict[str, Any] = {"ticker": ticker}
    for name, (field, render) in _VARIABLE_SOURCES.items():
        if field in claim.structured:
            variables[name] = render(claim.structured[field])
    return variables


def render_claim(claim, direction: str, materiality_bucket: str,
                 ticker: str) -> str | None:
    """One claim -> one sentence, or None when no template covers it or a
    variable the template needs is not stored. Emitting a sentence with a
    missing value is exactly the fabrication this layer exists to prevent."""
    template = TEMPLATES.get((claim.claim_type, direction, materiality_bucket))
    if template is None:
        return None
    try:
        return template.format(**_variables(claim, ticker))
    except KeyError:
        return None


def compile_prose(impact, claims: Iterable) -> list[str]:
    """`CompanyImpact` + `Claim`s -> base prose, as a list of sentences.

    Deterministic: claims are rendered in claim_id order and nothing here
    reads a clock, a random source or the network.
    """
    ticker = impact.ticker or ""
    sentences: list[str] = []

    if impact.mechanism_id:
        sentences.append(MECHANISM_SENTENCE.format(
            ticker=ticker, mechanism=str(impact.mechanism_id).replace("_", " ")))

    for claim in sorted(claims, key=lambda c: c.claim_id):
        sentence = render_claim(claim, impact.net_effect,
                                impact.materiality_bucket, ticker)
        if sentence:
            sentences.append(sentence)
    return sentences


def render(impact, claims: Sequence, *,
           rewriter: Callable[[str], str] | None = None) -> str:
    """Base prose as one string, optionally passed through an INJECTED
    fluency rewriter.

    The rewriter contract (spec §11.2): it may rewrite wording ONLY. Adding
    a fact, number, entity, causal step or qualifier is forbidden -- and is
    not merely forbidden by instruction, it is deleted downstream by
    `app.output.firewall`. `rewriter=None` (the default) is a fully
    functional system.
    """
    base = " ".join(compile_prose(impact, claims))
    if rewriter is None:
        return base
    return rewriter(base)


def fallback_text(impact, claims: Sequence) -> str:
    """The deterministic template output, verbatim -- what the firewall
    falls back to when deletion leaves the rewritten prose too short."""
    return " ".join(compile_prose(impact, claims))
