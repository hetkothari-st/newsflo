from app.companies.peers import get_sector_peers
from app.models import Company


def test_get_sector_peers_returns_same_sector_companies(db_session):
    target = Company(ticker="A.NS", name="Company A", sector="banking", index_tier="NIFTY50")
    peer1 = Company(ticker="B.NS", name="Company B", sector="banking", index_tier="NIFTY50")
    peer2 = Company(ticker="C.NS", name="Company C", sector="banking", index_tier="OTHER")
    other_sector = Company(ticker="D.NS", name="Company D", sector="auto", index_tier="NIFTY50")
    db_session.add_all([target, peer1, peer2, other_sector])
    db_session.commit()

    peers = get_sector_peers(db_session, target)

    tickers = {p.ticker for p in peers}
    assert tickers == {"B.NS", "C.NS"}


def test_get_sector_peers_excludes_the_company_itself(db_session):
    target = Company(ticker="A.NS", name="Company A", sector="banking", index_tier="NIFTY50")
    db_session.add(target)
    db_session.commit()

    peers = get_sector_peers(db_session, target)

    assert target.ticker not in {p.ticker for p in peers}


def test_get_sector_peers_respects_limit(db_session):
    target = Company(ticker="A.NS", name="Company A", sector="banking", index_tier="NIFTY50")
    db_session.add(target)
    for i in range(15):
        db_session.add(Company(ticker=f"P{i}.NS", name=f"Peer {i}", sector="banking", index_tier="OTHER"))
    db_session.commit()

    peers = get_sector_peers(db_session, target, limit=5)

    assert len(peers) == 5


def test_get_sector_peers_empty_when_no_peers_exist(db_session):
    target = Company(ticker="A.NS", name="Company A", sector="banking", index_tier="NIFTY50")
    db_session.add(target)
    db_session.commit()

    assert get_sector_peers(db_session, target) == []
