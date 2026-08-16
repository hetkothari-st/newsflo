"""TASK 3.1 -- the closed exposure-tag vocabulary.

`config/exposure_tags.yaml` is the closed, versioned, hierarchical set from
spec §6.1. Extending it is a code review, never a runtime decision -- so the
enforcement is not a Python `if`, it is the DATABASE refusing the row.
"""
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from tests.phase3.conftest import (
    FIXTURE_TODAY, TAG_PETCHEM, make_company, seed_edge, seed_exposure,
)

BACKEND = Path(__file__).resolve().parents[2]
TAGS_YAML = BACKEND / "config" / "exposure_tags.yaml"


# --- the file itself --------------------------------------------------------

def test_the_vocabulary_file_exists_and_is_versioned():
    assert TAGS_YAML.exists(), "backend/config/exposure_tags.yaml is missing"
    raw = yaml.safe_load(TAGS_YAML.read_text(encoding="utf-8"))
    assert isinstance(raw.get("version"), str) and raw["version"]


def test_the_vocabulary_carries_the_spec_6_1_hierarchy():
    from app.ledger.exposure_tags import load_vocabulary

    vocabulary = load_vocabulary()
    for tag in ("input:crude_direct", "input:crude_derivative_petchem",
                "input:crude_derivative_rubber", "input:crude_derivative_bitumen",
                "input:atf", "input:fuel_furnace_pet_coke", "input:freight_diesel",
                "input:steel_flat", "input:steel_long", "input:aluminium",
                "input:copper", "input:palm_oil", "input:wheat", "input:sugar",
                "input:milk", "revenue:crude_realization",
                "revenue:refining_gross_margin", "revenue:marketing_margin_retail_fuel",
                "revenue:gas_realization_apm", "revenue:gas_realization_market",
                "fx:usd_revenue_share", "fx:usd_cost_share", "fx:usd_debt_share",
                "rate:floating_debt_share", "rate:nim_asset_sensitivity"):
        assert tag in vocabulary.tags, f"spec §6.1 tag missing: {tag}"


def test_every_tag_keeps_the_family_leaf_shape_phase_1_validates():
    """The vocabulary must not contain a tag the Phase 1 shape check would
    reject -- two validators disagreeing is worse than one."""
    from app.ledger.exposure_tags import load_vocabulary
    from app.ledger.vocabulary import check_exposure_tag

    for tag in load_vocabulary().tags:
        check_exposure_tag(tag)


def test_the_addendum_spelling_map_is_documented_and_true():
    """M5. The addendum spells the priority tags WITH the group
    (`input:metals:steel_flat`); spec §6.1's YAML nests the group and leaves
    it out of the tag. The file must state the mapping -- and the claim it
    makes ("a three-segment tag is REJECTED") must actually hold, or the
    comment is worse than nothing."""
    from app.ledger.vocabulary import VocabularyError, check_exposure_tag

    header = TAGS_YAML.read_text(encoding="utf-8").split("version:", 1)[0]
    assert "input:metals:steel_flat" in header
    assert "input:agri:palm_oil" in header
    assert "input:steel_flat" in header and "input:palm_oil" in header

    for addendum_spelling in ("input:metals:steel_flat", "input:agri:palm_oil",
                              "revenue:realization:crude_realization"):
        with pytest.raises(VocabularyError):
            check_exposure_tag(addendum_spelling)


def test_a_three_segment_tag_is_rejected_at_db_level(ripple_session):
    """The same claim, at the layer that actually enforces it."""
    company = make_company(ripple_session, ticker="FIX3S", name="FIXTURE 3S LTD")
    with pytest.raises(DatabaseError):
        seed_exposure(ripple_session, exposure_id="fx-3seg",
                      company_id=company.id,
                      exposure_tag="input:metals:steel_flat", share_of_base=0.3)


def test_the_vocabulary_names_no_company_and_no_financial_figure():
    """A vocabulary is a list of WORDS. A number in it would be data."""
    raw = yaml.safe_load(TAGS_YAML.read_text(encoding="utf-8"))

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)
        elif node is not None:
            yield node

    for item in walk({k: v for k, v in raw.items() if k != "version"}):
        assert not isinstance(item, (int, float)), (
            f"exposure_tags.yaml carries a numeral ({item!r}); it is a "
            "vocabulary, not data")


def test_the_hierarchy_is_a_hierarchy_not_a_flat_list():
    """§6.1 is explicitly hierarchical: families, then leaves. The loader must
    surface the family so a caller can ask for 'every input: tag'."""
    from app.ledger.exposure_tags import load_vocabulary

    vocabulary = load_vocabulary()
    assert set(vocabulary.families) >= {"input", "revenue", "fx", "rate"}
    assert "input:crude_derivative_rubber" in vocabulary.tags_in_family("input")
    assert "fx:usd_revenue_share" not in vocabulary.tags_in_family("input")


# --- the DB-level rejection (the actual requirement) ------------------------

def test_the_vocabulary_table_is_populated_by_create_all(ripple_session):
    from app.ledger.exposure_tags import load_vocabulary

    rows = {row[0] for row in ripple_session.execute(
        text("SELECT exposure_tag FROM valid_exposure_tag"))}
    assert rows == set(load_vocabulary().tags)


def test_an_unknown_exposure_tag_is_rejected_at_db_level(ripple_session):
    company = make_company(ripple_session, ticker="FIXA", name="FIXTURE A LTD")
    with pytest.raises(DatabaseError):
        seed_exposure(ripple_session, exposure_id="fx-bad", company_id=company.id,
                      exposure_tag="input:not_a_real_tag", share_of_base=0.3)


def test_a_known_exposure_tag_is_accepted(ripple_session):
    """Non-vacuous companion: the guard refuses the unknown tag and ONLY the
    unknown tag."""
    company = make_company(ripple_session, ticker="FIXB", name="FIXTURE B LTD")
    seed_exposure(ripple_session, exposure_id="fx-ok", company_id=company.id,
                  exposure_tag=TAG_PETCHEM, share_of_base=0.3)
    assert ripple_session.execute(text(
        "SELECT count(*) FROM company_exposure")).scalar() == 1


def test_an_unknown_tag_is_rejected_on_update_too(ripple_session):
    from app.ledger.review import review_session

    company = make_company(ripple_session, ticker="FIXC", name="FIXTURE C LTD")
    seed_exposure(ripple_session, exposure_id="fx-upd", company_id=company.id,
                  exposure_tag=TAG_PETCHEM, share_of_base=0.3)
    with pytest.raises(DatabaseError):
        with review_session(ripple_session):
            ripple_session.execute(text(
                "UPDATE company_exposure SET exposure_tag = 'input:invented' "
                "WHERE exposure_id = 'fx-upd'"))


def test_a_mechanism_edge_with_an_unknown_tag_is_rejected_at_db_level(ripple_session):
    with pytest.raises(DatabaseError):
        seed_edge(ripple_session, edge_id="edge-bad", from_node="BRENT_CRUDE",
                  to_node="petchem", exposure_tag="input:invented_by_a_model")


def test_a_mechanism_edge_with_a_known_tag_is_accepted(ripple_session):
    seed_edge(ripple_session, edge_id="edge-ok", from_node="BRENT_CRUDE",
              to_node="petchem", exposure_tag=TAG_PETCHEM)
    assert ripple_session.execute(text(
        "SELECT count(*) FROM mechanism_edge")).scalar() == 1


def test_registering_a_tag_is_the_only_way_to_widen_the_vocabulary(ripple_session):
    """There is no code path that writes an exposure row with an unregistered
    tag. Registering one is an explicit, sourced act -- which is exactly what
    a code review of exposure_tags.yaml is."""
    from app.ledger.exposure_tags import register_tags

    company = make_company(ripple_session, ticker="FIXD", name="FIXTURE D LTD")
    register_tags(ripple_session, ("input:fixture_only_tag",),
                  source="tests/phase3")
    seed_exposure(ripple_session, exposure_id="fx-reg", company_id=company.id,
                  exposure_tag="input:fixture_only_tag", share_of_base=0.3)
    assert ripple_session.execute(text(
        "SELECT count(*) FROM company_exposure")).scalar() == 1


def test_register_tags_refuses_a_tag_of_the_wrong_shape(ripple_session):
    from app.ledger.exposure_tags import register_tags
    from app.ledger.vocabulary import VocabularyError

    with pytest.raises(VocabularyError):
        register_tags(ripple_session, ("NotATag",), source="tests/phase3")
