"""TASK 7.1's null slice -- the only measurement of whether the system can
say nothing.

"Do not drop the null-event slice because it is boring to build. It is the
most important stratum." The 50-event corpus slice is human work and does not
exist (DATA_GAPS section 1), so the corpus-wide assertion is SKIPPED with
that reason. What runs today is the same assertion over four `_fixture`
null events, each failing for a DIFFERENT structural reason, plus the
non-vacuity control that proves the same machinery DOES publish PRIMARY when
a company earns it.

A null-event test that passes because nothing can publish is not a test. The
control is therefore mandatory and it runs first in this file's logic.
"""
import pytest

from tests.phase0 import fixtures as phase0
from tests.phase7.conftest import load_fixture, requires_corpus, corpus_url


@pytest.fixture()
def null_bundles():
    from eval.harness import StageBundle

    return [StageBundle.from_dict(raw)
            for raw in load_fixture("null_events.json")["bundles"]]


# ---------------------------------------------------------------------------
# the control -- without it, everything below is vacuous
# ---------------------------------------------------------------------------

def test_the_same_machinery_publishes_primary_when_a_company_earns_it():
    """Phase 0's crude fixture reaches PRIMARY through the deployed reducer
    and the deployed gate. If this ever fails, every zero below means
    'the pipeline is broken', not 'the system abstained'."""
    from eval.harness import run_v5_path, StageBundle

    bundle = StageBundle.from_dict(phase0.load_raw())
    output = run_v5_path(bundle)
    assert output.primary_count == 1, output.rejections


# ---------------------------------------------------------------------------
# zero PRIMARY on every null fixture
# ---------------------------------------------------------------------------

def test_zero_primary_across_every_null_fixture_event(null_bundles):
    from eval.harness import run_v5_path

    for bundle in null_bundles:
        output = run_v5_path(bundle)
        assert output.primary_count == 0, (
            f"{bundle.event_id} published {output.primary_count} PRIMARY")


def test_every_null_fixture_fails_for_a_different_named_reason(null_bundles):
    """Four events, four refusals, ONE EACH.

    Pinned per bundle rather than as a set union: a union is satisfied by one
    event that happens to carry all four reasons, which would let three of
    the fixtures silently degenerate into copies of the fourth and leave the
    null slice measuring one guard instead of the system.
    """
    from eval.harness import run_v5_path

    by_event = {}
    for bundle in null_bundles:
        output = run_v5_path(bundle)
        reasons = {r.rejection_reason for r in output.records}
        assert len(reasons) == 1, (bundle.event_id, reasons)
        by_event[bundle.event_id] = next(iter(reasons))

    assert by_event == {
        "fixture:null-1-immaterial": "NO_MATERIAL_IMPACT",
        "fixture:null-2-ambiguous-entity": "ENTITY_AMBIGUOUS",
        "fixture:null-3-unsizeable-shock": "MACRO_CONTEXT_HAS_NO_COMPANIES",
        "fixture:null-4-unbound-claim": "UNBOUND_CLAIM",
    }
    assert len(set(by_event.values())) == len(by_event)


def test_a_null_event_publishes_no_section_at_all(null_bundles):
    from eval.harness import run_v5_path

    for bundle in null_bundles:
        output = run_v5_path(bundle)
        assert output.sections == ()


def test_abstention_precision_over_the_null_fixtures_is_one(null_bundles):
    from eval.harness import run_v5_path
    from eval.metrics import abstention_precision, null_event_primary_false_positives

    events = [{"stratum": "null_event",
               "primary_count": run_v5_path(b).primary_count}
              for b in null_bundles]
    rate = abstention_precision(events)
    assert (rate.numerator, rate.denominator) == (4, 4)
    assert null_event_primary_false_positives(events) == 0


def test_the_hard_zero_gate_reads_the_null_fixture_result(null_bundles):
    """End to end: null fixtures -> metric -> the hard-zero shipping gate."""
    from eval.harness import run_v5_path
    from eval.metrics import null_event_primary_false_positives
    from eval.shipping_gates import evaluate_gates

    events = [{"stratum": "null_event",
               "primary_count": run_v5_path(b).primary_count}
              for b in null_bundles]
    report = evaluate_gates(
        {"primary_false_positives_on_null_events":
             null_event_primary_false_positives(events)},
        baseline=None)
    outcome = {o.name: o
               for o in report.outcomes}["primary_false_positives_on_null_events"]
    assert outcome.status == "PASS"
    assert report.hard_violations == ()


# ---------------------------------------------------------------------------
# the zero-PRIMARY render (Phase 6's renderer, driven by the harness)
# ---------------------------------------------------------------------------

def test_the_system_renders_the_zero_primary_state(null_bundles):
    from eval.harness import run_v5_path

    output = run_v5_path(null_bundles[0])
    state = output.zero_primary_state
    assert state["zero_primary"] is True
    assert state["primary_count"] == 0
    assert state["rejected_count"] >= 1
    text = output.render_zero_primary()
    assert "NO PRIMARY IMPACT IDENTIFIED" in text
    assert str(state["rejected_count"]) in text


def test_the_zero_primary_render_is_not_an_empty_page(null_bundles):
    from eval.harness import run_v5_path

    text = run_v5_path(null_bundles[1]).render_zero_primary()
    assert len(text.strip()) > 40
    assert "rejected" in text.lower() or "candidate" in text.lower()


def test_a_publishing_event_does_not_render_the_zero_primary_state():
    from eval.harness import run_v5_path, StageBundle

    output = run_v5_path(StageBundle.from_dict(phase0.load_raw()))
    assert output.zero_primary_state["zero_primary"] is False


# ---------------------------------------------------------------------------
# the corpus slice -- skipped, loudly
# ---------------------------------------------------------------------------

@requires_corpus
def test_zero_primary_across_the_fifty_corpus_null_events():
    import sqlalchemy as sa

    from eval.harness import load_expectations, stored_event_output

    engine = sa.create_engine(corpus_url())
    try:
        with engine.connect() as conn:
            nulls = [e for e in load_expectations(conn)
                     if e.stratum == "null_event"]
            assert len(nulls) >= 50
            for expectation in nulls:
                output = stored_event_output(conn, expectation)
                assert output.primary_count == 0, expectation.event_id
    finally:
        engine.dispose()


def test_the_null_fixtures_are_marked_as_fixtures():
    raw = load_fixture("null_events.json")
    for bundle in raw["bundles"]:
        assert bundle["_fixture"] is True
        for signal in bundle["signals"]:
            assert signal["_fixture"] is True
            assert signal["payload"]["_fixture"] is True
