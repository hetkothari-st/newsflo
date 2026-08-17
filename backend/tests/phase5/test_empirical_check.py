"""TASK 5.2 -- the check, and conflict handling.

The phase file's mandatory tests:
  - n < 10 => NO_DATA;  p > 0.10 => WEAK
  - opposite sign with significance => CONFLICT
  - CONFLICT caps tier at SECONDARY, does not reject
  - REGIME_CHANGED annotation restores PRIMARY eligibility with expiry

THE RULE THIS FILE EXISTS TO PIN (§10.3, and the phase file's own DO NOT):
**conflict is not auto-reject**. Empirical history can be dominated by a
regime that no longer applies, and the market may simply have been wrong --
that is the alpha the product claims. So a conflict downgrades and queues a
human. Anything that rejects here is a bug, not a stricter policy.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from tests.phase5.conftest import (
    BACKEND, FIXTURE_COMPANY_ID, FIXTURE_EVENT_ID, FIXTURE_NOW, FIXTURE_TODAY,
)
from tests.phase5.helpers import impact_with_empirical, transmission_row


# --- the four outcomes ------------------------------------------------------

class _Impact:
    """The minimal shape `empirical_check` reads: a headline direction."""

    def __init__(self, net_effect):
        self.net_effect = net_effect


@pytest.mark.parametrize("n_events", [0, 1, 9])
def test_fewer_than_ten_events_is_no_data(n_events):
    from app.analysis.empirical.check import empirical_check

    assert empirical_check(_Impact("NEGATIVE"),
                           transmission_row(n_events=n_events)) == "NO_DATA"


def test_a_missing_row_is_no_data():
    from app.analysis.empirical.check import empirical_check

    assert empirical_check(_Impact("NEGATIVE"), None) == "NO_DATA"


def test_an_insignificant_p_value_is_weak():
    from app.analysis.empirical.check import empirical_check

    assert empirical_check(_Impact("NEGATIVE"),
                           transmission_row(p_value=0.11)) == "WEAK"


def test_the_same_sign_with_significance_is_agree():
    from app.analysis.empirical.check import empirical_check

    assert empirical_check(_Impact("NEGATIVE"),
                           transmission_row(median_car=-0.014, p_value=0.02)) == "AGREE"


def test_the_opposite_sign_with_significance_is_conflict():
    from app.analysis.empirical.check import empirical_check

    assert empirical_check(_Impact("POSITIVE"),
                           transmission_row(median_car=-0.014, p_value=0.02)) == "CONFLICT"


@pytest.mark.parametrize("net_effect", ["MIXED", "UNCERTAIN", "NO_MATERIAL_IMPACT"])
def test_a_record_that_claims_no_direction_is_never_in_conflict(net_effect):
    """There is no directional claim to falsify. Calling that a CONFLICT
    would manufacture a disagreement with a claim nobody made."""
    from app.analysis.empirical.check import empirical_check

    assert empirical_check(_Impact(net_effect),
                           transmission_row(median_car=-0.014, p_value=0.02)) == "NO_DATA"


def test_a_median_of_exactly_zero_has_no_sign_to_agree_with():
    from app.analysis.empirical.check import empirical_check

    assert empirical_check(_Impact("POSITIVE"),
                           transmission_row(median_car=0.0, p_value=0.01)) == "NO_DATA"


def test_the_objection_taxonomy_is_closed_at_the_signal_bus():
    """REVIEW ROUND 1 (m-8). §12.1's taxonomy is CONTROLLED. A free-text type
    is how a stage starts inventing criticisms nobody can aggregate -- and the
    gate's per-type exemption list is only trustworthy if the types it names
    are the types that can exist."""
    from app.core.signals import OBJECTION_TYPES, SignalPayloadError, validate_payload

    assert "EMPIRICAL_CONFLICT" in OBJECTION_TYPES
    assert "ALREADY_PRICED" in OBJECTION_TYPES
    assert {"ENTITY_WRONG", "MECHANISM_INVALID", "EXPOSURE_NOT_IN_LISTCO",
            "OFFSET_IGNORED", "REGIME_MODIFIER_MISSING", "MAGNITUDE_IMMATERIAL",
            "HORIZON_MISMATCH", "EVIDENCE_STALE", "BASE_RATE_VIOLATION",
            "SECOND_ORDER_OVERREACH"} <= set(OBJECTION_TYPES)

    with pytest.raises(SignalPayloadError):
        validate_payload("OBJECTION", {
            "objection_id": "x", "type": "THE_MODEL_FELT_UNEASY",
            "severity": "MAJOR", "sustained": True})


def test_the_v4_verifier_objection_type_still_validates():
    """The live path emits NOT_INDEPENDENTLY_VERIFIED for every entry whose V4
    verifier did not confirm the company. Closing the vocabulary must not
    silently drop the only objection production actually produces."""
    from app.core.signals import validate_payload

    validate_payload("OBJECTION", {
        "objection_id": "v4:X:verification", "type": "NOT_INDEPENDENTLY_VERIFIED",
        "severity": "MAJOR", "sustained": False})


def test_the_thresholds_come_from_config_not_from_code():
    from app.analysis.empirical.config import load_empirical_config

    policy = load_empirical_config()
    assert policy.min_events == 10        # spec §10.2
    assert policy.max_p_value == 0.10     # spec §10.2


# --- what a conflict does ---------------------------------------------------

def _assess(row, *, direction="POSITIVE", regime_change=None, as_of=FIXTURE_TODAY):
    from app.analysis.empirical.check import assess

    return assess(_Impact(direction), row, regime_change=regime_change, as_of=as_of,
                  shock_variable="fixture_variable", shock_sign="UP", horizon="5d")


def test_agree_publishes_primary():
    """The control. Without it, 'conflict caps at secondary' could be true
    because nothing ever reaches primary."""
    impact = impact_with_empirical(_assess(transmission_row(median_car=0.014)))
    assert impact.empirical_status == "AGREE"
    assert impact.publication_tier == "PRIMARY"


def test_conflict_caps_the_tier_at_secondary_and_does_not_reject():
    impact = impact_with_empirical(_assess(transmission_row(median_car=-0.014)))
    assert impact.empirical_status == "CONFLICT"
    assert impact.publication_tier == "SECONDARY_RIPPLE"
    assert impact.rejection_reason is None


def test_conflict_attaches_a_major_objection():
    impact = impact_with_empirical(_assess(transmission_row(median_car=-0.014)))
    conflicts = [o for o in impact.objections if o["type"] == "EMPIRICAL_CONFLICT"]
    assert len(conflicts) == 1
    assert conflicts[0]["severity"] == "MAJOR"
    assert conflicts[0]["sustained"] is True


def test_a_sustained_major_conflict_objection_still_publishes_as_a_ripple():
    """The gate refuses a sustained MAJOR objection at BOTH tiers by default,
    which would have turned the phase file's 'cap at SECONDARY' into a
    rejection. The exemption is narrow: one objection type, one tier."""
    from app.core.config_loader import load_gate_config

    config = load_gate_config()
    assert "EMPIRICAL_CONFLICT" in config.secondary.objection_types_exempt_from_severity_cap
    assert "EMPIRICAL_CONFLICT" not in config.primary.objection_types_exempt_from_severity_cap


def test_a_sustained_major_objection_of_another_type_still_rejects_at_secondary():
    """REVIEW ROUND 1 (I-3). The exemption must be NARROW, and a config list
    with one entry in it is not proof of that: this is the behavioural half.

    An OFFSET_IGNORED objection is MAJOR in §12.1's taxonomy exactly like
    EMPIRICAL_CONFLICT, is not exempt, and therefore still fails the SECONDARY
    walk and rejects -- which is what makes the empirical exemption a carve-out
    rather than a hole.
    """
    from app.core.signals import make_signal
    from tests.phase5.conftest import FIXTURE_ANALYSIS_VERSION

    objection = make_signal(
        event_id=FIXTURE_EVENT_ID, company_id=FIXTURE_COMPANY_ID,
        stage="FALSIFIER", kind="OBJECTION",
        payload={"objection_id": "fixture:offset-ignored", "type": "OFFSET_IGNORED",
                 "severity": "MAJOR", "sustained": True, "_fixture": True},
        created_by="human:fixture", analysis_version=FIXTURE_ANALYSIS_VERSION,
        created_at=FIXTURE_NOW)
    impact = impact_with_empirical(
        _assess(transmission_row(median_car=0.014)), extra_signals=(objection,))
    assert impact.publication_tier == "REJECTED"
    assert impact.rejection_reason == "SECONDARY_FAILED_OBJECTIONS"


def test_the_exemption_does_not_rescue_a_second_objection_on_the_same_record():
    """A conflicted candidate that ALSO has an unrelated sustained MAJOR
    objection is rejected: the carve-out forgives one named type, not the
    record that carries it."""
    from app.core.signals import make_signal
    from tests.phase5.conftest import FIXTURE_ANALYSIS_VERSION

    objection = make_signal(
        event_id=FIXTURE_EVENT_ID, company_id=FIXTURE_COMPANY_ID,
        stage="FALSIFIER", kind="OBJECTION",
        payload={"objection_id": "fixture:evidence-stale", "type": "EVIDENCE_STALE",
                 "severity": "MAJOR", "sustained": True, "_fixture": True},
        created_by="human:fixture", analysis_version=FIXTURE_ANALYSIS_VERSION,
        created_at=FIXTURE_NOW)
    impact = impact_with_empirical(
        _assess(transmission_row(median_car=-0.014)), extra_signals=(objection,))
    assert impact.publication_tier == "REJECTED"


def test_weak_caps_at_secondary_because_the_spec_allowlist_is_frozen():
    """CONTROLLER RULING (review round 1). BUILD_SPEC §7.4's PRIMARY
    allowlist is `{AGREE, NO_DATA}` and EXECUTION_CONTRACT §7.1 freezes it, so
    `WEAK` does not reach PRIMARY however good the argument for it is --
    amending a frozen spec value takes a failing measurement under §7.2, and
    none exists.

    The argument (a measured-but-insignificant sample currently publishes
    strictly worse than never having measured at all) is recorded as PROPOSED
    SPEC AMENDMENT 1 in DATA_GAPS §9.9 for the owner. It is deliberately NOT
    implemented here, and this test is the pin that keeps it that way.

    WEAK is admitted at SECONDARY_RIPPLE, which states no empirical policy --
    so the candidate publishes as a ripple rather than being rejected.
    """
    impact = impact_with_empirical(_assess(transmission_row(p_value=0.5)))
    assert impact.empirical_status == "WEAK"
    assert impact.publication_tier == "SECONDARY_RIPPLE"
    assert impact.rejection_reason is None


def test_no_data_does_not_block_primary():
    impact = impact_with_empirical(_assess(transmission_row(n_events=3)))
    assert impact.empirical_status == "NO_DATA"
    assert impact.publication_tier == "PRIMARY"


def test_the_empirical_check_never_changes_the_fundamental_read():
    """A cross-check may cap a tier and raise an objection. It may not touch
    direction, materiality or the band."""
    from app.core.reducer import serialize_company_impact

    agree = serialize_company_impact(
        impact_with_empirical(_assess(transmission_row(median_car=0.014))))
    conflict = serialize_company_impact(
        impact_with_empirical(_assess(transmission_row(median_car=-0.014))))
    for key in ("net_effect", "sign_consistency", "materiality_bucket",
                "direction_by_horizon", "headline_horizon"):
        assert agree["fundamental"][key] == conflict["fundamental"][key]


# --- the divergence queue ---------------------------------------------------

def test_a_conflict_is_routed_to_the_divergence_review_queue(phase5_session):
    from app.analysis.empirical.divergence import queue_empirical_conflict

    review_id = queue_empirical_conflict(
        phase5_session, event_id=FIXTURE_EVENT_ID, company_id=FIXTURE_COMPANY_ID,
        assessment=_assess(transmission_row(median_car=-0.014)),
        fundamental_direction="POSITIVE", created_at=FIXTURE_NOW)
    row = phase5_session.execute(text(
        "SELECT kind, status, company_id, shock_variable FROM divergence_review "
        "WHERE review_id = :id"), {"id": review_id}).one()
    assert row[0] == "EMPIRICAL_CONFLICT"
    assert row[1] == "OPEN"
    assert row[2] == FIXTURE_COMPANY_ID
    assert row[3] == "fixture_variable"


def test_queueing_the_same_conflict_twice_does_not_grow_the_queue(phase5_session):
    from app.analysis.empirical.divergence import queue_empirical_conflict

    for _ in range(2):
        queue_empirical_conflict(
            phase5_session, event_id=FIXTURE_EVENT_ID, company_id=FIXTURE_COMPANY_ID,
            assessment=_assess(transmission_row(median_car=-0.014)),
            fundamental_direction="POSITIVE", created_at=FIXTURE_NOW)
    assert phase5_session.execute(text(
        "SELECT count(*) FROM divergence_review")).scalar() == 1


# --- REGIME_CHANGED ---------------------------------------------------------

def test_a_regime_change_annotation_requires_an_expiry(phase5_session):
    """A regime claim nobody re-affirms is a regime claim nobody maintains --
    the same rule Phase 4 applied to `policy_state`."""
    from app.analysis.empirical.regime import RegimeChangeRefused, record_regime_change

    with pytest.raises(RegimeChangeRefused):
        record_regime_change(
            phase5_session, company_id=FIXTURE_COMPANY_ID,
            shock_class="fixture_variable:UP", reason="fixture regime change",
            reviewed_by="human:fixture-reviewer", effective_from=FIXTURE_TODAY,
            expires_on=None)


def test_resolving_a_review_as_regime_changed_writes_the_annotation(phase5_session):
    from app.analysis.empirical.divergence import queue_empirical_conflict, resolve
    from app.analysis.empirical.regime import active_regime_change

    review_id = queue_empirical_conflict(
        phase5_session, event_id=FIXTURE_EVENT_ID, company_id=FIXTURE_COMPANY_ID,
        assessment=_assess(transmission_row(median_car=-0.014)),
        fundamental_direction="POSITIVE", created_at=FIXTURE_NOW)
    resolve(phase5_session, review_id, resolution="REGIME_CHANGED",
            reason="the fixture levy that drove the old behaviour was repealed",
            reviewed_by="human:fixture-reviewer", resolved_at=FIXTURE_NOW,
            expires_on=FIXTURE_TODAY + timedelta(days=180))

    annotation = active_regime_change(
        phase5_session, company_id=FIXTURE_COMPANY_ID,
        shock_class="fixture_variable:UP", as_of=FIXTURE_TODAY)
    assert annotation is not None
    assert annotation.reviewed_by == "human:fixture-reviewer"
    assert phase5_session.execute(text(
        "SELECT status FROM divergence_review WHERE review_id = :id"),
        {"id": review_id}).scalar() == "RESOLVED"


def test_an_active_regime_change_restores_primary_eligibility(phase5_session):
    from app.analysis.empirical.regime import RegimeChange

    annotation = RegimeChange(
        company_id=FIXTURE_COMPANY_ID, shock_class="fixture_variable:UP",
        reason="fixture", reviewed_by="human:fixture-reviewer",
        effective_from=FIXTURE_TODAY - timedelta(days=1),
        expires_on=FIXTURE_TODAY + timedelta(days=180), review_id="fixture-review")
    impact = impact_with_empirical(
        _assess(transmission_row(median_car=-0.014), regime_change=annotation))
    assert impact.empirical_status == "CONFLICT", (
        "the record must keep saying what history said")
    assert impact.publication_tier == "PRIMARY"
    assert not [o for o in impact.objections if o["type"] == "EMPIRICAL_CONFLICT"]


def test_an_expired_regime_change_stops_restoring_primary(phase5_session):
    from app.analysis.empirical.regime import RegimeChange

    annotation = RegimeChange(
        company_id=FIXTURE_COMPANY_ID, shock_class="fixture_variable:UP",
        reason="fixture", reviewed_by="human:fixture-reviewer",
        effective_from=FIXTURE_TODAY - timedelta(days=400),
        expires_on=FIXTURE_TODAY - timedelta(days=1), review_id="fixture-review")
    impact = impact_with_empirical(
        _assess(transmission_row(median_car=-0.014), regime_change=annotation))
    assert impact.publication_tier == "SECONDARY_RIPPLE"


def test_an_expired_annotation_is_not_returned_by_the_lookup(phase5_session):
    from app.analysis.empirical.regime import active_regime_change, record_regime_change

    record_regime_change(
        phase5_session, company_id=FIXTURE_COMPANY_ID,
        shock_class="fixture_variable:UP", reason="fixture",
        reviewed_by="human:fixture-reviewer",
        effective_from=date(2225, 1, 1), expires_on=date(2225, 6, 1))
    assert active_regime_change(
        phase5_session, company_id=FIXTURE_COMPANY_ID,
        shock_class="fixture_variable:UP", as_of=FIXTURE_TODAY) is None


# --- the review console (review round 1, I-4) -------------------------------

def _queued(session):
    from app.analysis.empirical.divergence import queue_empirical_conflict

    return queue_empirical_conflict(
        session, event_id=FIXTURE_EVENT_ID, company_id=FIXTURE_COMPANY_ID,
        assessment=_assess(transmission_row(median_car=-0.014)),
        fundamental_direction="POSITIVE", created_at=FIXTURE_NOW)


def test_the_divergence_queue_is_mounted_on_the_ledger_console(phase5_engine):
    """§10.3 routes a conflict to a HUMAN reviewer, which needs somewhere for
    the human to stand. Same standalone console as the exposure ledger and the
    mechanism edges -- internal tooling, never the product surface."""
    from fastapi.testclient import TestClient

    from tools.ledger_ui import build_app

    client = TestClient(build_app(phase5_engine))
    response = client.get("/divergence/queue")
    assert response.status_code == 200
    assert "divergence review" in response.text.lower()
    assert "never auto-rejected" in response.text.lower()


def test_the_console_shows_an_open_conflict_with_its_sample(phase5_session,
                                                            phase5_engine):
    from fastapi.testclient import TestClient

    from tools.ledger_ui import build_app

    review_id = _queued(phase5_session)
    phase5_session.commit()
    client = TestClient(build_app(phase5_engine))

    queue = client.get("/divergence/queue")
    assert review_id in queue.text
    detail = client.get(f"/divergence/review?review_id={review_id}")
    assert detail.status_code == 200
    assert "-1.40%" in detail.text          # the median CAR, as a reviewer reads it
    assert "34" in detail.text              # the sample


def test_resolving_as_regime_changed_through_the_console_writes_the_annotation(
        phase5_session, phase5_engine):
    from fastapi.testclient import TestClient
    from sqlalchemy import text as sql

    from tools.ledger_ui import build_app

    review_id = _queued(phase5_session)
    phase5_session.commit()
    client = TestClient(build_app(phase5_engine))

    response = client.post("/divergence/resolve", data={
        "review_id": review_id, "resolution": "REGIME_CHANGED",
        "reviewed_by": "human:fixture-reviewer",
        "reason": "the fixture levy that drove the old behaviour was repealed",
        "expires_on": "2226-09-01"}, follow_redirects=False)
    assert response.status_code == 303

    assert phase5_session.execute(sql(
        "SELECT status FROM divergence_review WHERE review_id = :id"),
        {"id": review_id}).scalar() == "RESOLVED"
    annotation = phase5_session.execute(sql(
        "SELECT reviewed_by, expires_on FROM regime_change")).one()
    assert annotation[0] == "human:fixture-reviewer"


def test_the_console_refuses_a_regime_change_with_no_expiry(phase5_session,
                                                            phase5_engine):
    """The form is not where the rule lives -- `record_regime_change` refuses
    it and the page shows the refusal. There is no permanent option."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text as sql

    from tools.ledger_ui import build_app

    review_id = _queued(phase5_session)
    phase5_session.commit()
    client = TestClient(build_app(phase5_engine))

    response = client.post("/divergence/resolve", data={
        "review_id": review_id, "resolution": "REGIME_CHANGED",
        "reviewed_by": "human:fixture-reviewer", "reason": "because",
        "expires_on": ""}, follow_redirects=False)
    assert response.status_code == 400
    assert "expiry" in response.text.lower()
    assert phase5_session.execute(sql(
        "SELECT count(*) FROM regime_change")).scalar() == 0
    assert phase5_session.execute(sql(
        "SELECT status FROM divergence_review WHERE review_id = :id"),
        {"id": review_id}).scalar() == "OPEN"


def test_the_console_cannot_edit_a_measurement(phase5_engine):
    """A console that let a reviewer adjust the evidence they disagree with
    would be the opposite of a falsifier."""
    from pathlib import Path

    from tests.phase5.conftest import code_lines

    path = (BACKEND / "app" / "ledger" / "divergence_review_pages.py")
    for number, line in code_lines(Path(path)):
        for needle in ("UPDATE transmission_empirical", "INSERT INTO transmission",
                       "median_car =", "p_value ="):
            assert needle not in line, f"divergence_review_pages.py:{number}"


# --- the UI sentence --------------------------------------------------------

def test_the_disagreement_sentence_names_n_the_median_and_the_band():
    """§10.3's feature, not an apology: 'in 34 comparable historical shocks
    this name's 5-day abnormal return was -1.4% (IQR -3.2 to +0.1)'."""
    from app.analysis.empirical.presentation import empirical_line

    line = empirical_line(_assess(transmission_row(median_car=-0.014)),
                          fundamental_direction="POSITIVE")
    assert "34" in line
    assert "-1.4%" in line
    assert "-3.2" in line and "0.1" in line
    assert "5-day" in line


def test_the_sentence_refuses_to_render_without_the_band():
    from app.analysis.empirical.presentation import EmpiricalRenderError, empirical_line

    with pytest.raises(EmpiricalRenderError):
        empirical_line(_assess(transmission_row(n_events=3)),
                       fundamental_direction="POSITIVE")
