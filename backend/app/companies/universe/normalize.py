"""Stage 2a of the universe ingest: pure transforms from raw snapshot text
to canonical company records. No network, no DB, no app.models import --
which is what lets the 2,278-company dual-listing merge be tested with
plain dicts.

The ISIN is the identity key. NSE and BSE rows for the same ISIN collapse
into ONE record with TWO listings; keying on ticker instead would duplicate
46% of the universe (spec §1).
"""
import csv
import io
import json
import math
from datetime import date

from app.companies.universe import sector_map, sub_sector_map

# Equity ISIN prefixes. INF* are mutual-fund/ETF units (253 on BSE) and are
# not companies; BSE also publishes one row whose ISIN is the literal "NA".
# This predicate is what reduces the 5,220-ISIN union to ~4,967 companies.
_COMPANY_ISIN_PREFIXES = ("INE", "IN9")


def is_company_isin(isin: str | None) -> bool:
    if not isin:
        return False
    return isin.strip().upper().startswith(_COMPANY_ISIN_PREFIXES)


def _clean(value) -> str:
    """Coerce a raw field to a stripped string. ``None`` and bools yield ""
    (a bool is never a legitimate SCRIP_CD/Mktcap/ISIN value, so treating it
    as absent is safer than stringifying True/False into the data). Any
    other scalar (str/int/float) is stringified rather than silently
    discarded -- BSE's JSON does not guarantee SCRIP_CD or Mktcap come back
    as strings, and dropping a numeric SCRIP_CD/Mktcap to "" caused total,
    silent loss of market cap and official classification for every row it
    touched."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def parse_nse_rows(csv_text: str) -> list[dict]:
    """NSE publishes EQUITY_L.csv with a leading space in every header
    after the first (" SERIES", " ISIN NUMBER"). Strip keys and values."""
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = []
    for raw in reader:
        row = {(k or "").strip(): _clean(v) for k, v in raw.items()}
        if is_company_isin(row.get("ISIN NUMBER")):
            rows.append(row)
    return rows


def parse_bse_rows(json_text: str) -> list[dict]:
    rows = []
    for raw in json.loads(json_text):
        row = {k: (v if v is not None else "") for k, v in raw.items()}
        if is_company_isin(_clean(row.get("ISIN_NUMBER"))):
            rows.append(row)
    return rows


def parse_bse_detail(json_text: str) -> dict:
    payload = json.loads(json_text)
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    return payload or {}


def _parse_float(value) -> float | None:
    # Indian-grouped cap strings ("1,32,904.62") are valid input; strip
    # thousands separators before parsing rather than silently failing.
    text = _clean(value).replace(",", "")
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    # float("inf")/float("-inf")/float("nan") all parse without raising.
    # An infinite Mktcap/FACE_VALUE would rank #1 in a ~5,000-company pool
    # (compute_cap_tiers sorts by cap descending) and demote a genuine
    # large cap out of LARGE -- reject anything non-finite, same as
    # app.companies.market_caps.fetch_market_cap already does for the
    # yfinance path.
    if not math.isfinite(parsed):
        return None
    return parsed if parsed > 0 else None


# BSE's "Mktcap" field is published in RUPEES CRORE (RELIANCE was
# "1771409.32" live on 2026-08-03); yfinance's fast_info["marketCap"] --
# the other source written to this same Company.market_cap column via
# app.companies.market_caps.refresh_market_caps -- is ABSOLUTE RUPEES
# (RELIANCE was 17,662,582,622,436 live the same day). Mixing the two units
# in one column ranks a yfinance-unit microcap 1e7x too high against a
# BSE-unit peer -- a probe of 403 BSE-crore companies plus 30 yfinance-unit
# ~Rs 300 crore microcaps returned all 30 microcaps as LARGE.
#
# BSE is converted UP to absolute rupees (crore * 1e7), not yfinance down
# to crore, for three reasons:
#   1. The 42 caps already in the production DB are yfinance-sourced
#      (absolute). Converting BSE up leaves those 42 correct as-is and
#      needs no data migration; converting yfinance down would require one.
#   2. app.market.measure.compute_materiality divides excess_traded_value
#      (day_volume * close, always absolute rupees) by market_cap. The
#      divisor must share units with that numerator or the ratio is
#      meaningless -- crore-unit caps would inflate materiality 1e7x for
#      every BSE-sourced company.
#   3. The frontend renders Company.market_cap raw. Absolute rupees keeps
#      existing display behaviour (calibrated against yfinance's scale)
#      unchanged.
_BSE_CRORE_TO_RUPEES = 10_000_000  # 1 crore = 1e7


def _parse_nse_date(value: str) -> date | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return date(
            int(text[7:11]),
            ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
             "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"].index(text[3:6].upper()) + 1,
            int(text[0:2]),
        )
    except (ValueError, IndexError):
        return None


def build_records(
    nse_rows: list[dict], bse_rows: list[dict], details: dict[str, dict], as_of: date,
) -> list[dict]:
    """Merge both exchange masters by ISIN into canonical records.

    ``details`` is {scrip_code: parsed detail payload}. A scrip whose detail
    is absent yields NULL classification and NULL classification_source --
    never a guessed sector (spec §4).
    """
    merged: dict[str, dict] = {}

    for row in nse_rows:
        isin = row["ISIN NUMBER"].strip().upper()
        record = merged.setdefault(isin, _blank_record(isin, as_of))
        record["nse_name"] = row.get("NAME OF COMPANY", "")
        record["listings"].append({
            "exchange": "NSE",
            "symbol": row["SYMBOL"],
            "scrip_code": None,
            "series": row.get("SERIES") or None,
            "group_code": None,
            "status": "ACTIVE",
            "is_sme": False,
            "is_primary": False,
            "face_value": _parse_float(row.get("FACE VALUE")),
            "listed_on": _parse_nse_date(row.get("DATE OF LISTING", "")),
            "source": "NSE",
            "as_of": as_of,
        })

    for row in bse_rows:
        isin = _clean(row.get("ISIN_NUMBER")).upper()
        record = merged.setdefault(isin, _blank_record(isin, as_of))
        scrip_code = _clean(row.get("SCRIP_CD"))
        group_code = _clean(row.get("GROUP")).upper() or None
        record["bse_name"] = _clean(row.get("Issuer_Name")) or _clean(row.get("Scrip_Name"))

        market_cap_cr = _parse_float(row.get("Mktcap"))
        if market_cap_cr is not None:
            record["market_cap"] = market_cap_cr * _BSE_CRORE_TO_RUPEES
            record["market_cap_source"] = "BSE"
            record["market_cap_as_of"] = as_of

        detail = details.get(scrip_code)
        if detail:
            record["official_sector"] = _clean(detail.get("Sector")) or None
            record["official_industry"] = _clean(detail.get("IndustryNew")) or None
            record["official_igroup"] = _clean(detail.get("IGroup")) or None
            record["official_isubgroup"] = _clean(detail.get("ISubGroup")) or None
            if record["official_sector"]:
                record["classification_source"] = "BSE"
                record["classification_as_of"] = as_of

        record["listings"].append({
            "exchange": "BSE",
            "symbol": _clean(row.get("scrip_id")) or scrip_code,
            "scrip_code": scrip_code,
            "series": None,
            "group_code": group_code,
            "status": "SUSPENDED" if _clean(row.get("Status")).upper() == "SUSPENDED" else "ACTIVE",
            "is_sme": group_code in ("M", "MT", "MS"),
            "is_primary": False,
            "face_value": _parse_float(row.get("FACE_VALUE")),
            "listed_on": None,
            "source": "BSE",
            "as_of": as_of,
        })

    records = []
    for record in merged.values():
        nse_listing = next((l for l in record["listings"] if l["exchange"] == "NSE"), None)
        primary = nse_listing or record["listings"][0]
        primary["is_primary"] = True
        suffix = ".NS" if primary["exchange"] == "NSE" else ".BO"
        record["ticker"] = f"{primary['symbol']}{suffix}"
        # BSE's Issuer_Name is the registrar-style legal name and is the
        # better display/alias source; fall back to NSE's when BSE has no
        # listing for this ISIN.
        record["name"] = record.pop("bse_name", "") or record.pop("nse_name", "") or primary["symbol"]
        record.pop("nse_name", None)
        record["sector"] = sector_map.map_sector(
            record["official_sector"], record["official_industry"],
        )
        # Cap tier is unknown at ingest time (it's a rank over the whole
        # population, computed later) -- called with two args, so IT
        # services always resolve to it_other here; a later pass with the
        # tier can refine it.
        record["sub_sector"] = sub_sector_map.map_sub_sector(
            record["official_isubgroup"], record["sector"],
        )
        record["tradeability"] = sector_map.derive_tradeability(record["listings"])
        records.append(record)
    return records


def _blank_record(isin: str, as_of: date) -> dict:
    return {
        "isin": isin,
        "name": "",
        "sector": "other",
        "sub_sector": None,
        "official_sector": None,
        "official_industry": None,
        "official_igroup": None,
        "official_isubgroup": None,
        "classification_source": None,
        "classification_as_of": None,
        "market_cap": None,
        "market_cap_source": None,
        "market_cap_as_of": None,
        "tradeability": "NORMAL",
        "ticker": "",
        "listings": [],
    }


# AMFI's half-yearly "Average Market Capitalization of listed companies"
# workbook -- verified live on 2026-08-03 at
# https://portal.amfiindia.com/spages/AverageMarketCapitalization30Jun2026.xlsx
# (linked from https://www.amfiindia.com/otherdata/categorisation-of-stocks;
# the previously-documented /research-information/... URL 404s). Real header
# row: "Sr. No.", "Company name", "ISIN", "BSE Symbol",
# "BSE 6 month Avg Total Market Cap in (Rs. Crs.)", "NSE Symbol",
# "NSE 6 month Avg Total Market Cap (Rs. Crs.)", "MSEI Symbol",
# "MSEI 6 month Avg Total Market Cap in (Rs Crs.)",
# "Average of All Exchanges (Rs. Cr.)",
# "Categorization as per SEBI Circular dated Oct 6, 2017" -- NOT the
# documented "Company Name" / "Average Market Cap" / "Categorization"
# shape. Only ISIN and the categorization column are needed here; the
# per-exchange cap columns are not read.
#
# The file itself is fetched at runtime (like the NSE/BSE masters) into the
# data/universe/<day>/ snapshot directory -- it is NOT committed to the repo
# (see backend/.gitignore). Landing page to re-fetch from:
# https://www.amfiindia.com/otherdata/categorisation-of-stocks
_AMFI_CATEGORIZATION_COLUMN = "Categorization as per SEBI Circular dated Oct 6, 2017"

_AMFI_TIER_VOCABULARY = {
    "large cap": "LARGE", "largecap": "LARGE",
    "mid cap": "MID", "midcap": "MID",
    "small cap": "SMALL", "smallcap": "SMALL",
}


def parse_amfi_rows(csv_text: str) -> list[dict]:
    """AMFI's half-yearly categorisation list -- the only PUBLISHED source
    for the regulatory LARGE/MID/SMALL split. Rank is the row's position in
    the file, which AMFI publishes in descending average-market-cap order.

    Rows whose tier is outside the published vocabulary are dropped rather
    than guessed at.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = []
    for position, raw in enumerate(reader, start=1):
        row = {(k or "").strip(): _clean(v) for k, v in raw.items()}
        isin = row.get("ISIN", "").upper()
        tier = _AMFI_TIER_VOCABULARY.get(row.get(_AMFI_CATEGORIZATION_COLUMN, "").lower())
        if not is_company_isin(isin) or tier is None:
            continue
        rows.append({"isin": isin, "amfi_tier": tier, "amfi_rank": position})
    return rows
