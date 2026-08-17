"""`benchmark_impact_graph._path_recall` scores against the PERSISTED node
vocabulary, not a reimplementation of it.

The runner used to carry its own `_norm(name) = name.lower().replace(" ","_")`
-- the pre-snake only, none of the phrase-merge / singular / direction rules
the engine actually applies at the write choke point. Fixture path steps in
`benchmarks/impact_events.json` are written in human vocabulary
("lending_rates", "consumer_spending"), and the engine persists those chains
as `interest_rate*` / `consumer_demand*`. Neither string is a substring of
the other in either direction, so the fuzzy `label in n or n in label` rescue
also fails and the step scored as MISSING.

Consequence, which is why this is not cosmetic: path recall was understated
on exactly the rate-change and consumption chains, and path recall is one of
the numbers the shadow diff uses to decide whether to flip
`IMPACT_ENGINE_V4_STRICT`.
"""
from benchmark_impact_graph import _path_recall


def test_path_recall_matches_a_step_the_engine_normalizes_away():
    """`lending_rates` is persisted as `interest_rate` (a phrase merge plus a
    singularization); `emi_costs` as `emi_cost`."""
    edges = [{"parent_id": "interest_rate_down", "child_id": "emi_cost"}]
    assert _path_recall([["lending_rates", "emi_costs"]], edges) == 1.0


def test_path_recall_matches_the_consumption_chain_too():
    """`consumer_spending` -> `consumer_demand` is the second phrase merge the
    old `_norm` could not see."""
    edges = [{"parent_id": "consumer_demand_down", "child_id": "discretionary_volume"}]
    assert _path_recall(
        [["consumer_spending", "discretionary_volumes"]], edges) == 1.0


def test_path_recall_still_scores_a_genuinely_absent_chain_as_missing():
    """The anti-vacuity half: normalizing both sides must not turn the metric
    into one that always passes."""
    edges = [{"parent_id": "interest_rate_down", "child_id": "emi_cost"}]
    assert _path_recall([["monsoon_above_normal", "agrochemical_volume"]],
                        edges) == 0.0


def test_path_recall_is_unchanged_on_a_chain_that_needed_no_rewrite():
    edges = [{"parent_id": "crude_price_up", "child_id": "aviation_fuel_cost"}]
    assert _path_recall([["crude_price_up", "aviation_fuel_cost"]], edges) == 1.0
    assert _path_recall([], edges) == 1.0


def test_the_runner_holds_no_normalization_of_its_own():
    """R4: the reimplementation is DELETED, not wrapped. `_norm` is gone and
    the module reads the engine's transform directly."""
    import benchmark_impact_graph as runner

    assert not hasattr(runner, "_norm")
