"""TASK 3.5 -- reverse event studies as a blind-spot detector.

The §10 event-study machinery run BACKWARDS: instead of checking whether a
candidate moved, ask which industries moved and which of them the graph
cannot explain. The output is a work queue for graph authoring, never a
publication.

THE DISCIPLINE (addendum A3.2, invariant 7): an empirically discovered
relationship may NEVER publish until a human authors and reviews a mechanism
explaining it. `test_an_empirical_only_relationship_has_no_publication_path`
is the proof that no such path exists.

ZERO NETWORK. This module computes over a `PriceHistory` handed to it. It
fetches nothing, ever -- asserted by an ast scan, because "we would never do
that" is not a guarantee.
"""
import ast
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.phase3.conftest import (
    FIXTURE_TODAY, TAG_PETCHEM, code_lines, make_company, seed_edge,
    seed_exposure,
)

BACKEND = Path(__file__).resolve().parents[2]
GAP_FINDER = BACKEND / "app" / "analysis" / "empirical" / "gap_finder.py"

BANNED_NETWORK_MODULES = (
    "yfinance", "requests", "httpx", "urllib", "urllib3", "socket", "aiohttp",
    "http", "ftplib", "telnetlib", "smtplib",
)


# --- zero network -----------------------------------------------------------

def test_the_empirical_package_imports_nothing_that_opens_a_socket():
    package = BACKEND / "app" / "analysis" / "empirical"
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                assert root not in BANNED_NETWORK_MODULES, (
                    f"{path.name} imports {name}: the gap finder never "
                    "fetches -- it computes over a PriceHistory handed to it")


def test_no_module_in_the_empirical_package_names_a_url():
    package = BACKEND / "app" / "analysis" / "empirical"
    for path in sorted(package.glob("*.py")):
        for number, line in code_lines(path):
            assert "http://" not in line and "https://" not in line, (
                f"{path.name}:{number} names a URL")


# --- a synthetic price history ---------------------------------------------

class SyntheticHistory:
    """The `PriceHistory` interface, satisfied by arithmetic.

    Real price history for the whole listed universe over 8+ years does not
    exist in this repo and acquiring it is the owner's act (DATA_GAPS §7).
    Everything about the computation that can be tested without it is tested
    here, on returns a test wrote.
    """

    def __init__(self, abnormal_returns):
        # {(company_id, event_date, window_days): abnormal_return}
        self._returns = dict(abnormal_returns)

    def cumulative_abnormal_return(self, company_id, event_date, window_days):
        return self._returns.get((company_id, event_date, window_days))


def _events(n):
    return tuple(date(2222, 1, 1) + timedelta(days=7 * i) for i in range(n))


def _history(reacting, inert, events, *, reaction=-0.04, noise=0.0005):
    returns = {}
    for index, event_date in enumerate(events):
        for company_id in reacting:
            # consistently negative, with a deterministic wobble
            returns[(company_id, event_date, 5)] = reaction + noise * (index % 3)
        for company_id in inert:
            # alternating sign: no consistent reaction at all
            returns[(company_id, event_date, 5)] = noise * (1 if index % 2 else -1)
    return SyntheticHistory(returns)


@pytest.fixture()
def gap_universe(ripple_session):
    """Six tyre names that all react to crude, six IT names that do not, and
    a graph that explains neither."""
    session = ripple_session
    reacting, inert = [], []
    for i in range(6):
        reacting.append(make_company(
            session, ticker=f"FIXTYRE{i}", name=f"FIXTURE TYRE {i} LTD",
            sector="Auto Ancillary", sub_sector="tyres", market_cap=100.0 + i).id)
        inert.append(make_company(
            session, ticker=f"FIXIT{i}", name=f"FIXTURE IT {i} LTD",
            sector="IT", sub_sector="it_services", market_cap=100.0 + i).id)
    session.flush()
    return {"reacting": tuple(reacting), "inert": tuple(inert)}


# --- the computation --------------------------------------------------------

def test_an_injected_reacting_industry_reaches_the_coverage_gap_table(
        ripple_session, gap_universe):
    from app.analysis.empirical.gap_finder import find_coverage_gaps

    events = _events(20)
    history = _history(gap_universe["reacting"], gap_universe["inert"], events)
    gaps = find_coverage_gaps(ripple_session, variable="BRENT_CRUDE", sign="UP",
                              event_dates=events, history=history,
                              as_of=FIXTURE_TODAY)
    assert [gap.industry for gap in gaps] == ["tyres"]
    assert gaps[0].n == 120                    # 6 names x 20 events
    assert gaps[0].median_car < 0
    assert gaps[0].sign_consistency >= 0.65

    rows = list(ripple_session.execute(text(
        "SELECT industry, variable, sign, n FROM coverage_gap")))
    assert [tuple(row) for row in rows] == [("tyres", "BRENT_CRUDE", "UP", 120)]


def test_an_industry_the_graph_explains_is_not_a_gap(ripple_session, gap_universe):
    """Non-vacuous companion: the same reacting industry, with an authored
    mechanism reaching it, is EXPLAINED and produces no gap."""
    from app.analysis.empirical.gap_finder import find_coverage_gaps

    seed_edge(ripple_session, edge_id="explains-tyres", from_node="BRENT_CRUDE",
              to_node="tyres", exposure_tag=TAG_PETCHEM)
    for company_id in gap_universe["reacting"]:
        seed_exposure(ripple_session, exposure_id=f"x-{company_id}",
                      company_id=company_id, exposure_tag=TAG_PETCHEM,
                      share_of_base=0.25)

    events = _events(20)
    history = _history(gap_universe["reacting"], gap_universe["inert"], events)
    gaps = find_coverage_gaps(ripple_session, variable="BRENT_CRUDE", sign="UP",
                              event_dates=events, history=history,
                              as_of=FIXTURE_TODAY)
    assert gaps == ()


def test_an_industry_below_the_sample_floor_is_not_retained(ripple_session,
                                                            gap_universe):
    from app.analysis.empirical.gap_finder import find_coverage_gaps

    events = _events(2)                      # 6 x 2 = 12 < 15
    history = _history(gap_universe["reacting"], gap_universe["inert"], events)
    gaps = find_coverage_gaps(ripple_session, variable="BRENT_CRUDE", sign="UP",
                              event_dates=events, history=history,
                              as_of=FIXTURE_TODAY)
    assert gaps == ()


def test_an_industry_with_no_consistent_sign_is_not_retained(ripple_session,
                                                             gap_universe):
    from app.analysis.empirical.gap_finder import find_coverage_gaps

    events = _events(20)
    history = _history((), gap_universe["reacting"] + gap_universe["inert"], events)
    gaps = find_coverage_gaps(ripple_session, variable="BRENT_CRUDE", sign="UP",
                              event_dates=events, history=history,
                              as_of=FIXTURE_TODAY)
    assert gaps == ()


def test_gaps_are_ranked_by_absolute_car_times_n_times_market_cap(
        ripple_session, gap_universe):
    from app.analysis.empirical.gap_finder import find_coverage_gaps

    strong = [make_company(ripple_session, ticker=f"FIXPNT{i}",
                           name=f"FIXTURE PAINT {i} LTD", sector="Chemicals",
                           sub_sector="paints", market_cap=10000.0).id
              for i in range(6)]
    ripple_session.flush()
    events = _events(20)
    returns = {}
    for index, event_date in enumerate(events):
        for company_id in gap_universe["reacting"]:
            returns[(company_id, event_date, 5)] = -0.01
        for company_id in strong:
            returns[(company_id, event_date, 5)] = -0.06
        for company_id in gap_universe["inert"]:
            returns[(company_id, event_date, 5)] = 0.0005 * (1 if index % 2 else -1)
    gaps = find_coverage_gaps(ripple_session, variable="BRENT_CRUDE", sign="UP",
                              event_dates=events, history=SyntheticHistory(returns),
                              as_of=FIXTURE_TODAY)
    assert [gap.industry for gap in gaps] == ["paints", "tyres"]
    assert gaps[0].priority > gaps[1].priority


def test_the_finder_is_idempotent(ripple_session, gap_universe):
    """It is a queue, not a log: running it twice must not double the rows."""
    from app.analysis.empirical.gap_finder import find_coverage_gaps

    events = _events(20)
    history = _history(gap_universe["reacting"], gap_universe["inert"], events)
    for _ in range(2):
        find_coverage_gaps(ripple_session, variable="BRENT_CRUDE", sign="UP",
                           event_dates=events, history=history, as_of=FIXTURE_TODAY)
    assert ripple_session.execute(text(
        "SELECT count(*) FROM coverage_gap")).scalar() == 1


def test_a_company_with_no_price_history_is_omitted_not_zero_filled(
        ripple_session, gap_universe):
    """A missing return is missing. Treating it as 0.0 would dilute every
    median in the table with data that does not exist."""
    from app.analysis.empirical.gap_finder import industry_reactions

    events = _events(20)
    history = _history(gap_universe["reacting"][:3], gap_universe["inert"], events)
    rows = {row.industry: row for row in industry_reactions(
        ripple_session, event_dates=events, history=history)}
    assert rows["tyres"].n == 60             # 3 names with history, not 6


# --- the hard rule ----------------------------------------------------------

def test_an_empirical_only_relationship_has_no_publication_path(ripple_session,
                                                                gap_universe):
    """THE test this task exists for. A coverage_gap row is a statistical
    observation with no mechanism. Walk it as far towards publication as the
    system allows and it must end at REJECTED, for the stated reason.

    Three independent locks, each asserted:
      1. the gap queue writes no mechanism_edge at all;
      2. an EMPIRICAL edge without a reviewer cannot be traversed, so
         discovery never produces a candidate from one;
      3. the gate refuses SECONDARY_RIPPLE with a null mechanism_id.
    """
    from app.analysis.empirical.gap_finder import find_coverage_gaps
    from app.core.config_loader import load_gate_config
    from app.core.gates import evaluate
    from app.graph.traverse import traverse
    from tests.phase3.test_ripple_gates import ripple_draft

    events = _events(20)
    history = _history(gap_universe["reacting"], gap_universe["inert"], events)
    gaps = find_coverage_gaps(ripple_session, variable="BRENT_CRUDE", sign="UP",
                              event_dates=events, history=history,
                              as_of=FIXTURE_TODAY)
    assert gaps                                   # the signal was detected

    # 1. no edge was created by detecting it
    assert ripple_session.execute(text(
        "SELECT count(*) FROM mechanism_edge")).scalar() == 0

    # 2. even if someone records the observation AS an edge, it is inert
    seed_edge(ripple_session, edge_id="empirical-tyres", from_node="BRENT_CRUDE",
              to_node="tyres", exposure_tag=TAG_PETCHEM, derivation="EMPIRICAL",
              reviewed_by=None)
    assert traverse(ripple_session, "BRENT_CRUDE", as_of=FIXTURE_TODAY) == ()

    # 3. and a draft with no mechanism_id is REJECTED by the gate
    result = evaluate(ripple_draft(mechanism_id=None), load_gate_config())
    assert result.tier == "REJECTED"
    assert result.rejection_reason == "SECONDARY_REQUIRES_MECHANISM"


def test_the_gap_queue_is_visible_in_the_review_ui(ripple_engine, ripple_session,
                                                   gap_universe):
    from fastapi.testclient import TestClient

    from app.analysis.empirical.gap_finder import find_coverage_gaps
    from tools.ledger_ui import build_app

    events = _events(20)
    history = _history(gap_universe["reacting"], gap_universe["inert"], events)
    find_coverage_gaps(ripple_session, variable="BRENT_CRUDE", sign="UP",
                       event_dates=events, history=history, as_of=FIXTURE_TODAY)
    ripple_session.commit()

    client = TestClient(build_app(ripple_engine))
    response = client.get("/graph/gaps")
    assert response.status_code == 200
    assert "tyres" in response.text
    assert "BRENT_CRUDE" in response.text
