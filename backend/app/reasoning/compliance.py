"""Compliance guard: reject any LLM-generated text containing a
percentage, price target, or buy/sell/hold-style language before it is
ever persisted (docs/NEWS_IMPACT_APP_SPEC.md §7, §10 -- "No LLM-generated
number reaches a user"). Every LLM refinement function in
app.analysis.refinement and app.companies.business_profile runs its
generated text through this before persisting it.
"""
import re
from typing import NamedTuple

_PERCENT_RE = re.compile(r"-?\d+(\.\d+)?\s*%")
_TARGET_PRICE_RE = re.compile(r"\btarget\s+price\b|\bprice\s+target\b", re.IGNORECASE)
_ADVICE_WORDS_RE = re.compile(
    r"\b(buy|sell|hold|overweight|underweight|outperform|underperform)\b", re.IGNORECASE
)


class ValidationResult(NamedTuple):
    is_valid: bool
    reason: str | None


def validate_no_advice_language(text: str | None) -> ValidationResult:
    """Rejects text containing a percentage figure, a price-target phrase,
    or buy/sell/hold/rating language -- the three categories this
    architecture never allows an LLM to emit (measured numbers only, no
    advice). Empty/None text is valid (nothing to reject)."""
    if not text:
        return ValidationResult(True, None)
    if _PERCENT_RE.search(text):
        return ValidationResult(False, "contains a percentage figure")
    if _TARGET_PRICE_RE.search(text):
        return ValidationResult(False, "contains a price-target phrase")
    match = _ADVICE_WORDS_RE.search(text)
    if match:
        return ValidationResult(False, f"contains buy/sell/hold-style language ({match.group(0)!r})")
    return ValidationResult(True, None)


def validate_or_none(text: str | None) -> str | None:
    """Convenience wrapper for generation call sites: returns ``text``
    unchanged if it passes validate_no_advice_language, else None -- so a
    caller can always do ``field = validate_or_none(llm_output)`` and never
    persist rejected text."""
    if text is None:
        return None
    return text if validate_no_advice_language(text).is_valid else None
