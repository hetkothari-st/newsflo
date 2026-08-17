"""TASK 6.1 -- the falsification stage (spec section 12).

An ADVERSARY, not a verifier. Its objective is to destroy the candidate, and
the burden of proof sits on PUBLICATION: an objection stands unless a
rebuttal signal from ANOTHER stage cites a specific record field or evidence
id. Free-form argument is not a rebuttal, and the falsifier may not answer
itself.

Every LLM call here is a scripted string. Nothing in this file, and nothing
in `app/analysis/falsifier/`, constructs a provider client.
"""
import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest

from tests.phase6 import helpers
from tests.phase6.conftest import (
    BACKEND, FIXTURE_ANALYSIS_VERSION, FIXTURE_EVENT_ID,
    FIXTURE_FALSIFIER_MODEL, FIXTURE_FALSIFIER_PROVIDER,
    FIXTURE_GENERATOR_LINEAGE, FIXTURE_GENERATOR_MODEL,
    FIXTURE_GENERATOR_PROVIDER, FIXTURE_NOW, ScriptedClient, code_lines,
    package_sources,
)

FALSIFIER_PACKAGE = BACKEND / "app" / "analysis" / "falsifier"
FIXTURE_COMPANY_ID = 6001


@pytest.fixture()
def policy():
    from app.analysis.falsifier.config import load_falsifier_config

    return load_falsifier_config()


@pytest.fixture()
def record_set():
    """The record set the falsifier reasons over -- the serialized canonical
    record, exactly as the reducer emits it."""
    from app.core.reducer import serialize_company_impact

    return serialize_company_impact(helpers.impact(
        company_id=FIXTURE_COMPANY_ID, ticker="FIXFAL",
        publication_tier="PRIMARY", net_effect="NEGATIVE",
        mechanism_id="aviation_fuel_cost", delta_ebitda_pct_p50=-3.0,
        channels=[{"channel_id": "fixture-atf", "mechanism_id": "aviation_fuel_cost",
                   "horizon": "NEAR_TERM", "direction": "NEGATIVE",
                   "materiality": "MEDIUM", "material": True,
                   "exposure_id": "fixture-exposure-1",
                   "evidence_ids": ["fixture-evidence-1"],
                   "modifiers_applied": []}],
        claim_bindings=[{"claim_id": "fixture-claim-1", "claim_type": "COST_EXPOSURE",
                         "binding_status": "BOUND", "evidence_grade": "B",
                         "evidence_ids": ["fixture-evidence-1"]}]))


def answered(*, unanswerable: tuple[int, ...] = ()) -> dict:
    """A well-formed checklist response: all ten questions answered with a
    citation, except those the caller marks unanswerable."""
    return {"checklist": [
        {"question": n, "answerable": n not in unanswerable,
         "answer": ("the fixture record states it" if n not in unanswerable else ""),
         "cites": (["channels[fixture-atf].direction"] if n not in unanswerable else [])}
        for n in range(1, 11)], "objections": []}


def falsifier_for(policy, response: str, *, model_id: str | None = None):
    from app.analysis.falsifier.engine import Falsifier

    # A model id needs its provider -- `validate_policy` refuses half a
    # routing decision, so a test cannot configure one either.
    return Falsifier(
        client=ScriptedClient(response),
        policy=(replace(policy, model_id=model_id,
                        provider=FIXTURE_FALSIFIER_PROVIDER)
                if model_id else policy),
        generator_provider=FIXTURE_GENERATOR_PROVIDER,
        generator_model_id=FIXTURE_GENERATOR_MODEL,
        generator_prompt_lineage=FIXTURE_GENERATOR_LINEAGE)


# ---------------------------------------------------------------------------
# checklist -- unanswerable raises an objection, and malformed fails CLOSED
# ---------------------------------------------------------------------------

def test_an_unanswerable_checklist_item_raises_an_objection(policy, record_set):
    """Spec section 12.2: "Unanswerable => objection". The TYPE is the one the
    config maps that question to -- not one the model chose."""
    result = falsifier_for(policy, json.dumps(answered(unanswerable=(5,)))).run(record_set)

    raised = [o for o in result.objections if o.checklist_question == 5]
    assert len(raised) == 1
    assert raised[0].type == policy.checklist_objection_type(5)
    assert raised[0].severity == policy.severity_for(raised[0].type)
    assert raised[0].sustained is True, "the default is that the objection stands"

    assert [a.question for a in result.checklist if not a.answerable] == [5]


def test_every_checklist_question_is_asked(policy, record_set):
    """All ten, in structured form, with the record set in context."""
    falsifier = falsifier_for(policy, json.dumps(answered()))
    result = falsifier.run(record_set)

    assert [a.question for a in result.checklist] == list(range(1, 11))
    assert not result.objections
    prompt = falsifier.client.prompts[0]
    assert record_set["ticker"] in prompt
    for question in policy.checklist:
        assert question.text[:40] in prompt


def test_an_answer_without_a_citation_is_not_an_answer(policy, record_set):
    """Record citation or nothing -- the same discipline the rebuttal rule
    applies, applied to the checklist that produces the objections."""
    response = answered()
    response["checklist"][2]["cites"] = []
    result = falsifier_for(policy, json.dumps(response)).run(record_set)

    assert [a.question for a in result.checklist if not a.answerable] == [3]
    assert [o.checklist_question for o in result.objections] == [3]


def test_a_malformed_response_counts_every_question_unanswerable(policy, record_set):
    """FAIL CLOSED. A response the schema cannot read is not a clean bill of
    health: every question it failed to answer is unanswered, and each one
    raises its objection."""
    result = falsifier_for(policy, "not json at all").run(record_set)

    assert result.response_malformed is True
    assert all(not a.answerable for a in result.checklist)
    assert len(result.objections) == len(policy.checklist)
    assert any(o.severity == "BLOCKING" for o in result.objections)


def test_a_missing_question_is_unanswered_not_absent(policy, record_set):
    response = answered()
    response["checklist"] = [q for q in response["checklist"] if q["question"] != 2]
    result = falsifier_for(policy, json.dumps(response)).run(record_set)

    answer = next(a for a in result.checklist if a.question == 2)
    assert answer.answerable is False
    assert 2 in [o.checklist_question for o in result.objections]


def test_an_objection_type_outside_the_taxonomy_is_discarded_and_recorded(
        policy, record_set):
    """The taxonomy is CLOSED (Phase 5 m-8). A type nobody can aggregate is
    not smuggled through -- and not silently swallowed either."""
    response = answered()
    response["objections"] = [{"type": "FIXTURE_INVENTED_OBJECTION"}]
    result = falsifier_for(policy, json.dumps(response)).run(record_set)

    assert not result.objections
    assert any("FIXTURE_INVENTED_OBJECTION" in reason for reason in result.discarded)


def test_the_severity_comes_from_config_not_from_the_model(policy, record_set):
    """Severity is OUR policy. A model that calls its own ENTITY_WRONG a WARN
    does not get to downgrade a BLOCKING objection."""
    response = answered()
    response["objections"] = [{"type": "ENTITY_WRONG", "severity": "WARN"}]
    result = falsifier_for(policy, json.dumps(response)).run(record_set)

    raised = next(o for o in result.objections if o.type == "ENTITY_WRONG")
    assert raised.severity == "BLOCKING"


# ---------------------------------------------------------------------------
# sustaining logic -- the burden of proof
# ---------------------------------------------------------------------------

def phase0_signal(kind, payload, *, stage):
    """A signal that JOINS the Phase 0 PRIMARY fixture's signal set -- same
    event, same company, same analysis_version, so the reducer sees one
    company's view of one event."""
    from tests.phase0 import fixtures

    return helpers.signal(
        kind, payload, stage=stage, company_id=fixtures.PRIMARY_COMPANY_ID,
        event_id=fixtures.EVENT_ID, analysis_version=fixtures.ANALYSIS_VERSION,
        created_at=fixtures.FIXTURE_CREATED_AT)


def blocking_objection_signal(objection_id="falsifier:ENTITY_WRONG"):
    return phase0_signal("OBJECTION", {
        "objection_id": objection_id, "type": "ENTITY_WRONG",
        "severity": "BLOCKING", "sustained": True, "raised_by": "falsifier"},
        stage="FALSIFICATION")


def rebuttal_signal(payload, *, stage="SENSITIVITY"):
    return phase0_signal("REBUTTAL", payload, stage=stage)


def reduce_with(extra):
    """The Phase 0 PRIMARY fixture plus whatever this test adds."""
    from app.core.reducer import reduce_company_impact
    from tests.phase0 import fixtures

    return reduce_company_impact(
        list(fixtures.signals(fixtures.PRIMARY_COMPANY_ID)) + list(extra),
        fixtures.reducer_config())


def test_a_blocking_objection_without_a_rebuttal_rejects():
    impact = reduce_with([blocking_objection_signal()])

    assert impact.publication_tier == "REJECTED"
    assert impact.rejection_reason == "SUSTAINED_BLOCKING_OBJECTION"
    entry = next(o for o in impact.objections
                 if o["objection_id"] == "falsifier:ENTITY_WRONG")
    assert entry["sustained"] is True
    assert entry["rebutted_by"] == []


def test_the_same_candidate_publishes_without_the_objection():
    """Non-vacuity: the rejection above is caused by the objection, not by the
    fixture being unpublishable anyway."""
    assert reduce_with([]).publication_tier == "PRIMARY"


def test_an_objection_rebutted_by_a_record_field_citation_is_not_sustained():
    impact = reduce_with([
        blocking_objection_signal(),
        rebuttal_signal({"rebuttal_id": "fixture-reb-1",
                         "objection_id": "falsifier:ENTITY_WRONG",
                         "cites_record_field": "channels[fixture-atf].exposure_id"}),
    ])

    entry = next(o for o in impact.objections
                 if o["objection_id"] == "falsifier:ENTITY_WRONG")
    assert entry["sustained"] is False
    assert entry["rebutted_by"] == ["fixture-reb-1"]
    assert impact.publication_tier == "PRIMARY"


def test_an_objection_rebutted_by_an_evidence_id_is_not_sustained():
    impact = reduce_with([
        blocking_objection_signal(),
        rebuttal_signal({"rebuttal_id": "fixture-reb-2",
                         "objection_id": "falsifier:ENTITY_WRONG",
                         "cites_evidence_id": "fixture-evidence-1"},
                        stage="EVIDENCE"),
    ])
    entry = next(o for o in impact.objections
                 if o["objection_id"] == "falsifier:ENTITY_WRONG")
    assert entry["sustained"] is False


def test_a_free_text_only_rebuttal_leaves_the_objection_sustained():
    """DO NOT: "Do not accept free-form argument as a rebuttal. Record
    citation or nothing." A note is allowed to exist and changes nothing."""
    impact = reduce_with([
        blocking_objection_signal(),
        rebuttal_signal({"rebuttal_id": "fixture-reb-3",
                         "objection_id": "falsifier:ENTITY_WRONG",
                         "note": "on reflection the entity is obviously right"}),
    ])

    entry = next(o for o in impact.objections
                 if o["objection_id"] == "falsifier:ENTITY_WRONG")
    assert entry["sustained"] is True
    assert entry["rebutted_by"] == []
    assert impact.publication_tier == "REJECTED"


def test_a_rebuttal_from_the_objecting_stage_is_not_a_rebuttal():
    """DO NOT: "Do not let the falsifier rebut itself." Even a
    perfectly-cited rebuttal from the stage that raised the objection is
    ignored."""
    impact = reduce_with([
        blocking_objection_signal(),
        rebuttal_signal({"rebuttal_id": "fixture-reb-4",
                         "objection_id": "falsifier:ENTITY_WRONG",
                         "cites_record_field": "ticker"},
                        stage="FALSIFICATION"),
    ])

    entry = next(o for o in impact.objections
                 if o["objection_id"] == "falsifier:ENTITY_WRONG")
    assert entry["sustained"] is True
    assert impact.publication_tier == "REJECTED"


def test_a_rebuttal_pointed_at_another_objection_changes_nothing():
    impact = reduce_with([
        blocking_objection_signal(),
        rebuttal_signal({"rebuttal_id": "fixture-reb-5",
                         "objection_id": "falsifier:SOMETHING_ELSE",
                         "cites_record_field": "ticker"}),
    ])
    entry = next(o for o in impact.objections
                 if o["objection_id"] == "falsifier:ENTITY_WRONG")
    assert entry["sustained"] is True


def test_a_rebuttal_signal_must_name_the_objection_it_answers():
    from app.core.signals import SignalPayloadError

    with pytest.raises(SignalPayloadError):
        rebuttal_signal({"rebuttal_id": "fixture-reb-6",
                         "cites_record_field": "ticker"})


# ---------------------------------------------------------------------------
# rebuttal emission -- the stages that hold the cited data
# ---------------------------------------------------------------------------

def test_an_offset_objection_is_rebutted_by_the_offsetting_channel():
    """The sensitivity stage HOLDS the offsetting channel, so it is the stage
    that can cite one. The rebuttal names the channel_id."""
    from app.analysis.rebuttal import rebuttals_for

    objection = {"objection_id": "falsifier:q6:OFFSET_IGNORED",
                 "type": "OFFSET_IGNORED", "severity": "MAJOR", "sustained": True}
    record = {"fundamental": {"channels": [
        {"channel_id": "fixture-cost", "direction": "NEGATIVE", "material": True},
        {"channel_id": "fixture-realization", "direction": "POSITIVE", "material": True},
    ]}, "evidence": {"claim_bindings": []}}

    signals = rebuttals_for([objection], record, event_id=FIXTURE_EVENT_ID,
                            company_id=FIXTURE_COMPANY_ID,
                            analysis_version=FIXTURE_ANALYSIS_VERSION,
                            created_at=FIXTURE_NOW)
    assert len(signals) == 1
    payload = dict(signals[0].payload)
    assert payload["objection_id"] == "falsifier:q6:OFFSET_IGNORED"
    assert "fixture-realization" in payload["cites_record_field"]
    assert signals[0].stage == "SENSITIVITY"


def test_no_offsetting_channel_means_no_rebuttal():
    """Nothing is manufactured to clear an objection. One-sided channels
    leave the objection standing."""
    from app.analysis.rebuttal import rebuttals_for

    objection = {"objection_id": "falsifier:q6:OFFSET_IGNORED",
                 "type": "OFFSET_IGNORED", "severity": "MAJOR", "sustained": True}
    record = {"fundamental": {"channels": [
        {"channel_id": "fixture-cost", "direction": "NEGATIVE", "material": True}]},
        "evidence": {"claim_bindings": []}}

    assert rebuttals_for([objection], record, event_id=FIXTURE_EVENT_ID,
                         company_id=FIXTURE_COMPANY_ID,
                         analysis_version=FIXTURE_ANALYSIS_VERSION,
                         created_at=FIXTURE_NOW) == ()


def test_an_evidence_stale_objection_is_rebutted_by_a_bound_claim_evidence_id():
    from app.analysis.rebuttal import rebuttals_for

    objection = {"objection_id": "falsifier:EVIDENCE_STALE",
                 "type": "EVIDENCE_STALE", "severity": "MAJOR", "sustained": True}
    record = {"fundamental": {"channels": []}, "evidence": {"claim_bindings": [
        {"claim_id": "fixture-claim-1", "binding_status": "BOUND",
         "evidence_ids": ["fixture-evidence-7"]}]}}

    signals = rebuttals_for([objection], record, event_id=FIXTURE_EVENT_ID,
                            company_id=FIXTURE_COMPANY_ID,
                            analysis_version=FIXTURE_ANALYSIS_VERSION,
                            created_at=FIXTURE_NOW)
    assert len(signals) == 1
    assert dict(signals[0].payload)["cites_evidence_id"] == "fixture-evidence-7"
    assert signals[0].stage == "EVIDENCE"


def test_an_unbound_claim_cannot_rebut_a_stale_evidence_objection():
    from app.analysis.rebuttal import rebuttals_for

    objection = {"objection_id": "falsifier:EVIDENCE_STALE",
                 "type": "EVIDENCE_STALE", "severity": "MAJOR", "sustained": True}
    record = {"fundamental": {"channels": []}, "evidence": {"claim_bindings": [
        {"claim_id": "fixture-claim-1", "binding_status": "UNBOUND",
         "evidence_ids": ["fixture-evidence-7"]}]}}

    assert rebuttals_for([objection], record, event_id=FIXTURE_EVENT_ID,
                         company_id=FIXTURE_COMPANY_ID,
                         analysis_version=FIXTURE_ANALYSIS_VERSION,
                         created_at=FIXTURE_NOW) == ()


def test_no_rebuttal_signal_is_ever_emitted_by_the_falsifier_package():
    """Structural, not instructed: nothing under app/analysis/falsifier/
    mentions the REBUTTAL kind at all."""
    for path in package_sources(FALSIFIER_PACKAGE):
        source = "\n".join(line for _, line in code_lines(path))
        assert "REBUTTAL" not in source, f"{path.name} names the REBUTTAL kind"


# ---------------------------------------------------------------------------
# model discipline (spec section 12.4)
# ---------------------------------------------------------------------------

def test_the_falsifier_model_id_differs_from_the_generator_when_configured(
        policy, record_set):
    falsifier = falsifier_for(policy, json.dumps(answered(unanswerable=(1,))),
                              model_id=FIXTURE_FALSIFIER_MODEL)
    result = falsifier.run(record_set)

    assert result.discipline.falsifier_model_id == FIXTURE_FALSIFIER_MODEL
    assert result.discipline.falsifier_model_id != result.discipline.generator_model_id
    assert result.discipline.cross_model is True
    assert "SAME_MODEL_AS_GENERATOR" not in result.discipline.limitations

    # ...and every objection it raises records WHO raised it, with what.
    for objection in result.objections:
        assert objection.model_id == FIXTURE_FALSIFIER_MODEL
        assert objection.raised_by == "falsifier"


def test_an_unconfigured_falsifier_model_is_recorded_as_a_limitation(
        policy, record_set):
    """The deployed config names no cross-model provider (nobody has signed
    one off). That is a LIMITATION on the record, not a silent fallback."""
    assert policy.model_id is None
    result = falsifier_for(policy, json.dumps(answered(unanswerable=(1,)))).run(record_set)

    assert result.discipline.cross_model is False
    assert "SAME_MODEL_AS_GENERATOR" in result.discipline.limitations
    assert result.discipline.falsifier_model_id == FIXTURE_GENERATOR_MODEL


def test_the_falsifier_prompt_lineage_is_distinct_from_the_generators(policy):
    assert policy.prompt_lineage != FIXTURE_GENERATOR_LINEAGE


def test_a_shared_prompt_lineage_is_recorded_as_a_limitation(policy, record_set):
    """DO NOT: "Do not run generator and falsifier on the same prompt lineage
    without recording it as a limitation"."""
    from app.analysis.falsifier.engine import Falsifier

    falsifier = Falsifier(
        client=ScriptedClient(json.dumps(answered(unanswerable=(1,)))),
        policy=policy, generator_provider=FIXTURE_GENERATOR_PROVIDER,
        generator_model_id=FIXTURE_GENERATOR_MODEL,
        generator_prompt_lineage=policy.prompt_lineage)
    result = falsifier.run(record_set)

    assert "SAME_PROMPT_LINEAGE_AS_GENERATOR" in result.discipline.limitations


def test_the_provider_and_model_reach_every_objection_signal(policy, record_set):
    falsifier = falsifier_for(policy, json.dumps(answered(unanswerable=(2,))),
                              model_id=FIXTURE_FALSIFIER_MODEL)
    result = falsifier.run(record_set)
    signals = falsifier.signals(
        result, event_id=FIXTURE_EVENT_ID, company_id=FIXTURE_COMPANY_ID,
        analysis_version=FIXTURE_ANALYSIS_VERSION, created_at=FIXTURE_NOW)

    assert signals
    for emitted in signals:
        assert str(emitted.kind) == "OBJECTION"
        assert emitted.stage == "FALSIFICATION"
        assert emitted.payload["model_id"] == FIXTURE_FALSIFIER_MODEL
        assert emitted.payload["prompt_lineage"] == policy.prompt_lineage
        assert emitted.created_by.startswith("llm:")


def test_a_cross_model_falsifier_needs_a_provider_too(policy):
    """A model id with no provider is not a cross-model run, it is a half-
    configured one. Refused rather than half-honoured."""
    from app.analysis.falsifier.config import FalsifierConfigError, validate_policy

    with pytest.raises(FalsifierConfigError):
        validate_policy(replace(policy, model_id=FIXTURE_FALSIFIER_MODEL,
                                provider=None))
    validate_policy(replace(policy, model_id=FIXTURE_FALSIFIER_MODEL,
                            provider=FIXTURE_FALSIFIER_PROVIDER))


# ---------------------------------------------------------------------------
# structural guarantees
# ---------------------------------------------------------------------------

def test_the_falsifier_constructs_no_client_and_imports_no_provider_sdk():
    banned = ("anthropic", "openai", "google", "httpx", "requests", "socket",
              "urllib", "app.analysis.claude_client")
    for path in package_sources(FALSIFIER_PACKAGE):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not any(name == b or name.startswith(b + ".")
                               for b in banned), f"{path.name} imports {name}"


def test_the_falsifier_calls_exactly_one_client_method():
    """`client.generate(prompt)` and nothing else -- the seam is one method
    wide, so a stub is a complete implementation."""
    calls = set()
    for path in package_sources(FALSIFIER_PACKAGE):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "client"):
                calls.add(node.func.attr)
    assert calls <= {"generate"}, calls


def test_the_objection_taxonomy_is_exactly_the_spec_table(policy):
    """Section 12.1, verbatim, with the phase file's default severities."""
    expected = {
        "ENTITY_WRONG": "BLOCKING",
        "MECHANISM_INVALID": "BLOCKING",
        "EXPOSURE_NOT_IN_LISTCO": "BLOCKING",
        "OFFSET_IGNORED": "MAJOR",
        "REGIME_MODIFIER_MISSING": "MAJOR",
        "MAGNITUDE_IMMATERIAL": "MAJOR",
        "HORIZON_MISMATCH": "MAJOR",
        "EVIDENCE_STALE": "MAJOR",
        "ALREADY_PRICED": "WARN",
        "BASE_RATE_VIOLATION": "WARN",
        "SECOND_ORDER_OVERREACH": "WARN",
    }
    assert dict(policy.severities) == expected


def test_every_objection_type_the_falsifier_can_raise_is_in_the_closed_vocabulary(
        policy):
    from app.core.signals import OBJECTION_TYPES

    for objection_type in policy.severities:
        assert objection_type in OBJECTION_TYPES
    for question in policy.checklist:
        assert question.objection_type in OBJECTION_TYPES


def test_the_ten_questions_are_the_ten_questions(policy):
    assert [q.question for q in policy.checklist] == list(range(1, 11))
    assert len({q.text for q in policy.checklist}) == 10
