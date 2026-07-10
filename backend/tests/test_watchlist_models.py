import pytest

from app.models import Company, User, UserWatchlistCategory, UserWatchlistCompany


def _make_user_and_company(session):
    user = User(email="w@example.com", hashed_password="x")
    company = Company(ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market_cap=None)
    session.add_all([user, company])
    session.commit()
    return user, company


def test_create_watchlist_rows(db_session):
    user, company = _make_user_and_company(db_session)
    db_session.add(UserWatchlistCategory(user_id=user.id, category="oil_energy"))
    db_session.add(UserWatchlistCompany(user_id=user.id, company_id=company.id))
    db_session.commit()

    assert db_session.query(UserWatchlistCategory).one().category == "oil_energy"
    assert db_session.query(UserWatchlistCompany).one().company_id == company.id


def test_watchlist_category_unique_per_user(db_session):
    user, _ = _make_user_and_company(db_session)
    db_session.add(UserWatchlistCategory(user_id=user.id, category="oil_energy"))
    db_session.commit()

    db_session.add(UserWatchlistCategory(user_id=user.id, category="oil_energy"))
    with pytest.raises(Exception):
        db_session.commit()


def test_watchlist_company_unique_per_user(db_session):
    user, company = _make_user_and_company(db_session)
    db_session.add(UserWatchlistCompany(user_id=user.id, company_id=company.id))
    db_session.commit()

    db_session.add(UserWatchlistCompany(user_id=user.id, company_id=company.id))
    with pytest.raises(Exception):
        db_session.commit()
