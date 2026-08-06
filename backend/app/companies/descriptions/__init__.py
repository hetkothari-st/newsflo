"""Sourced company descriptions from Wikipedia.

Subsystem B replaced the LLM-written ``business_desc`` with sourced facts
and hardcoded the field to ``None`` in every serializer, because an
unattributable sentence about a company is exactly the "bogus, hallucinated
data" this whole effort exists to remove. This package puts the sentence
back -- but only when it can be attributed to a specific revision of a
specific article that PROVES it is about this company.

The proof is the point. Nothing here matches on company names. Wikipedia
infoboxes carry the exchange identifiers as templates -- ``{{BSE|532540}}``,
``{{NSE|TCS}}``, ``{{ISIN|...|INE467B01029}}`` -- which join exactly to the
``listings`` table. So the direction of resolution is ARTICLE -> COMPANY,
never company -> article: an article is only accepted when the codes inside
it resolve to one and only one company we already know about. A wrong
article cannot pass, because a wrong article does not contain our code.

That matters here specifically. A name-similarity approach was already
tried on this codebase for entity resolution and produced confident wrong
attributions (`Air India` -> Tenneco Clean Air India) for 488 of 718
tokens. Descriptions are more dangerous than tickers, not less: a wrong
one-liner reads as authoritative and nobody double-checks it.

Layout mirrors app.companies.universe -- fetchers (network only) write a
dated snapshot, extract (pure) reads it, loader writes the DB.
"""


def sourced_description(company) -> tuple[str | None, str | None]:
    """``(text, source_url)`` for a company, or ``(None, None)``.

    The gate is the URL, not the text. Rows still holding the legacy
    LLM-written ``business_desc`` have no source and stay withheld, exactly
    as they have been since subsystem B -- this function is what lets the
    sourced ones through without resurrecting the invented ones.

    Both halves are returned together on purpose. Wikipedia text is CC
    BY-SA: displaying it requires attributing it, so a caller that wants the
    sentence is handed the credit it owes in the same breath.
    """
    url = getattr(company, "business_desc_source_url", None)
    if not url:
        return None, None
    return company.business_desc, url
