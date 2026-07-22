"""Standalone verification: confirm every ticker in
app.market.sector_indices.SECTOR_INDEX_MAP actually returns data from
yfinance. Run manually (real network call, not part of the pytest suite):

    cd backend && python verify_sector_indices.py

Per the Phase 1 task brief: "Verify each ticker actually returns data from
yfinance before committing the map; report any that don't."
"""
import yfinance as yf

from app.market.sector_indices import SECTOR_INDEX_MAP


def main() -> None:
    unique_tickers = sorted(set(SECTOR_INDEX_MAP.values()))
    failures = []
    for ticker in unique_tickers:
        try:
            history = yf.Ticker(ticker).history(period="5d", interval="1d")
            ok = len(history) > 0
        except Exception as exc:  # noqa: BLE001 -- report, don't crash the script
            ok = False
            print(f"{ticker}: EXCEPTION {exc}")
            failures.append(ticker)
            continue
        print(f"{ticker}: {'OK (' + str(len(history)) + ' rows)' if ok else 'NO DATA'}")
        if not ok:
            failures.append(ticker)

    print()
    if failures:
        print(f"FAILED tickers ({len(failures)}): {failures}")
    else:
        print("All sector-index tickers returned data.")


if __name__ == "__main__":
    main()
