"""TASK 3.7 -- the coverage audit harness.

Ripple coverage must be MEASURED or it regresses silently as data ages. The
key deliverable is not the recall number: it is the PER-AXIS DIAGNOSTIC that
turns "the system misses ripples" into an assignable ticket naming which of
V / M / C / G failed and who owns it (addendum A6.2).

WHAT THE NUMBERS IN THIS FILE MEAN. They are measured on the SYNTHETIC
universe in `conftest.py` -- fake companies, round-number exposures. They
prove the harness counts correctly. Real coverage is zero and is recorded in
DATA_GAPS §7, not here.
"""
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text

from tests.coverage.conftest import (
    EXPECTED_MAP_YAML, FIXTURE_TODAY, expected_for, load_expected_map,
)
from tests.coverage.harness import audit_shock

BACKEND = Path(__file__).resolve().parents[2]


# --- the map itself ---------------------------------------------------------

def test_the_expected_map_is_marked_proposed_and_unsigned():
    text_ = EXPECTED_MAP_YAML.read_text(encoding="utf-8")
    assert "PROPOSED-PENDING-OWNER-SIGN-OFF" in text_
    assert "THE OWNER OWNS THIS LIST" in text_
    raw = yaml.safe_load(text_)
    assert raw["signed_off_by"] is None


def test_every_family_in_the_map_has_a_tag_mapping():
    raw = load_expected_map()
    known = set(raw["family_tags"])
    for entry in raw["shocks"]:
        for key in ("expected_primary", "expected_ripple", "expected_marginal",
                    "expected_absent"):
            for family in entry[key]:
                assert family in known, f"{family} has no family_tags entry"


def test_every_tag_in_the_map_is_in_the_closed_vocabulary():
    from app.ledger.exposure_tags import load_vocabulary

    vocabulary = load_vocabulary().tags
    for family, tags in load_expected_map()["family_tags"].items():
        for tag in tags:
            assert tag in vocabulary, f"{family} maps to unknown tag {tag}"


def test_marginal_and_absent_families_never_overlap_the_expected_sets():
    for entry in load_expected_map()["shocks"]:
        expected = set(entry["expected_primary"]) | set(entry["expected_ripple"])
        assert not expected & set(entry["expected_marginal"])
        assert not expected & set(entry["expected_absent"])


# --- the DoD numbers, on the synthetic universe -----------------------------

@pytest.fixture()
def crude_report(coverage_session, universe):
    return audit_shock(coverage_session, expected_for("BRENT_CRUDE"),
                       as_of=FIXTURE_TODAY)


def test_crude_ripple_family_recall_clears_the_floor(crude_report):
    assert crude_report.ripple_recall >= 0.80, crude_report.render()


def test_crude_surfaces_paints_and_tyres(crude_report):
    """The regression test named in the DEFINITION OF DONE. These are the two
    families the V4 system never found."""
    assert "paints" in crude_report.surfaced_ripple
    assert "tyres" in crude_report.surfaced_ripple


def test_secondary_precision_holds(crude_report):
    assert crude_report.secondary_precision >= 0.80, crude_report.render()


def test_expected_absent_families_do_not_appear(crude_report):
    assert crude_report.absent_violations == ()


def test_marginal_families_are_excluded_from_both_sides(crude_report):
    """`cement` is 0.58% of EBITDA in this universe -- genuinely marginal. It
    must not count as a miss, and it must not count as a false positive."""
    assert "cement" not in {d.family for d in crude_report.missing}
    assert "cement" not in crude_report.false_positive_families
    assert crude_report.ripple_denominator == 7


def test_every_published_company_carries_a_mechanism_id(crude_report):
    assert crude_report.published
    for row in crude_report.published:
        assert row.mechanism_id, row


# --- the per-axis diagnostic ------------------------------------------------

def test_a_family_with_no_tagged_company_is_attributed_to_the_c_axis(crude_report):
    """`city_gas` has an edge and no ledger row -- the exact situation the
    addendum says the system must be able to NAME."""
    by_family = {d.family: d for d in crude_report.missing}
    assert "city_gas" in by_family
    diagnostic = by_family["city_gas"]
    assert diagnostic.root_cause == "C"
    assert diagnostic.owner == "ledger"
    assert diagnostic.axis("V").status == "PASS"
    assert diagnostic.axis("M").status == "PASS"
    assert diagnostic.axis("C").status == "FAIL"
    assert diagnostic.axis("G").status == "n/a"


def test_an_injected_mechanism_gap_is_attributed_to_the_m_axis(coverage_session,
                                                               universe):
    """Delete the one edge that reaches tyres. The companies are still tagged,
    so C passes and M fails -- and the diagnostic must say M, not 'missing'."""
    coverage_session.execute(text(
        "DELETE FROM mechanism_edge WHERE edge_id = 'syn-naphtha-rubber'"))
    report = audit_shock(coverage_session, expected_for("BRENT_CRUDE"),
                         as_of=FIXTURE_TODAY)
    by_family = {d.family: d for d in report.missing}
    assert "tyres" in by_family
    diagnostic = by_family["tyres"]
    assert diagnostic.root_cause == "M"
    assert diagnostic.owner == "graph"
    assert diagnostic.axis("V").status == "PASS"
    assert diagnostic.axis("M").status == "FAIL"
    assert diagnostic.axis("C").status == "PASS"
    assert diagnostic.axis("G").status == "n/a"
    assert diagnostic.listed_names == 4


def test_an_injected_company_gap_is_attributed_to_the_c_axis(coverage_session):
    """Build the adhesives COMPANIES but tag none of them. The edge still
    exists, so M passes and C fails -- and the diagnostic must say C."""
    from tests.coverage.conftest import build_universe

    build_universe(coverage_session, untagged_families=("adhesives",))
    report = audit_shock(coverage_session, expected_for("BRENT_CRUDE"),
                         as_of=FIXTURE_TODAY)
    by_family = {d.family: d for d in report.missing}
    assert "adhesives" in by_family
    assert by_family["adhesives"].root_cause == "C"
    assert by_family["adhesives"].owner == "ledger"


def test_an_unmodelled_variable_is_attributed_to_the_v_axis(coverage_session,
                                                            universe):
    entry = dict(expected_for("BRENT_CRUDE"))
    entry["shock"] = dict(entry["shock"], variable="NOT_A_MODELLED_VARIABLE")
    report = audit_shock(coverage_session, entry, as_of=FIXTURE_TODAY)
    assert report.ripple_recall == 0.0
    for diagnostic in report.missing:
        assert diagnostic.root_cause == "V"
        assert diagnostic.owner == "shock modelling"
        assert diagnostic.axis("M").status == "n/a"


def test_the_diagnostic_renders_in_the_addendum_format(coverage_session,
                                                       universe):
    coverage_session.execute(text(
        "DELETE FROM mechanism_edge WHERE edge_id = 'syn-naphtha-rubber'"))
    report = audit_shock(coverage_session, expected_for("BRENT_CRUDE"),
                         as_of=FIXTURE_TODAY)
    rendered = {d.family: d.render() for d in report.missing}["tyres"]
    lines = rendered.splitlines()
    assert lines[0] == "MISSING: tyres"
    assert lines[1].startswith("  V shock variable modelled")
    assert lines[1].rstrip().endswith("PASS")
    assert lines[2].startswith("  M mechanism edge exists")
    assert "FAIL" in lines[2]
    assert lines[3].startswith("  C companies tagged")
    assert lines[4].startswith("  G would pass gates")
    assert lines[4].rstrip().endswith("n/a")
    assert lines[5].startswith("  ROOT CAUSE: mechanism gap (M).")
    assert "Owner: graph." in lines[5]
    assert "4 listed names." in lines[5]


# --- the top-5 shock classes ------------------------------------------------

def test_no_shock_class_in_the_map_has_an_unexplained_mechanism_gap(
        coverage_session, universe):
    """DEFINITION OF DONE: 'the per-axis diagnostic reports zero unexplained
    M-gaps for the top 5 shock classes'. The map proposes four; every family
    in every one of them is reachable by an authored edge. What is missing is
    C (ledger rows), and the diagnostic says so by name."""
    unexplained = []
    for entry in load_expected_map()["shocks"]:
        report = audit_shock(coverage_session, entry, as_of=FIXTURE_TODAY)
        unexplained.extend(
            f"{entry['shock']['variable']}/{d.family}"
            for d in report.missing if d.root_cause == "M")
    assert unexplained == []


def test_the_other_shock_classes_report_ledger_gaps_not_silence(coverage_session,
                                                                universe):
    """The whole point of the addendum: an uncovered family is a NAMED,
    assignable gap, not an absence nobody can see."""
    report = audit_shock(coverage_session, expected_for("REPO_RATE"),
                         as_of=FIXTURE_TODAY)
    assert report.ripple_recall == 0.0
    # nbfc is this shock's expected PRIMARY family; the diagnostic reports
    # every expected family it did not surface, not only the ripple ones.
    assert {d.family for d in report.missing} == {"nbfc", "real_estate", "infra"}
    assert {d.root_cause for d in report.missing} == {"C"}


# --- the harness must not cheat --------------------------------------------

def test_the_harness_never_infers_directness_from_distance():
    """Invariant 4. The harness scores the SECONDARY_RIPPLE walk and passes
    no directness at all -- it cannot, because discovery does not produce
    one."""
    from tests.coverage import harness
    from tests.phase3.conftest import code_lines

    for number, line in code_lines(Path(harness.__file__)):
        assert "directness" not in line or "directness=None" in line, (
            f"harness.py:{number}: {line}")


def test_thresholds_are_read_from_the_deployed_policy_not_the_harness():
    from tests.coverage import harness

    import re

    source = Path(harness.__file__).read_text(encoding="utf-8")
    for number, line in enumerate(source.splitlines(), 1):
        if line.strip().startswith("#"):
            continue
        for literal in re.findall(r"(?<![\w.])0\.\d+", line):
            pytest.fail(f"harness.py:{number} carries a threshold literal "
                        f"{literal}; the gate's thresholds are in "
                        f"config/gates.yaml")


def test_the_recall_floor_is_not_satisfied_by_an_empty_expectation(coverage_session,
                                                                   universe):
    """A denominator of zero must not read as perfect recall."""
    entry = dict(expected_for("BRENT_CRUDE"))
    entry["expected_ripple"] = []
    report = audit_shock(coverage_session, entry, as_of=FIXTURE_TODAY)
    assert report.ripple_denominator == 0
    assert report.ripple_recall is None
