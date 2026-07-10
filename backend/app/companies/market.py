def infer_market(ticker: str) -> str:
    """Derive the market ("IN" | "GLOBAL") from the ticker suffix.

    Indian NSE/BSE tickers carry a ".NS"/".BO" suffix (Plan 1 convention);
    everything else is a plain NYSE/NASDAQ-style symbol treated as GLOBAL.
    Computed at read time so no market column is stored (no migration).
    """
    return "IN" if ticker.endswith((".NS", ".BO")) else "GLOBAL"
