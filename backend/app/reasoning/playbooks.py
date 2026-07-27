"""Sector-specific reasoning playbooks, injected as static reference context
alongside the rulebook (see app.reasoning.rulebook for the always-on
rationale). Keyed by the same lowercase sector values as
app.analysis.schemas.SECTORS -- "other" intentionally has no playbook.
"""

from app.analysis.schemas import SECTORS

PLAYBOOKS: dict[str, str] = {
    "banking": (
        "Banking: KPIs are NIM, CASA, credit growth, deposit growth, GNPA, "
        "NNPA, ROA, ROE. Bullish: repo cuts (context dependent), credit "
        "growth, lower NPAs, strong deposit franchise. Bearish: asset "
        "quality deterioration, weak credit demand, regulatory tightening."
    ),
    "it": (
        "IT services: revenue driven by global enterprise spending, "
        "outsourcing, cloud migration, AI adoption. Sensitive to USD/INR, US "
        "recession risk, technology budgets. KPIs: deal wins, attrition, "
        "EBIT margin, utilization."
    ),
    "pharma": (
        "Pharma: drivers are USFDA approvals, generic launches, export "
        "demand, currency. Risks: regulatory actions, pricing pressure."
    ),
    "fmcg": (
        "FMCG: drivers are rural demand, urban demand, inflation, commodity "
        "costs. Watch gross margins and volume growth separately -- a price "
        "hike can grow margins while volume falls."
    ),
    "auto": (
        "Auto: drivers are consumer confidence, interest rates, steel and "
        "aluminium input costs, fuel prices. KPIs: volume growth, dealer "
        "inventory."
    ),
    "oil_gas": (
        "Oil & gas: sub-sectors (upstream, midstream, downstream) react "
        "differently to the same crude move -- upstream/exploration "
        "benefits from higher crude, downstream/refining margins depend on "
        "the crude-product spread, not crude direction alone. Also "
        "sensitive to government fuel-pricing policy."
    ),
    "metals": (
        "Metals: watch China demand, domestic infrastructure spend, and "
        "commodity prices. Propagation: infrastructure spend up -> steel up "
        "-> mining up."
    ),
    "telecom": (
        "Telecom: drivers are ARPU, subscriber growth, spectrum costs, and "
        "capex cycles."
    ),
    "infra": (
        "Infrastructure/industrials: drivers are government capex, private "
        "capex cycle, input costs (cement, steel), and execution/order-book "
        "visibility."
    ),
    "railways_transport": (
        "Transport: aviation drivers are passenger demand, jet fuel (ATF, ~40% "
        "of cost), and USD/INR (fuel/leases are dollar costs); KPIs are load "
        "factor and yields. Ports/shipping track trade volumes and freight "
        "rates. Road logistics tracks fuel costs, e-commerce, and "
        "manufacturing activity. Rail equipment tracks government railway "
        "capex."
    ),
    "construction_realestate": (
        "Real estate: drivers are mortgage rates, affordability, and job/income "
        "confidence. KPIs: pre-sales/bookings, collections, net debt, "
        "inventory months. Commercial/REIT depends on office absorption and "
        "retail footfalls. Highly rate-sensitive in both directions."
    ),
    "defense": (
        "Defense: driven by government procurement orders, indigenization "
        "policy, and export wins. KPIs: order book vs annual revenue, "
        "execution pace. Order-to-revenue lag runs years -- wins change "
        "visibility, not next quarter."
    ),
    "agriculture": (
        "Agri inputs: driven by monsoon/sowing, minimum support prices, and "
        "subsidy policy (urea subsidies drive fertilizer economics; gas is "
        "the key input cost). Agrochemical demand tracks planted acreage and "
        "pest cycles. Watch subsidy-receivable delays on fertilizer balance "
        "sheets."
    ),
    "consumer_durables": (
        "Consumer durables: driven by festive/summer season demand, consumer "
        "financing availability, and input costs (copper, aluminium, steel, "
        "imported electronics). Rate-sensitive (EMI purchases). KPIs: volume "
        "growth, channel inventory. PLI schemes shift manufacturing "
        "economics."
    ),
    "media_entertainment": (
        "Media: ad revenue tracks GDP and consumer-sector health (FMCG/auto "
        "are the biggest advertisers). Subscription/OTT growth structural; "
        "multiplexes track box-office slate and occupancy. KPIs: ad growth, "
        "subscriber counts, occupancy rates."
    ),
    "chemicals": (
        "Chemicals: crude derivatives are the feedstock -- margins move "
        "inversely with crude. China supply/pricing swings global spreads "
        "(Chinese oversupply crushes realizations). Specialty chemicals have "
        "stickier pricing than commodity chemicals. KPIs: spreads, capacity "
        "utilization, export mix."
    ),
    "textiles": (
        "Textiles: cotton/yarn prices drive spinning margins (spread between "
        "cotton and yarn). Export demand from US/EU retail, USD/INR, and "
        "trade agreements (UK/EU FTAs, China+1 shifts) drive orders. KPIs: "
        "yarn spreads, export order books, utilization."
    ),
}

PLAYBOOKS_TEXT = "\n".join(f"- {sector}: {text}" for sector, text in PLAYBOOKS.items())


def get_playbook(sector: str | None) -> str | None:
    if sector is None:
        return None
    return PLAYBOOKS.get(sector)
