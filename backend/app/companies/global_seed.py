from sqlalchemy.orm import Session

from app.models import Company

# Curated static list of ~50 real, well-known global large-cap companies, ~5 per
# sector, spanning the SAME fixed SECTORS taxonomy used for Indian companies so
# sector-inference resolution works identically for both markets. Tickers are
# real NYSE/NASDAQ symbols with NO .NS/.BO suffix -> infer_market -> "GLOBAL".
GLOBAL_COMPANIES: list[dict] = [
    # it
    {"ticker": "AAPL", "name": "Apple", "sector": "it"},
    {"ticker": "MSFT", "name": "Microsoft", "sector": "it"},
    {"ticker": "GOOGL", "name": "Alphabet", "sector": "it"},
    {"ticker": "NVDA", "name": "NVIDIA", "sector": "it"},
    {"ticker": "META", "name": "Meta Platforms", "sector": "it"},
    # banking
    {"ticker": "JPM", "name": "JPMorgan Chase", "sector": "banking"},
    {"ticker": "BAC", "name": "Bank of America", "sector": "banking"},
    {"ticker": "WFC", "name": "Wells Fargo", "sector": "banking"},
    {"ticker": "HSBC", "name": "HSBC Holdings", "sector": "banking"},
    {"ticker": "C", "name": "Citigroup", "sector": "banking"},
    # oil_gas
    {"ticker": "XOM", "name": "ExxonMobil", "sector": "oil_gas"},
    {"ticker": "CVX", "name": "Chevron", "sector": "oil_gas"},
    {"ticker": "SHEL", "name": "Shell", "sector": "oil_gas"},
    {"ticker": "BP", "name": "BP", "sector": "oil_gas"},
    {"ticker": "COP", "name": "ConocoPhillips", "sector": "oil_gas"},
    # auto
    {"ticker": "TSLA", "name": "Tesla", "sector": "auto"},
    {"ticker": "TM", "name": "Toyota Motor", "sector": "auto"},
    {"ticker": "VWAGY", "name": "Volkswagen", "sector": "auto"},
    {"ticker": "F", "name": "Ford Motor", "sector": "auto"},
    {"ticker": "GM", "name": "General Motors", "sector": "auto"},
    # pharma
    {"ticker": "PFE", "name": "Pfizer", "sector": "pharma"},
    {"ticker": "JNJ", "name": "Johnson & Johnson", "sector": "pharma"},
    {"ticker": "RHHBY", "name": "Roche Holding", "sector": "pharma"},
    {"ticker": "NVS", "name": "Novartis", "sector": "pharma"},
    {"ticker": "MRK", "name": "Merck & Co.", "sector": "pharma"},
    # fmcg
    {"ticker": "PG", "name": "Procter & Gamble", "sector": "fmcg"},
    {"ticker": "KO", "name": "Coca-Cola", "sector": "fmcg"},
    {"ticker": "PEP", "name": "PepsiCo", "sector": "fmcg"},
    {"ticker": "UL", "name": "Unilever", "sector": "fmcg"},
    {"ticker": "NSRGY", "name": "Nestle", "sector": "fmcg"},
    # metals
    {"ticker": "MT", "name": "ArcelorMittal", "sector": "metals"},
    {"ticker": "RIO", "name": "Rio Tinto", "sector": "metals"},
    {"ticker": "BHP", "name": "BHP Group", "sector": "metals"},
    {"ticker": "VALE", "name": "Vale", "sector": "metals"},
    {"ticker": "AA", "name": "Alcoa", "sector": "metals"},
    # telecom
    {"ticker": "VZ", "name": "Verizon Communications", "sector": "telecom"},
    {"ticker": "T", "name": "AT&T", "sector": "telecom"},
    {"ticker": "VOD", "name": "Vodafone Group", "sector": "telecom"},
    {"ticker": "DTEGY", "name": "Deutsche Telekom", "sector": "telecom"},
    {"ticker": "TMUS", "name": "T-Mobile US", "sector": "telecom"},
    # infra
    {"ticker": "CAT", "name": "Caterpillar", "sector": "infra"},
    {"ticker": "DE", "name": "Deere & Company", "sector": "infra"},
    {"ticker": "HON", "name": "Honeywell International", "sector": "infra"},
    {"ticker": "MMM", "name": "3M", "sector": "infra"},
    {"ticker": "GE", "name": "General Electric", "sector": "infra"},
    # other
    {"ticker": "BRK.B", "name": "Berkshire Hathaway", "sector": "other"},
    {"ticker": "DIS", "name": "Walt Disney", "sector": "other"},
    {"ticker": "AMZN", "name": "Amazon.com", "sector": "other"},
    {"ticker": "V", "name": "Visa", "sector": "other"},
    {"ticker": "MA", "name": "Mastercard", "sector": "other"},
]


def load_global_companies(session: Session) -> int:
    """Upsert every GLOBAL_COMPANIES entry as a Company row.

    Mirrors load_companies_from_csv's query-before-insert upsert pattern
    (no reliance on catching a unique-constraint error). All rows get
    index_tier="GLOBAL_LARGE_CAP" and market_cap=None.
    """
    count = 0
    for entry in GLOBAL_COMPANIES:
        existing = session.query(Company).filter_by(ticker=entry["ticker"]).one_or_none()
        if existing:
            existing.name = entry["name"]
            existing.sector = entry["sector"]
            existing.index_tier = "GLOBAL_LARGE_CAP"
        else:
            session.add(Company(
                ticker=entry["ticker"], name=entry["name"], sector=entry["sector"],
                index_tier="GLOBAL_LARGE_CAP", market_cap=None,
            ))
        count += 1
    session.commit()
    return count
