"""TASK 7.2 -- the harness itself: labels in, V5 records out, metrics both
per stratum and per sector.

The harness runs the V5 canonical path ENTIRELY OFFLINE. It is handed a
STAGE BUNDLE per event -- the same shape Phase 0's fixture uses -- and it
runs the deployed reducer, the deployed gate policy and the deployed section
engine over it. The two stages that would call a model take INJECTED clients
and are simply absent when nobody injects one, so "zero API calls" is a
property of the code rather than of a mock.

IT IS NOT SESSION 0'S SCORER. `scripts/score_baseline.py` scores the V4
system for Gate Zero and reads `alert_companies`; this reads `company_impact`
and the V5 record set. Two scorers, one corpus, both documented -- and a test
here pins that neither imports the other's scoring code.

WHAT CANNOT BE MEASURED IS NAMED, NOT GUESSED. The Gate Zero label schema
(Session 0, unmodified) carries an expected tier, direction, mechanism and
materiality -- and no expected directness, distance, evidence grade or
section. Those four metrics therefore exist as functions, are unit-tested in
test_metrics.py, and are reported by the harness as UNAVAILABLE with the
reason. Reporting them as 100% because nothing disagreed would be the exact
lie this phase exists to prevent.
"""
import pytest

from tests.phase7.conftest import load_fixture, seed_companies, seed_corpus


@pytest.fixture()
def corpus(phase7_engine):
    raw = load_fixture("labeled_corpus.json")
    seed_companies(phase7_engine, raw["companies"])
    seed_corpus(phase7_engine, raw)
    return phase7_engine


@pytest.fixture()
def commodity_output():
    from eval.harness import StageBundle, run_v5_path

    return run_v5_path(StageBundle.from_dict(load_fixture("corpus_event_bundle.json")))


def test_the_fixture_event_publishes_one_primary_and_one_ripple(commodity_output):
    """The precondition for every number below. Stated as its own test so a
    change in the gate policy shows up here rather than as a mystery in the
    precision figure."""
    tiers = {r.ticker: r.publication_tier for r in commodity_output.records}
    assert tiers == {"FIXA.NS": "PRIMARY", "FIXB.NS": "SECONDARY_RIPPLE"}


def test_pairs_join_labels_to_records_by_canonical_ticker(corpus, commodity_output):
    from eval.harness import build_pairs, load_expectations

    with corpus.connect() as conn:
        expectation = {e.event_id: e for e in load_expectations(conn)}["fx-commodity-1"]
        pairs = build_pairs(conn, expectation, commodity_output)

    by_company = {p.company_ref: p for p in pairs}
    assert by_company["FIXA"].expected_tier == "PRIMARY"
    assert by_company["FIXA"].published_tier == "PRIMARY"
    assert by_company["FIXB"].published_tier == "SECONDARY_RIPPLE"
    # labeled ABSENT, never published -- a true negative, and it must be in
    # the set so a future false positive on it can be counted
    assert by_company["FIXC"].published_tier == "ABSENT"


def test_pairs_carry_the_sector_so_the_report_can_split_by_it(corpus,
                                                              commodity_output):
    from eval.harness import build_pairs, load_expectations

    with corpus.connect() as conn:
        expectation = {e.event_id: e for e in load_expectations(conn)}["fx-commodity-1"]
        pairs = build_pairs(conn, expectation, commodity_output)
    assert {p.company_ref: p.sector for p in pairs}["FIXA"] == "fixture_energy"


def test_the_report_is_hand_checkable_on_the_fixture_event(corpus, commodity_output):
    from eval.harness import load_expectations, score

    with corpus.connect() as conn:
        expectations = [e for e in load_expectations(conn)
                        if e.event_id == "fx-commodity-1"]
        report = score(conn, expectations, {"fx-commodity-1": commodity_output})

    assert report.aggregate["primary_precision"] == 1.0
    assert report.aggregate["primary_recall"] == 1.0
    assert report.aggregate["secondary_ripple_precision"] == 1.0
    assert report.aggregate["secondary_ripple_recall"] == 1.0
    # two expected families, one reachable from the one published ripple
    assert report.aggregate["ripple_family_recall"] == 0.5


def test_the_report_breaks_down_by_stratum_and_by_sector(corpus, commodity_output):
    from eval.harness import load_expectations, score

    with corpus.connect() as conn:
        expectations = [e for e in load_expectations(conn)
                        if e.event_id == "fx-commodity-1"]
        report = score(conn, expectations, {"fx-commodity-1": commodity_output})

    assert "commodity" in report.per_stratum
    assert report.per_stratum["commodity"]["primary_precision"] == 1.0
    assert set(report.per_sector) >= {"fixture_energy", "fixture_materials"}


def test_metrics_the_label_schema_cannot_express_are_unavailable_not_perfect(
        corpus, commodity_output):
    from eval.harness import load_expectations, score

    with corpus.connect() as conn:
        expectations = [e for e in load_expectations(conn)
                        if e.event_id == "fx-commodity-1"]
        report = score(conn, expectations, {"fx-commodity-1": commodity_output})

    for metric in ("directness_accuracy", "distance_accuracy",
                   "evidence_accuracy", "section_accuracy", "calibration_ece",
                   "calibration_brier"):
        assert report.aggregate[metric] is None, metric
        assert metric in report.unavailable
        assert report.unavailable[metric], metric


def test_the_unavailability_reasons_name_the_missing_input(corpus, commodity_output):
    from eval.harness import load_expectations, score

    with corpus.connect() as conn:
        expectations = [e for e in load_expectations(conn)
                        if e.event_id == "fx-commodity-1"]
        report = score(conn, expectations, {"fx-commodity-1": commodity_output})

    assert "eval_label" in report.unavailable["directness_accuracy"]
    assert "calibration" in report.unavailable["calibration_ece"].lower()


def test_every_metric_the_task_names_is_in_the_report(corpus, commodity_output):
    from eval.harness import METRIC_NAMES, load_expectations, score

    with corpus.connect() as conn:
        expectations = [e for e in load_expectations(conn)
                        if e.event_id == "fx-commodity-1"]
        report = score(conn, expectations, {"fx-commodity-1": commodity_output})

    assert set(METRIC_NAMES) <= set(report.aggregate)
    for name in ("primary_precision", "primary_recall",
                 "secondary_ripple_precision", "secondary_ripple_recall",
                 "primary_wrong_direction_rate", "economic_effect_accuracy",
                 "mechanism_accuracy", "directness_accuracy", "distance_accuracy",
                 "materiality_accuracy", "evidence_accuracy", "section_accuracy",
                 "abstention_precision", "calibration_ece", "calibration_brier",
                 "ripple_family_recall", "firewall_deletion_rate_primary_prose",
                 "fabricated_numeral_rate", "internal_contradiction_rate",
                 "cross_model_primary_precision", "same_model_primary_precision"):
        assert name in report.aggregate, name


def test_the_gate_metric_set_is_derived_from_the_report(corpus, commodity_output):
    """The harness feeds the shipping gates; nobody types the numbers in."""
    from eval.harness import load_expectations, score
    from eval.shipping_gates import evaluate_gates

    with corpus.connect() as conn:
        expectations = [e for e in load_expectations(conn)
                        if e.event_id == "fx-commodity-1"]
        report = score(conn, expectations, {"fx-commodity-1": commodity_output})

    gate_metrics = report.gate_metrics()
    assert gate_metrics["primary_precision"] == 1.0
    gate_report = evaluate_gates(gate_metrics, baseline=None)
    # most gates are unmeasurable on a one-event fixture corpus, and that is
    # reported as REFUSED rather than passed
    assert gate_report.exit_code != 0
    assert {o.name for o in gate_report.refusals}


def test_an_event_with_no_output_is_reported_unscored_not_scored_as_a_miss(corpus):
    from eval.harness import load_expectations, score

    with corpus.connect() as conn:
        expectations = [e for e in load_expectations(conn)
                        if e.event_id == "fx-commodity-1"]
        report = score(conn, expectations, {})
    assert report.unscored == ("fx-commodity-1",)
    assert report.aggregate["primary_precision"] is None


def test_scoring_zero_events_is_refused(corpus):
    from eval.harness import HarnessRefusal, score

    with corpus.connect() as conn:
        with pytest.raises(HarnessRefusal):
            score(conn, [], {})


# ---------------------------------------------------------------------------
# the V5 path, offline
# ---------------------------------------------------------------------------

def test_the_path_makes_no_model_call_when_no_client_is_injected(commodity_output):
    assert commodity_output.ledger.total_calls == 0


def test_the_path_runs_the_falsifier_only_when_a_client_is_injected():
    import json

    from tests.phase7.conftest import ScriptedClient
    from eval.harness import StageBundle, run_v5_path

    response = json.dumps({"checklist": [], "objections": []})
    client = ScriptedClient(response, response)
    bundle = StageBundle.from_dict(load_fixture("corpus_event_bundle.json"))
    output = run_v5_path(bundle, falsifier_client=client)
    assert client.calls >= 1
    assert output.ledger.frontier_calls >= 1


def test_the_harness_imports_no_provider_sdk_and_no_network_module():
    from pathlib import Path

    from tests.phase7.conftest import BACKEND, imported_modules, package_sources

    banned = {"anthropic", "openai", "httpx", "requests", "socket", "aiohttp",
              "urllib.request", "google.generativeai", "groq"}
    for path in package_sources(Path(BACKEND) / "eval"):
        assert not (imported_modules(path) & banned), path


def test_the_two_scorers_stay_separate():
    """Session 0's V4 scorer and the V5 harness share the CORPUS and nothing
    else. The harness reuses exactly two pure helpers (kappa and the numeral
    tokenizer) and reimplements neither."""
    from pathlib import Path

    from tests.phase7.conftest import BACKEND, code_lines

    # EXECUTABLE lines only: the module docstring explains the relationship
    # between the two scorers and naturally names the V4 table, and a
    # docstring must not be what makes a scan fail any more than it may be
    # what makes one pass.
    executable = "\n".join(
        line for _, line in code_lines(Path(BACKEND) / "eval" / "harness.py"))
    assert "score_corpus" not in executable
    assert "alert_companies" not in executable


def test_the_v5_path_never_writes_a_row(phase7_engine, commodity_output):
    """The harness MEASURES. A harness that wrote canonical records would be
    scoring its own output."""
    import sqlalchemy as sa

    with phase7_engine.connect() as conn:
        assert conn.execute(sa.text("SELECT COUNT(*) FROM company_impact")).scalar() == 0
        assert conn.execute(sa.text("SELECT COUNT(*) FROM signal")).scalar() == 0
