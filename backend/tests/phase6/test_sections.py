"""TASK 6.2 -- the deterministic section engine (spec section 15).

    section_key = (publication_tier, economic_effect, mechanism_id, horizon_bucket)

Section identity is a PURE FUNCTION of the canonical record. An LLM has no
role: it does not name a section, it does not assign a company to one, and it
does not decide whether a section exists. Every assertion below is about
structure, not about any company's economics.
"""
import ast
import random
from pathlib import Path

import pytest

from app.core.reducer import serialize_company_impact
from tests.phase6 import helpers
from tests.phase6.conftest import BACKEND, code_lines, load_fixture

SECTIONS_PATH = BACKEND / "app" / "output" / "sections.py"
TAXONOMY_PATH = BACKEND / "config" / "section_taxonomy.yaml"


@pytest.fixture()
def taxonomy():
    from app.output.section_config import load_section_taxonomy

    return load_section_taxonomy()


@pytest.fixture()
def fixture():
    return load_fixture("integrated_energy_sections.json")


@pytest.fixture()
def impacts(fixture):
    return helpers.impacts_from(fixture)


# ---------------------------------------------------------------------------
# the phase file's TESTS section
# ---------------------------------------------------------------------------

def test_a_mixed_company_is_never_placed_in_a_directional_section(impacts, taxonomy):
    """Invariant 9, at the presentation layer. MIXED is not a direction, so a
    MIXED company cannot appear under one -- structurally, because the effect
    is part of the section KEY."""
    from app.output.sections import DIRECTIONAL_EFFECTS, build_sections

    sections = build_sections(impacts, taxonomy)
    mixed = {i.ticker for i in impacts if i.net_effect == "MIXED"}
    assert mixed, "the fixture must contain a MIXED company or this is vacuous"

    for section in sections:
        if section.key.economic_effect in DIRECTIONAL_EFFECTS:
            placed = {c["ticker"] for c in section.companies}
            assert not (placed & mixed), (
                f"{sorted(placed & mixed)} is MIXED and was placed in the "
                f"directional section {section.label!r}")


def test_the_integrated_energy_company_lands_in_mixed_integrated_energy(
        impacts, taxonomy):
    """THE NAMED REGRESSION (spec section 15, snapshot section 12's bug).

    An integrated energy company -- crude is realisation, feedstock cost and
    marketing margin at once -- is never inside
    "NEGATIVE — OIL MARKETING & REFINING" with the pure fuel retailers. It
    gets its own MIXED section.
    """
    from app.output.sections import build_sections

    sections = {s.label: s for s in build_sections(impacts, taxonomy)}

    assert "MIXED — INTEGRATED ENERGY" in sections, sorted(sections)
    assert [c["ticker"] for c in sections["MIXED — INTEGRATED ENERGY"].companies] \
        == ["FIXINT"]

    negative_refining = sections["NEGATIVE — OIL MARKETING & REFINING"]
    assert [c["ticker"] for c in negative_refining.companies] == \
        ["FIXOMC1", "FIXOMC2"]
    assert "FIXINT" not in {c["ticker"] for c in negative_refining.companies}


def test_a_section_contains_only_companies_whose_key_matches_exactly(
        impacts, taxonomy):
    from app.output.sections import build_sections, section_key_for

    for section in build_sections(impacts, taxonomy):
        for company in section.companies:
            match = next(i for i in impacts if i.ticker == company["ticker"])
            assert section_key_for(match) == section.key, (
                f"{company['ticker']} is in {section.label!r} but its key is "
                f"{section_key_for(match)}, not {section.key}")


def test_empty_sections_are_omitted(impacts, taxonomy):
    """The taxonomy names mechanisms nobody in this event carries. Not one of
    them becomes a section -- a section is built FROM companies, never from
    the label list."""
    from app.output.sections import build_sections

    sections = build_sections(impacts, taxonomy)
    assert sections, "the fixture publishes companies"
    for section in sections:
        assert section.companies, f"{section.label!r} has no companies"

    used = {i.mechanism_id for i in impacts}
    unused = [m for m in taxonomy.labels if m not in used]
    assert unused, "the taxonomy must name an unused mechanism or this is vacuous"
    for mechanism_id in unused:
        assert not [s for s in sections if s.key.mechanism_id == mechanism_id]


def test_rejected_candidates_never_become_a_section(impacts, taxonomy):
    """A rejection is shown in the review console, never as a published
    section -- and never silently dropped from the record set either."""
    from app.output.sections import build_sections

    sections = build_sections(impacts, taxonomy)
    rejected = {i.ticker for i in impacts if i.publication_tier == "REJECTED"}
    assert rejected, "the fixture must contain a rejected candidate"
    placed = {c["ticker"] for s in sections for c in s.companies}
    assert not (placed & rejected)


def test_the_zero_primary_state_renders_explicitly_with_the_rejected_count(
        taxonomy):
    """Spec section 15: zero PRIMARY is a designed state, not an error, and
    the rejected COUNT is part of it."""
    from app.output.sections import build_sections, render_zero_primary, zero_primary_state

    impacts = (
        helpers.impact(company_id=1, ticker="FIXA", publication_tier="SECONDARY_RIPPLE",
                       net_effect="NEGATIVE", mechanism_id="aviation_fuel_cost",
                       delta_ebitda_pct_p50=-1.0),
        helpers.impact(company_id=2, ticker="FIXB", publication_tier="SECONDARY_RIPPLE",
                       net_effect="NEGATIVE", mechanism_id="paint_input_cost",
                       delta_ebitda_pct_p50=-0.5),
        helpers.impact(company_id=3, ticker="FIXC", publication_tier="SECONDARY_RIPPLE",
                       net_effect="NEGATIVE", mechanism_id="tyre_input_cost",
                       delta_ebitda_pct_p50=-0.5),
        *[helpers.impact(company_id=100 + n, ticker=f"FIXR{n}",
                         publication_tier="REJECTED", net_effect="NEGATIVE",
                         mechanism_id="paint_input_cost",
                         rejection_reason="PRIMARY_FAILED_EVIDENCE")
          for n in range(14)],
    )
    sections = build_sections(impacts, taxonomy)
    state = zero_primary_state(impacts, sections, macro_channel_count=2)

    assert state["zero_primary"] is True
    assert state["second_order_count"] == 3
    assert state["macro_channel_count"] == 2
    assert state["rejected_count"] == 14

    rendered = render_zero_primary(state, taxonomy)
    assert "NO PRIMARY IMPACT IDENTIFIED" in rendered
    assert "3 second-order effects" in rendered
    assert "2 macro channels" in rendered
    assert "14 candidates rejected" in rendered


def test_zero_primary_is_false_when_a_primary_exists(impacts, taxonomy):
    from app.output.sections import build_sections, zero_primary_state

    state = zero_primary_state(impacts, build_sections(impacts, taxonomy))
    assert state["zero_primary"] is False


def test_the_section_structure_is_identical_across_1000_runs(impacts, taxonomy):
    """Determinism: the same impacts, in any order, produce byte-identical
    section structure."""
    from app.output.sections import build_sections, serialize_sections

    baseline = serialize_sections(build_sections(impacts, taxonomy))
    rng = random.Random(20260817)
    shuffled = list(impacts)
    for _ in range(1000):
        rng.shuffle(shuffled)
        assert serialize_sections(build_sections(shuffled, taxonomy)) == baseline


# ---------------------------------------------------------------------------
# ordering, labelling and the no-LLM guarantee
# ---------------------------------------------------------------------------

def test_sections_are_ordered_tier_then_median_materiality_then_alphabetical(
        impacts, taxonomy, fixture):
    from app.output.sections import build_sections

    labels = [s.label for s in build_sections(impacts, taxonomy)]
    assert labels == [s["label"] for s in fixture["expected_sections"]]


def test_a_section_nobody_could_size_sorts_after_the_sized_ones_alphabetically(
        taxonomy):
    """|median materiality| cannot rank a section whose companies carry no
    computed band. Such a section sorts AFTER every sized one, alphabetically
    -- it is not given a magnitude of zero, which would read as "no impact",
    and it is not given the benefit of the doubt either."""
    from app.output.sections import build_sections

    impacts = (
        helpers.impact(company_id=1, ticker="FIXSIZED", publication_tier="PRIMARY",
                       net_effect="NEGATIVE", mechanism_id="aviation_fuel_cost",
                       delta_ebitda_pct_p50=-0.1),
        helpers.impact(company_id=2, ticker="FIXUNSIZEDA", publication_tier="PRIMARY",
                       net_effect="NEGATIVE", mechanism_id="paint_input_cost",
                       delta_ebitda_pct_p50=None),
        helpers.impact(company_id=3, ticker="FIXUNSIZEDB", publication_tier="PRIMARY",
                       net_effect="NEGATIVE", mechanism_id="tyre_input_cost",
                       delta_ebitda_pct_p50=None),
    )
    sections = build_sections(impacts, taxonomy)
    assert [s.median_materiality for s in sections] == [0.1, None, None]
    assert [s.label for s in sections][1:] == sorted([s.label for s in sections][1:])


def test_an_unknown_mechanism_id_gets_a_keyed_label_not_invented_prose(taxonomy):
    """A mechanism the taxonomy does not name still gets a section (its key is
    distinct, so collapsing it into another section would misplace a company)
    -- with a label built from the ID ITSELF. Nothing writes prose about a
    mechanism nobody described."""
    from app.output.sections import build_sections

    sections = build_sections((
        helpers.impact(company_id=1, ticker="FIXUNK", publication_tier="PRIMARY",
                       net_effect="NEGATIVE", mechanism_id="fixture_unknown_mechanism",
                       delta_ebitda_pct_p50=-1.0),), taxonomy)
    assert len(sections) == 1
    assert "fixture_unknown_mechanism" in sections[0].label
    assert taxonomy.unknown_label_word in sections[0].label


def test_two_unknown_mechanisms_do_not_collapse_into_one_section(taxonomy):
    from app.output.sections import build_sections

    sections = build_sections((
        helpers.impact(company_id=1, ticker="FIXU1", publication_tier="PRIMARY",
                       net_effect="NEGATIVE", mechanism_id="fixture_unknown_one",
                       delta_ebitda_pct_p50=-1.0),
        helpers.impact(company_id=2, ticker="FIXU2", publication_tier="PRIMARY",
                       net_effect="NEGATIVE", mechanism_id="fixture_unknown_two",
                       delta_ebitda_pct_p50=-1.0),), taxonomy)
    assert len(sections) == 2
    assert len({s.label for s in sections}) == 2


def test_a_null_mechanism_id_gets_its_own_keyed_label(taxonomy):
    """A company named directly by the event carries no mechanism. That is a
    real key, not a missing one."""
    from app.output.sections import build_sections

    sections = build_sections((
        helpers.impact(company_id=1, ticker="FIXNAMED", publication_tier="PRIMARY",
                       net_effect="NEGATIVE", mechanism_id=None,
                       delta_ebitda_pct_p50=-1.0),), taxonomy)
    assert len(sections) == 1
    assert sections[0].label == f"NEGATIVE{taxonomy.separator}{taxonomy.no_mechanism_label}"


def test_no_section_label_concatenates_a_directness_with_a_tier(impacts, taxonomy):
    """The Phase 0 lint, extended to the rendered labels themselves (spec
    section 15's banned "DIRECT EXPOSURE · RIPPLE")."""
    from tests.phase0.test_field_separation import _literal_joins_both
    from app.output.sections import build_sections, render_zero_primary, zero_primary_state

    labels = [s.label for s in build_sections(impacts, taxonomy)]
    labels += list(taxonomy.labels.values())
    labels.append(taxonomy.no_mechanism_label)
    labels.append(render_zero_primary(
        zero_primary_state(impacts, build_sections(impacts, taxonomy)), taxonomy))
    for label in labels:
        assert not _literal_joins_both(label), label


def test_the_section_engine_calls_no_llm_and_reads_no_disk():
    """`sections.py` is a PURE function. The taxonomy is loaded by its impure
    sibling `section_config.py` and passed in, exactly as gates.py/
    config_loader.py are split."""
    imported = set()
    for node in ast.walk(ast.parse(SECTIONS_PATH.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    for banned in ("yaml", "sqlalchemy", "anthropic", "app.models", "app.db",
                   "app.analysis.claude_client", "app.output.section_config"):
        assert banned not in imported, f"sections.py imports {banned}"

    source = "\n".join(line for _, line in code_lines(SECTIONS_PATH))
    for banned in ("open(", "read_text", "generate(", "datetime.now"):
        assert banned not in source, f"sections.py calls {banned}"


def test_the_taxonomy_is_labels_only_and_carries_no_company_or_figure():
    """`config/section_taxonomy.yaml` is VOCABULARY, not data: no numeral
    outside `version`, no ticker, no company."""
    import re

    text = TAXONOMY_PATH.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("#")
                     and not line.strip().startswith("version:"))
    # The zero-PRIMARY template carries `{}` placeholders, never a figure.
    assert not re.search(r"(?<!\{)\b\d+(\.\d+)?\b", body), (
        "a numeral appears in the section taxonomy")


def test_the_serialized_record_and_the_section_key_agree(impacts, taxonomy):
    """The key is read off the canonical record's own fields -- the same four
    the serializer emits, never a fifth derived one."""
    from app.output.sections import section_key_for

    for record in impacts:
        payload = serialize_company_impact(record)
        key = section_key_for(record)
        assert key.publication_tier == payload["publication_tier"]
        assert key.economic_effect == payload["fundamental"]["net_effect"]
        assert key.mechanism_id == payload["fundamental"]["mechanism_id"]
        assert key.horizon_bucket == payload["fundamental"]["headline_horizon"]


# ---------------------------------------------------------------------------
# the taxonomy speaks the PERSISTED dialect (node-id consolidation, P1)
# ---------------------------------------------------------------------------
#
# `config/section_taxonomy.yaml` is keyed by mechanism_id, and the
# mechanism_id that ARRIVES is whatever `signal_adapters` put on the CHANNEL
# signal -- `entry["causal_parent_id"]`, i.e. `normalize_node_id(...)` output.
# Nine of the 42 registry ids change under that transform, so a taxonomy
# keyed in the RAW registry dialect renders those nine as
# "UNCLASSIFIED MECHANISM (paint_input_cost)" -- a raw engine node id in a
# section header, and nine singleton sections.

def _emittable(mechanism_id: str) -> tuple[bool, str]:
    """Can the V5 path actually carry this mechanism id?

    Two producers write `company_impact.mechanism_id`:

      * the V4 adapter (`app.core.signal_adapters`), which forwards
        `causal_parent_id` -- ALWAYS `normalize_node_id` output;
      * the Phase-2 sensitivity ledger, whose channel ids come from the
        reviewed `mechanism_edge` vocabulary and are NOT node ids (a
        separate domain -- see the sweep's C6/C7; it is not normalized and
        must not be forced to be).

    So the rule is about the REGISTRY-owned ids only: an id that names a
    knowledge-registry mechanism must be spelled the way production
    persists it. An id the registry does not own is free-form and passes.
    """
    from app.analysis.impact_graph.knowledge import resolve_mechanism_id
    from app.analysis.impact_graph.normalize import normalize_node_id

    raw = resolve_mechanism_id(mechanism_id)
    if raw is None:
        return True, "not registry-owned"
    persisted = normalize_node_id(raw)
    if mechanism_id == persisted:
        return True, "persisted dialect"
    return False, (f"{mechanism_id!r} names registry mechanism {raw!r}, which "
                   f"production persists as {persisted!r} -- the pipeline can "
                   f"never emit {mechanism_id!r}, so a fixture keyed to it "
                   f"tests nothing")


def _mechanism_ids_in_fixtures() -> dict[str, set[str]]:
    """Every mechanism id any V5 test fixture carries -> where it came from.

    Both carriers are swept so a new fixture cannot reintroduce the defect:
    `mechanism_id` / `expected_mechanism` values inside every JSON under
    `tests/`, and the same keyword arguments written as literals in every
    test module.
    """
    import json

    tests_root = BACKEND / "tests"
    keys = ("mechanism_id", "expected_mechanism")
    found: dict[str, set[str]] = {}

    def add(value, source):
        if isinstance(value, str) and value:
            found.setdefault(value, set()).add(source)

    for path in sorted(tests_root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:                                   # pragma: no cover
            continue
        stack = [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in keys:
                        add(value, str(path.relative_to(BACKEND)))
                    stack.append(value)
            elif isinstance(node, list):
                stack.extend(node)

    for path in sorted(tests_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.keyword) and node.arg in keys
                    and isinstance(node.value, ast.Constant)):
                add(node.value.value, str(path.relative_to(BACKEND)))
    return found


def test_every_registry_mechanism_has_a_taxonomy_label_in_the_PERSISTED_dialect(
        taxonomy):
    """Mirrors `tests/test_sections_structural.py::test_all_42_mechanisms_
    have_labels`, which is the assertion the legacy ripple taxonomy already
    carries and the V5 taxonomy was missing."""
    from app.analysis.impact_graph.knowledge import MECHANISMS
    from app.analysis.impact_graph.normalize import normalize_node_id

    missing = sorted(m for m in MECHANISMS
                     if normalize_node_id(m) not in taxonomy.labels)
    assert not missing, f"unlabelled after normalize: {missing}"


def test_every_taxonomy_key_is_a_mechanism_id_the_pipeline_can_emit(taxonomy):
    """A key nothing can ever arrive under is dead vocabulary: it never
    renders, and the mechanism it was written for renders UNCLASSIFIED."""
    from app.analysis.impact_graph.normalize import normalize_node_id

    unreachable = []
    for key in taxonomy.labels:
        ok, why = _emittable(key)
        if not ok:
            unreachable.append(why)
        elif normalize_node_id(key) != key:
            unreachable.append(
                f"{key!r} is not normalize-idempotent, so no causal_parent_id "
                f"can ever equal it (it would be persisted as "
                f"{normalize_node_id(key)!r})")
    assert not unreachable, "\n".join(unreachable)


def test_no_v5_fixture_is_keyed_to_a_mechanism_id_nothing_can_emit():
    """The structural fix for the class of defect this whole sweep is about:
    a fixture that exercises the section taxonomy with `paints_input_cost`
    validates NOTHING, because the id the pipeline persists is
    `paint_input_cost` and the two take different code paths."""
    broken = []
    for mechanism_id, sources in sorted(_mechanism_ids_in_fixtures().items()):
        ok, why = _emittable(mechanism_id)
        if not ok:
            broken.append(f"{why}  [{', '.join(sorted(sources))}]")
    assert not broken, "\n".join(broken)
