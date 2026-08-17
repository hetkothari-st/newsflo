"""TASK 4.1 / 4.2 -- the registry, the six transfer functions, and the rules
around them (docs/v5/05_PHASE_4_policy_horizon.md TESTS section).

Every number exercised here comes from `fixtures/policy_modifiers.json` and is
obviously fake. The DEPLOYED registry carries no parameter value at all, which
is itself asserted below.
"""
from datetime import date

import pytest
import yaml

from tests.phase4.conftest import (
    FIXTURE_TODAY, fixture_policy_state, fixture_registry, make_params,
    realization_channel,
)

BACKEND = __import__("pathlib").Path(__file__).resolve().parents[2]
DEPLOYED_REGISTRY = BACKEND / "config" / "policy_modifiers.yaml"


# --- THRESHOLD_CAPTURE ------------------------------------------------------

def test_threshold_capture_reduces_the_channel_by_the_captured_fraction():
    """HAND-VERIFIED FIXTURE.

        base 1,000,000,000 x share 1.0 x delta +0.20 x elasticity 1.0
            x (1 - capture 0.0) x ownership 1.0        =  +200,000,000

        the exposed variable moves 90 -> 110 and the fixture threshold is 100,
        so HALF the move sits above the threshold; the fixture captures half
        of that:            captured share = 0.5 x 0.5 = 0.25
                            the channel keeps 0.75      =  +150,000,000
    """
    from app.analysis.policy.transforms import apply_modifiers

    channel = realization_channel(
        exposure_tag="realization:fixture_product", delta_pct=0.20,
        level_before=90.0, level_after=110.0)
    assert channel.delta_ebitda_inr == pytest.approx(200_000_000.0)

    result = apply_modifiers(
        (channel,), as_of_date=FIXTURE_TODAY,
        policy_state=fixture_policy_state(),
        registry=fixture_registry("FIXTURE_A_THRESHOLD"))

    assert result.applied == ("FIXTURE_A_THRESHOLD",)
    assert result.channels[0].delta_ebitda_inr == pytest.approx(150_000_000.0)


def test_threshold_capture_leaves_a_move_entirely_below_the_threshold_alone():
    from app.analysis.policy.transforms import apply_modifiers

    channel = realization_channel(
        exposure_tag="realization:fixture_product", delta_pct=0.20,
        level_before=50.0, level_after=60.0)
    result = apply_modifiers(
        (channel,), as_of_date=FIXTURE_TODAY, policy_state=fixture_policy_state(),
        registry=fixture_registry("FIXTURE_A_THRESHOLD"))
    assert result.channels[0].delta_ebitda_inr == pytest.approx(
        channel.delta_ebitda_inr)


def test_threshold_capture_without_a_level_widens_instead_of_guessing():
    """A modifier whose input is missing is NOT skipped silently and is NOT
    applied on an assumed level. It widens and caps, like an unknown regime."""
    from app.analysis.policy.transforms import apply_modifiers

    channel = realization_channel(exposure_tag="realization:fixture_product",
                                  delta_pct=0.20)
    result = apply_modifiers(
        (channel,), as_of_date=FIXTURE_TODAY, policy_state=fixture_policy_state(),
        registry=fixture_registry("FIXTURE_A_THRESHOLD"))

    assert result.applied == ()
    assert "FIXTURE_A_THRESHOLD" in result.unresolved
    assert result.channels[0].grade_cap == "C"
    assert result.channels[0].delta_ebitda_inr == pytest.approx(
        channel.delta_ebitda_inr)


# --- HARD_CAP ---------------------------------------------------------------

def test_hard_cap_clips_the_channel_at_the_administered_ceiling():
    """HAND-VERIFIED FIXTURE: the variable moves 5 -> 10, the fixture ceiling
    is 7.5, so only half the move is realisable and the channel keeps 0.5."""
    from app.analysis.policy.transforms import apply_modifiers

    channel = realization_channel(
        exposure_tag="realization:fixture_capped", delta_pct=1.0,
        level_before=5.0, level_after=10.0)
    assert channel.delta_ebitda_inr == pytest.approx(1_000_000_000.0)

    result = apply_modifiers(
        (channel,), as_of_date=FIXTURE_TODAY, policy_state=fixture_policy_state(),
        registry=fixture_registry("FIXTURE_B_CAP"))
    assert result.applied == ("FIXTURE_B_CAP",)
    assert result.channels[0].delta_ebitda_inr == pytest.approx(500_000_000.0)


def test_hard_cap_below_the_ceiling_changes_nothing():
    from app.analysis.policy.transforms import apply_modifiers

    channel = realization_channel(
        exposure_tag="realization:fixture_capped", delta_pct=0.20,
        level_before=5.0, level_after=6.0)
    result = apply_modifiers(
        (channel,), as_of_date=FIXTURE_TODAY, policy_state=fixture_policy_state(),
        registry=fixture_registry("FIXTURE_B_CAP"))
    assert result.channels[0].delta_ebitda_inr == pytest.approx(
        channel.delta_ebitda_inr)


# --- STATE_DEPENDENT --------------------------------------------------------

def test_state_dependent_with_a_known_state_overrides_the_parameter():
    from app.analysis.policy.transforms import apply_modifiers

    channel = realization_channel(
        exposure_tag="realization:fixture_state_dependent", delta_pct=0.10,
        elasticity=1.0, capture=0.5)
    assert channel.delta_ebitda_inr == pytest.approx(50_000_000.0)

    result = apply_modifiers(
        (channel,), as_of_date=FIXTURE_TODAY,
        policy_state=fixture_policy_state("fixture_revision_active"),
        registry=fixture_registry("FIXTURE_C_STATE"))

    assert result.applied == ("FIXTURE_C_STATE",)
    # capture collapses from 0.5 to 0.0, so the whole move lands.
    assert result.channels[0].delta_ebitda_inr == pytest.approx(100_000_000.0)


def test_state_dependent_with_an_unknown_state_widens_and_caps_grade_at_c():
    """The phase file's rule, verbatim: unknown or stale regime state widens
    the band and caps evidence at C. It NEVER assumes a default regime."""
    from app.analysis.policy.transforms import apply_modifiers
    from app.analysis.sensitivity.config import load_materiality_config

    channel = realization_channel(
        exposure_tag="realization:fixture_state_dependent", delta_pct=0.10,
        elasticity=1.0, capture=0.5)
    before = channel.params["realization_elasticity"]

    result = apply_modifiers(
        (channel,), as_of_date=FIXTURE_TODAY,
        policy_state=fixture_policy_state(),        # the state is not there
        registry=fixture_registry("FIXTURE_C_STATE"))

    modified = result.channels[0]
    assert result.applied == ()
    assert "FIXTURE_C_STATE" in result.unknown_state
    assert modified.grade_cap == "C"
    # the number itself is UNCHANGED -- an unknown regime is not a reason to
    # move the point estimate, only to be less sure of it.
    assert modified.delta_ebitda_inr == pytest.approx(channel.delta_ebitda_inr)

    after = modified.params["realization_elasticity"]
    multiplier = load_materiality_config().unknown_modifier_band_multiplier
    assert after.hi - after.point == pytest.approx(
        (before.hi - before.point) * multiplier)
    assert after.point - after.lo == pytest.approx(
        (before.point - before.lo) * multiplier)
    assert any("fixture_revision_active" in note for note in modified.policy_notes)


def test_a_stale_state_is_treated_exactly_like_an_unknown_one():
    from app.analysis.policy.transforms import apply_modifiers
    from app.analysis.policy.registry import modifier_from_mapping, PolicyRegistry
    from tests.phase4.conftest import fixture_modifier

    raw = dict(fixture_modifier("FIXTURE_C_STATE"))
    raw["parameters"] = dict(raw["parameters"], state_key="fixture_stale_state")
    registry = PolicyRegistry((modifier_from_mapping(raw),))

    channel = realization_channel(
        exposure_tag="realization:fixture_state_dependent", delta_pct=0.10,
        elasticity=1.0, capture=0.5)
    result = apply_modifiers(
        (channel,), as_of_date=FIXTURE_TODAY,
        policy_state=fixture_policy_state("fixture_stale_state"),
        registry=registry)

    assert result.applied == ()
    assert "FIXTURE_C_STATE" in result.unknown_state
    assert result.channels[0].grade_cap == "C"
    assert result.stale_state_keys == ("fixture_stale_state",)


# --- SUBSIDY_SHARE / FORMULA_PRICING / REGIONAL_MULTIPLIER ------------------

def test_subsidy_share_keeps_only_the_retained_fraction():
    from app.analysis.policy.transforms import apply_modifiers

    channel = realization_channel(exposure_tag="realization:fixture_shared",
                                  delta_pct=0.10)
    result = apply_modifiers(
        (channel,), as_of_date=FIXTURE_TODAY, policy_state=fixture_policy_state(),
        registry=fixture_registry("FIXTURE_D_SUBSIDY"))
    assert result.channels[0].delta_ebitda_inr == pytest.approx(25_000_000.0)


def test_formula_pricing_replaces_the_market_move_with_the_administered_one():
    """The market moved 8%; the fixture's administered formula moves 2%, so
    every §5.1 formula (all six are linear in delta) is rescaled by 0.25."""
    from app.analysis.policy.transforms import apply_modifiers

    channel = realization_channel(exposure_tag="realization:fixture_formula",
                                  delta_pct=0.08)
    assert channel.delta_ebitda_inr == pytest.approx(80_000_000.0)
    result = apply_modifiers(
        (channel,), as_of_date=FIXTURE_TODAY, policy_state=fixture_policy_state(),
        registry=fixture_registry("FIXTURE_E_FORMULA"))
    assert result.channels[0].delta_ebitda_inr == pytest.approx(20_000_000.0)


def test_regional_multiplier_uses_the_supplied_geography_mix():
    """0.5 x 2.0 + 0.5 x 0.5 = 1.25."""
    from app.analysis.policy.transforms import apply_modifiers

    channel = realization_channel(exposure_tag="input:fixture_regional",
                                  delta_pct=0.10)
    result = apply_modifiers(
        (channel,), as_of_date=FIXTURE_TODAY, policy_state=fixture_policy_state(),
        registry=fixture_registry("FIXTURE_F_REGIONAL"),
        region_mix={"NORTH_FIXTURE": 0.5, "SOUTH_FIXTURE": 0.5})
    assert result.channels[0].delta_ebitda_inr == pytest.approx(125_000_000.0)


def test_regional_multiplier_without_a_mix_widens_rather_than_assuming_one():
    from app.analysis.policy.transforms import apply_modifiers

    channel = realization_channel(exposure_tag="input:fixture_regional",
                                  delta_pct=0.10)
    result = apply_modifiers(
        (channel,), as_of_date=FIXTURE_TODAY, policy_state=fixture_policy_state(),
        registry=fixture_registry("FIXTURE_F_REGIONAL"))
    assert result.applied == ()
    assert "FIXTURE_F_REGIONAL" in result.unresolved
    assert result.channels[0].grade_cap == "C"


# --- ordering and effective dates -------------------------------------------

def test_modifier_application_order_is_deterministic_across_runs():
    """Two modifiers on one tag, offered to the engine in both orders, must
    produce the same number and the same `applied` list -- sorted by
    `modifier_id`, never by iteration order."""
    from app.analysis.policy.registry import PolicyRegistry, modifier_from_mapping
    from app.analysis.policy.transforms import apply_modifiers
    from tests.phase4.conftest import fixture_modifier

    first = dict(fixture_modifier("FIXTURE_D_SUBSIDY"))
    second = dict(fixture_modifier("FIXTURE_E_FORMULA"),
                  applies_to_tag="realization:fixture_shared")
    entries = [modifier_from_mapping(first), modifier_from_mapping(second)]

    channel = realization_channel(exposure_tag="realization:fixture_shared",
                                  delta_pct=0.08)
    results = []
    for order in (entries, list(reversed(entries))):
        results.append(apply_modifiers(
            (channel,), as_of_date=FIXTURE_TODAY,
            policy_state=fixture_policy_state(),
            registry=PolicyRegistry(tuple(order))))

    assert results[0].applied == results[1].applied
    assert results[0].applied == ("FIXTURE_D_SUBSIDY", "FIXTURE_E_FORMULA")
    assert (results[0].channels[0].delta_ebitda_inr
            == results[1].channels[0].delta_ebitda_inr)


def test_a_modifier_outside_its_effective_window_is_not_active():
    from app.analysis.policy.registry import PolicyRegistry, modifier_from_mapping
    from app.analysis.policy.transforms import apply_modifiers
    from tests.phase4.conftest import fixture_modifier

    repealed = dict(fixture_modifier("FIXTURE_A_THRESHOLD"),
                    effective_to="2225-01-01")
    channel = realization_channel(exposure_tag="realization:fixture_product",
                                  delta_pct=0.20, level_before=90.0,
                                  level_after=110.0)
    result = apply_modifiers(
        (channel,), as_of_date=FIXTURE_TODAY, policy_state=fixture_policy_state(),
        registry=PolicyRegistry((modifier_from_mapping(repealed),)))
    assert result.applied == ()
    assert result.channels[0].delta_ebitda_inr == pytest.approx(
        channel.delta_ebitda_inr)


def test_no_modifier_configured_is_an_identity_transform():
    """Phase 2's engine must keep behaving exactly as it did."""
    from app.analysis.policy.registry import PolicyRegistry
    from app.analysis.policy.transforms import apply_modifiers

    channel = realization_channel(delta_pct=0.10)
    result = apply_modifiers((channel,), as_of_date=FIXTURE_TODAY,
                             policy_state=fixture_policy_state(),
                             registry=PolicyRegistry(()))
    assert result.channels == (channel,)
    assert result.applied == ()
    assert result.unknown_state == ()


# --- the applied modifiers reach the payload --------------------------------

def test_applied_modifiers_appear_in_the_channel_signal_and_the_impact():
    """Showing the user that the levy was modelled is worth more than the
    impact call itself (phase file Task 4.2), so it must survive all the way
    into the canonical record and its serialisation."""
    from app.core.reducer import serialize_company_impact
    from tests.phase4.helpers import upstream_impact

    impact = upstream_impact(levy_active=True)
    assert "FIXTURE_LEVY_UPSTREAM" in impact.policy_modifiers_applied

    payload = serialize_company_impact(impact)
    assert "FIXTURE_LEVY_UPSTREAM" in payload["fundamental"]["policy_modifiers_applied"]
    chips = payload["fundamental"]["policy_modifiers"]
    assert [chip["modifier_id"] for chip in chips] == ["FIXTURE_LEVY_UPSTREAM"]
    assert chips[0]["modifier_type"] == "THRESHOLD_CAPTURE"
    assert chips[0]["source_url"] == "https://fixture.invalid/notification/upstream-levy"
    assert chips[0]["status"] == "APPLIED"


# --- stale policy state blocks PRIMARY --------------------------------------

def test_stale_policy_state_blocks_primary():
    """§9.3: if `policy_state` is stale past its horizon, affected companies
    cannot reach PRIMARY. It is a PRIMARY-tier rule, not a hard block: the
    company still publishes as a ripple if it clears that (weaker) bar."""
    from app.core.gates import ImpactDraft, evaluate_primary, evaluate_secondary
    from app.core.config_loader import load_gate_config
    from tests.phase4.helpers import clean_primary_draft

    config = load_gate_config()
    fresh = clean_primary_draft()
    assert evaluate_primary(fresh, config).tier == "PRIMARY"

    stale = ImpactDraft(**{**fresh.__dict__, "policy_state_stale": True})
    primary = evaluate_primary(stale, config)
    assert primary.tier is None
    assert primary.rejection_reason == "PRIMARY_FAILED_POLICY_STATE_FRESHNESS"
    # ...and the secondary walk, evaluated independently, still admits it.
    assert evaluate_secondary(stale, config).tier == "SECONDARY_RIPPLE"


def test_a_stale_policy_state_reaches_the_gate_from_the_channel_alone():
    """Two lines of defence, exactly like `exposure_stale`: a caller that
    forgets to thread the event context cannot un-block the company."""
    from tests.phase4.helpers import upstream_impact

    impact = upstream_impact(levy_active=True, policy_state_stale=True)
    assert impact.publication_tier != "PRIMARY"
    names = {rule["rule"] for rule in impact.gate_trace}
    assert "policy_state_freshness" in names


# --- THE DEPLOYED REGISTRY IS STRUCTURE ONLY --------------------------------

def _deployed() -> dict:
    return yaml.safe_load(DEPLOYED_REGISTRY.read_text(encoding="utf-8"))


def test_the_deployed_registry_scaffolds_the_minimum_india_set():
    from app.analysis.policy.registry import MINIMUM_INDIA_REGISTRY, load_registry

    registry = load_registry()
    assert {entry.modifier_id for entry in registry.entries} == set(
        MINIMUM_INDIA_REGISTRY)


def test_no_deployed_modifier_carries_a_parameter_value():
    """THE FABRICATION GUARD. Levy rates, thresholds, ceilings and capture
    fractions are claims about the world and none of them came from a source,
    so every one of them is null and `_required` names what is missing."""
    for entry in _deployed()["modifiers"]:
        parameters = entry["parameters"]
        assert parameters["_required"], f"{entry['id']}: nothing declared required"
        for name, value in parameters.items():
            if name == "_required":
                continue
            assert value is None, (
                f"{entry['id']}.{name} = {value!r}: a policy parameter value in "
                "the deployed registry is fabricated data")
        assert set(parameters["_required"]) == set(parameters) - {"_required"}


def test_every_deployed_modifier_names_an_owner_placeholder_and_loads_inactive():
    from app.analysis.policy.registry import OWNER_PLACEHOLDER, load_registry

    registry = load_registry()
    assert registry.entries
    for entry in registry.entries:
        assert entry.owner == OWNER_PLACEHOLDER
        assert entry.status == "SCAFFOLD"
        assert not entry.is_active(FIXTURE_TODAY)


def test_the_deployed_registry_can_apply_nothing_at_all():
    from app.analysis.policy.registry import load_registry
    from app.analysis.policy.transforms import apply_modifiers

    registry = load_registry()
    for tag in {entry.applies_to_tag for entry in registry.entries if
                entry.applies_to_tag}:
        assert registry.active_for(tag, FIXTURE_TODAY) == ()

    channel = realization_channel(exposure_tag="revenue:crude_realization",
                                  delta_pct=0.064)
    result = apply_modifiers((channel,), as_of_date=FIXTURE_TODAY,
                             policy_state=fixture_policy_state(),
                             registry=registry)
    assert result.applied == ()
    assert result.channels == (channel,)


def test_an_owner_signed_entry_with_complete_parameters_does_activate():
    """The scaffold refuses for a REASON, not because activation is broken."""
    from app.analysis.policy.registry import modifier_from_mapping

    entry = modifier_from_mapping({
        "modifier_id": "FIXTURE_SIGNED", "applies_to_tag": "realization:fixture_product",
        "jurisdiction": "FIXTURELAND", "modifier_type": "SUBSIDY_SHARE",
        "parameters": {"retained_fraction": 0.25},
        "effective_from": "2200-01-01", "effective_to": None,
        "source_url": "https://fixture.invalid/signed", "owner": "human:fixture-owner",
        "review_interval_days": 30, "last_reviewed_at": "2226-02-22"})
    assert entry.status == "ACTIVE"
    assert entry.is_active(FIXTURE_TODAY)


@pytest.mark.parametrize("break_it", [
    {"owner": None},
    {"owner": "OWNER-REQUIRED"},
    {"parameters": {"_required": ["retained_fraction"], "retained_fraction": None}},
    {"source_url": None},
    {"effective_from": None},
    {"review_interval_days": None},
    {"last_reviewed_at": None},
])
def test_an_incomplete_entry_never_activates(break_it):
    from app.analysis.policy.registry import modifier_from_mapping

    base = {
        "modifier_id": "FIXTURE_SIGNED", "applies_to_tag": "realization:fixture_product",
        "jurisdiction": "FIXTURELAND", "modifier_type": "SUBSIDY_SHARE",
        "parameters": {"retained_fraction": 0.25},
        "effective_from": "2200-01-01", "effective_to": None,
        "source_url": "https://fixture.invalid/signed", "owner": "human:fixture-owner",
        "review_interval_days": 30, "last_reviewed_at": "2226-02-22"}
    entry = modifier_from_mapping({**base, **break_it})
    assert entry.status == "SCAFFOLD"
    assert not entry.is_active(FIXTURE_TODAY)


def test_the_registry_refuses_a_modifier_type_it_has_no_transfer_function_for():
    from app.analysis.policy.registry import PolicyRegistryError, modifier_from_mapping

    with pytest.raises(PolicyRegistryError):
        modifier_from_mapping({
            "modifier_id": "FIXTURE_BOGUS", "applies_to_tag": "realization:fixture_product",
            "jurisdiction": "FIXTURELAND", "modifier_type": "VIBES",
            "parameters": {}, "effective_from": "2200-01-01", "effective_to": None,
            "source_url": None, "owner": None, "review_interval_days": None,
            "last_reviewed_at": None})


def test_every_deployed_tag_is_in_the_closed_vocabulary_or_declared_pending():
    from app.ledger.exposure_tags import load_vocabulary

    vocabulary = set(load_vocabulary().tags)
    for entry in _deployed()["modifiers"]:
        tag = entry.get("applies_to_tag")
        if tag is None:
            assert entry.get("pending_tag"), (
                f"{entry['id']} has no tag and does not say which one it needs")
            continue
        assert tag in vocabulary, f"{entry['id']} names an unknown tag {tag!r}"


def test_the_deployed_registry_dates_are_structural_not_financial():
    """A date on which a public regime came into force is a STRUCTURAL fact
    about the world, not a financial parameter. Every one present must carry
    a `date_basis` saying which public act it refers to."""
    for entry in _deployed()["modifiers"]:
        if entry.get("effective_from") is not None:
            assert entry.get("date_basis"), (
                f"{entry['id']} states an effective_from with no date_basis")
        assert entry.get("effective_to") is None


def test_the_registry_reports_what_it_is_waiting_for():
    from app.analysis.policy.registry import load_registry

    pending = load_registry().awaiting_parameters()
    assert pending
    for entry in pending:
        assert entry.owner_field_required
        assert entry.missing_parameters


def test_a_state_beyond_its_freshness_window_is_unknown_at_that_horizon():
    """A regime state measured with a 30-day freshness window says nothing
    about day 270. Treating it as known there would be assuming a default
    regime at exactly the horizon where regimes change."""
    store = fixture_policy_state("fixture_revision_active")
    assert not store.is_unknown_or_stale(
        "fixture_revision_active", as_of=FIXTURE_TODAY, horizon_days=5)
    assert store.is_unknown_or_stale(
        "fixture_revision_active", as_of=FIXTURE_TODAY, horizon_days=270)
    assert store.is_unknown_or_stale(
        "fixture_revision_active", as_of=date(2227, 2, 22), horizon_days=5)
    assert store.is_unknown_or_stale(
        "nothing_by_that_name", as_of=FIXTURE_TODAY, horizon_days=5)


# --- FIX ROUND 1 -----------------------------------------------------------

def test_an_administered_override_rewrites_the_channels_provenance(
        ):
    """I-2 REGRESSION. A STATE_DEPENDENT override replaces a parameter with an
    ADMINISTERED value. The channel's `param_sources` must say so: leaving it
    at DISCLOSED_CALL is a field-level contradiction inside one record, in
    exactly the field a reader consults to ask where a number came from."""
    from app.analysis.policy.transforms import apply_modifiers

    channel = realization_channel(
        exposure_tag="realization:fixture_state_dependent", delta_pct=0.10,
        elasticity=1.0, capture=0.5, source="DISCLOSED_CALL")
    assert channel.param_sources["regulatory_capture_fraction"] == "DISCLOSED_CALL"

    result = apply_modifiers(
        (channel,), as_of_date=FIXTURE_TODAY,
        policy_state=fixture_policy_state("fixture_revision_active"),
        registry=fixture_registry("FIXTURE_C_STATE"))

    modified = result.channels[0]
    assert modified.params["regulatory_capture_fraction"].source == "ADMINISTERED"
    assert modified.param_sources["regulatory_capture_fraction"] == "ADMINISTERED"
    # the parameter the modifier did NOT touch keeps its own provenance
    assert modified.param_sources["realization_elasticity"] == "DISCLOSED_CALL"
    assert (set(modified.param_sources) == set(modified.params)), (
        "param_sources and params are one map projected twice; they cannot "
        "name different parameters")


def test_the_administered_source_reaches_the_channel_signal_payload():
    """I-2, one layer out: the provenance the reader actually sees."""
    from app.analysis.policy.transforms import apply_modifiers
    from app.analysis.sensitivity.config import load_materiality_config
    from app.analysis.sensitivity.engine import channel_signals
    from app.analysis.sensitivity.monte_carlo import serialize_materiality, simulate
    from tests.phase4.conftest import (
        FIXTURE_ANALYSIS_VERSION, FIXTURE_EVENT_ID, FIXTURE_NOW,
    )

    config = load_materiality_config()
    channel = realization_channel(
        exposure_tag="realization:fixture_state_dependent", delta_pct=0.10,
        elasticity=1.0, capture=0.5, source="DISCLOSED_CALL")
    modified = apply_modifiers(
        (channel,), as_of_date=FIXTURE_TODAY,
        policy_state=fixture_policy_state("fixture_revision_active"),
        registry=fixture_registry("FIXTURE_C_STATE"))
    materiality = simulate(
        modified.channels, ebitda_ttm_inr=1_000_000_000.0,
        event_id=FIXTURE_EVENT_ID, company_id=9401,
        analysis_version=FIXTURE_ANALYSIS_VERSION, config=config)
    signals, _ = channel_signals(
        modified.channels,
        materiality_block=serialize_materiality(materiality, config),
        ebitda_ttm_inr=1_000_000_000.0, event_id=FIXTURE_EVENT_ID,
        company_id=9401, analysis_version=FIXTURE_ANALYSIS_VERSION,
        created_at=FIXTURE_NOW, config=config,
        policy_modifiers=modified.as_payload())

    sources = signals[0].payload["param_sources"]
    assert sources["regulatory_capture_fraction"] == "ADMINISTERED"
    assert sources["realization_elasticity"] == "DISCLOSED_CALL"


def test_a_parameter_override_and_a_scaling_modifier_commute():
    """M-6. A STATE_DEPENDENT override and a scaling modifier on the SAME
    channel, offered in both orders, produce the same number.

    Not because multiplication commutes: scaling modifiers contribute factors
    applied at the end, the override replaces an entry in a parameter map, and
    the point estimate is computed once from the final map and the final
    factor list."""
    from app.analysis.policy.registry import PolicyRegistry, modifier_from_mapping
    from app.analysis.policy.transforms import apply_modifiers
    from tests.phase4.conftest import fixture_modifier

    override = dict(fixture_modifier("FIXTURE_C_STATE"),
                    modifier_id="FIXTURE_M_OVERRIDE")
    scaling = dict(fixture_modifier("FIXTURE_D_SUBSIDY"),
                   modifier_id="FIXTURE_Z_SCALE",
                   applies_to_tag="realization:fixture_state_dependent")
    entries = [modifier_from_mapping(override), modifier_from_mapping(scaling)]

    channel = realization_channel(
        exposure_tag="realization:fixture_state_dependent", delta_pct=0.10,
        elasticity=1.0, capture=0.5)
    results = [
        apply_modifiers((channel,), as_of_date=FIXTURE_TODAY,
                        policy_state=fixture_policy_state("fixture_revision_active"),
                        registry=PolicyRegistry(tuple(order)))
        for order in (entries, list(reversed(entries)))]

    # capture 0.5 -> 0.0 doubles the channel to 100,000,000; the subsidy share
    # then retains a quarter of it.
    assert results[0].channels[0].delta_ebitda_inr == pytest.approx(25_000_000.0)
    assert (results[0].channels[0].delta_ebitda_inr
            == results[1].channels[0].delta_ebitda_inr)
    assert results[0].applied == results[1].applied == (
        "FIXTURE_M_OVERRIDE", "FIXTURE_Z_SCALE")


@pytest.mark.parametrize("name,value", [
    ("capture_fraction_above", 1.2),
    ("capture_fraction_above", -0.1),
    ("retained_fraction", 1.5),
    ("retained_fraction", -0.01),
])
def test_a_share_outside_its_domain_is_refused_at_load(name, value):
    """M-3. A `capture_fraction_above` of 1.2 does not mean a harsher levy --
    the transfer function returns a NEGATIVE factor and the channel silently
    flips sign. A typo in a YAML must not become a reversed impact call."""
    from app.analysis.policy.registry import PolicyRegistryError, modifier_from_mapping

    with pytest.raises(PolicyRegistryError, match="domain"):
        modifier_from_mapping({
            "modifier_id": "FIXTURE_OUT_OF_DOMAIN",
            "applies_to_tag": "realization:fixture_product",
            "jurisdiction": "FIXTURELAND",
            "modifier_type": ("THRESHOLD_CAPTURE"
                              if name == "capture_fraction_above"
                              else "SUBSIDY_SHARE"),
            "parameters": {"threshold_level": 100.0, name: value},
            "effective_from": "2200-01-01", "effective_to": None,
            "source_url": "https://fixture.invalid/x", "owner": "human:fixture",
            "review_interval_days": 30, "last_reviewed_at": "2226-02-22"})


def test_a_null_share_is_a_scaffold_not_a_domain_error():
    """A null parameter says "nobody has supplied one yet", which is the
    deployed state of every entry in the registry. Refusing nulls as out of
    domain would refuse the whole file."""
    from app.analysis.policy.registry import MINIMUM_INDIA_REGISTRY, load_registry

    assert len(load_registry().entries) == len(MINIMUM_INDIA_REGISTRY)


@pytest.mark.parametrize("value", [0.0, 1.0, 0.25])
def test_a_share_inside_its_domain_loads(value):
    from app.analysis.policy.registry import modifier_from_mapping

    entry = modifier_from_mapping({
        "modifier_id": "FIXTURE_IN_DOMAIN",
        "applies_to_tag": "realization:fixture_product",
        "jurisdiction": "FIXTURELAND", "modifier_type": "SUBSIDY_SHARE",
        "parameters": {"retained_fraction": value},
        "effective_from": "2200-01-01", "effective_to": None,
        "source_url": "https://fixture.invalid/x", "owner": "human:fixture",
        "review_interval_days": 30, "last_reviewed_at": "2226-02-22"})
    assert entry.status == "ACTIVE"


def test_the_migration_downgrade_is_symmetric_with_its_upgrade():
    """M-4. `upgrade` creates each object only if absent, so `downgrade` must
    drop each only if present -- otherwise a half-built schema raises halfway
    through a downgrade and ends in a state neither version describes."""
    import ast
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[2] / "alembic" /
              "versions" / "0014_v5_policy_horizon.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    downgrade = next(node for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef)
                     and node.name == "downgrade")
    guards = [node for node in ast.walk(downgrade) if isinstance(node, ast.If)]
    assert len(guards) >= 3, (
        "every drop in downgrade() must be guarded on the object existing")
    assert "get_table_names" in source


def test_make_params_helper_is_not_smuggling_a_band_width():
    """Guard on the tests themselves: the fixture bands come from the deployed
    policy file, so a test can never silently disagree with the product."""
    from app.analysis.sensitivity.config import load_materiality_config

    dist = make_params(hedge_ratio=(0.5, "FILED"))["hedge_ratio"]
    width = load_materiality_config().band_width_for("FILED")
    assert dist.hi == pytest.approx(0.5 * (1.0 + width))
