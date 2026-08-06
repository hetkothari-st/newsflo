"""The ONLY bridge between supply_links and the analysis pipeline: a
capped, sourced prompt block plus extra candidate tickers. Nothing here
writes AlertCompany/ImpactEdge rows, and nothing else in the pipeline
reads SupplyLink -- that one-way flow IS the user-locked no-auto-
attribution guarantee (spec 1, tested by name in test_supply_links).
"""
from app import config
from app.models import Company, SupplyLink

_HEADER = (
    "KNOWN RELATIONSHIPS (sourced from rating documents; historical, not "
    "caused by this news):\n"
)
_TAIL = (
    "\nInclude a counterparty ONLY if THIS news plausibly transmits through "
    "the relationship, and say how. A relationship alone is never a reason."
)
_INSTRUCTION = _HEADER + "{lines}" + _TAIL

_RELATION_LABEL = {"CUSTOMER": "customers", "SUPPLIER": "suppliers"}
_RELATION_RANK = {"CUSTOMER": 0, "SUPPLIER": 1}


def known_relationships_block(session, event_tickers: list[str]) -> tuple[str, list[str]]:
    """Query stored SupplyLink rows for `event_tickers`' companies and
    render the capped KNOWN RELATIONSHIPS block plus the resolved
    counterparties' tickers (for the caller to fold into its own candidate
    list). Empty string + empty list whenever there is nothing to say --
    no event tickers, no matching companies, or no stored links -- so the
    cascade prompt stays byte-identical to before this module existed.
    """
    if not event_tickers:
        return "", []

    companies = session.query(Company).filter(Company.ticker.in_(event_tickers)).all()
    if not companies:
        return "", []
    company_by_id = {c.id: c for c in companies}

    links = (
        session.query(SupplyLink)
        .filter(SupplyLink.company_id.in_(list(company_by_id.keys())))
        .all()
    )
    if not links:
        return "", []

    counterparty_ids = {l.counterparty_company_id for l in links if l.counterparty_company_id}
    counterparty_companies = {}
    if counterparty_ids:
        for c in session.query(Company).filter(Company.id.in_(counterparty_ids)).all():
            counterparty_companies[c.id] = c

    groups: dict[tuple[int, str], list[SupplyLink]] = {}
    for link in links:
        groups.setdefault((link.company_id, link.relation), []).append(link)

    ticker_rank = {ticker: i for i, ticker in enumerate(event_tickers)}
    ordered_keys = sorted(
        groups.keys(),
        key=lambda k: (
            ticker_rank.get(company_by_id[k[0]].ticker, len(event_tickers)),
            _RELATION_RANK.get(k[1], 2),
        ),
    )

    line_texts: list[str] = []
    extras: list[str] = []
    seen_tickers: set[str] = set(event_tickers)

    for key in ordered_keys:
        if len(line_texts) >= config.SUPPLY_PROMPT_MAX_LINES:
            break
        company_id, relation = key
        company = company_by_id[company_id]
        label = _RELATION_LABEL.get(relation, relation.lower())
        group_links = sorted(groups[key], key=lambda l: l.as_of, reverse=True)
        newest = group_links[0]
        prefix = f"- {company.ticker} {label}: "
        suffix = f" [{newest.source_agency} {newest.as_of.isoformat()}]"

        entries: list[str] = []
        pending_extras: list[str] = []
        stop_after_this_group = False
        for link in group_links:
            counterparty = counterparty_companies.get(link.counterparty_company_id)
            entry = (
                f"{link.counterparty_name} ({counterparty.ticker})"
                if counterparty is not None else link.counterparty_name
            )
            candidate_line = prefix + ", ".join(entries + [entry]) + suffix
            # Budget is checked against the HEADER + lines-so-far running
            # total, not the whole formatted block -- the trailing fixed
            # instruction sentence (_TAIL) is a constant appended once at
            # the end regardless, excluded from this per-line budget (see
            # test_block_respects_line_and_char_caps' "+ fixed instruction
            # text" allowance).
            candidate_total_len = (
                len(_HEADER) + sum(len(t) for t in line_texts) + len(line_texts) + len(candidate_line)
            )
            if candidate_total_len > config.SUPPLY_PROMPT_MAX_CHARS and entries:
                # This entry would blow the budget but the group already has
                # at least one entry -- finalize the line as-is and stop
                # adding to ANY further group too (the budget is exhausted).
                stop_after_this_group = True
                break
            entries.append(entry)
            if counterparty is not None:
                pending_extras.append(counterparty.ticker)
            if candidate_total_len > config.SUPPLY_PROMPT_MAX_CHARS:
                # Even a single entry exceeds the budget -- include it (a
                # group must never render with zero counterparties) but stop
                # here entirely.
                stop_after_this_group = True
                break

        if entries:
            line_texts.append(prefix + ", ".join(entries) + suffix)
            for ticker in pending_extras:
                if ticker not in seen_tickers:
                    seen_tickers.add(ticker)
                    extras.append(ticker)

        if stop_after_this_group:
            break

    if not line_texts:
        return "", []

    block = _INSTRUCTION.format(lines="\n".join(line_texts))
    return block, extras
