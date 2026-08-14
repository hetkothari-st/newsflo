"""Final blueprint §32 -- the executable index of the twenty regression
scenarios.

§32 lists twenty scenarios the system must not regress on. Ten of them are
BEHAVIORAL (what the engine publishes for a given event) and live as
labeled fixtures in ``benchmarks/regression_events/``, scored end-to-end by
``tools/offline_benchmark.py``. The other ten are SYSTEMIC (what the
database, the section builder, the persistence path or the provider layer
must guarantee regardless of any particular event) and cannot honestly be
expressed as a fixture -- a benchmark corpus cannot assert that a DB
trigger rejects a contradictory UPDATE, or that two racing sessions
converge on one alert.

Rather than leave those ten uncovered -- or worse, fake a fixture for them
-- this module is the MAP: §32 number -> the concrete artifact(s) that
actually pin it. Every entry is CHECKED, not documented:

* a ``fixture`` entry must name a real JSON file in the corpus that parses
  and carries a ``ground_truth`` block;
* a ``test`` entry must name a real module and a real function INSIDE it,
  resolved by importing the module and looking the attribute up.

That is what stops the map from rotting. A renamed test or a deleted
fixture fails HERE, at the index, instead of quietly leaving a blueprint
scenario with no coverage and nobody noticing for six months.

The index is deliberately NOT a coverage claim by itself: it asserts that
the named artifacts exist and are wired, and the artifacts themselves
assert the behavior. Read it as a table of contents with a checksum.
"""
import importlib
import json
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[1]
FIXTURE_DIR = _BACKEND_DIR / "benchmarks" / "regression_events"


# §32 number -> (title, fixture ids, "module::function" test pointers).
# Batch A (1-10) is fixture-only by construction; batch B (11-20) mixes the
# two, and every entry states WHY it takes the shape it does.
BLUEPRINT_32_INDEX: dict[int, dict] = {
    1: {
        "title": "no PRIMARY but valid ripple sectors",
        "fixtures": ["crude_macro_decline_no_primary"],
        "tests": [],
    },
    2: {
        "title": "PRIMARY + SECONDARY_RIPPLE in same event",
        "fixtures": ["primary_and_secondary_ripple_same_event"],
        "tests": [],
    },
    3: {
        "title": "direct exposure that is secondary only because of evidence",
        "fixtures": ["direct_exposure_secondary_because_evidence"],
        "tests": [],
    },
    4: {
        "title": "article-mentioned stock losers that are not fundamental casualties",
        "fixtures": ["mentioned_losers_not_fundamental_casualties"],
        "tests": [],
    },
    5: {
        "title": "semantic-similarity false positive",
        "fixtures": ["semantic_similarity_false_positive"],
        "tests": [],
    },
    6: {
        "title": "Reliance-style mixed exposure",
        "fixtures": ["reliance_crude_mixed_effect"],
        "tests": [],
    },
    7: {
        "title": "Oil India direction inconsistency",
        "fixtures": ["oil_india_direction_inconsistency"],
        "tests": [],
    },
    8: {
        "title": "paint ripple",
        "fixtures": ["paint_ripple_secondary"],
        "tests": [],
    },
    9: {
        "title": "tyre ripple",
        "fixtures": ["tyre_ripple_secondary"],
        "tests": [],
    },
    10: {
        "title": "cement ripple",
        "fixtures": ["cement_ripple_secondary"],
        "tests": [],
    },
    11: {
        "title": "INR/IT multi-hop ripple -> macro_context, not company rows",
        "fixtures": ["inr_it_multihop_macro_context"],
        "tests": [],
        "note": "Trade deficit -> rupee -> IT export realisation is three hops. "
                "The tier-C candidate publishes as macro_context (§7); the "
                "tier-E candidate at the same node produces no row at all "
                "(REJECT_LOW_PRIORITY at the d3 causal-path bar).",
    },
    12: {
        "title": "generic macro false positive rejection",
        "fixtures": ["generic_macro_false_positive"],
        "tests": [],
        "note": "Both shapes in one event: the article's own subject rejected "
                "on a NOT_SUPPORTED counterfactual, and a sector peer rejected "
                "on interchangeable sector prose at tier E.",
    },
    13: {
        "title": "low-materiality ripple rejection",
        "fixtures": ["low_materiality_ripple_rejected"],
        "tests": [],
        "note": "Rejected at the gate (grade LOW, tier SUBJECT -- strong "
                "evidence never buys materiality) AND by the engine's own "
                "distance-scaled prune, with a published control on the same "
                "mechanism so the fixture cannot pass by refusing everything.",
    },
    14: {
        "title": "primary evidence promotion (C -> primary, D -> secondary_ripple)",
        "fixtures": [
            "primary_evidence_promotion_tier_c",
            "primary_evidence_promotion_tier_d",
        ],
        "tests": [],
        "note": "A matched PAIR: identical article, universe, mechanism, "
                "materiality, confidence and canned stage responses. The only "
                "difference is whether an independently sourced exposure record "
                "exists, and that alone decides primary vs secondary_ripple.",
    },
    15: {
        "title": "stale worker mutation",
        "fixtures": [],
        "tests": [
            # T3: DB-level triggers -- a stale worker cannot UPDATE a gated
            # row into an inconsistent state, whatever code path it runs.
            "tests.test_migrations::test_0008_installs_gated_consistency_triggers",
            "tests.test_migrations::test_models_and_0008_trigger_ddl_are_byte_identical",
            "tests.test_migrations::test_batch_recreating_alert_companies_drops_the_triggers",
            "tests.test_gated_row_immutability::test_trigger_blocks_direction_contradiction_on_gated_row",
            "tests.test_gated_row_immutability::test_trigger_blocks_rationale_nulling_on_gated_row",
            "tests.test_gated_row_immutability::test_ungated_legacy_row_updates_still_allowed",
            # T7: application-level guards -- refinement and the one-off
            # repair scripts leave gated rows alone, with positive controls
            # proving the legacy path still works for ungated rows.
            "tests.test_refinement_gated_guard::test_refine_alert_leaves_a_gated_row_byte_identical",
            "tests.test_refinement_gated_guard::test_refine_alert_still_refines_an_ungated_legacy_row",
            "tests.test_refinement_gated_guard::test_reanalyze_recent_skips_a_gated_row",
            "tests.test_refinement_gated_guard::test_fix_direction_contradiction_skips_a_gated_row",
        ],
        "note": "NOT a fixture: 'a worker holding a stale copy mutates a "
                "published row' is a property of the database and the writers, "
                "not of any particular news event. The trigger tests are the "
                "floor (they hold even for a writer that never imports our "
                "code) and the guard tests are the application half.",
    },
    16: {
        "title": "legacy section isolation",
        "fixtures": [],
        "tests": [
            "tests.test_sections_structural::test_legacy_secondary_spellings_stay_isolated_from_the_renamed_tiers",
            "tests.test_sections_structural::test_gated_alert_never_renders_legacy_layers",
            "tests.test_sections_structural::test_gated_alert_legacy_unreachable_even_flag_off",
            "tests.test_sections_structural::test_ungated_alert_keeps_three_tier",
        ],
        "note": "The first pointer is this task's addition and is stated in the "
                "RENAMED tier vocabulary (primary / secondary_ripple / "
                "macro_context): legacy-spelled rows keep rendering, as RIPPLE "
                "sections, never inside a MECH: or MACRO: one.",
    },
    17: {
        "title": "concurrency / idempotency",
        "fixtures": [],
        "tests": [
            "tests.test_pipeline::test_a_second_persist_with_the_same_content_key_returns_the_existing_alert",
            "tests.test_pipeline::test_the_fresh_analysis_path_stamps_the_content_key",
            "tests.test_pipeline::test_the_dedup_reuse_path_claims_no_content_key",
            "tests.test_pipeline::test_two_sessions_racing_one_content_key_converge_on_one_alert",
            "tests.test_gated_row_immutability::test_duplicate_content_key_insert_rejected",
            "tests.test_gated_row_immutability::test_null_content_key_alerts_are_not_constrained",
            "tests.test_gated_row_immutability::test_different_content_keys_on_same_article_coexist",
        ],
        "note": "T4's same-session idempotency tests plus this task's TWO-SESSION "
                "race on a file-backed SQLite database (two distinct DBAPI "
                "connections), where uq_alerts_article_content is the arbiter "
                "and the loser converges through the IntegrityError -> "
                "return-existing path.",
    },
    18: {
        "title": "provider / cache isolation",
        "fixtures": [],
        "tests": [
            "tests.test_provider_cache_isolation::test_gemini_era_cache_row_never_matches_claude_fingerprint",
            "tests.test_provider_cache_isolation::test_duplicate_claude_call_served_from_cache",
            "tests.test_provider_cache_isolation::test_malformed_response_is_never_cached",
            "tests.test_provider_cache_isolation::test_compact_variant_result_not_cached",
            "tests.test_provider_policy::test_fingerprint_includes_provider_and_model",
            "tests.test_provider_policy::test_fallback_does_not_repoint_later_cache_keys_at_groq",
            "tests.test_provider_policy::test_default_router_selects_claude",
            "tests.test_provider_policy::test_gemini_is_not_importable_from_router",
            "tests.test_fallback_quality::test_fingerprint_includes_policy_version_and_strict_flag",
        ],
        "note": "A cache row from one provider/model/policy version must never "
                "serve another. Provider-layer property, exercised against a "
                "fake client -- no fixture and no network can express it.",
    },
    19: {
        "title": "fallback / degraded isolation",
        "fixtures": [],
        "tests": [
            "tests.test_fallback_quality::test_groq_is_never_authoritative",
            "tests.test_fallback_quality::test_claude_router_starts_authoritative",
            "tests.test_fallback_quality::test_compact_context_result_never_cached_under_full_key",
            "tests.test_fallback_quality::test_cache_hit_propagates_stored_quality",
            "tests.test_provider_policy::test_fallback_result_never_cached_as_authoritative",
            "tests.test_provider_policy::test_later_claude_stage_after_a_fallback_is_never_cached",
            "tests.test_provider_policy::test_no_key_and_no_fallback_fails_closed_at_construction",
            "tests.test_budget_fail_closed::test_exceeded_budget_flags_without_verifying",
            "tests.test_v4_invariants::test_inv016_analysis_quality_decides_how_loudly_a_result_speaks",
            "tests.test_v4_invariants::test_inv016_groq_fallback_quality_reaches_the_gate_end_to_end",
        ],
        "note": "A degraded/fallback/budget-exhausted run must never be stored, "
                "replayed or displayed as an authoritative one. The offline "
                "corpus deliberately replays AUTHORITATIVE canned output only, "
                "so the degradation ladder is out of its reach by construction.",
    },
    20: {
        "title": "market / fundamental divergence",
        "fixtures": ["market_fundamental_divergence"],
        "tests": [
            "tests.test_feed_primary_only::test_new_fields_present_including_divergence_for_apollo_case",
            "tests.test_v4_invariants::test_inv001_measurement_never_overwrites_the_fundamental_call",
            "tests.test_v4_invariants::test_inv003_market_observation_is_never_fundamental_evidence",
        ],
        "note": "Split on purpose, because the scenario spans two SEPARATE "
                "truths (INV-001/INV-002). The fixture pins the analysis half "
                "-- a negative fundamental primary published unmoved by a "
                "positive reaction, and a candidate whose only basis is the "
                "price move rejected outright. The feed test pins the "
                "measurement half (excess move -> reaction_direction -> the "
                "divergence sentence), which needs price bars this corpus "
                "carries none of by design.",
    },
}


def _resolve(pointer: str):
    """`module::function` -> the function object, imported for real. Raises
    on a stale pointer -- which is the whole point of this module."""
    module_path, _, attribute = pointer.partition("::")
    module = importlib.import_module(module_path)
    return getattr(module, attribute)


def test_every_blueprint_32_scenario_is_indexed():
    """All twenty, numbered 1..20, no gaps and no strays."""
    assert sorted(BLUEPRINT_32_INDEX) == list(range(1, 21))


@pytest.mark.parametrize("number", sorted(BLUEPRINT_32_INDEX))
def test_every_scenario_names_at_least_one_artifact(number):
    """No scenario may be indexed with an empty entry: a title without an
    artifact is a coverage claim with nothing behind it."""
    entry = BLUEPRINT_32_INDEX[number]
    assert entry["title"].strip()
    assert entry["fixtures"] or entry["tests"], (
        f"§32 scenario {number} ({entry['title']}) names no fixture and no test"
    )


@pytest.mark.parametrize(
    "fixture_id",
    sorted({f for entry in BLUEPRINT_32_INDEX.values() for f in entry["fixtures"]}),
)
def test_indexed_fixture_exists_and_is_labeled(fixture_id):
    """The fixture file is real, parses, and carries the ground-truth block
    the benchmark scores against -- an unlabeled fixture would run and score
    nothing."""
    path = FIXTURE_DIR / f"{fixture_id}.json"
    assert path.exists(), f"§32 index points at missing fixture {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload.get("ground_truth"), f"{fixture_id} carries no ground_truth"
    assert payload.get("article", {}).get("title")


@pytest.mark.parametrize(
    "pointer",
    sorted({t for entry in BLUEPRINT_32_INDEX.values() for t in entry["tests"]}),
)
def test_indexed_test_pointer_resolves(pointer):
    """IMPORT-CHECKED: the module imports and the named function exists on
    it. A renamed or deleted test fails here rather than silently leaving a
    §32 scenario uncovered."""
    resolved = _resolve(pointer)
    assert callable(resolved), f"{pointer} resolved to a non-callable"


def test_batch_b_systemic_scenarios_are_not_faked_as_fixtures():
    """Scenarios 15-19 are infrastructural: a benchmark corpus replays canned
    ANALYSIS output through the engine and cannot assert anything about DB
    triggers, session races, provider caches or the degradation ladder. If a
    fixture ever shows up under one of them, someone has almost certainly
    written a fixture that pretends to test something it structurally
    cannot."""
    for number in (15, 16, 17, 18, 19):
        assert BLUEPRINT_32_INDEX[number]["fixtures"] == [], (
            f"§32 scenario {number} is systemic and must be pinned by tests, "
            f"not by a benchmark fixture"
        )


def test_every_corpus_fixture_that_this_index_claims_is_actually_in_the_corpus():
    """The benchmark loads EVERY json in the corpus directory, so an indexed
    id that does not appear in that listing would be scored under a
    different name (or not at all)."""
    from tools.offline_benchmark import load_fixtures

    corpus_ids = {fixture["id"] for fixture in load_fixtures()}
    indexed = {f for entry in BLUEPRINT_32_INDEX.values() for f in entry["fixtures"]}
    assert indexed <= corpus_ids, f"indexed but not in the corpus: {sorted(indexed - corpus_ids)}"
