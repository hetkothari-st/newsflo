"""TASK 2.4 -- no LLM assigns materiality on the V5 path.

SCOPE RULING (controller adaptation, binding). "Delete every code path where
an LLM assigns materiality" applies to the V5 CANONICAL PATH. The V4 legacy
path (`app/analysis/impact_graph/*` and the `alert_companies` serving path)
is the live product until V5 serves, and stays byte-untouched this session.
So:

  * `app/analysis/sensitivity/*` may not import a provider module, may not
    define a prompt, and may not name an LLM -- asserted below by ast scan;
  * the V4 prompt file is exempted by an EXACT baseline (the same ratchet
    pattern as Phase 0's field-separation lint), so no NEW prompt anywhere in
    the codebase may contain materiality-assignment language.

The baseline is a frozen file list. Adding a materiality-assigning prompt in
any other module fails this test.
"""
import ast
import re
from pathlib import Path

import pytest

from tests.phase2.conftest import code_lines

BACKEND = Path(__file__).resolve().parents[2]
SENSITIVITY = BACKEND / "app" / "analysis" / "sensitivity"

# Modules that talk to a model provider, directly or through this repo's
# adapters.
PROVIDER_MODULES = (
    "anthropic", "openai", "groq", "google", "google.generativeai",
    "transformers", "httpx",
    "app.analysis.claude_client",
    "app.analysis.impact_graph.claude_json",
    "app.analysis.impact_graph.gemini_json",
    "app.analysis.impact_graph.router",
    "app.analysis.impact_graph.prompts",
    "app.analysis.impact_graph.engine",
    "app.analysis.impact_graph.materiality",
    "app.analysis.cascade",
    "app.analysis.refinement",
    "app.analysis.verification",
)

# V4 legacy, exempt by explicit baseline -- NOT deleted this session (the
# live product still runs on it). Paths are repo-relative to `backend/`.
V4_PROMPT_BASELINE = ("app/analysis/impact_graph/prompts.py",)

MATERIALITY_LANGUAGE = re.compile(
    r"materialit|HIGH/MEDIUM/LOW|impact_strength", re.IGNORECASE)


def _sensitivity_sources() -> list[Path]:
    return sorted(SENSITIVITY.glob("*.py"))


def test_the_sensitivity_package_exists_and_is_not_empty():
    assert _sensitivity_sources(), "app/analysis/sensitivity/ has no modules"


def _imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, at module level or inside a
    function (a lazy import is still an import)."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize("provider", PROVIDER_MODULES)
def test_no_sensitivity_module_imports_a_provider(provider):
    for path in _sensitivity_sources():
        for module in _imported_modules(path):
            assert module != provider and not module.startswith(provider + "."), (
                f"{path.name} imports {module}")


def test_no_sensitivity_module_defines_a_prompt_or_names_a_model():
    banned = re.compile(r"\bprompt\b|claude|gpt-|gemini|llama|anthropic", re.IGNORECASE)
    for path in _sensitivity_sources():
        # A comment or a docstring may say the word (they explain WHY there
        # is no model on this path); executable code may not.
        for number, line in code_lines(path):
            assert not banned.search(line), f"{path.name}:{number}: {line.strip()}"


def test_no_new_prompt_template_contains_materiality_assignment_language():
    offenders = {}
    for path in sorted((BACKEND / "app").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:                       # pragma: no cover
            continue
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target.id]
            if not any("PROMPT" in t.upper() for t in targets) or node.value is None:
                continue
            for sub in ast.walk(node.value):
                text = sub.value if isinstance(sub, ast.Constant) and isinstance(
                    sub.value, str) else None
                if text and MATERIALITY_LANGUAGE.search(text):
                    offenders.setdefault(
                        str(path.relative_to(BACKEND)).replace("\\", "/"), 0)
                    offenders[str(path.relative_to(BACKEND)).replace("\\", "/")] += 1

    assert tuple(sorted(offenders)) == V4_PROMPT_BASELINE, (
        "a prompt template outside the V4 baseline assigns materiality: "
        f"{sorted(set(offenders) - set(V4_PROMPT_BASELINE))}")


def test_the_baseline_lint_actually_fires(tmp_path):
    """A ratchet nobody has seen fire is not a ratchet."""
    offender = tmp_path / "fake_module.py"
    offender.write_text(
        'BAD_PROMPT = """Rate the materiality of this company as '
        'HIGH/MEDIUM/LOW."""\n', encoding="utf-8")
    tree = ast.parse(offender.read_text(encoding="utf-8"))
    found = [sub.value for node in ast.walk(tree)
             if isinstance(node, ast.Assign)
             for sub in ast.walk(node.value)
             if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
             and MATERIALITY_LANGUAGE.search(sub.value)]
    assert found


def test_the_v5_materiality_number_is_produced_by_arithmetic_not_by_a_model():
    """The positive half of the claim: the bucket that reaches the reducer is
    computed from ledger values by `simulate`, whose whole call graph is
    stdlib."""
    from tests.phase2.conftest import case_by_id, exposure_from_case
    from tests.phase2.conftest import params_from_case, shock_from_case
    from app.analysis.sensitivity.channels import compute_channel
    from app.analysis.sensitivity.monte_carlo import simulate

    case = case_by_id("C1")
    result = simulate(
        [compute_channel(exposure_from_case(case), shock_from_case(case),
                         params_from_case(case), horizon_days=90)],
        ebitda_ttm_inr=2000000000.0, event_id="fixture:e", company_id=9101,
        analysis_version="v5:fixture")
    assert result.bucket in ("HIGH", "MEDIUM", "LOW", "NO_MATERIAL_IMPACT")
    assert result.driver_ranking
