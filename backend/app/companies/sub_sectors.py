"""Closed sub-sector vocabulary, one level below app.analysis.schemas.SECTORS,
plus the LLM classification helpers used by the one-time enrichment job
(see backend/backfill_subsectors.py).

Same discipline as SECTORS: a fixed, closed list per sector rather than
LLM-invented strings, so every drilldown branch is guaranteed to resolve to
a known label and to its parent sector's already-validated color on the
frontend. Every sector's list ends with an explicit "<sector>_other" escape
value so an ambiguous company gets an honest bucket instead of a forced
wrong fit -- the same "omit rather than mismatch" philosophy
app.companies.resolution already applies.

"other" (the SECTORS catch-all) is intentionally excluded here -- there is
no meaningful sub-classification for it, and Company.sub_sector simply stays
NULL forever for companies in that sector. The frontend renders NULL as a
flat, unbucketed list under the sector, not an error state.
"""

import json

from openai import RateLimitError

from app.analysis.claude_client import FALLBACK_MODEL, MODEL

SUB_SECTOR_TAXONOMY: dict[str, list[str]] = {
    "oil_gas": [
        "upstream_exploration", "refining_marketing", "gas_distribution", "oil_gas_other",
    ],
    "banking": [
        "private_bank", "psu_bank", "nbfc", "housing_finance", "insurance", "asset_management", "banking_other",
    ],
    "auto": [
        "passenger_vehicle", "two_wheeler", "commercial_vehicle", "auto_component", "auto_other",
    ],
    "it": [
        "it_services_large_cap", "it_services_mid_small_cap", "product_saas", "it_other",
    ],
    "pharma": [
        "generics_formulations", "specialty_pharma", "hospital_diagnostics", "api_cdmo", "pharma_other",
    ],
    "fmcg": [
        "staples_food", "personal_care", "beverages", "retail", "fmcg_other",
    ],
    "metals": [
        "steel", "non_ferrous", "mining_coal", "metals_other",
    ],
    "telecom": [
        "telecom_operator", "telecom_infrastructure", "telecom_other",
    ],
    "infra": [
        "construction_engineering", "power_utilities", "capital_goods", "cement", "infra_other",
    ],
}

# Short definitions for the classification prompt, same terse style as
# claude_client.py's SECTOR_DEFINITIONS.
SUB_SECTOR_DEFINITIONS: dict[str, str] = {
    "oil_gas": (
        "- upstream_exploration: oil & gas exploration and production (E&P).\n"
        "- refining_marketing: refiners and fuel marketing companies.\n"
        "- gas_distribution: city gas distribution and pipeline operators.\n"
        "- oil_gas_other: none of the above cleanly."
    ),
    "banking": (
        "- private_bank: privately-owned scheduled commercial banks.\n"
        "- psu_bank: public-sector/government-owned banks.\n"
        "- nbfc: non-bank lenders (consumer/vehicle/gold loans etc).\n"
        "- housing_finance: dedicated home-loan lenders.\n"
        "- insurance: life or general insurers.\n"
        "- asset_management: mutual fund / asset management companies.\n"
        "- banking_other: none of the above cleanly."
    ),
    "auto": (
        "- passenger_vehicle: passenger car manufacturers.\n"
        "- two_wheeler: motorcycle/scooter manufacturers.\n"
        "- commercial_vehicle: truck/bus manufacturers.\n"
        "- auto_component: auto parts and component makers, not full-vehicle OEMs.\n"
        "- auto_other: none of the above cleanly."
    ),
    "it": (
        "- it_services_large_cap: large, well-established IT services/consulting firms.\n"
        "- it_services_mid_small_cap: smaller IT services/consulting firms.\n"
        "- product_saas: product or SaaS companies, not primarily services.\n"
        "- it_other: none of the above cleanly."
    ),
    "pharma": (
        "- generics_formulations: generic drug manufacturers.\n"
        "- specialty_pharma: specialty/branded pharma companies.\n"
        "- hospital_diagnostics: hospitals and diagnostic chains.\n"
        "- api_cdmo: active pharmaceutical ingredient (API) and CDMO/contract manufacturers.\n"
        "- pharma_other: none of the above cleanly."
    ),
    "fmcg": (
        "- staples_food: packaged food and staples companies.\n"
        "- personal_care: personal care and home care companies.\n"
        "- beverages: beverage companies.\n"
        "- retail: retail chains.\n"
        "- fmcg_other: none of the above cleanly."
    ),
    "metals": (
        "- steel: steel producers.\n"
        "- non_ferrous: non-ferrous metal producers (aluminium, copper, zinc, etc).\n"
        "- mining_coal: mining and coal companies.\n"
        "- metals_other: none of the above cleanly."
    ),
    "telecom": (
        "- telecom_operator: mobile/broadband network operators.\n"
        "- telecom_infrastructure: tower, equipment, and infrastructure companies.\n"
        "- telecom_other: none of the above cleanly."
    ),
    "infra": (
        "- construction_engineering: construction and engineering (EPC) contractors.\n"
        "- power_utilities: power generation, transmission, and utility companies.\n"
        "- capital_goods: industrial and capital goods manufacturers.\n"
        "- cement: cement manufacturers.\n"
        "- infra_other: none of the above cleanly."
    ),
}


def is_valid_sub_sector(sector: str, sub_sector: str) -> bool:
    return sub_sector in SUB_SECTOR_TAXONOMY.get(sector, [])


def other_bucket(sector: str) -> str:
    """The guaranteed-valid fallback sub-sector for a given sector."""
    return f"{sector}_other"


def classify_batch(client, sector: str, tickers_and_names: list[tuple[str, str]]) -> dict[str, str]:
    """One tool-call classifying every (ticker, name) pair into that sector's
    sub-sector enum. Returns {ticker: sub_sector}. A ticker the model returns
    with a missing/off-enum sub_sector falls back to other_bucket(sector)
    rather than raising -- same "omit rather than mismatch" philosophy as
    app.companies.resolution. A ticker the model omits entirely from its
    response is simply absent from the returned dict -- the caller
    (backfill_subsectors.py) leaves its sub_sector NULL and retries it on the
    next run, rather than guessing a bucket for a company the model never
    addressed.
    """
    tool = build_classify_tool(sector)
    listing = "\n".join(f"- {ticker}: {name}" for ticker, name in tickers_and_names)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a financial sector-classification analyst. Classify each "
                f"listed company into exactly one {sector} sub-sector from the given "
                "enum, based on its actual, primary line of business."
            ),
        },
        {"role": "user", "content": f"Companies to classify:\n{listing}"},
    ]

    def _call(model: str):
        return client.chat.completions.create(
            model=model,
            max_tokens=4096,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_subsector_classifications"}},
            messages=messages,
        )

    try:
        response = _call(MODEL)
    except RateLimitError:
        response = _call(FALLBACK_MODEL)

    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((tc for tc in tool_calls if tc.function.name == "record_subsector_classifications"), None)
    if tool_call is None:
        return {}

    arguments = json.loads(tool_call.function.arguments)
    result: dict[str, str] = {}
    for entry in arguments.get("classifications", []):
        ticker = entry.get("ticker")
        sub_sector = entry.get("sub_sector")
        if not ticker:
            continue
        if sub_sector and is_valid_sub_sector(sector, sub_sector):
            result[ticker] = sub_sector
        else:
            result[ticker] = other_bucket(sector)
    return result


def build_classify_tool(sector: str) -> dict:
    """Tool schema for one batched sub-sector classification call, scoped to
    a single sector's own sub-sector list only -- a tight, unambiguous enum
    (not all ~35 values across every sector), matching the precision
    discipline already used for SECTOR_DEFINITIONS in claude_client.py."""
    allowed = SUB_SECTOR_TAXONOMY[sector]
    return {
        "type": "function",
        "function": {
            "name": "record_subsector_classifications",
            "description": f"Classify each company into a {sector} sub-sector.",
            "parameters": {
                "type": "object",
                "properties": {
                    "classifications": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ticker": {"type": "string"},
                                "sub_sector": {"type": "string", "enum": allowed},
                            },
                            "required": ["ticker", "sub_sector"],
                        },
                    },
                },
                "required": ["classifications"],
            },
        },
    }
