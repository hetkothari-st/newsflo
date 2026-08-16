"""TASK 0.4 tests -- the publication gate is config-driven code with no LLM.

docs/v5/01_PHASE_0_canonical_truth.md TESTS/test_gates_no_llm.py:
  * ast scan: gates.py imports nothing from the provider surface
  * PRIMARY failure does not produce SECONDARY without independent evaluation

REPO MAPPING (controller adaptation): the spec's `newsflo/providers` is this
repo's `app.analysis.claude_client`, `app.analysis.impact_graph.claude_json`,
`app.analysis.impact_graph.gemini_json`, `app.reasoning`, and any Groq
client -- the ast scan targets THOSE module names.
"""
import ast
from pathlib import Path

import pytest

from tests.phase0 import fixtures

APP = Path(__file__).resolve().parents[2] / "app"
CORE = APP / "core"
OUTPUT = APP / "output"

# This repo's provider surface (the spec's `newsflo/providers`).
PROVIDER_MODULES = (
    "app.analysis.claude_client",
    "app.analysis.impact_graph.claude_json",
    "app.analysis.impact_graph.gemini_json",
    "app.analysis.impact_graph.router",
    "app.reasoning",
    "anthropic", "openai", "groq",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def _offenders(path: Path) -> set[str]:
    return {name for name in _imports(path)
            if any(name == provider or name.startswith(provider + ".")
                   for provider in PROVIDER_MODULES)}


def test_gates_module_imports_no_provider_code():
    assert not _offenders(CORE / "gates.py")


def test_no_module_under_app_core_imports_provider_code():
    """Phase file DO NOT: 'Do not add an LLM call anywhere in newsflo/core/'.
    Scans EVERY module in the package, including the impure ones."""
    for path in sorted(CORE.glob("*.py")):
        assert not _offenders(path), f"{path.name} imports provider code"


def test_no_module_under_app_core_calls_an_llm():
    """Belt and braces against an inline/deferred import: no source file in
    app/core may even mention a provider client construction."""
    for path in sorted(CORE.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for needle in ("anthropic.", "Anthropic(", "ClaudeJSONClient",
                       "GeminiJSON", "chat.completions", "messages.create"):
            assert needle not in source, (
                f"app/core/{path.name} references `{needle}` -- no LLM call "
                "may exist anywhere under app/core/")


def test_gate_config_is_loaded_from_yaml_not_hardcoded():
    from app.core.config_loader import GATES_CONFIG_PATH, load_gate_config

    assert GATES_CONFIG_PATH.exists(), "backend/config/gates.yaml is missing"
    config = load_gate_config()
    assert config.primary.max_graph_distance == 2
    assert config.primary.min_sign_consistency == pytest.approx(0.90)
    assert config.secondary.max_graph_distance == 3
    assert config.secondary.min_sign_consistency == pytest.approx(0.60)


def _draft(**overrides):
    from app.core.gates import ImpactDraft

    base = dict(
        entity_status="ACTIVE", entity_ambiguous=False, exposure_stale=False,
        materiality_bucket="HIGH", graph_distance=1, directness="DIRECT",
        evidence_grade="A", weakest_link=None, sign_consistency=1.0,
        empirical_status="NO_DATA", objections=(), unbound_claim_ids=(),
        verifier_status="PASS", adv_20d_inr=None, event_status="CONFIRMED",
        shock_magnitude_confidence=None, mechanism_id="crude_input_cost",
        net_effect="NEGATIVE",
    )
    base.update(overrides)
    return ImpactDraft(**base)


def test_primary_failure_does_not_demote_to_secondary_by_itself():
    """Master context invariant 5. `evaluate_primary` returns a FAILED
    result; nothing in it names a tier, and the secondary verdict comes only
    from a separate call over the same draft."""
    from app.core.gates import evaluate_primary, evaluate_secondary

    config = fixtures.reducer_config().gate_config
    draft = _draft(sign_consistency=0.7)  # fails PRIMARY's 0.90 floor

    primary = evaluate_primary(draft, config)
    assert primary.tier is None
    assert primary.rejection_reason is not None
    assert any(not rule.passed for rule in primary.gate_trace)

    secondary = evaluate_secondary(draft, config)
    assert secondary.tier == "SECONDARY_RIPPLE"
    # The two walks are independent: the secondary trace is not a suffix of
    # the primary one, and it re-evaluated sign consistency on its own floor.
    assert any(rule.name == "sign_consistency" and rule.passed
               for rule in secondary.gate_trace)


def test_failing_both_walks_is_rejected_not_silently_secondary():
    from app.core.gates import evaluate

    config = fixtures.reducer_config().gate_config
    result = evaluate(_draft(sign_consistency=0.1, materiality_bucket="LOW",
                             evidence_grade="E", graph_distance=5), config)
    assert result.tier == "REJECTED"
    assert result.rejection_reason


def test_hard_blocks_are_evaluated_before_any_tier():
    from app.core.gates import evaluate

    config = fixtures.reducer_config().gate_config
    for override, reason in (
        ({"entity_ambiguous": True}, "ENTITY_AMBIGUOUS"),
        ({"entity_status": "DELISTED"}, "ENTITY_NOT_ACTIVE"),
        ({"materiality_bucket": "NO_MATERIAL_IMPACT"}, "NO_MATERIAL_IMPACT"),
        ({"unbound_claim_ids": ("cl_x",)}, "UNBOUND_CLAIM"),
        ({"exposure_stale": True}, "EXPOSURE_STALE"),
        ({"objections": ({"severity": "BLOCKING", "sustained": True},)},
         "SUSTAINED_BLOCKING_OBJECTION"),
    ):
        result = evaluate(_draft(**override), config)
        assert result.tier == "REJECTED", override
        assert result.rejection_reason == reason, override


def test_a_company_draft_is_never_given_macro_context():
    """Master context invariant 6: MACRO_CONTEXT may never carry a company
    list. A per-company draft that would only qualify as macro is REJECTED
    with an explicit reason rather than being tagged MACRO_CONTEXT."""
    from app.core.gates import evaluate

    config = fixtures.reducer_config().gate_config
    result = evaluate(_draft(shock_magnitude_confidence=0.2), config)
    assert result.tier == "REJECTED"
    assert result.rejection_reason == "MACRO_CONTEXT_HAS_NO_COMPANIES"


def test_secondary_ripple_requires_a_mechanism_id():
    """Master context invariant 7."""
    from app.core.gates import evaluate

    config = fixtures.reducer_config().gate_config
    result = evaluate(_draft(sign_consistency=0.7, mechanism_id=None), config)
    assert result.tier == "REJECTED"
    assert result.rejection_reason == "SECONDARY_REQUIRES_MECHANISM"


def test_sign_consistency_below_the_floor_must_publish_mixed_or_uncertain():
    """Master context invariant 8."""
    from app.core.gates import evaluate

    config = fixtures.reducer_config().gate_config
    result = evaluate(_draft(sign_consistency=0.4, net_effect="NEGATIVE"), config)
    assert result.tier == "REJECTED"
    assert result.rejection_reason == "SIGN_CONSISTENCY_BELOW_FLOOR"

    mixed = evaluate(_draft(sign_consistency=0.4, net_effect="MIXED"), config)
    assert mixed.tier == "SECONDARY_RIPPLE"


def test_gate_is_a_pure_function_of_draft_and_config():
    from app.core.gates import evaluate

    config = fixtures.reducer_config().gate_config
    draft = _draft()
    assert evaluate(draft, config) == evaluate(draft, config)
