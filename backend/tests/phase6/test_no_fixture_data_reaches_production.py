"""The master context's fabrication guard, applied to Phase 6.

Phase 6 creates NO table and writes NO row of its own: the falsifier appends
to `signal` (append-only, already existing), the section engine is a pure
function, and the console's single write path is a human's label in the eval
corpus. So the guard here is about the two CONFIG files this phase adds and
about the fixtures never leaking into production code.
"""
from pathlib import Path

import pytest

from tests.phase6.conftest import BACKEND, code_lines, package_sources

CONFIGS = (BACKEND / "config" / "falsifier.yaml",
           BACKEND / "config" / "section_taxonomy.yaml")
NEW_PACKAGES = (BACKEND / "app" / "analysis" / "falsifier",)
NEW_MODULES = (BACKEND / "app" / "output" / "sections.py",
               BACKEND / "app" / "output" / "section_config.py",
               BACKEND / "app" / "analysis" / "rebuttal.py",
               BACKEND / "app" / "ledger" / "event_review.py",
               BACKEND / "app" / "ledger" / "event_review_pages.py")


def test_no_production_module_imports_the_phase6_fixtures():
    for path in sorted((BACKEND / "app").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert "tests.phase6" not in source, path
        assert "integrated_energy_sections" not in source, path


def test_every_numeral_bearing_fixture_object_is_marked():
    """Master context: every numeric value in a fixture carries
    `"_fixture": true`."""
    from tests.phase6.conftest import load_fixture

    def check(node, path="$"):
        if isinstance(node, dict):
            has_number = any(isinstance(v, (int, float)) and not isinstance(v, bool)
                             for v in node.values())
            if has_number:
                assert node.get("_fixture") is True, f"unmarked numerals at {path}"
            for key, value in node.items():
                check(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                check(value, f"{path}[{index}]")

    check(load_fixture("integrated_energy_sections.json"))


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.name)
def test_the_phase6_configs_carry_no_company_and_no_financial_figure(path: Path):
    """Both files are POLICY and VOCABULARY: what an objection is called, how
    severe it is, and what a section is labelled. Not one of them may carry a
    company, a ticker or a coefficient."""
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    for banned in (".ns", ".bo", "reliance", "ebitda_ttm", "share_of_base",
                   "coefficient"):
        assert banned not in lowered, f"{path.name} names {banned}"


def test_the_phase6_modules_hold_no_threshold_of_their_own():
    """Every severity, label and question lives in YAML, so policy cannot
    drift between the file and the code."""
    import ast

    for path in (*NEW_MODULES, *[p for pkg in NEW_PACKAGES
                                 for p in package_sources(pkg)]):
        if path.name in ("section_config.py", "config.py"):
            continue        # the loaders, whose job is to read the YAML
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                raise AssertionError(
                    f"{path.name}:{node.lineno} carries the float literal "
                    f"{node.value} -- thresholds belong in config")


def test_the_falsifier_reads_no_clock_and_opens_no_socket():
    for path in package_sources(NEW_PACKAGES[0]):
        source = "\n".join(line for _, line in code_lines(path))
        for banned in ("datetime.now", "time.time", "utcnow(", "socket."):
            assert banned not in source, f"{path.name} calls {banned}"
