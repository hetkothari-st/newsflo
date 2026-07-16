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
}

PLAYBOOKS_TEXT = "\n".join(f"- {sector}: {text}" for sector, text in PLAYBOOKS.items())


def get_playbook(sector: str | None) -> str | None:
    if sector is None:
        return None
    return PLAYBOOKS.get(sector)
