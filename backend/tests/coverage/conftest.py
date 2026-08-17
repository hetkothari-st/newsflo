"""The synthetic universe the coverage harness measures itself against.

WHAT THIS IS AND IS NOT. Ripple recall cannot be measured against the real
listed universe today, because the exposure ledger is empty (DATA_GAPS §5).
So the harness is measured against a universe a test wrote: obviously fake
companies, round-number exposures, one shock. Passing proves the harness's
ARITHMETIC -- that it counts recall and precision correctly and attributes a
missing family to the right axis. It proves NOTHING about coverage of the
Indian market, which is zero.
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app import models  # noqa: F401 -- registers every table on Base

FIXTURES = Path(__file__).resolve().parent / "fixtures"
UNIVERSE_JSON = FIXTURES / "synthetic_universe.json"
EXPECTED_MAP_YAML = FIXTURES / "expected_ripple_map.yaml"

FIXTURE_TODAY = date(2228, 4, 4)
FIXTURE_NOW = datetime(2228, 4, 4, 4, 44, tzinfo=timezone.utc)


def load_universe() -> dict:
    raw = json.loads(UNIVERSE_JSON.read_text(encoding="utf-8"))
    assert raw["_fixture"] is True
    return raw


def load_expected_map() -> dict:
    raw = yaml.safe_load(EXPECTED_MAP_YAML.read_text(encoding="utf-8"))
    assert raw["signed_off_by"] is None, (
        "the expected-ripple map claims a sign-off; update this assertion "
        "deliberately when the owner really has signed it")
    return raw


def expected_for(variable: str) -> dict:
    for entry in load_expected_map()["shocks"]:
        if entry["shock"]["variable"] == variable:
            return entry
    raise KeyError(variable)


def _insert_edge(session, edge):
    """`review_status = 'APPROVED'` with a reviewer name is what makes an edge
    walkable, for every derivation (`app/graph/traverse.py`). These fixture
    edges exist to be traversed, so they are seeded approved and signed."""
    session.execute(text(
        "INSERT INTO mechanism_edge (edge_id, from_node, to_node, exposure_tag, "
        "relationship_type, distance, derivation, reviewed_by, review_status, "
        "confidence, source_url, created_at) VALUES (:edge_id, :from_node, "
        ":to_node, :exposure_tag, :relationship_type, 1, 'AUTHORED', "
        "'human:fixture-reviewer', 'APPROVED', 0.5, "
        "'https://fixture.invalid/edge', :created_at)"),
        dict(edge, created_at=FIXTURE_NOW.isoformat()))


def build_universe(session, *, untagged_families: tuple[str, ...] = (),
                   share_overrides: dict | None = None,
                   extra_families: tuple[dict, ...] = ()) -> dict:
    """Seed the whole synthetic universe. Returns {family: [company_id, ...]}.

    `untagged_families` builds the family's COMPANIES but not their exposure
    rows -- an injected C-axis gap. It is a build-time option rather than a
    DELETE afterwards because `company_exposure` refuses DELETE outright
    (Phase 1 fix round 1, I1: nobody deletes a reviewed claim, not even the
    reviewer), and working around that guard in a test would be working
    around the guarantee it exists to give.

    `share_overrides` is {family: share_of_base}. It is the MUTATION knob for
    the falsifiability tests (review round 1, I1/I2): raise a rejected
    family's exposure until it clears the gate and watch precision, the
    expected_absent check or the marginal exclusion react. A metric that
    cannot be made to move by any mutation is not measuring anything.

    `extra_families` appends rows in the same shape as the fixture's
    `families` list, for a test that needs a company the shipped universe
    does not describe.
    """
    share_overrides = dict(share_overrides or {})
    from app.ledger.review import review_session
    from app.models import Company

    universe = load_universe()
    parameters = universe["_parameters"]
    base_value = float(parameters["base_value_inr"])
    ebitda = float(parameters["ebitda_inr"])

    for edge in universe["edges"]:
        _insert_edge(session, edge)

    members: dict[str, list[int]] = {}
    for entry in tuple(universe["families"]) + tuple(extra_families):
        family = entry["family"]
        members[family] = []
        share = float(share_overrides.get(family, entry["share_of_base"] or 0.0))
        for index in range(int(entry["companies"])):
            ticker = f"SYN{family.upper()[:6]}{index}"
            company = Company(
                ticker=ticker, name=f"SYNTHETIC {family.upper()} {index} LTD",
                sector=entry["sector"], sub_sector=entry.get("sub_sector", family),
                index_tier="OTHER",
                market="INDIA", market_cap=1000.0, tradeability="NORMAL")
            session.add(company)
            session.flush()
            members[family].append(company.id)

            if not entry["tag"] or family in untagged_families:
                continue

            with review_session(session):
                session.execute(text(
                    "INSERT INTO company_exposure (exposure_id, company_id, "
                    "exposure_kind, exposure_tag, share_of_base, base_kind, "
                    "base_value_inr, measurement, source_type, source_url, "
                    "as_of_date, freshness_days, confidence, created_by, "
                    "reviewed_by) VALUES (:exposure_id, :company_id, "
                    ":exposure_kind, :exposure_tag, :share_of_base, 'COGS', "
                    ":base_value_inr, 'FILED', 'ANNUAL_REPORT', "
                    "'https://fixture.invalid/ar', :as_of_date, 400, 0.1111, "
                    "'ingest:fixture', 'human:fixture-reviewer')"), {
                        "exposure_id": f"syn-x-{ticker}",
                        "company_id": company.id,
                        "exposure_kind": entry["exposure_kind"],
                        "exposure_tag": entry["tag"],
                        "share_of_base": share,
                        "base_value_inr": base_value,
                        "as_of_date": FIXTURE_TODAY.isoformat()})

            session.execute(text(
                "INSERT INTO company_financials (company_id, fiscal_period, "
                "ebitda_inr, source_url, as_of_date) VALUES (:company_id, "
                "'FY28', :ebitda, 'https://fixture.invalid/ar', :as_of)"), {
                    "company_id": company.id, "ebitda": ebitda,
                    "as_of": FIXTURE_TODAY.isoformat()})

            session.execute(text(
                "INSERT INTO pass_through_curve (curve_id, company_id, "
                "exposure_tag, points, basis, as_of_date) VALUES "
                "(:curve_id, :company_id, :tag, :points, 'DISCLOSED_CALL', "
                ":as_of)"), {
                    "curve_id": f"syn-c-{ticker}", "company_id": company.id,
                    "tag": entry["tag"],
                    "points": json.dumps([
                        {"lag_days": 0,
                         "fraction": float(parameters["pass_through_fraction"])},
                        {"lag_days": 365,
                         "fraction": float(parameters["pass_through_fraction"])}]),
                    "as_of": FIXTURE_TODAY.isoformat()})

            session.execute(text(
                "INSERT INTO company_modifier (modifier_id, company_id, "
                "modifier_kind, applies_to_tag, parameters, effective_from, "
                "source_url, as_of_date, confidence) VALUES (:modifier_id, "
                ":company_id, 'HEDGE', :tag, :parameters, :effective_from, "
                "'https://fixture.invalid/call', :as_of, 0.1111)"), {
                    "modifier_id": f"syn-m-{ticker}", "company_id": company.id,
                    "tag": entry["tag"],
                    "parameters": json.dumps({
                        "hedge_ratio": float(parameters["hedge_ratio"]),
                        "measurement": "FILED"}),
                    "effective_from": date(2228, 1, 1).isoformat(),
                    "as_of": FIXTURE_TODAY.isoformat()})

    session.flush()
    return members


@pytest.fixture()
def coverage_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def coverage_session(coverage_engine):
    session = sessionmaker(bind=coverage_engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def universe(coverage_session):
    return build_universe(coverage_session)
