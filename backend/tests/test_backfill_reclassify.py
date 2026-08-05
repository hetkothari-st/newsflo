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


# --- Fix round 2: final whole-branch review -------------------------------


def test_stale_sub_sector_cleared_when_sector_reclassified(db_session):
    """[Important 3] Rewriting sector without touching sub_sector can leave
    the same sector/sub_sector incoherence as the universe loader: a
    sub_sector valid for the OLD sector ("auto_component" under "auto") does
    not belong to the newly-derived sector ("infra", from official_industry
    "Capital Goods") and must be cleared, not left stale.
    app.companies.integrity.check_sub_sectors (master) flags exactly this."""
    c = _co(db_session, "X.NS", "auto", "Industrials", "Capital Goods")
    c.sub_sector = "auto_component"
    db_session.commit()

    result = backfill_reclassify.reclassify(db_session)

    updated = db_session.get(Company, c.id)
    assert updated.sector == "infra"
    assert updated.sub_sector is None
    assert result["sub_sector_cleared"] == 1


def test_coherent_sub_sector_survives_reclassification(db_session):
    """A sub_sector that IS a valid member of the newly-derived sector's
    taxonomy list must survive the sector rewrite untouched."""
    c = _co(db_session, "Y.NS", "other", "Industrials", "Capital Goods")
    c.sub_sector = "capital_goods"  # already valid under "infra"
    db_session.commit()

    result = backfill_reclassify.reclassify(db_session)

    updated = db_session.get(Company, c.id)
    assert updated.sector == "infra"
    assert updated.sub_sector == "capital_goods"
    assert result["sub_sector_cleared"] == 0


def test_dry_run_reports_sub_sector_clear_without_mutating(db_session):
    c = _co(db_session, "Z.NS", "auto", "Industrials", "Capital Goods")
    c.sub_sector = "auto_component"
    db_session.commit()

    result = backfill_reclassify.reclassify(db_session, dry_run=True)

    assert result["sub_sector_cleared"] == 1
    updated = db_session.get(Company, c.id)
    assert updated.sector == "auto"
    assert updated.sub_sector == "auto_component"
