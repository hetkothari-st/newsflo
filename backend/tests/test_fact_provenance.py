"""Per-fact epistemic class + event geography (2026-08-14).

Two gaps the final blueprint never covered, agreed as ADVISORY (prompt
discipline + audit), NOT gate-enforced:

* every FactItem carries fact_class -- FACT (the article states it),
  DERIVED (arithmetic/unit conversion off stated numbers), INFERENCE (the
  model's own reasoning, absent from the article) or UNKNOWN -- and the
  class rides into every downstream prompt via compact_lines();
* EventFacts carries the event's geography scope + the regions exactly as
  the article states them, so a US-only event stops silently authorizing
  India company claims two stages later.

The publication gate is deliberately UNTOUCHED by both: GATE_SEQUENCE is
not extended here, and no test in this file asserts a gate outcome.
"""
import json

from app.analysis.impact_graph import prompts
from app.analysis.impact_graph.engine import _compact_suffix, _facts_suffix, analyze_article_v3
from app.analysis.impact_graph.schemas import (
    FACT_CLASSES, GEOGRAPHY_SCOPES, IMPACT_SCHEMA_VERSION, EventFacts, FactItem,
    ImpactGraphResult,
)
from app.models import Article
from app.pipeline import _persist_alert, _v3_entries

from tests.test_impact_graph import FACTS, FakeRouter


def _facts(**overrides) -> EventFacts:
    return EventFacts(**dict(FACTS, **overrides))


# --- FactItem.fact_class ---------------------------------------------------

def test_fact_class_parsed_when_valid():
    item = FactItem(fact_id="F1", text="Hormuz closed", fact_class="FACT")
    assert item.fact_class == "FACT"


def test_fact_class_defaults_to_unknown_when_omitted():
    """An omitted class is honestly UNKNOWN -- never optimistically FACT."""
    item = FactItem(fact_id="F1", text="Hormuz closed")
    assert item.fact_class == "UNKNOWN"


def test_fact_class_out_of_enum_normalizes_to_unknown():
    item = FactItem(fact_id="F1", text="x", fact_class="PROBABLY_TRUE")
    assert item.fact_class == "UNKNOWN"


def test_fact_class_is_case_normalized():
    """Models emit the enum in whatever case the prompt echoed; the stored
    value is canonical upper-case, not a second spelling of the same class."""
    assert FactItem(fact_id="F1", text="x", fact_class="inference").fact_class == "INFERENCE"
    assert FactItem(fact_id="F2", text="x", fact_class=" derived ").fact_class == "DERIVED"


def test_fact_class_enum_is_the_four_agreed_values():
    assert FACT_CLASSES == ["FACT", "DERIVED", "INFERENCE", "UNKNOWN"]


# --- the class reaches downstream prompts ----------------------------------

def test_compact_lines_tags_every_fact_with_its_class():
    facts = _facts(fact_items=[
        {"fact_id": "F1", "text": "Hormuz closed", "fact_class": "FACT"},
        {"fact_id": "F2", "text": "a fifth of crude transits it", "fact_class": "DERIVED"},
        {"fact_id": "F3", "text": "refiners will hedge", "fact_class": "INFERENCE"},
    ])
    lines = facts.compact_lines().splitlines()
    assert lines[0] == "F1 [FACT]: Hormuz closed"
    assert lines[1] == "F2 [DERIVED]: a fifth of crude transits it"
    assert lines[2] == "F3 [INFERENCE]: refiners will hedge"


def test_compact_lines_differs_by_class_only():
    """Proof the class is genuinely carried downstream: two fact stores
    identical except for the class must not produce the same prompt block."""
    stated = _facts(fact_items=[{"fact_id": "F1", "text": "x", "fact_class": "FACT"}])
    guessed = _facts(fact_items=[{"fact_id": "F1", "text": "x", "fact_class": "INFERENCE"}])
    assert stated.compact_lines() != guessed.compact_lines()


def test_compact_lines_prose_fallback_unchanged_for_legacy_results():
    """A pre-upgrade cached result has no fact_items at all -- it keeps the
    clipped prose block, with no tag machinery applied."""
    facts = _facts()
    assert facts.fact_items == []
    assert facts.compact_lines() == FACTS["facts"][:1200]


# --- EventFacts geography --------------------------------------------------

def test_geography_scope_parsed_when_valid():
    assert _facts(geography_scope="INDIA").geography_scope == "INDIA"


def test_geography_scope_defaults_to_unknown_when_omitted():
    assert _facts().geography_scope == "UNKNOWN"


def test_geography_scope_out_of_enum_normalizes_to_unknown():
    """Same discipline as event_cause: never invent a scope the article
    does not support."""
    assert _facts(geography_scope="MARS").geography_scope == "UNKNOWN"


def test_geography_scope_is_case_normalized():
    assert _facts(geography_scope="india").geography_scope == "INDIA"


def test_geography_scopes_enum():
    assert GEOGRAPHY_SCOPES == ["INDIA", "GLOBAL", "OTHER_COUNTRY", "UNKNOWN"]


def test_geography_regions_preserved_verbatim():
    """Regions are the article's own words -- never normalized to a
    controlled vocabulary, never inferred from the scope."""
    facts = _facts(geography_regions=["Strait of Hormuz", "Persian Gulf"])
    assert facts.geography_regions == ["Strait of Hormuz", "Persian Gulf"]


def test_geography_regions_default_empty():
    assert _facts().geography_regions == []


def test_geography_regions_not_synthesized_from_named_entities():
    facts = _facts(named_entities=["Iran", "Hormuz"])
    assert facts.geography_regions == []


# --- geography reaches the prompts ----------------------------------------

def test_compact_suffix_carries_geography():
    suffix = _compact_suffix(_facts(geography_scope="OTHER_COUNTRY",
                                    geography_regions=["United States"]))
    assert "GEOGRAPHY: OTHER_COUNTRY" in suffix
    assert "United States" in suffix


def test_facts_suffix_carries_geography():
    suffix = _facts_suffix(_facts(geography_scope="GLOBAL"))
    assert "GEOGRAPHY: GLOBAL" in suffix


def test_geography_line_omitted_when_nothing_is_known():
    """UNKNOWN scope with no regions adds NOTHING to the prompt -- an
    honest absence, not a 'GEOGRAPHY: UNKNOWN' line for the model to
    reason from."""
    assert "GEOGRAPHY" not in _compact_suffix(_facts())
    assert "GEOGRAPHY" not in _facts_suffix(_facts())


def test_geography_line_present_when_only_regions_are_known():
    suffix = _compact_suffix(_facts(geography_regions=["Gulf of Mexico"]))
    assert "GEOGRAPHY: UNKNOWN" in suffix
    assert "Gulf of Mexico" in suffix


# --- structured-output schema ---------------------------------------------

def test_schema_requires_fact_class_on_every_fact_item():
    from app.analysis.impact_graph.schemas import SCHEMA_FACTS

    items = SCHEMA_FACTS["properties"]["fact_items"]["items"]
    assert items["properties"]["fact_class"]["enum"] == FACT_CLASSES
    assert "fact_class" in items["required"]


def test_schema_offers_geography_but_never_requires_it():
    from app.analysis.impact_graph.schemas import SCHEMA_FACTS

    props = SCHEMA_FACTS["properties"]
    assert props["geography_scope"]["enum"] == GEOGRAPHY_SCOPES
    assert props["geography_regions"]["type"] == "array"
    # An omission is a legitimate UNKNOWN, exactly like event_cause.
    assert "geography_scope" not in SCHEMA_FACTS["required"]
    assert "geography_regions" not in SCHEMA_FACTS["required"]


def test_schema_and_prompt_versions_were_bumped():
    """Both feed _v3_cache_key and StageRouter._fingerprint. Leaving either
    at its pre-change value would replay cached results that carry no fact
    classes and no geography as if they did."""
    assert IMPACT_SCHEMA_VERSION != "kg-1"
    assert prompts.IMPACT_PROMPT_VERSION != "kg-6"


# --- prompt discipline -----------------------------------------------------

def test_facts_prompt_defines_all_four_classes():
    for value in FACT_CLASSES:
        assert value in prompts.FACTS_PROMPT


def test_facts_prompt_forbids_labelling_an_inference_as_fact():
    assert "INFERENCE" in prompts.FACTS_PROMPT
    assert "fact_class" in prompts.FACTS_PROMPT


def test_facts_prompt_requires_structured_geography():
    assert "geography_scope" in prompts.FACTS_PROMPT
    assert "geography_regions" in prompts.FACTS_PROMPT


def test_downstream_prompts_explain_the_tags():
    """The tags are worthless if the stage reading them was never told what
    they mean, so the shared static prefix carries the legend by default."""
    legend = prompts.FACT_CLASS_LEGEND
    assert "[FACT]" in legend and "[INFERENCE]" in legend
    assert legend in prompts.static_prefix(prompts.RIPPLE_PROMPT)
    assert legend in prompts.static_prefix(prompts.RIPPLE_COMPANIES_PROMPT)


def test_facts_stage_prefix_does_not_carry_the_legend():
    """Stage 1 PRODUCES the classes -- FACTS_PROMPT states the rules in
    full -- so it must not also pay for the downstream reader's legend.
    Asserted against the prefix the ENGINE actually sends, not against a
    hand-built call, so wiring the flag anywhere else fails this test."""
    class _CapturingRouter(FakeRouter):
        def __init__(self, responses):
            super().__init__(responses)
            self.prefixes: dict[str, str] = {}

        def call(self, stage, **kwargs):
            self.prefixes[stage] = kwargs.get("static_prefix", "")
            return super().call(stage, **kwargs)

    router = _CapturingRouter({"extract_facts": dict(FACTS), "initial_shocks": {"shocks": []}})
    analyze_article_v3(router, "t", "c", session=None, article_id=1)
    assert prompts.FACT_CLASS_LEGEND not in router.prefixes["extract_facts"]
    assert prompts.FACT_CLASS_LEGEND in router.prefixes["initial_shocks"]


# --- carry-through to the engine result ------------------------------------

def test_result_carries_fact_items_and_geography():
    router = FakeRouter({
        "extract_facts": dict(
            FACTS,
            fact_items=[{"fact_id": "F1", "text": "Hormuz closed", "fact_class": "FACT"}],
            geography_scope="GLOBAL", geography_regions=["Strait of Hormuz"],
        ),
        "initial_shocks": {"shocks": []},
    })
    result = analyze_article_v3(router, "t", "c", session=None, article_id=1)
    assert [f.fact_class for f in result.fact_items] == ["FACT"]
    assert [f.text for f in result.fact_items] == ["Hormuz closed"]
    assert result.geography_scope == "GLOBAL"
    assert result.geography_regions == ["Strait of Hormuz"]


def test_legacy_cached_result_without_the_new_fields_still_deserializes():
    """get_cached_v3 replays ImpactGraphResult JSON up to V3_CACHE_TTL_DAYS
    old. A blob written before these fields existed must load, not raise."""
    legacy = json.dumps({"category": "oil_gas", "facts": "old"})
    result = ImpactGraphResult.model_validate_json(legacy)
    assert result.fact_items == []
    assert result.geography_scope == "UNKNOWN"
    assert result.geography_regions == []


# --- persistence -----------------------------------------------------------

def _persist(db, result):
    article = Article(source="s", provider="finnhub", url="https://ex.com/fact-prov",
                      title="crude spikes", content="c", status="CATEGORIZED")
    db.add(article)
    db.commit()
    return _persist_alert(
        db, article, result.category, _v3_entries(db, result),
        event_type=result.event_type, gaps=[], edges=[], client=None,
        facts=result.facts, analysis_provider=result.analysis_provider,
        analysis_quality=result.analysis_quality, event_cause=result.event_cause,
        fact_items=[f.model_dump() for f in result.fact_items],
        geography_scope=result.geography_scope,
        geography_regions=result.geography_regions,
    )


def test_persist_writes_fact_items_and_geography(db_session):
    result = ImpactGraphResult(
        category="oil_gas", event_type="geopolitics", facts="f",
        fact_items=[FactItem(fact_id="F1", text="Hormuz closed", fact_class="FACT")],
        geography_scope="GLOBAL", geography_regions=["Strait of Hormuz"],
    )
    alert = _persist(db_session, result)
    assert json.loads(alert.fact_items_json) == [
        {"fact_id": "F1", "text": "Hormuz closed", "fact_class": "FACT"}
    ]
    assert alert.event_geography_scope == "GLOBAL"
    assert json.loads(alert.event_geography_regions_json) == ["Strait of Hormuz"]


def test_persist_leaves_columns_null_when_nothing_was_extracted(db_session):
    """No facts and no geography must persist as NULL, never as an empty
    JSON array pretending an extraction happened."""
    result = ImpactGraphResult(category="oil_gas", event_type="geopolitics", facts="f")
    alert = _persist(db_session, result)
    assert alert.fact_items_json is None
    assert alert.event_geography_regions_json is None
    assert alert.event_geography_scope is None
