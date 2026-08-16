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
    reported loudly. Silence is not agreement. DEVIATION, declared: leaving
    a row blank in the adjudication form writes NO eval_adjudication row at
    all, rather than writing an explicit "unresolved" state. The two are
    indistinguishable in the table, so the scorer treats a missing row over
    a disagreement as unresolved and counts it into the ambiguity line
    alongside DISPUTED. The alternative -- materializing a row for every
    unvisited pair -- would fill the table with rows no human ever saw.
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

COMPANY REFERENCE RESOLUTION. A labeler types a bare symbol (RELIANCE);
the universe stores an exchange-suffixed ticker (RELIANCE.NS) for ~90% of
its rows. Both sides are reduced to a canonical ticker
(app.eval.store.canonical_company_ref: upper-case, known exchange suffix
stripped), then unresolved references fall back through `company_aliases`
(so RIL and "Reliance Industries" resolve too). A reference that still
matches nothing is NOT scored: it goes to BASELINE.md's UNMATCHED COMPANY
REFERENCES section, because it is either a typo or a universe coverage gap,
and both are fixable facts rather than engine errors. Two listings of the
same company (.NS and .BO) collapse to one canonical company, so publishing
both counts once.

RIPPLE FAMILY RECALL = of the adjudicated expected families, the fraction
with at least one published SECONDARY-tier company classified into the
family. Families have no per-company adjudication row (they are
event-level), so "adjudicated" here means the INTERSECTION of the two
labelers' family sets; the symmetric difference is reported as disputed
families, and an event where only ONE labeler filed families is excluded
and listed. A family name is translated to taxonomy slugs first
(config/eval_family_map.yaml, then a direct match against the universe's own
DISTINCT sub_sector/sector vocabulary) -- against the live universe, whose
sub_sectors are slugs like `refining_marketing`, raw string comparison
matched almost nothing and the metric measured our vocabulary rather than
the engine. LIMITATION, stated plainly: a family term that translates to
NOTHING is excluded from the denominator and reported under MISMATCHED
FAMILIES rather than scored as a miss, so family recall is computed only
over families we can interpret. The count of what we could not interpret is
printed next to it; if that list is long, the metric is weak and says so.

FALSE PRIMARY ON NULL EVENTS = the number of stratum=null_event events
with at least one published PRIMARY company, reported as "n of N" with the
offending events named. A hard-zero gate later (08_PHASE_7 Task 7.3).

EMPTY-CORPUS SEMANTICS (declared, so it cannot be quietly loosened): the
scorer refuses only when there are ZERO events, or zero labels of BOTH
kinds (no `eval_label` row and no `eval_event_label` row anywhere). A
corpus of null events whose correct labels name no company is NOT empty --
it has `eval_event_label` rows, which are the record that a labeler looked
at the event and expected nothing. That is why the labeling UI always
writes one, even when every field is blank. A per-event blank on a
NON-null event is ambiguous and is reported (AMBIGUOUS EMPTY LABELS), never
read as a deliberate empty set.

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
from app.eval.families import (  # noqa: E402
    load_family_map,
    normalize_family,
    resolve_family,
)
from app.eval.schema import STRATA  # noqa: E402

# The published-tier vocabulary. Held as literals rather than imported from
# app.analysis.impact_graph.publication_gate -- this script must not import
# app.analysis at all (see the module docstring) -- and pinned to that
# module by test_secondary_tier_spellings_track_the_publication_gate so the
# copy cannot rot. "secondary_deep_dive"/"secondary" are dead spellings that
# are still READABLE on rows written before migration 0008's rewrite.
PRIMARY_TIER = "primary"
SECONDARY_TIERS = ("secondary_ripple", "secondary_deep_dive", "secondary")

DIRECTIONAL = ("bullish", "bearish")
_OPPOSITE = {"bullish": "bearish", "bearish": "bullish"}

_NUMERAL_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


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


def numerals(text: str | None) -> list[str]:
    """Normalized numeral TOKENS in ``text``.

    Normalization makes two spellings of the same number one token:
    commas dropped (``1,370`` -> ``1370``), trailing decimal zeros dropped
    (``3.50`` -> ``3.5``, ``100.0`` -> ``100``), leading zeros dropped
    (``07`` -> ``7``). A ``%`` or currency mark next to the numeral is not
    part of the token -- it never was under the regex.
    """
    out = []
    for match in _NUMERAL_RE.finditer(text or ""):
        token = match.group(0).replace(",", "")
        if "." in token:
            token = token.rstrip("0").rstrip(".")
        integer, dot, fraction = token.partition(".")
        integer = integer.lstrip("0") or "0"
        out.append(integer + dot + fraction)
    return out


def fabricated_numerals_in(text: str | None, source: str) -> list[str]:
    """Numerals in ``text`` that are not among ``source``'s numerals.

    SET MEMBERSHIP, not substring containment. Containment was silently
    wrong in both directions: ``37`` "appeared in" ``1370`` and ``3.5`` in
    ``13.55``, so a fabricated figure passed the audit whenever some longer
    unrelated number happened to contain its digits. This feeds a
    hard-zero shipping gate (08_PHASE_7 Task 7.3), so a false negative here
    is the most expensive kind of bug in the harness.
    """
    known = set(numerals(source))
    return [n for n in numerals(text) if n not in known]


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
    mismatched_families: list[tuple[str, str]] = field(default_factory=list)
    single_labeler_families: list[str] = field(default_factory=list)

    unmatched_refs: list[tuple[str, str, str]] = field(default_factory=list)
    label_self_conflicts: list[tuple[str, str, str]] = field(default_factory=list)
    ambiguous_empty_labels: list[tuple[str, str]] = field(default_factory=list)

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
    index = store.load_company_index(conn)
    for event in store.all_events(conn):
        labelers = store.labelers_for_event(conn, event["event_id"])
        if len(labelers) != 2:
            skipped += 1
            continue
        labels = store.labels_for_event(conn, event["event_id"])
        by_company: dict[str, dict[str, str]] = defaultdict(dict)
        for row in labels:
            # Resolved key, so "RIL" from one labeler and "RELIANCE" from
            # the other are one company and not a spurious disagreement. A
            # reference that resolves to nothing keeps its own spelling --
            # agreement on an unresolvable ref is still agreement.
            resolved, _reason = store.resolve_ref(index, row["company_ref"])
            key = resolved or store.canonical_company_ref(row["company_ref"])
            by_company[key][row["labeler"]] = row["expected_tier"]
        for company in sorted(by_company):
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
    index = store.load_company_index(conn)
    vocabulary = store.load_family_vocabulary(conn)
    family_map = load_family_map()

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

        # M1: a NON-null event where a labeler named no company at all is
        # ambiguous -- a deliberate "nothing material here" and an
        # unfinished label look identical in the data. Reported, never
        # silently read as an empty expected set.
        if stratum != "null_event":
            named = {row["labeler"] for row in labels}
            for who in labelers:
                if who not in named:
                    result.ambiguous_empty_labels.append((event_id, who))

        # C1: a labeler types a bare symbol (RELIANCE); the universe stores
        # RELIANCE.NS. Resolve both sides to one canonical ticker, falling
        # back through company_aliases, and report anything that resolves to
        # no company instead of scoring it as a miss.
        by_company: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self_conflicted: set[str] = set()
        for row in labels:
            resolved, reason = store.resolve_ref(index, row["company_ref"])
            if resolved is None:
                result.unmatched_refs.append((event_id, row["company_ref"], reason))
                continue
            existing = by_company[resolved].get(row["labeler"])
            if existing and existing["expected_tier"] != row["expected_tier"]:
                # One labeler, two references to the same company, two
                # different tiers. Not resolvable here; excluded and named.
                result.label_self_conflicts.append((event_id, resolved, row["labeler"]))
                self_conflicted.add(resolved)
                continue
            by_company[resolved][row["labeler"]] = row

        adjudications = {
            (store.resolve_ref(index, ref)[0] or store.canonical_company_ref(ref)): value
            for ref, value in adjudications.items()}

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

        universe = (set(by_company) | set(published)) - self_conflicted
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
        event_level = store.event_labels_for_event(conn, event_id)
        family_sets = [set(normalize_family(f) for f in row["ripple_families"])
                       for row in event_level if row["labeler"] in labelers]
        original: dict[str, str] = {}
        for row in event_level:
            for fam in row["ripple_families"]:
                original.setdefault(normalize_family(fam), fam)
        # M3: families need BOTH labelers to be adjudicable by intersection.
        # One filer -> excluded and listed, never scored against the engine.
        if len([row for row in event_level
                if row["labeler"] in labelers and row["ripple_families"]]) == 1:
            result.single_labeler_families.append(event_id)
        if len(family_sets) >= 2:
            agreed = set.intersection(*family_sets)
            disputed = set.union(*family_sets) - agreed
            result.ripple_families_disputed += len(disputed)
            for fam in sorted(agreed):
                # I1: translate analyst wording into taxonomy slugs before
                # comparing. A term we cannot translate at all is REPORTED,
                # not counted as a miss -- see app/eval/families.py.
                targets, how = resolve_family(fam, vocabulary, family_map)
                if how == "unknown":
                    result.mismatched_families.append(
                        (event_id, original.get(fam, fam)))
                    continue
                result.ripple_families_expected += 1
                bucket.families_expected += 1
                hit = any(
                    normalize_family(row.get("sub_sector")) in targets
                    or normalize_family(row.get("sector")) in targets
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


def _role_legend(result: BaselineResult) -> str:
    """I4: LABELER_A / LABELER_B are positional (the event's labelers sorted
    by name). Printing the legend is what makes an adjudication decision
    readable six months later."""
    if not result.labeler_roles:
        return "none recorded"
    pairs = {roles for roles in result.labeler_roles.values()}
    if len(pairs) == 1:
        a, b = next(iter(pairs))
        return f"**A = {a}** · **B = {b}** (all scored events)"
    parts = [f"`{event}`: A = {roles[0]} · B = {roles[1]}"
             for event, roles in sorted(result.labeler_roles.items())]
    return "per event — " + "; ".join(parts)


def render_baseline(result: BaselineResult, *, commit: str, when: str) -> str:
    precision = result.primary_precision
    recall = result.primary_recall
    out = [
        f"NEWSFLO BASELINE — {when} — commit {commit}",
        "",]
    if result.rows_scored and result.rows_tier_derived == result.rows_scored:
        # I5: every single row's tier was inferred from legacy fields. The
        # numbers below are about a corpus the strict gate never touched,
        # and that must not be a parenthetical.
        out += [
            "> ⚠ **ALL tiers derived from legacy fields.** Not one scored row carried a",
            f"> gate-authorized `display_tier`: all {result.rows_scored} were read off",
            "> `causal_distance`/`impact_level`. These numbers describe the PRE-V4-strict",
            "> pipeline. V4 strict rows are absent from this corpus entirely — re-run the",
            "> analysis with the strict gate enabled before treating this as its baseline.",
            "",
        ]
    out += [
        "```",
        f"PRIMARY precision            {_pct(precision, result.primary_true_positives, result.primary_true_positives + result.primary_false_positives)}",
        f"PRIMARY recall               {_pct(recall, result.primary_true_positives, result.primary_true_positives + result.primary_false_negatives)}",
        f"Wrong-direction rate         {_pct(result.wrong_direction_rate, result.wrong_direction, result.wrong_direction_denominator)}",
        f"Ripple family recall         {_pct(result.ripple_family_recall, result.ripple_families_hit, result.ripple_families_expected)}"
        + (f"   [{len(result.mismatched_families)} family name(s) not interpretable "
           f"and EXCLUDED -- see MISMATCHED FAMILIES]"
           if result.mismatched_families else ""),
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
        f"- ambiguity: {result.disputed_pairs} DISPUTED pair(s) and "
        f"{len(result.unadjudicated_pairs)} unadjudicated disagreement(s), all "
        f"excluded from every precision denominator and counted here instead"
        + (f"; {len(result.unresolvable_merged)} MERGED-but-divergent pair(s)"
           if result.unresolvable_merged else ""),
        f"- labeler roles: {_role_legend(result)}",
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
        out += ["## UNADJUDICATED DISAGREEMENTS (excluded from all denominators)", ""]
        out += [f"- `{event_id}` / `{company}` — labelers disagree, no adjudication"
                for event_id, company in result.unadjudicated_pairs]
        out += [f"- `{event_id}` / `{company}` — MERGED but the labelers' tiers differ"
                for event_id, company in result.unresolvable_merged]
        out.append("")
    if result.unmatched_refs:
        out += [
            "## UNMATCHED COMPANY REFERENCES — action required",
            "",
            "These labeler-typed references resolved to no company, through neither "
            "the canonical ticker (exchange suffix stripped) nor `company_aliases`. "
            "Each is either a typo to correct in the label, or a genuine coverage gap "
            "in the universe. Both must be resolved before the numbers above are "
            "trustworthy: every one of these is an expectation nobody scored.",
            "",
        ]
        out += [f"- `{event_id}`: `{ref}` — {reason}"
                for event_id, ref, reason in result.unmatched_refs]
        out.append("")
    if result.label_self_conflicts:
        out += ["## SELF-CONFLICTING LABELS (one labeler, one company, two tiers)", ""]
        out += [f"- `{event_id}` / `{company}` — labeler {who}"
                for event_id, company, who in result.label_self_conflicts]
        out.append("")
    if result.ambiguous_empty_labels:
        out += [
            "## AMBIGUOUS EMPTY LABELS",
            "",
            "A labeler filed a label for a NON-null event but named no company at all. "
            "A deliberate \"nothing material here\" and an unfinished label are "
            "indistinguishable in the data, so these are reported rather than read as "
            "an empty expected set. Confirm each one.",
            "",
        ]
        out += [f"- `{event_id}` — labeler {who} named no company"
                for event_id, who in result.ambiguous_empty_labels]
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
                "The family was translated to one or more taxonomy slugs "
                "(config/eval_family_map.yaml, or a direct vocabulary match) and no "
                "published secondary-tier company carried them. These are engine "
                "misses, not vocabulary misses.", ""]
        out += [f"- `{event_id}`: {family}" for event_id, family in result.missed_families]
        out.append("")
    if result.mismatched_families:
        out += [
            "## MISMATCHED FAMILIES — vocabulary gap, NOT scored",
            "",
            "These family names could not be translated into the universe's taxonomy: "
            "they are neither in `config/eval_family_map.yaml` nor close to any "
            "`sub_sector`/`sector` slug the universe holds. They are EXCLUDED from the "
            "family-recall denominator — scoring them zero would blame the engine for "
            "wording we cannot interpret. Add each to the map (or correct the label), "
            "then re-run.",
            "",
        ]
        out += [f"- `{event_id}`: {family}"
                for event_id, family in result.mismatched_families]
        out.append("")
    if result.single_labeler_families:
        out += [
            "## Ripple families filed by only one labeler (excluded)",
            "",
            "Families are adjudicated by intersection, which needs two filers. These "
            "events had one, so their families are in no denominator.",
            "",
        ]
        out += [f"- `{event_id}`" for event_id in result.single_labeler_families]
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

    url = args.db or _default_db_url()
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            result = score_corpus(conn)
    except EmptyCorpusError as exc:
        print(f"REFUSING TO SCORE: {exc}", file=sys.stderr)
        return 2
    except sa.exc.OperationalError as exc:
        # I3: the overwhelmingly likely cause is a database that has not had
        # migration 0010 applied. Say so, with the command, instead of a
        # SQLAlchemy traceback.
        if "eval_" in str(exc) or "no such table" in str(exc).lower():
            print(f"REFUSING TO SCORE: the eval tables are absent from {url} "
                  f"({exc.orig}).\n"
                  f"Run:  cd backend && .venv/Scripts/python.exe -m alembic upgrade head\n"
                  f"(migration 0010 creates eval_event / eval_label / "
                  f"eval_event_label / eval_adjudication). No baseline was written.",
                  file=sys.stderr)
            return 2
        raise

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
