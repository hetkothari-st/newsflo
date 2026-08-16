"""TASK 0.2 tests -- the reducer is a PURE function.

docs/v5/01_PHASE_0_canonical_truth.md TESTS/test_reducer_purity.py:
  * reducer imports no I/O modules (ast scan of imports)
  * property test: 10_000 random permutations of a signal set produce
    byte-identical CompanyImpact
  * reducer given identical input twice returns equal objects

DEVIATION (recorded in the phase 0 report): the phase file names hypothesis
for the property test. `hypothesis` is NOT installed in this repo and adding
a dependency for one test is a worse trade than the equivalent, fully
deterministic formulation used here -- a seeded `random.Random` shuffling
the same signal set 10_000 times. The assertion the phase file asks for
(order-independence at 10k permutations) is the one made.
"""
import ast
import json
import random
from pathlib import Path

import pytest

from tests.phase0 import fixtures

APP = Path(__file__).resolve().parents[2] / "app"
CORE = APP / "core"

# The pure surface. `config_loader.py` (reads gates.yaml) and
# `impact_writer.py` (the reducer's DB writer) are deliberately impure and
# are NOT importable from any module below -- proven by
# test_pure_modules_do_not_import_the_impure_ones.
PURE_MODULES = ("signals.py", "reducer.py", "gates.py", "claims.py",
                "signal_adapters.py")
IMPURE_MODULES = ("config_loader.py", "impact_writer.py")

# Anything that touches a socket, a file, a clock, a random source or the ORM.
FORBIDDEN_IMPORT_ROOTS = {
    "sqlalchemy", "httpx", "requests", "urllib", "socket", "http",
    "anthropic", "openai", "groq", "yaml", "os", "pathlib", "subprocess",
    "random", "time", "sqlite3", "pickle", "shutil", "tempfile",
}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
                roots.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
            roots.add(node.module)
    return roots


@pytest.mark.parametrize("module", PURE_MODULES)
def test_pure_core_modules_import_no_io_modules(module):
    roots = _imported_roots(CORE / module)
    forbidden = {r for r in roots if r in FORBIDDEN_IMPORT_ROOTS}
    assert not forbidden, (
        f"app/core/{module} imports I/O modules {sorted(forbidden)} -- the "
        "reducer surface must be pure (no network, no disk, no clock, no "
        "unseeded randomness, no ORM)")


@pytest.mark.parametrize("module", PURE_MODULES)
def test_pure_core_modules_import_no_app_module_outside_core(module):
    roots = _imported_roots(CORE / module)
    outside = {r for r in roots
               if r.startswith("app.") and not r.startswith("app.core")}
    assert not outside, (
        f"app/core/{module} imports {sorted(outside)} -- the pure core may "
        "only depend on itself and the standard library")


@pytest.mark.parametrize("module", PURE_MODULES)
def test_pure_modules_do_not_import_the_impure_ones(module):
    roots = _imported_roots(CORE / module)
    banned = {f"app.core.{m[:-3]}" for m in IMPURE_MODULES}
    assert not (roots & banned), (
        f"app/core/{module} imports the impure sibling(s) "
        f"{sorted(roots & banned)}; that would drag disk/DB access back into "
        "the pure surface")


def test_reducer_reads_no_clock():
    """Purity is not only about imports: a `datetime.now()` anywhere in the
    reducer would make the same input produce different output."""
    source = (CORE / "reducer.py").read_text(encoding="utf-8")
    for forbidden in ("datetime.now", "utcnow", "time.time", "uuid4", "uuid1"):
        assert forbidden not in source, (
            f"app/core/reducer.py contains `{forbidden}` -- the reducer must "
            "not read a clock or draw entropy")


def test_reducer_output_is_byte_identical_across_10k_permutations():
    from app.core.reducer import reduce_company_impact, serialize_company_impact

    config = fixtures.reducer_config()
    signal_set = fixtures.signals(fixtures.PRIMARY_COMPANY_ID)
    assert len(signal_set) >= 5, "fixture signal set is too small to permute"

    baseline = json.dumps(
        serialize_company_impact(reduce_company_impact(signal_set, config)),
        sort_keys=True).encode()

    rng = random.Random(20260817)
    shuffled = list(signal_set)
    for _ in range(10_000):
        rng.shuffle(shuffled)
        got = json.dumps(
            serialize_company_impact(reduce_company_impact(shuffled, config)),
            sort_keys=True).encode()
        assert got == baseline, (
            "reducer output changed under a permutation of the SAME signal "
            "set -- the reducer is order-dependent")


def test_reducer_returns_equal_objects_for_identical_input():
    from app.core.reducer import reduce_company_impact

    config = fixtures.reducer_config()
    signal_set = fixtures.signals(fixtures.PRIMARY_COMPANY_ID)
    assert reduce_company_impact(signal_set, config) == \
           reduce_company_impact(signal_set, config)


def test_decision_trace_id_is_derived_not_drawn():
    """Two runs over the same signals must yield the SAME trace id (it is a
    content hash), and a different signal set must yield a different one."""
    from app.core.reducer import reduce_company_impact

    config = fixtures.reducer_config()
    primary = reduce_company_impact(
        fixtures.signals(fixtures.PRIMARY_COMPANY_ID), config)
    primary_again = reduce_company_impact(
        fixtures.signals(fixtures.PRIMARY_COMPANY_ID), config)
    remote = reduce_company_impact(
        fixtures.signals(fixtures.REMOTE_COMPANY_ID), config)

    assert primary.decision_trace_id == primary_again.decision_trace_id
    assert primary.decision_trace_id != remote.decision_trace_id


def test_reducer_rejects_a_signal_set_spanning_two_companies():
    """One CompanyImpact is one company's truth. Mixing companies in one
    call is a caller bug, not something to silently pick a winner for."""
    from app.core.reducer import ReducerInputError, reduce_company_impact

    with pytest.raises(ReducerInputError):
        reduce_company_impact(fixtures.signals(), fixtures.reducer_config())


def test_ambiguous_entity_resolution_rejects():
    from app.core.reducer import reduce_company_impact
    from app.core.signals import make_signal

    config = fixtures.reducer_config()
    signal_set = list(fixtures.signals(fixtures.PRIMARY_COMPANY_ID))
    signal_set = [s for s in signal_set if s.kind != "ENTITY_RESOLUTION"]
    signal_set.append(make_signal(
        event_id=fixtures.EVENT_ID, company_id=fixtures.PRIMARY_COMPANY_ID,
        stage="ENTITY", kind="ENTITY_RESOLUTION",
        payload={"_fixture": True, "ticker": "FIXCO1.NS", "isin": None,
                 "resolution": "AMBIGUOUS", "entity_status": "ACTIVE"},
        created_by="fixture:entity_resolver",
        analysis_version=fixtures.ANALYSIS_VERSION,
        created_at=fixtures.FIXTURE_CREATED_AT))

    impact = reduce_company_impact(signal_set, config)
    assert impact.publication_tier == "REJECTED"
    assert impact.rejection_reason == "ENTITY_AMBIGUOUS"


# --- fix round 1 ------------------------------------------------------------

def _modifier_signal(applies_to, modifier_id="FIXTURE_UNMATCHED"):
    from app.core.signals import make_signal

    return make_signal(
        event_id=fixtures.EVENT_ID, company_id=fixtures.PRIMARY_COMPANY_ID,
        stage="POLICY", kind="MODIFIER",
        payload={"_fixture": True, "modifier_id": modifier_id,
                 "effect": "BLOCK", "applies_to_channel_id": applies_to},
        created_by="fixture:policy_registry",
        analysis_version=fixtures.ANALYSIS_VERSION,
        created_at=fixtures.FIXTURE_CREATED_AT)


def test_a_modifier_that_matches_no_channel_is_not_recorded_as_applied():
    """It never touched anything, so claiming it was applied is a small lie
    in the audit trail -- and the policy_modifiers list is exactly what a
    postmortem reads to explain a number."""
    from app.core.reducer import reduce_company_impact

    signals = list(fixtures.signals(fixtures.PRIMARY_COMPANY_ID))
    signals.append(_modifier_signal("no_such_channel"))
    impact = reduce_company_impact(signals, fixtures.reducer_config())

    assert "FIXTURE_UNMATCHED" not in impact.policy_modifiers_applied
    assert "FIXTURE_UNMATCHED" in impact.policy_modifiers_unmatched
    # ...and it changed nothing about the outcome.
    assert impact.net_effect == reduce_company_impact(
        fixtures.signals(fixtures.PRIMARY_COMPANY_ID),
        fixtures.reducer_config()).net_effect


def test_a_modifier_that_matches_a_channel_is_recorded_as_applied():
    from app.core.reducer import reduce_company_impact

    signals = list(fixtures.signals(fixtures.PRIMARY_COMPANY_ID))
    signals.append(_modifier_signal("input_cost_crude", "FIXTURE_MATCHED"))
    impact = reduce_company_impact(signals, fixtures.reducer_config())

    assert "FIXTURE_MATCHED" in impact.policy_modifiers_applied
    assert "FIXTURE_MATCHED" not in impact.policy_modifiers_unmatched
    blocked = [c for c in impact.channels if c["channel_id"] == "input_cost_crude"]
    assert blocked and blocked[0]["material"] is False


def test_the_unmatched_modifier_list_is_serialized():
    from app.core.reducer import reduce_company_impact, serialize_company_impact

    signals = list(fixtures.signals(fixtures.PRIMARY_COMPANY_ID))
    signals.append(_modifier_signal("no_such_channel"))
    payload = serialize_company_impact(
        reduce_company_impact(signals, fixtures.reducer_config()))
    assert payload["fundamental"]["policy_modifiers_unmatched"] == ["FIXTURE_UNMATCHED"]
    assert payload["fundamental"]["policy_modifiers_applied"] == ["FIXTURE_PRICE_FREEZE"]
