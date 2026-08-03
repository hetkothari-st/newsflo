import pytest

from app.companies.universe import sector_map


@pytest.mark.parametrize("official,expected", [
    ("Energy", "oil_gas"),
    ("Financial Services", "banking"),
    ("Information Technology", "it"),
    ("Healthcare", "pharma"),
    ("Fast Moving Consumer Goods", "fmcg"),
    ("Metals & Mining", "metals"),
    ("Telecommunication", "telecom"),
    ("Automobile and Auto Components", "auto"),
    ("Chemicals", "chemicals"),
    ("Construction", "infra"),
    ("Capital Goods", "infra"),
])
def test_official_sectors_map_to_closed_vocabulary(official, expected):
    assert sector_map.map_sector(official) == expected


def test_unknown_official_sector_falls_back_to_other():
    assert sector_map.map_sector("Something Unheard Of") == "other"


def test_missing_official_sector_falls_back_to_other():
    assert sector_map.map_sector(None) == "other"


def test_mapping_is_case_and_whitespace_insensitive():
    assert sector_map.map_sector("  energy  ") == "oil_gas"


def test_every_mapped_bucket_is_in_the_closed_vocabulary():
    allowed = {
        "banking", "fmcg", "pharma", "it", "oil_gas", "metals", "infra",
        "auto", "telecom", "chemicals", "defense", "railways_transport", "other",
    }
    assert set(sector_map.OFFICIAL_SECTOR_TO_BUCKET.values()) <= allowed


@pytest.mark.parametrize("exchange,series,group,expected", [
    ("NSE", "EQ", None, "NORMAL"),
    ("NSE", "BE", None, "RESTRICTED"),
    ("NSE", "BZ", None, "RESTRICTED"),
    ("BSE", None, "A", "NORMAL"),
    ("BSE", None, "B", "NORMAL"),
    ("BSE", None, "X", "RESTRICTED"),
    ("BSE", None, "XT", "RESTRICTED"),
    ("BSE", None, "T", "RESTRICTED"),
    ("BSE", None, "M", "SME"),
    ("BSE", None, "MT", "SME"),
    ("BSE", None, "Z", "SUSPENDED"),
])
def test_listing_tradeability(exchange, series, group, expected):
    assert sector_map.listing_tradeability(exchange, series, group, "ACTIVE") == expected


def test_suspended_status_overrides_group():
    assert sector_map.listing_tradeability("BSE", None, "A", "SUSPENDED") == "SUSPENDED"


def test_most_permissive_listing_wins():
    listings = [
        {"exchange": "NSE", "series": "EQ", "group_code": None, "status": "ACTIVE"},
        {"exchange": "BSE", "series": None, "group_code": "Z", "status": "ACTIVE"},
    ]
    assert sector_map.derive_tradeability(listings) == "NORMAL"


def test_company_with_only_a_suspended_listing_is_suspended():
    listings = [{"exchange": "BSE", "series": None, "group_code": "Z", "status": "ACTIVE"}]
    assert sector_map.derive_tradeability(listings) == "SUSPENDED"


def test_no_listings_defaults_to_normal():
    assert sector_map.derive_tradeability([]) == "NORMAL"
