"""TASK 1.5 -- staleness, and the abstention the whole phase exists to prove.

The phase file's TESTS section, verbatim:
  - exposure older than freshness_days is flagged STALE
  - STALE exposure blocks PRIMARY in the gate
  - pipeline with an empty ledger abstains and publishes nothing

The last one is the DoD's headline item: "with no exposure data, the system
publishes nothing rather than guessing".
"""
from datetime import date, timedelta

from sqlalchemy import text

from tests.phase1.conftest import make_company

EVENT_ID = "fixture:phase1-empty-ledger"
ANALYSIS_VERSION = "v3:fixture:phase1"
AS_OF = date(2226, 2, 22)


def _exposure(session, company_id, *, as_of_date, freshness_days=400,
              exposure_tag="input:fixture_foo"):
    from app.ledger.review import review_session

    row = {
        "exposure_id": f"fixture-{exposure_tag}-{as_of_date}", "company_id": company_id,
        "exposure_kind": "INPUT_COST", "exposure_tag": exposure_tag,
        "share_of_base": 0.1111, "base_kind": "COGS", "base_value_inr": 99999.0,
        "measurement": "FILED", "source_type": "ANNUAL_REPORT",
        "source_url": "https://fixture.invalid/ar", "source_page": "2",
        "as_of_date": as_of_date.isoformat(), "freshness_days": freshness_days,
        "confidence": 0.1111, "created_by": "test:phase1",
        "reviewed_by": "human:fixture",
    }
    with review_session(session):
        session.execute(text(
            "INSERT INTO company_exposure (" + ", ".join(row) + ") VALUES ("
            + ", ".join(f":{c}" for c in row) + ")"), row)
        session.commit()
    return row["exposure_id"]


# --- staleness -------------------------------------------------------------

def test_an_exposure_older_than_freshness_days_is_flagged_stale(ledger_session):
    from app.ledger.staleness import flag_stale_exposures

    company = make_company(ledger_session, ticker="FIXCO.NS", name="Fixture Co Ltd",
                           isin="INFIXTURE001")
    fresh = _exposure(ledger_session, company.id, as_of_date=AS_OF - timedelta(days=10),
                      exposure_tag="input:fixture_fresh")
    old = _exposure(ledger_session, company.id, as_of_date=AS_OF - timedelta(days=401),
                    exposure_tag="input:fixture_old")

    flagged = flag_stale_exposures(ledger_session, as_of=AS_OF)
    assert flagged == 1

    states = dict(ledger_session.execute(
        text("SELECT exposure_id, stale FROM company_exposure")).all())
    assert states[old] == 1
    assert states[fresh] == 0


def test_flagging_is_idempotent_and_unflags_a_refreshed_row(ledger_session):
    from app.ledger.staleness import flag_stale_exposures

    company = make_company(ledger_session, ticker="FIXCO.NS", name="Fixture Co Ltd",
                           isin="INFIXTURE001")
    _exposure(ledger_session, company.id, as_of_date=AS_OF - timedelta(days=401))

    assert flag_stale_exposures(ledger_session, as_of=AS_OF) == 1
    assert flag_stale_exposures(ledger_session, as_of=AS_OF) == 0
    # The same rows, evaluated at a date at which they are NOT yet stale.
    assert flag_stale_exposures(ledger_session, as_of=AS_OF - timedelta(days=200)) == 1
    assert ledger_session.execute(
        text("SELECT stale FROM company_exposure")).scalar() == 0


def test_company_exposure_is_stale_reports_the_gate_input(ledger_session):
    from app.ledger.staleness import company_exposure_is_stale, flag_stale_exposures

    company = make_company(ledger_session, ticker="FIXCO.NS", name="Fixture Co Ltd",
                           isin="INFIXTURE001")
    _exposure(ledger_session, company.id, as_of_date=AS_OF - timedelta(days=401))
    flag_stale_exposures(ledger_session, as_of=AS_OF)

    assert company_exposure_is_stale(ledger_session, company.id, as_of=AS_OF) is True
    assert company_exposure_is_stale(
        ledger_session, company.id, as_of=AS_OF,
        exposure_tags=("input:fixture_other",)) is False


def test_an_empty_ledger_reports_nothing_stale(ledger_session):
    """Nothing exists, so nothing is stale -- the honest answer. Abstention
    comes from having no channels at all, not from a fake staleness flag."""
    from app.ledger.staleness import company_exposure_is_stale

    company = make_company(ledger_session, ticker="FIXCO.NS", name="Fixture Co Ltd",
                           isin="INFIXTURE001")
    assert company_exposure_is_stale(ledger_session, company.id, as_of=AS_OF) is False


# --- the gate --------------------------------------------------------------

def test_a_stale_exposure_blocks_primary_in_the_gate():
    """Non-vacuous by construction: the SAME signal set reaches PRIMARY when
    the exposure backing it is fresh."""
    from app.core.config_loader import load_gate_config
    from app.core.reducer import EventContext, ReducerConfig, reduce_company_impact
    from tests.phase0 import fixtures as phase0

    signals = phase0.signals(phase0.PRIMARY_COMPANY_ID)
    fresh = ReducerConfig(
        gate_config=load_gate_config(),
        event_context=EventContext(event_status="CONFIRMED", exposure_stale=False))
    stale = ReducerConfig(
        gate_config=load_gate_config(),
        event_context=EventContext(event_status="CONFIRMED", exposure_stale=True))

    assert reduce_company_impact(signals, fresh).publication_tier == "PRIMARY"

    blocked = reduce_company_impact(signals, stale)
    assert blocked.publication_tier != "PRIMARY"
    assert blocked.rejection_reason == "EXPOSURE_STALE"


# --- THE EMPTY-LEDGER TEST -------------------------------------------------

def _entity_and_discovery_signals(company_id):
    """Everything a company needs to be considered -- except an exposure."""
    from app.core.signals import make_signal
    from tests.phase1.conftest import FIXTURE_NOW

    common = dict(event_id=EVENT_ID, company_id=company_id,
                  analysis_version=ANALYSIS_VERSION, created_at=FIXTURE_NOW,
                  created_by="test:phase1")
    return [
        make_signal(stage="entity_resolver", kind="ENTITY_RESOLUTION",
                    payload={"ticker": "FIXCO.NS", "isin": "INFIXTURE001",
                             "resolution": "RESOLVED", "entity_status": "ACTIVE"},
                    **common),
        make_signal(stage="discovery", kind="DISCOVERY",
                    payload={"discovery_source": "MENTION", "directness": "DIRECT",
                             "graph_distance": 1}, **common),
    ]


def test_an_empty_ledger_yields_no_channels_however_confident_the_caller_is(
        ledger_session):
    """The structural statement of Phase 1: a channel cannot exist without
    an exposure row. The sensitivity map below is deliberately confident and
    deliberately ignored."""
    from app.ledger.channels import channel_signals_from_ledger
    from tests.phase1.conftest import FIXTURE_NOW

    company = make_company(ledger_session, ticker="FIXCO.NS", name="Fixture Co Ltd",
                           isin="INFIXTURE001")
    channels = channel_signals_from_ledger(
        ledger_session, company_id=company.id, event_id=EVENT_ID,
        analysis_version=ANALYSIS_VERSION, created_at=FIXTURE_NOW, as_of=AS_OF,
        sensitivity={"input:fixture_foo": ("NEGATIVE", "HIGH")})
    assert channels == ()


def test_the_pipeline_with_an_empty_ledger_abstains_and_publishes_nothing(
        ledger_session):
    from app.core.config_loader import load_gate_config
    from app.core.reducer import EventContext, ReducerConfig, reduce_company_impact
    from app.ledger.channels import channel_signals_from_ledger
    from app.output.compiler import compile_prose
    from tests.phase1.conftest import FIXTURE_NOW

    company = make_company(ledger_session, ticker="FIXCO.NS", name="Fixture Co Ltd",
                           isin="INFIXTURE001")
    assert ledger_session.execute(
        text("SELECT count(*) FROM company_exposure")).scalar() == 0

    signals = list(_entity_and_discovery_signals(company.id))
    signals += list(channel_signals_from_ledger(
        ledger_session, company_id=company.id, event_id=EVENT_ID,
        analysis_version=ANALYSIS_VERSION, created_at=FIXTURE_NOW, as_of=AS_OF,
        sensitivity={"input:fixture_foo": ("NEGATIVE", "HIGH")}))

    impact = reduce_company_impact(signals, ReducerConfig(
        gate_config=load_gate_config(),
        event_context=EventContext(event_status="CONFIRMED", exposure_stale=False)))

    assert impact.channels == ()
    assert impact.materiality_bucket == "NO_MATERIAL_IMPACT"
    assert impact.publication_tier == "REJECTED"
    assert impact.rejection_reason == "NO_MATERIAL_IMPACT"
    # And nothing is said about it.
    assert compile_prose(impact, claims=()) == []


def test_the_same_pipeline_produces_a_channel_once_the_ledger_has_a_row(
        ledger_session):
    """Proves the abstention above is caused by the EMPTY LEDGER and not by
    a broken helper that always returns nothing."""
    from app.core.reducer import reduce_company_impact
    from app.core.config_loader import load_gate_config
    from app.core.reducer import EventContext, ReducerConfig
    from app.ledger.channels import channel_signals_from_ledger
    from tests.phase1.conftest import FIXTURE_NOW

    company = make_company(ledger_session, ticker="FIXCO.NS", name="Fixture Co Ltd",
                           isin="INFIXTURE001")
    _exposure(ledger_session, company.id, as_of_date=AS_OF)

    channels = channel_signals_from_ledger(
        ledger_session, company_id=company.id, event_id=EVENT_ID,
        analysis_version=ANALYSIS_VERSION, created_at=FIXTURE_NOW, as_of=AS_OF,
        sensitivity={"input:fixture_foo": ("NEGATIVE", "HIGH")})

    assert len(channels) == 1
    assert channels[0].payload["direction"] == "NEGATIVE"
    assert channels[0].payload["channel_id"] == "input:fixture_foo"

    impact = reduce_company_impact(
        list(_entity_and_discovery_signals(company.id)) + list(channels),
        ReducerConfig(gate_config=load_gate_config(),
                      event_context=EventContext(event_status="CONFIRMED")))
    assert impact.materiality_bucket == "HIGH"
    assert impact.net_effect == "NEGATIVE"


def test_a_stale_exposure_row_yields_no_channel(ledger_session):
    """Stale exposures are excluded before they can back a claim."""
    from app.ledger.channels import channel_signals_from_ledger
    from app.ledger.staleness import flag_stale_exposures
    from tests.phase1.conftest import FIXTURE_NOW

    company = make_company(ledger_session, ticker="FIXCO.NS", name="Fixture Co Ltd",
                           isin="INFIXTURE001")
    _exposure(ledger_session, company.id, as_of_date=AS_OF - timedelta(days=401))
    flag_stale_exposures(ledger_session, as_of=AS_OF)

    assert channel_signals_from_ledger(
        ledger_session, company_id=company.id, event_id=EVENT_ID,
        analysis_version=ANALYSIS_VERSION, created_at=FIXTURE_NOW, as_of=AS_OF,
        sensitivity={"input:fixture_foo": ("NEGATIVE", "HIGH")}) == ()


def test_a_tag_with_no_sensitivity_yields_no_channel(ledger_session):
    """Phase 1 owns the exposure. It does not own the direction or the
    magnitude, and it never invents one (Phase 2 supplies them)."""
    from app.ledger.channels import channel_signals_from_ledger
    from tests.phase1.conftest import FIXTURE_NOW

    company = make_company(ledger_session, ticker="FIXCO.NS", name="Fixture Co Ltd",
                           isin="INFIXTURE001")
    _exposure(ledger_session, company.id, as_of_date=AS_OF)

    assert channel_signals_from_ledger(
        ledger_session, company_id=company.id, event_id=EVENT_ID,
        analysis_version=ANALYSIS_VERSION, created_at=FIXTURE_NOW, as_of=AS_OF,
        sensitivity={}) == ()


def test_the_nightly_script_runs_against_an_empty_ledger(ledger_engine, capsys):
    """`scripts/flag_stale_exposures.py` is runnable and idempotent, and on
    an empty ledger it reports zero rather than failing."""
    from scripts.flag_stale_exposures import run

    flagged = run(ledger_engine, as_of=AS_OF)
    assert flagged == 0
