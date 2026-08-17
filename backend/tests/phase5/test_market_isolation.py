"""TASK 5.5 -- market reaction engine isolation (Axis B).

The phase file's mandatory tests:
  - ast scan: core and analysis import nothing from market
  - divergence writes to review queue and never mutates CompanyImpact

WHAT WAS AND WAS NOT DONE (controller adaptation, binding). `app/market/*` is
the LIVE V4 serving path. It is not restructured, not moved and not touched.
What this phase delivers is the BOUNDARY: the V5 packages may not import it,
and the divergence signal may only write to a review queue.

Phase 0 already pinned `app/core/*`. This file widens the ban to every V5
analysis package and adds the divergence half.
"""
import pytest
from sqlalchemy import text

from tests.phase5.conftest import (
    BACKEND, FIXTURE_COMPANY_ID, FIXTURE_EVENT_ID, FIXTURE_NOW, imported_modules,
    package_sources,
)
from tests.phase5.helpers import impact_with_empirical

V5_PACKAGES = {
    "core": BACKEND / "app" / "core",
    "sensitivity": BACKEND / "app" / "analysis" / "sensitivity",
    "policy": BACKEND / "app" / "analysis" / "policy",
    "empirical": BACKEND / "app" / "analysis" / "empirical",
    "calibration": BACKEND / "app" / "analysis" / "calibration",
    "surprise": BACKEND / "app" / "analysis" / "surprise",
}


@pytest.mark.parametrize("name", sorted(V5_PACKAGES))
def test_no_v5_package_imports_app_market(name):
    package = V5_PACKAGES[name]
    assert package.exists(), f"{package} does not exist"
    for path in package_sources(package):
        offenders = {m for m in imported_modules(path)
                     if m == "app.market" or m.startswith("app.market.")}
        assert not offenders, (
            f"{path.relative_to(BACKEND)} imports {sorted(offenders)}: market "
            "movement may never influence a fundamental verdict (invariant 3)")


def test_the_import_scan_sees_a_relative_import_too(tmp_path):
    """REVIEW ROUND 1 (m-11). A scan nobody has seen fire is not a scan, and
    this one had a hole: `from ..market import measure` has `node.level == 2`
    and was invisible. Both spellings must resolve to `app.market`."""
    module = BACKEND / "app" / "analysis" / "empirical" / "_scan_probe.py"
    module.write_text(
        # From `app.analysis.empirical`, three dots is `app` -- so this is the
        # spelling that would actually reach the market layer.
        "from ...market import measure\n"
        "from ..market import other\n"
        "import app.market.intensity\n", encoding="utf-8")
    try:
        seen = imported_modules(module)
        assert "app.market" in seen, seen
        assert "app.market.intensity" in seen, seen
        # ...and the level count is honoured rather than flattened: two dots
        # is the sibling package, which is a different module entirely.
        assert "app.analysis.market" in seen, seen
    finally:
        module.unlink()


def test_the_package_scan_reaches_a_subpackage(tmp_path):
    """`glob('*.py')` would have let a subpackage exist unscanned."""
    package = BACKEND / "app" / "analysis" / "empirical" / "_scan_probe_pkg"
    package.mkdir()
    (package / "inner.py").write_text("import app.market\n", encoding="utf-8")
    try:
        found = package_sources(BACKEND / "app" / "analysis" / "empirical")
        assert (package / "inner.py") in found
    finally:
        (package / "inner.py").unlink()
        package.rmdir()


def test_the_price_history_protocols_live_outside_app_market():
    """`gap_finder.PriceHistory` and `event_study.ReturnHistory` are the two
    interfaces the studies compute over. If either lived in `app/market/*`,
    the import ban above would be unsatisfiable and somebody would relax it."""
    from app.analysis.empirical import event_study, gap_finder

    assert gap_finder.PriceHistory.__module__ == "app.analysis.empirical.gap_finder"
    assert event_study.ReturnHistory.__module__ == "app.analysis.empirical.event_study"


def test_no_v5_package_reads_a_market_field_by_name():
    """The fields `app/market/*` writes onto a V4 row. Reading one by name
    would be the same violation as importing the module.

    ONE EXEMPTION, and it is the point of Task 5.5 rather than a hole in it:
    `divergence.py` is the boundary module whose entire job is to RECORD a
    market disagreement. It never reads the number -- the caller passes it in
    as a float -- and it never lets it reach a verdict, which the byte-identity
    test below is what proves. Every other V5 module must not name the field
    at all.
    """
    from tests.phase5.conftest import code_lines

    banned = ("excess_move_pct", "return_1m", "return_3m", "price_at_analysis",
              "reaction_direction", "volume_z")
    exempt = {"divergence.py"}
    for package in V5_PACKAGES.values():
        for path in package_sources(package):
            if path.name in exempt:
                continue
            for number, line in code_lines(path):
                for needle in banned:
                    assert needle not in line, (
                        f"{path.relative_to(BACKEND)}:{number} reads {needle}")


def test_the_exempt_divergence_module_still_takes_the_move_as_an_argument():
    """The exemption above is only safe because the number ARRIVES; it is
    never fetched. `divergence.py` imports nothing from app.market (asserted
    package-wide above) and `queue_market_divergence` takes the excess move as
    a parameter."""
    import inspect

    from app.analysis.empirical.divergence import queue_market_divergence

    parameters = inspect.signature(queue_market_divergence).parameters
    assert "excess_move_pct" in parameters


# --- divergence is a monitoring signal, never a correction ------------------

@pytest.mark.parametrize("direction,excess,expected", [
    ("POSITIVE", 4.0, "AGREE"),
    ("POSITIVE", -4.0, "DIVERGENT"),
    ("NEGATIVE", 4.0, "DIVERGENT"),
    ("NEGATIVE", -4.0, "AGREE"),
    ("POSITIVE", 0.2, "WITHIN_THRESHOLD"),
    ("MIXED", -9.0, "NOT_APPLICABLE"),
    ("UNCERTAIN", -9.0, "NOT_APPLICABLE"),
])
def test_divergence_status_is_a_pure_function_of_two_numbers(
        direction, excess, expected):
    from app.analysis.empirical.divergence import divergence_status

    assert divergence_status(direction, excess, threshold_pct=3.0) == expected


def test_an_unknown_excess_move_is_not_a_divergence():
    from app.analysis.empirical.divergence import divergence_status

    assert divergence_status("POSITIVE", None, threshold_pct=3.0) == "NO_DATA"


def test_a_divergence_writes_to_the_review_queue(phase5_session):
    from app.analysis.empirical.divergence import queue_market_divergence

    review_id = queue_market_divergence(
        phase5_session, event_id=FIXTURE_EVENT_ID, company_id=FIXTURE_COMPANY_ID,
        fundamental_direction="POSITIVE", excess_move_pct=-4.2,
        threshold_pct=3.0, created_at=FIXTURE_NOW)
    assert review_id is not None
    row = phase5_session.execute(text(
        "SELECT kind, status FROM divergence_review WHERE review_id = :id"),
        {"id": review_id}).one()
    assert row[0] == "MARKET_DIVERGENCE"
    assert row[1] == "OPEN"


def test_an_agreeing_move_queues_nothing(phase5_session):
    from app.analysis.empirical.divergence import queue_market_divergence

    assert queue_market_divergence(
        phase5_session, event_id=FIXTURE_EVENT_ID, company_id=FIXTURE_COMPANY_ID,
        fundamental_direction="POSITIVE", excess_move_pct=4.2,
        threshold_pct=3.0, created_at=FIXTURE_NOW) is None
    assert phase5_session.execute(text(
        "SELECT count(*) FROM divergence_review")).scalar() == 0


def test_queueing_a_divergence_leaves_the_company_impact_byte_identical(phase5_session):
    """'Do not resolve silently in either direction.' The queue is the only
    thing that happens."""
    from app.analysis.empirical.divergence import queue_market_divergence
    from app.core.reducer import serialize_company_impact

    impact = impact_with_empirical()
    before = serialize_company_impact(impact)
    queue_market_divergence(
        phase5_session, event_id=FIXTURE_EVENT_ID, company_id=FIXTURE_COMPANY_ID,
        fundamental_direction=impact.net_effect, excess_move_pct=-9.9,
        threshold_pct=3.0, created_at=FIXTURE_NOW)
    assert serialize_company_impact(impact) == before
    assert impact.publication_tier == "PRIMARY"


def test_the_divergence_module_never_writes_company_impact():
    from tests.phase5.conftest import code_lines

    path = BACKEND / "app" / "analysis" / "empirical" / "divergence.py"
    for number, line in code_lines(path):
        assert "company_impact" not in line, (
            f"divergence.py:{number} touches company_impact -- divergence is a "
            "monitoring signal, never a correction")
