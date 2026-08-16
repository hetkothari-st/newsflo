"""TASK 3.6 -- ripple-specific gates (addendum A5.1) and the sector
coherence rule (A5.2).

The gate split is ADDITIVE: Phase 0's gate keeps every rule it had, and the
A5.1 keys that it did not previously express (`materiality_floor_pct`,
`allow_sector_proxy`, `min_companies_per_section`) become rules only when the
policy names them. `tests/phase0` must stay green, and does.

PRECISION IS NOT NEGOTIABLE. Nothing in this task loosens a primary
threshold; the ripple floor is lower than the primary floor because a ripple
is a different claim, not because a number needed hitting.
"""
from pathlib import Path

import pytest
import yaml

from app.core.gates import ImpactDraft

BACKEND = Path(__file__).resolve().parents[2]
GATES_YAML = BACKEND / "config" / "gates.yaml"


def ripple_draft(**overrides) -> ImpactDraft:
    """A draft that clears every SECONDARY rule -- so a single override is
    the only thing under test."""
    base = dict(
        entity_status="ACTIVE", entity_ambiguous=False, exposure_stale=False,
        materiality_bucket="MEDIUM", graph_distance=3, directness="INDIRECT",
        evidence_grade="C", weakest_link="MATERIALITY:BOUND",
        sign_consistency=0.75, empirical_status=None, objections=(),
        unbound_claim_ids=(), verifier_status=None, adv_20d_inr=None,
        event_status="CONFIRMED", shock_magnitude_confidence=0.9,
        mechanism_id="fixture:mechanism:1", net_effect="UNCERTAIN",
        delta_ebitda_pct_abs=1.5, uses_sector_proxy=False)
    base.update(overrides)
    return ImpactDraft(**base)


# --- the config split -------------------------------------------------------

def test_gates_yaml_carries_the_a5_1_split():
    raw = yaml.safe_load(GATES_YAML.read_text(encoding="utf-8"))
    assert "primary" in raw
    assert "secondary_ripple" in raw, (
        "A5.1 names the ripple block `secondary_ripple`")
    primary, ripple = raw["primary"], raw["secondary_ripple"]
    assert primary["materiality_floor_pct"] == 2.0
    assert ripple["materiality_floor_pct"] == 0.75
    assert primary["max_graph_distance"] == 2
    assert ripple["max_graph_distance"] == 3
    assert primary["min_sign_consistency"] == 0.90
    assert ripple["min_sign_consistency"] == 0.60
    assert primary["allow_sector_proxy"] is False
    assert ripple["allow_sector_proxy"] is True
    assert ripple["require_mechanism_id"] is True
    assert ripple["min_companies_per_section"] == 1


def test_the_loader_accepts_both_spellings_of_the_ripple_block(tmp_path):
    """`secondary` was Phase 0's spelling and `secondary_ripple` is A5.1's.
    The loader reads either and produces the SAME policy, so renaming the key
    could not silently change what publishes."""
    from app.core.config_loader import load_gate_config

    raw = yaml.safe_load(GATES_YAML.read_text(encoding="utf-8"))
    legacy = dict(raw)
    legacy["secondary"] = legacy.pop("secondary_ripple")
    path = tmp_path / "gates.yaml"
    path.write_text(yaml.safe_dump(legacy), encoding="utf-8")

    assert load_gate_config(path).secondary == load_gate_config().secondary


def test_min_evidence_grade_agrees_with_the_grade_list():
    """A5.1 states the floor as a single grade; Phase 0's gate states it as a
    list. Two spellings of one policy must not be able to disagree."""
    from app.core.config_loader import load_gate_config

    config = load_gate_config()
    assert config.primary.min_evidence_grade == "C"
    assert config.secondary.min_evidence_grade == "D"
    assert config.primary.evidence_grades[-1] == config.primary.min_evidence_grade
    assert config.secondary.evidence_grades[-1] == config.secondary.min_evidence_grade


def test_the_loader_refuses_a_grade_floor_that_contradicts_the_list(tmp_path):
    from app.core.config_loader import load_gate_config

    raw = yaml.safe_load(GATES_YAML.read_text(encoding="utf-8"))
    raw["secondary_ripple"]["min_evidence_grade"] = "A"
    path = tmp_path / "gates.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        load_gate_config(path)


# --- the rules --------------------------------------------------------------

def test_secondary_without_a_mechanism_id_is_rejected():
    from app.core.config_loader import load_gate_config
    from app.core.gates import evaluate

    result = evaluate(ripple_draft(mechanism_id=None), load_gate_config())
    assert result.tier == "REJECTED"
    assert result.rejection_reason == "SECONDARY_REQUIRES_MECHANISM"


def test_secondary_with_a_mechanism_id_publishes():
    from app.core.config_loader import load_gate_config
    from app.core.gates import evaluate

    assert evaluate(ripple_draft(), load_gate_config()).tier == "SECONDARY_RIPPLE"


def test_the_ripple_materiality_floor_differs_from_the_primary_floor():
    from app.core.config_loader import load_gate_config
    from app.core.gates import evaluate_primary, evaluate_secondary

    config = load_gate_config()
    assert config.primary.materiality_floor_pct == 2.0
    assert config.secondary.materiality_floor_pct == 0.75

    # 1.5% of EBITDA: below the primary floor, above the ripple floor.
    draft = ripple_draft(delta_ebitda_pct_abs=1.5, materiality_bucket="HIGH",
                         graph_distance=1, directness="DIRECT",
                         sign_consistency=0.95, evidence_grade="A",
                         net_effect="NEGATIVE", verifier_status="PASS",
                         empirical_status="AGREE")
    assert evaluate_primary(draft, config).tier is None
    assert evaluate_secondary(draft, config).tier == "SECONDARY_RIPPLE"


def test_a_company_below_the_ripple_floor_is_rejected():
    from app.core.config_loader import load_gate_config
    from app.core.gates import evaluate

    result = evaluate(ripple_draft(delta_ebitda_pct_abs=0.5), load_gate_config())
    assert result.tier == "REJECTED"
    assert result.rejection_reason == "SECONDARY_FAILED_MATERIALITY_FLOOR"


def test_what_an_absent_band_means_is_stated_in_the_policy_not_defaulted():
    """A draft with no computed band cannot be SHOWN to clear a floor
    expressed in percent of EBITDA. Phase 0's convention for an input that
    does not exist yet is an explicit `unknown_*_passes` key in the YAML, and
    the two Phase 3 rules follow it rather than inventing a default.

    Deployed TRUE today, because nothing computes a band on the V4-fed
    canonical path (Phase 2's engine needs ledger rows that do not exist), so
    this task changes no verdict. The key exists so that flipping it is one
    line in a config review rather than a code change."""
    import yaml

    from app.core.config_loader import load_gate_config

    raw = yaml.safe_load(GATES_YAML.read_text(encoding="utf-8"))
    for block in ("primary", "secondary_ripple"):
        assert "unknown_materiality_delta_passes" in raw[block], (
            f"{block} does not state what an absent band means")
        assert "unknown_sector_proxy_passes" in raw[block]

    config = load_gate_config()
    assert config.primary.unknown_materiality_delta_passes is True
    assert config.secondary.unknown_materiality_delta_passes is True


def test_flipping_the_unknown_policy_rejects_a_draft_with_no_band(tmp_path):
    """Non-vacuous companion: the rule really is a rule, and the key really
    is what decides it."""
    import yaml

    from app.core.config_loader import load_gate_config
    from app.core.gates import evaluate

    raw = yaml.safe_load(GATES_YAML.read_text(encoding="utf-8"))
    raw["primary"]["unknown_materiality_delta_passes"] = False
    raw["secondary_ripple"]["unknown_materiality_delta_passes"] = False
    path = tmp_path / "gates.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    result = evaluate(ripple_draft(delta_ebitda_pct_abs=None),
                      load_gate_config(path))
    assert result.tier == "REJECTED"
    assert result.rejection_reason == "SECONDARY_FAILED_MATERIALITY_FLOOR"
    # and with the deployed policy the same draft still publishes
    assert evaluate(ripple_draft(delta_ebitda_pct_abs=None),
                    load_gate_config()).tier == "SECONDARY_RIPPLE"


def test_a_sector_proxy_parameter_is_admissible_for_ripple_and_not_for_primary():
    from app.core.config_loader import load_gate_config
    from app.core.gates import evaluate_primary, evaluate_secondary

    config = load_gate_config()
    draft = ripple_draft(uses_sector_proxy=True, materiality_bucket="HIGH",
                         graph_distance=1, directness="DIRECT",
                         sign_consistency=0.95, evidence_grade="A",
                         net_effect="NEGATIVE", verifier_status="PASS",
                         empirical_status="AGREE", delta_ebitda_pct_abs=6.0)
    assert evaluate_primary(draft, config).tier is None
    assert evaluate_secondary(draft, config).tier == "SECONDARY_RIPPLE"


def test_precision_first_the_primary_walk_is_unchanged_by_this_task():
    """A5.3's guardrail as a test: every PRIMARY threshold is what Phase 0
    deployed. Recall work may add rules; it may never relax these."""
    from app.core.config_loader import load_gate_config

    primary = load_gate_config().primary
    assert primary.max_graph_distance == 2
    assert primary.min_sign_consistency == 0.90
    assert primary.materiality_buckets == ("HIGH",)
    assert primary.evidence_grades == ("A", "B", "C")
    assert primary.forbidden_weakest_link_statuses == ("SECTOR_PROXY", "UNBOUND")
    assert primary.allowed_empirical_status == ("AGREE", "NO_DATA")
    assert primary.required_verifier_status == "PASS"


def test_a_failed_primary_does_not_demote_to_secondary_through_the_new_rules():
    """Invariant 5, re-checked against the rules this task added."""
    from app.core.config_loader import load_gate_config
    from app.core.gates import evaluate_primary, evaluate_secondary

    config = load_gate_config()
    draft = ripple_draft(delta_ebitda_pct_abs=0.5, mechanism_id=None)
    primary = evaluate_primary(draft, config)
    secondary = evaluate_secondary(draft, config)
    assert primary.tier is None and secondary.tier is None
    assert not set(r.name for r in primary.gate_trace) & {"__demoted__"}


# --- I3: the partial-rollout hazard, made loud -----------------------------
#
# The two `unknown_*` flags are correct today and dangerous tomorrow. The
# moment the sensitivity engine feeds SOME drafts and not others, a band-less
# draft clears the PRIMARY materiality floor and the PRIMARY sector-proxy ban
# in silence, next to drafts that had to earn it. Silence is the problem, so
# the escape is now recorded on the rule and shouted about at PRIMARY.

def test_the_gate_marks_a_rule_that_passed_only_by_the_unknown_escape():
    from app.core.config_loader import load_gate_config
    from app.core.gates import evaluate_primary

    draft = ripple_draft(delta_ebitda_pct_abs=None, uses_sector_proxy=None,
                         materiality_bucket="HIGH", graph_distance=1,
                         directness="DIRECT", sign_consistency=0.95,
                         evidence_grade="A", net_effect="NEGATIVE",
                         verifier_status="PASS", empirical_status="AGREE")
    result = evaluate_primary(draft, load_gate_config())
    assert result.tier == "PRIMARY"
    escaped = {rule.name for rule in result.gate_trace if rule.unknown_escape}
    assert escaped == {"materiality_floor", "sector_proxy"}


def test_a_rule_that_passed_on_its_merits_is_not_marked_as_an_escape():
    from app.core.config_loader import load_gate_config
    from app.core.gates import evaluate_primary

    draft = ripple_draft(delta_ebitda_pct_abs=6.0, uses_sector_proxy=False,
                         materiality_bucket="HIGH", graph_distance=1,
                         directness="DIRECT", sign_consistency=0.95,
                         evidence_grade="A", net_effect="NEGATIVE",
                         verifier_status="PASS", empirical_status="AGREE")
    result = evaluate_primary(draft, load_gate_config())
    assert result.tier == "PRIMARY"
    assert not any(rule.unknown_escape for rule in result.gate_trace)


def test_a_primary_publication_that_leant_on_an_escape_logs_a_warning(caplog):
    import logging

    from app.core.config_loader import load_gate_config
    from app.core.gate_warnings import warn_on_unknown_escapes
    from app.core.gates import evaluate

    draft = ripple_draft(delta_ebitda_pct_abs=None, uses_sector_proxy=None,
                         materiality_bucket="HIGH", graph_distance=1,
                         directness="DIRECT", sign_consistency=0.95,
                         evidence_grade="A", net_effect="NEGATIVE",
                         verifier_status="PASS", empirical_status="AGREE")
    result = evaluate(draft, load_gate_config())
    assert result.tier == "PRIMARY"

    with caplog.at_level(logging.WARNING, logger="newsflo.gate"):
        escapes = warn_on_unknown_escapes(
            result.gate_trace, tier=result.tier, event_id="fixture:event",
            company_id=4242)

    assert escapes == ("materiality_floor", "sector_proxy")
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert record.gate_unknown_escape_rules == "materiality_floor,sector_proxy"
    assert record.gate_tier == "PRIMARY"
    assert record.company_id == 4242
    assert "V5 SERVING CUTOVER CHECKLIST" in record.getMessage()


def test_a_secondary_publication_does_not_shout(caplog):
    """The hazard is a PRIMARY claim resting on an input nobody evaluated. A
    ripple already admits weaker evidence by design, so warning on it would
    be noise that trains people to ignore the warning that matters."""
    import logging

    from app.core.config_loader import load_gate_config
    from app.core.gate_warnings import warn_on_unknown_escapes
    from app.core.gates import evaluate

    result = evaluate(ripple_draft(delta_ebitda_pct_abs=None,
                                   uses_sector_proxy=None), load_gate_config())
    assert result.tier == "SECONDARY_RIPPLE"
    with caplog.at_level(logging.WARNING, logger="newsflo.gate"):
        escapes = warn_on_unknown_escapes(
            result.gate_trace, tier=result.tier, event_id="e", company_id=1)
    assert escapes == ()
    assert caplog.records == []


def test_the_reducer_carries_the_escape_flag_into_the_gate_trace():
    """The warning has to be reachable from what is PERSISTED, not only from
    an in-memory GateResult, or a postmortem cannot tell which published rows
    leant on an escape."""
    from app.core.reducer import reduce_company_impact
    from tests.phase0 import fixtures

    impact = reduce_company_impact(
        fixtures.signals(fixtures.PRIMARY_COMPANY_ID),
        fixtures.reducer_config())
    assert impact.gate_trace
    assert all("unknown_escape" in row for row in impact.gate_trace)


def test_the_cutover_checklist_exists_and_names_both_flags():
    """I3(3). The instruction to flip these two flags must live in a place
    somebody reads BEFORE cutover, not in a paragraph of prose."""
    data_gaps = (BACKEND.parent / "DATA_GAPS.md").read_text(encoding="utf-8")
    assert "V5 SERVING CUTOVER CHECKLIST" in data_gaps
    checklist = data_gaps.split("V5 SERVING CUTOVER CHECKLIST", 1)[1]
    assert "unknown_materiality_delta_passes" in checklist
    assert "unknown_sector_proxy_passes" in checklist


def test_the_gates_yaml_philosophy_comment_admits_the_fail_open_keys():
    """I3(4). The header said the unknown_* policy is 'FAIL-CLOSED for
    PRIMARY'. Two of them no longer are, and a comment that is no longer true
    is worse than no comment."""
    header = GATES_YAML.read_text(encoding="utf-8").split("version:", 1)[0]
    assert "fail-open" in header.lower()
    assert "unknown_materiality_delta_passes" in header
    assert "unknown_sector_proxy_passes" in header
    assert "CUTOVER" in header


# --- A5.2 sector coherence --------------------------------------------------

def test_three_cleared_companies_publish_the_section():
    from app.discovery.coherence import SectionMember, section_decision

    cleared = tuple(SectionMember(company_id=i, cleared=True) for i in range(3))
    decision = section_decision("tyres", cleared)
    assert decision.publish is True
    assert decision.coverage_note is None
    assert decision.company_ids == (0, 1, 2)


def test_one_of_six_with_peers_rejected_on_data_gaps_emits_a_coverage_note():
    from app.discovery.coherence import SectionMember, section_decision

    members = (SectionMember(company_id=1, cleared=True),) + tuple(
        SectionMember(company_id=i, cleared=False, rejection_reason="NO_EXPOSURE_ROW")
        for i in range(2, 7))
    decision = section_decision("tyres", members)
    assert decision.publish is True
    assert decision.coverage_note == (
        "5 further names in this sector lack company-level input data")
    assert decision.company_ids == (1,)


def test_one_of_six_with_peers_rejected_on_economics_carries_no_coverage_note():
    """The distinction that keeps the note honest: peers we DID size and
    found immaterial are not a coverage gap, and saying they are would be a
    lie in the user's favour."""
    from app.discovery.coherence import SectionMember, section_decision

    members = (SectionMember(company_id=1, cleared=True),) + tuple(
        SectionMember(company_id=i, cleared=False,
                      rejection_reason="SECONDARY_FAILED_MATERIALITY_FLOOR")
        for i in range(2, 7))
    decision = section_decision("tyres", members)
    assert decision.publish is True
    assert decision.coverage_note is None


def test_a_mixed_rejection_set_counts_only_the_data_gap_peers():
    from app.discovery.coherence import SectionMember, section_decision

    members = (
        SectionMember(company_id=1, cleared=True),
        SectionMember(company_id=2, cleared=False, rejection_reason="NO_EXPOSURE_ROW"),
        SectionMember(company_id=3, cleared=False, rejection_reason="EXPOSURE_STALE"),
        SectionMember(company_id=4, cleared=False,
                      rejection_reason="SECONDARY_FAILED_MATERIALITY_FLOOR"),
    )
    decision = section_decision("tyres", members)
    assert decision.coverage_note == (
        "2 further names in this sector lack company-level input data")


def test_a_section_with_nobody_cleared_does_not_publish():
    from app.discovery.coherence import SectionMember, section_decision

    members = tuple(SectionMember(company_id=i, cleared=False,
                                  rejection_reason="NO_EXPOSURE_ROW")
                    for i in range(6))
    decision = section_decision("tyres", members)
    assert decision.publish is False
    assert decision.company_ids == ()


def test_the_minimum_section_size_comes_from_the_deployed_policy():
    from app.core.config_loader import load_gate_config
    from app.discovery.coherence import SectionMember, section_decision

    config = load_gate_config()
    members = (SectionMember(company_id=1, cleared=True),)
    assert section_decision("tyres", members,
                            min_companies=config.secondary.min_companies_per_section
                            ).publish is True
    assert section_decision("tyres", members, min_companies=2).publish is False
