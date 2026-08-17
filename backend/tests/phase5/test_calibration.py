"""TASK 5.3 -- calibrated confidence, DISABLED until a corpus exists.

The phase file's mandatory tests:
  - ECE <= 0.05 on holdout (skipped until corpus exists)
  - OOD feature vector sets in_distribution=false and caps tier
  - no LLM-sourced confidence value exists anywhere (grep + ast scan)
  - with calibration disabled, calibrated_p is null and UI degrades correctly

THE RULE THIS FILE EXISTS TO PIN: **disabled beats fake**. The isotonic
fitting, the reliability/ECE/Brier reporting and the Mahalanobis gate are all
implemented and their MATH is proved here on obviously-fake `_fixture`
labels. None of it can be switched on: activation needs a labeled corpus
above a configured minimum AND an ACTIVE `calibration_model` row, the corpus
is empty, and the table refuses an active row outright.
"""
import ast
import re
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.phase5.conftest import (
    BACKEND, code_lines, imported_modules, package_sources,
)
from tests.phase5.helpers import clean_primary_draft, impact_with_empirical

CALIBRATION = BACKEND / "app" / "analysis" / "calibration"
V5_PACKAGES = (
    BACKEND / "app" / "core",
    BACKEND / "app" / "analysis" / "sensitivity",
    BACKEND / "app" / "analysis" / "policy",
    BACKEND / "app" / "analysis" / "empirical",
    BACKEND / "app" / "analysis" / "calibration",
    BACKEND / "app" / "analysis" / "surprise",
)

PROVIDER_MODULES = (
    "anthropic", "openai", "groq", "google", "google.generativeai",
    "transformers", "httpx",
    "app.analysis.claude_client",
    "app.analysis.impact_graph.claude_json",
    "app.analysis.impact_graph.gemini_json",
    "app.analysis.impact_graph.router",
    "app.analysis.impact_graph.prompts",
    "app.analysis.impact_graph.engine",
    "app.analysis.cascade",
    "app.analysis.refinement",
    "app.analysis.verification",
)

# V4 legacy, exempt by an EXACT baseline -- the same ratchet pattern Phase 2
# used for materiality-assigning prompts. These three files ask a model for a
# confidence number today; none of their answers reaches a CompanyImpact (see
# `test_no_llm_confidence_reaches_the_canonical_record`). Adding a
# confidence-asking prompt anywhere else, or another one inside these files,
# fails this test.
V4_CONFIDENCE_PROMPT_BASELINE = {
    "app/analysis/impact_graph/prompts.py": 11,
    "app/ingest/filings/llm_extract.py": 1,
    "app/reasoning/rulebook.py": 1,
}

CONFIDENCE_LANGUAGE = re.compile(r"confidence", re.IGNORECASE)
PROMPT_LIKE_NAME = re.compile(r"PROMPT|SYSTEM|INSTRUCTION|TEMPLATE|RULES|ONTOLOGY")


# --- the feature vector -----------------------------------------------------

def test_the_feature_vector_is_exactly_the_spec_list():
    from app.analysis.calibration.features import FEATURE_NAMES

    assert set(FEATURE_NAMES) == {
        "materiality_p50", "band_width", "sign_consistency", "graph_distance",
        "directness", "evidence_grade", "weakest_link_kind", "n_bound_claims",
        "param_proxy_fraction", "empirical_status", "empirical_n", "empirical_p",
        "objection_count_blocking", "objection_count_major", "objection_count_warn",
        "event_status", "shock_magnitude_confidence", "surprise_score",
        "sector_id", "exposure_freshness_days"}


def test_every_feature_is_deterministic_and_none_of_them_is_a_model_score():
    from app.analysis.calibration.features import build_features

    impact = impact_with_empirical()
    first = build_features(impact)
    second = build_features(impact)
    assert first == second
    assert not any("llm" in str(name).lower() or "model" in str(name).lower()
                   for name in first)


def test_a_feature_that_is_not_known_stays_none_rather_than_becoming_zero():
    from app.analysis.calibration.features import build_features

    features = build_features(impact_with_empirical())
    # no computed band on this record: the band features are UNKNOWN, and an
    # unknown is not a zero (a zero band is a claim of perfect precision).
    assert features["band_width"] is None
    assert features["materiality_p50"] is None


def test_vectorising_an_incomplete_feature_set_is_refused():
    from app.analysis.calibration.features import FeatureUnavailable, build_features, vectorize

    with pytest.raises(FeatureUnavailable):
        vectorize(build_features(impact_with_empirical()))


# --- the math, proved on obviously fake labels ------------------------------

def test_isotonic_regression_pools_adjacent_violators():
    """x=[1,2,3,4], y=[0,1,0,1] -> [0, 0.5, 0.5, 1] by hand: the (1,0) pair at
    x=2,3 violates monotonicity and pools to its mean."""
    from app.analysis.calibration.isotonic import fit_isotonic

    model = fit_isotonic([1.0, 2.0, 3.0, 4.0], [0.0, 1.0, 0.0, 1.0])
    assert model.predict(1.0) == pytest.approx(0.0, abs=1e-12)
    assert model.predict(2.0) == pytest.approx(0.5, abs=1e-12)
    assert model.predict(3.0) == pytest.approx(0.5, abs=1e-12)
    assert model.predict(4.0) == pytest.approx(1.0, abs=1e-12)


def test_the_isotonic_fit_is_monotone_non_decreasing():
    from app.analysis.calibration.isotonic import fit_isotonic

    model = fit_isotonic([1.0, 2.0, 3.0, 4.0, 5.0], [0.0, 1.0, 0.0, 1.0, 1.0])
    values = [model.predict(x) for x in (1.0, 2.0, 3.0, 4.0, 5.0)]
    assert values == sorted(values)


def test_brier_and_ece_on_a_hand_computed_case():
    from app.analysis.calibration.metrics import brier_score, expected_calibration_error

    assert brier_score([0.0, 0.0, 1.0, 1.0], [0, 0, 1, 1]) == pytest.approx(0.0)
    assert brier_score([0.5] * 4, [1, 0, 0, 0]) == pytest.approx(0.25)
    # one bin, mean prob 0.5, observed frequency 0.25 -> |0.5 - 0.25| = 0.25
    assert expected_calibration_error([0.5] * 4, [1, 0, 0, 0], bins=10) == \
        pytest.approx(0.25)


def test_the_reliability_diagram_reports_per_bin_counts():
    from app.analysis.calibration.metrics import reliability_diagram

    diagram = reliability_diagram([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1], bins=2)
    assert sum(bin_["count"] for bin_ in diagram) == 4
    assert all("mean_predicted" in bin_ and "observed" in bin_ for bin_ in diagram)


@pytest.mark.skip(reason=(
    "no labeled corpus exists (DATA_GAPS §1 / §9). Calibration ships DISABLED "
    "and calibrated_p is null; fitting on synthetic labels is forbidden by the "
    "phase file's own DO NOT, so there is nothing to measure an ECE on. "
    "Un-skip when the Phase 7 corpus lands."))
def test_expected_calibration_error_is_within_five_percent_on_holdout():
    from app.analysis.calibration.metrics import expected_calibration_error
    from app.analysis.calibration.registry import load_labeled_corpus

    corpus = load_labeled_corpus()
    assert expected_calibration_error(
        [row.predicted for row in corpus.holdout],
        [row.label for row in corpus.holdout], bins=10) <= 0.05


# --- the out-of-distribution gate ------------------------------------------

def _manifold():
    from app.analysis.calibration.ood import fit_manifold

    rows = [(float(i), float(i) + 0.5) for i in range(50)]
    return fit_manifold(rows)


def test_a_row_inside_the_fitted_manifold_is_in_distribution():
    from app.analysis.calibration.ood import in_distribution

    assert in_distribution((10.0, 10.5), _manifold()) is True


def test_a_row_far_outside_the_fitted_manifold_is_not():
    from app.analysis.calibration.ood import in_distribution

    assert in_distribution((10.0, -400.0), _manifold()) is False


def test_with_no_fitted_manifold_in_distribution_is_unknown_not_false():
    """The absence of a model must not silently cap every company at ripple.
    Unknown is unknown; it is not evidence of novelty."""
    from app.analysis.calibration.ood import in_distribution

    assert in_distribution((1.0, 2.0), None) is None


def test_out_of_distribution_caps_the_tier_at_secondary():
    from app.core.config_loader import load_gate_config
    from app.core.gates import evaluate

    config = load_gate_config()
    assert evaluate(clean_primary_draft(), config).tier == "PRIMARY"
    capped = evaluate(clean_primary_draft(in_distribution=False), config)
    assert capped.tier == "SECONDARY_RIPPLE"


def test_unknown_in_distribution_does_not_cap_the_tier():
    from app.core.config_loader import load_gate_config
    from app.core.gates import evaluate

    config = load_gate_config()
    assert evaluate(clean_primary_draft(in_distribution=None),
                    config).tier == "PRIMARY"


# --- disabled, and structurally unable to activate --------------------------

def test_calibration_ships_disabled():
    from app.analysis.calibration.config import load_calibration_config

    assert load_calibration_config().enabled is False


def test_calibrated_p_is_null_with_no_active_model(phase5_session):
    from app.analysis.calibration.confidence import calibrated_p
    from app.analysis.calibration.registry import active_model

    assert active_model(phase5_session) is None
    assert calibrated_p(impact_with_empirical(), model=None) is None


def test_the_calibration_model_table_ships_empty(phase5_session):
    assert phase5_session.execute(text(
        "SELECT count(*) FROM calibration_model")).scalar() == 0


def test_a_model_cannot_be_recorded_as_active(phase5_session):
    from app.analysis.calibration.registry import CalibrationActivationRefused, record_model

    with pytest.raises(CalibrationActivationRefused):
        record_model(phase5_session, model_version="fixture-v1", method="isotonic",
                     corpus_size=10, fitted_at=None, is_active=True)


def test_activation_is_refused_below_the_configured_corpus_minimum(phase5_session):
    from app.analysis.calibration.config import load_calibration_config
    from app.analysis.calibration.registry import can_activate

    minimum = load_calibration_config().min_corpus_size
    assert minimum > 0
    assert can_activate(corpus_size=minimum - 1) is False
    # ...and even at the minimum, activation still needs an ACTIVE row, which
    # the table refuses. Both conditions, not either.
    assert phase5_session.execute(text(
        "SELECT count(*) FROM calibration_model WHERE is_active = 1")).scalar() == 0


def test_fitting_on_fixture_labels_produces_a_model_that_cannot_be_persisted(phase5_session):
    """The math may be exercised on fake labels. The RESULT may not become a
    model anything reads -- 'do not ship a fitted-looking model trained on
    synthetic labels'."""
    from app.analysis.calibration.registry import CalibrationActivationRefused, record_model

    with pytest.raises(CalibrationActivationRefused):
        record_model(phase5_session, model_version="fixture-v1", method="isotonic",
                     corpus_size=4, fitted_at=None, is_active=False,
                     fixture_labels=True)


# --- the UI contract --------------------------------------------------------

def test_with_calibration_disabled_the_payload_carries_a_null_and_degrades():
    from app.analysis.calibration.confidence import confidence_block

    block = confidence_block(impact_with_empirical())
    assert block["calibrated_p"] is None
    assert block["degraded"] is True
    assert block["evidence_grade"] == "A"
    assert "reason" in block


def test_the_degraded_line_shows_grade_and_band_instead_of_a_number():
    from app.analysis.calibration.confidence import confidence_block, confidence_line

    line = confidence_line(confidence_block(impact_with_empirical()))
    assert "not calibrated" in line.lower()
    assert "evidence" in line.lower()
    assert "0." not in line, "a degraded line must not show a probability"


def test_a_confidence_number_without_its_band_and_driver_is_refused():
    """§13.3 / the phase file's DO NOT: never a bare number."""
    from app.analysis.calibration.confidence import ConfidenceRenderError, confidence_line

    with pytest.raises(ConfidenceRenderError):
        confidence_line({"calibrated_p": 0.71, "degraded": False,
                         "band": None, "dominant_driver": None,
                         "evidence_grade": "A"})


# --- no LLM-sourced confidence ---------------------------------------------

@pytest.mark.parametrize("provider", PROVIDER_MODULES)
def test_no_v5_module_imports_a_provider(provider):
    for package in V5_PACKAGES:
        for path in package_sources(package):
            for module in imported_modules(path):
                assert module != provider and not module.startswith(provider + "."), (
                    f"{path.relative_to(BACKEND)} imports {module}")


def test_no_calibration_module_names_a_model_or_defines_a_prompt():
    banned = re.compile(r"\bprompt\b|claude|gpt-|gemini|llama|anthropic", re.IGNORECASE)
    for path in package_sources(CALIBRATION):
        for number, line in code_lines(path):
            assert not banned.search(line), f"{path.name}:{number}: {line.strip()}"


def scan_confidence_prompt_offenders(root: Path) -> dict[str, int]:
    """{path relative to `root`: how many prompt-like strings ask a model for
    a confidence}. Shared by the ratchet and by its self-test, so the two can
    never disagree about what the rule is."""
    offenders: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        if "tests" in path.parts or ".venv" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:                       # pragma: no cover
            continue
        relative = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target.id]
            else:
                continue
            if node.value is None or not any(
                    PROMPT_LIKE_NAME.search(t.upper()) for t in targets):
                continue
            for sub in ast.walk(node.value):
                text_ = sub.value if isinstance(sub, ast.Constant) and isinstance(
                    sub.value, str) else None
                if text_ and CONFIDENCE_LANGUAGE.search(text_):
                    offenders[relative] = offenders.get(relative, 0) + 1
    return offenders


def test_no_new_prompt_asks_a_model_for_a_confidence_number():
    offenders = scan_confidence_prompt_offenders(BACKEND)
    new_files = sorted(set(offenders) - set(V4_CONFIDENCE_PROMPT_BASELINE))
    assert not new_files, (
        f"a prompt-like template outside the V4 baseline asks for a "
        f"confidence: {new_files}")
    assert offenders == V4_CONFIDENCE_PROMPT_BASELINE, (
        "the count of confidence-asking strings inside an exempt file "
        f"changed: {V4_CONFIDENCE_PROMPT_BASELINE} -> {offenders}. If language "
        "was ADDED, remove it. If it was REMOVED, shrink the baseline in this "
        "file -- deliberately.")


def test_the_confidence_ratchet_actually_fires(tmp_path):
    (tmp_path / "fake_module.py").write_text(
        'SYSTEM_RULES = """Report your confidence 0-1 for each company."""\n',
        encoding="utf-8")
    assert scan_confidence_prompt_offenders(tmp_path) == {"fake_module.py": 1}


def _keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from _keys(value)


def test_no_llm_confidence_reaches_the_canonical_record():
    """The positive half of the claim: the canonical record has no confidence
    field at all, and its serialization emits none."""
    from app.core.reducer import CompanyImpact, serialize_company_impact

    assert not [f for f in CompanyImpact.__dataclass_fields__ if "confidence" in f]
    payload = serialize_company_impact(impact_with_empirical())
    offenders = [k for k in _keys(payload) if "confidence" in k.lower()]
    assert offenders == [], offenders
    assert "calibrated_p" not in list(_keys(payload))


@pytest.mark.parametrize("package", [p for p in V5_PACKAGES],
                         ids=lambda p: p.name)
def test_the_ledgers_llm_extraction_confidence_never_reaches_a_v5_module(package):
    """The one LLM-sourced confidence that still exists in this repo is
    `company_exposure.confidence`, written from an extractor's
    `extraction_confidence` at review time. It is a REVIEW-QUEUE TRIAGE score
    (`app/ledger/review.py` ranks proposals by market cap x (1 - confidence))
    and it must never become an input to a number.

    REVIEW ROUND 1 (m-14): widened from the sensitivity package to ALL SIX V5
    packages. Two allowances, both named rather than pattern-matched:

      * `shock_magnitude_confidence` is a §7.4 GATE INPUT about the EVENT, not
        a per-company model score, and it is None on the deployed path;
      * `app/analysis/calibration/*` is the module that DEFINES the confidence
        surface (and emits null); banning the word there would ban the fix.
    """
    allowed = ("shock_magnitude_confidence", "min_shock_magnitude_confidence",
               "sign_consistency")
    for path in package_sources(package):
        for number, line in code_lines(path):
            lowered = line.lower()
            assert "extraction_confidence" not in lowered, (
                f"{path.name}:{number} reads the extractor's confidence")
            if package.name == "calibration":
                continue
            if "confidence" not in lowered:
                continue
            assert any(name in line for name in allowed), (
                f"{path.name}:{number} reads a confidence: {line.strip()}")


def test_the_signal_bus_has_no_confidence_carrying_payload_key():
    from app.core.signals import _SCHEMAS

    for kind, schema in _SCHEMAS.items():
        assert not [key for key in schema if "confidence" in key], (
            f"{kind} carries a confidence key")
