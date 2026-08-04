import backfill_reclassify
from app.models import Company


def _co(session, ticker, sector, official_sector, official_industry):
    c = Company(ticker=ticker, name=ticker, sector=sector, index_tier="OTHER",
                official_sector=official_sector, official_industry=official_industry)
    session.add(c)
    session.commit()
    return c


def test_reclassifies_a_company_stuck_on_other(db_session):
    c = _co(db_session, "X.NS", "other", "Consumer Discretionary",
            "Automobile and Auto Components")
    result = backfill_reclassify.reclassify(db_session)
    assert db_session.get(Company, c.id).sector == "auto"
    assert result["changed"] == 1


def test_dry_run_changes_nothing(db_session):
    c = _co(db_session, "X.NS", "other", "Commodities", "Chemicals")
    result = backfill_reclassify.reclassify(db_session, dry_run=True)
    assert db_session.get(Company, c.id).sector == "other"
    assert result["changed"] == 1  # reported, not applied


def test_dry_run_leaves_no_pending_or_committed_state(db_session):
    """Guards against the autoflush trap: mutate-then-query-then-rollback
    must not let a pending UPDATE slip through to the database. Forces a
    query (which triggers autoflush) immediately after reclassify() returns,
    then reopens a completely independent session bound to the same
    database file to rule out identity-map caching masking a real write.
    """
    c = _co(db_session, "Y.NS", "other", "Commodities", "Chemicals")
    backfill_reclassify.reclassify(db_session, dry_run=True)

    # Autoflush trigger: any query on this session flushes pending changes
    # first. If the guard were broken (attribute assigned unconditionally
    # and only `session.rollback()` relied upon), this query would persist
    # the mutation to the transaction before anything rolls it back.
    db_session.query(Company).filter_by(id=c.id).one()

    assert db_session.get(Company, c.id).sector == "other"
    assert not db_session.dirty

    # Independent session sharing the same bind: proves the row is
    # untouched at the database level, not just in this session's identity
    # map.
    from sqlalchemy.orm import sessionmaker
    OtherSession = sessionmaker(bind=db_session.get_bind())
    other = OtherSession()
    try:
        assert other.query(Company).filter_by(id=c.id).one().sector == "other"
    finally:
        other.close()


def test_company_without_official_classification_is_untouched(db_session):
    c = _co(db_session, "X.NS", "banking", None, None)
    backfill_reclassify.reclassify(db_session)
    assert db_session.get(Company, c.id).sector == "banking"


def test_transitions_are_reported(db_session):
    _co(db_session, "A.NS", "other", "Industrials", "Capital Goods")
    _co(db_session, "B.NS", "other", "Industrials", "Capital Goods")
    result = backfill_reclassify.reclassify(db_session)
    assert result["by_transition"]["other -> infra"] == 2
