import io

from app.holdings.csv_loader import load_holdings_from_csv
from app.models import Company, Holding, User


def _seed(db_session):
    user = User(email="h@example.com", hashed_password="x")
    reliance = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    tcs = Company(ticker="TCS.NS", name="TCS", sector="it", index_tier="NIFTY50", market_cap=1.0)
    db_session.add_all([user, reliance, tcs])
    db_session.commit()
    return user, reliance, tcs


def test_load_holdings_inserts_known_tickers(db_session):
    user, reliance, tcs = _seed(db_session)
    csv_bytes = io.BytesIO(b"Ticker,Quantity\nRELIANCE.NS,10\nTCS.NS,5\n")

    count = load_holdings_from_csv(db_session, user.id, csv_bytes)

    assert count == 2
    holdings = db_session.query(Holding).filter_by(user_id=user.id).all()
    assert {h.company_id for h in holdings} == {reliance.id, tcs.id}


def test_load_holdings_skips_unknown_ticker(db_session):
    user, reliance, _ = _seed(db_session)
    csv_bytes = io.BytesIO(b"Ticker,Quantity\nRELIANCE.NS,10\nUNKNOWN.NS,99\n")

    count = load_holdings_from_csv(db_session, user.id, csv_bytes)

    assert count == 1  # the unknown ticker is skipped, not counted, and does not fail the batch
    assert db_session.query(Holding).count() == 1


def test_load_holdings_upserts_existing(db_session):
    user, reliance, _ = _seed(db_session)
    load_holdings_from_csv(db_session, user.id, io.BytesIO(b"Ticker,Quantity\nRELIANCE.NS,10\n"))
    load_holdings_from_csv(db_session, user.id, io.BytesIO(b"Ticker,Quantity\nRELIANCE.NS,25\n"))

    holdings = db_session.query(Holding).filter_by(user_id=user.id, company_id=reliance.id).all()
    assert len(holdings) == 1
    assert holdings[0].quantity == 25.0


def test_load_holdings_accepts_text_stream(db_session):
    user, reliance, _ = _seed(db_session)

    count = load_holdings_from_csv(db_session, user.id, io.StringIO("Ticker,Quantity\nRELIANCE.NS,7\n"))

    assert count == 1
    assert db_session.query(Holding).one().quantity == 7.0
