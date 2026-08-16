"""TASK 3.4 -- input-output bootstrap: the Leontief inverse is the ripple
engine.

`io_coefficient` SHIPS EMPTY. The parser, the linear algebra, the pruning
rule, the industry mapping and the human review queue are all built and
tested; not one coefficient is written from memory. Real coefficients come
from MOSPI's Supply-Use / Input-Output Transaction Tables and nowhere else
(DATA_GAPS §7).
"""
import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from sqlalchemy import text

from tests.phase3.conftest import (
    FIXTURE_TODAY, TAG_PETCHEM, TAG_RUBBER, code_lines, seed_edge,
)

BACKEND = Path(__file__).resolve().parents[2]
IO_DIR = BACKEND / "app" / "graph" / "io_bootstrap"
MAPPING_YAML = BACKEND / "config" / "industry_mapping.yaml"
TOY = Path(__file__).resolve().parent / "fixtures" / "leontief_toy.json"


# --- the hand-verified toy matrix -------------------------------------------

def toy() -> dict:
    raw = json.loads(TOY.read_text(encoding="utf-8"))
    assert raw["_fixture"] is True
    return raw


def test_the_toy_matrix_fixture_is_the_documented_one():
    """The inverse in this fixture was computed BY HAND (cofactor expansion,
    written out in .superpowers/.../phase3-leontief-toy.md) and is pinned
    here. If numpy and the hand arithmetic ever disagree, one of them is
    wrong and the build must stop."""
    raw = toy()
    assert raw["A"] == [[0.2, 0.1, 0.0], [0.0, 0.2, 0.1], [0.1, 0.0, 0.2]]
    assert raw["determinant_of_I_minus_A"] == 0.511


def test_leontief_inverse_matches_the_hand_computed_toy_matrix():
    from app.graph.io_bootstrap.leontief import leontief_inverse

    raw = toy()
    computed = leontief_inverse(np.array(raw["A"], dtype=float))
    expected = np.array(raw["leontief_inverse"], dtype=float)
    assert computed.shape == (3, 3)
    np.testing.assert_allclose(computed, expected, atol=5e-5)


def test_the_inverse_really_inverts_i_minus_a():
    """The independent check: (I - A) @ (I - A)^-1 == I. This is what makes
    the hand arithmetic falsifiable rather than merely transcribed."""
    from app.graph.io_bootstrap.leontief import leontief_inverse

    a = np.array(toy()["A"], dtype=float)
    identity = (np.eye(3) - a) @ leontief_inverse(a)
    np.testing.assert_allclose(identity, np.eye(3), atol=1e-9)


def test_the_inverse_is_not_the_transpose_of_itself():
    """The toy matrix is deliberately ASYMMETRIC and cyclic, so a transposed
    orientation -- the classic IO bug -- fails this test instead of passing
    everything."""
    from app.graph.io_bootstrap.leontief import leontief_inverse

    inverse = leontief_inverse(np.array(toy()["A"], dtype=float))
    assert not np.allclose(inverse, inverse.T)


def test_total_coefficients_exceed_direct_coefficients():
    """This IS the ripple claim: total requirements include every indirect
    round, so every entry grows."""
    from app.graph.io_bootstrap.leontief import leontief_inverse

    a = np.array(toy()["A"], dtype=float)
    total = leontief_inverse(a) - np.eye(3)
    assert (total >= a - 1e-12).all()
    assert (total > a + 1e-9).any()


def test_a_divergent_matrix_is_refused_not_approximated():
    from app.graph.io_bootstrap.leontief import LeontiefError, leontief_inverse

    with pytest.raises(LeontiefError):
        leontief_inverse(np.array([[1.2, 0.0], [0.0, 0.3]], dtype=float))


def test_a_non_square_matrix_is_refused():
    from app.graph.io_bootstrap.leontief import LeontiefError, leontief_inverse

    with pytest.raises(LeontiefError):
        leontief_inverse(np.array([[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]], dtype=float))


# --- pruning ----------------------------------------------------------------

def test_coefficients_below_the_prune_threshold_are_excluded():
    from app.graph.io_bootstrap.leontief import PRUNE_THRESHOLD, prune

    assert PRUNE_THRESHOLD == 0.02
    rows = ({"source_industry": "A", "target_industry": "B", "total_coeff": 0.31},
            {"source_industry": "A", "target_industry": "C", "total_coeff": 0.019},
            {"source_industry": "A", "target_industry": "D", "total_coeff": 0.02})
    kept = prune(rows)
    assert [row["target_industry"] for row in kept] == ["B", "D"]


# --- the parser -------------------------------------------------------------

def test_the_parser_normalises_a_supply_use_table_to_direct_coefficients(tmp_path):
    """A tiny, obviously fake 3x3 transaction table: each column is one
    industry's input purchases. a(A->B) is A's row entry divided by B's total
    input."""
    from app.graph.io_bootstrap.parser import parse_transaction_table

    csv = tmp_path / "fixture_iott.csv"
    csv.write_text(
        "industry,IND_A,IND_B,IND_C\n"
        "IND_A,20,10,0\n"
        "IND_B,0,20,10\n"
        "IND_C,10,0,20\n"
        "TOTAL_INPUT,100,100,100\n", encoding="utf-8")

    table = parse_transaction_table(
        csv, table_year=2222, source_url="https://fixture.invalid/iott")
    assert table.industries == ("IND_A", "IND_B", "IND_C")
    assert table.table_year == 2222
    assert table.source_url == "https://fixture.invalid/iott"
    np.testing.assert_allclose(
        table.direct_coefficients,
        np.array([[0.2, 0.1, 0.0], [0.0, 0.2, 0.1], [0.1, 0.0, 0.2]]))


def test_the_parser_refuses_a_table_with_no_source_url(tmp_path):
    from app.graph.io_bootstrap.parser import IOTableError, parse_transaction_table

    csv = tmp_path / "f.csv"
    csv.write_text("industry,IND_A\nIND_A,1\nTOTAL_INPUT,10\n", encoding="utf-8")
    with pytest.raises(IOTableError):
        parse_transaction_table(csv, table_year=2222, source_url="")


def test_the_parser_refuses_a_column_with_no_total_input(tmp_path):
    from app.graph.io_bootstrap.parser import IOTableError, parse_transaction_table

    csv = tmp_path / "f.csv"
    csv.write_text("industry,IND_A,IND_B\nIND_A,1,2\nIND_B,2,1\n"
                   "TOTAL_INPUT,10,0\n", encoding="utf-8")
    with pytest.raises(IOTableError):
        parse_transaction_table(csv, table_year=2222,
                                source_url="https://fixture.invalid/x")


# --- the industry mapping ---------------------------------------------------

def test_the_industry_mapping_file_ships_as_structure_only():
    assert MAPPING_YAML.exists()
    raw = yaml.safe_load(MAPPING_YAML.read_text(encoding="utf-8"))
    assert raw["mappings"], "the file must document its own shape"
    assert all(row.get("_example") is True for row in raw["mappings"]), (
        "industry_mapping.yaml must ship with EXAMPLE rows only -- the real "
        "mapping is hand-authored by the owner (DATA_GAPS §7)")


def test_the_loader_refuses_every_example_row():
    from app.graph.io_bootstrap.mapping import IndustryMappingError, load_mapping

    with pytest.raises(IndustryMappingError):
        load_mapping(MAPPING_YAML)


def test_the_loader_accepts_a_reviewed_mapping(tmp_path):
    from app.graph.io_bootstrap.mapping import load_mapping

    path = tmp_path / "mapping.yaml"
    path.write_text(yaml.safe_dump({
        "version": "fixture-1",
        "mappings": [{"industry_code": "IND_A", "sector_id": "chemicals",
                      "exposure_tag": TAG_PETCHEM,
                      "reviewed_by": "human:fixture-reviewer",
                      "source_url": "https://fixture.invalid/nic"}]}),
        encoding="utf-8")
    mapping = load_mapping(path)
    assert mapping["IND_A"].exposure_tag == TAG_PETCHEM


def test_the_loader_refuses_a_mapping_to_a_tag_outside_the_vocabulary(tmp_path):
    from app.graph.io_bootstrap.mapping import IndustryMappingError, load_mapping

    path = tmp_path / "mapping.yaml"
    path.write_text(yaml.safe_dump({
        "version": "fixture-1",
        "mappings": [{"industry_code": "IND_A", "sector_id": "chemicals",
                      "exposure_tag": "input:invented",
                      "reviewed_by": "human:fixture-reviewer",
                      "source_url": "https://fixture.invalid/nic"}]}),
        encoding="utf-8")
    with pytest.raises(IndustryMappingError):
        load_mapping(path)


# --- candidate edges --------------------------------------------------------

def test_candidate_edges_are_unreviewed_and_carry_their_coefficient(tmp_path):
    from app.graph.io_bootstrap.edges import candidate_edges
    from app.graph.io_bootstrap.mapping import IndustryMapping

    mapping = {
        "IND_A": IndustryMapping("IND_A", "petrochemicals", TAG_PETCHEM,
                                 "human:r", "https://fixture.invalid/nic"),
        "IND_B": IndustryMapping("IND_B", "paints", TAG_PETCHEM,
                                 "human:r", "https://fixture.invalid/nic"),
    }
    rows = ({"source_industry": "IND_A", "target_industry": "IND_B",
             "direct_coeff": 0.10, "total_coeff": 0.13},)
    edges = candidate_edges(rows, mapping, table_year=2222,
                            source_url="https://fixture.invalid/iott")
    assert len(edges) == 1
    edge = edges[0]
    assert edge["derivation"] == "IO_TABLE"
    assert edge["reviewed_by"] is None
    assert edge["io_total_coeff"] == 0.13
    assert edge["relationship_type"] == "INPUT_COST"
    assert edge["exposure_tag"] == TAG_PETCHEM


def test_an_unmapped_industry_produces_no_edge():
    from app.graph.io_bootstrap.edges import candidate_edges
    from app.graph.io_bootstrap.mapping import IndustryMapping

    mapping = {"IND_A": IndustryMapping("IND_A", "petrochemicals", TAG_PETCHEM,
                                        "human:r", "https://fixture.invalid/nic")}
    rows = ({"source_industry": "IND_A", "target_industry": "IND_UNKNOWN",
             "direct_coeff": 0.10, "total_coeff": 0.13},)
    assert candidate_edges(rows, mapping, table_year=2222,
                           source_url="https://fixture.invalid/iott") == ()


def test_io_edges_generate_only_input_cost_and_demand_relationships():
    """A2.4, honestly encoded: IO tables model cost structure. They cannot
    produce REVENUE_REALIZATION, FX, rate or regulatory edges, and this
    module must not pretend otherwise."""
    from app.graph.io_bootstrap.edges import IO_RELATIONSHIP_TYPES

    assert set(IO_RELATIONSHIP_TYPES) == {"INPUT_COST", "DEMAND"}


# --- the review queue -------------------------------------------------------

def test_an_unreviewed_io_edge_appears_in_the_review_queue(ripple_session):
    from app.ledger.edge_review import pending_edges

    seed_edge(ripple_session, edge_id="io-1", from_node="petrochemicals",
              to_node="paints", exposure_tag=TAG_PETCHEM, derivation="IO_TABLE",
              reviewed_by=None, io_total_coeff=0.31)
    seed_edge(ripple_session, edge_id="auth-1", from_node="BRENT_CRUDE",
              to_node="paints", exposure_tag=TAG_PETCHEM, derivation="AUTHORED",
              reviewed_by=None)
    queue = pending_edges(ripple_session)
    assert [row["edge_id"] for row in queue] == ["io-1"]


def test_the_queue_is_ranked_by_coefficient(ripple_session):
    from app.ledger.edge_review import pending_edges

    seed_edge(ripple_session, edge_id="io-small", from_node="a", to_node="b",
              exposure_tag=TAG_PETCHEM, derivation="IO_TABLE", reviewed_by=None,
              io_total_coeff=0.05)
    seed_edge(ripple_session, edge_id="io-big", from_node="a", to_node="c",
              exposure_tag=TAG_RUBBER, derivation="IO_TABLE", reviewed_by=None,
              io_total_coeff=0.42)
    assert [row["edge_id"] for row in pending_edges(ripple_session)] == [
        "io-big", "io-small"]


def test_approving_an_edge_records_the_reviewer(ripple_session):
    from app.ledger.edge_review import approve_edge, pending_edges

    seed_edge(ripple_session, edge_id="io-2", from_node="a", to_node="b",
              exposure_tag=TAG_PETCHEM, derivation="IO_TABLE", reviewed_by=None,
              io_total_coeff=0.31)
    approve_edge(ripple_session, "io-2", reviewed_by="human:fixture-reviewer")
    assert pending_edges(ripple_session) == []
    assert ripple_session.execute(text(
        "SELECT reviewed_by FROM mechanism_edge WHERE edge_id = 'io-2'"
    )).scalar() == "human:fixture-reviewer"


def test_an_approval_with_no_reviewer_is_refused(ripple_session):
    from app.ledger.edge_review import EdgeReviewError, approve_edge

    seed_edge(ripple_session, edge_id="io-3", from_node="a", to_node="b",
              exposure_tag=TAG_PETCHEM, derivation="IO_TABLE", reviewed_by=None,
              io_total_coeff=0.31)
    with pytest.raises(EdgeReviewError):
        approve_edge(ripple_session, "io-3", reviewed_by="  ")


def test_a_rejected_edge_is_retained_with_its_reason(ripple_session):
    """Invariant 12: rejected candidates are retained, with a reason, and are
    visible in the review console."""
    from app.ledger.edge_review import pending_edges, reject_edge, rejected_edges

    seed_edge(ripple_session, edge_id="io-4", from_node="a", to_node="b",
              exposure_tag=TAG_PETCHEM, derivation="IO_TABLE", reviewed_by=None,
              io_total_coeff=0.31)
    reject_edge(ripple_session, "io-4", reviewed_by="human:fixture-reviewer",
                reason="the coefficient is an aggregation artefact")
    assert pending_edges(ripple_session) == []
    rejected = rejected_edges(ripple_session)
    assert [row["edge_id"] for row in rejected] == ["io-4"]
    assert rejected[0]["review_note"] == "the coefficient is an aggregation artefact"


def test_a_rejected_edge_can_never_be_traversed(ripple_session):
    from app.graph.traverse import traverse
    from app.ledger.edge_review import reject_edge

    seed_edge(ripple_session, edge_id="io-5", from_node="BRENT_CRUDE",
              to_node="b", exposure_tag=TAG_PETCHEM, derivation="IO_TABLE",
              reviewed_by=None, io_total_coeff=0.31)
    reject_edge(ripple_session, "io-5", reviewed_by="human:r", reason="no")
    assert traverse(ripple_session, "BRENT_CRUDE", as_of=FIXTURE_TODAY) == ()


def test_the_review_page_is_mounted_on_the_ledger_console(ripple_engine):
    from fastapi.testclient import TestClient

    from tools.ledger_ui import build_app

    client = TestClient(build_app(ripple_engine))
    response = client.get("/graph/edges")
    assert response.status_code == 200
    assert "mechanism edge" in response.text.lower()


# --- the fabrication guard --------------------------------------------------

def test_the_io_package_writes_no_coefficient_from_its_own_knowledge():
    """Every number this package emits must arrive from a parsed table. No
    module in it may contain a coefficient literal."""
    import re

    for path in sorted(IO_DIR.glob("*.py")):
        for number, line in code_lines(path):
            if "PRUNE_THRESHOLD" in line:
                continue
            for literal in re.findall(r"(?<![\w.])0\.\d+", line):
                pytest.fail(f"{path.name}:{number} carries a coefficient "
                            f"literal {literal}")


def test_io_coefficient_ships_empty(ripple_session):
    assert ripple_session.execute(text(
        "SELECT count(*) FROM io_coefficient")).scalar() == 0


def test_loading_coefficients_demands_provenance(ripple_session):
    from app.graph.io_bootstrap.load import IOLoadError, load_coefficients

    with pytest.raises(IOLoadError):
        load_coefficients(ripple_session, ({"source_industry": "A",
                                            "target_industry": "B",
                                            "direct_coeff": 0.1,
                                            "total_coeff": 0.13},),
                          table_year=2222, source_url="")
