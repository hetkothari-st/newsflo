"""Guard on the company-identification stage's assembled prompt SIZE.

This test exists because prose growth in the company prompt silently broke
production, twice. Groq enforces a per-minute TOKEN ceiling per model
(app.analysis.claude_client.GROQ_TPM_CEILING), and the tightest one belongs
to the ONLY model that can reliably satisfy this stage's deeply-nested tool
schema:

    openai/gpt-oss-20b      8,000 TPM   handles the nested tool schema
    llama-3.3-70b-versatile 12,000 TPM  fails the schema constantly

A prompt that fits only llama is therefore a prompt that fails -- which is
exactly what happened: 47 of the last 48 alerts carried ZERO companies
because every article 413'd or tool_use_failed'd. The fix was to shrink the
prompt under gpt-oss's ceiling so gpt-oss can be the PRIMARY model. Nothing
enforces that but this test, so if it fails, do not raise the budget --
shrink the prompt.

Token estimation uses a documented chars-per-token ratio calibrated against
a REAL production request: a 45,200-char request billed 16,358 tokens, i.e.
2.76 chars/token. That is deliberately pessimistic relative to ordinary
English prose (~4 chars/token) because a large share of this particular
prompt is ticker/JSON-dense text (the candidate block and the tool schema's
ticker enum), which tokenizes far worse than prose.
"""
import json
from types import SimpleNamespace

import pytest

from app.analysis.cascade import (
    COMPANY_PROMPT_TOKEN_BUDGET, MAX_PARENT_POOL, _identify_companies,
)
from app.analysis.claude_client import GROQ_TPM_CEILING, SYSTEM_PROMPT, FALLBACK_MODEL
from app.analysis.schemas import SectorFinding
from app.companies.candidates import MAX_CANDIDATES_PER_SECTOR
from app.models import Company

# Production calibration (2026-08): a 45,200-char request billed 16,358
# tokens. 45_200 / 16_358 = 2.763 chars/token. Rounded DOWN to 2.76 so the
# estimate errs high (more tokens) rather than low.
CHARS_PER_TOKEN = 2.76

# Under gpt-oss-20b's 8,000 TPM with real margin, not by a rounding error.
# The margin absorbs the parts this test cannot see: a longer real `facts`
# blob, longer real company names, and the response tokens Groq also counts
# against the same per-minute budget. Imported, not redeclared -- the budget
# belongs next to the prompt it constrains, so that a reader of cascade.py
# sees the limit without having to find this file.
PROMPT_TOKEN_BUDGET = COMPANY_PROMPT_TOKEN_BUDGET


def estimate_tokens(text: str) -> int:
    return round(len(text) / CHARS_PER_TOKEN)


def _seed_full_sector(session, sector="oil_gas", count=MAX_CANDIDATES_PER_SECTOR):
    """A FULL candidate list -- the worst case the prompt ever assembles,
    since app.companies.candidates caps one sector at
    MAX_CANDIDATES_PER_SECTOR and every company stage now sends one sector
    per call. Names/sub-sectors are sized like real Indian listed rows
    (which is what actually lands in the prompt and in the tool schema's
    ticker enum), not like short test fixtures.

    Idempotent, so a test may assemble the prompt more than once against the
    same session."""
    if session.query(Company).filter_by(sector=sector).count():
        return
    for i in range(count):
        session.add(Company(
            ticker=f"CANDIDATE{i:02d}.NS",
            name=f"Candidate Industries & Petrochemicals Limited {i:02d}",
            sector=sector,
            index_tier="OTHER",
            sub_sector="Refineries & Marketing",
            business_desc=(
                "Refines crude oil into transport fuels and petrochemical "
                "feedstock, and operates a national retail fuel network."
            ),
            market_cap=float(1_000_000 - i),
            market="INDIA",
            tradeability="NORMAL",
        ))
    session.commit()


# A representative facts blob -- deliberately on the LONG side of what
# _extract_facts actually returns (that stage runs with max_tokens=1024 and
# emits one dense prose paragraph). A one-line stub here would understate
# the prompt and let the budget pass while production still 413s.
REPRESENTATIVE_FACTS = (
    "Brent crude settled 4.8% higher at $91.30 a barrel after OPEC+ agreed "
    "to extend voluntary production cuts of 2.2 million barrels per day "
    "through the end of the quarter, with Saudi Arabia and Russia both "
    "confirming their individual quotas would roll over unchanged. Indian "
    "refiners import roughly 88% of their crude requirement, and the "
    "country's crude import bill was $132 billion in the last full "
    "financial year. The rupee closed at 83.42 to the dollar, a two-week "
    "low, after the announcement. Government officials said retail petrol "
    "and diesel prices would remain unchanged for now, with state-owned oil "
    "marketing companies absorbing the difference between landed crude cost "
    "and the administered pump price; no compensation mechanism has been "
    "announced. Aviation turbine fuel prices were raised 3.1% with "
    "immediate effect, the third increase this quarter. Petrochemical "
    "feedstock naphtha and LPG contract prices are indexed to crude with a "
    "one-month lag. Analysts quoted in the article noted that upstream "
    "producers realise a higher price on every barrel produced, while "
    "downstream marketers face a widening gap between input cost and the "
    "price they are permitted to charge, and that gas-based producers whose "
    "realisations are set administratively see no immediate benefit. The "
    "article did not name any specific listed company."
)


class _CapturingClient:
    """Captures the assembled request and returns an empty-but-valid tool
    call, so _identify_companies runs its real prompt-assembly path end to
    end (framing + instructions + facts + sectors + candidate block + tool
    schema) instead of the test re-implementing it and drifting from it."""

    def __init__(self):
        self.messages = None
        self.tools = None

    class _Completions:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            self._outer.messages = kwargs["messages"]
            self._outer.tools = kwargs["tools"]
            message = SimpleNamespace(tool_calls=[SimpleNamespace(
                function=SimpleNamespace(
                    name="record_sector_companies",
                    arguments=json.dumps({"sector_companies": []}),
                ),
            )])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    @property
    def chat(self):
        return SimpleNamespace(completions=self._Completions(self))


def _assemble(db_session, parent_pool=None):
    """Runs the real stage against a captured client and returns the FULL
    billable request text: every message plus the serialized tool schema.
    Groq bills the tool schema too -- measuring only the user message would
    miss the ticker enum, which is one of the largest single blocks here."""
    _seed_full_sector(db_session)
    client = _CapturingClient()
    _identify_companies(
        client, REPRESENTATIVE_FACTS,
        [SectorFinding(
            sector="oil_gas", direction="bullish",
            mechanism=(
                "Higher crude prices lift upstream realisations while "
                "squeezing downstream marketing margins under an unchanged "
                "administered pump price."
            ),
        )],
        "direct", parent_pool, session=db_session,
    )
    assert client.messages is not None, "stage never issued a request"
    return "".join(m["content"] for m in client.messages) + json.dumps(client.tools)


def test_direct_stage_prompt_fits_the_smallest_groq_token_ceiling(db_session):
    request_text = _assemble(db_session)
    tokens = estimate_tokens(request_text)

    assert tokens < PROMPT_TOKEN_BUDGET, (
        f"company prompt is {tokens} tokens ({len(request_text)} chars at "
        f"{CHARS_PER_TOKEN} chars/token), over the {PROMPT_TOKEN_BUDGET} "
        f"budget. Do NOT raise the budget: {FALLBACK_MODEL} allows "
        f"{GROQ_TPM_CEILING[FALLBACK_MODEL]} tokens/minute and it is the only "
        "model that reliably satisfies this tool schema. Shrink the prompt."
    )


def _parent_pool(count):
    from app.analysis.schemas import CompanyMention
    return [
        CompanyMention(
            name=f"Parent Industries & Petrochemicals Limited {i:02d}",
            ticker=f"PARENT{i:02d}.NS", is_direct=True, sector="oil_gas",
            direction="bullish", magnitude_low=1.0, magnitude_high=3.0,
            rationale="r", time_horizon="Short-Term",
        )
        for i in range(count)
    ]


def test_cascade_stage_prompt_fits_the_smallest_groq_token_ceiling(db_session):
    """The cascade stages (5/7) carry a LONGER framing than the direct stage,
    a parent-company list, AND a parent_ticker enum in the tool schema, so
    the direct stage passing is not evidence that these do -- the cascade
    prompt is the binding case, and it is the one measured against budget.

    The pool is deliberately OVERSUBSCRIBED (more parents than
    MAX_PARENT_POOL) so this measures the capped worst case. Uncapped, the
    pool is the entire previous company stage's output, which grows with the
    breadth the prompt asks for -- i.e. the better the primary stage does,
    the more likely the cascade stage would blow the ceiling.
    """
    request_text = _assemble(db_session, parent_pool=_parent_pool(MAX_PARENT_POOL * 2))
    tokens = estimate_tokens(request_text)

    assert tokens < PROMPT_TOKEN_BUDGET, (
        f"cascade company prompt is {tokens} tokens over the "
        f"{PROMPT_TOKEN_BUDGET} budget -- shrink the prompt, not the budget."
    )


def test_cascade_stage_prompt_fits_budget_with_supply_links(db_session):
    """Regression guard (2026-08-06 review): grounding the L1 cascade stage
    with the KNOWN RELATIONSHIPS block (app.companies.supply_links.
    prompting) is additive prompt content the two tests above cannot see --
    they seed no SupplyLink rows. Before the block's caps were tightened
    (app.config's SUPPLY_PROMPT_MAX_CHARS 700->500, SUPPLY_PROMPT_MAX_EXTRAS
    added, and grounding restricted to the L1 stage only -- see
    cascade._identify_companies), the assembled prompt measured 6,657-7,165
    tokens against this file's PROMPT_TOKEN_BUDGET=6,500.

    Reuses test_cascade_stage_prompt_fits_the_smallest_groq_token_ceiling's
    OVERSUBSCRIBED pool (MAX_PARENT_POOL * 2, truncated to MAX_PARENT_POOL)
    -- that scenario is ALREADY close to budget without links (~6,283
    tokens measured), which is exactly why adding the block on top is where
    a regression would actually surface; the isolated case with only a
    couple of parent companies and no oversubscription has too much slack
    to ever catch it (measured ~5,050 tokens either way -- nowhere near
    budget regardless of the caps, because too few parents have stored
    links for the block to actually reach its own cap).

    5 of the (already-capped) MAX_PARENT_POOL parent companies get stored
    links -- 3 customer + 3 supplier each, long names -- enough groups (10)
    to exceed SUPPLY_PROMPT_MAX_LINES (8) and actually saturate the block's
    own caps, which is what makes this measure the real worst case rather
    than an under-filled one: measured BEFORE this review's fix (char cap
    700, no extras cap) this exact scenario is 6,579 tokens, already over
    PROMPT_TOKEN_BUDGET=6,500 on its own -- confirming this is a genuine
    regression guard, not a test that would pass regardless of the caps.
    """
    from datetime import date, datetime, timezone

    from app.models import SupplyLink

    parents = _parent_pool(MAX_PARENT_POOL * 2)
    # Only the first MAX_PARENT_POOL survive _identify_companies' own
    # truncation (see cascade.py's MAX_PARENT_POOL comment) -- real Company
    # rows (needed for known_relationships_block to resolve a ticker to a
    # company_id) are seeded for exactly that many, matching production
    # (every parent the LLM actually sees resolves to a real company).
    surviving = parents[:MAX_PARENT_POOL]
    for mention in surviving:
        db_session.add(Company(
            ticker=mention.ticker, name=mention.name, sector="oil_gas", index_tier="OTHER",
            market="INDIA", tradeability="NORMAL",
        ))
    db_session.commit()

    for mention in surviving[:5]:
        parent_company = db_session.query(Company).filter_by(ticker=mention.ticker).one()
        for relation in ("CUSTOMER", "SUPPLIER"):
            for j in range(3):
                db_session.add(SupplyLink(
                    company_id=parent_company.id, relation=relation,
                    counterparty_name=(
                        f"{relation.title()} Industries & Trading Company "
                        f"Number {mention.ticker}{j} Limited"
                    ),
                    counterparty_company_id=None,
                    evidence="q", source_url="u", source_agency="CRISIL",
                    as_of=date(2026, 8, 6), extracted_at=datetime.now(timezone.utc),
                ))
    db_session.commit()

    request_text = _assemble(db_session, parent_pool=parents)
    tokens = estimate_tokens(request_text)

    assert tokens < PROMPT_TOKEN_BUDGET, (
        f"cascade company prompt WITH supply links is {tokens} tokens over "
        f"the {PROMPT_TOKEN_BUDGET} budget -- shrink the KNOWN RELATIONSHIPS "
        "block (app.companies.supply_links.prompting / app.config's "
        "SUPPLY_PROMPT_* caps), not the budget."
    )


def test_cascade_prompt_size_does_not_grow_with_the_parent_pool(db_session):
    """The cap must actually bind: doubling the parent pool past
    MAX_PARENT_POOL must not add a single character to the prompt."""
    at_cap = _assemble(db_session, parent_pool=_parent_pool(MAX_PARENT_POOL))
    over_cap = _assemble(db_session, parent_pool=_parent_pool(MAX_PARENT_POOL * 5))

    assert len(over_cap) == len(at_cap)


def test_system_prompt_alone_leaves_room_for_the_rest():
    """SYSTEM_PROMPT is sent on every stage and is pure overhead for the
    budget above. Kept well under half of it so the company-specific content
    (candidates, tool schema, facts) has somewhere to live."""
    assert estimate_tokens(SYSTEM_PROMPT) < PROMPT_TOKEN_BUDGET // 3


@pytest.mark.parametrize("model", sorted(GROQ_TPM_CEILING))
def test_budget_is_under_every_model_ceiling(model):
    """The whole point: the prompt must fit BOTH models, so the ladder can be
    ordered on schema quality rather than on prompt size."""
    assert PROMPT_TOKEN_BUDGET < GROQ_TPM_CEILING[model]
