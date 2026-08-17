"""ONE definition of "this event is broad", and one declared delta.

THE DEFECT THIS PINS. Two hand-maintained frozensets named almost the same
thing -- `app.analysis.cascade.BROAD_EVENT_TYPES` (10 entries) and
`app.config.IMPACT_BROAD_EVENT_TYPES` (11) -- with a comment in config.py
claiming they were "the same set the legacy cascade used for fan-out
gating". They were not. They had drifted by `geopolitics`, silently, and
nothing failed.

The two ARE allowed to differ: one is a precision control (fan-out invents
companies) and the other is a cost control (triage spends tokens). What is
banned is differing WITHOUT SAYING SO, so the delta is a named constant and
these tests assert it has not grown, shrunk, or reversed.

NO SERVING BEHAVIOUR IS PINNED HERE beyond the values that were already
deployed -- the consolidation was value-preserving on both sides and the
first two tests say exactly that.
"""
import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


# --- the values that were deployed before the consolidation -----------------
# Copied from the two definition sites as they stood at 00323b0a, so this
# file is an independent record rather than a restatement of the code.
DEPLOYED_FANOUT = frozenset({
    "repo_rate_change", "inflation", "macro_data", "fiscal_policy",
    "monsoon_weather", "crude_oil", "commodity_price", "currency_move",
    "global_rates", "trade_policy",
})
DEPLOYED_IMPACT = DEPLOYED_FANOUT | {"geopolitics"}


def test_fanout_set_is_value_identical_to_what_was_deployed():
    from app.analysis.cascade import BROAD_EVENT_TYPES

    assert BROAD_EVENT_TYPES == DEPLOYED_FANOUT
    assert len(BROAD_EVENT_TYPES) == 10


def test_triage_set_is_value_identical_to_what_was_deployed():
    from app.config import IMPACT_BROAD_EVENT_TYPES

    assert IMPACT_BROAD_EVENT_TYPES == DEPLOYED_IMPACT
    assert len(IMPACT_BROAD_EVENT_TYPES) == 11


def test_the_delta_is_exactly_geopolitics_and_is_declared():
    from app.config import (
        BROAD_FANOUT_EVENT_TYPES, IMPACT_BROAD_EVENT_TYPES,
        IMPACT_BROAD_EXTRA_EVENT_TYPES,
    )

    assert IMPACT_BROAD_EXTRA_EVENT_TYPES == frozenset({"geopolitics"})
    # The triage set is a SUPERSET of the fan-out set. If this ever reverses,
    # something is being fanned out that is not even worth a deep graph.
    assert BROAD_FANOUT_EVENT_TYPES < IMPACT_BROAD_EVENT_TYPES
    assert (IMPACT_BROAD_EVENT_TYPES - BROAD_FANOUT_EVENT_TYPES
            == IMPACT_BROAD_EXTRA_EVENT_TYPES)


def test_cascade_reexports_the_config_object_rather_than_restating_it():
    """Identity, not equality. Two equal frozensets is the state this test
    exists to prevent -- they can be edited apart."""
    from app.analysis import cascade
    from app.config import BROAD_FANOUT_EVENT_TYPES

    assert cascade.BROAD_EVENT_TYPES is BROAD_FANOUT_EVENT_TYPES


# A literal carrying this many of the ten base members is a COPY of the
# vocabulary, not a set that happens to share event-type names with it.
#
# The threshold is 8 rather than 2 because several modules legitimately key
# OTHER decisions by event_type and overlap heavily without restating this
# one -- measured 2026-08-17:
#   reasoning/rulebook.CHAIN_FALLBACK_KEEP_EVENT_TYPES  5/10 (and it carries
#       `government_spending`, which is in neither broad set -- a different
#       question with a different answer);
#   impact_graph/knowledge.EVENT_ARCHETYPES[...]["event_types"]  2/10.
# Both are correct as they stand. Ten-of-ten is the shape that was the bug.
RESTATEMENT_THRESHOLD = 8


def test_no_module_restates_the_broad_event_vocabulary():
    """No second hand-written copy of the vocabulary anywhere under app/.

    `app/config.py` is the one permitted definition site.
    """
    base = set(DEPLOYED_FANOUT)
    offenders = []
    for path in sorted((BACKEND / "app").rglob("*.py")):
        if "__pycache__" in path.parts or path.name == "config.py":
            continue
        source = path.read_text(encoding="utf-8")
        for block in re.findall(r"(?:frozenset\(\{|\{|\[)([^{}\[\]]{0,800}?)(?:\}|\])",
                                source, re.S):
            quoted = set(re.findall(r"[\"']([a-z_]+)[\"']", block))
            hit = quoted & base
            if len(hit) >= RESTATEMENT_THRESHOLD:
                offenders.append((str(path.relative_to(BACKEND)), sorted(hit)))
    assert not offenders, (
        "the broad-event vocabulary is restated outside app/config.py "
        "(%d+ of the %d base members in one literal): %r"
        % (RESTATEMENT_THRESHOLD, len(base), offenders))


def _load_config_isolated(name="app_config_env_probe"):
    """Execute `app/config.py` into a THROWAWAY module object.

    Deliberately NOT `importlib.reload(app.config)`: a reload rebinds
    `sys.modules['app.config']` and mints a new `settings` instance for the
    whole session, while every module that already did `from app.config
    import settings` keeps the old one. That is process-wide state damage
    from one assertion -- it made `tests/test_companies_api.py` fail when run
    after this file and pass in isolation (measured 2026-08-17). This never
    touches `sys.modules`.
    """
    spec = importlib.util.spec_from_file_location(name, BACKEND / "app" / "config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_env_override_reaches_triage_only_and_never_fanout(monkeypatch):
    """An impact-graph COST knob must not widen what the cascade INVENTS."""
    monkeypatch.setenv("IMPACT_BROAD_EVENT_TYPES", "earnings,merger_acquisition")
    probe = _load_config_isolated()

    assert probe.IMPACT_BROAD_EVENT_TYPES == frozenset(
        {"earnings", "merger_acquisition"})
    assert probe.BROAD_FANOUT_EVENT_TYPES == DEPLOYED_FANOUT

    # and the real, already-imported module is untouched by any of this
    import app.config as live

    assert live.IMPACT_BROAD_EVENT_TYPES == DEPLOYED_IMPACT


def test_the_default_when_no_env_override_is_set(monkeypatch):
    monkeypatch.delenv("IMPACT_BROAD_EVENT_TYPES", raising=False)
    probe = _load_config_isolated("app_config_default_probe")

    assert probe.IMPACT_BROAD_EVENT_TYPES == DEPLOYED_IMPACT
    assert probe.BROAD_FANOUT_EVENT_TYPES == DEPLOYED_FANOUT


def test_every_broad_event_type_is_a_real_event_type():
    from app.analysis.schemas import EVENT_TYPES
    from app.config import BROAD_FANOUT_EVENT_TYPES, IMPACT_BROAD_EVENT_TYPES

    unknown = (BROAD_FANOUT_EVENT_TYPES | IMPACT_BROAD_EVENT_TYPES) - set(EVENT_TYPES)
    assert not unknown, unknown
