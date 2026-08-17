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
                       net_effect="NEGATIVE", mechanism_id="paints_input_cost",
                       delta_ebitda_pct_p50=-0.5),
        helpers.impact(company_id=3, ticker="FIXC", publication_tier="SECONDARY_RIPPLE",
                       net_effect="NEGATIVE", mechanism_id="tyre_input_cost",
                       delta_ebitda_pct_p50=-0.5),
        *[helpers.impact(company_id=100 + n, ticker=f"FIXR{n}",
                         publication_tier="REJECTED", net_effect="NEGATIVE",
                         mechanism_id="paints_input_cost",
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
                       net_effect="NEGATIVE", mechanism_id="paints_input_cost",
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
