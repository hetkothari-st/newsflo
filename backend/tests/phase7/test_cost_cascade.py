"""TASK 7.5 tests -- the cost cascade is real, or it is a paragraph.

Spec section 18 makes three claims that are cheap to write and easy to
violate silently. Each one is a test here:

  1. **a 250-candidate pool must not produce 250 frontier calls.** The
     deterministic layers must eliminate >= 90% of candidates before ANY
     model sees one, and `frontier_calls / candidates <= 0.10`. The
     elimination in this file is performed by the DEPLOYED publication gate
     over `config/gates.yaml` -- a fixture that eliminated its own candidates
     would prove nothing about the system;
  2. **static prefix before dynamic suffix.** "Never place dynamic content
     before static content -- it destroys the prefix cache." A prompt builder
     that interleaves them costs money on every call and nothing fails, which
     is why it needs a test rather than a convention;
  3. **the stage-result cache is keyed (stage, input_hash, model_id,
     prompt_version)** and an identical repeat is a hit that costs no call.

The falsifiability control matters more than the assertion: a pool where
NOTHING is eliminated must blow the budget. If it does not, the 0.10
assertion is measuring the fixture, not the cascade.

ZERO REAL CALLS. Every client here is a `ScriptedClient`; the ledger is a
counting wrapper around whatever client it is handed.
"""
import json

import pytest

from tests.phase7.conftest import ScriptedClient, load_fixture

FRONTIER_BUDGET = 0.10
ELIMINATION_FLOOR = 0.90


def _drafts(key="cohorts"):
    from eval.cascade import drafts_from_cohorts

    return drafts_from_cohorts(load_fixture("cascade_candidates.json")[key])


@pytest.fixture()
def gate_config():
    from app.core.config_loader import load_gate_config

    return load_gate_config()


# ---------------------------------------------------------------------------
# the fixture pool itself
# ---------------------------------------------------------------------------

def test_the_fixture_event_really_has_two_hundred_and_fifty_candidates():
    assert len(_drafts()) == 250


def test_the_deployed_gate_eliminates_at_least_ninety_percent_pre_llm(gate_config):
    """Section 18's budget rule, measured against the REAL gate."""
    from eval.cascade import SHORT_CIRCUIT, route_candidates

    run = route_candidates(_drafts(), gate_config)
    eliminated = run.counts[SHORT_CIRCUIT]
    assert eliminated / run.candidates >= ELIMINATION_FLOOR, run.counts


def test_a_short_circuited_candidate_reaches_no_model_at_all(gate_config):
    from eval.cascade import FRONTIER, SHORT_CIRCUIT, SMALL, route_candidates

    run = route_candidates(_drafts(), gate_config)
    for routing in run.routings:
        if routing.tier == SHORT_CIRCUIT:
            assert routing.tier not in (FRONTIER, SMALL)
            assert routing.reason, "an elimination with no reason is not auditable"


def test_frontier_calls_per_candidate_is_at_most_one_tenth(gate_config):
    """The phase file's test, end to end: route the pool, then actually run
    the falsifier on everything routed to the frontier and count the calls
    the ledger saw."""
    from eval.cascade import FRONTIER, route_candidates, run_frontier_stage
    from eval.cost_ledger import CallLedger

    run = route_candidates(_drafts(), gate_config)
    ledger = CallLedger()
    client = ScriptedClient(*[_checklist_response()] * run.counts[FRONTIER])
    run_frontier_stage(run, client=client, ledger=ledger)

    assert ledger.frontier_calls == run.counts[FRONTIER]
    ratio = ledger.frontier_calls / run.candidates
    assert ratio <= FRONTIER_BUDGET, f"{ledger.frontier_calls}/{run.candidates}"
    ledger.assert_within_budget(run.candidates, FRONTIER_BUDGET)


def test_the_budget_assertion_actually_bites(gate_config):
    """THE FALSIFIABILITY CONTROL. A pool the deterministic layers cannot
    reduce must blow the budget."""
    from eval.cascade import FRONTIER, route_candidates
    from eval.cost_ledger import CascadeBudgetExceeded, CallLedger

    run = route_candidates(_drafts("all_frontier_cohorts"), gate_config)
    assert run.counts[FRONTIER] == 250
    ledger = CallLedger()
    for _ in range(run.counts[FRONTIER]):
        ledger.record("FRONTIER", stage="FALSIFIER")
    with pytest.raises(CascadeBudgetExceeded):
        ledger.assert_within_budget(run.candidates, FRONTIER_BUDGET)


def test_only_the_three_section_eighteen_cases_reach_the_frontier(gate_config):
    from eval.cascade import FRONTIER, route_candidates

    run = route_candidates(_drafts(), gate_config)
    reasons = {r.reason for r in run.routings if r.tier == FRONTIER}
    assert reasons <= {"PRIMARY_ELIGIBLE_FALSIFICATION", "MIXED_RESOLUTION",
                       "MARGINAL_AT_GATE_BOUNDARY"}, reasons
    assert "PRIMARY_ELIGIBLE_FALSIFICATION" in reasons
    assert "MIXED_RESOLUTION" in reasons


def test_a_prior_identical_event_short_circuits_to_zero_tokens(gate_config):
    """Rung 1 of the cascade: a deterministic short-circuit costs no tokens,
    whatever the gate would have said."""
    from eval.cascade import SHORT_CIRCUIT, route_candidates

    drafts = _drafts()
    known = tuple(key for key, _ in drafts[:250])
    run = route_candidates(drafts, gate_config, short_circuit_ids=known)
    assert run.counts[SHORT_CIRCUIT] == 250
    assert run.counts["FRONTIER"] == 0
    assert all(r.reason == "DETERMINISTIC_SHORT_CIRCUIT" for r in run.routings)


def test_a_publishable_ripple_is_small_model_work_not_frontier(gate_config):
    from eval.cascade import SMALL, route_candidates

    run = route_candidates(_drafts(), gate_config)
    assert run.counts[SMALL] >= 1
    assert all(r.reason == "PUBLISHED_BELOW_PRIMARY"
               for r in run.routings if r.tier == SMALL)


# ---------------------------------------------------------------------------
# prompt assembly order
# ---------------------------------------------------------------------------

def test_the_falsifier_prompt_puts_the_static_prefix_before_the_dynamic_suffix():
    from app.analysis.falsifier.config import load_falsifier_policy
    from app.analysis.falsifier.prompts import build_prompt_parts
    from eval.prompt_audit import check_prompt_order

    policy = load_falsifier_policy()
    check_prompt_order(
        lambda record: build_prompt_parts(record, policy.checklist,
                                          tuple(policy.severities)),
        [json.dumps({"company": "FIXA", "channel": "fixture_input_cost"}),
         json.dumps({"company": "FIXB", "channel": "fixture_demand"})])


def test_the_entailment_judge_prompt_puts_the_static_prefix_first():
    from app.output.entailment_prompt import build_judge_prompt_parts
    from app.output.firewall import RecordSet
    from eval.prompt_audit import check_prompt_order

    record_set = RecordSet(numerals=(28.0,), entities=frozenset({"FIXA.NS"}),
                           dates=frozenset({"2026-04-30"}))
    check_prompt_order(
        lambda sentence: build_judge_prompt_parts(sentence, record_set),
        ["FIXA.NS carries a crude-linked cost exposure.",
         "FIXA.NS discloses the share in its annual report."])


def test_the_static_prefix_carries_the_rules_and_the_dynamic_suffix_the_event():
    from app.analysis.falsifier.config import load_falsifier_policy
    from app.analysis.falsifier.prompts import build_prompt_parts

    policy = load_falsifier_policy()
    static, dynamic = build_prompt_parts(
        json.dumps({"company": "FIXA"}), policy.checklist,
        tuple(policy.severities))
    assert "ADVERSARY" in static
    assert "FIXA" not in static
    assert "FIXA" in dynamic


def test_the_order_check_catches_a_builder_that_violates_it():
    """The self-test. A check that cannot fail is not a check."""
    from eval.prompt_audit import PromptOrderError, check_prompt_order

    def dynamic_first(payload):
        return (f"RECORD {payload}\nYou are the adversary.", "")

    with pytest.raises(PromptOrderError):
        check_prompt_order(dynamic_first, ["A", "B"])


def test_the_order_check_catches_a_prefix_that_is_not_actually_static():
    from eval.prompt_audit import PromptOrderError, check_prompt_order

    def leaky(payload):
        return (f"You are the adversary. Consider {payload}.", "tail")

    with pytest.raises(PromptOrderError):
        check_prompt_order(leaky, ["A", "B"])


def test_splitting_the_falsifier_prompt_did_not_change_a_byte_of_it():
    """The split is a refactor for cacheability, not a prompt change: a
    changed prompt is a changed model behaviour nobody measured."""
    from app.analysis.falsifier.config import load_falsifier_policy
    from app.analysis.falsifier.prompts import build_prompt, build_prompt_parts

    policy = load_falsifier_policy()
    record = json.dumps({"company": "FIXA"})
    static, dynamic = build_prompt_parts(record, policy.checklist,
                                         tuple(policy.severities))
    assert static + dynamic == build_prompt(record, policy.checklist,
                                            tuple(policy.severities))


# ---------------------------------------------------------------------------
# the stage-result cache
# ---------------------------------------------------------------------------

def test_the_cache_key_is_stage_input_hash_model_id_and_prompt_version():
    from eval.cost_ledger import stage_cache_key

    base = dict(stage="FALSIFIER", input_hash="abc", model_id="m1",
                prompt_version="p1")
    key = stage_cache_key(**base)
    for field in ("stage", "input_hash", "model_id", "prompt_version"):
        changed = dict(base)
        changed[field] = "different"
        assert stage_cache_key(**changed) != key, field


def test_an_identical_repeated_event_is_a_cache_hit_and_costs_no_call():
    from eval.cost_ledger import CallLedger, StageCache

    cache = StageCache()
    ledger = CallLedger()
    scripted = ScriptedClient(_checklist_response())
    client = ledger.wrap(scripted, tier="FRONTIER", stage="FALSIFIER",
                         model_id="fixture-model", prompt_version="fixture-v1",
                         cache=cache)

    first = client.generate("PROMPT-A")
    second = client.generate("PROMPT-A")

    assert first == second
    assert scripted.calls == 1, "the second identical call reached the model"
    assert ledger.frontier_calls == 1
    assert ledger.cache_hits == 1


def test_a_changed_prompt_version_misses_the_cache():
    from eval.cost_ledger import CallLedger, StageCache

    cache = StageCache()
    ledger = CallLedger()
    scripted = ScriptedClient("first", "second")
    v1 = ledger.wrap(scripted, tier="FRONTIER", stage="FALSIFIER",
                     model_id="m", prompt_version="v1", cache=cache)
    v2 = ledger.wrap(scripted, tier="FRONTIER", stage="FALSIFIER",
                     model_id="m", prompt_version="v2", cache=cache)
    assert v1.generate("SAME") == "first"
    assert v2.generate("SAME") == "second"
    assert ledger.cache_hits == 0


def test_a_changed_model_misses_the_cache():
    from eval.cost_ledger import CallLedger, StageCache

    cache = StageCache()
    ledger = CallLedger()
    scripted = ScriptedClient("first", "second")
    a = ledger.wrap(scripted, tier="FRONTIER", stage="FALSIFIER",
                    model_id="model-a", prompt_version="v1", cache=cache)
    b = ledger.wrap(scripted, tier="FRONTIER", stage="FALSIFIER",
                    model_id="model-b", prompt_version="v1", cache=cache)
    a.generate("SAME")
    b.generate("SAME")
    assert ledger.cache_hits == 0


def test_the_ledger_counts_by_tier_and_by_stage():
    from eval.cost_ledger import CallLedger

    ledger = CallLedger()
    ledger.record("FRONTIER", stage="FALSIFIER")
    ledger.record("SMALL", stage="FIREWALL_JUDGE")
    ledger.record("SMALL", stage="FIREWALL_JUDGE")
    assert ledger.frontier_calls == 1
    assert ledger.small_calls == 2
    assert ledger.calls_by_stage["FIREWALL_JUDGE"] == 2
    assert ledger.total_calls == 3


def test_a_cache_hit_is_not_counted_as_a_model_call():
    from eval.cost_ledger import CallLedger

    ledger = CallLedger()
    ledger.record("FRONTIER", stage="FALSIFIER")
    ledger.record("FRONTIER", stage="FALSIFIER", cached=True)
    assert ledger.frontier_calls == 1
    assert ledger.cache_hits == 1


def test_the_ratio_over_zero_candidates_is_none_not_zero():
    from eval.cost_ledger import CallLedger

    assert CallLedger().cascade_ratio(0) is None


def test_the_ledger_refuses_an_unknown_tier():
    from eval.cost_ledger import CallLedger

    with pytest.raises(ValueError):
        CallLedger().record("SUPER_FRONTIER", stage="FALSIFIER")


def test_the_wrapped_client_is_the_only_seam_and_makes_no_client_of_its_own():
    from pathlib import Path

    from tests.phase7.conftest import BACKEND, imported_modules, package_sources

    banned = {"anthropic", "openai", "httpx", "requests", "socket",
              "urllib.request", "google.generativeai", "groq"}
    for path in package_sources(Path(BACKEND) / "eval"):
        assert not (imported_modules(path) & banned), path


def _checklist_response() -> str:
    """A scripted adversary response that answers everything, so the frontier
    stage under test is the CALL COUNT and not the checklist logic (Phase 6
    owns that)."""
    return json.dumps({
        "checklist": [{"question": q, "answerable": True,
                       "answer": "the record set answers this",
                       "cites": ["channels[0].channel_id"]}
                      for q in range(1, 11)],
        "objections": []})
