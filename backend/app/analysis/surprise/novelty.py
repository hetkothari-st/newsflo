"""TASK 5.4 -- `novelty_score = 1 - max cosine similarity to prior events`.

DETERMINISTIC TOKEN OVERLAP, NOT AN EMBEDDING. The spec says "cosine
similarity"; it does not say against what representation, and the choice
matters more than it looks:

  * an embedding means a model call, which means a network hop on the critical
    path of a 90-second SLO, a cost per event, and a score that changes when
    the vendor updates the model -- for a number whose only job is to rank a
    feed and decide whether to show a badge;
  * token-count cosine is reproducible forever, costs nothing, and is
    explainable to the person who asks why two stories were called the same.

Short tokens are dropped (`min_token_length`, deployed at 4). Without that,
"the" and "from" alone give two unrelated stories a non-zero similarity, and
every novelty score drifts down by a constant nobody can account for.
"""
import re
from typing import Mapping, Sequence

from app.analysis.surprise.config import SurpriseConfig, load_surprise_config

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenise(text: str, *, min_token_length: int) -> Mapping[str, int]:
    counts: dict[str, int] = {}
    for token in _TOKEN.findall(str(text or "").lower()):
        if len(token) < min_token_length:
            continue
        counts[token] = counts.get(token, 0) + 1
    return counts


def cosine(left: Mapping[str, int], right: Mapping[str, int]) -> float:
    if not left or not right:
        return 0.0
    shared = set(left) & set(right)
    dot = sum(left[token] * right[token] for token in shared)
    if dot == 0:
        return 0.0
    left_norm = sum(value * value for value in left.values()) ** 0.5
    right_norm = sum(value * value for value in right.values()) ** 0.5
    return dot / (left_norm * right_norm)


def novelty_score(event_text: str, prior_texts: Sequence[str] = (), *,
                  config: SurpriseConfig | None = None) -> float:
    """1.0 when nothing in the prior window looks like this, 0.0 when the same
    story already ran. No prior events means fully novel -- which is the
    literal truth about a window that contains nothing."""
    config = config or load_surprise_config()
    subject = tokenise(event_text, min_token_length=config.min_token_length)
    if not prior_texts:
        return 1.0
    closest = max(
        (cosine(subject, tokenise(prior, min_token_length=config.min_token_length))
         for prior in prior_texts), default=0.0)
    return max(0.0, min(1.0, 1.0 - closest))
