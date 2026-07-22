from app.reasoning.rulebook import EDGE_RELATIONS
from app.reasoning.ripple_relationship import (
    RIPPLE_RELATIONSHIPS,
    is_exposure_only,
    relation_to_ripple_relationship,
)


def test_every_edge_relation_maps_to_a_valid_ripple_relationship():
    for relation in EDGE_RELATIONS:
        mapped = relation_to_ripple_relationship(relation)
        assert mapped in RIPPLE_RELATIONSHIPS, f"{relation!r} mapped to invalid {mapped!r}"


def test_supplier_maps_to_supplier():
    assert relation_to_ripple_relationship("supplier") == "SUPPLIER"


def test_competitor_maps_to_competitor():
    assert relation_to_ripple_relationship("competitor") == "COMPETITOR"


def test_unrecognized_relation_falls_back_to_sector_wide():
    assert relation_to_ripple_relationship("not_a_real_relation") == "SECTOR_WIDE"


def test_is_exposure_only_true_for_no_data_and_stale_and_none():
    assert is_exposure_only("no_data") is True
    assert is_exposure_only("stale") is True
    assert is_exposure_only(None) is True


def test_is_exposure_only_false_for_ok():
    assert is_exposure_only("ok") is False
