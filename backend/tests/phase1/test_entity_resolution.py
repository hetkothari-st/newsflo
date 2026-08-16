"""TASK 1.2 -- company master and entity resolution (spec §4.4).

The phase file's TESTS section, verbatim:
  - ticker collision across exchanges => ENTITY_AMBIGUOUS
  - claim on merged-away entity after effective date => ENTITY_WRONG
  - unlisted subsidiary exposure without consolidated segment evidence does
    not attach to parent
  - holdco route caps tier at SECONDARY_RIPPLE
"""
from datetime import date

import pytest

from tests.phase1.conftest import make_company

CLAIM_DATE = date(2226, 2, 22)


def _listing(session, company, *, exchange: str, symbol: str):
    from app.models import Listing

    session.add(Listing(company_id=company.id, exchange=exchange, symbol=symbol,
                        source="fixture", as_of=CLAIM_DATE))
    session.flush()


def _entity_meta(session, company, **kwargs):
    from app.models import CompanyEntityMeta

    defaults = dict(company_id=company.id, status="ACTIVE",
                    source_url="https://fixture.invalid/entity-meta",
                    as_of_date=CLAIM_DATE)
    defaults.update(kwargs)
    session.add(CompanyEntityMeta(**defaults))
    session.flush()


# --- resolution ------------------------------------------------------------

def test_isin_is_the_primary_key_and_resolves_outright(ledger_session):
    from app.entities.resolver import RESOLVED, resolve_entity

    company = make_company(ledger_session, ticker="FIXA.NS", name="Fixture Alpha Ltd",
                           isin="INFIXTUREA01")
    result = resolve_entity(ledger_session, isin="INFIXTUREA01", as_of=CLAIM_DATE)
    assert result.status == RESOLVED
    assert result.company_id == company.id
    assert result.method == "isin"


def test_an_unknown_isin_is_not_found_rather_than_guessed(ledger_session):
    from app.entities.resolver import ENTITY_NOT_FOUND, resolve_entity

    make_company(ledger_session, ticker="FIXA.NS", name="Fixture Alpha Ltd",
                 isin="INFIXTUREA01")
    result = resolve_entity(ledger_session, isin="INFIXTUREZ99", name="Fixture Alpha Ltd",
                            as_of=CLAIM_DATE)
    assert result.status == ENTITY_NOT_FOUND


def test_ticker_collision_across_exchanges_is_ambiguous(ledger_session):
    """The same bare symbol listed on two exchanges by two different
    companies. §4.4: fail closed, never pick one."""
    from app.entities.resolver import ENTITY_AMBIGUOUS, resolve_entity

    nse = make_company(ledger_session, ticker="FIXCO.NS", name="Fixture Co Ltd",
                       isin="INFIXTURE001")
    bse = make_company(ledger_session, ticker="FIXCO.BO", name="Fixture Company Ltd",
                       isin="INFIXTURE002")
    _listing(ledger_session, nse, exchange="NSE", symbol="FIXCO")
    _listing(ledger_session, bse, exchange="BSE", symbol="FIXCO")

    result = resolve_entity(ledger_session, ticker="FIXCO", as_of=CLAIM_DATE)
    assert result.status == ENTITY_AMBIGUOUS
    assert result.company_id is None


def test_a_name_shared_across_markets_is_ambiguous(ledger_session):
    """'Castrol' India vs plc (§4.4). Two rows, one name, no tiebreak."""
    from app.entities.resolver import ENTITY_AMBIGUOUS, resolve_entity

    make_company(ledger_session, ticker="FIXN.NS", name="Fixture Naming Ltd",
                 isin="INFIXTURE003")
    make_company(ledger_session, ticker="FIXN.GLOBAL", name="Fixture Naming Ltd",
                 isin=None, market="GLOBAL")

    result = resolve_entity(ledger_session, name="Fixture Naming Ltd", as_of=CLAIM_DATE)
    assert result.status == ENTITY_AMBIGUOUS


def test_the_ledger_resolver_never_fuzzy_matches(ledger_session):
    """A near-miss name is NOT a filing's company. Nothing in the ledger may
    be attached on a similarity score."""
    from app.entities.resolver import ENTITY_NOT_FOUND, resolve_entity

    make_company(ledger_session, ticker="FIXA.NS", name="Fixture Alpha Ltd",
                 isin="INFIXTUREA01")
    result = resolve_entity(ledger_session, name="Fixture Alpa Limited", as_of=CLAIM_DATE)
    assert result.status == ENTITY_NOT_FOUND


def test_claim_on_a_merged_away_entity_after_the_effective_date_is_wrong(ledger_session):
    from app.entities.resolver import ENTITY_WRONG, RESOLVED, resolve_entity
    from app.models import EntityCorporateAction

    company = make_company(ledger_session, ticker="FIXM.NS", name="Fixture Merged Ltd",
                           isin="INFIXTUREM01")
    ledger_session.add(EntityCorporateAction(
        action_id="fixture-action-1", company_id=company.id, action_type="MERGER",
        effective_date=date(2226, 1, 1), successor_isin="INFIXTURES01",
        source_url="https://fixture.invalid/merger", as_of_date=date(2226, 1, 1)))
    ledger_session.flush()

    after = resolve_entity(ledger_session, isin="INFIXTUREM01", as_of=CLAIM_DATE)
    assert after.status == ENTITY_WRONG
    assert "MERGER" in after.detail

    before = resolve_entity(ledger_session, isin="INFIXTUREM01", as_of=date(2225, 12, 1))
    assert before.status == RESOLVED


def test_a_claim_outside_the_entity_validity_window_is_wrong(ledger_session):
    from app.entities.resolver import ENTITY_WRONG, resolve_entity

    company = make_company(ledger_session, ticker="FIXV.NS", name="Fixture Window Ltd",
                           isin="INFIXTUREV01")
    _entity_meta(ledger_session, company, valid_from=date(2226, 3, 1))
    result = resolve_entity(ledger_session, isin="INFIXTUREV01", as_of=CLAIM_DATE)
    assert result.status == ENTITY_WRONG


def test_as_of_is_required_so_validity_can_never_be_skipped(ledger_session):
    from app.entities.resolver import resolve_entity

    make_company(ledger_session, ticker="FIXA.NS", name="Fixture Alpha Ltd",
                 isin="INFIXTUREA01")
    with pytest.raises(TypeError):
        resolve_entity(ledger_session, isin="INFIXTUREA01")


def test_a_former_name_resolves_only_inside_its_window(ledger_session):
    from app.entities.resolver import ENTITY_NOT_FOUND, RESOLVED, resolve_entity
    from app.models import CompanyAliasWindow

    company = make_company(ledger_session, ticker="FIXR.NS", name="Fixture Renamed Ltd",
                           isin="INFIXTURER01")
    ledger_session.add(CompanyAliasWindow(
        alias_id="fixture-alias-1", company_id=company.id,
        alias="Fixture Oldname Ltd", kind="FORMER",
        normalized="fixture oldname", valid_from=date(2220, 1, 1),
        valid_to=date(2225, 1, 1), source_url="https://fixture.invalid/rename"))
    ledger_session.flush()

    inside = resolve_entity(ledger_session, name="Fixture Oldname Ltd",
                            as_of=date(2224, 6, 1))
    assert inside.status == RESOLVED
    assert inside.company_id == company.id

    outside = resolve_entity(ledger_session, name="Fixture Oldname Ltd",
                             as_of=CLAIM_DATE)
    assert outside.status == ENTITY_NOT_FOUND


# --- attachment ------------------------------------------------------------

def _origin(**overrides):
    from app.entities.resolver import ExposureOrigin

    defaults = dict(entity_name="Fixture Subsidiary Pvt Ltd", isin="INFIXTURESUB1",
                    listed=False, parent_isin="INFIXTUREP01",
                    ownership_fraction=None, segment_name="Fixture Segment")
    defaults.update(overrides)
    return ExposureOrigin(**defaults)


def _listco(**overrides):
    from app.entities.resolver import ListCo

    defaults = dict(company_id=101, isin="INFIXTUREP01", listed=True)
    defaults.update(overrides)
    return ListCo(**defaults)


def _segment(**overrides):
    from app.entities.resolver import SegmentEvidence

    defaults = dict(segment_name="Fixture Segment", fiscal_year=2222,
                    source_url="https://fixture.invalid/ar#segment-note")
    defaults.update(overrides)
    return SegmentEvidence(**defaults)


def test_unlisted_subsidiary_without_consolidated_segment_evidence_does_not_attach():
    from app.entities.resolver import attach_exposure_to_listco

    result = attach_exposure_to_listco(_origin(ownership_fraction=0.1111), _listco(),
                                       consolidated_segments=())
    assert result.attached is False
    assert result.reason == "NO_CONSOLIDATED_SEGMENT_EVIDENCE"


def test_unlisted_subsidiary_with_segment_evidence_attaches_with_ownership_applied():
    from app.entities.resolver import attach_exposure_to_listco

    result = attach_exposure_to_listco(
        _origin(ownership_fraction=0.1111), _listco(),
        consolidated_segments=(_segment(),))
    assert result.attached is True
    assert result.company_id == 101
    assert result.ownership_fraction == 0.1111
    assert result.materiality_base == "CONSOLIDATED_EBITDA"
    assert result.tier_cap is None


def test_an_unknown_ownership_fraction_blocks_attachment_rather_than_defaulting():
    """Missing is missing -- never 1.0."""
    from app.entities.resolver import attach_exposure_to_listco

    result = attach_exposure_to_listco(_origin(ownership_fraction=None), _listco(),
                                       consolidated_segments=(_segment(),))
    assert result.attached is False
    assert result.reason == "OWNERSHIP_FRACTION_UNKNOWN"


def test_an_entity_outside_the_ownership_chain_never_attaches():
    from app.entities.resolver import attach_exposure_to_listco

    result = attach_exposure_to_listco(
        _origin(parent_isin="INFIXTUREOTHER", ownership_fraction=0.1111),
        _listco(), consolidated_segments=(_segment(),))
    assert result.attached is False
    assert result.reason == "NOT_IN_OWNERSHIP_CHAIN"


def test_holdco_route_caps_tier_at_secondary_ripple():
    """An operating exposure that sits in a LISTED subsidiary transmits to
    the holdco capped at SECONDARY_RIPPLE with a HOLDCO_DISCOUNT modifier."""
    from app.entities.resolver import attach_exposure_to_listco

    result = attach_exposure_to_listco(
        _origin(listed=True, ownership_fraction=0.1111), _listco(),
        consolidated_segments=(_segment(),))
    assert result.attached is True
    assert result.tier_cap == "SECONDARY_RIPPLE"
    assert "HOLDCO_DISCOUNT" in result.modifiers


def test_the_holdco_discount_modifier_carries_no_invented_coefficient():
    """Phase 1 records WHICH modifier applies. The coefficient is Phase 4
    policy data that does not exist -- and must not be invented here."""
    from app.entities.resolver import attach_exposure_to_listco

    result = attach_exposure_to_listco(
        _origin(listed=True, ownership_fraction=0.1111), _listco(),
        consolidated_segments=(_segment(),))
    assert result.modifiers == ("HOLDCO_DISCOUNT",)
    assert all(isinstance(m, str) for m in result.modifiers)


def test_a_companys_own_exposure_attaches_to_itself_uncapped():
    from app.entities.resolver import attach_exposure_to_listco

    result = attach_exposure_to_listco(
        _origin(isin="INFIXTUREP01", listed=True, parent_isin=None,
                ownership_fraction=1.0),
        _listco(), consolidated_segments=())
    assert result.attached is True
    assert result.tier_cap is None
    assert result.modifiers == ()
