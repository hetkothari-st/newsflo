"""Named supplier/customer relationships extracted from rating rationales.

Credit-rating agencies (CRISIL, ICRA, CARE, India Ratings, Acuite,
Infomerics) publish public rationale PDFs for every rated instrument, and
those PDFs routinely name the business model and key counterparties
("derives ~60% of revenue from Indian Railways"; "key suppliers include
..."). They are the only free, public, citable source of named supply-chain
relationships for Indian listed companies -- annual reports anonymize
counterparties, exchanges publish none, and commercial datasets (Bloomberg
SPLC, FactSet Revere) are licensed. Coverage is honest, not complete: only
rated companies have rationales, realistically 1,500-2,500 of the universe.
Nothing is invented for the gap.

This package fills `supply_chain_suppliers_json` / `supply_chain_customers_
json`, and still-NULL `business_desc` rows, with facts traceable to a named
PDF: every stored supplier/customer entry carries a verbatim evidence quote
that must appear in the source document under whitespace-normalized
substring match, or the row is never written.

Hard constraint (user-locked): supply links never auto-attribute impact. No
code path may create an AlertCompany or ImpactEdge from a stored link --
links reach the LLM prompt as a grounding layer and nothing else. The LLM
still decides who is affected. This must be structurally impossible, not
merely policy, because a deterministic fan-out from "company X supplies
company Y" to "Y is directly affected" is exactly the failure mode this
package exists to prevent.

Layout mirrors app.companies.universe and app.companies.descriptions --
`snapshot.py` (paths/resume sets), `fetchers.py` (network only), `extract.py`
(pure: PDF text + LLM-as-reader + evidence gate), `loader.py` (DB only).
"""
