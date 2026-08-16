"""TASK 0.6 -- the ENTAILMENT FIREWALL (spec §11.3).

Every sentence that reaches a user must be reconstructible from the stored
records. This module is the structural enforcement of that rule:

  STAGE 1 (deterministic, ALWAYS runs)
    * every numeral in the sentence is in the record set (0.5% tolerance
      for rounding)
    * every capitalised entity is in the record set
    * every date is in the record set
  STAGE 2 (LLM entailment judge, only when a judge is INJECTED)
    * binary entailed / not-entailed, with the record set as context, from a
      different prompt lineage than the rewriter

A failing sentence is DELETED. Never repaired, never rewritten -- a repair
is a second chance to fabricate. If deletion leaves the output below
`MIN_PROSE_CHARS`, the caller's deterministic template prose is used
verbatim instead.

NO CLIENT IS CONSTRUCTED HERE. The judge is an injected object exposing
`entails(sentence, record_set) -> bool` and `model_id`. That is what makes
"zero real API calls in tests" structural rather than a convention.
"""
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol, Sequence

import re

# Below this, deleted output is not worth publishing and the deterministic
# template prose is used instead.
MIN_PROSE_CHARS = 60

# Rounding tolerance for "this numeral is in the record set".
NUMERAL_TOLERANCE = 0.005      # 0.5%

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_NUMERAL = re.compile(r"\d[\d,]*(?:\.\d+)?")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_MONTH_DATE = re.compile(
    r"\b(?:\d{1,2}\s+)?(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{4}\b")
# Entity-shaped tokens. NOT `[A-Z]…`: real NSE tickers start with digits
# (3MINDIA.NS, 5PAISA.NS, 63MOONS.NS), and a pattern that could not see them
# left their leading digits to the numeral check, which then deleted an
# otherwise honest sentence for "numeral not in record set: 63" (fix round
# 1, finding I3). A token counts as entity-shaped when it contains at least
# one UPPERCASE letter -- that is what separates `63MOONS.NS` from `90`, and
# an ordinary lowercase word from a name.
_TOKEN = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9&.\-']*\b")
_HAS_UPPER = re.compile(r"[A-Z]")

# Capitalised words that are ordinary English, not entities. Deliberately
# short: anything not here must be justified by the record set.
ALLOWED_CAPITALISED = frozenset({
    "A", "An", "And", "As", "At", "But", "By", "For", "From", "How", "If",
    "In", "Is", "It", "Its", "No", "Not", "Of", "On", "Or", "The", "Their",
    "There", "This", "To", "When", "Where", "While", "With",
})


class EntailmentJudge(Protocol):
    """Stage 2's contract. Implemented by an injected adapter; nothing in
    app/output constructs one."""
    model_id: str

    def entails(self, sentence: str, record_set: "RecordSet") -> bool: ...


@dataclass(frozen=True)
class RecordSet:
    """Everything the prose is allowed to say, drawn from stored records."""
    numerals: tuple[float, ...] = ()
    entities: frozenset[str] = frozenset()
    dates: frozenset[str] = frozenset()
    facts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Deletion:
    sentence: str
    reason: str
    stage: str              # STAGE_1 | STAGE_2
    model_id: str | None = None


@dataclass
class FirewallResult:
    kept: list[str] = field(default_factory=list)
    deletions: list[Deletion] = field(default_factory=list)
    fallback_used: bool = False
    text: str = ""

    @property
    def sentences_total(self) -> int:
        return len(self.kept) + len(self.deletions)

    @property
    def deletion_rate(self) -> float:
        return (len(self.deletions) / self.sentences_total
                if self.sentences_total else 0.0)


# --- record set ------------------------------------------------------------

def _entity_tokens(*values: Any) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        for token in _TOKEN.findall(str(value or "")):
            if _HAS_UPPER.search(token):
                tokens.add(token.rstrip("."))
    return tokens


def record_set_from(impact, claims: Iterable = (), evidence: Iterable = ()) -> RecordSet:
    """The record set for one company's prose: the numerals, entities and
    dates that EXIST in the stored records. Nothing else may appear in a
    sentence."""
    numerals: list[float] = []
    entities: set[str] = set()
    dates: set[str] = set()

    entities |= _entity_tokens(impact.ticker, impact.isin)
    for channel in impact.channels:
        entities |= _entity_tokens(channel.get("channel_id"),
                                   channel.get("mechanism_id"))
    entities |= _entity_tokens(impact.mechanism_id, impact.net_effect,
                               impact.materiality_bucket, impact.directness,
                               impact.discovery_source, impact.publication_tier)
    if impact.graph_distance is not None:
        numerals.append(float(impact.graph_distance))
    numerals.append(float(impact.sign_consistency))

    for claim in claims:
        entities |= _entity_tokens(*(v for v in claim.structured.values()
                                     if isinstance(v, str)))
        for value in claim.numerals:
            numerals.append(float(value))
            # A share stored as a fraction is rendered as a percentage by
            # the compiler; both forms trace to the SAME stored field.
            if 0 < abs(value) < 1:
                numerals.append(float(value) * 100)

    for item in evidence:
        entities |= _entity_tokens(item.source_name, item.source_type)
        if getattr(item, "source_date", None):
            dates.add(str(item.source_date))

    return RecordSet(numerals=tuple(sorted(set(numerals))),
                     entities=frozenset(entities), dates=frozenset(dates))


# --- stage 1 ---------------------------------------------------------------

def _numeral_in(value: float, record_set: RecordSet) -> bool:
    for known in record_set.numerals:
        if known == value:
            return True
        if known and abs(value - known) <= NUMERAL_TOLERANCE * abs(known):
            return True
    return False


def _blank(text: str) -> str:
    """Same length, no content -- masking rather than deleting keeps every
    other token's word boundaries intact, so a numeral sitting next to a
    masked ticker is still seen."""
    return re.sub(r"[^\s]", " ", text)


def stage_one(sentence: str, record_set: RecordSet) -> str | None:
    """The deterministic checks. Returns a failure reason, or None to pass.

    ORDER IS LOAD-BEARING (fix round 1, finding I3):
      1. dates, so an unknown date is reported as a date problem rather than
         as three unknown numbers;
      2. entities, and every VALIDATED entity is then MASKED OUT -- the
         digits inside `63MOONS.NS` are part of its name, not a claim about
         the world, and reading them as numerals deleted honest sentences.
         Only validated entities are masked: an unknown ticker-shaped token
         still fails as an entity, and numerals adjacent to a masked ticker
         are still checked;
      3. numerals, over what is left.
    """
    remainder = sentence
    for pattern in (_ISO_DATE, _MONTH_DATE):
        for match in pattern.findall(remainder):
            if match not in record_set.dates:
                return f"date not in record set: {match}"
        remainder = pattern.sub(_blank, remainder)

    masked: list[str] = []
    position = 0
    for match in _TOKEN.finditer(remainder):
        token = match.group(0)
        if not _HAS_UPPER.search(token):
            continue                       # ordinary word or bare number
        cleaned = token.rstrip(".")
        if cleaned not in ALLOWED_CAPITALISED and cleaned not in record_set.entities:
            return f"entity not in record set: {cleaned}"
        masked.append(remainder[position:match.start()])
        masked.append(_blank(token))
        position = match.end()
    masked.append(remainder[position:])
    remainder = "".join(masked)

    for raw in _NUMERAL.findall(remainder):
        value = float(raw.replace(",", ""))
        if not _numeral_in(value, record_set):
            return f"numeral not in record set: {raw}"
    return None


# --- metrics ---------------------------------------------------------------
# Prometheus exposition without a dependency: this repo has no
# prometheus_client, and adding one for two counters is not worth it. The
# text format is the contract, and it is stable.
_METRICS = {"sentences_total": 0, "deletions": {"STAGE_1": 0, "STAGE_2": 0}}


def reset_metrics() -> None:
    _METRICS["sentences_total"] = 0
    _METRICS["deletions"] = {"STAGE_1": 0, "STAGE_2": 0}


def metrics_text() -> str:
    lines = [
        "# HELP newsflo_firewall_sentences_total Sentences examined by the entailment firewall.",
        "# TYPE newsflo_firewall_sentences_total counter",
        f"newsflo_firewall_sentences_total {_METRICS['sentences_total']}",
        "# HELP newsflo_firewall_deletions_total Sentences deleted by the entailment firewall.",
        "# TYPE newsflo_firewall_deletions_total counter",
    ]
    for stage, count in sorted(_METRICS["deletions"].items()):
        lines.append(f'newsflo_firewall_deletions_total{{stage="{stage}"}} {count}')
    return "\n".join(lines) + "\n"


# --- the firewall ----------------------------------------------------------

def firewall(sentences: Sequence[str], record_set: RecordSet, *,
             judge: EntailmentJudge | None = None,
             fallback_text: str = "",
             min_prose_chars: int = MIN_PROSE_CHARS) -> FirewallResult:
    result = FirewallResult()
    for sentence in sentences:
        _METRICS["sentences_total"] += 1
        reason = stage_one(sentence, record_set)
        if reason is not None:
            _METRICS["deletions"]["STAGE_1"] += 1
            result.deletions.append(Deletion(sentence, reason, "STAGE_1"))
            continue
        if judge is not None and not judge.entails(sentence, record_set):
            _METRICS["deletions"]["STAGE_2"] += 1
            result.deletions.append(Deletion(
                sentence, "not entailed by the record set", "STAGE_2",
                getattr(judge, "model_id", None)))
            continue
        # Kept sentences are passed through BYTE-IDENTICALLY. A firewall
        # that edits is a firewall that can introduce.
        result.kept.append(sentence)

    kept_text = " ".join(result.kept)
    if len(kept_text) < min_prose_chars and fallback_text:
        result.fallback_used = True
        result.text = fallback_text
    else:
        result.text = kept_text
    return result


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(text.strip()) if s]


def log_deletions(session, *, event_id: str | None, company_id: int | None,
                  result: FirewallResult) -> int:
    """Persist every deletion. A rising rate is the early warning that a
    prompt or model change has started fabricating (spec §11.3)."""
    from app.models import FirewallDeletion

    for deletion in result.deletions:
        session.add(FirewallDeletion(
            event_id=event_id, company_id=company_id,
            sentence=deletion.sentence, reason=deletion.reason,
            stage=deletion.stage, model_id=deletion.model_id))
    return len(result.deletions)
