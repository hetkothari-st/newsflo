from app.companies.integrity import (
    ALERT_COMPANY_DEPENDENTS, delete_demo_companies, is_demo_company, check_sub_sectors,
)
from app.db import Base
from app.models import (
    Alert,
    AlertCompany,
    AlertCompanyTranslation,
    Article,
    CalibrationSample,
    CarOutcome,
    Company,
    CompanyIndexMembership,
    EmailNotification,
    Holding,
    ImpactEdge,
    MarketMove,
    User,
    UserWatchlistCompany,
)
from app.analysis.schemas import CompanyMention
from app.companies.resolution import resolve_companies


def test_alert_company_dependents_covers_every_referencing_model():
    """ALERT_COMPANY_DEPENDENTS is the single source of truth shared by
    delete_demo_companies, cleanup_orphan_company_refs.py, and
    migrate_precision.py for which tables reference alert_companies.id --
    a second, hand-maintained copy of this list anywhere is exactly the
    failure mode this task fixed three times over (a model gains a new FK
    to alert_companies.id, one copy of the list gets updated, the other
    doesn't, and the next orphan generation appears silently under
    SQLite's default off FK enforcement).

    Derives the expected set by introspecting SQLAlchemy metadata --
    every mapped class with a column whose ForeignKey targets
    "alert_companies.id" -- rather than hardcoding a second list, so this
    test itself cannot drift out of sync with the schema.
    """
    expected = set()
    for mapper in Base.registry.mappers:
        for column in mapper.local_table.columns:
            for fk in column.foreign_keys:
                if fk.target_fullname == "alert_companies.id":
                    expected.add(mapper.class_)

    assert set(ALERT_COMPANY_DEPENDENTS) == expected


def test_known_demo_ticker_is_flagged():
    assert is_demo_company("SOMETEXTILE.NS") is True


def test_real_ticker_is_not_flagged():
    assert is_demo_company("RELIANCE.NS") is False


def test_delete_demo_companies_removes_only_demo_rows(db_session):
    db_session.add(Company(ticker="SOMETEXTILE.NS", name="Demo Textiles Ltd", sector="textiles", index_tier="OTHER"))
    db_session.add(Company(ticker="RELIANCE.NS", name="Reliance Industries Ltd.", sector="oil_gas", index_tier="NIFTY50"))
    db_session.commit()

    deleted = delete_demo_companies(db_session)

    assert deleted == ["SOMETEXTILE.NS"]
    remaining = {c.ticker for c in db_session.query(Company).all()}
    assert remaining == {"RELIANCE.NS"}


def test_delete_demo_companies_is_idempotent(db_session):
    db_session.add(Company(ticker="RELIANCE.NS", name="Reliance Industries Ltd.", sector="oil_gas", index_tier="NIFTY50"))
    db_session.commit()

    assert delete_demo_companies(db_session) == []


def test_delete_demo_companies_leaves_no_orphaned_references_anywhere(db_session):
    """Regression test for the incident where an earlier version of
    delete_demo_companies deleted only the Company row and left
    alert_companies/market_moves rows dangling -- invisible under SQLite's
    default (off) FK enforcement until a later, unrelated schema-rebuild
    script ran PRAGMA foreign_key_check for the first time and found them
    (SOMETEXTILE.NS, alert_companies 858/887, market_moves 21/50), with a
    further 7 alert_company_translations rows one silent step from becoming
    a second generation of orphans.

    Builds one row in every table that can reference a company -- directly,
    or transitively through the demo company's own alert_companies row --
    plus rows that merely reference the demo company through a nullable
    column while being otherwise unrelated to it, then asserts: every
    direct/transitive reference is gone, every nullable reference is
    cleared (not cascaded into deleting an unrelated row), and no surviving
    row's foreign key points at a company that no longer exists.
    """
    demo = Company(ticker="SOMETEXTILE.NS", name="Demo Textiles Ltd", sector="textiles", index_tier="OTHER")
    real = Company(ticker="RELIANCE.NS", name="Reliance Industries Ltd.", sector="oil_gas", index_tier="NIFTY50")
    db_session.add_all([demo, real])
    db_session.commit()

    article = Article(source="test", url="https://example.com/x", title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="test")
    db_session.add(alert)
    db_session.commit()

    user = User(email="u@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    # Direct references to the demo company.
    db_session.add(CompanyIndexMembership(company_id=demo.id, index_code="NIFTY500"))
    db_session.add(Holding(user_id=user.id, company_id=demo.id, quantity=10))
    db_session.add(UserWatchlistCompany(user_id=user.id, company_id=demo.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=demo.id, benchmark_ticker="NIFTY50",
        measurement_status="ok",
    ))

    # The demo company's own alert_companies row, plus every row that
    # references THAT row.
    ac = AlertCompany(
        alert_id=alert.id, company_id=demo.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
    )
    db_session.add(ac)
    db_session.commit()

    db_session.add(CalibrationSample(
        alert_company_id=ac.id, category="test", company_id=demo.id,
        direction="bullish", magnitude_actual=1.5, horizon_days=1,
    ))
    db_session.add(CarOutcome(
        alert_company_id=ac.id, company_id=demo.id, category="test",
        day0_excess_move_pct=1.0, car_pct=1.0,
    ))
    db_session.add(EmailNotification(user_id=user.id, alert_company_id=ac.id))
    db_session.add(AlertCompanyTranslation(alert_company_id=ac.id, lang="hi", rationale="r"))

    # A DIFFERENT, real company's alert_companies row that merely chains an
    # indirect-impact parent through the demo company -- must survive, with
    # parent_company_id cleared rather than the row being deleted.
    indirect = AlertCompany(
        alert_id=alert.id, company_id=real.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
        impact_level="indirect_l1", parent_company_id=demo.id,
    )
    db_session.add(indirect)

    # An ImpactEdge whose alert has nothing else to do with the demo
    # company except naming it as one endpoint -- must survive, with its
    # company reference cleared.
    edge = ImpactEdge(
        alert_id=alert.id, from_company_id=demo.id, from_node_kind="company",
        from_label="Demo Textiles Ltd", to_company_id=real.id, to_node_kind="company",
        to_label="Reliance Industries Ltd.", relation="supplier", direction="bullish",
        note="n", source="llm_only",
    )
    db_session.add(edge)
    db_session.commit()

    # Captured as plain ints BEFORE the delete -- delete_demo_companies
    # removes the `demo` Company row and the `ac` AlertCompany row that
    # references it out from under the ORM session (via bulk delete(),
    # synchronize_session=False), and expire_on_commit means touching
    # demo.id / ac.id as an attribute afterward would try to re-fetch a row
    # that's genuinely gone and raise ObjectDeletedError -- a test-harness
    # trap, not something delete_demo_companies needs to account for.
    demo_id = demo.id
    real_id = real.id
    ac_id = ac.id
    indirect_id = indirect.id
    edge_id = edge.id

    deleted = delete_demo_companies(db_session)

    assert deleted == ["SOMETEXTILE.NS"]
    assert db_session.query(Company).filter_by(ticker="SOMETEXTILE.NS").first() is None

    # Every direct/transitive reference to the demo company is gone.
    assert db_session.query(CompanyIndexMembership).filter_by(company_id=demo_id).count() == 0
    assert db_session.query(Holding).filter_by(company_id=demo_id).count() == 0
    assert db_session.query(UserWatchlistCompany).filter_by(company_id=demo_id).count() == 0
    assert db_session.query(MarketMove).filter_by(company_id=demo_id).count() == 0
    assert db_session.query(AlertCompany).filter_by(company_id=demo_id).count() == 0
    assert db_session.query(CalibrationSample).filter_by(alert_company_id=ac_id).count() == 0
    assert db_session.query(CarOutcome).filter_by(alert_company_id=ac_id).count() == 0
    assert db_session.query(EmailNotification).filter_by(alert_company_id=ac_id).count() == 0
    assert db_session.query(AlertCompanyTranslation).filter_by(alert_company_id=ac_id).count() == 0

    # Unrelated rows that merely referenced the demo company via a nullable
    # column survive, with the reference cleared -- never cascade-deleted.
    surviving_indirect = db_session.query(AlertCompany).filter_by(id=indirect_id).one()
    assert surviving_indirect.parent_company_id is None

    surviving_edge = db_session.query(ImpactEdge).filter_by(id=edge_id).one()
    assert surviving_edge.from_company_id is None
    assert surviving_edge.to_company_id == real_id

    # No surviving foreign key points at a company that no longer exists.
    remaining_company_ids = {c.id for c in db_session.query(Company).all()}
    for row in db_session.query(AlertCompany).all():
        assert row.company_id in remaining_company_ids
        if row.parent_company_id is not None:
            assert row.parent_company_id in remaining_company_ids
    for row in db_session.query(ImpactEdge).all():
        if row.from_company_id is not None:
            assert row.from_company_id in remaining_company_ids
        if row.to_company_id is not None:
            assert row.to_company_id in remaining_company_ids


def test_resolution_never_returns_a_demo_company_by_ticker(db_session):
    db_session.add(Company(ticker="SOMETEXTILE.NS", name="Demo Textiles Ltd", sector="textiles", index_tier="OTHER"))
    db_session.commit()

    resolved = resolve_companies(db_session, [CompanyMention(
        name="Demo Textiles Ltd", ticker="SOMETEXTILE.NS", is_direct=True,
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0,
        rationale="r", time_horizon="Short-Term",
    )])

    assert resolved == []


def test_sector_fanout_never_returns_a_demo_company(db_session):
    db_session.add(Company(ticker="SOMETEXTILE.NS", name="Demo Textiles Ltd", sector="textiles", index_tier="OTHER"))
    db_session.commit()

    resolved = resolve_companies(db_session, [CompanyMention(
        name="textiles sector", is_direct=False, sector="textiles",
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0,
        rationale="r", time_horizon="Short-Term",
    )])

    assert resolved == []


def test_valid_pairing_is_not_a_violation(db_session):
    db_session.add(Company(
        ticker="HINDUNILVR.NS", name="Hindustan Unilever Ltd.",
        sector="fmcg", sub_sector="personal_care", index_tier="NIFTY50",
    ))
    db_session.commit()

    assert check_sub_sectors(db_session) == []


def test_sub_sector_from_another_sector_is_a_violation(db_session):
    db_session.add(Company(
        ticker="ASIANPAINT.NS", name="Asian Paints Ltd.",
        sector="fmcg", sub_sector="paints", index_tier="NIFTY50",
    ))
    db_session.commit()

    violations = check_sub_sectors(db_session)

    assert len(violations) == 1
    assert violations[0].ticker == "ASIANPAINT.NS"
    assert violations[0].sector == "fmcg"
    assert violations[0].sub_sector == "paints"
    # "paints" appears in exactly one sector's branch, so the fix is
    # unambiguous and can be suggested.
    assert violations[0].correct_sector == "chemicals"


def test_null_sub_sector_is_not_a_violation(db_session):
    db_session.add(Company(ticker="X.NS", name="X Ltd.", sector="other", sub_sector=None, index_tier="OTHER"))
    db_session.commit()

    assert check_sub_sectors(db_session) == []


def test_unknown_sub_sector_reports_no_suggested_sector(db_session):
    db_session.add(Company(
        ticker="Y.NS", name="Y Ltd.", sector="fmcg", sub_sector="not_a_real_subsector", index_tier="NIFTY100",
    ))
    db_session.commit()

    violations = check_sub_sectors(db_session)

    assert len(violations) == 1
    assert violations[0].correct_sector is None
