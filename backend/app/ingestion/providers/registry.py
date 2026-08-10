"""The provider registry: every ingestion source Newsflo knows about.

Adding a source = one provider module + one entry here. The collector,
scheduler, and health endpoint all iterate this dict; none of them know
any provider by name.

Which sources actually RUN is decided per deployment, not here:
IngestionSource rows seed `enabled` from settings.ingestion_enabled_sources
on first boot (see app/ingestion/collector.py.ensure_registry_rows), and
the DB row is the live switch afterwards. Every entry below being
registered costs nothing while disabled.

Feed URLs verified live 2026-08-10 (PIB's reg/Lang combination
specifically: Lang=1&Regid=3&reg=3 is the English national feed --
other combinations redirect to Hindi).
"""
from app.ingestion.providers.base import Provider
from app.ingestion.providers.benzinga import BenzingaProvider
from app.ingestion.providers.bse import BseAnnouncementsProvider
from app.ingestion.providers.finnhub import FinnhubProvider
from app.ingestion.providers.gdelt import GdeltProvider
from app.ingestion.providers.indianapi import IndianApiProvider
from app.ingestion.providers.marketaux import MarketauxProvider
from app.ingestion.providers.rss import BROWSER_UA_HEADERS, NseAnnouncementsProvider, RssProvider

_PROVIDERS: list[Provider] = [
    # API sources
    FinnhubProvider(),
    IndianApiProvider(),
    MarketauxProvider(),
    BenzingaProvider(),
    GdeltProvider(),
    # Exchange feeds -- primary disclosures
    NseAnnouncementsProvider(
        slug="nse",
        display_name="NSE Announcements",
        source_name="nse",
        feed_url="https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml",
        headers=BROWSER_UA_HEADERS,
    ),
    BseAnnouncementsProvider(),
    # Indian government / regulator feeds -- primary sources
    RssProvider(
        slug="pib",
        display_name="PIB Press Releases",
        source_name="pib",
        feed_url="https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3&reg=3",
        headers=BROWSER_UA_HEADERS,
        poll_interval_minutes=10,
    ),
    RssProvider(
        slug="rbi",
        display_name="RBI Press Releases",
        source_name="rbi",
        feed_url="https://www.rbi.org.in/pressreleases_rss.xml",
        headers=BROWSER_UA_HEADERS,
        poll_interval_minutes=10,
    ),
    RssProvider(
        slug="sebi",
        display_name="SEBI Updates",
        source_name="sebi",
        feed_url="https://www.sebi.gov.in/sebirss.xml",
        headers=BROWSER_UA_HEADERS,
        poll_interval_minutes=10,
    ),
    # Indian press RSS -- the feeds the legacy poller (poller.py/sources.py)
    # served before it was unwired, now one health-tracked source each
    # Browser UA on all three: Business Standard 403s a default client UA
    # outright (verified live 2026-08-10), and the other two gain nothing
    # from advertising one.
    RssProvider(
        slug="economic_times",
        display_name="Economic Times Markets",
        source_name="economic_times",
        feed_url="https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        headers=BROWSER_UA_HEADERS,
    ),
    RssProvider(
        slug="moneycontrol",
        display_name="Moneycontrol Market Reports",
        source_name="moneycontrol",
        feed_url="https://www.moneycontrol.com/rss/marketreports.xml",
        headers=BROWSER_UA_HEADERS,
    ),
    # Business Standard's RSS (the legacy poller's third feed) is gone --
    # Akamai 403s every client including browser UAs (verified live
    # 2026-08-10). Replaced with LiveMint + Hindu BusinessLine markets
    # feeds, both verified live the same day.
    RssProvider(
        slug="livemint",
        display_name="LiveMint Markets",
        source_name="livemint",
        feed_url="https://www.livemint.com/rss/markets",
        headers=BROWSER_UA_HEADERS,
    ),
    RssProvider(
        slug="hindu_businessline",
        display_name="Hindu BusinessLine Markets",
        source_name="hindu_businessline",
        feed_url="https://www.thehindubusinessline.com/markets/feeder/default.rss",
        headers=BROWSER_UA_HEADERS,
    ),
]

PROVIDER_REGISTRY: dict[str, Provider] = {provider.slug: provider for provider in _PROVIDERS}
