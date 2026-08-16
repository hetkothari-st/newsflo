"""STAGE B -- XBRL instance parsing.

XBRL first, because it is structured and unambiguous: a concept name, a
context, a unit and a number, with no layout to misread. stdlib
`xml.etree.ElementTree` only -- no new dependency (controller adaptation).

This module PARSES. It maps concepts to `company_financials` columns via an
explicit table below, and returns rows for a loader to write; it decides
nothing and writes nothing. A concept the table does not name is returned as
an unmapped fact rather than guessed into a column.
"""
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import xml.etree.ElementTree as ET

# Ind AS / in-gaap concept local-names -> company_financials columns.
# DELIBERATELY SMALL AND EXPLICIT. A wrong mapping here is a wrong number in
# the ledger with a perfect-looking provenance chain, so this table grows
# only by review against a real taxonomy -- never by pattern-matching a
# concept name at runtime.
CONCEPT_MAP: Mapping[str, str | None] = {
    "RevenueFromOperations": "revenue_inr",
    "ProfitLossForPeriod": "pat_inr",
    "CostOfMaterialsConsumed": "raw_material_inr",
    "PurchasesOfStockInTrade": None,          # known, deliberately not mapped
    "EmployeeBenefitExpense": "employee_inr",
    "PowerAndFuelExpense": "power_fuel_inr",
    "FreightAndForwardingExpense": "freight_inr",
    "Borrowings": "gross_debt_inr",
}


@dataclass(frozen=True)
class XBRLFact:
    concept: str
    context: str | None
    unit: str | None
    value: float | None
    raw: str


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def parse_xbrl_facts(source: str | bytes) -> list[XBRLFact]:
    """Every numeric-looking fact in an instance document, in document
    order. A value that does not parse as a number is kept with
    `value=None` and its raw text -- never coerced to 0."""
    root = ET.fromstring(source)
    facts: list[XBRLFact] = []
    for element in root.iter():
        text_value = (element.text or "").strip()
        if not text_value:
            continue
        context = element.attrib.get("contextRef")
        if context is None and "unitRef" not in element.attrib:
            continue
        try:
            value = float(text_value.replace(",", ""))
        except ValueError:
            value = None
        facts.append(XBRLFact(_localname(element.tag), context,
                              element.attrib.get("unitRef"), value, text_value))
    return facts


def financial_rows_from_facts(facts: Sequence[XBRLFact], *, company_id: int,
                              fiscal_period: str, source_url: str,
                              as_of_date, contexts: Iterable[str] | None = None,
                              created_by: str = "ingest:xbrl_v0") -> dict:
    """One `company_financials` row from the mapped facts.

    Only mapped concepts contribute; every other column stays absent (and
    therefore NULL in the table) rather than being filled with a derived or
    assumed figure."""
    wanted = set(contexts) if contexts else None
    row = {"company_id": company_id, "fiscal_period": fiscal_period,
           "source_url": source_url, "as_of_date": as_of_date,
           "created_by": created_by}
    for fact in facts:
        if wanted is not None and fact.context not in wanted:
            continue
        column = CONCEPT_MAP.get(fact.concept)
        if not column or fact.value is None:
            continue
        row.setdefault(column, fact.value)
    return row


def unmapped_concepts(facts: Sequence[XBRLFact]) -> list[str]:
    """What this filing carried that the map does not know about -- the
    working list for extending CONCEPT_MAP under review."""
    return sorted({fact.concept for fact in facts
                   if fact.concept not in CONCEPT_MAP})
