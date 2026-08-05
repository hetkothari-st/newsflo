"""Deterministic vague-rationale guard: flag a company rationale that hedges
("may benefit", "could see", "is exposed to", "sentiment", "broader theme")
WITHOUT ever naming a concrete transmission channel.

Same spirit as app.reasoning.compliance -- a pure, testable text predicate
that runs before anything is persisted, rather than a second opinion asked of
a model. app.analysis.verification runs it over every ticker-bearing company
so a pure-hedge rationale is dropped whatever the LLM verifier says about it
(a generative model asked "does this belong?" is measurably reluctant to
reject its own earlier output; a regex is not).

CONSERVATISM IS THE WHOLE DESIGN. A false positive here silently deletes a
genuine, correct company from a user-visible alert, and nothing downstream
can recover it. So the rule is deliberately two-sided: a rationale is flagged
ONLY when it hedges AND names no concrete channel at all. Hedging is normal,
honest analyst language -- "margins may compress because jet fuel is 30% of
operating cost" hedges and is exactly the output we want -- so the hedge word
alone is never enough. The concrete-channel vocabulary below is intentionally
wide for the same reason: every term missing from it is a potential false
positive, while a term wrongly included only costs us a rejection we would
have had to rely on the LLM verifier for anyway.
"""
import re
from typing import NamedTuple

# Hedges: language that asserts a relationship without committing to a
# mechanism. Deliberately narrow -- these are the specific constructions the
# cascade actually produces when it has nothing concrete to say.
_HEDGE_RE = re.compile(
    r"\b("
    r"may|might|could|potentially|possibly|perhaps|"
    r"likely|expected to|anticipated to|"
    r"exposed to|exposure to|"
    r"stands? to|poised to|set to|"
    r"sentiment|thematic|theme|narrative|"
    r"indirectly|broadly|generally|somewhat|arguably"
    r")\b",
    re.IGNORECASE,
)

# Concrete transmission channels: a named cost line, a named revenue line, a
# named customer/supplier/competitor relationship, a named regulatory
# exposure, or a named balance-sheet/financing channel. Presence of ANY of
# these means the rationale said something checkable, so it is never flagged
# however much it also hedges.
_CONCRETE_RE = re.compile(
    r"\b("
    # -- cost lines
    r"cost|costs|costing|input|inputs|raw material|raw materials|feedstock|"
    r"fuel|crude|coal|gas|power|electricity|freight|shipping|logistics|"
    r"wage|wages|salary|salaries|labour|labor|rent|royalty|royalties|"
    r"margin|margins|ebitda|opex|capex|expense|expenses|overhead|"
    r"depreciation|amortisation|amortization|"
    # -- revenue lines
    r"revenue|revenues|sales|turnover|topline|top-line|"
    r"order|orders|orderbook|order book|backlog|volume|volumes|"
    r"realisation|realisations|realization|realizations|pricing|price|prices|"
    r"tariff|tariffs|toll|tolls|fare|fares|premium|premiums|yield|yields|"
    r"fee|fees|commission|commissions|subscription|footfall|occupancy|"
    # -- named relationships
    r"customer|customers|client|clients|buyer|buyers|"
    r"supplier|suppliers|supplies|vendor|vendors|sourcing|procurement|"
    r"contract|contracts|tender|tenders|deal|deals|offtake|"
    r"distributor|distributors|dealer|dealers|oem|oems|"
    r"competitor|competitors|competition|market share|"
    r"subsidiary|subsidiaries|joint venture|partnership|"
    r"fleet|plant|plants|factory|factories|refinery|refineries|mine|mines|"
    r"capacity|utilisation|utilization|inventory|inventories|"
    # -- regulatory exposure
    r"regulator|regulators|regulation|regulations|regulatory|regulated|"
    r"licence|licences|license|licenses|licensing|permit|permits|"
    r"approval|approvals|certification|certified|certify|clearance|"
    r"duty|duties|levy|levies|cess|tax|taxes|gst|"
    r"subsidy|subsidies|incentive|incentives|quota|quotas|ban|banned|"
    r"mandate|mandated|compliance|norm|norms|standard|standards|"
    r"sanction|sanctions|antitrust|"
    # -- financing / balance sheet
    r"loan|loans|lending|credit|debt|borrowing|borrowings|interest|"
    r"deposit|deposits|nim|npa|provision|provisions|"
    r"hedge|hedged|unhedged|forex|currency|rupee|dollar|"
    r"import|imports|imported|export|exports|exported|"
    r"receivable|receivables|payable|payables|working capital|"
    r"demand|supply|production|output|shipment|shipments|delivery|deliveries"
    r")\b",
    re.IGNORECASE,
)


class VaguenessResult(NamedTuple):
    is_vague: bool
    reason: str | None


def flag_vague_rationale(text: str | None) -> VaguenessResult:
    """True only when `text` hedges AND names no concrete channel.

    Empty/None is NOT flagged -- same choice as
    app.reasoning.compliance.validate_no_advice_language. There is nothing
    here to call vague, and a missing rationale is a different defect with a
    different owner (the schema requires one); silently deleting a company
    over it would be this guard reaching outside its remit.
    """
    if not text:
        return VaguenessResult(False, None)
    hedge = _HEDGE_RE.search(text)
    if not hedge:
        return VaguenessResult(False, None)
    if _CONCRETE_RE.search(text):
        return VaguenessResult(False, None)
    return VaguenessResult(
        True, f"hedged ({hedge.group(0)!r}) with no concrete cost, revenue, "
              f"relationship, or regulatory channel named",
    )
