"""Gate Zero baseline scorer -- emits BASELINE.md (EXECUTION_CONTRACT §2).

    python scripts/score_baseline.py                       # writes ../BASELINE.md
    python scripts/score_baseline.py --db sqlite:///./newsflo.db --out ../BASELINE.md

Scores what the system ALREADY PUBLISHED for each labeled event against
the adjudicated human labels, and writes the one-page baseline that
docs/v5/EXECUTION_CONTRACT.md §2 requires before any further V5 work
starts.

ZERO API CALLS, BY CONSTRUCTION. "Runs the current production pipeline
over all labeled events" is satisfied by reading the pipeline's PERSISTED
output (alerts + alert_companies for the event's article). This script
imports no provider SDK, no app.analysis module and no HTTP client at all
-- tests/test_gate_zero_tooling.py enforces that statically and by
checking sys.modules in a clean subprocess. An event whose article has no
stored analysis is reported as UNSCORED with instructions; running the
analysis for it is a separate, human-initiated act, never a side effect of
measuring.

IT NEVER WRITES. Reads only. It also refuses to emit a baseline over an
empty corpus: a precision of "0%" or "100%" computed over zero labels is
the most dangerous number this project could produce, so zero events or
zero labels exits 2 with an explanation and writes nothing.

--------------------------------------------------------------------------
DEFINITIONS (all of them, because a metric whose definition is implicit is
a metric that will be quietly redefined the first time it is inconvenient)
--------------------------------------------------------------------------

PUBLISHED TIER. A stored alert_companies row's tier is `display_tier` when
that column is set. It is NULL on every row written with the V4 strict
gate flag off, which is most of the existing corpus, so those rows fall
back to a DERIVED tier: causal_distance == 1 (or, when that is also NULL,
impact_level == "direct") -> PRIMARY; anything further out -> SECONDARY.
That fallback is a reading of app/models.py's own documented derivation
(impact_level is "DERIVED from causal_distance"), not a new judgment, and
BASELINE.md reports how many rows were scored through it so the reader can
discount accordingly.

EXPECTED TIER (adjudicated). Per (event, company_ref):
  * both labelers agree           -> that tier. Agreement needs no adjudicator.
  * an eval_adjudication row exists -> it WINS over agreement:
      LABELER_A / LABELER_B -> that labeler's tier (A and B are the event's
                               labelers sorted by name, stated in BASELINE.md)
      MERGED   -> the labelers' tier if they agree; if they do not, the pair
                  is UNRESOLVABLE -- excluded and reported, never guessed
      DISPUTED -> excluded from every precision/recall denominator and
                  counted as the corpus's ambiguity rate
  * they disagree with no adjudication row -> UNADJUDICATED: excluded and
    reported loudly. Silence is not agreement.
A company named by one labeler and not the other is read as ABSENT for the
silent labeler: the labeling UI states that the PRIMARY/ABSENT lists are
exhaustive for the event. A company the SYSTEM published that neither
labeler named is therefore ABSENT by agreement -- which is exactly how a
false positive becomes measurable.

PRIMARY PRECISION = TP / (TP + FP) over resolved pairs, where TP is a
published-PRIMARY company whose adjudicated tier is PRIMARY and FP is a
published-PRIMARY company whose adjudicated tier is not. DISPUTED,
UNADJUDICATED and UNRESOLVABLE pairs are in NO denominator.

PRIMARY RECALL = TP / (TP + FN), FN = adjudicated-PRIMARY company the
system did not publish at PRIMARY.

WRONG-DIRECTION RATE = among TRUE-POSITIVE PRIMARY rows where both the
adjudicated expectation and the published row carry a directional value
(bullish/bearish), the fraction whose published direction is the opposite.
The denominator is printed alongside. Direction is optional on a label, so
silence is not disagreement: when only one labeler stated a direction it
is used; when two stated conflicting directions the pair is excluded and
counted separately.

RIPPLE FAMILY RECALL = of the adjudicated expected families, the fraction
with at least one published SECONDARY-tier company whose sector or
sub_sector string-matches the family. Families have no per-company
adjudication row (they are event-level), so "adjudicated" here means the
INTERSECTION of the two labelers' family sets; the symmetric difference is
reported as disputed families. LIMITATION, stated plainly: the match is a
normalized substring comparison between a free-text family name and the
company's stored sector/sub_sector. It will miss a family whose wording
does not resemble our taxonomy ("airlines" vs "Aviation") and can over-match
a very short family name. It measures the taxonomy as much as the engine.

FALSE PRIMARY ON NULL EVENTS = the number of stratum=null_event events
with at least one published PRIMARY company, reported as "n of N" with the
offending events named. A hard-zero gate later (08_PHASE_7 Task 7.3).

FABRICATED NUMERALS = numeral tokens appearing in served text
(alert_companies.mechanism / rationale / why) that do not appear in the
event's source material: the article title, content and full_content, plus
the alert's stored `facts` and `fact_items_json`. Commas are stripped from
both sides before comparison. This is deliberately a fresh, narrow check
rather than a call into app.analysis.refinement.validate_closed_world:
that validator takes a live ORM Session and an allowed-company set,
inspects only PERCENT tokens, folds in a company-name hallucination check
and answers all-or-nothing (text or None) rather than naming the offending
numerals -- and importing it would pull app.analysis into a script that
must provably be unable to reach an LLM. It is NOT modified, and nothing
here changes its behaviour for the running system.

INTERNAL CONTRADICTIONS = stored rows where economic_effect contradicts
direction (positive+bearish, negative+bullish), plus any (alert, company)
pair holding two rows with opposite directions.

COHEN'S KAPPA = per-company expected_tier agreement between the two
labelers, over the union of companies either labeler named for an event
(the silent labeler contributing ABSENT, as above), pooled across every
2-labeler event. kappa = (p_o - p_e) / (1 - p_e) with p_e the sum over
categories of each labeler's marginal probability product. It is reported
as UNDEFINED, never as 1.0, when there is no category variance -- a corpus
where both labelers said PRIMARY to everything carries no information
about their agreement, and printing "perfect" would be a lie.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import sqlalchemy as sa  # noqa: E402

from app.eval import store  # noqa: E402
from app.eval.schema import STRATA  # noqa: E402

# The published-tier vocabulary. Held as literals rather than imported from
# app.analysis.impact_graph.publication_gate -- this script must not import
# app.analysis at all (see the module docstring) -- and pinned to that
# module by test_secondary_tier_spellings_track_the_publication_gate so the
# copy cannot rot. "secondary_deep_dive"/"secondary" are dead spellings that
# are still READABLE on rows written before migration 0008's rewrite.
PRIMARY_TIER = "primary"
SECONDARY_TIERS = ("secondary_ripple", "secondary_deep_dive", "secondary")
MACRO_TIER = "macro_context"

DIRECTIONAL = ("bullish", "bearish")
_OPPOSITE = {"bullish": "bearish", "bearish": "bullish"}

_NUMERAL_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# small pure helpers
# ---------------------------------------------------------------------------

def cohens_kappa(pairs: Sequence[tuple[str, str]]) -> float | None:
    """Cohen's kappa over (labeler_a_category, labeler_b_category) pairs.

    Returns None -- not 0.0, not 1.0 -- when kappa is undefined: no pairs
    at all, or no category variance (p_e == 1), where the statistic
    carries no information and any number printed would be a fabrication.
    """
    if not pairs:
        return None
    n = len(pairs)
    observed = sum(1 for a, b in pairs if a == b) / n
    a_counts = Counter(a for a, _ in pairs)
    b_counts = Counter(b for _, b in pairs)
    expected = sum((a_counts[c] / n) * (b_counts[c] / n)
                   for c in set(a_counts) | set(b_counts))
    if expected >= 1.0:
        return None
    return (observed - expected) / (1 - expected)


def normalize_family(value: str | None) -> str:
    return _NON_ALNUM_RE.sub(" ", (value or "").lower()).strip()


def family_matches(family: str, sector: str | None, sub_sector: str | None) -> bool:
    """Normalized substring match either way round. See the LIMITATION note
    in the module docstring -- this is a string comparison, not semantics."""
    target = normalize_family(family)
    if not target:
        return False
    for candidate in (normalize_family(sector), normalize_family(sub_sector)):
        if not candidate:
            continue
        if target == candidate or target in candidate or candidate in target:
            return True
    return False


def numerals(text: str | None) -> list[str]:
    return [m.group(0).replace(",", "") for m in _NUMERAL_RE.finditer(text or "")]


def fabricated_numerals_in(text: str | None, source: str) -> list[str]:
    """Numerals in ``text`` that do not literally appear in ``source``."""
    haystack = (source or "").replace(",", "")
    return [n for n in numerals(text) if n not in haystack]


def published_tier(row: dict[str, Any]) -> tuple[str, bool]:
    """(tier, derived) for one stored alert_companies row.

    ``derived`` is True when display_tier was NULL and the tier had to be
    read off causal_distance / impact_level -- counted and disclosed in
    BASELINE.md rather than silently blended with gate-authorized rows.
    """
    stored = (row.get("display_tier") or "").strip()
    if stored:
        if stored == PRIMARY_TIER:
            return PRIMARY_TIER, False
        if stored in SECONDARY_TIERS:
            return SECONDARY_TIERS[0], False
        return stored, False
    distance = row.get("causal_distance")
    if distance is not None:
        return (PRIMARY_TIER if int(distance) <= 1 else SECONDARY_TIERS[0]), True
    level = (row.get("impact_level") or "").strip()
    if level == "direct":
        return PRIMARY_TIER, True
    if level:
        return SECONDARY_TIERS[0], True
    return "", True


# ---------------------------------------------------------------------------
# result container
# ---------------------------------------------------------------------------

@dataclass
class StratumScore:
    events: int = 0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    wrong_direction: int = 0
    direction_denominator: int = 0
    families_expected: int = 0
    families_hit: int = 0


@dataclass
class BaselineResult:
    events_total: int = 0
    events_scored: int = 0
    unscored_events: list[tuple[str, str]] = field(default_factory=list)
    under_labeled_events: list[tuple[str, int]] = field(default_factory=list)
    unresolved_article_events: list[tuple[str, str]] = field(default_factory=list)

    primary_true_positives: int = 0
    primary_false_positives: int = 0
    primary_false_negatives: int = 0
    false_positive_detail: list[tuple[str, str]] = field(default_factory=list)
    false_negative_detail: list[tuple[str, str]] = field(default_factory=list)

    wrong_direction: int = 0
    wrong_direction_denominator: int = 0
    direction_conflicts: int = 0

    ripple_families_expected: int = 0
    ripple_families_hit: int = 0
    ripple_families_disputed: int = 0
    missed_families: list[tuple[str, str]] = field(default_factory=list)

    null_events_total: int = 0
    null_events_with_primary: int = 0
    null_event_violations: list[tuple[str, list[str]]] = field(default_factory=list)

    fabricated_numerals: int = 0
    fabricated_detail: list[tuple[str, str, str]] = field(default_factory=list)
    internal_contradictions: int = 0
    contradiction_detail: list[tuple[str, str, str]] = field(default_factory=list)

    disputed_pairs: int = 0
    unadjudicated_pairs: list[tuple[str, str]] = field(default_factory=list)
    unresolvable_merged: list[tuple[str, str]] = field(default_factory=list)

    rows_scored: int = 0
    rows_tier_derived: int = 0

    kappa: float | None = None
    kappa_pairs: int = 0
    kappa_note: str = ""

    per_stratum: dict[str, StratumScore] = field(default_factory=dict)
    per_sector: dict[str, StratumScore] = field(default_factory=dict)
    labeler_roles: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def primary_precision(self) -> float | None:
        denominator = self.primary_true_positives + self.primary_false_positives
        return self.primary_true_positives / denominator if denominator else None

    @property
    def primary_recall(self) -> float | None:
        denominator = self.primary_true_positives + self.primary_false_negatives
        return self.primary_true_positives / denominator if denominator else None

    @property
    def wrong_direction_rate(self) -> float | None:
        return (self.wrong_direction / self.wrong_direction_denominator
                if self.wrong_direction_denominator else None)

    @property
    def ripple_family_recall(self) -> float | None:
        return (self.ripple_families_hit / self.ripple_families_expected
                if self.ripple_families_expected else None)


class EmptyCorpusError(Exception):
    """Zero events or zero labels. Never scored, never reported as a rate."""


# ---------------------------------------------------------------------------
# stored system output
# ---------------------------------------------------------------------------

_PUBLISHED_SQL = sa.text("""
    SELECT ac.id AS row_id, ac.alert_id, ac.company_id, ac.direction, ac.display_tier,
           ac.causal_distance, ac.impact_level, ac.economic_effect, ac.mechanism,
           ac.rationale, ac.why, c.ticker, c.sector, c.sub_sector,
           a.facts, a.fact_items_json
      FROM alert_companies ac
      JOIN alerts a ON a.id = ac.alert_id
      JOIN companies c ON c.id = ac.company_id
     WHERE a.article_id = :article_id
""")


def _published_rows(conn: sa.Connection, article_id: int) -> list[dict[str, Any]]:
    return [dict(r) for r in
            conn.execute(_PUBLISHED_SQL, {"article_id": article_id}).mappings()]


def _has_alert(conn: sa.Connection, article_id: int) -> bool:
    return conn.execute(sa.text("SELECT COUNT(*) FROM alerts WHERE article_id = :a"),
                        {"a": article_id}).scalar() > 0


def _source_text(article: dict[str, Any], rows: Iterable[dict[str, Any]]) -> str:
    parts = [article.get("title") or "", article.get("content") or "",
             article.get("full_content") or ""]
    seen_alerts: set[int] = set()
    for row in rows:
        if row["alert_id"] in seen_alerts:
            continue
        seen_alerts.add(row["alert_id"])
        parts.append(row.get("facts") or "")
        raw = row.get("fact_items_json")
        if raw:
            try:
                for item in json.loads(raw):
                    parts.append(str(item.get("text", "")) if isinstance(item, dict) else str(item))
            except (ValueError, TypeError):
                parts.append(str(raw))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# label resolution
# ---------------------------------------------------------------------------

def _resolve_pair(company: str, tiers: dict[str, str], labelers: Sequence[str],
                  adjudication: dict[str, Any] | None) -> tuple[str | None, str]:
    """-> (resolved tier or None, status). Status is one of
    agreed / adjudicated / disputed / unadjudicated / unresolvable_merged."""
    values = [tiers[who] for who in labelers]
    if adjudication:
        resolution = adjudication["resolution"]
        if resolution == "DISPUTED":
            return None, "disputed"
        if resolution == "LABELER_A":
            return tiers[labelers[0]], "adjudicated"
        if resolution == "LABELER_B":
            return tiers[labelers[1]], "adjudicated"
        if resolution == "MERGED":
            if len(set(values)) == 1:
                return values[0], "adjudicated"
            return None, "unresolvable_merged"
    if len(set(values)) == 1:
        return values[0], "agreed"
    return None, "unadjudicated"


def _resolve_direction(company: str, labels: dict[str, dict[str, Any]],
                       labelers: Sequence[str],
                       adjudication: dict[str, Any] | None) -> tuple[str | None, bool]:
    """-> (direction or None, conflicted)."""
    if adjudication and adjudication["resolution"] in ("LABELER_A", "LABELER_B"):
        who = labelers[0 if adjudication["resolution"] == "LABELER_A" else 1]
        entry = labels.get(who) or {}
        return (entry.get("expected_direction") or None), False
    stated = {(labels.get(who) or {}).get("expected_direction")
              for who in labelers}
    stated.discard(None)
    stated.discard("")
    if len(stated) > 1:
        return None, True
    return (next(iter(stated)) if stated else None), False


def kappa_over_corpus(conn: sa.Connection) -> tuple[float | None, int, str]:
    """Pooled two-labeler kappa over per-company expected_tier. See the
    module docstring for the treatment of unnamed companies."""
    pairs: list[tuple[str, str]] = []
    skipped = 0
    for event in store.all_events(conn):
        labelers = store.labelers_for_event(conn, event["event_id"])
        if len(labelers) != 2:
            skipped += 1
            continue
        labels = store.labels_for_event(conn, event["event_id"])
        universe = sorted({row["company_ref"] for row in labels})
        by_company: dict[str, dict[str, str]] = defaultdict(dict)
        for row in labels:
            by_company[row["company_ref"]][row["labeler"]] = row["expected_tier"]
        for company in universe:
            entry = by_company[company]
            pairs.append((entry.get(labelers[0], "ABSENT"),
                          entry.get(labelers[1], "ABSENT")))
    note = ""
    if skipped:
        note = (f"{skipped} event(s) excluded from kappa: they do not have exactly "
                f"two labelers")
    return cohens_kappa(pairs), len(pairs), note


# ---------------------------------------------------------------------------
# the scorer
# ---------------------------------------------------------------------------

def score_corpus(conn: sa.Connection) -> BaselineResult:
    events = store.all_events(conn)
    label_count = conn.execute(sa.text("SELECT COUNT(*) FROM eval_label")).scalar()
    event_label_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM eval_event_label")).scalar()

    if not events:
        raise EmptyCorpusError(
            "the Gate Zero corpus is EMPTY: eval_event holds no events. Load a "
            "labeled corpus (tools/eval_import.py) or label one (tools/eval_ui.py) "
            "before scoring. No baseline was written -- a precision computed over "
            "zero events would be meaningless, and reporting one would be worse "
            "than reporting nothing.")
    if not label_count and not event_label_count:
        raise EmptyCorpusError(
            f"the Gate Zero corpus is EMPTY of labels: {len(events)} event(s) loaded, "
            "but eval_label and eval_event_label hold no labels at all. Label the "
            "events with two independent labelers (tools/eval_ui.py) before scoring. "
            "No baseline was written.")

    result = BaselineResult(events_total=len(events))
    result.per_stratum = {s: StratumScore() for s in STRATA}

    for event in events:
        event_id = event["event_id"]
        stratum = event["stratum"]
        bucket = result.per_stratum.setdefault(stratum, StratumScore())

        labelers = store.labelers_for_event(conn, event_id)
        if len(labelers) < 2:
            result.under_labeled_events.append((event_id, len(labelers)))
            continue
        result.labeler_roles[event_id] = tuple(labelers[:2])

        article = store.resolve_article(conn, event["article_ref"])
        if article is None:
            result.unresolved_article_events.append((event_id, event["article_ref"]))
            continue
        if not _has_alert(conn, article["id"]):
            result.unscored_events.append((event_id, event["article_ref"]))
            continue

        rows = _published_rows(conn, article["id"])
        result.events_scored += 1
        bucket.events += 1

        labels = store.labels_for_event(conn, event_id)
        adjudications = store.adjudications_for_event(conn, event_id)
        by_company: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for row in labels:
            by_company[row["company_ref"]][row["labeler"]] = row

        published: dict[str, dict[str, Any]] = {}
        secondary_rows: list[dict[str, Any]] = []
        for row in rows:
            tier, derived = published_tier(row)
            result.rows_scored += 1
            result.rows_tier_derived += int(derived)
            ticker = store.normalize_company_ref(row.get("ticker") or "")
            if tier == PRIMARY_TIER and ticker:
                published[ticker] = row
            elif tier in SECONDARY_TIERS:
                secondary_rows.append(row)

        universe = set(by_company) | set(published)
        expected_primary: set[str] = set()
        for company in sorted(universe):
            per_labeler = by_company.get(company, {})
            tiers = {who: (per_labeler.get(who) or {}).get("expected_tier", "ABSENT")
                     for who in labelers}
            adjudication = adjudications.get(company)
            resolved, status = _resolve_pair(company, tiers, labelers, adjudication)
            if status == "disputed":
                result.disputed_pairs += 1
                continue
            if status == "unadjudicated":
                result.unadjudicated_pairs.append((event_id, company))
                continue
            if status == "unresolvable_merged":
                result.unresolvable_merged.append((event_id, company))
                continue

            is_published = company in published
            if resolved == "PRIMARY":
                expected_primary.add(company)
                if is_published:
                    result.primary_true_positives += 1
                    bucket.tp += 1
                    sector = _sector_bucket(result, published[company])
                    sector.tp += 1
                    direction, conflicted = _resolve_direction(
                        company, per_labeler, labelers, adjudication)
                    if conflicted:
                        result.direction_conflicts += 1
                    published_direction = (published[company].get("direction") or "").lower()
                    if (direction in DIRECTIONAL and published_direction in DIRECTIONAL):
                        result.wrong_direction_denominator += 1
                        bucket.direction_denominator += 1
                        if published_direction == _OPPOSITE[direction]:
                            result.wrong_direction += 1
                            bucket.wrong_direction += 1
                else:
                    result.primary_false_negatives += 1
                    bucket.fn += 1
                    result.false_negative_detail.append((event_id, company))
            elif is_published:
                result.primary_false_positives += 1
                bucket.fp += 1
                _sector_bucket(result, published[company]).fp += 1
                result.false_positive_detail.append((event_id, company))

        # --- ripple families (event-level, adjudicated by intersection) ---
        family_sets = [set(normalize_family(f) for f in row["ripple_families"])
                       for row in store.event_labels_for_event(conn, event_id)
                       if row["labeler"] in labelers]
        original: dict[str, str] = {}
        for row in store.event_labels_for_event(conn, event_id):
            for fam in row["ripple_families"]:
                original.setdefault(normalize_family(fam), fam)
        if len(family_sets) >= 2:
            agreed = set.intersection(*family_sets)
            disputed = set.union(*family_sets) - agreed
            result.ripple_families_disputed += len(disputed)
            for fam in sorted(agreed):
                result.ripple_families_expected += 1
                bucket.families_expected += 1
                hit = any(family_matches(fam, row.get("sector"), row.get("sub_sector"))
                          for row in secondary_rows)
                if hit:
                    result.ripple_families_hit += 1
                    bucket.families_hit += 1
                else:
                    result.missed_families.append((event_id, original.get(fam, fam)))

        # --- null events ---
        if stratum == "null_event":
            result.null_events_total += 1
            if published:
                result.null_events_with_primary += 1
                result.null_event_violations.append((event_id, sorted(published)))

        # --- integrity audits over every published row of this event ---
        source = _source_text(article, rows)
        for row in rows:
            for column in ("mechanism", "rationale", "why"):
                for numeral in fabricated_numerals_in(row.get(column), source):
                    result.fabricated_numerals += 1
                    result.fabricated_detail.append(
                        (event_id, row.get("ticker") or "?", f"{column}: {numeral}"))
            effect = (row.get("economic_effect") or "").lower()
            direction = (row.get("direction") or "").lower()
            if ((effect == "positive" and direction == "bearish")
                    or (effect == "negative" and direction == "bullish")):
                result.internal_contradictions += 1
                result.contradiction_detail.append(
                    (event_id, row.get("ticker") or "?",
                     f"economic_effect={effect} vs direction={direction}"))
        seen: dict[tuple[int, int], set[str]] = defaultdict(set)
        for row in rows:
            seen[(row["alert_id"], row["company_id"])].add((row.get("direction") or "").lower())
        for (_alert_id, _company_id), directions in seen.items():
            if len(directions & set(DIRECTIONAL)) > 1:
                result.internal_contradictions += 1
                result.contradiction_detail.append(
                    (event_id, "?", f"duplicate rows with opposite directions: "
                                    f"{sorted(directions)}"))

    result.kappa, result.kappa_pairs, result.kappa_note = kappa_over_corpus(conn)
    return result


def _sector_bucket(result: BaselineResult, row: dict[str, Any]) -> StratumScore:
    key = row.get("sector") or "(no sector)"
    return result.per_sector.setdefault(key, StratumScore())


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _pct(value: float | None, numerator: int | None = None,
         denominator: int | None = None) -> str:
    """Never a bare percentage: always the fraction it came from, and an
    explicit 'not measurable' when there is no denominator."""
    if value is None:
        return "not measurable (no scoreable rows)"
    body = f"{value * 100:.1f}%"
    if numerator is not None and denominator is not None:
        body += f"  ({numerator}/{denominator})"
    return body


def _table(rows: list[list[str]], header: list[str]) -> str:
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join(["---"] * len(header)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_baseline(result: BaselineResult, *, commit: str, when: str) -> str:
    precision = result.primary_precision
    recall = result.primary_recall
    out = [
        f"NEWSFLO BASELINE — {when} — commit {commit}",
        "",
        "```",
        f"PRIMARY precision            {_pct(precision, result.primary_true_positives, result.primary_true_positives + result.primary_false_positives)}",
        f"PRIMARY recall               {_pct(recall, result.primary_true_positives, result.primary_true_positives + result.primary_false_negatives)}",
        f"Wrong-direction rate         {_pct(result.wrong_direction_rate, result.wrong_direction, result.wrong_direction_denominator)}",
        f"Ripple family recall         {_pct(result.ripple_family_recall, result.ripple_families_hit, result.ripple_families_expected)}",
        f"False PRIMARY on null events {result.null_events_with_primary} of {result.null_events_total}",
        f"Fabricated numerals found    {result.fabricated_numerals}",
        f"Internal contradictions      {result.internal_contradictions}",
        "```",
        "",
        "## Corpus",
        "",
        f"- events loaded: **{result.events_total}**",
        f"- events scored: **{result.events_scored}**",
        f"- published rows scored: {result.rows_scored} "
        f"({result.rows_tier_derived} of them with a DERIVED tier -- `display_tier` "
        f"was NULL and the tier was read off `causal_distance`/`impact_level`; see "
        f"the definitions in scripts/score_baseline.py)",
        f"- ambiguity: {result.disputed_pairs} DISPUTED pair(s), excluded from every "
        f"precision denominator and counted here instead",
        f"- Cohen's kappa (2 labelers, expected_tier): "
        + (f"**{result.kappa:.3f}** over {result.kappa_pairs} company pair(s)"
           if result.kappa is not None else
           f"**UNDEFINED** over {result.kappa_pairs} company pair(s) -- no category "
           f"variance, so agreement carries no information")
        + (f". {result.kappa_note}" if result.kappa_note else ""),
        "",
    ]

    if result.unscored_events:
        out += [
            "## UNSCORED EVENTS — action required",
            "",
            "These labeled events have NO stored analysis for their article, so they "
            "are in no metric above. This scorer never triggers an analysis run (zero "
            "API calls by construction). Run the controlled analysis pass for these "
            "articles yourself, then re-run the scorer:",
            "",
        ]
        out += [f"- `{event_id}` -> article_ref `{ref}`"
                for event_id, ref in result.unscored_events]
        out.append("")
    if result.unresolved_article_events:
        out += ["## UNRESOLVABLE ARTICLE REFERENCES", ""]
        out += [f"- `{event_id}` -> `{ref}` is not in the articles table"
                for event_id, ref in result.unresolved_article_events]
        out.append("")
    if result.under_labeled_events:
        out += ["## UNDER-LABELED EVENTS (fewer than two labelers, excluded)", ""]
        out += [f"- `{event_id}`: {count} labeler(s)"
                for event_id, count in result.under_labeled_events]
        out.append("")
    if result.unadjudicated_pairs or result.unresolvable_merged:
        out += ["## UNRESOLVED DISAGREEMENTS (excluded from all denominators)", ""]
        out += [f"- `{event_id}` / `{company}` — labelers disagree, no adjudication"
                for event_id, company in result.unadjudicated_pairs]
        out += [f"- `{event_id}` / `{company}` — MERGED but the labelers' tiers differ"
                for event_id, company in result.unresolvable_merged]
        out.append("")

    strata_rows = []
    for stratum, score in result.per_stratum.items():
        if not score.events:
            strata_rows.append([stratum, "0", "—", "—", "—", "—"])
            continue
        p = score.tp / (score.tp + score.fp) if (score.tp + score.fp) else None
        r = score.tp / (score.tp + score.fn) if (score.tp + score.fn) else None
        wd = (score.wrong_direction / score.direction_denominator
              if score.direction_denominator else None)
        fam = (score.families_hit / score.families_expected
               if score.families_expected else None)
        strata_rows.append([
            stratum, str(score.events),
            _pct(p, score.tp, score.tp + score.fp),
            _pct(r, score.tp, score.tp + score.fn),
            _pct(wd, score.wrong_direction, score.direction_denominator),
            _pct(fam, score.families_hit, score.families_expected)])
    out += ["## Per-stratum", "",
            "An aggregate number hides being excellent on crude and useless on policy "
            "(08_PHASE_7). Strata with zero scored events are shown as empty, not as "
            "zero.", "",
            _table(strata_rows, ["stratum", "events", "PRIMARY precision",
                                 "PRIMARY recall", "wrong-direction", "family recall"]),
            ""]

    if result.per_sector:
        sector_rows = []
        for sector, score in sorted(result.per_sector.items()):
            p = score.tp / (score.tp + score.fp) if (score.tp + score.fp) else None
            sector_rows.append([sector, str(score.tp), str(score.fp),
                                _pct(p, score.tp, score.tp + score.fp)])
        out += ["## Per-sector (published PRIMARY rows)", "",
                _table(sector_rows, ["sector", "true positives", "false positives",
                                     "precision"]), ""]

    out += ["## Null events", "",
            f"{result.null_events_with_primary} of {result.null_events_total} null "
            f"event(s) published at least one PRIMARY company. This is a hard-zero "
            f"gate in 08_PHASE_7 Task 7.3: any non-zero value here is an integrity "
            f"failure, not a quality shortfall.", ""]
    if result.null_event_violations:
        out += [f"- `{event_id}` published: {', '.join(tickers)}"
                for event_id, tickers in result.null_event_violations]
        out.append("")

    if result.false_positive_detail or result.false_negative_detail:
        out += ["## PRIMARY errors", ""]
        out += [f"- FALSE POSITIVE `{event_id}` / `{company}`"
                for event_id, company in result.false_positive_detail]
        out += [f"- MISSED `{event_id}` / `{company}`"
                for event_id, company in result.false_negative_detail]
        out.append("")
    if result.missed_families:
        out += ["## Missed ripple families", "",
                "Matching is a normalized string comparison against the company's "
                "stored sector/sub_sector, so a miss can be a taxonomy-wording gap "
                "rather than an engine gap. Read these individually.", ""]
        out += [f"- `{event_id}`: {family}" for event_id, family in result.missed_families]
        out.append("")
    if result.fabricated_detail:
        out += ["## Fabricated numerals", ""]
        out += [f"- `{event_id}` / {ticker}: {detail}"
                for event_id, ticker, detail in result.fabricated_detail]
        out.append("")
    if result.contradiction_detail:
        out += ["## Internal contradictions", ""]
        out += [f"- `{event_id}` / {ticker}: {detail}"
                for event_id, ticker, detail in result.contradiction_detail]
        out.append("")

    out += ["## How these numbers were produced", "",
            "`python backend/scripts/score_baseline.py` read the PERSISTED output of "
            "the production pipeline (alerts + alert_companies) for each labeled "
            "event's article and compared it with the adjudicated human labels. No "
            "LLM was called; no row was written. Every definition, and every honest "
            "limitation of them, is documented at the top of that file.", ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=REPO_ROOT, capture_output=True, text=True,
                              check=True).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _default_db_url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite:///./newsflo.db")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score the Gate Zero corpus and emit BASELINE.md.")
    parser.add_argument("--db", default=None,
                        help="SQLAlchemy URL (default: $DATABASE_URL, else sqlite:///./newsflo.db)")
    parser.add_argument("--out", default=str(REPO_ROOT / "BASELINE.md"),
                        help="where to write the baseline (default: repo-root BASELINE.md)")
    parser.add_argument("--commit", default=None, help="override the commit sha in the header")
    parser.add_argument("--date", default=None, help="override the date in the header")
    args = parser.parse_args(argv)

    engine = sa.create_engine(args.db or _default_db_url())
    try:
        with engine.connect() as conn:
            result = score_corpus(conn)
    except EmptyCorpusError as exc:
        print(f"REFUSING TO SCORE: {exc}", file=sys.stderr)
        return 2

    text = render_baseline(result, commit=args.commit or _git_commit(),
                           when=args.date or date.today().isoformat())
    Path(args.out).write_text(text, encoding="utf-8")

    print(text.split("## Corpus")[0].strip())
    print(f"\nwritten to {args.out}")
    if result.unscored_events:
        print(f"\nWARNING: {len(result.unscored_events)} labeled event(s) are UNSCORED "
              f"-- their articles have no stored analysis and are in no metric above:",
              file=sys.stderr)
        for event_id, ref in result.unscored_events:
            print(f"  UNSCORED {event_id} -> {ref}", file=sys.stderr)
        print("  Run the controlled analysis pass for those articles, then re-run this "
              "scorer. It never triggers an analysis itself.", file=sys.stderr)
    if result.under_labeled_events:
        print(f"\nWARNING: {len(result.under_labeled_events)} event(s) have fewer than "
              f"two labelers and were excluded.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
