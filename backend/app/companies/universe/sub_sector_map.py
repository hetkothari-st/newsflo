"""BSE ISubGroup -> the app's closed sub-sector vocabulary.

190 distinct ISubGroup values appear across the 4,684 companies BSE classifies.
This maps the ones that correspond to a value in
app.companies.sub_sectors.SUB_SECTOR_TAXONOMY; anything absent resolves to None
rather than being forced into the nearest bucket.

Keyed on ISubGroup alone. The company's sector is derived separately from
official_sector/official_industry (app.companies.universe.sector_map), and
map_sub_sector VALIDATES the pair -- duplicating the sector into every key
would let the two drift apart.

Several entries below target a different sub-sector than the naive
sector-implied-by-ISubGroup-name would suggest. Each such case was checked
against the real 4,684-company snapshot (Sector/IndustryNew actually returned
by BSE for that ISubGroup) rather than assumed, because BSE's own
classification sometimes splits an ISubGroup across an unexpected sector
(e.g. paint makers are classified as Consumer Durables, not Chemicals; heavy
commercial/tractor/construction-vehicle makers as Capital Goods, not
Automobile and Auto Components). Mapping to the sub_sector implied by the
ISubGroup's *name* in those cases would validate against the wrong sector and
silently return None for the real companies. See inline comments.

Three sectors in SUB_SECTOR_TAXONOMY -- "defense", "agriculture", and
"railways_transport" -- are not reachable from real production data at all:
map_sector's OFFICIAL_SECTOR_TO_BUCKET has no key matching any Sector/
IndustryNew value BSE actually emits for a defense, agriculture, or transport
company (defense and heavy-transport manufacturers carry IndustryNew
"Capital Goods"; fertilizer/agrochemical makers carry IndustryNew
"Chemicals"; most transport operators carry the generic Sector "Services",
which resolves to "other"). This was already found for "defense" in this
plan's Task 1 (app/companies/universe/sector_map.py); the same root cause
also makes "agriculture" and "railways_transport" unreachable. That module is
out of this task's scope, so ISubGroups whose real population lands on
"other" (airline, port & port services, shipping, logistics solution
provider, road transport, transport related services, jute & jute products,
road assets-toll/annuity/hybrid-annuity, dredging, data processing services)
are left mapped to their semantically-correct-but-currently-unreachable
target -- that mapping is not wrong, it just cannot fire until sector_map
gains a real bucket for them. ISubGroups whose real population instead lands
on a *different, reachable* sector (aerospace & defense, ship building,
explosives, fertilizers, pesticides & agrochemicals, railway wagons, food
storage facilities) are targeted at that real sector's bucket instead, so the
companies resolve today.

Pure data plus one function: no I/O, no DB, no app.models import.
"""
from app.companies.sub_sectors import SUB_SECTOR_TAXONOMY

ISUBGROUP_TO_SUB_SECTOR = {
    # --- oil_gas ---
    "oil exploration & production": "upstream_exploration",
    "refineries & marketing": "refining_marketing",
    "lpg/cng/png/lng supplier": "gas_distribution",
    "gas transmission/marketing": "gas_distribution",
    "trading - gas": "gas_distribution",
    "oil storage & transportation": "oil_gas_other",
    "oil equipment & services": "oil_gas_other",
    "offshore support solution drilling": "oil_gas_other",
    "lubricants": "oil_gas_other",
    # Real data: Coal India, FFPL, Bharat Coal et al. all carry official
    # Sector "Energy" / IndustryNew "Oil, Gas & Consumable Fuels" -> sector
    # oil_gas, not "Metals & Mining" -> metals. "mining_coal" (in the metals
    # taxonomy) would silently drop every coal company; oil_gas_other is
    # what their real sector supports.
    "coal": "oil_gas_other",
    "trading coal": "oil_gas_other",
    # --- banking ---
    "private sector bank": "private_bank",
    "public sector bank": "psu_bank",
    "other bank": "banking_other",
    "non banking financial company (nbfc)": "nbfc",
    "microfinance institutions": "nbfc",
    "housing finance company": "housing_finance",
    "life insurance": "insurance",
    "general insurance": "insurance",
    "insurance distributors": "insurance",
    "asset management company": "asset_management",
    "investment company": "banking_other",
    "holding company": "banking_other",
    "other financial services": "banking_other",
    "stockbroking & allied": "banking_other",
    "financial institution": "banking_other",
    "financial technology (fintech)": "banking_other",
    "financial products distributor": "banking_other",
    "other capital market related services": "banking_other",
    "depositories, clearing houses and other intermediaries": "banking_other",
    "ratings": "banking_other",
    "exchange and data platform": "banking_other",
    # --- auto ---
    "passenger cars & utility vehicles": "passenger_vehicle",
    "2/3 wheelers": "two_wheeler",
    "auto components & equipments": "auto_component",
    "tyres & rubber products": "auto_component",
    "trading - auto components": "auto_component",
    "auto -dealer": "auto_other",
    # --- it (see IT_SERVICES_ISUBGROUPS below for the cap-dependent cases) ---
    "software products": "product_saas",
    "computers hardware & equipments": "it_other",
    "data processing services": "it_other",  # real data: sector "other" (see module docstring)
    # --- pharma ---
    "pharmaceuticals": "generics_formulations",
    "biotechnology": "specialty_pharma",
    "hospital": "hospital_diagnostics",
    "healthcare service provider": "hospital_diagnostics",
    # Real data: Syngene, Suven, Vimta Labs -- genuine CRO/CDMO businesses,
    # not analytics-only firms. api_cdmo fits.
    "healthcare research, analytics & technology": "api_cdmo",
    "medical equipment & supplies": "pharma_other",
    # --- fmcg ---
    "packaged foods": "staples_food",
    "other food products": "staples_food",
    "edible oil": "staples_food",
    "sugar": "staples_food",
    "dairy products": "staples_food",
    "seafood": "staples_food",
    "meat products including poultry": "staples_food",
    "other agricultural products": "staples_food",
    "tea & coffee": "beverages",
    "breweries & distilleries": "beverages",
    "other beverages": "beverages",
    "personal care": "personal_care",
    "household products": "personal_care",
    "diversified fmcg": "fmcg_other",
    "cigarettes & tobacco products": "fmcg_other",
    "animal feed": "fmcg_other",
    "speciality retail": "retail",
    "diversified retail": "retail",
    "e-retail/ e-commerce": "retail",
    "internet & catalogue retail": "retail",
    "distributors": "retail",
    # Real data: sector fmcg (IndustryNew "Consumer Services"), not pharma.
    # "retail" fits a pharmacy chain better than pharma_other, and matches
    # the other retail-chain ISubGroups above.
    "pharmacy retail": "retail",
    # Real data: sector fmcg (IndustryNew "Consumer Services"), not pharma.
    # No wellness-specific fmcg bucket exists; fmcg_other is the honest
    # catch-all.
    "wellness": "fmcg_other",
    # Real data: sector fmcg (IndustryNew "Consumer Services"), not
    # railways_transport (which is unreachable -- see module docstring).
    "food storage facilities": "fmcg_other",
    # Real data: sector fmcg (IndustryNew "Fast Moving Consumer Goods"), not
    # consumer_durables.
    "stationary": "fmcg_other",
    # --- metals ---
    "iron & steel": "steel",
    "sponge iron": "steel",
    "pig iron": "steel",
    "ferro & silica manganese": "steel",
    "aluminium": "non_ferrous",
    "copper": "non_ferrous",
    "zinc": "non_ferrous",
    "precious metals": "non_ferrous",
    "diversified metals": "metals_other",
    # Real data: NMDC (iron ore), MOIL (manganese), GMDC (lignite), 20 Micron
    # etc. -- a mixed-mineral bucket, not coal specifically. metals_other is
    # the honest catch-all; mining_coal would misstate the commodity (and
    # real coal companies carry a different ISubGroup -- see "coal" above,
    # which resolves under oil_gas instead).
    "industrial minerals": "metals_other",
    "trading - minerals": "metals_other",
    "trading - metals": "metals_other",
    # --- telecom ---
    "telecom - cellular & fixed line services": "telecom_operator",
    "telecom - infrastructure": "telecom_infrastructure",
    "telecom -  equipment & accessories": "telecom_infrastructure",
    "other telecom services": "telecom_other",
    # --- infra ---
    "civil construction": "construction_engineering",
    "road assets–toll, annuity, hybrid-annuity": "construction_engineering",  # real data: sector "other" (see module docstring)
    "dredging": "construction_engineering",  # real data: sector "other" (see module docstring)
    "power generation": "power_utilities",
    "integrated power utilities": "power_utilities",
    "power distribution": "power_utilities",
    "power trading": "power_utilities",
    "power - transmission": "power_utilities",
    "water supply & management": "power_utilities",
    "multi utilities": "power_utilities",
    "other utilities": "power_utilities",
    "heavy electrical equipment": "capital_goods",
    "other electrical equipment": "capital_goods",
    "industrial products": "capital_goods",
    "other industrial products": "capital_goods",
    "compressors, pumps & diesel engines": "capital_goods",
    "castings & forgings": "capital_goods",
    "abrasives & bearings": "capital_goods",
    "electrodes & refractories": "capital_goods",
    "cables - electricals": "capital_goods",
    "glass - industrial": "capital_goods",
    # Real data: NOL, Linde India, Gagan, et al. all carry IndustryNew
    # "Chemicals" -> sector chemicals, not infra. Moved to the chemicals
    # section below (commodity_chemicals).
    # Real data: BEML, TIL, ACE, Ashok Leyland, SML Isuzu, Atul Auto,
    # Escorts, VST Tillers, JKIPL, Seemax -- all carry official IndustryNew
    # "Capital Goods" (Sector "Industrials"), not "Automobile and Auto
    # Components" -> sector infra, not auto. "commercial_vehicle"/
    # "auto_other" (the brief's original targets, in the auto sector) would
    # silently drop all of them, including Ashok Leyland and Escorts.
    "commercial vehicles": "capital_goods",
    "construction vehicles": "capital_goods",
    "tractors": "capital_goods",
    "dealers-commercial vehicles, tractors, construction vehicles": "capital_goods",
    # Real data: BEL, HAL, BDL, MIDHANI, GRSE, Data Patterns et al. all carry
    # official IndustryNew "Capital Goods" (Sector "Industrials") -- BSE's
    # vocabulary has no "defense" value at all, so map_sector can never
    # produce sector "defense" (see module docstring). Targeting the
    # defense_* values here would make these 29 companies -- the
    # highest-volume miss in this whole file -- permanently unresolvable.
    # capital_goods is what BSE's own classification actually says and what
    # sector resolves to for all of them; it is not a guess.
    "aerospace & defense": "capital_goods",
    # Real data: Cochin Shipyard, Mazagon Dock, GRSE -- also IndustryNew
    # "Capital Goods" -> sector infra, not "defense". Same reasoning as
    # aerospace & defense above.
    "ship building & allied services": "capital_goods",
    # Real data: sector infra (IndustryNew "Capital Goods"), not
    # railways_transport (which is unreachable -- see module docstring).
    "railway wagons": "capital_goods",
    # Real data: sector infra (IndustryNew "Capital Goods"), not metals.
    # "steel"/"non_ferrous" (the brief's original targets, in the metals
    # sector) would silently drop every one of these -- BSE evidently treats
    # fabricated/downstream metal products as capital goods, distinct from
    # the raw-metal ISubGroups above which do carry sector metals.
    "iron & steel products": "capital_goods",
    "aluminium, copper & zinc products": "capital_goods",
    # Real data: sector infra (IndustryNew "Capital Goods"), not textiles.
    # No rubber-specific infra bucket exists; capital_goods is the closest
    # real fit (industrial rubber goods manufacturing).
    "rubber": "capital_goods",
    "cement & cement products": "cement",
    "other construction materials": "cement",
    "packaging": "infra_other",
    "plastic products - industrial": "infra_other",
    "waste management": "infra_other",
    # --- railways_transport (unreachable from real data -- see module
    # docstring; these ISubGroups' real population resolves to sector
    # "other" and cannot validate here today, but the mapping itself is the
    # semantically-correct target if sector_map ever gains a real bucket) ---
    "airline": "aviation",
    "airport & airport services": "aviation",
    "port & port services": "ports_shipping",
    "shipping": "ports_shipping",
    "logistics solution provider": "logistics_roadways",
    "road transport": "logistics_roadways",
    "transport related services": "logistics_roadways",
    # --- construction_realestate ---
    "residential, commercial projects": "residential_developer",
    "real estate related services": "construction_realestate_other",
    # --- agriculture (unreachable from real data -- see module docstring) ---
    # Real data: sector chemicals (IndustryNew "Chemicals") for every
    # fertilizer and pesticide/agrochemical company in the snapshot, not
    # agriculture. "fertilizers"/"agrochemicals" (the brief's original
    # targets, in the unreachable agriculture sector) would permanently drop
    # all 50 of them; chemicals_other is the honest catch-all for their real
    # sector (no fertilizer/agrochemical-specific chemicals bucket exists).
    "fertilizers": "chemicals_other",
    "pesticides & agrochemicals": "chemicals_other",
    # --- consumer_durables ---
    "household appliances": "appliances_electronics",
    "consumer electronics": "appliances_electronics",
    # Real data: sector consumer_durables (IndustryNew "Consumer Durables"),
    # not auto. Only 1 company (Atlas Cycle) but the same real-vs-assumed
    # sector mismatch as the vehicle ISubGroups above.
    "cycles": "consumer_durables_other",
    # Real data: all under IndustryNew "Consumer Durables" -- not appliances
    # or electronics, but there is no furniture-specific bucket in this
    # sector's list. consumer_durables_other is the honest catch-all (same
    # treatment as leisure products / houseware below), not a forced fit
    # into appliances_electronics.
    "furniture, home furnishing": "consumer_durables_other",
    # Real data: 2 companies, IndustryNew "Consumer Durables" -> sector
    # consumer_durables, not infra. "infra_other" (the brief's original
    # target) requires sector infra and would silently drop both.
    "sanitary ware": "consumer_durables_other",
    "leisure products": "consumer_durables_other",
    # Real data: 10 companies (Kajaria-style tile makers etc.), all
    # IndustryNew "Consumer Durables" -> sector consumer_durables, not infra.
    # "cement" requires sector infra and would silently drop every one of
    # them; consumer_durables_other is what their real sector supports.
    "ceramics": "consumer_durables_other",
    "glass - consumer": "consumer_durables_other",
    "plastic products - consumer": "consumer_durables_other",
    "diversified consumer products": "consumer_durables_other",
    # Real data: same population as ceramics above -- IndustryNew "Consumer
    # Durables", not "Construction Materials"/infra. See ceramics comment.
    "granites & marbles": "consumer_durables_other",
    # Real data: sector consumer_durables (IndustryNew "Consumer Durables"),
    # not fmcg. Houseware (cookware/plasticware) has no specific bucket here;
    # consumer_durables_other is the honest catch-all.
    "houseware": "consumer_durables_other",
    # Real data: sector consumer_durables (IndustryNew "Consumer Durables")
    # for every plywood/laminate maker in the snapshot (e.g. Century Ply-
    # style companies), not infra.
    "plywood boards/ laminates": "consumer_durables_other",
    # Not in the brief's table at all, but the highest-volume gap found in
    # the real snapshot (86 companies, incl. Titan, Kalyan Jewellers): sector
    # consumer_durables (IndustryNew "Consumer Durables", the same specific,
    # finer-level match as ceramics/granites/paints/footwear above, not the
    # coarse Consumer-Services-to-fmcg fallback). Same treatment: no
    # jewellery-specific bucket exists, so consumer_durables_other.
    "gems, jewellery and watches": "consumer_durables_other",
    # Real data: Asian Paints, Berger Paints et al. all carry IndustryNew
    # "Consumer Durables", not "Chemicals" -> sector consumer_durables, not
    # chemicals. "paints" (in the chemicals taxonomy) would silently drop
    # every paint company; consumer_durables_other is the honest catch-all
    # since consumer_durables has no paint-specific bucket.
    "paints": "consumer_durables_other",
    # Real data: Bata-style footwear/leather companies all carry IndustryNew
    # "Consumer Durables", not "Textiles" -> sector consumer_durables, not
    # textiles. "apparel_garments" (in the textiles taxonomy) would silently
    # drop every one of them; consumer_durables_other is the honest
    # catch-all since consumer_durables has no footwear/leather bucket.
    "footwear": "consumer_durables_other",
    "leather and leather products": "consumer_durables_other",
    # --- media_entertainment ---
    "tv broadcasting & software production": "broadcast_tv",
    "electronic media": "broadcast_tv",
    "film production, distribution & exhibition": "multiplex_film",
    "digital entertainment": "digital_gaming",
    "web based media and service": "digital_gaming",
    "print media": "media_entertainment_other",
    "printing & publication": "media_entertainment_other",
    "advertising & media agencies": "media_entertainment_other",
    "media & entertainment": "media_entertainment_other",
    # --- chemicals ---
    "specialty chemicals": "specialty_chemicals",
    "dyes and pigments": "specialty_chemicals",
    "printing inks": "specialty_chemicals",
    "commodity chemicals": "commodity_chemicals",
    "petrochemicals": "commodity_chemicals",
    "carbon black": "commodity_chemicals",
    "trading - chemicals": "commodity_chemicals",
    # Real data: NOL, Linde India, Gagan et al. all carry IndustryNew
    # "Chemicals" -> sector chemicals, not infra (the brief's original
    # "capital_goods" target). Bulk industrial gas production is closer to
    # commodity chemical manufacturing than a paints/specialty distinction.
    "industrial gases": "commodity_chemicals",
    # Real data: Solar Industries, GOCL, Premier Explosives -- all official
    # Sector "Commodities" / IndustryNew "Chemicals" -> sector chemicals, not
    # "defense" (which map_sector cannot produce -- see module docstring).
    # chemicals_other is the honest catch-all for their actual sector.
    "explosives": "chemicals_other",
    # --- textiles ---
    "garments & apparels": "apparel_garments",
    "other textile products": "yarn_fabric",
    "trading - textile products": "yarn_fabric",
    # real data: sector "other" (see module docstring)
    "jute & jute products": "yarn_fabric",
    # No ISubGroup in the real snapshot lands on textiles_other -- rubber
    # (previously mapped here) turned out to be sector infra, not textiles
    # (see the infra section above). textiles_other stays in the taxonomy as
    # the sector's required escape value even though nothing currently
    # targets it.
}

# IT services cannot be split large-cap vs mid/small-cap from the industry
# taxonomy -- that distinction is about company size, which BSE does not
# encode. These resolve via the caller's cap tier; see map_sub_sector.
IT_SERVICES_ISUBGROUPS = {
    "computers - software & consulting",
    "it enabled services",
    "business process outsourcing (bpo)/ knowledge process outsourcing (kpo)",
}

_VALID = {sector: set(values) for sector, values in SUB_SECTOR_TAXONOMY.items()}


def map_sub_sector(isubgroup: str | None, sector: str, cap_tier: str | None = None) -> str | None:
    """Derive a sub_sector, or None.

    Returns None when the ISubGroup is unmapped, or when the mapped value does
    not belong to ``sector``'s list. The sector is itself sourced, so a
    contradiction means the mapping is wrong for this company -- reporting
    nothing beats reporting a sub_sector from a different industry.
    """
    if not isubgroup:
        return None
    key = isubgroup.strip().lower()

    if key in IT_SERVICES_ISUBGROUPS:
        # The vocabulary splits IT services by company SIZE, which BSE does
        # not encode. At ingest time cap tier is unknown -- it is a rank over
        # the whole population, computed later -- so asserting either bucket
        # would mislabel someone: "mid/small" is wrong for TCS, "large" is
        # wrong for the other ~240. it_other says what we actually know (it is
        # IT services) without claiming a size we cannot derive. A caller that
        # does know the tier gets the precise answer.
        if cap_tier == "LARGE":
            candidate = "it_services_large_cap"
        elif cap_tier in ("MID", "SMALL", "MICRO"):
            candidate = "it_services_mid_small_cap"
        else:
            candidate = "it_other"
    else:
        candidate = ISUBGROUP_TO_SUB_SECTOR.get(key)

    if candidate is None:
        return None
    return candidate if candidate in _VALID.get(sector, ()) else None
