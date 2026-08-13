"""Tests for the offline benchmark harness itself (corrective-v4 Task 21).

A benchmark that scores itself wrong is worse than no benchmark: it
manufactures confidence. These tests pin the harness arithmetic on
SYNTHETIC decision sets (no engine, no DB, no fixtures) so a scoring bug
cannot hide behind a passing corpus, plus one end-to-end smoke that the
smallest real fixture actually runs and emits its artifacts.
"""
import json
import sys

import pytest

from app.config import settings
from tools.offline_benchmark import (
    DEFAULT_OUT_DIR, load_fixtures, run_fixture, score, stub_network,
)


def _entry(ticker, tier, effect="negative", **overrides):
    payload = {
        "ticker": ticker, "display_tier": tier, "gate_state": (
            "DISPLAY_ELIGIBLE" if tier != "excluded" else "REJECT_LOW_MATERIALITY"),
        "rejection_reason": None, "gates_passed": [], "evidence_class": "ARTICLE_SUBJECT",
        "evidence_tier": "SUBJECT", "materiality_grade": "HIGH", "economic_effect": effect,
        "causal_distance": 1, "causal_parent_type": "economic_node",
        "causal_parent_id": "some_node", "mechanism": "m", "rationale": "r",
        "materiality": 0.7, "confidence": 0.8, "discovery_source": "subject",
        "counterfactual": "SUPPORTED", "resolved": True, "decision_notes": None,
    }
    payload.update(overrides)
    return payload


def _observation(entries, ground_truth, **overrides):
    payload = {
        "id": "synthetic", "error": None, "title": "t", "facts": "f",
        "event_label": "e", "analysis_quality": "authoritative", "stages": [],
        "entries": entries, "edges": [], "sections": [], "ghost_tickers": [],
        "unresolved_eligible": [], "universe_tickers": [], "explanation_checked": 0,
        "explanation_faithful": 0, "ground_truth": ground_truth,
    }
    payload.update(overrides)
    return payload


# --- company precision / recall / false positives -------------------------

def test_precision_recall_and_false_positive_rate_on_a_known_decision_set():
    """Two published companies of which one is expected, one expected
    company missed entirely, and one correctly-excluded candidate."""
    observation = _observation(
        entries=[
            _entry("GOOD.NS", "primary"),
            _entry("BAD.NS", "primary"),
            _entry("DROPPED.NS", "excluded"),
        ],
        ground_truth={
            "expected_primary": {"GOOD.NS": "negative", "MISSED.NS": "negative"},
            "expected_rejected": ["DROPPED.NS"],
        },
    )
    metrics = score([observation])["metrics"]

    assert metrics["company_precision"] == {"value": 0.5, "hits": 1, "total": 2}
    assert metrics["company_recall"] == {"value": 0.5, "hits": 1, "total": 2}
    # 1 false positive out of 3 candidates that walked the gate.
    assert metrics["false_positive_rate"] == {"value": 1 / 3, "hits": 1, "total": 3}
    assert metrics["rejection_recall"]["value"] == 1.0


def test_allow_secondary_ticker_is_not_a_false_positive():
    observation = _observation(
        entries=[_entry("DEEP.NS", "secondary_deep_dive")],
        ground_truth={"expected_primary": {}, "allow_secondary": ["DEEP.NS"]},
    )
    metrics = score([observation])["metrics"]

    assert metrics["company_precision"]["value"] == 1.0
    assert metrics["false_positive_rate"]["value"] == 0.0


# --- primary_feed_precision: the release metric ---------------------------

def test_primary_feed_precision_counts_only_the_primary_tier():
    """A wrong company parked in the deep dive is a company_precision
    problem; it must NOT enter the primary-feed number, which is the one
    the release gate reads."""
    observation = _observation(
        entries=[
            _entry("GOOD.NS", "primary"),
            _entry("WRONG.NS", "secondary_deep_dive"),
        ],
        ground_truth={"expected_primary": {"GOOD.NS": "negative"}},
    )
    metrics = score([observation])["metrics"]

    assert metrics["primary_feed_precision"] == {"value": 1.0, "hits": 1, "total": 1}
    assert metrics["company_precision"]["value"] == 0.5   # the deep dive still counts here


def test_primary_feed_precision_fails_a_right_company_with_the_wrong_effect():
    """A correct ticker published with the wrong fundamental direction is a
    wrong published claim, not a partial credit."""
    observation = _observation(
        entries=[_entry("GOOD.NS", "primary", effect="positive")],
        ground_truth={"expected_primary": {"GOOD.NS": "negative"}},
    )
    metrics = score([observation])["metrics"]

    assert metrics["primary_feed_precision"]["value"] == 0.0
    assert metrics["fundamental_direction_accuracy"]["value"] == 0.0


def test_legacy_secondary_spelling_counts_as_published():
    observation = _observation(
        entries=[_entry("OLD.NS", "secondary")],
        ground_truth={"expected_primary": {}, "allow_secondary": []},
    )
    metrics = score([observation])["metrics"]

    assert metrics["company_precision"] == {"value": 0.0, "hits": 0, "total": 1}


# --- mixed_accuracy: the auto-pass bug, pinned dead ------------------------

def test_mixed_accuracy_is_not_awarded_for_a_directional_prediction():
    """THE regression this metric exists for: a 'mixed' label demands a
    'mixed' prediction. Calling a genuinely two-sided story negative is
    wrong, however plausible the direction."""
    observation = _observation(
        entries=[_entry("BOTH.NS", "primary", effect="negative")],
        ground_truth={"expected_primary": {"BOTH.NS": "mixed"}},
    )
    metrics = score([observation])["metrics"]

    assert metrics["mixed_accuracy"] == {"value": 0.0, "hits": 0, "total": 1}


def test_mixed_accuracy_is_na_not_100_percent_when_nothing_is_labeled_mixed():
    """An empty denominator must report N/A. Scoring it 1.0 is exactly how
    an unmeasured metric turns into a green number on a release dashboard."""
    observation = _observation(
        entries=[_entry("PLAIN.NS", "primary")],
        ground_truth={"expected_primary": {"PLAIN.NS": "negative"}},
    )
    metrics = score([observation])["metrics"]

    assert metrics["mixed_accuracy"] == {"value": None, "hits": 0, "total": 0}


def test_mixed_accuracy_passes_only_on_a_mixed_prediction():
    observation = _observation(
        entries=[_entry("BOTH.NS", "primary", effect="mixed")],
        ground_truth={"expected_primary": {"BOTH.NS": "mixed"}},
    )
    metrics = score([observation])["metrics"]

    assert metrics["mixed_accuracy"]["value"] == 1.0


# --- abstention / entity / section ----------------------------------------

def test_abstention_is_correct_only_when_the_primary_feed_is_empty():
    published = _observation(
        entries=[_entry("ANY.NS", "primary")],
        ground_truth={"expected_primary": {}, "expect_abstention": True},
    )
    abstained = _observation(
        entries=[_entry("ANY.NS", "excluded")],
        ground_truth={"expected_primary": {}, "expect_abstention": True},
    )
    assert score([published])["metrics"]["abstention_precision"]["value"] == 0.0
    assert score([abstained])["metrics"]["abstention_precision"]["value"] == 1.0


def test_abstention_allows_a_deep_dive_but_never_a_primary():
    """Abstention is a claim about the FEED, not about the whole analysis:
    a deep-dive row is still an abstention from leading with a claim."""
    observation = _observation(
        entries=[_entry("DEEP.NS", "secondary_deep_dive")],
        ground_truth={"expected_primary": {}, "allow_secondary": ["DEEP.NS"],
                      "expect_abstention": True},
    )
    assert score([observation])["metrics"]["abstention_precision"]["value"] == 1.0


def test_entity_accuracy_fails_on_a_ghost_or_an_unresolved_eligible_row():
    ghost = _observation([], {}, ghost_tickers=["NOTREAL.NS"])
    unresolved = _observation([], {}, unresolved_eligible=["PHANTOM.NS"])
    clean = _observation([], {})

    assert score([ghost])["metrics"]["entity_accuracy"]["value"] == 0.0
    assert score([unresolved])["metrics"]["entity_accuracy"]["value"] == 0.0
    assert score([clean])["metrics"]["entity_accuracy"]["value"] == 1.0


def test_section_with_a_disallowed_member_does_not_count_as_present():
    """A right-looking title full of wrong companies is not a correct
    section -- membership is part of the claim."""
    observation = _observation(
        entries=[_entry("GOOD.NS", "primary"), _entry("BAD.NS", "primary")],
        ground_truth={
            "expected_primary": {"GOOD.NS": "negative"},
            "expected_sections": [{"effect": "negative", "label_contains": "crude"}],
        },
        sections=[{"title": "Negative - crude-linked", "icon": "lose",
                   "relationship": "MECH:crude-linked",
                   "tickers": ["GOOD.NS", "BAD.NS"]}],
    )
    assert score([observation])["metrics"]["section_accuracy"]["value"] == 0.0


def test_market_measurement_accuracy_reports_na_with_a_reason():
    metrics = score([_observation([], {})])["metrics"]
    payload = metrics["market_measurement_accuracy"]

    assert payload["value"] is None
    assert "INV-002" in payload["reason"]


# --- corpus-level accumulation --------------------------------------------

def test_metrics_accumulate_across_events_by_decision_not_by_article():
    """One article with four correct calls must outweigh one article with a
    single wrong call -- the corpus measures decisions."""
    many = _observation(
        entries=[_entry(f"C{i}.NS", "primary") for i in range(4)],
        ground_truth={"expected_primary": {f"C{i}.NS": "negative" for i in range(4)}},
    )
    one = _observation(
        entries=[_entry("W.NS", "primary", effect="positive")],
        ground_truth={"expected_primary": {"W.NS": "negative"}},
    )
    metrics = score([many, one])["metrics"]

    assert metrics["primary_feed_precision"] == {"value": 0.8, "hits": 4, "total": 5}


# --- end-to-end smoke on the smallest real fixture ------------------------

@pytest.fixture()
def _restore_pipeline_stubs(monkeypatch):
    """stub_network() patches app.pipeline attributes permanently; take the
    same monkeypatch locks first so pytest restores the real functions for
    every test that runs after this one."""
    import app.pipeline as pipeline

    for name in ("measure_company_move", "get_or_fetch_financial_snapshot",
                 "fetch_og_image", "fetch_pending_full_text",
                 "send_pending_notifications"):
        monkeypatch.setattr(pipeline, name, getattr(pipeline, name))
    monkeypatch.setattr(pipeline.manager, "broadcast_sync", pipeline.manager.broadcast_sync)
    stub_network()


def test_smallest_fixture_runs_end_to_end_and_emits_artifacts(
        tmp_path, monkeypatch, _restore_pipeline_stubs):
    fixtures = load_fixtures()
    assert len(fixtures) >= 22, "the labeled corpus lost fixtures"
    smallest = min(fixtures, key=lambda f: len(f.get("universe", [])))

    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)
    observation = run_fixture(smallest)

    assert observation["error"] is None
    assert observation["entries"], "the engine produced no candidates at all"
    scored = score([observation])
    assert scored["metrics"]["entity_accuracy"]["value"] == 1.0
    assert not scored["per_event"][0]["failures"], scored["per_event"][0]["failures"]

    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "offline_benchmark.py", "--only", smallest["id"],
        "--out-dir", str(out_dir), "--quiet",
    ])
    from tools import offline_benchmark

    assert offline_benchmark.main() == 0
    results_path = out_dir / "offline_results.json"
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    assert payload["fixtures"] == 1
    assert payload["strict_mode"] is True
    assert set(payload["metrics"]) >= {
        "company_precision", "company_recall", "false_positive_rate",
        "primary_feed_precision", "fundamental_direction_accuracy", "mixed_accuracy",
        "mechanism_accuracy", "causal_distance_accuracy", "materiality_accuracy",
        "section_accuracy", "abstention_precision", "entity_accuracy",
        "evidence_accuracy", "market_measurement_accuracy", "explanation_faithfulness",
    }
    review = out_dir / "reviews" / f"{smallest['id']}.md"
    assert "Reviewer label" in review.read_text(encoding="utf-8")
    # The real output directory must be untouched by a tmp_path run.
    assert results_path != DEFAULT_OUT_DIR / "offline_results.json"
