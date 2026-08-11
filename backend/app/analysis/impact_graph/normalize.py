"""Deterministic economic-node normalization (token-opt spec §4/P7).

Equivalent economic concepts must collapse to ONE canonical node id
BEFORE any dedup/gate/LLM decision -- "crude price rises", "oil price
increase" and "higher crude prices" are the same branch, and a synonym
slipping through creates a duplicate subtree whose every call is wasted
money. Pure string rules; no LLM ever spends tokens on this.

Pipeline: snake tokens -> drop noise words -> singularize -> extract
direction words (anywhere, leading or trailing) -> phrase merges on
token boundaries -> re-append one canonical _up/_down suffix.
"""
import re

_NOISE = {"the", "a", "an", "of", "in", "on", "for", "to", "and", "its", "their"}

_UP = {"increase", "increased", "increases", "rise", "rises", "risen", "rising",
       "surge", "surges", "surged", "spike", "spikes", "spiked", "higher", "up",
       "hike", "hikes", "hiked", "growth", "strengthen", "strengthens",
       "strengthening", "strengthened", "jump", "jumps", "jumped"}
_DOWN = {"decrease", "decreased", "decreases", "fall", "falls", "fallen",
         "falling", "drop", "drops", "dropped", "decline", "declines",
         "declined", "lower", "down", "cut", "cuts", "weaken", "weakens",
         "weakening", "weakened", "slump", "slumps", "slumped"}

# Simple plural singularization exceptions (token -> canonical token).
_SINGULAR_EXCEPTIONS = {"gas": "gas", "logistics": "logistics", "economics": "economics"}

# Token-boundary phrase merges, applied to the "_"-joined token string.
# (?:^|_) / (?=_|$) are the underscore-aware word boundaries -- plain \b
# does not fire inside snake_case.
_PHRASE_RULES = [
    (r"(?:^|_)crude_oil(?=_|$)", "_crude"),
    (r"(?:^|_)oil_price(?=_|$)", "_crude_price"),
    (r"(?:^|_)petrol(?:eum)?_price(?=_|$)", "_crude_price"),
    (r"(?:^|_)borrowing_cost(?=_|$)", "_financing_cost"),
    (r"(?:^|_)funding_cost(?=_|$)", "_financing_cost"),
    (r"(?:^|_)interest_expense(?=_|$)", "_financing_cost"),
    (r"(?:^|_)lending_rate(?=_|$)", "_interest_rate"),
    (r"(?:^|_)repo_rate(?=_|$)", "_interest_rate"),
    (r"(?:^|_)fx(?=_|$)", "_currency"),
    (r"(?:^|_)forex(?=_|$)", "_currency"),
    (r"(?:^|_)rupee(?=_|$)", "_currency"),
    (r"(?:^|_)consumer_spending(?=_|$)", "_consumer_demand"),
    (r"(?:^|_)consumption(?=_|$)", "_consumer_demand"),
    (r"(?:^|_)household_spending(?=_|$)", "_consumer_demand"),
    (r"(?:^|_)jet_fuel(?=_|$)", "_aviation_fuel"),
    (r"(?:^|_)atf(?=_|$)", "_aviation_fuel"),
]


def _singular(token: str) -> str:
    if token in _SINGULAR_EXCEPTIONS:
        return _SINGULAR_EXCEPTIONS[token]
    if len(token) > 3 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def normalize_node_id(raw: str) -> str:
    """Canonical snake_case node id. Deterministic and idempotent."""
    tokens = [t for t in re.split(r"[^a-z0-9]+", (raw or "").strip().lower()) if t]
    direction = ""
    kept: list[str] = []
    for token in tokens:
        if token in _NOISE:
            continue
        if token in _UP:
            direction = direction or "up"
            continue
        if token in _DOWN:
            direction = direction or "down"
            continue
        kept.append(_singular(token))
    text = "_".join(kept)
    for pattern, replacement in _PHRASE_RULES:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"_+", "_", text).strip("_")
    if direction and text:
        # idempotency: an already-suffixed id keeps a single suffix
        if not (text.endswith("_up") or text.endswith("_down")):
            text = f"{text}_{direction}"
    return text or "node"
