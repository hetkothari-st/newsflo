"""TASK 7.1 tests -- the labeled corpus, and the refusal that stands in for it.

THE CORPUS DOES NOT EXIST. Session 0 built the schema, the labeling UI, the
importer and the V4 scorer; the labels themselves are human work and
`eval_event` holds zero rows (DATA_GAPS section 1). So this file does two
things and never a third:

  * the rules Task 7.1 states about a corpus (>= 300 events, every stratum,
    >= 50 nulls, >= 2 independent labelers, kappa reported, DISPUTED excluded
    from precision denominators) are asserted for real ONLY when a corpus is
    pointed at -- `NEWSFLO_EVAL_CORPUS_DB`. Otherwise they SKIP with that
    reason in the skip message. They never pass over zero events;
  * the EMPTY-CORPUS REFUSAL IS ITSELF TESTED, here, unconditionally. A
    harness that returns 0.0 or 1.0 over an empty corpus is worse than a
    harness that returns nothing, so refusing is the behaviour under test.

Everything structural about the report -- that it counts strata, that it
reports a single-labeler event instead of scoring it, that a DISPUTED pair
leaves the precision denominator -- is proven against a `_fixture`-marked
six-event corpus in a THROWAWAY in-memory database. That fixture corpus is
deliberately too small to satisfy any Task 7.1 rule: the report must say what
is missing, not paper over it.

This file NEVER generates a label (Task 7.1 DO NOT #1 and #2, and the master
context's fabrication guard applied to the one dataset that measures us).
"""
import inspect

import pytest
import sqlalchemy as sa

from tests.phase7.conftest import (
    CORPUS_DB_ENV, load_fixture, requires_corpus, seed_companies, seed_corpus,
    corpus_url,
)


@pytest.fixture()
def fixture_corpus(phase7_engine):
    raw = load_fixture("labeled_corpus.json")
    seed_companies(phase7_engine, raw["companies"])
    seed_corpus(phase7_engine, raw)
    return phase7_engine


# ---------------------------------------------------------------------------
# the refusal -- tested unconditionally, because it is the deployed behaviour
# ---------------------------------------------------------------------------

def test_an_empty_corpus_is_refused_rather_than_scored(phase7_engine):
    from eval.harness import HarnessRefusal, corpus_integrity

    with phase7_engine.connect() as conn:
        with pytest.raises(HarnessRefusal) as excinfo:
            corpus_integrity(conn)
    assert "EMPTY" in str(excinfo.value).upper()


def test_the_refusal_names_the_tooling_that_would_fill_the_corpus(phase7_engine):
    from eval.harness import HarnessRefusal, corpus_integrity

    with phase7_engine.connect() as conn:
        with pytest.raises(HarnessRefusal) as excinfo:
            corpus_integrity(conn)
    message = str(excinfo.value)
    assert "eval_ui" in message and "eval_import" in message, message
    assert "DATA_GAPS" in message


def test_loading_expectations_from_an_empty_corpus_is_refused(phase7_engine):
    from eval.harness import HarnessRefusal, load_expectations

    with phase7_engine.connect() as conn:
        with pytest.raises(HarnessRefusal):
            load_expectations(conn)


def test_events_without_labels_are_refused_too(phase7_engine):
    """Events loaded, nobody labeled them. A precision over zero labels is
    not a small number, it is no number."""
    from app.eval import store
    from eval.harness import HarnessRefusal, corpus_integrity

    with phase7_engine.begin() as conn:
        store.upsert_event(conn, event_id="fx-empty", stratum="commodity",
                           article_ref="9000001")
    with phase7_engine.connect() as conn:
        with pytest.raises(HarnessRefusal) as excinfo:
            corpus_integrity(conn)
    assert "label" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# structure, proven on the fixture corpus
# ---------------------------------------------------------------------------

def test_the_report_counts_events_per_stratum(fixture_corpus):
    from eval.harness import corpus_integrity

    with fixture_corpus.connect() as conn:
        report = corpus_integrity(conn)
    assert report.events_total == 6
    assert report.per_stratum["null_event"] == 2
    assert report.per_stratum["commodity"] == 1
    assert report.null_events == 2


def test_the_report_names_the_strata_that_are_missing(fixture_corpus):
    from eval.harness import corpus_integrity

    with fixture_corpus.connect() as conn:
        report = corpus_integrity(conn)
    assert "macro_data" in report.strata_missing
    assert "geopolitical" in report.strata_missing
    assert "commodity" not in report.strata_missing


def test_the_fixture_corpus_fails_every_size_requirement_and_says_so(fixture_corpus):
    """The fixture is six events. The report must NOT be satisfiable by a
    corpus that cannot satisfy Task 7.1 -- if this ever passes, the size
    rules have been quietly dropped."""
    from eval.harness import corpus_integrity

    with fixture_corpus.connect() as conn:
        report = corpus_integrity(conn)
    unmet = {r.name for r in report.requirements if not r.met}
    assert "event_count" in unmet
    assert "null_event_count" in unmet
    assert "every_stratum_represented" in unmet
    assert "two_labelers_per_event" in unmet
    assert report.meets_requirements is False


def test_a_single_labeler_event_is_reported_and_excluded(fixture_corpus):
    """Task 7.1 DO NOT #2. One labeler is an opinion, not a label."""
    from eval.harness import corpus_integrity, load_expectations

    with fixture_corpus.connect() as conn:
        report = corpus_integrity(conn)
        expectations = load_expectations(conn)
    assert ("fx-earnings-1", 1) in report.under_labeled
    scored = {e.event_id for e in expectations}
    assert "fx-earnings-1" not in scored, (
        "a single-labeler event reached the scored set")
    assert "fx-commodity-1" in scored


def test_a_disputed_pair_is_excluded_from_the_precision_denominator(fixture_corpus):
    from eval.harness import load_expectations

    with fixture_corpus.connect() as conn:
        expectations = {e.event_id: e for e in load_expectations(conn)}
    policy = expectations["fx-policy-1"]
    assert "FIXD" in policy.disputed
    assert "FIXD" not in policy.expected_tiers, (
        "a DISPUTED pair kept an expected tier -- it would score as a hit or "
        "a miss, and it is neither")


def test_an_unadjudicated_disagreement_is_also_excluded(phase7_engine):
    """Two labelers, different tiers, nobody adjudicated. That is ambiguity
    the corpus has not resolved, and scoring it would resolve it by coin
    toss."""
    from app.eval import store
    from eval.harness import load_expectations

    with phase7_engine.begin() as conn:
        store.upsert_event(conn, event_id="fx-split", stratum="commodity",
                           article_ref="9000009")
        store.upsert_label(conn, event_id="fx-split", company_ref="FIXA",
                           labeler="a", expected_tier="PRIMARY")
        store.upsert_label(conn, event_id="fx-split", company_ref="FIXA",
                           labeler="b", expected_tier="ABSENT")
    with phase7_engine.connect() as conn:
        expectation = {e.event_id: e for e in load_expectations(conn)}["fx-split"]
    assert "FIXA" not in expectation.expected_tiers
    assert "FIXA" in expectation.unresolved


def test_kappa_is_computed_and_reported_on_the_fixture_corpus(fixture_corpus):
    from eval.harness import corpus_integrity

    with fixture_corpus.connect() as conn:
        report = corpus_integrity(conn)
    assert report.kappa_pairs > 0
    assert report.kappa is None or -1.0 <= report.kappa <= 1.0


def test_kappa_is_none_rather_than_one_when_it_is_undefined(phase7_engine):
    """Two labelers, one company, perfect agreement: p_e == 1 and kappa
    carries no information. Session 0's rule -- None, never 1.0."""
    from app.eval import store
    from eval.harness import corpus_integrity

    with phase7_engine.begin() as conn:
        store.upsert_event(conn, event_id="fx-flat", stratum="commodity",
                           article_ref="9000010")
        for who in ("a", "b"):
            store.upsert_label(conn, event_id="fx-flat", company_ref="FIXA",
                               labeler=who, expected_tier="PRIMARY")
    with phase7_engine.connect() as conn:
        report = corpus_integrity(conn)
    assert report.kappa is None
    assert report.kappa_note


def test_the_harness_does_not_reimplement_cohens_kappa():
    """Session 0 owns the statistic. Two implementations of kappa in one repo
    is two answers to one question."""
    import eval.harness as harness
    from scripts.score_baseline import cohens_kappa

    assert harness.cohens_kappa is cohens_kappa
    source = inspect.getsource(harness)
    assert "def cohens_kappa" not in source


def test_session_zero_schema_is_untouched():
    """The Phase 7 harness READS Session 0's tables and never widens them."""
    from app.eval.schema import (
        EXPECTED_TIERS, RESOLUTIONS, STRATA, eval_event, eval_label,
    )

    assert STRATA == ("commodity", "policy_regulatory", "company_action",
                      "macro_data", "geopolitical", "earnings", "null_event")
    assert EXPECTED_TIERS == ("PRIMARY", "SECONDARY_RIPPLE", "MACRO_CONTEXT", "ABSENT")
    assert RESOLUTIONS == ("LABELER_A", "LABELER_B", "MERGED", "DISPUTED")
    assert [c.name for c in eval_event.columns] == [
        "event_id", "stratum", "article_ref", "notes"]
    assert [c.name for c in eval_label.columns] == [
        "event_id", "company_ref", "labeler", "expected_tier", "expected_direction",
        "expected_mechanism", "expected_materiality", "label", "rationale",
        "labeled_at"]


def test_nothing_in_the_harness_writes_a_label():
    """Task 7.1's first two DO NOTs, structurally: the harness has no write
    path into the corpus at all."""
    from pathlib import Path

    from tests.phase7.conftest import BACKEND, code_lines, package_sources

    banned = ("upsert_label", "upsert_event", "upsert_adjudication",
              "upsert_event_label", "INSERT INTO eval_", "insert(eval_")
    offenders = []
    for path in package_sources(Path(BACKEND) / "eval"):
        for number, line in code_lines(path):
            for token in banned:
                if token in line:
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, offenders


# ---------------------------------------------------------------------------
# the real rules -- skipped, loudly, until a corpus exists
# ---------------------------------------------------------------------------

@pytest.fixture()
def real_corpus():
    engine = sa.create_engine(corpus_url())
    try:
        yield engine
    finally:
        engine.dispose()


@requires_corpus
def test_the_corpus_holds_at_least_three_hundred_events(real_corpus):
    from eval.harness import REQUIRED_EVENTS, corpus_integrity

    with real_corpus.connect() as conn:
        report = corpus_integrity(conn)
    assert report.events_total >= REQUIRED_EVENTS


@requires_corpus
def test_every_stratum_is_represented(real_corpus):
    from eval.harness import corpus_integrity

    with real_corpus.connect() as conn:
        report = corpus_integrity(conn)
    assert report.strata_missing == ()


@requires_corpus
def test_at_least_fifty_null_events(real_corpus):
    from eval.harness import REQUIRED_NULL_EVENTS, corpus_integrity

    with real_corpus.connect() as conn:
        report = corpus_integrity(conn)
    assert report.null_events >= REQUIRED_NULL_EVENTS


@requires_corpus
def test_every_event_has_at_least_two_independent_labelers(real_corpus):
    from eval.harness import corpus_integrity

    with real_corpus.connect() as conn:
        report = corpus_integrity(conn)
    assert report.under_labeled == ()


@requires_corpus
def test_cohens_kappa_is_computed_and_reported(real_corpus):
    from eval.harness import corpus_integrity

    with real_corpus.connect() as conn:
        report = corpus_integrity(conn)
    assert report.kappa is not None, report.kappa_note
    assert report.kappa_pairs > 0


@requires_corpus
def test_disputed_pairs_are_excluded_from_precision_denominators(real_corpus):
    from eval.harness import load_expectations

    with real_corpus.connect() as conn:
        for expectation in load_expectations(conn):
            assert not (expectation.disputed & set(expectation.expected_tiers))


def test_the_skip_reason_names_the_environment_variable():
    """The skip must be readable as an instruction, not as a mystery."""
    from tests.phase7.conftest import SKIP_REASON

    assert CORPUS_DB_ENV in SKIP_REASON
    assert "DATA_GAPS" in SKIP_REASON
