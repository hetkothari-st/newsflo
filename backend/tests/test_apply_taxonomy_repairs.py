from apply_taxonomy_repairs import TAXONOMY_REPAIRS, apply_taxonomy_repairs
from app.models import Company


def _seed_target_companies(db_session):
    db_session.add_all([
        Company(ticker="ETERNAL.NS", name="Eternal Ltd.", sector="fmcg", sub_sector="personal_care", index_tier="NIFTY50"),
        Company(ticker="ASIANPAINT.NS", name="Asian Paints Ltd.", sector="fmcg", sub_sector="paints", index_tier="NIFTY50"),
        Company(ticker="INDIGO.NS", name="InterGlobe Aviation Ltd.", sector="other", index_tier="NIFTY50"),
    ])
    db_session.commit()


def test_applies_every_repair_in_the_table(db_session):
    _seed_target_companies(db_session)

    results = apply_taxonomy_repairs(db_session, dry_run=False)

    assert all(r.status == "applied" for r in results)
    assert db_session.query(Company).filter_by(ticker="ETERNAL.NS").one().sub_sector == "retail"
    assert db_session.query(Company).filter_by(ticker="ASIANPAINT.NS").one().sector == "chemicals"
    assert db_session.query(Company).filter_by(ticker="INDIGO.NS").one().sector == "railways_transport"


def test_dry_run_reports_without_writing(db_session):
    _seed_target_companies(db_session)

    results = apply_taxonomy_repairs(db_session, dry_run=True)

    assert all(r.status == "applied" for r in results)
    # Nothing was actually written.
    assert db_session.query(Company).filter_by(ticker="ETERNAL.NS").one().sub_sector == "personal_care"
    assert db_session.query(Company).filter_by(ticker="ASIANPAINT.NS").one().sector == "fmcg"
    assert db_session.query(Company).filter_by(ticker="INDIGO.NS").one().sector == "other"


def test_idempotent_second_run_reports_already_correct_and_changes_nothing(db_session):
    _seed_target_companies(db_session)
    apply_taxonomy_repairs(db_session, dry_run=False)

    second_pass = apply_taxonomy_repairs(db_session, dry_run=False)

    assert all(r.status == "already_correct" for r in second_pass)
    assert db_session.query(Company).filter_by(ticker="ETERNAL.NS").one().sub_sector == "retail"
    assert db_session.query(Company).filter_by(ticker="ASIANPAINT.NS").one().sector == "chemicals"
    assert db_session.query(Company).filter_by(ticker="INDIGO.NS").one().sector == "railways_transport"


def test_safe_against_a_database_where_the_repair_was_already_applied_by_other_means(db_session):
    # Simulates a production row that already carries the correct, final
    # value through some other path (e.g. a fresh seed) -- must be reported
    # as already-correct, not re-applied or errored on.
    db_session.add(Company(
        ticker="ETERNAL.NS", name="Eternal Ltd.", sector="fmcg", sub_sector="retail", index_tier="NIFTY50",
    ))
    db_session.commit()

    results = apply_taxonomy_repairs(db_session, dry_run=False)

    eternal_result = next(r for r in results if r.ticker == "ETERNAL.NS")
    assert eternal_result.status == "already_correct"
    assert db_session.query(Company).filter_by(ticker="ETERNAL.NS").one().sub_sector == "retail"


def test_missing_ticker_is_reported_not_found_and_does_not_crash(db_session):
    # No Company rows seeded at all -- every repair target is missing.
    results = apply_taxonomy_repairs(db_session, dry_run=False)

    assert all(r.status == "not_found" for r in results)
    assert db_session.query(Company).count() == 0


def test_repair_table_only_contains_supported_fields():
    for ticker, field, expected in TAXONOMY_REPAIRS:
        assert field in ("sector", "sub_sector")
        assert isinstance(ticker, str) and ticker
        assert isinstance(expected, str) and expected
