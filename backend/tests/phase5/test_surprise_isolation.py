"""TASK 5.4 -- the surprise engine (Axis C), and its isolation from Axis A.

The phase file's mandatory tests:
  - ast scan: analysis/sensitivity and analysis/policy import nothing from surprise
  - mutating surprise fields leaves direction and materiality byte-identical
  - ALREADY_PRICED objection raised at WARN when forward_curve_implied is high

THE RULE THIS FILE EXISTS TO PIN: Axis C answers "is this actually news?" and
NOTHING ELSE. It ranks a feed, badges an item and raises a WARN objection. It
never touches direction or materiality -- and "never" here is an ast fact
about the import graph plus a byte-identity test, not a promise in a
docstring.
"""
import ast
from datetime import datetime, timedelta, timezone

import pytest

from tests.phase5.conftest import BACKEND, code_lines, imported_modules
from tests.phase5.helpers import impact_with_empirical

SURPRISE = BACKEND / "app" / "analysis" / "surprise"
SENSITIVITY = BACKEND / "app" / "analysis" / "sensitivity"
POLICY = BACKEND / "app" / "analysis" / "policy"
CORE = BACKEND / "app" / "core"

FIRST_SEEN = datetime(2226, 3, 3, 3, 0, tzinfo=timezone.utc)

EVENT_TEXT = ("Government raises the export duty on refined product cargoes "
              "shipped from western ports")
PRIOR_SAME = ("Government raises the export duty on refined product cargoes "
              "shipped from western ports")
PRIOR_OTHER = ("Monsoon rainfall ends fourteen percent above the long period "
               "average across peninsular districts")


# --- isolation, by ast ------------------------------------------------------

@pytest.mark.parametrize("package", [SENSITIVITY, POLICY, CORE],
                         ids=lambda p: p.name)
def test_axis_a_imports_nothing_from_the_surprise_package(package):
    for path in sorted(package.glob("*.py")):
        offenders = {m for m in imported_modules(path)
                     if m == "app.analysis.surprise"
                     or m.startswith("app.analysis.surprise.")}
        assert not offenders, (
            f"{path.relative_to(BACKEND)} imports {sorted(offenders)}: Axis C "
            "may never reach direction or materiality")


def test_the_surprise_package_imports_nothing_that_opens_a_socket():
    banned = ("yfinance", "requests", "httpx", "urllib", "urllib3", "socket",
              "aiohttp", "http", "ftplib", "smtplib")
    for path in sorted(SURPRISE.glob("*.py")):
        for module in imported_modules(path):
            assert module.split(".")[0] not in banned, f"{path.name}: {module}"


def test_the_surprise_package_names_no_model_and_computes_no_embedding():
    """Novelty is deterministic token overlap. An embedding would mean a
    model call, a network hop and a score nobody can reproduce."""
    banned = ("embedding", "claude", "gemini", "gpt-", "anthropic", "openai")
    for path in sorted(SURPRISE.glob("*.py")):
        for number, line in code_lines(path):
            for needle in banned:
                assert needle not in line.lower(), f"{path.name}:{number}"


def test_the_surprise_package_reads_no_clock():
    for path in sorted(SURPRISE.glob("*.py")):
        for number, line in code_lines(path):
            assert "now(" not in line and "utcnow" not in line, \
                f"{path.name}:{number} reads a clock"


# --- mutation cannot move Axis A -------------------------------------------

def test_mutating_surprise_leaves_direction_and_materiality_byte_identical():
    from app.analysis.surprise.engine import compute_surprise, serialize_surprise
    from app.core.reducer import serialize_company_impact

    before = serialize_company_impact(impact_with_empirical())

    for forward, novelty_source, sources in ((0.0, PRIOR_OTHER, 1),
                                             (0.95, PRIOR_SAME, 20)):
        surprise = compute_surprise(
            event_text=EVENT_TEXT, prior_texts=(novelty_source,),
            first_seen_at=FIRST_SEEN, published_at=FIRST_SEEN + timedelta(seconds=41),
            source_count=sources, forward_curve_implied=forward)
        assert serialize_surprise(surprise)          # the payload really changed
        after = serialize_company_impact(impact_with_empirical())
        assert after == before, (
            "a surprise value changed a fundamental record")


def test_no_reducer_input_can_carry_a_surprise_field():
    from app.core.gates import ImpactDraft

    assert not [f for f in ImpactDraft.__dataclass_fields__
                if "surprise" in f or "novelty" in f or "dissemination" in f]


# --- the computation --------------------------------------------------------

def test_novelty_is_zero_against_an_identical_prior_event():
    from app.analysis.surprise.novelty import novelty_score

    assert novelty_score(EVENT_TEXT, (PRIOR_SAME,)) == pytest.approx(0.0, abs=1e-12)


def test_novelty_is_one_against_a_wholly_unrelated_prior_event():
    from app.analysis.surprise.novelty import novelty_score

    assert novelty_score(EVENT_TEXT, (PRIOR_OTHER,)) == pytest.approx(1.0, abs=1e-9)


def test_novelty_with_no_prior_events_is_one():
    from app.analysis.surprise.novelty import novelty_score

    assert novelty_score(EVENT_TEXT, ()) == pytest.approx(1.0)


def test_novelty_is_deterministic():
    from app.analysis.surprise.novelty import novelty_score

    priors = (PRIOR_SAME, PRIOR_OTHER)
    assert novelty_score(EVENT_TEXT, priors) == novelty_score(EVENT_TEXT, priors)


@pytest.mark.parametrize("sources,minutes,expected", [
    (1, 0, "EARLY"), (4, 5, "SPREADING"), (20, 400, "SATURATED")])
def test_dissemination_stage_comes_from_source_count_and_elapsed_time(
        sources, minutes, expected):
    from app.analysis.surprise.engine import dissemination_stage

    assert dissemination_stage(source_count=sources,
                               minutes_since_first_seen=minutes) == expected


def test_consensus_gap_is_none_when_no_consensus_was_supplied():
    """There is no consensus feed in this repo. None means MISSING; it does
    not mean zero surprise."""
    from app.analysis.surprise.engine import compute_surprise

    surprise = compute_surprise(
        event_text=EVENT_TEXT, prior_texts=(), first_seen_at=FIRST_SEEN,
        published_at=FIRST_SEEN + timedelta(seconds=41))
    assert surprise.consensus_gap_sigma is None
    assert surprise.forward_curve_implied is None


def test_consensus_gap_is_computed_when_the_inputs_are_supplied():
    from app.analysis.surprise.engine import compute_surprise

    surprise = compute_surprise(
        event_text=EVENT_TEXT, prior_texts=(), first_seen_at=FIRST_SEEN,
        published_at=FIRST_SEEN, consensus_actual=9.0, consensus_expected=5.4,
        consensus_sigma=2.0)
    assert surprise.consensus_gap_sigma == pytest.approx(1.8, abs=1e-12)


def test_latency_is_measured_from_the_supplied_timestamps():
    from app.analysis.surprise.engine import compute_surprise

    surprise = compute_surprise(
        event_text=EVENT_TEXT, prior_texts=(), first_seen_at=FIRST_SEEN,
        published_at=FIRST_SEEN + timedelta(seconds=41))
    assert surprise.latency_ms_from_first_seen == 41_000
    assert surprise.first_seen_at == FIRST_SEEN


def test_information_value_is_a_config_weighted_composite_in_zero_one():
    from app.analysis.surprise.engine import compute_surprise

    fresh = compute_surprise(
        event_text=EVENT_TEXT, prior_texts=(PRIOR_OTHER,), first_seen_at=FIRST_SEEN,
        published_at=FIRST_SEEN, source_count=1, forward_curve_implied=0.0)
    stale = compute_surprise(
        event_text=EVENT_TEXT, prior_texts=(PRIOR_SAME,), first_seen_at=FIRST_SEEN,
        published_at=FIRST_SEEN + timedelta(hours=9), source_count=25,
        forward_curve_implied=0.95)
    assert 0.0 <= stale.information_value <= fresh.information_value <= 1.0


def test_the_slo_target_is_recorded_in_config_not_in_code():
    from app.analysis.surprise.config import load_surprise_config

    assert load_surprise_config().latency_p95_target_ms == 90_000


# --- the ALREADY_PRICED objection ------------------------------------------

def test_already_priced_is_raised_at_warn_when_the_forward_curve_is_high():
    from app.analysis.surprise.engine import already_priced_objection, compute_surprise

    surprise = compute_surprise(
        event_text=EVENT_TEXT, prior_texts=(), first_seen_at=FIRST_SEEN,
        published_at=FIRST_SEEN, forward_curve_implied=0.85)
    objection = already_priced_objection(surprise, objection_id="fixture:already-priced")
    assert objection is not None
    assert objection["type"] == "ALREADY_PRICED"
    assert objection["severity"] == "WARN"


def test_already_priced_is_not_raised_when_the_forward_curve_is_low():
    from app.analysis.surprise.engine import already_priced_objection, compute_surprise

    surprise = compute_surprise(
        event_text=EVENT_TEXT, prior_texts=(), first_seen_at=FIRST_SEEN,
        published_at=FIRST_SEEN, forward_curve_implied=0.05)
    assert already_priced_objection(surprise, objection_id="fixture:x") is None


def test_already_priced_is_not_raised_when_the_forward_curve_is_unknown():
    from app.analysis.surprise.engine import already_priced_objection, compute_surprise

    surprise = compute_surprise(
        event_text=EVENT_TEXT, prior_texts=(), first_seen_at=FIRST_SEEN,
        published_at=FIRST_SEEN)
    assert already_priced_objection(surprise, objection_id="fixture:x") is None


def test_a_warn_objection_does_not_change_the_tier():
    """The whole point of WARN: it is visible and it publishes anyway."""
    from app.core.signals import make_signal
    from tests.phase5.conftest import (
        FIXTURE_ANALYSIS_VERSION, FIXTURE_COMPANY_ID, FIXTURE_EVENT_ID, FIXTURE_NOW,
    )

    warn = make_signal(
        event_id=FIXTURE_EVENT_ID, company_id=FIXTURE_COMPANY_ID, stage="SURPRISE",
        kind="OBJECTION",
        payload={"objection_id": "fixture:already-priced", "type": "ALREADY_PRICED",
                 "severity": "WARN", "sustained": True, "_fixture": True},
        created_by="surprise:engine", analysis_version=FIXTURE_ANALYSIS_VERSION,
        created_at=FIXTURE_NOW)
    impact = impact_with_empirical(extra_signals=(warn,))
    assert impact.publication_tier == "PRIMARY"
    assert any(o["type"] == "ALREADY_PRICED" for o in impact.objections)


def test_the_badge_is_a_pure_function_of_the_dissemination_stage():
    from app.analysis.surprise.engine import already_widely_reported

    assert already_widely_reported("SATURATED") is True
    assert already_widely_reported("EARLY") is False
