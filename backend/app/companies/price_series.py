import yfinance as yf


def fetch_price_series(ticker: str, period: str) -> list[dict] | None:
    """Return daily closing prices for ``ticker`` over ``period`` (a yfinance
    period string, e.g. "1mo"/"3mo"/"6mo"/"1y") as
    ``[{"date": "YYYY-MM-DD", "close": float}, ...]``, oldest first, or
    ``None`` if data is unavailable or the fetch fails.

    Same "never raise, degrade to None" contract as
    ``app.outcomes.price_fetcher.fetch_price_change_pct`` -- a live
    third-party call on the request path should never 500 the page it feeds.
    """
    try:
        history = yf.Ticker(ticker).history(period=period, interval="1d")
        close = history["Close"]
        if len(close) == 0:
            return None
        return [
            {"date": index.strftime("%Y-%m-%d"), "close": float(value)}
            for index, value in close.items()
        ]
    except Exception:
        return None
