from app.analysis.schemas import SECTORS
from app.market import sector_indices


def test_every_sector_has_a_benchmark_mapping():
    for sector in SECTORS:
        assert sector_indices.benchmark_ticker_for_sector(sector)


def test_map_covers_exactly_the_18_sectors():
    assert set(sector_indices.SECTOR_INDEX_MAP.keys()) == set(SECTORS)


def test_banking_maps_to_nifty_bank():
    assert sector_indices.benchmark_ticker_for_sector("banking") == "^NSEBANK"
    assert sector_indices.is_fallback_benchmark("banking") is False


def test_sectors_with_no_clean_index_fall_back_to_nifty_50():
    for sector in ("defense", "textiles", "agriculture", "other"):
        assert sector_indices.benchmark_ticker_for_sector(sector) == sector_indices.NIFTY50_TICKER
        assert sector_indices.is_fallback_benchmark(sector) is True


def test_unrecognized_sector_falls_back_to_nifty_50():
    assert sector_indices.benchmark_ticker_for_sector("not_a_real_sector") == sector_indices.NIFTY50_TICKER
    assert sector_indices.is_fallback_benchmark("not_a_real_sector") is True
