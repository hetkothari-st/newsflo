from app.companies.sub_sectors import SUB_SECTOR_TAXONOMY
from app.companies.universe import sub_sector_map


def test_every_mapped_value_exists_in_the_closed_vocabulary():
    valid = {v for values in SUB_SECTOR_TAXONOMY.values() for v in values}
    unknown = set(sub_sector_map.ISUBGROUP_TO_SUB_SECTOR.values()) - valid
    assert unknown == set(), f"mappings target values outside the taxonomy: {unknown}"


def test_mapping_is_rejected_when_it_contradicts_the_sector():
    # "Private Sector Bank" belongs to banking. Asked for under sector "it",
    # the honest answer is None -- the sector is sourced and wins.
    assert sub_sector_map.map_sub_sector("Private Sector Bank", "banking") == "private_bank"
    assert sub_sector_map.map_sub_sector("Private Sector Bank", "it") is None


def test_unmapped_isubgroup_is_none_not_a_guess():
    assert sub_sector_map.map_sub_sector("Entirely Novel Business", "it") is None
    assert sub_sector_map.map_sub_sector(None, "it") is None
    assert sub_sector_map.map_sub_sector("", "it") is None


def test_lookup_is_case_and_whitespace_insensitive():
    assert sub_sector_map.map_sub_sector("  private sector bank  ", "banking") == "private_bank"


def test_known_high_volume_values_map():
    # The five most common ISubGroup values in the real data, by company count.
    cases = [
        ("Non Banking Financial Company (NBFC)", "banking", "nbfc"),
        ("Pharmaceuticals", "pharma", "generics_formulations"),
        ("Auto Components & Equipments", "auto", "auto_component"),
        ("Specialty Chemicals", "chemicals", "specialty_chemicals"),
        ("Residential, Commercial Projects", "construction_realestate", "residential_developer"),
    ]
    for isub, sector, expected in cases:
        assert sub_sector_map.map_sub_sector(isub, sector) == expected
