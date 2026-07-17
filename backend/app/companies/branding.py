from app.config import settings
from app.models import Company


def logo_url(company: Company) -> str | None:
    if not settings.brandfetch_client_id:
        return None
    if company.isin:
        return f"https://cdn.brandfetch.io/isin/{company.isin}?c={settings.brandfetch_client_id}"
    return f"https://cdn.brandfetch.io/ticker/{company.ticker}?c={settings.brandfetch_client_id}"
