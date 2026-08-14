"""Blueprint §24 -- the deterministic consistency gate.

One pure function over an alert-shaped dict, run at BOTH boundaries the
blueprint names: "before persistence and before serving". Nothing here
touches the DB, an LLM or `settings` -- the caller resolves the shape, this
module only judges it, which is what lets the same rules run in the
pipeline, in a serializer and in a test with no fixtures at all.

The shape (every key optional except `companies`):

```python
{
  "companies": [
      {"ticker": "OIL.NS", "economic_effect": "negative", "direction": "bearish",
       "display_tier": "primary", "channel_effects": ["positive"]},
  ],
  "headline_ticker": "ONGC.NS",       # None when the caller has no headline
  "headline_tier_source": "primary",  # optional self-declaration, checked
}
```

Returns a list of violation strings; EMPTY means consistent. Strings, not
codes-with-payloads, because both callers do the same two things with them:
log them verbatim and refuse to publish. Each begins with the ticker (or
`HEADLINE`) so a postmortem can tell WHICH row poisoned the alert.

What it deliberately does NOT check:

* `market reaction != fundamental impact` (§24's fourth line) -- that
  separation is enforced structurally (app.market.measure writes its own
  columns and app.pipeline never lets a measured move touch
  economic_effect), so there is no shared field here to compare.
* `section effect = company economic effect` -- sections are assembled
  AFTER persistence from these same rows (T5); checking rows is checking
  sections, and this module never sees a section.
"""
from __future__ import annotations

from app.analysis.impact_graph.publication_gate import (
    DIRECTION_FROM_EFFECT,
    TIER_EXCLUDED,
    TIER_MACRO_CONTEXT,
    TIER_PRIMARY,
    TIER_SECONDARY_RIPPLE,
    is_secondary_tier,
    validate_net_effect,
)

# Every tier a persisted row may legally carry, INCLUDING the legacy
# spellings (`is_secondary_tier` owns those) -- this gate also runs
# pre-serve over rows written before the rename, and reporting the whole
# pre-migration corpus as violations would block exactly the alerts it is
# supposed to protect.
KNOWN_TIERS = (TIER_PRIMARY, TIER_SECONDARY_RIPPLE, TIER_MACRO_CONTEXT, TIER_EXCLUDED)

NET_EFFECT_CONTRADICTION = "NET_EFFECT_CONTRADICTION"
DIRECTION_NOT_DERIVED = "DIRECTION_NOT_DERIVED"
UNKNOWN_ECONOMIC_EFFECT = "UNKNOWN_ECONOMIC_EFFECT"
UNKNOWN_DISPLAY_TIER = "UNKNOWN_DISPLAY_TIER"
HEADLINE_NOT_IN_PRIMARY_SET = "HEADLINE_NOT_IN_PRIMARY_SET"
HEADLINE_NOT_IN_SECONDARY_SET = "HEADLINE_NOT_IN_SECONDARY_SET"
HEADLINE_TIER_SOURCE_MISMATCH = "HEADLINE_TIER_SOURCE_MISMATCH"


def _net_effect_violation(effect: str, channel_effects: list) -> str | None:
    """§24's net-effect check, at the severity the DATA can actually
    support.

    `validate_net_effect` (§4, publication_gate) is the primitive and is
    called first -- when it passes, nothing further is asked. When it
    fails, there are two very different shapes underneath it:

    1. **Unsupported claim** -- the company's own effect has ZERO channels
       on its side. Oil India: company NEGATIVE, every validated channel
       POSITIVE. Nothing the analysis produced supports what it published.
       BLOCKED.
    2. **Acknowledged offset** -- the claim IS supported (at least one
       channel on its own side) and an opposing channel is also listed.
       §4's rule is "no MATERIAL negative", and channel materiality is not
       modelled anywhere: `positive_channels`/`negative_channels` are plain
       sentences with no weight attached. Blocking here would block the
       system's own correct output -- a fertiliser producer whose subsidy
       realisation lags cheaper feedstock is NEGATIVE with a real, minor
       positive channel, and the curated regression corpus scores exactly
       that shape as ground truth. Treating "an opposing channel exists"
       as a contradiction would refuse every honest offsetting analysis
       and, worse, teach the upstream stages to stop listing the opposing
       channel at all. NOT blocked.

    `mixed` keeps the strict rule in both directions: mixed is a claim
    about BOTH sides existing, so a missing side is an unsupported claim,
    not an offset.
    """
    if validate_net_effect(effect, channel_effects) is None:
        return None
    channels = [str(value or "").strip().lower() for value in (channel_effects or [])]
    if effect == "positive":
        supporting = sum(1 for value in channels if value in ("positive", "mixed"))
    elif effect == "negative":
        supporting = sum(1 for value in channels if value in ("negative", "mixed"))
    else:
        supporting = 0                       # mixed / unknown: strict
    return NET_EFFECT_CONTRADICTION if supporting == 0 else None


class ConsistencyError(Exception):
    """Raised at the persistence boundary when §24 finds ANY violation.

    Publication is blocked, not repaired: a contradiction means the system
    does not know which of two claims is true, and silently picking one is
    how the Oil India card shipped. The caller (app.pipeline's never-fail
    wrapper) turns this into ANALYSIS_FAILED + the logged violations, which
    is the "audit decision" §24 requires.
    """

    def __init__(self, violations: list[str]):
        self.violations = list(violations)
        super().__init__("; ".join(self.violations) or "consistency violation")


def check_alert_consistency(alert_like: dict) -> list[str]:
    """Every §24 check this module can answer from row-level truth alone.
    Empty list = consistent. Never raises on a malformed shape -- a missing
    key is reported as a violation, not an exception, because a serializer
    that forgot a field must not be able to crash the request it is
    validating."""
    violations: list[str] = []
    primary_tickers: list[str] = []
    secondary_tickers: list[str] = []

    for company in (alert_like.get("companies") or []):
        ticker = str(company.get("ticker") or "?")
        effect = str(company.get("economic_effect") or "").strip().lower()
        direction = str(company.get("direction") or "").strip().lower()
        tier = str(company.get("display_tier") or "").strip()
        channel_effects = list(company.get("channel_effects") or [])

        # (1) company effect vs its own validated channels. An EMPTY
        # channel list is silence, not a contradiction: validate_net_effect
        # rejects it (correctly -- nothing supports the claim), but at the
        # alert level "the model never decomposed this company into
        # channels" is the common, honest case and blocking it would fail
        # nearly every alert. The Oil India shape -- channels present, all
        # pointing the other way -- is exactly what remains caught.
        if channel_effects and _net_effect_violation(effect, channel_effects) is not None:
            violations.append(
                f"{ticker}: {NET_EFFECT_CONTRADICTION} economic_effect={effect!r} "
                f"channels={sorted(str(c).strip().lower() for c in channel_effects)}"
            )

        # (2) direction is DERIVED (§4). There is exactly one map; a row
        # whose direction is not the one that map produces was written by
        # something that thinks direction is its own field.
        #
        # An ABSENT effect is not a violation, it is a legacy-shaped row:
        # `economic_effect` is nullable and the whole pre-v3 corpus has
        # none, so there is nothing to derive a direction from and nothing
        # to contradict. A PRESENT effect outside the closed vocabulary is
        # a different thing entirely -- that is a value nobody can act on.
        expected_direction = DIRECTION_FROM_EFFECT.get(effect)
        if not effect:
            pass
        elif expected_direction is None:
            violations.append(f"{ticker}: {UNKNOWN_ECONOMIC_EFFECT} economic_effect={effect!r}")
        elif direction != expected_direction:
            violations.append(
                f"{ticker}: {DIRECTION_NOT_DERIVED} direction={direction!r} "
                f"expected={expected_direction!r} from economic_effect={effect!r}"
            )

        # (3) publication tier is inside the closed vocabulary.
        if tier not in KNOWN_TIERS and not is_secondary_tier(tier):
            violations.append(f"{ticker}: {UNKNOWN_DISPLAY_TIER} display_tier={tier!r}")

        if tier == TIER_PRIMARY:
            primary_tickers.append(ticker)
        elif is_secondary_tier(tier):
            secondary_tickers.append(ticker)

    # (4) headline company subset rule (§24 + ruling R1). The headline is
    # the alert's single loudest claim, so it must come from the strongest
    # tier the alert actually has: PRIMARY, or -- when there is no primary
    # company at all -- the secondary/ripple set. A macro_context row is
    # never headline-eligible (§7: macro context must not become a company
    # impact), which falls out of it belonging to neither set.
    headline = alert_like.get("headline_ticker")
    if headline:
        headline = str(headline)
        eligible = primary_tickers or secondary_tickers
        source = "primary" if primary_tickers else "secondary"
        if headline not in eligible:
            code = (HEADLINE_NOT_IN_PRIMARY_SET if primary_tickers
                    else HEADLINE_NOT_IN_SECONDARY_SET)
            violations.append(
                f"HEADLINE: {code} headline_ticker={headline!r} eligible={sorted(eligible)}"
            )
        declared = alert_like.get("headline_tier_source")
        if declared and str(declared).strip().lower() != source:
            violations.append(
                f"HEADLINE: {HEADLINE_TIER_SOURCE_MISMATCH} declared={str(declared)!r} "
                f"actual={source!r}"
            )

    return violations
