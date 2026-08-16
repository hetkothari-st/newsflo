"""The closed value sets the ledger's text columns accept (spec §4.1).

SQLite has no enum type, so these are enforced in the write path
(`app.ledger.review`) rather than by the schema. A value outside a set is
REFUSED, never normalised -- a silent normalisation is a guess about what
the reviewer meant.

`exposure_tag` is the one deliberately open field here: its closed
vocabulary is `config/exposure_tags.yaml`, which spec §6.1 assigns to
PHASE 3. Until that file exists, Phase 1 validates only the SHAPE of a tag
(`family:leaf`) so the ledger cannot fill with free text, and records in
DATA_GAPS.md that the vocabulary itself is not yet closed.
"""
import re

EXPOSURE_KINDS = (
    "INPUT_COST", "REVENUE_REALIZATION", "VOLUME_DEMAND", "FX_TRANSACTION",
    "FX_TRANSLATION", "INTEREST_RATE", "REGULATORY", "LOGISTICS_ENERGY",
    "CUSTOMER_CONCENTRATION",
)
BASE_KINDS = ("COGS", "REVENUE", "EBITDA", "TOTAL_COST", "DEBT", "OPEX")
MEASUREMENTS = ("FILED", "DISCLOSED_CALL", "ESTIMATED", "MODELLED")
SOURCE_TYPES = ("ANNUAL_REPORT", "QUARTERLY", "EXCHANGE_FILING", "EARNINGS_CALL",
                "REGULATOR", "EXCHANGE_DATA")
MODIFIER_KINDS = ("HEDGE", "PASS_THROUGH", "CONTRACT_FLOOR", "PRICE_CAP",
                  "SUBSIDY_SHARE", "WINDFALL_LEVY", "TAKE_OR_PAY", "FORMULA_PRICING")
CURVE_BASES = ("DISCLOSED_CALL", "FILED", "ESTIMATED", "SECTOR_MEDIAN")
PROPOSAL_STATUSES = ("PENDING_REVIEW", "APPROVED", "REJECTED", "REJECTED_UNVERBATIM")

_TAG_SHAPE = re.compile(r"^[a-z][a-z0-9_]*:[a-z0-9_]+$")


class VocabularyError(ValueError):
    """A value outside a closed set."""


def check(value, allowed: tuple[str, ...], field: str) -> str:
    if value not in allowed:
        raise VocabularyError(f"{field}: {value!r} is not one of {allowed}")
    return str(value)


def check_exposure_tag(value) -> str:
    """Shape only -- see the module docstring. Phase 3 closes the set."""
    if not isinstance(value, str) or not _TAG_SHAPE.match(value):
        raise VocabularyError(
            f"exposure_tag: {value!r} is not of the form 'family:leaf' "
            "(spec §6.1); the closed vocabulary itself arrives in Phase 3")
    return value
