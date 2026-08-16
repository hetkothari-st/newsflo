"""TASK 3.3 -- discovery is a query, not a recollection.

The bug being fixed: discovery anchored on companies named in the article, so
a crude shock surfaced refiners (mentioned) and never surfaced paints or
tyres (not mentioned, but exposed). MECHANISM discovery finds them from the
ledger, deterministically, whether or not any model has heard of them.
"""
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text

from tests.phase3.conftest import (
    FIXTURE_TODAY, TAG_ATF, TAG_CRUDE_DIRECT, TAG_FREIGHT, TAG_PETCHEM,
    TAG_RUBBER, make_company, seed_edge, seed_exposure, seed_supply_link,
)

BACKEND = Path(__file__).resolve().parents[2]
DISCOVERY_YAML = BACKEND / "config" / "discovery.yaml"


# --- config -----------------------------------------------------------------

def test_the_discovery_config_carries_the_phase_files_thresholds():
    raw = yaml.safe_load(DISCOVERY_YAML.read_text(encoding="utf-8"))
    assert raw["distance_thresholds"] == {1: 0.02, 2: 0.05, 3: 0.10}
    assert raw["max_candidates_per_event"] == 250
    assert raw["peer_closure_min_members"] == 2
    assert raw["peer_closure_threshold"] == 0.08


def test_the_engine_holds_no_threshold_of_its_own():
    """Same discipline as Phase 0's gate: the module reads policy, it does
    not carry it."""
    import re

    from tests.phase3.conftest import code_lines

    source = BACKEND / "app" / "discovery" / "engine.py"
    for number, line in code_lines(source):
        for literal in re.findall(r"(?<![\w.])\d\.\d+", line):
            # 0.0 and 1.0 are identities (an absent prior, an unweighted
            # factor), not policy. Anything between them is a threshold and
            # belongs in the YAML.
            if literal in ("0.0", "1.0"):
                continue
            pytest.fail(f"engine.py:{number} carries a threshold literal "
                        f"{literal}: thresholds live in config/discovery.yaml")


# --- fixture universe -------------------------------------------------------

@pytest.fixture()
def crude_universe(ripple_session):
    """A crude shock, a graph that reaches petchem and rubber, and six
    companies -- two of them named in the article, four of them not.

    Nothing here is real. The point is the SHAPE: the four unmentioned names
    are reachable only through the mechanism graph plus the ledger.
    """
    session = ripple_session
    refiner = make_company(session, ticker="FIXREF", name="FIXTURE REFINING LTD",
                           sector="Energy", sub_sector="oil_marketing",
                           market_cap=1000.0)
    airline = make_company(session, ticker="FIXAIR", name="FIXTURE AIRWAYS LTD",
                           sector="Transport", sub_sector="aviation",
                           market_cap=500.0)
    paint_a = make_company(session, ticker="FIXPNT1", name="FIXTURE PAINTS ONE LTD",
                           sector="Chemicals", sub_sector="paints", market_cap=800.0)
    paint_b = make_company(session, ticker="FIXPNT2", name="FIXTURE PAINTS TWO LTD",
                           sector="Chemicals", sub_sector="paints", market_cap=400.0)
    tyre_a = make_company(session, ticker="FIXTYR1", name="FIXTURE TYRES ONE LTD",
                          sector="Auto Ancillary", sub_sector="tyres", market_cap=600.0)
    tyre_b = make_company(session, ticker="FIXTYR2", name="FIXTURE TYRES TWO LTD",
                          sector="Auto Ancillary", sub_sector="tyres", market_cap=300.0)

    # the graph: crude -> (d1) atf ; crude -> naphtha -> (d2) petchem, rubber
    seed_edge(session, edge_id="e-atf", from_node="BRENT_CRUDE", to_node="atf",
              exposure_tag=TAG_ATF, distance=1)
    seed_edge(session, edge_id="e-naphtha", from_node="BRENT_CRUDE",
              to_node="naphtha", exposure_tag=TAG_CRUDE_DIRECT, distance=1)
    seed_edge(session, edge_id="e-petchem", from_node="naphtha",
              to_node="petchem", exposure_tag=TAG_PETCHEM, distance=1)
    seed_edge(session, edge_id="e-rubber", from_node="naphtha",
              to_node="synthetic_rubber", exposure_tag=TAG_RUBBER, distance=1)

    seed_exposure(session, exposure_id="x-air", company_id=airline.id,
                  exposure_tag=TAG_ATF, share_of_base=0.35)
    seed_exposure(session, exposure_id="x-pnt1", company_id=paint_a.id,
                  exposure_tag=TAG_PETCHEM, share_of_base=0.30)
    seed_exposure(session, exposure_id="x-pnt2", company_id=paint_b.id,
                  exposure_tag=TAG_PETCHEM, share_of_base=0.22)
    seed_exposure(session, exposure_id="x-tyr1", company_id=tyre_a.id,
                  exposure_tag=TAG_RUBBER, share_of_base=0.28)
    seed_exposure(session, exposure_id="x-tyr2", company_id=tyre_b.id,
                  exposure_tag=TAG_RUBBER, share_of_base=0.19)
    session.flush()
    return {"refiner": refiner, "airline": airline, "paint_a": paint_a,
            "paint_b": paint_b, "tyre_a": tyre_a, "tyre_b": tyre_b}


def crude_shock():
    from app.discovery.engine import DiscoveryShock

    return DiscoveryShock(shock_id="fixture:crude-up", variable="BRENT_CRUDE",
                          sign="UP", magnitude_pct=6.0)


def crude_event(mentions=("FIXREF",)):
    from app.discovery.engine import DiscoveryEvent

    return DiscoveryEvent(event_id="fixture:event-crude",
                          mentions=tuple(mentions), shocks=(crude_shock(),))


# --- 1. the recall fix ------------------------------------------------------

def test_a_crude_shock_surfaces_companies_absent_from_the_article(
        ripple_session, crude_universe):
    from app.discovery.engine import discover

    pool = discover(ripple_session, crude_event(), as_of=FIXTURE_TODAY)
    found = {c.company_id for c in pool.candidates}

    assert crude_universe["paint_a"].id in found
    assert crude_universe["tyre_a"].id in found
    mechanism = {c.company_id for c in pool.candidates
                 if c.discovery_source == "MECHANISM"}
    assert crude_universe["paint_a"].id in mechanism
    assert crude_universe["tyre_a"].id in mechanism


def test_the_mentioned_company_is_recorded_as_a_mention(ripple_session,
                                                        crude_universe):
    from app.discovery.engine import discover

    pool = discover(ripple_session, crude_event(), as_of=FIXTURE_TODAY)
    by_id = {c.company_id: c for c in pool.candidates}
    assert by_id[crude_universe["refiner"].id].discovery_source == "MENTION"


def test_every_mechanism_candidate_carries_the_edge_that_found_it(
        ripple_session, crude_universe):
    from app.discovery.engine import discover

    pool = discover(ripple_session, crude_event(), as_of=FIXTURE_TODAY)
    for candidate in pool.candidates:
        if candidate.discovery_source != "MECHANISM":
            continue
        assert candidate.mechanism_id, candidate
        assert candidate.via_tag, candidate
        assert candidate.graph_distance is not None, candidate


# --- 2. the four fields stay four fields ------------------------------------

def test_discovery_source_directness_graph_distance_and_tier_are_four_fields(
        ripple_session, crude_universe):
    """Invariant 4. A candidate carries a discovery source, a graph distance
    and (once resolved) a via_tag; it carries NO directness and NO tier,
    because discovery does not decide either -- and there is no field on it
    that fuses any two of them."""
    from dataclasses import fields

    from app.discovery.engine import Candidate, discover

    names = {f.name for f in fields(Candidate)}
    assert {"discovery_source", "graph_distance", "via_tag", "mechanism_id"} <= names
    assert "directness" not in names
    assert "publication_tier" not in names and "tier" not in names
    for name in names:
        fused = sum(token in name for token in
                    ("discovery_source", "directness", "graph_distance", "tier"))
        assert fused <= 1, f"Candidate.{name} fuses two separation concepts"

    pool = discover(ripple_session, crude_event(), as_of=FIXTURE_TODAY)
    serialized = pool.serialize()
    for row in serialized:
        assert set(row) >= {"discovery_source", "via_tag", "mechanism_id",
                            "graph_distance"}
        assert "directness" not in row


# --- 3. bounds and thresholds -----------------------------------------------

def test_the_distance_threshold_rises_with_distance(ripple_session, crude_universe):
    """A d2 candidate must clear 0.05, not 0.02. Seed a paint company at 3%:
    it would qualify at d1 and must NOT at d2."""
    from app.discovery.engine import discover

    thin = make_company(ripple_session, ticker="FIXPNT3",
                        name="FIXTURE PAINTS THREE LTD", sector="Chemicals",
                        sub_sector="paints", market_cap=100.0)
    seed_exposure(ripple_session, exposure_id="x-pnt3", company_id=thin.id,
                  exposure_tag=TAG_PETCHEM, share_of_base=0.03)

    pool = discover(ripple_session, crude_event(), as_of=FIXTURE_TODAY)
    mechanism = {c.company_id for c in pool.candidates
                 if c.discovery_source == "MECHANISM"}
    assert thin.id not in mechanism, (
        "a 3% exposure reached at graph distance 2 cleared the d1 threshold")


def test_the_pool_respects_its_maximum_size(ripple_session, crude_universe):
    from app.discovery.config import DiscoveryConfig
    from app.discovery.engine import discover

    config = DiscoveryConfig(distance_thresholds={1: 0.02, 2: 0.05, 3: 0.10},
                             max_candidates_per_event=2,
                             peer_closure_min_members=2,
                             peer_closure_threshold=0.08,
                             max_depth=3, modelled_shock_variables=("BRENT_CRUDE",))
    pool = discover(ripple_session, crude_event(), as_of=FIXTURE_TODAY,
                    config=config)
    assert len(pool.candidates) == 2


def test_the_pool_never_grows_past_its_bound_even_while_filling(ripple_session,
                                                                crude_universe):
    """M6. `max_size` bounds the pool's GROWTH, not just its output. A pool
    that accumulates ten thousand candidates and slices at the end is a
    memory profile nobody asked for, and it hides a runaway from every test
    that only inspects the result."""
    from app.discovery.config import DiscoveryConfig
    from app.discovery.engine import Candidate, CandidatePool

    pool = CandidatePool(max_size=3)
    for company_id in range(20):
        pool.add(Candidate(company_id=company_id, discovery_source="MECHANISM",
                           via_tag=TAG_PETCHEM, mechanism_id="e",
                           graph_distance=2, shock_id="s",
                           share_of_base=0.01 * (company_id + 1),
                           expected_materiality_prior=0.01 * (company_id + 1)))
        assert pool.size <= 3, f"pool grew to {pool.size} while filling"
    # and the survivors are the strongest, not the first three seen
    assert [c.company_id for c in pool.candidates] == [19, 18, 17]


def test_mentions_survive_the_bound_and_the_deviation_is_documented(
        ripple_session, crude_universe):
    """M6. A mention ranks above every mechanism find by construction (its
    prior is infinite), so with a pool smaller than the mention count the
    pool is all mentions. That is deliberate -- a company the article NAMES
    must not be dropped to make room for one the ledger found -- and the
    engine says so in writing."""
    from pathlib import Path

    from app.discovery.config import DiscoveryConfig
    from app.discovery.engine import discover

    source = (BACKEND / "app" / "discovery" / "engine.py").read_text(encoding="utf-8")
    assert "mentions always survive" in source.lower(), (
        "engine.py does not document the mentions-always-survive deviation")

    config = DiscoveryConfig(distance_thresholds={1: 0.02, 2: 0.05, 3: 0.10},
                             max_candidates_per_event=1,
                             peer_closure_min_members=2,
                             peer_closure_threshold=0.08,
                             max_depth=3, modelled_shock_variables=("BRENT_CRUDE",))
    pool = discover(ripple_session, crude_event(), as_of=FIXTURE_TODAY,
                    config=config)
    assert len(pool.candidates) == 1
    assert pool.candidates[0].discovery_source == "MENTION"


def test_the_pool_is_ranked_by_the_expected_materiality_prior(
        ripple_session, crude_universe):
    """The prior orders the pool; it is never published and never becomes a
    materiality. Bigger exposure share ranks first among mechanism finds."""
    from app.discovery.engine import discover

    pool = discover(ripple_session, crude_event(), as_of=FIXTURE_TODAY)
    mechanism = [c for c in pool.candidates if c.discovery_source == "MECHANISM"]
    priors = [c.expected_materiality_prior for c in mechanism]
    assert priors == sorted(priors, reverse=True)


def test_discovery_is_deterministic(ripple_session, crude_universe):
    from app.discovery.engine import discover

    first = discover(ripple_session, crude_event(), as_of=FIXTURE_TODAY).serialize()
    second = discover(ripple_session, crude_event(), as_of=FIXTURE_TODAY).serialize()
    assert first == second


# --- 4. the graph's own rules -----------------------------------------------

def test_an_io_table_edge_without_a_reviewer_cannot_be_traversed(ripple_session):
    from app.graph.traverse import traverse

    seed_edge(ripple_session, edge_id="e-io", from_node="BRENT_CRUDE",
              to_node="petchem", exposure_tag=TAG_PETCHEM,
              derivation="IO_TABLE", reviewed_by=None, io_total_coeff=0.31)
    assert traverse(ripple_session, "BRENT_CRUDE", as_of=FIXTURE_TODAY) == ()


def test_a_reviewed_io_table_edge_can_be_traversed(ripple_session):
    from app.graph.traverse import traverse

    seed_edge(ripple_session, edge_id="e-io2", from_node="BRENT_CRUDE",
              to_node="petchem", exposure_tag=TAG_PETCHEM,
              derivation="IO_TABLE", reviewed_by="human:fixture-reviewer",
              io_total_coeff=0.31)
    edges = traverse(ripple_session, "BRENT_CRUDE", as_of=FIXTURE_TODAY)
    assert [e.edge_id for e in edges] == ["e-io2"]


def test_an_empirical_edge_without_a_reviewer_cannot_be_traversed(ripple_session):
    from app.graph.traverse import traverse

    seed_edge(ripple_session, edge_id="e-emp", from_node="BRENT_CRUDE",
              to_node="paints", exposure_tag=TAG_PETCHEM,
              derivation="EMPIRICAL", reviewed_by=None)
    assert traverse(ripple_session, "BRENT_CRUDE", as_of=FIXTURE_TODAY) == ()


def test_traversal_stops_at_max_depth(ripple_session):
    from app.graph.traverse import traverse

    seed_edge(ripple_session, edge_id="d1", from_node="V", to_node="a",
              exposure_tag=TAG_PETCHEM)
    seed_edge(ripple_session, edge_id="d2", from_node="a", to_node="b",
              exposure_tag=TAG_PETCHEM)
    seed_edge(ripple_session, edge_id="d3", from_node="b", to_node="c",
              exposure_tag=TAG_PETCHEM)
    seed_edge(ripple_session, edge_id="d4", from_node="c", to_node="d",
              exposure_tag=TAG_PETCHEM)
    edges = traverse(ripple_session, "V", as_of=FIXTURE_TODAY, max_depth=3)
    assert [e.edge_id for e in edges] == ["d1", "d2", "d3"]
    assert [e.graph_distance for e in edges] == [1, 2, 3]


def test_traversal_terminates_on_a_cycle(ripple_session):
    from app.graph.traverse import traverse

    seed_edge(ripple_session, edge_id="c1", from_node="V", to_node="a",
              exposure_tag=TAG_PETCHEM)
    seed_edge(ripple_session, edge_id="c2", from_node="a", to_node="V",
              exposure_tag=TAG_PETCHEM)
    edges = traverse(ripple_session, "V", as_of=FIXTURE_TODAY, max_depth=3)
    assert {e.edge_id for e in edges} == {"c1", "c2"}


def test_an_edge_outside_its_effective_window_is_not_traversed(ripple_session):
    from app.graph.traverse import traverse

    seed_edge(ripple_session, edge_id="expired", from_node="V", to_node="a",
              exposure_tag=TAG_PETCHEM,
              effective_from=FIXTURE_TODAY - timedelta(days=100),
              effective_to=FIXTURE_TODAY - timedelta(days=1))
    assert traverse(ripple_session, "V", as_of=FIXTURE_TODAY) == ()


# --- 5. supply chain and peer closure ---------------------------------------

def test_supply_chain_closure_adds_one_hop_from_the_pool(ripple_session,
                                                          crude_universe):
    from app.discovery.engine import discover

    downstream = make_company(ripple_session, ticker="FIXDWN",
                              name="FIXTURE DOWNSTREAM LTD", sector="Auto",
                              sub_sector="auto_oem", market_cap=900.0)
    seed_supply_link(ripple_session, company_id=downstream.id,
                     counterparty_company_id=crude_universe["tyre_a"].id,
                     relation="SUPPLIER")
    pool = discover(ripple_session, crude_event(), as_of=FIXTURE_TODAY)
    by_id = {c.company_id: c for c in pool.candidates}
    assert downstream.id in by_id
    assert by_id[downstream.id].discovery_source == "SUPPLY_CHAIN"
    assert by_id[downstream.id].graph_distance == (
        by_id[crude_universe["tyre_a"].id].graph_distance + 1)


def _deep_graph(session):
    """A three-hop path to `input:freight_diesel`, so the tag is reached at
    distance 3 and must clear 0.10. Peer closure's 0.08 is LOWER than that --
    which is the only reason a sweep can add anything the walk did not."""
    seed_edge(session, edge_id="g1", from_node="BRENT_CRUDE", to_node="refining",
              exposure_tag=TAG_CRUDE_DIRECT, distance=1)
    seed_edge(session, edge_id="g2", from_node="refining", to_node="diesel",
              exposure_tag=TAG_ATF, distance=1)
    seed_edge(session, edge_id="g3", from_node="diesel", to_node="road_freight",
              exposure_tag=TAG_FREIGHT, distance=1)


def test_peer_closure_sweeps_an_industry_at_a_higher_threshold(ripple_session):
    """Two logistics names clear the d3 bar (0.10), so the industry is swept
    at 0.08 -- which admits a third name the walk had rejected, and still
    refuses a fourth at 3%."""
    from app.discovery.engine import discover

    _deep_graph(ripple_session)
    names = {}
    for ticker, share in (("FIXLOG1", 0.30), ("FIXLOG2", 0.25),
                          ("FIXLOG3", 0.09), ("FIXLOG4", 0.03)):
        company = make_company(ripple_session, ticker=ticker,
                               name=f"{ticker} FIXTURE LTD", sector="Transport",
                               sub_sector="logistics", market_cap=100.0)
        seed_exposure(ripple_session, exposure_id=f"x-{ticker}",
                      company_id=company.id, exposure_tag=TAG_FREIGHT,
                      share_of_base=share)
        names[ticker] = company

    pool = discover(ripple_session, crude_event(mentions=()), as_of=FIXTURE_TODAY)
    by_id = {c.company_id: c for c in pool.candidates}

    assert by_id[names["FIXLOG1"].id].discovery_source == "MECHANISM"
    assert by_id[names["FIXLOG2"].id].discovery_source == "MECHANISM"
    assert names["FIXLOG3"].id in by_id
    assert by_id[names["FIXLOG3"].id].discovery_source == "PEER_CLOSURE"
    assert names["FIXLOG4"].id not in by_id


def test_a_peer_closure_candidate_still_carries_a_mechanism(ripple_session):
    """A swept name is not a name without a reason: it is admitted through
    the same tag and the same edge as its peers, at a looser bar. Without a
    mechanism_id it could never publish as SECONDARY_RIPPLE anyway."""
    from app.discovery.engine import discover

    _deep_graph(ripple_session)
    for ticker, share in (("FIXLOG1", 0.30), ("FIXLOG2", 0.25), ("FIXLOG3", 0.09)):
        company = make_company(ripple_session, ticker=ticker,
                               name=f"{ticker} FIXTURE LTD", sector="Transport",
                               sub_sector="logistics", market_cap=100.0)
        seed_exposure(ripple_session, exposure_id=f"x-{ticker}",
                      company_id=company.id, exposure_tag=TAG_FREIGHT,
                      share_of_base=share)

    pool = discover(ripple_session, crude_event(mentions=()), as_of=FIXTURE_TODAY)
    swept = [c for c in pool.candidates if c.discovery_source == "PEER_CLOSURE"]
    assert swept
    for candidate in swept:
        assert candidate.mechanism_id == "g3"
        assert candidate.via_tag == TAG_FREIGHT
        assert candidate.graph_distance == 3


def test_peer_closure_needs_two_members_before_it_fires(ripple_session):
    from app.discovery.engine import discover

    _deep_graph(ripple_session)
    lone = make_company(ripple_session, ticker="FIXLOG1", name="FIXLOG1 FIXTURE LTD",
                        sector="Transport", sub_sector="logistics", market_cap=100.0)
    near = make_company(ripple_session, ticker="FIXLOG3", name="FIXLOG3 FIXTURE LTD",
                        sector="Transport", sub_sector="logistics", market_cap=100.0)
    seed_exposure(ripple_session, exposure_id="pc-1", company_id=lone.id,
                  exposure_tag=TAG_FREIGHT, share_of_base=0.30)
    seed_exposure(ripple_session, exposure_id="pc-2", company_id=near.id,
                  exposure_tag=TAG_FREIGHT, share_of_base=0.09)

    pool = discover(ripple_session, crude_event(mentions=()), as_of=FIXTURE_TODAY)
    assert near.id not in {c.company_id for c in pool.candidates}


# --- 6. the empty case ------------------------------------------------------

def test_an_empty_ledger_yields_only_mentions(ripple_session):
    """Today's production state. No exposure row, no mechanism candidate --
    and the engine says so rather than falling back on a model."""
    from app.discovery.engine import discover

    make_company(ripple_session, ticker="FIXREF", name="FIXTURE REFINING LTD")
    seed_edge(ripple_session, edge_id="only-edge", from_node="BRENT_CRUDE",
              to_node="petchem", exposure_tag=TAG_PETCHEM)
    pool = discover(ripple_session, crude_event(), as_of=FIXTURE_TODAY)
    assert {c.discovery_source for c in pool.candidates} == {"MENTION"}


def test_an_empty_graph_yields_only_mentions(ripple_session, crude_universe):
    from app.discovery.engine import discover

    ripple_session.execute(text("DELETE FROM mechanism_edge"))
    pool = discover(ripple_session, crude_event(), as_of=FIXTURE_TODAY)
    assert {c.discovery_source for c in pool.candidates} == {"MENTION"}


def test_an_unmodelled_shock_variable_is_reported_not_guessed(ripple_session,
                                                              crude_universe):
    from app.discovery.engine import DiscoveryEvent, DiscoveryShock, discover

    event = DiscoveryEvent(
        event_id="fixture:event-unknown", mentions=(),
        shocks=(DiscoveryShock(shock_id="s", variable="UNMODELLED_VARIABLE",
                               sign="UP", magnitude_pct=6.0),))
    pool = discover(ripple_session, event, as_of=FIXTURE_TODAY)
    assert pool.candidates == ()
    assert pool.unmodelled_variables == ("UNMODELLED_VARIABLE",)


def test_a_stale_exposure_row_does_not_produce_a_candidate(ripple_session,
                                                           crude_universe):
    from app.discovery.engine import discover

    stale = make_company(ripple_session, ticker="FIXSTL", name="FIXTURE STALE LTD",
                         sector="Chemicals", sub_sector="adhesives", market_cap=100.0)
    seed_exposure(ripple_session, exposure_id="x-stale", company_id=stale.id,
                  exposure_tag=TAG_PETCHEM, share_of_base=0.40,
                  as_of_date=FIXTURE_TODAY - timedelta(days=900),
                  freshness_days=400)
    pool = discover(ripple_session, crude_event(), as_of=FIXTURE_TODAY)
    assert stale.id not in {c.company_id for c in pool.candidates}
