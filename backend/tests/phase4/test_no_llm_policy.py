"""Phase file TESTS/test_no_llm_policy.py --
`newsflo/analysis/policy/*` imports no provider module.

"Do not let an LLM decide whether a modifier applies." A modifier is a
transfer function over a registered parameter set; whether it applies is a
date comparison and a tag comparison. There is nothing here for a model to
judge, and the ast scan makes that structural rather than a promise.
"""
import ast
from pathlib import Path

import pytest

from tests.phase4.conftest import code_lines

BACKEND = Path(__file__).resolve().parents[2]
POLICY = BACKEND / "app" / "analysis" / "policy"

PROVIDER_MODULES = (
    "anthropic", "openai", "groq", "google", "google.generativeai",
    "transformers", "httpx",
    # FIX ROUND 1 (M-8). The list above is the one Phase 2 froze, and it is
    # the set of providers THIS REPO has used. A scan that only knows the
    # providers already in the repo cannot catch the next one, and "the policy
    # layer never asks a model" is a claim about all of them.
    "vertexai", "google.cloud.aiplatform", "cohere", "mistralai", "litellm",
    "ollama", "boto3", "bedrock", "together", "replicate", "huggingface_hub",
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

BANNED_NETWORK_MODULES = (
    "yfinance", "requests", "httpx", "urllib", "urllib3", "socket", "aiohttp",
    "ftplib", "telnetlib", "smtplib",
)


def _policy_sources() -> list[Path]:
    return sorted(POLICY.glob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_the_policy_package_exists_and_is_not_empty():
    assert _policy_sources(), "app/analysis/policy/ has no modules"


@pytest.mark.parametrize("provider", PROVIDER_MODULES)
def test_no_policy_module_imports_a_provider(provider):
    for path in _policy_sources():
        for module in _imported_modules(path):
            assert module != provider and not module.startswith(provider + "."), (
                f"{path.name} imports {module}")


def test_no_policy_module_imports_anything_that_opens_a_socket():
    for path in _policy_sources():
        for module in _imported_modules(path):
            assert module.split(".")[0] not in BANNED_NETWORK_MODULES, (
                f"{path.name} imports {module}")


def test_no_policy_module_defines_a_prompt_or_names_a_model():
    import re

    banned = re.compile(r"\bprompt\b|claude|gpt-|gemini|llama|anthropic",
                        re.IGNORECASE)
    for path in _policy_sources():
        # A comment or a docstring may say the word (they explain WHY there is
        # no model on this path); executable code may not.
        for number, line in code_lines(path):
            assert not banned.search(line), f"{path.name}:{number}: {line.strip()}"


def test_the_whole_transfer_call_graph_is_arithmetic():
    """The positive half of the claim: the six transfer functions are pure
    functions of floats, and calling one twice with the same inputs gives the
    same float."""
    from app.analysis.policy.transfer import TRANSFER_FUNCTIONS

    assert set(TRANSFER_FUNCTIONS) == {
        "THRESHOLD_CAPTURE", "HARD_CAP", "STATE_DEPENDENT", "SUBSIDY_SHARE",
        "FORMULA_PRICING", "REGIONAL_MULTIPLIER"}
    factor = TRANSFER_FUNCTIONS["SUBSIDY_SHARE"]
    assert factor({"retained_fraction": 0.25}, {}) == factor(
        {"retained_fraction": 0.25}, {})


def test_the_new_gate_rule_is_policy_in_the_yaml_not_a_constant_in_the_code():
    """Phase 4 adds one PRIMARY rule. Like every other one it is named by
    `config/gates.yaml` and defaults to NO RULE in the code, so a config that
    predates this phase walks exactly the rules it walked before."""
    import yaml

    from app.core.gates import TierPolicy

    assert TierPolicy.__dataclass_fields__[
        "allow_stale_policy_state"].default is None
    raw = yaml.safe_load(
        (BACKEND / "config" / "gates.yaml").read_text(encoding="utf-8"))
    assert raw["primary"]["allow_stale_policy_state"] is False
    assert raw["secondary_ripple"]["allow_stale_policy_state"] is True
