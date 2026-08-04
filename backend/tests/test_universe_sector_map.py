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
    # CORRECTION (2026-08-04 IndustryNew fix): this "allowed" set was a
    # manually-maintained duplicate of the closed vocabulary, frozen at the
    # 13 buckets the old Sector-only table could reach. Widening the table
    # to key on IndustryNew deliberately makes 5 more buckets reachable
    # (agriculture, construction_realestate, consumer_durables,
    # media_entertainment, textiles) -- that expansion is the fix, not a
    # defect. See test_every_emitted_value_is_a_valid_sector below for the
    # authoritative version of this check, sourced from SECTORS directly
    # instead of a second hand-maintained copy.
    allowed = {
        "banking", "fmcg", "pharma", "it", "oil_gas", "metals", "infra",
        "auto", "telecom", "chemicals", "defense", "railways_transport", "other",
        "agriculture", "construction_realestate", "consumer_durables",
        "media_entertainment", "textiles",
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


from app.analysis.schemas import SECTORS


@pytest.mark.parametrize("sector,industry,expected", [
    # The five Sector values that fall through today, each recovered via
    # IndustryNew. These five accounted for 2,971 production companies.
    ("Consumer Discretionary", "Automobile and Auto Components", "auto"),
    ("Consumer Discretionary", "Realty", "construction_realestate"),
    ("Consumer Discretionary", "Consumer Durables", "consumer_durables"),
    ("Consumer Discretionary", "Textiles", "textiles"),
    ("Industrials", "Capital Goods", "infra"),
    ("Industrials", "Construction", "infra"),
    ("Commodities", "Chemicals", "chemicals"),
    ("Commodities", "Metals & Mining", "metals"),
    ("Commodities", "Construction Materials", "infra"),
    ("Services", "Transport Services", "railways_transport"),
    # Sector still works when IndustryNew is absent or unknown.
    ("Energy", None, "oil_gas"),
    ("Financial Services", None, "banking"),
    ("Healthcare", "Something Unheard Of", "pharma"),
])
def test_industry_takes_precedence_then_sector_falls_back(sector, industry, expected):
    assert sector_map.map_sector(sector, industry) == expected


def test_previously_unreachable_sectors_are_now_reachable():
    # Six of the 18 valid sectors could never be produced. A sector no
    # company can be assigned is a dead branch in fan-out and filtering.
    #
    # NOTE: "defense" is deliberately excluded from this list. Neither BSE's
    # Sector nor IndustryNew vocabulary has a value that means "defense" --
    # defense manufacturers (BEL, HAL, Mazagon Dock, ...) are classified
    # under IndustryNew "Capital Goods", which this table already maps to
    # "infra". Adding a fabricated key to reach "defense" would be exactly
    # the kind of guess the mapping is designed to avoid (see map_sector's
    # "omit rather than guess" contract) -- so it stays unreachable from this
    # table pending a real BSE-sourced signal for it.
    reachable = set(sector_map.OFFICIAL_SECTOR_TO_BUCKET.values())
    for missing in ("agriculture", "construction_realestate", "consumer_durables",
                    "media_entertainment", "railways_transport", "textiles"):
        assert missing in reachable


def test_every_emitted_value_is_a_valid_sector():
    assert set(sector_map.OFFICIAL_SECTOR_TO_BUCKET.values()) <= set(SECTORS)


def test_unknown_both_levels_is_other():
    assert sector_map.map_sector("Nonsense", "Also Nonsense") == "other"
    assert sector_map.map_sector(None, None) == "other"
