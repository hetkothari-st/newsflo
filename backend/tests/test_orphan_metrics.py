"""The OTHER_LABEL fall-through is counted, and counting it changes nothing.

`ripple_layers._label_for` drops an unresolvable `causal_parent_id` into
OTHER_LABEL with no log, no counter and no metric. `app/market/orphan_metrics.py`
observes that; these tests pin BOTH halves -- that it counts correctly, and
that it is incapable of altering a render.

SCOPE, stated so nobody reads the number as more than it is: OTHER_LABEL only
exists on the strict/gated section path, so an ungated alert contributes
nothing here even when its stored ids are orphans. The metric measures what
RENDERS, which is what it is for.
"""
import logging
from dataclasses import dataclass

import pytest

from app.market.orphan_metrics import (
    OrphanReport, log_orphan_report, orphan_report,
)

OTHER = "other verified mechanisms"


@dataclass
class FakeCompany:
    causal_parent_id: str | None
    label: str


def label_for(alert_company):
    return alert_company.label


def section(title):
    return {"title": title, "rows": []}


# --- counting ---------------------------------------------------------------

def test_a_clean_alert_reports_nothing_and_logs_nothing(caplog):
    companies = [FakeCompany("upstream_realization", "Upstream oil producers"),
                 FakeCompany("tyre_input_cost", "Tyres & rubber")]
    report = orphan_report(
        alert_id=1, alert_companies=companies,
        sections=[section("Positive — Upstream oil producers")],
        label_for=label_for, other_label=OTHER)

    assert report.clean
    assert report.orphan_parent_ids == ()
    assert report.orphan_row_count == 0
    with caplog.at_level(logging.INFO, logger="newsflo.ripple"):
        log_orphan_report(report)
    assert caplog.records == []


def test_rows_and_distinct_ids_are_counted_separately():
    """Five rows under one unknown id is a NAMING gap. Five rows under five
    ids is also a MERGE -- V4 renders them as one section. One number cannot
    say both."""
    companies = [
        FakeCompany("shock_subsidy_receivable_wc", OTHER),
        FakeCompany("shock_subsidy_receivable_wc", OTHER),
        FakeCompany("shock_subsidy_receivable_wc", OTHER),
        FakeCompany("shock_subsidy_overrun", OTHER),
        FakeCompany("shock_policy_balanced_nutrition", OTHER),
        FakeCompany("refiner_marketing_margin", "Oil marketing & refining"),
    ]
    report = orphan_report(
        alert_id=21, alert_companies=companies,
        sections=[section("Negative — " + OTHER),
                  section("Secondary — " + OTHER),
                  section("Positive — Oil marketing & refining")],
        label_for=label_for, other_label=OTHER)

    assert report.orphan_row_count == 5
    assert report.orphan_parent_count == 3
    assert report.orphan_parent_ids == (
        "shock_policy_balanced_nutrition", "shock_subsidy_overrun",
        "shock_subsidy_receivable_wc")
    assert report.other_label_section_count == 2
    assert report.section_count == 3
    assert not report.clean


def test_ids_are_deduplicated_and_sorted_so_the_metric_is_stable():
    companies = [FakeCompany("z_shock", OTHER), FakeCompany("a_shock", OTHER),
                 FakeCompany("z_shock", OTHER)]
    report = orphan_report(alert_id=2, alert_companies=companies, sections=[],
                           label_for=label_for, other_label=OTHER)
    assert report.orphan_parent_ids == ("a_shock", "z_shock")


def test_a_null_causal_parent_is_recorded_as_event_not_dropped():
    report = orphan_report(
        alert_id=3, alert_companies=[FakeCompany(None, OTHER)], sections=[],
        label_for=label_for, other_label=OTHER)
    assert report.orphan_parent_ids == ("event",)
    assert report.orphan_row_count == 1


def test_a_resolver_that_raises_cannot_break_the_metric():
    """A metric must never be able to break a render."""
    def exploding(_alert_company):
        raise RuntimeError("resolver blew up")

    report = orphan_report(alert_id=4, alert_companies=[FakeCompany("x", OTHER)],
                           sections=[], label_for=exploding, other_label=OTHER)
    assert report.clean


# --- logging ----------------------------------------------------------------

def test_one_structured_record_per_alert_with_every_field(caplog):
    report = OrphanReport(alert_id=21,
                          orphan_parent_ids=("a", "b"), orphan_row_count=5,
                          other_label_section_count=3, section_count=3)
    with caplog.at_level(logging.INFO, logger="newsflo.ripple"):
        returned = log_orphan_report(report)

    assert returned is report, "the report is returned unchanged"
    assert len(caplog.records) == 1, "one record per alert, never one per row"
    record = caplog.records[0]
    assert record.levelno == logging.INFO, (
        "INFO, not WARNING: this is V4's expected steady state and warning on "
        "every alert trains people to ignore warnings")
    assert record.alert_id == 21
    assert record.orphan_parent_ids == "a,b"
    assert record.orphan_parent_count == 2
    assert record.orphan_row_count == 5
    assert record.other_label_section_count == 3
    assert record.section_count == 3


# --- no behaviour change ----------------------------------------------------

def test_the_metric_module_cannot_write_or_render():
    """Source scan: it counts. It does not touch a database, a section, or a
    label."""
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "market"
              / "orphan_metrics.py").read_text(encoding="utf-8")
    for banned in ("INSERT INTO", "UPDATE ", "DELETE FROM", "session",
                   "_TAXONOMY_LABELS", "resolve_mechanism_id"):
        assert banned not in source, (
            f"orphan_metrics.py references {banned!r} -- it observes a render, "
            f"it does not participate in one")


def test_the_call_site_is_a_bare_statement_and_cannot_alter_the_render():
    """AST-level: in `_strict_sections`, `log_orphan_report(...)` must be an
    expression STATEMENT, and the return that follows must be the bare name
    `layers`.

    Asserted structurally rather than by monkeypatching a spy, because the
    defect worth preventing is someone later writing
    `layers = log_orphan_report(...)` or `return [s for s in layers if ...]`
    -- a metric that started filtering the render. A spy cannot see that; the
    syntax tree can.
    """
    import ast
    from pathlib import Path

    path = (Path(__file__).resolve().parents[1] / "app" / "market"
            / "ripple_layers.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))

    call_sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_strict_sections":
            continue
        body = node.body
        for index, statement in enumerate(body):
            called = (isinstance(statement, ast.Expr)
                      and isinstance(statement.value, ast.Call)
                      and getattr(statement.value.func, "id", "")
                      == "log_orphan_report")
            if not called:
                assert not (isinstance(statement, ast.Assign)
                            and "log_orphan_report" in ast.dump(statement)), (
                    "log_orphan_report's result is being assigned -- the "
                    "metric must not feed anything")
                continue
            call_sites.append(statement)
            following = body[index + 1]
            assert isinstance(following, ast.Return), (
                "the observation must be the last thing before the return")
            assert isinstance(following.value, ast.Name) \
                and following.value.id == "layers", (
                "_strict_sections must return the bare `layers` it assembled, "
                "not a value derived from the metric")

    assert len(call_sites) == 1, (
        "expected exactly one orphan-metric call site in _strict_sections, "
        f"found {len(call_sites)}")


@pytest.mark.parametrize("title, expected", [
    ("Negative — other verified mechanisms", 1),
    ("Secondary — other verified mechanisms", 1),
    ("Positive — Upstream oil producers", 0),
])
def test_section_counting_matches_on_the_rendered_title(title, expected):
    report = orphan_report(alert_id=5, alert_companies=[],
                           sections=[section(title)],
                           label_for=label_for, other_label=OTHER)
    assert report.other_label_section_count == expected
