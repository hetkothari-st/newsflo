"""V5 PHASE 2 -- THE SENSITIVITY ENGINE (spec §5).

Materiality stops being a word a model chose and becomes a number computed
from ledger rows, with an uncertainty band and an attribution of where the
uncertainty comes from.

    company_exposure row  (Phase 1, human-approved, sourced)
        + a shock
        + parameters resolved from the ledger        -> ChannelResult
    ChannelResults + EBITDA_ttm  -> Monte Carlo      -> MaterialityResult
    MaterialityResult                                -> CHANNEL signals
    CHANNEL signals              -> the Canonical Reducer (Phase 0)

WHAT THIS PACKAGE MAY NOT DO, enforced by `tests/phase2`:

  * import a model provider, define a prompt, or name a model. No LLM
    assigns materiality, confidence or magnitude on this path;
  * write anything. It reads the ledger; the review console remains the only
    writer of `company_exposure`;
  * read a clock. Every caller supplies `as_of`, so a run is reproducible;
  * default a missing parameter. `resolve_param` has exactly three outcomes
    and the third is `InsufficientParameterData`. A channel that cannot be
    computed is not a channel.

THE PRECONDITION, STATED HONESTLY. The Tier 1 ledger is empty. Everything
here has been exercised on obviously fake `_fixture`-marked rows in test
databases only; it has never seen a real filing. See DATA_GAPS.md §6.
"""
