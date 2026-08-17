"""GENERICITY PROOF -- a commodity this system has never heard of.

THE CLAIM UNDER TEST. The V5 canonical path (discovery -> sensitivity ->
reducer -> gate -> sectioning) is commodity-agnostic: a new shock variable,
a new exposure tag, a new mechanism edge and a new section label are all
CONFIGURATION, and none of them needs a line of Python.

SO THIS TEST CHANGES NO PRODUCTION MODULE AND NO SHIPPED CONFIG FILE. It
takes the three deployed YAML policy files, adds exactly one synthetic entry
to each in a temp directory, and runs the REAL loaders against those paths.
Every loader in the path already accepts a `path` override, which is the
property being exercised: if the vocabulary, the modelled-variable list, the
mechanism graph and the section taxonomy are genuinely data, then
SYNTH_COMMODITY_X -- a substance that does not exist -- publishes a section.

WHAT IS SYNTHETIC AND SAID SO. Two fixture companies, one fixture exposure
row each, round-number bases. Nothing here is a claim about any real company;
`_fixture: true` markers and the SYNTH tickers keep it that way.
"""
from datetime import date, datetime, timezone

import pytest
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app import models  # noqa: F401 -- registers every table on Base

# --- the synthetic vocabulary, in one place ---------------------------------

SHOCK_VARIABLE = "SYNTH_COMMODITY_X"
EXPOSURE_TAG = "input:synth_commodity_x"
MECHANISM_ID = "synth_input_cost"           # == mechanism_edge.edge_id
SECTION_LABEL = "SYNTHETIC COMMODITY X INPUTS"

FIXTURE_TODAY = date(2228, 4, 4)
FIXTURE_NOW = datetime(2228, 4, 4, 4, 44, tzinfo=timezone.utc)
FIXTURE_EVENT_ID = "fixture:synth-commodity-x-shock"
FIXTURE_ANALYSIS_VERSION = "v5:fixture:genericity"

# Round numbers, chosen so the arithmetic is checkable by hand:
#   COST = -(base * share * delta * (1-pass_through) * (1-hedge) * ownership)
#        = -(1000 * 0.30 * 0.10 * 0.8 * 1.0 * 1.0) = -24.0
#   pct  = -24.0 / 500.0 * 100 = -4.8 %
BASE_VALUE_INR = 1000.0
EBITDA_INR = 500.0
SHARE_OF_BASE = 0.30
DELTA_PCT = 0.10
PASS_THROUGH = 0.2
EXPECTED_PCT = -4.8


# --- config only: three deployed YAMLs, one synthetic entry each ------------

@pytest.fixture()
def synthetic_config(tmp_path):
    """The three policy files, each with ONE line added. No code is touched.

    Returns a mapping of loader-path overrides. Every value is a real YAML
    file on disk that the deployed loader parses with its deployed schema --
    nothing here monkeypatches a module or injects a fake object.
    """
    from app.discovery.config import DISCOVERY_CONFIG_PATH
    from app.ledger.exposure_tags import EXPOSURE_TAGS_PATH
    from app.output.section_config import SECTION_TAXONOMY_PATH

    # 1. VOCABULARY -- a new leaf under the `input` family.
    tags = yaml.safe_load(EXPOSURE_TAGS_PATH.read_text(encoding="utf-8"))
    tags["families"]["input"]["synth"] = {"synth_commodity_x": None}
    tags_path = tmp_path / "exposure_tags.yaml"
    tags_path.write_text(yaml.safe_dump(tags, sort_keys=False), encoding="utf-8")

    # 2. DISCOVERY POLICY -- a new modelled shock variable.
    discovery = yaml.safe_load(DISCOVERY_CONFIG_PATH.read_text(encoding="utf-8"))
    discovery["modelled_shock_variables"].append(SHOCK_VARIABLE)
    discovery_path = tmp_path / "discovery.yaml"
    discovery_path.write_text(yaml.safe_dump(discovery, sort_keys=False),
                              encoding="utf-8")

    # 3. SECTION TAXONOMY -- a rendered label for the new mechanism.
    taxonomy = yaml.safe_load(SECTION_TAXONOMY_PATH.read_text(encoding="utf-8"))
    taxonomy["labels"][MECHANISM_ID] = SECTION_LABEL
    taxonomy_path = tmp_path / "section_taxonomy.yaml"
    taxonomy_path.write_text(yaml.safe_dump(taxonomy, sort_keys=False),
                             encoding="utf-8")

    return {"exposure_tags": tags_path, "discovery": discovery_path,
            "section_taxonomy": taxonomy_path}


# --- the throwaway universe --------------------------------------------------

@pytest.fixture()
def synthetic_session(synthetic_config):
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        _seed(session, synthetic_config)
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed(session, config):
    """Two fixture companies tagged against the synthetic exposure, plus the
    ONE mechanism edge that reaches them. The tag is admitted to the closed
    vocabulary by running the DEPLOYED loader over the synthetic YAML -- the
    DB triggers reject it otherwise, which is the point."""
    import json

    from app.ledger.exposure_tags import register_vocabulary
    from app.ledger.review import review_session
    from app.models import Company

    register_vocabulary(session, config["exposure_tags"])

    # APPROVED + a reviewer name is what makes an edge walkable, for every
    # derivation (app/graph/traverse.py). This edge is the one the synthetic
    # commodity is discovered through, so it is seeded approved and signed.
    session.execute(text(
        "INSERT INTO mechanism_edge (edge_id, from_node, to_node, exposure_tag, "
        "relationship_type, distance, derivation, reviewed_by, review_status, "
        "confidence, source_url, created_at) VALUES (:edge_id, :from_node, "
        ":to_node, :tag, 'INPUT_COST', 1, 'AUTHORED', 'human:fixture-reviewer', "
        "'APPROVED', 0.5, 'https://fixture.invalid/edge', :created_at)"), {
            "edge_id": MECHANISM_ID, "from_node": SHOCK_VARIABLE,
            "to_node": "synth_x_users", "tag": EXPOSURE_TAG,
            "created_at": FIXTURE_NOW.isoformat()})

    for index in range(2):
        ticker = f"SYNTHX{index}"
        company = Company(ticker=ticker, name=f"SYNTHETIC X USER {index} LTD",
                          sector="chemicals", sub_sector="synth_x_users",
                          index_tier="OTHER", market="INDIA", market_cap=1000.0,
                          tradeability="NORMAL")
        session.add(company)
        session.flush()

        with review_session(session):
            session.execute(text(
                "INSERT INTO company_exposure (exposure_id, company_id, "
                "exposure_kind, exposure_tag, share_of_base, base_kind, "
                "base_value_inr, measurement, source_type, source_url, "
                "as_of_date, freshness_days, confidence, created_by, "
                "reviewed_by) VALUES (:exposure_id, :company_id, 'INPUT_COST', "
                ":tag, :share, 'COGS', :base, 'FILED', 'ANNUAL_REPORT', "
                "'https://fixture.invalid/ar', :as_of, 400, 0.1111, "
                "'ingest:fixture', 'human:fixture-reviewer')"), {
                    "exposure_id": f"synthx-{ticker}", "company_id": company.id,
                    "tag": EXPOSURE_TAG, "share": SHARE_OF_BASE,
                    "base": BASE_VALUE_INR,
                    "as_of": FIXTURE_TODAY.isoformat()})

        session.execute(text(
            "INSERT INTO company_financials (company_id, fiscal_period, "
            "ebitda_inr, source_url, as_of_date) VALUES (:company_id, 'FY28', "
            ":ebitda, 'https://fixture.invalid/ar', :as_of)"), {
                "company_id": company.id, "ebitda": EBITDA_INR,
                "as_of": FIXTURE_TODAY.isoformat()})

        session.execute(text(
            "INSERT INTO pass_through_curve (curve_id, company_id, "
            "exposure_tag, points, basis, as_of_date) VALUES (:curve_id, "
            ":company_id, :tag, :points, 'DISCLOSED_CALL', :as_of)"), {
                "curve_id": f"synthx-c-{ticker}", "company_id": company.id,
                "tag": EXPOSURE_TAG,
                "points": json.dumps([{"lag_days": 0, "fraction": PASS_THROUGH},
                                      {"lag_days": 365, "fraction": PASS_THROUGH}]),
                "as_of": FIXTURE_TODAY.isoformat()})

        session.execute(text(
            "INSERT INTO company_modifier (modifier_id, company_id, "
            "modifier_kind, applies_to_tag, parameters, effective_from, "
            "source_url, as_of_date, confidence) VALUES (:modifier_id, "
            ":company_id, 'HEDGE', :tag, :parameters, :effective_from, "
            "'https://fixture.invalid/call', :as_of, 0.1111)"), {
                "modifier_id": f"synthx-m-{ticker}", "company_id": company.id,
                "tag": EXPOSURE_TAG,
                "parameters": json.dumps({"hedge_ratio": 0.0,
                                          "measurement": "FILED"}),
                "effective_from": date(2228, 1, 1).isoformat(),
                "as_of": FIXTURE_TODAY.isoformat()})

    session.flush()


# --- stage 1: DISCOVERY -----------------------------------------------------

def _discover(session, config):
    from app.discovery.config import load_discovery_config
    from app.discovery.engine import DiscoveryEvent, DiscoveryShock, discover

    event = DiscoveryEvent(
        event_id=FIXTURE_EVENT_ID, mentions=(),
        shocks=(DiscoveryShock(shock_id="synth:1", variable=SHOCK_VARIABLE,
                               sign="UP", magnitude_pct=10.0),))
    return discover(session, event, as_of=FIXTURE_TODAY,
                    config=load_discovery_config(config["discovery"]))


def test_discovery_finds_candidates_for_a_variable_it_has_never_seen(
        synthetic_session, synthetic_config):
    pool = _discover(synthetic_session, synthetic_config)

    assert pool.unmodelled_variables == (), (
        "the variable is in modelled_shock_variables -- config alone")
    assert pool.size == 2, f"expected both tagged companies, got {pool.size}"
    for candidate in pool.candidates:
        assert candidate.discovery_source == "MECHANISM"
        assert candidate.via_tag == EXPOSURE_TAG
        assert candidate.mechanism_id == MECHANISM_ID
        assert candidate.graph_distance == 1


def test_an_unregistered_variable_is_reported_not_guessed(synthetic_session):
    """The control. Without the discovery.yaml line, the SAME shock finds
    nothing and says so -- so the test above is measuring the config entry."""
    from app.discovery.config import load_discovery_config
    from app.discovery.engine import DiscoveryEvent, DiscoveryShock, discover

    event = DiscoveryEvent(
        event_id=FIXTURE_EVENT_ID, mentions=(),
        shocks=(DiscoveryShock(shock_id="synth:1", variable=SHOCK_VARIABLE,
                               sign="UP", magnitude_pct=10.0),))
    pool = discover(synthetic_session, event, as_of=FIXTURE_TODAY,
                    config=load_discovery_config())   # the DEPLOYED policy

    assert pool.size == 0
    assert pool.unmodelled_variables == (SHOCK_VARIABLE,)


# --- stages 2-5: SENSITIVITY -> REDUCER -> GATE -> SECTIONING ---------------

def _run_full_path(session, config):
    """The whole canonical path for one synthetic event."""
    from app.analysis.sensitivity.channels import Shock
    from app.analysis.sensitivity.engine import analyse_company
    from app.core.config_loader import (
        load_gate_config, load_horizon_policy, load_sensitivity_policy,
    )
    from app.core.reducer import EventContext, ReducerConfig, reduce_company_impact
    from app.core.signals import make_signal
    from app.output.section_config import load_section_taxonomy
    from app.output.sections import build_sections

    pool = _discover(session, config)
    impacts = []

    for candidate in pool.candidates:
        shock = Shock(shock_id="synth:1", exposure_tag=candidate.via_tag,
                      delta_pct=DELTA_PCT, horizon_days=90,
                      mechanism_id=candidate.mechanism_id)
        run = analyse_company(
            session, company_id=candidate.company_id, shocks=(shock,),
            event_id=FIXTURE_EVENT_ID, analysis_version=FIXTURE_ANALYSIS_VERSION,
            created_at=FIXTURE_NOW, as_of=FIXTURE_TODAY)
        assert run.materiality is not None, (
            f"company {candidate.company_id} was not sizeable: "
            f"{run.uncomputable_channels}")

        ticker = session.execute(text("SELECT ticker FROM companies WHERE id = :i"),
                                 {"i": candidate.company_id}).scalar()
        signals = list(run.signals) + [
            make_signal(event_id=FIXTURE_EVENT_ID, company_id=candidate.company_id,
                        stage="ENTITY", kind="ENTITY_RESOLUTION",
                        payload={"ticker": ticker, "isin": None,
                                 "resolution": "RESOLVED",
                                 "entity_status": "ACTIVE", "_fixture": True},
                        created_by="human:fixture",
                        analysis_version=FIXTURE_ANALYSIS_VERSION,
                        created_at=FIXTURE_NOW),
            make_signal(event_id=FIXTURE_EVENT_ID, company_id=candidate.company_id,
                        stage="DISCOVERY", kind="DISCOVERY",
                        payload={"discovery_source": candidate.discovery_source,
                                 "directness": "INDIRECT",
                                 "graph_distance": candidate.graph_distance,
                                 "_fixture": True},
                        created_by="human:fixture",
                        analysis_version=FIXTURE_ANALYSIS_VERSION,
                        created_at=FIXTURE_NOW),
            make_signal(event_id=FIXTURE_EVENT_ID, company_id=candidate.company_id,
                        stage="CLAIMS", kind="EVIDENCE_BINDING",
                        payload={"claim_id": f"synthx-claim-{candidate.company_id}",
                                 "claim_type": "COST_EXPOSURE",
                                 "binding_status": "BOUND", "evidence_grade": "C",
                                 "evidence_ids": [f"synthx-SYNTHX"],
                                 "_fixture": True},
                        created_by="human:fixture",
                        analysis_version=FIXTURE_ANALYSIS_VERSION,
                        created_at=FIXTURE_NOW),
        ]

        impacts.append(reduce_company_impact(signals, ReducerConfig(
            gate_config=load_gate_config(),
            event_context=EventContext(event_status="CONFIRMED",
                                       shock_magnitude_confidence=0.9,
                                       exposure_stale=False),
            sensitivity_policy=load_sensitivity_policy(),
            horizon_policy=load_horizon_policy())))

    sections = build_sections(
        impacts, load_section_taxonomy(config["section_taxonomy"]))
    return impacts, sections


def test_sensitivity_sizes_the_synthetic_shock(synthetic_session, synthetic_config):
    impacts, _ = _run_full_path(synthetic_session, synthetic_config)
    assert len(impacts) == 2
    for impact in impacts:
        p50 = impact.sensitivity["delta_ebitda_pct"]["p50"]
        assert p50 == pytest.approx(EXPECTED_PCT, abs=0.01), (
            "the §5.1 COST formula ran on a tag it has never seen")
        assert impact.net_effect == "NEGATIVE"
        assert impact.mechanism_id == MECHANISM_ID


def test_the_gate_publishes_the_synthetic_companies(synthetic_session,
                                                    synthetic_config):
    impacts, _ = _run_full_path(synthetic_session, synthetic_config)
    tiers = sorted(i.publication_tier for i in impacts)
    assert all(tier in ("PRIMARY", "SECONDARY_RIPPLE") for tier in tiers), (
        f"nothing published: {[(i.publication_tier, i.rejection_reason) for i in impacts]}")


def test_sectioning_renders_a_section_for_the_synthetic_mechanism(
        synthetic_session, synthetic_config):
    _, sections = _run_full_path(synthetic_session, synthetic_config)

    assert sections, "no section was produced for the synthetic mechanism"
    labels = [s.label for s in sections]
    assert any(SECTION_LABEL in label for label in labels), labels
    assert all("UNCLASSIFIED" not in label for label in labels), labels

    section = next(s for s in sections if SECTION_LABEL in s.label)
    assert section.key.mechanism_id == MECHANISM_ID
    assert len(section.companies) == 2
