"""Approved Step-1 roster for the crude ripple-exposure bootstrap.

Owner-approved on 2026-08-17 with these edits to the proposed list:
  - city gas DROPPED entirely (wrong mechanism; see DATA_GAPS.md §13)
  - adhesives MERGED into specialty_chemicals (same mechanism tag)
  - ASTRAL (pipes-primary) and VINYLINDIA (VAM trader) dropped
  - micro-cap floor of Rs 1,500cr applied as a DISCLOSED PROXY for the ADV
    filter that cannot be run (DATA_GAPS.md §12) -> drops HPAL, JYOTIRES
  - logistics uses base_kind = TOTAL_COST on the fuel / freight-and-handling
    expense line, NOT materials-consumed
  - fmcg_distribution runs last, lowest priority

A market-cap floor is not a liquidity filter. It is recorded here so the
substitution is visible in the artefact rather than only in a report.
"""

# family -> ordered list of NSE/BSE tickers as they appear in `companies.ticker`
ROSTER = {
    "paints": [
        "ASIANPAINT.NS", "BERGEPAINT.NS", "KANSAINER.NS",
        "JSWDULUX.NS", "INDIGOPNTS.NS", "SIRCA.NS",
    ],
    "tyres": [
        "MRF.NS", "BALKRISIND.NS", "APOLLOTYRE.NS", "CEATLTD.NS",
        "JKTYRE.NS", "TVSSRICHAK.NS", "GOODYEAR.NS",
    ],
    "specialty_chemicals": [
        # adhesives merged in: PIDILITIND, JUBLCPL
        "PIDILITIND.NS", "DEEPAKNTR.NS", "ATUL.NS", "AARTIIND.NS",
        "PRIVISCL.NS", "ANURAS.NS", "VINATIORGA.NS", "JUBLINGREA.NS",
        "CHEMPLASTS.NS", "JUBLCPL.NS",
    ],
    "packaging_films": [
        "SRF.NS", "GRWRHITECH.NS", "POLYPLEX.NS", "UFLEX.NS",
        "JINDALPOLY.NS", "COSMOFIRST.NS", "XPROINDIA.NS", "HUHTAMAKI.NS",
    ],
    "logistics": [
        "CONCOR.NS", "DELHIVERY.NS", "BLUEDART.NS", "TCI.NS",
        "VRLLOG.NS", "MAHLOG.NS", "TCIEXP.NS",
    ],
    "lubricants": [
        "CASTROLIND.NS", "GULFOILLUB.NS", "SOTL.NS",
        "PANAMAPET.NS", "VEEDOL.NS", "GANDHAR.NS",
    ],
    # LAST, lowest priority. Expect most of this to land UNSOURCED on
    # aggregated-single-line. Do not backfill or substitute.
    "fmcg_distribution": [
        "HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS",
        "GODREJCP.NS", "DABUR.NS", "COLPAL.NS", "EMAMILTD.NS",
    ],
}

# Order families are worked in. fmcg_distribution is deliberately last.
FAMILY_ORDER = [
    "paints", "tyres", "specialty_chemicals", "packaging_films",
    "logistics", "lubricants", "fmcg_distribution",
]

# Per-family base for share_of_base.
#   COGS        -> crude-linked material value / total cost of materials consumed
#   TOTAL_COST  -> fuel or freight-and-handling expense / total expenses
# Owner ruling 2026-08-17: logistics is TOTAL_COST because materials-consumed
# is the wrong base for a service business that buys no materials.
BASE_KIND = {
    "paints": "COGS",
    "tyres": "COGS",
    "specialty_chemicals": "COGS",
    "packaging_films": "COGS",
    "logistics": "TOTAL_COST",
    "lubricants": "COGS",
    "fmcg_distribution": "COGS",
}

MICRO_CAP_FLOOR_INR = 1_500e7  # Rs 1,500cr, disclosed ADV proxy

# Recorded so the reason survives the run.
DROPPED = {
    "city_gas": "family dropped entirely - wrong mechanism (VOLUME_DEMAND, "
                "plausibly positive sign) and regime-dependent administered "
                "input. DATA_GAPS.md section 13.",
    "ASTRAL.NS": "pipes-primary; adhesives is one segment",
    "VINYLINDIA.NS": "VAM trader, not an adhesives manufacturer; also below "
                     "the Rs 1,500cr floor",
    "HPAL.NS": "below the Rs 1,500cr micro-cap floor",
    "JYOTIRES.BO": "below the Rs 1,500cr micro-cap floor",
}
