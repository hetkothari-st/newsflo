"""STEP 3 - write one finding.json per roster company.

A finding either states the component values read off a cited page, or states
why the company could not be sourced. It never states a share: build_csv.py
computes that from the components, so no share can enter this pipeline as a
number somebody chose.

Every figure below was transcribed from the page named in its finding and is
re-checked against that page's text by build_csv.py before any row is
written. Nothing here comes from prior knowledge of the company.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FILINGS = REPO / "data" / "filings"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from roster import ROSTER, FAMILY_ORDER  # noqa: E402

# ------------------------------------------------- LEDGER-IMPORT METADATA
# Everything a ledger row needs that is a property of the DOCUMENT rather
# than of the ratio. Keyed by ISIN because it is the same for every channel
# read off the same statement.
#
# `unit` is the unit the FILING states on the cited page and was read off
# that page, never inferred from the magnitude of the number:
#   CEAT p119 "₹ in lakhs" · Savita p231 "` in Lakhs" · VRL p210/p171
#   "₹ lakhs" · Delhivery p145 "(All amounts in Indian Rupees in millions)" ·
#   Mahindra Logistics p127 "` Crores" · Blue Dart p200/p178 "` Lakhs" ·
#   TCI p188 "C in Mn" (p157 "B in Mn") · TCI Express p286 "₹ in Crores" ·
#   CONCOR p237 "(in Indian Rupees crore)".
# Getting this wrong by one order of magnitude would put a wrong
# base_value_inr in the ledger, so it is transcribed, not guessed.
UNIT_MULTIPLIER = {"LAKH": 1e5, "CRORE": 1e7, "MILLION": 1e6}

LEDGER_META = {
    # isin: (unit, fiscal year end of the cited column, markers)
    "INE482A01020": ("LAKH",    "2026-03-31", ("FLOOR",)),      # CEAT
    "INE035D01020": ("LAKH",    "2026-03-31", ()),              # Savita Oil
    "INE366I01010": ("LAKH",    "2026-03-31", ()),              # VRL
    "INE148O01028": ("MILLION", "2025-03-31", ()),              # Delhivery
    "INE766P01016": ("CRORE",   "2026-03-31", ("UPPER_BOUND",)),  # Mahindra Log
    "INE233B01017": ("LAKH",    "2025-03-31", ("FLOOR",)),      # Blue Dart
    "INE688A01022": ("MILLION", "2026-03-31", ()),              # TCI
    "INE586V01016": ("CRORE",   "2026-03-31", ()),              # TCI Express
    "INE111A01025": ("CRORE",   "2025-03-31", ()),              # CONCOR
}

# Every row this run produces is an INPUT_COST exposure. Stated once rather
# than repeated eleven times, and asserted at write time.
EXPOSURE_KIND = "INPUT_COST"

# ---------------------------------------------------------------- SOURCED

SOURCED = [
  # ---- TYRES -----------------------------------------------------------
  dict(
    isin="INE482A01020", family="tyres",              # CEAT
    exposure_tag="input:crude_derivative_rubber", base_kind="COGS",
    source_page="119",
    verbatim_excerpt=(
      "Details of raw materials consumed (₹ in lakhs) Particulars 2025-26 "
      "2024-25 Rubber 4,91,060 3,94,454 Fabrics 75,633 61,717 Carbon black "
      "1,43,495 1,32,291 Chemicals 66,050 53,404 Others 1,43,474 1,90,017 "
      "Total 9,19,712 8,31,883"),
    numerator=[dict(label="Carbon black", value="1,43,495"),
               dict(label="Chemicals", value="66,050")],
    denominator=dict(label="Total raw materials consumed", value="9,19,712"),
    computed_from=(
      "Standalone note 29 'Details of raw materials consumed', FY2025-26 "
      "column, Rs in lakhs. Numerator = Carbon black 1,43,495 + Chemicals "
      "66,050 (rubber chemicals). LOWER BOUND: the 'Rubber' line (4,91,060, "
      "53% of the base) merges natural rubber, which is not crude-linked, "
      "with synthetic rubber, which is, and the filing does not split them; "
      "'Others' (1,43,474) is unnamed. Both are therefore excluded rather "
      "than apportioned. Fabrics is carried as a separate petchem row."),
  ),
  dict(
    isin="INE482A01020", family="tyres",              # CEAT, second channel
    exposure_tag="input:crude_derivative_petchem", base_kind="COGS",
    source_page="119",
    verbatim_excerpt=(
      "Details of raw materials consumed (₹ in lakhs) Particulars 2025-26 "
      "2024-25 Rubber 4,91,060 3,94,454 Fabrics 75,633 61,717 Carbon black "
      "1,43,495 1,32,291 Chemicals 66,050 53,404 Others 1,43,474 1,90,017 "
      "Total 9,19,712 8,31,883"),
    numerator=[dict(label="Fabrics", value="75,633")],
    denominator=dict(label="Total raw materials consumed", value="9,19,712"),
    computed_from=(
      "Standalone note 29, FY2025-26 column, Rs in lakhs. Tyre 'Fabrics' is "
      "nylon/polyester tyre cord, a polymer rather than a rubber input, so "
      "it is tagged petchem and kept separate from the carbon-black + "
      "chemicals row rather than summed into one tag."),
  ),

  # ---- LUBRICANTS ------------------------------------------------------
  dict(
    isin="INE035D01020", family="lubricants",         # Savita Oil
    exposure_tag="input:base_oil", base_kind="COGS",
    source_page="231",
    verbatim_excerpt=(
      "18 C OST OF MATERIALS CONSUMED ` in Lakhs Particulars 2025-2026 "
      "2024-2025 Base oils 307,960.79 272,685.09 Process chemicals / "
      "solvents / Waxes 25,375.64 22,648.90 Packing materials 18,213.01 "
      "16,396.52 Others 6,192.16 4,260.85 357,741.60 315,991.36"),
    numerator=[dict(label="Base oils", value="307,960.79")],
    denominator=dict(label="Total cost of materials consumed",
                     value="357,741.60"),
    computed_from=(
      "Consolidated note 18, FY2025-26 column, Rs in lakhs. The single "
      "cleanest disclosure in this run: the material type IS the line item. "
      "Packing materials (18,213.01) and Others (6,192.16) excluded. "
      "VOCABULARY GAP: 'input:base_oil' is NOT a leaf in "
      "config/exposure_tags.yaml and the DB triggers will reject it - the "
      "vocabulary must gain the leaf before this row can be imported."),
  ),
  dict(
    isin="INE035D01020", family="lubricants",         # Savita Oil, 2nd
    exposure_tag="input:crude_derivative_petchem", base_kind="COGS",
    source_page="231",
    verbatim_excerpt=(
      "18 C OST OF MATERIALS CONSUMED ` in Lakhs Particulars 2025-2026 "
      "2024-2025 Base oils 307,960.79 272,685.09 Process chemicals / "
      "solvents / Waxes 25,375.64 22,648.90 Packing materials 18,213.01 "
      "16,396.52 Others 6,192.16 4,260.85 357,741.60 315,991.36"),
    numerator=[dict(label="Process chemicals / solvents / Waxes",
                    value="25,375.64")],
    denominator=dict(label="Total cost of materials consumed",
                     value="357,741.60"),
    computed_from=(
      "Consolidated note 18, FY2025-26 column. Solvents and waxes are named "
      "crude derivatives in the shock definition; 'process chemicals' is "
      "bundled with them by the filing and cannot be separated, so the row "
      "is slightly wider than a pure solvent exposure."),
  ),

  # ---- LOGISTICS (base_kind TOTAL_COST, owner ruling 2026-08-17) -------
  dict(
    isin="INE366I01010", family="logistics",          # VRL - fleet-owning
    exposure_tag="input:freight_diesel", base_kind="TOTAL_COST",
    source_page="210",
    verbatim_excerpt=(
      "Freight, handling and servicing cost Year ended Year ended 31 March "
      "2026 31 March 2025 Lorry hire 15,571 17,662 Diesel cost 80,821 "
      "87,055 Vehicle running, repairs and maintenance (net) 17,376 15,592"),
    numerator=[dict(label="Diesel cost", value="80,821")],
    denominator=dict(label="Total expenses", value="292,690", page="171",),
    denominator_excerpt=(
      "Employee benefits expense 23 58,739 54,517 Finance costs 24 9,498 "
      "9,483 Depreciation and amortisation expense 25 26,103 25,363 Other "
      "expenses 26 6,102 4,345 Total expenses 292,690 293,522"),
    computed_from=(
      "FLEET-OWNING (direct diesel). Standalone note 22, Rs in lakhs. "
      "Numerator is the company's own 'Diesel cost' line - a fuel purchase, "
      "not bought-in freight. Denominator is total expenses from the "
      "standalone P&L (p171). Excluded from the numerator though also "
      "crude-linked: 'Tyres and flaps' 6,676 and 'Lorry hire' 15,571 "
      "(bought-in capacity, a different channel)."),
  ),
  dict(
    isin="INE148O01028", family="logistics",          # Delhivery - 3PL
    exposure_tag="input:bought_in_freight", base_kind="TOTAL_COST",
    source_page="145",
    verbatim_excerpt=(
      "Freight, handling and servicing costs Particulars March 31, 2025 "
      "March 31, 2024 Line haul expenses 28,875.11 26,836.40 Contractual "
      "manpower expenses 11,574.11 9,950.34 Vehicle rental expenses "
      "17,567.71 16,029.60"),
    numerator=[dict(label="Line haul expenses", value="28,875.11")],
    denominator=dict(label="Total Expenses (II)", value="92,167.73",
                     page="127"),
    denominator_excerpt=(
      "Employee benefits expense 24 13,759.04 14,367.70 Finance costs 27 "
      "1,257.87 885.20 Depreciation and amortisation expense 26 5,349.08 "
      "7,215.50 Other expenses 25 6,453.89 6,073.78 Total Expenses (II) "
      "92,167.73 88,249.67"),
    computed_from=(
      "ASSET-LIGHT 3PL (bought-in freight, INDIRECT). Consolidated note 23, "
      "FY2024-25, Rs in millions. Numerator is 'Line haul expenses', the "
      "bought-in long-haul transport line. Diesel is inside a supplier's "
      "price here, not a purchase by the company, so pass-through is lagged "
      "and partial. 'Vehicle rental expenses' 17,567.71 excluded (rental of "
      "capacity, fuel treatment not stated); 'Power, fuel & water charges' "
      "2,129.66 excluded because water is bundled into it. "
      "INTERMEDIATION NOTE (input:bought_in_freight): the numerator is a "
      "bought-in FREIGHT BILL, not a fuel bill - it contains driver wages, "
      "tolls, tyres, financing and the operator's margin as well as diesel. "
      "The crude elasticity of this share is therefore materially BELOW the "
      "raw ratio: a 10% crude move does not move this line by 10%. The share "
      "states how much of total cost is exposed to the freight market; how "
      "much of the freight market is crude is a pass-through question this "
      "row does not answer and must not be read as answering."),
  ),
  dict(
    isin="INE766P01016", family="logistics",          # Mahindra Logistics
    exposure_tag="input:bought_in_freight", base_kind="TOTAL_COST",
    source_page="127",
    verbatim_excerpt=(
      "24. Operating Expenses (` Crores) Particulars Year ended 31 March "
      "2026 Year ended 31 March 2025 Freight & Other Related Expenses "
      "3,960.37 3,510.01 Labour & Other Related Expenses 740.32 627.04"),
    numerator=[dict(label="Freight & Other Related Expenses",
                    value="3,960.37")],
    denominator=dict(label="Total Expenses", value="5,620.52", page="111"),
    denominator_excerpt=(
      "(b) Employee benefits expense 25 325.01 292.81 (c) Finance costs 26 "
      "59.13 54.31 (d) Depreciation and amortisation expense 27 242.35 "
      "196.05 (e) Other expenses 28 130.47 120.05 Total Expenses 5,620.52"),
    computed_from=(
      "ASSET-LIGHT 3PL (bought-in freight, INDIRECT). Standalone note 24, "
      "Rs in crores. The line is named 'Freight & Other Related Expenses', "
      "so an unquantified 'other related' component is inside the "
      "numerator - this share is an upper bound on bought-in freight. The "
      "company's own direct fuel line, 'Power & Fuel' 32.56, is two orders "
      "of magnitude smaller and is excluded. "
      "INTERMEDIATION NOTE (input:bought_in_freight): the numerator is a "
      "bought-in FREIGHT BILL, not a fuel bill - it contains driver wages, "
      "tolls, tyres, financing and the operator's margin as well as diesel. "
      "The crude elasticity of this share is therefore materially BELOW the "
      "raw ratio: a 10% crude move does not move this line by 10%. The share "
      "states how much of total cost is exposed to the freight market; how "
      "much of the freight market is crude is a pass-through question this "
      "row does not answer and must not be read as answering."),
  ),
  dict(
    isin="INE233B01017", family="logistics",          # Blue Dart - air
    exposure_tag="input:intermediated_air_capacity", base_kind="TOTAL_COST",
    source_page="200",
    verbatim_excerpt=(
      "FREIGHT, HANDLING AND SERVICING COSTS Aircraft charter costs "
      "1,24,447 1,09,418 Domestic network operating costs 2,07,498 1,84,469 "
      "International servicing charges 18,929 20,077 Commercial airlift "
      "charges 25,488 25,603"),
    numerator=[dict(label="Aircraft charter costs", value="1,24,447"),
               dict(label="Commercial airlift charges", value="25,488")],
    denominator=dict(label="Total Expenses", value="5,46,260", page="178"),
    denominator_excerpt=(
      "Handling and Servicing Costs 27 4,04,051 3,63,659 Employee Benefits "
      "Expenses 28 73,741 70,781 Finance Costs 29 2,879 1,927 Depreciation "
      "and Amortisation Expense 30 20,921 18,725 Other Expenses 31 44,668 "
      "40,596 Total Expenses 5,46,260 4,95,688"),
    computed_from=(
      "ASSET-LIGHT (bought-in air capacity, INDIRECT), standalone note 27, "
      "Rs in lakhs, FY2024-25. Numerator = the two air-capacity lines. "
      "LOWER BOUND and the weakest logistics row: the largest line, "
      "'Domestic network operating costs' 2,07,498, is a black box that "
      "certainly contains diesel line-haul and equally certainly contains "
      "manpower, and the filing gives no split - it is excluded rather than "
      "apportioned. TAG CHOICE (input:intermediated_air_capacity, NOT "
      "input:atf): Blue Dart does not buy ATF. It buys air capacity from "
      "operators who do, so fuel reaches it through charter rates and fuel "
      "surcharges - lagged, contractual and diluted. The filing states the "
      "COST; that its price tracks ATF is mechanism, not disclosure. The "
      "separate tag is what records that difference instead of letting a "
      "charter bill be read as a fuel purchase."),
  ),
  dict(
    isin="INE688A01022", family="logistics",          # TCI - hybrid
    exposure_tag="input:bought_in_freight", base_kind="TOTAL_COST",
    source_page="188",
    verbatim_excerpt=(
      "COST OF RENDERING OF SERVICES C in Mn Particulars For the Year Ended "
      "31st March 2026 For the Year Ended 31st March 2025 Freight 23,738.74 "
      "22,586.97 Voyage Expenses 3,046.22 3,165.29 Vehicles' Trip Expenses "
      "2,790.68 2,595.28"),
    numerator=[dict(label="Freight", value="23,738.74")],
    denominator=dict(label="Total Expenses", value="38,729.68", page="157"),
    denominator_excerpt=(
      "Employee Benefits Expense 29 2,667.74 2,394.82 Finance Costs 30 "
      "177.61 149.73 Depreciation and Amortization Expense 31 1,112.79 "
      "1,060.08 Other Expenses 32 1,660.96 1,439.45 Total Expenses "
      "38,729.68 36,206.99"),
    computed_from=(
      "HYBRID, reported on its bought-in leg (INDIRECT). Standalone note "
      "28, Rs in millions. Numerator is the 'Freight' line only. TCI also "
      "discloses two further crude-linked lines this row deliberately "
      "EXCLUDES because they are a different channel: 'Vehicles' Trip "
      "Expenses' 2,790.68 (own-fleet diesel, DIRECT) and 'Voyage Expenses' "
      "3,046.22 (ship bunker fuel). Adding all three would give 29,575.64 "
      "and mix three transmission speeds in one number. "
      "INTERMEDIATION NOTE (input:bought_in_freight): the numerator is a "
      "bought-in FREIGHT BILL, not a fuel bill - it contains driver wages, "
      "tolls, tyres, financing and the operator's margin as well as diesel. "
      "The crude elasticity of this share is therefore materially BELOW the "
      "raw ratio: a 10% crude move does not move this line by 10%. The share "
      "states how much of total cost is exposed to the freight market; how "
      "much of the freight market is crude is a pass-through question this "
      "row does not answer and must not be read as answering."),
  ),
  dict(
    isin="INE586V01016", family="logistics",          # TCI Express
    exposure_tag="input:bought_in_freight", base_kind="TOTAL_COST",
    source_page="286",
    verbatim_excerpt=(
      "Network freight charges 797.95 781.65 GPS communication charges 0.90 "
      "0.85 Crane operating expenses 2.31 2.51 Payments to labour board "
      "16.64 16.38 Air freight charges 45.23 39.91 Ship freight charges "
      "2.58 2.42 Rail freight charges 14.29 12.51"),
    numerator=[dict(label="Network freight charges", value="797.95")],
    denominator=dict(label="Total Expenses", value="1,131.65", page="255"),
    denominator_excerpt=(
      "Operating expenses 28 886.96 862.13 Employee benefits expense 29 "
      "140.47 137.02 Finance costs 30 1.87 1.25 Depreciation and "
      "amortization expense 31 25.39 21.86 Other expenses 32 76.96 78.74 "
      "Total Expenses 1,131.65 1,101.00"),
    computed_from=(
      "ASSET-LIGHT 3PL (bought-in road freight, INDIRECT). Standalone note "
      "28, Rs in crores. Numerator is 'Network freight charges' - the "
      "bought-in road leg. Air freight 45.23, ship freight 2.58 and rail "
      "freight 14.29 are separate modes with separate fuel pass-throughs "
      "and are excluded. "
      "INTERMEDIATION NOTE (input:bought_in_freight): the numerator is a "
      "bought-in FREIGHT BILL, not a fuel bill - it contains driver wages, "
      "tolls, tyres, financing and the operator's margin as well as diesel. "
      "The crude elasticity of this share is therefore materially BELOW the "
      "raw ratio: a 10% crude move does not move this line by 10%. The share "
      "states how much of total cost is exposed to the freight market; how "
      "much of the freight market is crude is a pass-through question this "
      "row does not answer and must not be read as answering."),
  ),
  dict(
    isin="INE111A01025", family="logistics",          # CONCOR - rail
    exposure_tag="input:freight_diesel", base_kind="TOTAL_COST",
    source_page="280",
    verbatim_excerpt=(
      "(i) Handling & Other Operating expenses include ₹113.77 crore "
      "(2023-24: ₹112.92 crore) & ₹23.21 crore (2023- 24: ₹23.96 crore) "
      "towards power & fuel and consumption of stores & spares "
      "respectively."),
    numerator=[dict(label="power & fuel (within Handling & Other Operating "
                          "expenses)", value="113.77")],
    denominator=dict(label="Total expenses (IV)", value="7,597.15",
                     page="237"),
    denominator_excerpt=(
      "Employee benefits expense 31 488.85 462.82 Depreciation and "
      "amortisation expense 32 562.84 600.88 Finance cost 33 69.49 65.33 "
      "Other expenses 34 303.64 258.44 Total expenses (IV) 7,597.15"),
    computed_from=(
      "DIRECT fuel, standalone FY2024-25, Rs in crores. A deliberately "
      "SMALL number and the useful part of it: CONCOR's dominant cost is "
      "'Terminal and other service charges' 6,172.33, most of which is rail "
      "haulage paid to Indian Railways at administered rates rather than a "
      "diesel-indexed price. Power & fuel is the only line the filing "
      "identifies as fuel. Read this row as evidence that CONCOR is NOT "
      "materially crude-exposed on the cost side, not as an incomplete "
      "measurement of a large exposure."),
  ),

  # ---- FMCG DISTRIBUTION -----------------------------------------------
  # HINDUNILVR was sourced in the first pass at 0.2201 and has been REJECTED
  # to the unsourced file on owner ruling 2026-08-17. See the
  # MEASUREMENT_BASIS_MISMATCH entry below for the full record of what the
  # row was and why it does not stand. The family is now 0 of 8.
]

# -------------------------------------------------------------- UNSOURCED
# code -> (reason sentence template). Every entry names the pages checked.
UNSOURCED = [
  # ---- PAINTS: 6 of 6 -------------------------------------------------
  ("INE021A01026", "paints", "NO_BREAKUP_DISCLOSED",
   "Note 24A (p209) splits cost of materials consumed into 'Raw Materials "
   "Consumed' and 'Packing Materials Consumed' only, each as an "
   "opening/purchases/closing roll-forward, with no split by material type. "
   "The SEBI LODR commodity table (p154) is filled 'Not Applicable' and the "
   "narrative states most significant raw materials 'are not commodities, "
   "per se'. Checked p154, p185, p209, p262."),
  ("INE463A01038", "paints", "NO_BREAKUP_DISCLOSED",
   "Note 36 (p178) gives Raw materials Consumed and Packing material "
   "Consumed as roll-forwards only. The LODR commodity table (p142) is "
   "filled 'NIL' with the statement 'No commodity is considered to be "
   "material'. Checked p142, p152, p178."),
  ("INE531A01024", "paints", "NO_BREAKUP_DISCLOSED",
   "Note 31 (p309) gives Raw Material Consumed and Packing Material "
   "Consumed as roll-forwards only; no material-type split. Checked p275, "
   "p309."),
  ("INE133A01011", "paints", "AGGREGATED_SINGLE_LINE",
   "Note 20 (p73) is a single opening/purchases/closing roll-forward to "
   "'Total cost of materials consumed'. No components at all. Checked p59, "
   "p73, p94, p108."),
  ("INE09VQ01012", "paints", "NOTE_NOT_IN_TEXT_LAYER",
   "No 'cost of materials consumed' note could be located in this PDF's "
   "text layer at all (FY2025 report, 254 pages). The MD&A (p28) names "
   "'crude-based derivatives like binders and solvents, along with titanium "
   "dioxide' but attaches no values. Nothing computable, and the absence is "
   "an extraction limitation as much as a disclosure one."),
  ("INE792Z01011", "paints", "AGGREGATED_SINGLE_LINE",
   "Note 32 (p119) is headed 'Raw and Packing material consumed' - raw and "
   "packing are merged into one line, so even the raw/packing split other "
   "paint companies give is unavailable here. Checked p109, p119, p142."),

  # ---- TYRES: 6 of 7 (CEAT sourced) ------------------------------------
  ("INE883A01011", "tyres", "AGGREGATED_SINGLE_LINE",
   "Note 19 (p124 standalone, p199 consolidated) is opening stock / "
   "purchases / closing stock only. The SEBI LODR commodity table (p71) "
   "quantifies exactly one commodity - Natural Rubber, ₹4710.25 crores, "
   "249350 MT - which is the NON-crude input; the crude-linked basket is "
   "not quantified anywhere. A crude share cannot be derived by subtraction "
   "because the residual also contains steel cord, bead wire and zinc "
   "oxide."),
  ("INE787D01026", "tyres", "AGGREGATED_SINGLE_LINE",
   "Note 31 (p263) reads 'Raw Material Consumed 5,140.85' and nothing "
   "further. The Rupee-Spent chart (p92) gives a raw-material share of "
   "total cost but no commodity split. Checked p230, p263, p298."),
  ("INE438A01022", "tyres", "QUALITATIVE_ONLY",
   "The Board's Report (p79) and MD&A (p57, p80) name the crude-linked "
   "basket explicitly - 'Crude related based RM basket including Carbon "
   "Black, Synthetic Rubber, Fabric and Chemicals' - and state a 4% "
   "reduction in raw material cost, but attach no value or share to any "
   "component. The financial-statement note (p228, p303) is a single line. "
   "Named is not measured."),
  ("INE573A01042", "tyres", "PARTIAL_ONLY_NON_CRUDE_QUANTIFIED",
   "The Corporate Governance Report (p94) quantifies only natural rubber: "
   "'Natural Rubber is considered a material commodity, as its consumption "
   "constitutes more than 30% out of overall cost of raw material "
   "consumed... consumed 1,12,618 MT rubber, valuing ₹2,152 Crores'. That "
   "is the non-crude input. The commodity-risk note (p141) lists synthetic "
   "rubber, carbon black, fabric and crude oil by name with no values, and "
   "the P&L note (p121) is a single line. A crude share by subtraction "
   "would also sweep in steel and bead wire."),
  ("INE421C01016", "tyres", "AGGREGATED_SINGLE_LINE",
   "Note (p104) is an opening/purchases/closing roll-forward to 'Cost of "
   "Materials consumed' with no components. Checked p82, p98, p104, p127, "
   "p154."),
  ("INE533A01012", "tyres", "AGGREGATED_SINGLE_LINE",
   "Note 20 (p144) is 'Raw materials at the beginning of the year / Add: "
   "Purchases / Less: Raw materials at the end of the year'. No components. "
   "Checked p39, p120, p144."),

  # ---- SPECIALTY CHEMICALS (incl. adhesives): 10 of 10 -----------------
  ("INE318A01026", "specialty_chemicals", "AGGREGATED_SINGLE_LINE",
   "Note 32 (p209) is an inventory roll-forward to a single TOTAL of "
   "5,123.67. Pidilite - the largest adhesives exposure in the roster - "
   "discloses no VAM, no monomer, no resin and no solvent line anywhere in "
   "the financial statements. Checked p176, p209, p237, p264, p302."),
  ("INE288B01029", "specialty_chemicals", "AGGREGATED_SINGLE_LINE",
   "Note 28 is referenced from the P&L (p342) as a single 'Cost of "
   "Materials Consumed 1,544.01'; the note itself carries no commodity "
   "split. Phenol, acetone and cumene are named in the business narrative "
   "with no cost values. Checked p342, p371, p392, p406, p437."),
  ("INE100A01010", "specialty_chemicals", "NOTE_BODY_NOT_IN_TEXT_LAYER",
   "The P&L (p183) shows 'Cost of materials consumed 23 3,007.16'. Note 23 "
   "at p215 renders as a heading with no table body in the PDF text layer, "
   "so no components could be read - and none may be assumed. Checked p183, "
   "p215, p255, p290."),
  ("INE769A01020", "specialty_chemicals", "AGGREGATED_SINGLE_LINE",
   "Note 29 (p178) does split the base four ways - 'Consumption of Raw "
   "Materials 3,950.31 / Consumption of Packing Materials 50.64 / "
   "Consumption of Fuel 309.91 / Consumption of Stores & Spares 72.36' - "
   "but the raw-material line, which is where the benzene and toluene "
   "derivatives sit, is a single aggregate. 'Consumption of Fuel' is not "
   "identified as crude versus coal or briquette and is not assumed to be "
   "either. The BRSR materials table (p62) is tonnage, not value, and not "
   "by commodity."),
  ("INE959A01019", "specialty_chemicals", "AGGREGATED_SINGLE_LINE",
   "Note 23 (p158) gives 'Raw material consumed ... Consumption 132,353.56' "
   "and 'Packing material consumed ... Consumption 3,211.72'. No commodity "
   "split. Checked p104, p123, p139, p146, p158."),
  ("INE930P01018", "specialty_chemicals", "AGGREGATED_SINGLE_LINE",
   "Note 25(a)/27(a) (p218 standalone, p287 consolidated) is an "
   "opening/purchases/closing roll-forward with no components. Checked "
   "p180, p218, p249, p287."),
  ("INE410B01037", "specialty_chemicals", "AGGREGATED_SINGLE_LINE",
   "Note 19 (p161) is 'Opening Stock of Raw Materials / Purchases during "
   "the year / Closing Stock of Raw Materials / Total 1,182.29'. Isobutylene "
   "and other crude-derived feedstocks are not itemised. Checked p138, "
   "p161, p184, p206."),
  ("INE0BY001018", "specialty_chemicals", "AGGREGATED_SINGLE_LINE",
   "The note (p121 standalone, p166 consolidated) reads 'Raw materials "
   "consumed 21,545.69' as a single line. Checked p84, p105, p121, p123, "
   "p146, p166."),
  ("INE488A01050", "specialty_chemicals", "AGGREGATED_SINGLE_LINE",
   "Note (p178 standalone, p237 consolidated) is 'Inventories of material "
   "at the beginning of the year / Add: Purchase / Inventories of material "
   "at the end of the year'. EDC and VCM, the crude-linked PVC feedstocks, "
   "are not itemised. Checked p161, p178, p219, p237."),
  ("INE03CC01015", "specialty_chemicals", "AGGREGATED_SINGLE_LINE",
   "Note (p136 standalone, p217 consolidated) reads 'Raw and process "
   "materials consumed 9,164.32' - one line, and it merges raw with process "
   "materials. Checked p100, p136, p138, p165, p178, p217."),

  # ---- PACKAGING FILMS: 8 of 8 -----------------------------------------
  ("INE647A01010", "packaging_films", "AGGREGATED_SINGLE_LINE",
   "Note 24.1 (p158) is an opening/purchases/closing roll-forward to "
   "5,766.91, explicitly 'including packing material'. SRF's three segments "
   "(chemicals, packaging films, technical textiles) are not split by "
   "material anywhere in the note. Checked p132, p158, p179, p189, p216, "
   "p237."),
  ("INE291A01017", "packaging_films", "AGGREGATED_SINGLE_LINE",
   "Note 21 (p126 standalone, p174 consolidated) is Opening Inventory / "
   "Purchases / Sales / Closing Inventory to a single TOTAL. No polyester "
   "chip, PTA or MEG line. Checked p101, p126, p147, p174."),
  ("INE633B01018", "packaging_films", "NO_BREAKUP_DISCLOSED",
   "Note (p229 standalone, p320 consolidated) splits only 'Raw material "
   "consumed 1,00,582.32' from 'Packing material consumed 3,796.44'. The "
   "polymer inputs inside the raw-material line are not itemised. Checked "
   "p81, p188, p229, p268, p320."),
  ("INE516A01017", "packaging_films", "AGGREGATED_SINGLE_LINE",
   "Note 27 (p107) is Opening Stock / Purchases / less Inter Unit Purchases "
   "/ less Closing Stock to a single TOTAL of 4,95,875.04. Checked p54, "
   "p107, p108, p138, p139."),
  ("INE197D01010", "packaging_films", "AGGREGATED_SINGLE_LINE",
   "Note 33 (p162) reads 'Cost of Materials Consumed* / Cost of materials "
   "consumed 46,085.08' with the footnote 'identified from derived method "
   "based on physical verification of inventories'. One line, and a derived "
   "one. Checked p121, p162, p205, p257."),
  ("INE757A01017", "packaging_films", "NOTE_BODY_NOT_IN_TEXT_LAYER",
   "The P&L (p78 standalone, p122 consolidated) carries 'Cost of materials "
   "consumed 2,288.36' but no note table with components could be located "
   "in the text layer. The 'Other expenses' note (p100) separately shows "
   "'Stores, spare parts and packing materials consumed 144.33' and 'Power "
   "and fuel 219.12', neither of which is the raw-material breakup this "
   "exercise needs."),
  ("INE445C01015", "packaging_films", "AGGREGATED_SINGLE_LINE",
   "Note 32 (p116) is 'Raw material at the beginning of the year / Add: "
   "Purchases during the year / Less: Raw material at the end of the year / "
   "Cost of materials consumed 3,50,00.77'. No polymer line. Checked p91, "
   "p116, p144, p170."),
  ("INE275B01026", "packaging_films", "AGGREGATED_SINGLE_LINE",
   "Note (p92) is 'Inventory of raw materials and components at the "
   "beginning of the year / Add: Purchases / Less: Inventory at the end' to "
   "16,200.7. As flagged at roster time, Huhtamaki is one hop further out - "
   "a converter buying film rather than a polymer buyer - and its filing "
   "gives no film or resin line either. Checked p73, p92."),

  # ---- LOGISTICS: 0 unsourced (all 7 sourced) --------------------------

  # ---- LUBRICANTS: 5 of 6 (Savita sourced) -----------------------------
  ("INE172A01027", "lubricants", "NO_BREAKUP_DISCLOSED",
   "Note 17.1 (p162) is headed 'Cost of raw and packing materials consumed' "
   "- raw and packing merged - and is an inventory roll-forward with no "
   "components. The commodity-price-risk note (p181) states 'we are a "
   "purchaser of base oil... Material purchases forms the largest portion "
   "of our operating expenses' but quantifies nothing. Castrol is the "
   "clearest case in the run of a company that says its exposure in words "
   "and never in a number."),
  ("INE635Q01029", "lubricants", "NO_BREAKUP_DISCLOSED",
   "The note (p216 standalone, p294 consolidated) splits 'Cost of Raw "
   "Materials Consumed 1,64,335.16' from 'Cost of Packing Materials "
   "Consumed' but does not itemise base oil or additives inside the raw "
   "line. The LODR commodity table (p150) reads 'Total exposure of the "
   "listed entity to commodities: Nil' and 'NOT APPLICABLE', while the "
   "narrative on the same page calls the company 'a sizable user of "
   "imported Base oil' - the disclosure contradicts itself and quantifies "
   "neither side."),
  ("INE305C01029", "lubricants", "NO_BREAKUP_DISCLOSED",
   "Note (p141 standalone, p197 consolidated) splits raw material consumed "
   "from packing material consumed, both as roll-forwards; base oil is not "
   "a line. The commodity-risk note (p156) names base oil and crude "
   "volatility without values. Checked p111, p141, p156, p167, p197."),
  ("INE484C01030", "lubricants", "AGGREGATED_SINGLE_LINE",
   "Note 24 (p146) is headed 'Raw Materials (including Packing Materials)' "
   "- a single merged roll-forward to 1,106.31. Checked p32, p93, p105, "
   "p108, p121, p128, p142, p146."),
  ("INE717W01049", "lubricants", "AGGREGATED_SINGLE_LINE",
   "Note 25 (p127 P&L reference) is a single 'Cost of Materials Consumed "
   "27,538.99'; no base-oil line in the note. The commodity-risk note "
   "(p181) names base oil qualitatively. Checked p127, p156, p181, p185, "
   "p199, p230, p256."),

  # ---- FMCG DISTRIBUTION: 8 of 8 ---------------------------------------
  ("INE030A01027", "fmcg_distribution", "MEASUREMENT_BASIS_MISMATCH",
   "REJECTED FROM SOURCED on owner ruling 2026-08-17. A share of 0.2201 was "
   "computable and is not defensible. Numerator: the SEBI LODR commodity "
   "table in the Corporate Governance Report (p123) carries a single row "
   "'Brent / Benzene' at Rs 4,122 crores against a stated total commodity "
   "exposure of Rs 14,299 crores. Denominator: Ind AS note 27 (p160), total "
   "cost of materials consumed Rs 18,726 crores. THE TWO ARE DIFFERENT "
   "MEASURES. The LODR figure is an EXPOSURE on a purchase / hedged-position "
   "basis (the same row records 54% hedged through commodity derivatives); "
   "note 27 is CONSUMPTION, an inventory roll-forward. Nothing in the filing "
   "reconciles them, so the ratio has no defined meaning: its numerator and "
   "denominator do not measure the same thing over the same population. "
   "SECOND, INDEPENDENT DEFECT: the numerator row merges Brent and Benzene "
   "into one number. Both are crude-linked, but they are different price "
   "series with different spreads - benzene is a petrochemical whose margin "
   "over naphtha moves on its own - so even a well-based version of this row "
   "could not be attributed to a crude shock without splitting a figure the "
   "filing does not split. Neither defect is fixable from this document. "
   "Vegetable Oil (CPO) 1,078 and Tea 3,080 on the same table are excluded "
   "as not crude-linked."),
  ("INE154A01025", "fmcg_distribution", "AGGREGATED_SINGLE_LINE",
   "The P&L (p159 standalone, p255 consolidated) carries 'Cost of materials "
   "consumed 25939.49' as one line and the note adds no commodity split. "
   "ITC's crude exposure would sit in packaging and freight, neither of "
   "which is separately disclosed against the materials base. Checked p159, "
   "p255."),
  ("INE239A01024", "fmcg_distribution", "NOTE_BODY_NOT_IN_TEXT_LAYER",
   "Note 26 'COST OF MATERIALS CONSUMED' appears as a heading at p84 "
   "(standalone) and p142 (consolidated) with no table body in the PDF text "
   "layer, so no component values could be read. The P&L total is 98,140.4. "
   "Not sourced, and not assumed."),
  ("INE216A01030", "fmcg_distribution", "AGGREGATED_SINGLE_LINE",
   "Note 28 (p107) is 'Inventory of materials at the beginning of the year "
   "/ Add: Purchases, net / Less: Inventory of materials at the end of the "
   "year' to 8,608.64. No packaging or freight component against the "
   "materials base. Checked p90, p107, p125, p133, p152."),
  ("INE102D01028", "fmcg_distribution", "PARTIAL_ONLY_NON_CRUDE_QUANTIFIED",
   "The LODR commodity table (p373) quantifies exactly one commodity: "
   "'Soap Base Materials 1,412' crore, 1,45,968 MT, and the accompanying "
   "text attributes the exposure to 'imported palm oil derivatives' - "
   "agri-linked, not crude-linked. The materials note (p404, p494) carries "
   "no commodity split. Nothing crude is quantified."),
  ("INE016A01026", "fmcg_distribution", "NO_BREAKUP_DISCLOSED",
   "Note 35 (p369) splits 'Raw material' Sub-Total 2,471.48 from 'Packing "
   "material' Sub-Total 1,083.44, both as roll-forwards. Packing material "
   "is a large and partly crude-linked line, but the filing does not say "
   "how much of it is plastic or laminate versus paper, board and glass, so "
   "it cannot be used - see the ambiguity note in the report. Checked p330, "
   "p369, p371, p412, p457, p459."),
  ("INE259A01022", "fmcg_distribution", "NOTE_BODY_NOT_IN_TEXT_LAYER",
   "The only text-layer hits for 'cost of material consumed' (p57, p232, "
   "p251) are cross-references - e.g. p251 'obsolete inventory, which is "
   "included as a part of cost of material consumed'. The note table itself "
   "did not extract, so no components could be read."),
  ("INE548C01032", "fmcg_distribution", "AGGREGATED_SINGLE_LINE",
   "The note (p281 standalone, p378 consolidated) is an "
   "opening/purchases/closing roll-forward with no components. Checked "
   "p237, p281, p331, p378."),
]


def main() -> None:
    written = 0
    for f in SOURCED:
        unit, fy_end, markers = LEDGER_META[f["isin"]]
        f = dict(f, unit=unit, unit_multiplier=UNIT_MULTIPLIER[unit],
                 as_of_date=fy_end, exposure_kind=EXPOSURE_KIND,
                 markers=list(markers))
        d = FILINGS / f["isin"]
        # a company can carry more than one channel -> findings.json is a list
        path = d / "finding.json"
        existing = []
        if path.exists():
            cur = json.loads(path.read_text(encoding="utf-8"))
            existing = cur if isinstance(cur, list) else [cur]
        existing = [x for x in existing
                    if x.get("exposure_tag") != f["exposure_tag"]]
        existing.append(f)
        path.write_text(json.dumps(existing, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        written += 1
    for isin, family, code, reason in UNSOURCED:
        path = FILINGS / isin / "finding.json"
        path.write_text(json.dumps(
            [dict(isin=isin, family=family, unsourced=code, reason=reason)],
            indent=2, ensure_ascii=False), encoding="utf-8")
        written += 1

    # completeness: every roster company must have a finding of some kind
    missing = []
    for fam in FAMILY_ORDER:
        for ticker in ROSTER[fam]:
            hit = False
            for d in FILINGS.iterdir():
                sp = d / "source.json"
                if sp.exists() and json.loads(sp.read_text())["ticker"] == ticker:
                    hit = (d / "finding.json").exists()
                    break
            if not hit:
                missing.append((fam, ticker))
    print(f"findings written: {written}")
    if missing:
        print("!! roster companies with NO finding at all:")
        for fam, t in missing:
            print(f"   {fam:<22}{t}")
    else:
        print("every roster company has a finding.")


if __name__ == "__main__":
    main()
