from app.companies.market import infer_market


def test_infer_market_ns_is_india():
    assert infer_market("RELIANCE.NS") == "IN"


def test_infer_market_bo_is_india():
    assert infer_market("500325.BO") == "IN"


def test_infer_market_plain_ticker_is_global():
    assert infer_market("AAPL") == "GLOBAL"
