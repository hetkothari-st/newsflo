from app.analysis.schemas import SECTORS
from app.companies.global_seed import GLOBAL_COMPANIES, load_global_companies
from app.models import Company


def test_load_global_companies_inserts_all_entries(db_session):
    count = load_global_companies(db_session)

    assert count == len(GLOBAL_COMPANIES)
    rows = db_session.query(Company).filter_by(index_tier="GLOBAL_LARGE_CAP").all()
    assert len(rows) == len(GLOBAL_COMPANIES)


def test_load_global_companies_is_idempotent_upsert(db_session):
    load_global_companies(db_session)
    load_global_companies(db_session)

    rows = db_session.query(Company).filter_by(index_tier="GLOBAL_LARGE_CAP").all()
    assert len(rows) == len(GLOBAL_COMPANIES)  # no duplicates on re-run


def test_every_global_company_sector_is_valid():
    for entry in GLOBAL_COMPANIES:
        assert entry["sector"] in SECTORS, entry


def test_every_global_ticker_is_non_indian():
    # No global seed ticker may end in .NS/.BO, so infer_market classifies
    # them all as GLOBAL.
    for entry in GLOBAL_COMPANIES:
        assert not entry["ticker"].endswith((".NS", ".BO")), entry


def test_no_duplicate_tickers():
    tickers = [e["ticker"] for e in GLOBAL_COMPANIES]
    assert len(tickers) == len(set(tickers))


# The 9 original sectors GLOBAL_COMPANIES was hand-curated for. The 8
# sectors added later (railways_transport, construction_realestate,
# defense, agriculture, consumer_durables, media_entertainment, chemicals,
# textiles -- see app.analysis.schemas.SECTORS) don't have curated global
# entries yet -- that's real company-data authoring, tracked as a separate
# follow-up, not something to fabricate to satisfy this test.
_ORIGINAL_CURATED_SECTORS = {
    "oil_gas", "banking", "auto", "it", "pharma", "fmcg", "metals", "telecom", "infra", "other",
}


def test_fifty_companies_per_sector():
    from collections import Counter
    counts = Counter(e["sector"] for e in GLOBAL_COMPANIES)
    for sector in _ORIGINAL_CURATED_SECTORS:
        assert counts[sector] == 50, (sector, counts[sector])
    for sector in set(SECTORS) - _ORIGINAL_CURATED_SECTORS:
        assert counts[sector] == 0, (
            sector, counts[sector],
            "a newly-added sector has GLOBAL_COMPANIES entries -- if these are "
            "real, curated companies, remove this assertion for that sector; "
            "if they were auto-generated, verify their accuracy before keeping them",
        )
