"""TASK 3.2 -- the exposure tag index.

ADAPTATION (binding): SQLite has no MATERIALIZED VIEW. The index is a plain
VIEW -- the join and the WHERE are trivial at this scale, and a live view has
no staleness at all -- plus the required covering INDEX expressed on the BASE
TABLE, which is where SQLite can actually use it. The Postgres MV DDL is
recorded verbatim in migration 0013's docstring.
"""
from datetime import date, timedelta

from sqlalchemy import text

from tests.phase3.conftest import (
    FIXTURE_TODAY, TAG_PETCHEM, TAG_RUBBER, make_company, seed_exposure,
)


def test_the_index_view_exists(ripple_session):
    names = {row[0] for row in ripple_session.execute(text(
        "SELECT name FROM sqlite_master WHERE type = 'view'"))}
    assert "exposure_index" in names


def test_the_base_table_carries_the_tag_share_index(ripple_session):
    names = {row[0] for row in ripple_session.execute(text(
        "SELECT name FROM sqlite_master WHERE type = 'index'"))}
    assert "ix_company_exposure_tag_share" in names


def test_the_index_prunes_shares_below_two_percent(ripple_session):
    company = make_company(ripple_session, ticker="FIXE", name="FIXTURE E LTD")
    seed_exposure(ripple_session, exposure_id="big", company_id=company.id,
                  exposure_tag=TAG_PETCHEM, share_of_base=0.25)
    seed_exposure(ripple_session, exposure_id="trivial", company_id=company.id,
                  exposure_tag=TAG_RUBBER, share_of_base=0.011)
    rows = {row[0] for row in ripple_session.execute(text(
        "SELECT exposure_id FROM exposure_index"))}
    assert rows == {"big"}


def test_the_index_excludes_a_company_that_is_not_active(ripple_session):
    company = make_company(ripple_session, ticker="FIXF", name="FIXTURE F LTD")
    seed_exposure(ripple_session, exposure_id="delisted", company_id=company.id,
                  exposure_tag=TAG_PETCHEM, share_of_base=0.25)
    ripple_session.execute(text(
        "INSERT INTO company_entity_meta (company_id, status, source_url, "
        "as_of_date, updated_at) VALUES (:cid, 'DELISTED', "
        "'https://fixture.invalid/x', :as_of, :as_of)"),
        {"cid": company.id, "as_of": FIXTURE_TODAY.isoformat()})
    rows = list(ripple_session.execute(text("SELECT * FROM exposure_index")))
    assert rows == []


def test_a_company_with_no_entity_meta_row_is_treated_as_active(ripple_session):
    """The repo's `companies` table has no status column; §4.1's status lives
    in `company_entity_meta`, which ships empty. An absent row means nothing
    has been recorded AGAINST the company, and the universe loader only ever
    lists live names -- so absence reads ACTIVE. Stated, not silent."""
    company = make_company(ripple_session, ticker="FIXG", name="FIXTURE G LTD")
    seed_exposure(ripple_session, exposure_id="nometa", company_id=company.id,
                  exposure_tag=TAG_PETCHEM, share_of_base=0.25)
    rows = [row[0] for row in ripple_session.execute(text(
        "SELECT exposure_id FROM exposure_index"))]
    assert rows == ["nometa"]


def test_the_index_query_helper_honours_a_minimum_share(ripple_session):
    from app.discovery.index import query_exposure_index

    a = make_company(ripple_session, ticker="FIXH", name="FIXTURE H LTD")
    b = make_company(ripple_session, ticker="FIXI", name="FIXTURE I LTD")
    seed_exposure(ripple_session, exposure_id="h", company_id=a.id,
                  exposure_tag=TAG_PETCHEM, share_of_base=0.30)
    seed_exposure(ripple_session, exposure_id="i", company_id=b.id,
                  exposure_tag=TAG_PETCHEM, share_of_base=0.04)

    high = query_exposure_index(ripple_session, TAG_PETCHEM, min_share=0.10)
    assert [row["company_id"] for row in high] == [a.id]
    low = query_exposure_index(ripple_session, TAG_PETCHEM, min_share=0.02)
    assert [row["company_id"] for row in low] == [a.id, b.id]   # share DESC


def test_the_index_reports_its_own_staleness(ripple_session):
    """`staleness` on a live view is the age of the OLDEST row it exposes --
    the honest reading of 'how out of date is what discovery can see'."""
    from app.discovery.index import index_staleness

    company = make_company(ripple_session, ticker="FIXJ", name="FIXTURE J LTD")
    assert index_staleness(ripple_session, as_of=FIXTURE_TODAY) is None

    seed_exposure(ripple_session, exposure_id="old", company_id=company.id,
                  exposure_tag=TAG_PETCHEM, share_of_base=0.30,
                  as_of_date=FIXTURE_TODAY - timedelta(days=40))
    report = index_staleness(ripple_session, as_of=FIXTURE_TODAY)
    assert report.rows == 1
    assert report.max_age_days == 40
