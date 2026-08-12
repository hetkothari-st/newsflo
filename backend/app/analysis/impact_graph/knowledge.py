"""Economic knowledge registry (cost-opt spec 2026-08-12 P2/P4/P5).

Static economic intelligence that Gemini was re-deriving on every article:
which exposure classes a macro shock transmits to, through what mechanism,
in which direction. Three layers:

1. EXPOSURE_ARCHETYPES -- canonical exposure classes mapped to the REAL
   company vocabulary (sector + sub_sector + business_desc keywords, taken
   from the live companies table, never invented).
2. MECHANISMS -- reusable causal channels: trigger variable -> exposure
   archetype, with direction, mechanism text, horizon, confidence baseline
   and provenance. A mechanism is a CANDIDATE PRIOR -- Gemini judges
   whether it applies to the current event and can override it.
3. EVENT_ARCHETYPES -- recurring event patterns (crude shock, rate change,
   Hormuz-style supply disruption...) that select a mechanism slice
   deterministically, so Pro never rediscovers a known universe.

Matching is DETERMINISTIC (event_type + keywords over extracted facts) --
no LLM call. No match -> the engine's dynamic discovery path runs exactly
as before; novel events are never forced through a template.

Provenance discipline: mechanism content is curated from this system's own
verified production output (impact-graph runs whose companies survived
independent verification + measurement) and standard sector economics
already encoded in the prompts' examples. No company-specific facts live
here -- companies arrive only through the archetype->DB retrieval.
"""
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.companies.integrity import DEMO_TICKERS
from app.models import Company

# Bump on ANY change to archetypes/mechanisms/event templates: rides the
# semantic-cache fingerprint, so registry edits are explicit invalidations.
KNOWLEDGE_REGISTRY_VERSION = "kg-1"


# --- P4: exposure archetypes ----------------------------------------------
# sector / sub_sectors match Company rows exactly (vocabulary verified
# against the live table 2026-08-12). desc_keywords are LIKE-matched on
# business_desc for archetypes finer than the sub_sector grid.

EXPOSURE_ARCHETYPES: dict[str, dict] = {
    "upstream_oil_producer": {"sector": "oil_gas", "sub_sectors": ["upstream_exploration"],
                              "desc_keywords": ["exploration", "upstream", "crude oil"]},
    "oil_refiner_marketer": {"sector": "oil_gas", "sub_sectors": ["refining_marketing"],
                             "desc_keywords": ["refin", "petroleum product", "oil marketing"]},
    "gas_distributor": {"sector": "oil_gas", "sub_sectors": ["gas_distribution"]},
    "lubricant_producer": {"sector": "oil_gas", "desc_keywords": ["lubricant", "base oil", "grease"]},
    "petrochemical_producer": {"sector": "chemicals",
                               "desc_keywords": ["petrochemical", "polymer", "phenol",
                                                 "carbon black", "resin"]},
    "specialty_chemical_producer": {"sector": "chemicals", "sub_sectors": ["specialty_chemicals"]},
    "commodity_chemical_producer": {"sector": "chemicals", "sub_sectors": ["commodity_chemicals"]},
    "paint_producer": {"desc_keywords": ["paint", "coating"]},
    "tyre_producer": {"sector": "auto", "desc_keywords": ["tyre", "tire"]},
    "airline": {"desc_keywords": ["airline", "air transport", "aviation"]},
    "logistics_operator": {"sector": "railways_transport",
                           "desc_keywords": ["logistic", "freight", "cargo", "warehous",
                                             "supply chain", "courier", "transport"]},
    "shipping_port_operator": {"desc_keywords": ["shipping", "port", "vessel", "marine"]},
    "cement_producer": {"sector": "infra", "sub_sectors": ["cement"]},
    "power_utility": {"sector": "infra", "sub_sectors": ["power_utilities"]},
    "construction_epc": {"sector": "infra", "sub_sectors": ["construction_engineering"]},
    "capital_goods_manufacturer": {"sector": "infra", "sub_sectors": ["capital_goods"]},
    "steel_producer": {"sector": "metals", "sub_sectors": ["steel"]},
    "non_ferrous_producer": {"sector": "metals", "sub_sectors": ["non_ferrous"]},
    "metals_producer": {"sector": "metals"},
    "auto_manufacturer": {"sector": "auto", "sub_sectors": ["passenger_vehicle", "auto_other"]},
    "two_wheeler_manufacturer": {"sector": "auto", "sub_sectors": ["two_wheeler"]},
    "auto_component_maker": {"sector": "auto", "sub_sectors": ["auto_component"]},
    "ev_manufacturer": {"sector": "auto", "desc_keywords": ["electric vehicle", "electric two",
                                                            "electric scooter", "ev "]},
    "bank": {"sector": "banking", "sub_sectors": ["private_bank", "psu_bank"]},
    "nbfc": {"sector": "banking", "sub_sectors": ["nbfc", "housing_finance"]},
    "insurer": {"sector": "banking", "sub_sectors": ["insurance"]},
    "asset_manager": {"sector": "banking", "sub_sectors": ["asset_management"]},
    "real_estate_developer": {"sector": "construction_realestate"},
    "fmcg_consumer_staples": {"sector": "fmcg",
                              "sub_sectors": ["staples_food", "personal_care", "beverages",
                                              "fmcg_other"]},
    "retailer": {"sector": "fmcg", "sub_sectors": ["retail"]},
    "consumer_discretionary": {"sector": "consumer_durables"},
    "appliance_maker": {"sector": "consumer_durables", "sub_sectors": ["appliances_electronics"]},
    "it_services": {"sector": "it"},
    "pharma_manufacturer": {"sector": "pharma",
                            "sub_sectors": ["generics_formulations", "api_cdmo", "specialty_pharma"]},
    "hospital_operator": {"sector": "pharma", "sub_sectors": ["hospital_diagnostics"]},
    "telecom_operator": {"sector": "telecom", "sub_sectors": ["telecom_operator"]},
    "textile_manufacturer": {"sector": "textiles"},
    "agri_producer": {"sector": "agriculture"},
    "fertilizer_agrochemical": {"desc_keywords": ["fertilizer", "fertiliser", "agrochemical",
                                                  "pesticide", "crop protection"]},
    "defense_manufacturer": {"sector": "defense"},
    "media_broadcaster": {"sector": "media_entertainment"},
}


# --- P2: economic mechanism registry --------------------------------------
# Effects are for the mechanism's CANONICAL trigger direction (the
# `parent_variable` name states it, e.g. crude_price_up). oriented() flips
# them when the event moves the variable the other way.
# confidence_baseline: prior strength -- Gemini re-scores per event.
# distance: causal hops from the trigger variable to the exposure class.

_PROV_VERIFIED = "production-verified (impact-graph runs, measured + verified)"
_PROV_CURATED = "curated sector economics (prompt-spec examples)"

MECHANISMS: dict[str, dict] = {
    # -- crude oil family --
    "upstream_realization": {
        "parent_variable": "crude_price_up", "child_exposure": "upstream_oil_producer",
        "effect": "positive", "distance": 1, "time_horizon": "Immediate",
        "confidence_baseline": 0.9, "provenance": _PROV_VERIFIED,
        "mechanism": "Higher crude realization per barrel directly improves upstream producers' revenue economics.",
    },
    "refiner_marketing_margin": {
        "parent_variable": "crude_price_up", "child_exposure": "oil_refiner_marketer",
        "effect": "negative", "distance": 1, "time_horizon": "Short-Term",
        "confidence_baseline": 0.8, "provenance": _PROV_VERIFIED,
        "mechanism": "Higher crude feedstock cost squeezes refining/marketing margins where retail pass-through lags; inventory gains can partly offset -- judge net per event.",
    },
    "lubricant_base_oil_cost": {
        "parent_variable": "crude_price_up", "child_exposure": "lubricant_producer",
        "effect": "negative", "distance": 2, "time_horizon": "Short-Term",
        "confidence_baseline": 0.8, "provenance": _PROV_VERIFIED,
        "mechanism": "Base-oil (crude derivative) input costs rise, compressing lubricant margins until price hikes catch up.",
    },
    "petrochemical_feedstock": {
        "parent_variable": "crude_price_up", "child_exposure": "petrochemical_producer",
        "effect": "negative", "distance": 2, "time_horizon": "Short-Term",
        "confidence_baseline": 0.8, "provenance": _PROV_VERIFIED,
        "mechanism": "Hydrocarbon feedstock costs rise with crude, compressing petrochemical spreads and margins.",
    },
    "paints_input_cost": {
        "parent_variable": "crude_price_up", "child_exposure": "paint_producer",
        "effect": "negative", "distance": 2, "time_horizon": "Short-Term",
        "confidence_baseline": 0.75, "provenance": _PROV_VERIFIED,
        "mechanism": "Crude-derivative raw materials (monomers, solvents, titanium dioxide carriers) are a large share of paint input cost.",
    },
    "tyre_input_cost": {
        "parent_variable": "crude_price_up", "child_exposure": "tyre_producer",
        "effect": "negative", "distance": 2, "time_horizon": "Short-Term",
        "confidence_baseline": 0.75, "provenance": _PROV_CURATED,
        "mechanism": "Crude-linked inputs (synthetic rubber, carbon black) raise tyre production costs.",
    },
    "aviation_fuel_cost": {
        "parent_variable": "crude_price_up", "child_exposure": "airline",
        "effect": "negative", "distance": 2, "time_horizon": "Immediate",
        "confidence_baseline": 0.9, "provenance": _PROV_CURATED,
        "mechanism": "ATF tracks crude; fuel is the largest airline operating cost, so margins compress quickly.",
    },
    "road_freight_fuel_cost": {
        "parent_variable": "crude_price_up", "child_exposure": "logistics_operator",
        "effect": "negative", "distance": 2, "time_horizon": "Short-Term",
        "confidence_baseline": 0.75, "provenance": _PROV_CURATED,
        "mechanism": "Diesel cost is the dominant variable cost in road freight; pass-through to customers lags.",
    },
    "cement_energy_freight": {
        "parent_variable": "crude_price_up", "child_exposure": "cement_producer",
        "effect": "negative", "distance": 2, "time_horizon": "Short-Term",
        "confidence_baseline": 0.8, "provenance": _PROV_VERIFIED,
        "mechanism": "Diesel-linked freight and pet-coke/energy costs rise with crude, pressuring cement margins.",
    },
    "auto_fuel_demand": {
        "parent_variable": "crude_price_up", "child_exposure": "auto_manufacturer",
        "effect": "negative", "distance": 2, "time_horizon": "Medium-Term",
        "confidence_baseline": 0.7, "provenance": _PROV_VERIFIED,
        "mechanism": "Higher retail fuel prices raise total cost of ownership for ICE vehicles, weighing on demand, sharpest in price-sensitive segments.",
    },
    "two_wheeler_fuel_demand": {
        "parent_variable": "crude_price_up", "child_exposure": "two_wheeler_manufacturer",
        "effect": "negative", "distance": 2, "time_horizon": "Medium-Term",
        "confidence_baseline": 0.7, "provenance": _PROV_CURATED,
        "mechanism": "Two-wheeler buyers are the most fuel-price-sensitive segment; running-cost inflation defers purchases.",
    },
    "ev_relative_advantage": {
        "parent_variable": "crude_price_up", "child_exposure": "ev_manufacturer",
        "effect": "positive", "distance": 2, "time_horizon": "Medium-Term",
        "confidence_baseline": 0.65, "provenance": _PROV_VERIFIED,
        "mechanism": "Higher ICE running costs improve the relative total-cost-of-ownership case for EVs -- a relative, not absolute, benefit.",
    },
    "vehicle_financier_stress": {
        "parent_variable": "crude_price_up", "child_exposure": "nbfc",
        "effect": "negative", "distance": 3, "time_horizon": "Medium-Term",
        "confidence_baseline": 0.6, "provenance": _PROV_VERIFIED,
        "mechanism": "Higher fuel costs squeeze commercial-vehicle operator cash flows, pressuring CV-loan asset quality at vehicle financiers.",
    },
    "crude_inflation_pressure": {
        "parent_variable": "crude_price_up", "child_exposure": "fmcg_consumer_staples",
        "effect": "negative", "distance": 3, "time_horizon": "Medium-Term",
        "confidence_baseline": 0.55, "provenance": _PROV_CURATED,
        "mechanism": "Fuel-led inflation erodes household purchasing power and raises packaging/distribution costs for staples.",
    },
    "oil_import_bill_currency": {
        "parent_variable": "crude_price_up", "child_exposure": "gas_distributor",
        "effect": "negative", "distance": 2, "time_horizon": "Short-Term",
        "confidence_baseline": 0.55, "provenance": _PROV_CURATED,
        "mechanism": "Imported LNG and crude-linked gas contracts reprice upward, squeezing distributor spreads where tariffs lag.",
    },
    # -- rates family (canonical: repo_rate_up) --
    "bank_nim_repricing": {
        "parent_variable": "repo_rate_up", "child_exposure": "bank",
        "effect": "mixed", "distance": 1, "time_horizon": "Short-Term",
        "confidence_baseline": 0.75, "provenance": _PROV_CURATED,
        "mechanism": "Loan books reprice faster than deposits, initially widening NIMs; deposit-cost catch-up and credit-demand drag arrive later -- net effect is bank-specific.",
    },
    "nbfc_funding_cost": {
        "parent_variable": "repo_rate_up", "child_exposure": "nbfc",
        "effect": "negative", "distance": 1, "time_horizon": "Short-Term",
        "confidence_baseline": 0.8, "provenance": _PROV_CURATED,
        "mechanism": "Wholesale-funded NBFCs face immediate borrowing-cost increases they cannot fully pass through.",
    },
    "housing_demand_rates": {
        "parent_variable": "repo_rate_up", "child_exposure": "real_estate_developer",
        "effect": "negative", "distance": 2, "time_horizon": "Medium-Term",
        "confidence_baseline": 0.75, "provenance": _PROV_CURATED,
        "mechanism": "Higher mortgage EMIs reduce housing affordability and defer purchases, slowing developer sales velocity.",
    },
    "durables_financing_demand": {
        "parent_variable": "repo_rate_up", "child_exposure": "consumer_discretionary",
        "effect": "negative", "distance": 2, "time_horizon": "Medium-Term",
        "confidence_baseline": 0.65, "provenance": _PROV_CURATED,
        "mechanism": "Financed purchases (appliances, electronics, vehicles) become costlier as consumer-loan rates rise.",
    },
    "auto_financing_demand": {
        "parent_variable": "repo_rate_up", "child_exposure": "auto_manufacturer",
        "effect": "negative", "distance": 2, "time_horizon": "Medium-Term",
        "confidence_baseline": 0.65, "provenance": _PROV_CURATED,
        "mechanism": "Most vehicle purchases are financed; higher loan rates raise effective prices and defer demand.",
    },
    "corporate_capex_rates": {
        "parent_variable": "repo_rate_up", "child_exposure": "capital_goods_manufacturer",
        "effect": "negative", "distance": 2, "time_horizon": "Long-Term",
        "confidence_baseline": 0.6, "provenance": _PROV_CURATED,
        "mechanism": "Higher cost of capital raises project hurdle rates, deferring private capex and equipment orders.",
    },
    # -- inflation family (canonical: inflation_up) --
    "staples_volume_pressure": {
        "parent_variable": "inflation_up", "child_exposure": "fmcg_consumer_staples",
        "effect": "negative", "distance": 1, "time_horizon": "Short-Term",
        "confidence_baseline": 0.75, "provenance": _PROV_CURATED,
        "mechanism": "Household budgets compress; staples see downtrading and volume pressure even when value grows.",
    },
    "discretionary_demand_squeeze": {
        "parent_variable": "inflation_up", "child_exposure": "consumer_discretionary",
        "effect": "negative", "distance": 1, "time_horizon": "Short-Term",
        "confidence_baseline": 0.75, "provenance": _PROV_CURATED,
        "mechanism": "Discretionary purchases are deferred first when real incomes fall.",
    },
    "rate_expectation_shift": {
        "parent_variable": "inflation_up", "child_exposure": "bank",
        "effect": "mixed", "distance": 2, "time_horizon": "Medium-Term",
        "confidence_baseline": 0.6, "provenance": _PROV_CURATED,
        "mechanism": "Persistent inflation shifts policy-rate expectations upward, moving bank funding economics and bond-book valuations.",
    },
    # -- currency family (canonical: inr_depreciation) --
    "it_export_realization": {
        "parent_variable": "inr_depreciation", "child_exposure": "it_services",
        "effect": "positive", "distance": 1, "time_horizon": "Immediate",
        "confidence_baseline": 0.85, "provenance": _PROV_CURATED,
        "mechanism": "USD-billed revenue converts to more rupees; margins expand as costs are largely INR.",
    },
    "pharma_export_realization": {
        "parent_variable": "inr_depreciation", "child_exposure": "pharma_manufacturer",
        "effect": "positive", "distance": 1, "time_horizon": "Short-Term",
        "confidence_baseline": 0.7, "provenance": _PROV_CURATED,
        "mechanism": "Export-heavy formulations revenue benefits from conversion; partially offset by imported API costs.",
    },
    "textile_export_competitiveness": {
        "parent_variable": "inr_depreciation", "child_exposure": "textile_manufacturer",
        "effect": "positive", "distance": 1, "time_horizon": "Short-Term",
        "confidence_baseline": 0.65, "provenance": _PROV_CURATED,
        "mechanism": "A weaker rupee improves export price competitiveness for garment/yarn exporters.",
    },
    "import_cost_inflation": {
        "parent_variable": "inr_depreciation", "child_exposure": "oil_refiner_marketer",
        "effect": "negative", "distance": 1, "time_horizon": "Immediate",
        "confidence_baseline": 0.75, "provenance": _PROV_CURATED,
        "mechanism": "Dollar-priced crude imports cost more in rupees, raising working capital and under-recovery risk.",
    },
    "electronics_import_cost": {
        "parent_variable": "inr_depreciation", "child_exposure": "appliance_maker",
        "effect": "negative", "distance": 1, "time_horizon": "Short-Term",
        "confidence_baseline": 0.65, "provenance": _PROV_CURATED,
        "mechanism": "Imported components (compressors, panels, semiconductors) reprice upward with the dollar.",
    },
    # -- government spending family (canonical: govt_infra_spending_up) --
    "cement_demand_infra": {
        "parent_variable": "govt_infra_spending_up", "child_exposure": "cement_producer",
        "effect": "positive", "distance": 1, "time_horizon": "Medium-Term",
        "confidence_baseline": 0.8, "provenance": _PROV_CURATED,
        "mechanism": "Public infrastructure programs drive bulk cement demand.",
    },
    "epc_order_book": {
        "parent_variable": "govt_infra_spending_up", "child_exposure": "construction_epc",
        "effect": "positive", "distance": 1, "time_horizon": "Medium-Term",
        "confidence_baseline": 0.8, "provenance": _PROV_CURATED,
        "mechanism": "Project awards flow directly into EPC/construction order books.",
    },
    "steel_demand_infra": {
        "parent_variable": "govt_infra_spending_up", "child_exposure": "steel_producer",
        "effect": "positive", "distance": 1, "time_horizon": "Medium-Term",
        "confidence_baseline": 0.75, "provenance": _PROV_CURATED,
        "mechanism": "Construction steel intensity rises with infrastructure execution.",
    },
    "capital_goods_orders": {
        "parent_variable": "govt_infra_spending_up", "child_exposure": "capital_goods_manufacturer",
        "effect": "positive", "distance": 1, "time_horizon": "Medium-Term",
        "confidence_baseline": 0.7, "provenance": _PROV_CURATED,
        "mechanism": "Equipment and machinery orders track public capex cycles.",
    },
    "infra_logistics_volume": {
        "parent_variable": "govt_infra_spending_up", "child_exposure": "logistics_operator",
        "effect": "positive", "distance": 2, "time_horizon": "Long-Term",
        "confidence_baseline": 0.55, "provenance": _PROV_CURATED,
        "mechanism": "Completed corridors and freight infrastructure lift logistics volumes and efficiency.",
    },
    # -- trade/tariff family (canonical: import_tariff_up on the protected good) --
    "domestic_producer_protection": {
        "parent_variable": "import_tariff_up", "child_exposure": "steel_producer",
        "effect": "positive", "distance": 1, "time_horizon": "Short-Term",
        "confidence_baseline": 0.7, "provenance": _PROV_CURATED,
        "mechanism": "Import duties raise landed cost of foreign supply, improving domestic producers' pricing power.",
        "exclusions": ["applies to the protected good's producers only -- verify the tariff's actual product scope"],
    },
    "downstream_input_cost_tariff": {
        "parent_variable": "import_tariff_up", "child_exposure": "capital_goods_manufacturer",
        "effect": "negative", "distance": 2, "time_horizon": "Short-Term",
        "confidence_baseline": 0.6, "provenance": _PROV_CURATED,
        "mechanism": "Users of the protected input face higher raw-material costs.",
    },
    # -- geopolitical supply disruption (canonical: supply_route_disruption) --
    "freight_rate_spike": {
        "parent_variable": "supply_route_disruption", "child_exposure": "shipping_port_operator",
        "effect": "mixed", "distance": 1, "time_horizon": "Immediate",
        "confidence_baseline": 0.65, "provenance": _PROV_CURATED,
        "mechanism": "Route disruption spikes freight rates (positive for shippers with capacity) while volumes and insurance costs cut the other way.",
    },
    "defense_procurement_sentiment": {
        "parent_variable": "supply_route_disruption", "child_exposure": "defense_manufacturer",
        "effect": "positive", "distance": 2, "time_horizon": "Long-Term",
        "confidence_baseline": 0.5, "provenance": _PROV_CURATED,
        "mechanism": "Sustained geopolitical escalation supports defense procurement pipelines; weak for one-off incidents.",
    },
    # -- monsoon/rural family (canonical: monsoon_above_normal) --
    "rural_income_agri": {
        "parent_variable": "monsoon_above_normal", "child_exposure": "agri_producer",
        "effect": "positive", "distance": 1, "time_horizon": "Medium-Term",
        "confidence_baseline": 0.7, "provenance": _PROV_CURATED,
        "mechanism": "A good monsoon lifts crop output and farm incomes.",
    },
    "rural_fmcg_demand": {
        "parent_variable": "monsoon_above_normal", "child_exposure": "fmcg_consumer_staples",
        "effect": "positive", "distance": 2, "time_horizon": "Medium-Term",
        "confidence_baseline": 0.65, "provenance": _PROV_CURATED,
        "mechanism": "Higher farm incomes flow into rural staples consumption.",
    },
    "rural_two_wheeler_demand": {
        "parent_variable": "monsoon_above_normal", "child_exposure": "two_wheeler_manufacturer",
        "effect": "positive", "distance": 2, "time_horizon": "Medium-Term",
        "confidence_baseline": 0.65, "provenance": _PROV_CURATED,
        "mechanism": "Rural discretionary purchases -- two-wheelers first -- track monsoon-driven incomes.",
    },
    "agrochemical_volume": {
        "parent_variable": "monsoon_above_normal", "child_exposure": "fertilizer_agrochemical",
        "effect": "positive", "distance": 1, "time_horizon": "Short-Term",
        "confidence_baseline": 0.7, "provenance": _PROV_CURATED,
        "mechanism": "Sowing area and input intensity rise with a good monsoon.",
    },
}


# --- P5: event archetypes --------------------------------------------------
# `trigger`: the canonical variable the mechanisms are written against.
# `up_keywords` / `down_keywords`: deterministic direction detection over
# the extracted facts; no keyword hit -> direction from the matched set.

EVENT_ARCHETYPES: dict[str, dict] = {
    "CRUDE_PRICE_SHOCK": {
        "event_types": ["crude_oil"],
        "keywords": ["crude", "oil price", "brent", "wti", "opec", "petrol", "diesel"],
        "trigger": "crude_price_up",
        "up_keywords": ["rise", "rising", "surge", "spike", "jump", "high", "increase", "up"],
        "down_keywords": ["fall", "falling", "decline", "drop", "slump", "crash", "ease", "down", "low"],
        "mechanisms": ["upstream_realization", "refiner_marketing_margin", "lubricant_base_oil_cost",
                       "petrochemical_feedstock", "paints_input_cost", "tyre_input_cost",
                       "aviation_fuel_cost", "road_freight_fuel_cost", "cement_energy_freight",
                       "auto_fuel_demand", "two_wheeler_fuel_demand", "ev_relative_advantage",
                       "vehicle_financier_stress", "crude_inflation_pressure",
                       "oil_import_bill_currency"],
    },
    "RATE_CHANGE": {
        "event_types": ["repo_rate_change", "global_rates"],
        "keywords": ["repo", "rate", "monetary policy", "rbi", "fed", "basis points"],
        "trigger": "repo_rate_up",
        "up_keywords": ["hike", "raise", "increase", "tighten", "up"],
        "down_keywords": ["cut", "lower", "reduce", "ease", "down"],
        "mechanisms": ["bank_nim_repricing", "nbfc_funding_cost", "housing_demand_rates",
                       "durables_financing_demand", "auto_financing_demand", "corporate_capex_rates"],
    },
    "INFLATION_DATA": {
        "event_types": ["inflation"],
        "keywords": ["inflation", "cpi", "wpi", "price index"],
        "trigger": "inflation_up",
        "up_keywords": ["rise", "accelerat", "high", "increase", "surge", "up"],
        "down_keywords": ["cool", "ease", "fall", "decline", "moderat", "soften", "down", "low"],
        "mechanisms": ["staples_volume_pressure", "discretionary_demand_squeeze",
                       "rate_expectation_shift"],
    },
    "CURRENCY_MOVE": {
        "event_types": ["currency_move"],
        "keywords": ["rupee", "inr", "dollar", "exchange rate", "forex", "depreciat", "appreciat"],
        "trigger": "inr_depreciation",
        "up_keywords": ["depreciat", "weaken", "fall", "low", "slide", "record low"],
        "down_keywords": ["appreciat", "strengthen", "rise", "gain", "recover"],
        "mechanisms": ["it_export_realization", "pharma_export_realization",
                       "textile_export_competitiveness", "import_cost_inflation",
                       "electronics_import_cost"],
    },
    "INFRA_SPENDING": {
        "event_types": ["fiscal_policy"],
        "keywords": ["infrastructure", "capex", "highway", "railway", "budget allocation",
                     "public spending", "capital expenditure"],
        "trigger": "govt_infra_spending_up",
        "up_keywords": ["increase", "boost", "raise", "record", "higher", "push"],
        "down_keywords": ["cut", "reduce", "slash", "lower", "defer"],
        "mechanisms": ["cement_demand_infra", "epc_order_book", "steel_demand_infra",
                       "capital_goods_orders", "infra_logistics_volume"],
    },
    "TRADE_TARIFF": {
        "event_types": ["trade_policy"],
        "keywords": ["tariff", "duty", "import restriction", "anti-dumping", "safeguard", "export ban"],
        "trigger": "import_tariff_up",
        "up_keywords": ["impose", "raise", "hike", "levy", "restrict"],
        "down_keywords": ["remove", "cut", "withdraw", "exempt", "ease"],
        "mechanisms": ["domestic_producer_protection", "downstream_input_cost_tariff"],
    },
    "GEOPOLITICAL_SUPPLY_DISRUPTION": {
        "event_types": ["geopolitical_conflict"],
        "keywords": ["strait", "hormuz", "red sea", "shipping route", "blockade", "supply disruption",
                     "attack", "conflict", "war"],
        "trigger": "supply_route_disruption",
        "up_keywords": [],  # a disruption event is canonical by construction
        "down_keywords": ["de-escalat", "reopen", "ceasefire", "resume"],
        "mechanisms": ["freight_rate_spike", "defense_procurement_sentiment",
                       # crude chain rides along -- a Gulf disruption IS a crude shock
                       "upstream_realization", "refiner_marketing_margin", "aviation_fuel_cost",
                       "petrochemical_feedstock", "road_freight_fuel_cost",
                       "crude_inflation_pressure"],
    },
    "MONSOON_UPDATE": {
        "event_types": ["monsoon_weather"],
        "keywords": ["monsoon", "rainfall", "imd", "sowing", "kharif", "rabi"],
        "trigger": "monsoon_above_normal",
        "up_keywords": ["above normal", "good", "surplus", "adequate", "normal"],
        "down_keywords": ["deficit", "below normal", "weak", "delay", "drought", "scanty"],
        "mechanisms": ["rural_income_agri", "rural_fmcg_demand", "rural_two_wheeler_demand",
                       "agrochemical_volume"],
    },
}

_EFFECT_INVERSE = {"positive": "negative", "negative": "positive",
                   "mixed": "mixed", "uncertain": "uncertain", "neutral": "neutral"}


def _kw_hit(text: str, keyword: str) -> bool:
    """Keyword match with word boundaries for short tokens -- a bare "up"
    must not match inside "support" (measured false positive)."""
    import re

    if len(keyword) <= 4:
        return re.search(rf"\b{re.escape(keyword)}\b", text) is not None
    return keyword in text


def match_event_archetype(facts) -> tuple[str, str] | None:
    """Deterministic archetype match: (archetype_id, direction) where
    direction is 'canonical' or 'inverted' relative to the archetype's
    trigger variable. None when no archetype confidently applies -- the
    dynamic discovery path then runs unchanged (novel events are never
    templated). Matching needs BOTH the event_type gate and at least one
    keyword hit, so a mislabelled event_type alone cannot force a template."""
    text = " ".join([
        getattr(facts, "event", "") or "",
        getattr(facts, "facts", "") or "",
    ]).lower()
    event_type = getattr(facts, "event_type", None)
    for archetype_id, spec in EVENT_ARCHETYPES.items():
        if event_type not in spec["event_types"]:
            continue
        if not any(_kw_hit(text, k) for k in spec["keywords"]):
            continue
        down = any(_kw_hit(text, k) for k in spec["down_keywords"])
        up = any(_kw_hit(text, k) for k in spec["up_keywords"])
        direction = "inverted" if (down and not up) else "canonical"
        return archetype_id, direction
    return None


def oriented_mechanisms(archetype_id: str, direction: str) -> list[dict]:
    """The archetype's mechanism slice with effects oriented to the event's
    actual direction. Each dict gains `mechanism_id` and `oriented_effect`;
    registry entries themselves are never mutated."""
    spec = EVENT_ARCHETYPES[archetype_id]
    result = []
    for mechanism_id in spec["mechanisms"]:
        mech = MECHANISMS.get(mechanism_id)
        if mech is None:
            continue
        effect = mech["effect"]
        if direction == "inverted":
            effect = _EFFECT_INVERSE[effect]
        result.append({**mech, "mechanism_id": mechanism_id, "oriented_effect": effect})
    return result


# --- P3: company exposure registry ----------------------------------------
# Ordinal exposure levels per (archetype, dimension) -- the deterministic
# seed for the company_exposures table. Ordinal ONLY (spec P3): where no
# verified number exists, the honest value is a rank, not a percentage.

EXPOSURE_LEVELS = ["NONE", "LOW", "MEDIUM", "HIGH", "VERY_HIGH", "UNKNOWN"]
_LEVEL_ORDER = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "VERY_HIGH": 4, "UNKNOWN": 1}

# Which exposure DIMENSION each mechanism tests -- the bridge between the
# mechanism registry and per-company exposure rows (P8 priority scoring).
MECHANISM_DIMENSIONS: dict[str, str] = {
    "upstream_realization": "commodity_revenue",
    "refiner_marketing_margin": "crude_linked_inputs",
    "lubricant_base_oil_cost": "crude_linked_inputs",
    "petrochemical_feedstock": "crude_linked_inputs",
    "paints_input_cost": "crude_linked_inputs",
    "tyre_input_cost": "crude_linked_inputs",
    "aviation_fuel_cost": "fuel_cost",
    "road_freight_fuel_cost": "fuel_cost",
    "cement_energy_freight": "fuel_cost",
    "auto_fuel_demand": "consumer_demand",
    "two_wheeler_fuel_demand": "consumer_demand",
    "ev_relative_advantage": "substitution",
    "vehicle_financier_stress": "credit_quality",
    "crude_inflation_pressure": "consumer_demand",
    "oil_import_bill_currency": "commodity_input",
    "bank_nim_repricing": "financing",
    "nbfc_funding_cost": "financing",
    "housing_demand_rates": "housing_demand",
    "durables_financing_demand": "consumer_demand",
    "auto_financing_demand": "consumer_demand",
    "corporate_capex_rates": "capex_cycle",
    "staples_volume_pressure": "consumer_demand",
    "discretionary_demand_squeeze": "consumer_demand",
    "rate_expectation_shift": "financing",
    "it_export_realization": "fx",
    "pharma_export_realization": "fx",
    "textile_export_competitiveness": "fx",
    "import_cost_inflation": "fx",
    "electronics_import_cost": "fx",
    "cement_demand_infra": "govt_spending",
    "epc_order_book": "govt_spending",
    "steel_demand_infra": "govt_spending",
    "capital_goods_orders": "govt_spending",
    "infra_logistics_volume": "govt_spending",
    "domestic_producer_protection": "trade_policy",
    "downstream_input_cost_tariff": "trade_policy",
    "freight_rate_spike": "trade_flows",
    "defense_procurement_sentiment": "govt_spending",
    "rural_income_agri": "rural_demand",
    "rural_fmcg_demand": "rural_demand",
    "rural_two_wheeler_demand": "rural_demand",
    "agrochemical_volume": "rural_demand",
}

# Archetype -> {dimension: ordinal level}. Derived from what membership in
# the archetype STRUCTURALLY implies (an airline is HIGH fuel_cost by
# construction) -- never company-specific claims.
ARCHETYPE_EXPOSURES: dict[str, dict[str, str]] = {
    "upstream_oil_producer": {"commodity_revenue": "VERY_HIGH", "fx": "MEDIUM"},
    "oil_refiner_marketer": {"crude_linked_inputs": "VERY_HIGH", "fx": "HIGH",
                             "commodity_input": "VERY_HIGH"},
    "gas_distributor": {"commodity_input": "HIGH", "fx": "MEDIUM"},
    "lubricant_producer": {"crude_linked_inputs": "HIGH", "consumer_demand": "LOW"},
    "petrochemical_producer": {"crude_linked_inputs": "VERY_HIGH", "fx": "MEDIUM"},
    "specialty_chemical_producer": {"crude_linked_inputs": "HIGH", "fx": "HIGH"},
    "commodity_chemical_producer": {"crude_linked_inputs": "HIGH", "fx": "MEDIUM"},
    "paint_producer": {"crude_linked_inputs": "HIGH", "consumer_demand": "MEDIUM",
                       "housing_demand": "MEDIUM"},
    "tyre_producer": {"crude_linked_inputs": "HIGH", "consumer_demand": "MEDIUM"},
    "airline": {"fuel_cost": "VERY_HIGH", "consumer_demand": "HIGH", "fx": "MEDIUM"},
    "logistics_operator": {"fuel_cost": "HIGH", "trade_flows": "HIGH",
                           "govt_spending": "LOW"},
    "shipping_port_operator": {"trade_flows": "VERY_HIGH", "fuel_cost": "HIGH"},
    "cement_producer": {"fuel_cost": "HIGH", "govt_spending": "HIGH",
                        "housing_demand": "MEDIUM"},
    "power_utility": {"commodity_input": "HIGH", "govt_spending": "MEDIUM"},
    "construction_epc": {"govt_spending": "VERY_HIGH", "financing": "HIGH",
                         "capex_cycle": "HIGH"},
    "capital_goods_manufacturer": {"capex_cycle": "VERY_HIGH", "govt_spending": "HIGH",
                                   "trade_policy": "MEDIUM"},
    "steel_producer": {"govt_spending": "HIGH", "trade_policy": "HIGH",
                       "commodity_revenue": "HIGH", "fuel_cost": "MEDIUM"},
    "non_ferrous_producer": {"commodity_revenue": "HIGH", "fx": "HIGH", "trade_policy": "MEDIUM"},
    "metals_producer": {"commodity_revenue": "HIGH", "trade_policy": "MEDIUM"},
    "auto_manufacturer": {"consumer_demand": "HIGH", "crude_linked_inputs": "MEDIUM",
                          "financing": "MEDIUM", "rural_demand": "MEDIUM"},
    "two_wheeler_manufacturer": {"consumer_demand": "HIGH", "rural_demand": "HIGH",
                                 "fuel_cost": "MEDIUM"},
    "auto_component_maker": {"capex_cycle": "MEDIUM", "consumer_demand": "MEDIUM",
                             "fx": "MEDIUM", "crude_linked_inputs": "MEDIUM"},
    "ev_manufacturer": {"substitution": "HIGH", "consumer_demand": "HIGH",
                        "govt_spending": "MEDIUM"},
    "bank": {"financing": "VERY_HIGH", "credit_quality": "HIGH", "housing_demand": "MEDIUM"},
    "nbfc": {"financing": "VERY_HIGH", "credit_quality": "VERY_HIGH",
             "consumer_demand": "MEDIUM"},
    "insurer": {"financing": "HIGH"},
    "asset_manager": {"financing": "MEDIUM", "consumer_demand": "MEDIUM"},
    "real_estate_developer": {"housing_demand": "VERY_HIGH", "financing": "HIGH",
                              "govt_spending": "LOW"},
    "fmcg_consumer_staples": {"consumer_demand": "HIGH", "rural_demand": "HIGH",
                              "crude_linked_inputs": "MEDIUM"},
    "retailer": {"consumer_demand": "VERY_HIGH", "rural_demand": "MEDIUM"},
    "consumer_discretionary": {"consumer_demand": "VERY_HIGH", "financing": "MEDIUM"},
    "appliance_maker": {"consumer_demand": "HIGH", "fx": "MEDIUM", "trade_policy": "MEDIUM"},
    "it_services": {"fx": "VERY_HIGH", "capex_cycle": "MEDIUM"},
    "pharma_manufacturer": {"fx": "HIGH", "trade_policy": "MEDIUM"},
    "hospital_operator": {"consumer_demand": "MEDIUM"},
    "telecom_operator": {"financing": "HIGH", "consumer_demand": "MEDIUM"},
    "textile_manufacturer": {"fx": "HIGH", "trade_policy": "HIGH", "rural_demand": "LOW",
                             "consumer_demand": "MEDIUM"},
    "agri_producer": {"rural_demand": "VERY_HIGH", "trade_policy": "MEDIUM"},
    "fertilizer_agrochemical": {"rural_demand": "VERY_HIGH", "govt_spending": "HIGH",
                                "commodity_input": "MEDIUM"},
    "defense_manufacturer": {"govt_spending": "VERY_HIGH"},
    "media_broadcaster": {"consumer_demand": "HIGH"},
}


def seed_company_exposures(session: Session, per_archetype_limit: int = 300) -> int:
    """Materialize archetype-implied exposures into company_exposures
    (source='archetype:<version>'). Idempotent; keeps the HIGHEST level
    when a company matches several archetypes; never overwrites manual
    rows. Returns rows written/updated."""
    from app.models import CompanyExposure, utcnow

    desired: dict[tuple[int, str], str] = {}
    for archetype_id, dims in ARCHETYPE_EXPOSURES.items():
        for company in companies_for_archetype(session, archetype_id, limit=per_archetype_limit):
            for dimension, level in dims.items():
                key = (company.id, dimension)
                held = desired.get(key)
                if held is None or _LEVEL_ORDER[level] > _LEVEL_ORDER[held]:
                    desired[key] = level

    written = 0
    existing = {(r.company_id, r.dimension): r for r in session.query(CompanyExposure).all()}
    source = f"archetype:{KNOWLEDGE_REGISTRY_VERSION}"
    for (company_id, dimension), level in desired.items():
        row = existing.get((company_id, dimension))
        if row is None:
            session.add(CompanyExposure(company_id=company_id, dimension=dimension,
                                        level=level, source=source,
                                        version=KNOWLEDGE_REGISTRY_VERSION))
            written += 1
        elif row.source != "manual" and (row.level != level or row.version != KNOWLEDGE_REGISTRY_VERSION):
            row.level, row.source, row.version = level, source, KNOWLEDGE_REGISTRY_VERSION
            row.updated_at = utcnow()
            written += 1
    session.commit()
    return written


def exposure_levels_for(session: Session, company_ids: list[int]) -> dict[tuple[int, str], str]:
    """Bulk (company_id, dimension) -> level lookup for priority scoring."""
    from app.models import CompanyExposure

    if not company_ids:
        return {}
    rows = (session.query(CompanyExposure)
            .filter(CompanyExposure.company_id.in_(company_ids)).all())
    return {(r.company_id, r.dimension): r.level for r in rows}


def level_rank(level: str | None) -> int:
    return _LEVEL_ORDER.get(level or "UNKNOWN", 1)


def companies_for_archetype(session: Session, archetype_id: str, limit: int = 40) -> list[Company]:
    """Deterministic archetype -> candidate companies (P7). Same
    tradeability rails as every other candidate pool; ordered by market cap
    so the visible slice is the prominent names."""
    spec = EXPOSURE_ARCHETYPES.get(archetype_id)
    if spec is None:
        return []
    query = (
        session.query(Company)
        .filter(Company.ticker.notin_(DEMO_TICKERS))
        .filter(Company.market == "INDIA")
        .filter(Company.tradeability == "NORMAL")
    )
    if spec.get("sector"):
        query = query.filter(Company.sector == spec["sector"])
    clauses = []
    if spec.get("sub_sectors"):
        clauses.append(Company.sub_sector.in_(spec["sub_sectors"]))
    for keyword in spec.get("desc_keywords", []):
        clauses.append(Company.business_desc.ilike(f"%{keyword}%"))
    if clauses:
        query = query.filter(or_(*clauses))
    return (query.order_by(Company.market_cap.desc().nullslast(), Company.ticker.asc())
            .limit(limit).all())
