from apply_taxonomy_repairs import (
    TAXONOMY_REPAIRS,
    TaxonomyRepairIntegrityError,
    apply_taxonomy_repairs,
)
from app.companies.integrity import check_sub_sectors
from app.models import Company

import pytest


_DEFENSE_TICKERS = ("HAL.NS", "BEL.NS", "MAZDOCK.NS", "GRSE.NS", "BDL.NS", "DATAPATTNS.NS")


def _seed_target_companies(db_session):
    # ASIANPAINT.NS seeded exactly as production carries it -- other/
    # personal_care -- not dev's other/paints, so these tests exercise the
    # real shape of the bug this file guards against: a repair that only
    # touches one of the two fields would leave (or create) an incoherent
    # pairing here, not fix it.
    db_session.add_all([
        Company(ticker="ETERNAL.NS", name="Eternal Ltd.", sector="fmcg", sub_sector="personal_care", index_tier="NIFTY50"),
        Company(ticker="ASIANPAINT.NS", name="Asian Paints Ltd.", sector="other", sub_sector="personal_care", index_tier="NIFTY50"),
        Company(ticker="INDIGO.NS", name="InterGlobe Aviation Ltd.", sector="other", index_tier="NIFTY50"),
        # Seeded as production carries them -- sector="infra", sub_sector
        # NULL -- the exact misclassification that made candidate_companies
        # (session, ["defense"]) return 0 for a defence/aerospace story.
        Company(ticker="HAL.NS", name="Hindustan Aeronautics Limited", sector="infra", index_tier="NIFTY50"),
        Company(ticker="BEL.NS", name="Bharat Electronics Ltd.", sector="infra", index_tier="NIFTY50"),
        Company(ticker="MAZDOCK.NS", name="Mazagon Dock Shipbuilders Limited", sector="infra", index_tier="NIFTY50"),
        Company(ticker="GRSE.NS", name="Garden Reach Shipbuilders & Engineers Limited", sector="infra", index_tier="NIFTY100"),
        Company(ticker="BDL.NS", name="Bharat Dynamics Limited", sector="infra", index_tier="NIFTY100"),
        Company(ticker="DATAPATTNS.NS", name="Data Patterns (India) Limited", sector="infra", index_tier="NIFTY500"),
    ])
    db_session.commit()


def test_applies_every_repair_in_the_table(db_session):
    _seed_target_companies(db_session)

    results = apply_taxonomy_repairs(db_session, dry_run=False)

    assert all(r.status == "applied" for r in results)
    assert db_session.query(Company).filter_by(ticker="ETERNAL.NS").one().sub_sector == "retail"
    asianpaint = db_session.query(Company).filter_by(ticker="ASIANPAINT.NS").one()
    assert asianpaint.sector == "chemicals"
    assert asianpaint.sub_sector == "paints"
    assert db_session.query(Company).filter_by(ticker="INDIGO.NS").one().sector == "railways_transport"
    for ticker in _DEFENSE_TICKERS:
        assert db_session.query(Company).filter_by(ticker=ticker).one().sector == "defense"
    # The repaired state itself must be coherent -- no leftover violation.
    assert check_sub_sectors(db_session) == []


def test_dry_run_reports_without_writing(db_session):
    _seed_target_companies(db_session)

    results = apply_taxonomy_repairs(db_session, dry_run=True)

    assert all(r.status == "applied" for r in results)
    # Nothing was actually written.
    assert db_session.query(Company).filter_by(ticker="ETERNAL.NS").one().sub_sector == "personal_care"
    asianpaint = db_session.query(Company).filter_by(ticker="ASIANPAINT.NS").one()
    assert asianpaint.sector == "other"
    assert asianpaint.sub_sector == "personal_care"
    assert db_session.query(Company).filter_by(ticker="INDIGO.NS").one().sector == "other"
    for ticker in _DEFENSE_TICKERS:
        assert db_session.query(Company).filter_by(ticker=ticker).one().sector == "infra"


def test_idempotent_second_run_reports_already_correct_and_changes_nothing(db_session):
    _seed_target_companies(db_session)
    apply_taxonomy_repairs(db_session, dry_run=False)

    second_pass = apply_taxonomy_repairs(db_session, dry_run=False)

    assert all(r.status == "already_correct" for r in second_pass)
    assert db_session.query(Company).filter_by(ticker="ETERNAL.NS").one().sub_sector == "retail"
    asianpaint = db_session.query(Company).filter_by(ticker="ASIANPAINT.NS").one()
    assert asianpaint.sector == "chemicals"
    assert asianpaint.sub_sector == "paints"
    assert db_session.query(Company).filter_by(ticker="INDIGO.NS").one().sector == "railways_transport"
    for ticker in _DEFENSE_TICKERS:
        assert db_session.query(Company).filter_by(ticker=ticker).one().sector == "defense"


def test_safe_against_a_database_where_the_repair_was_already_applied_by_other_means(db_session):
    # Simulates a production row that already carries the correct, final
    # value through some other path (e.g. a fresh seed) -- must be reported
    # as already-correct, not re-applied or errored on.
    db_session.add(Company(
        ticker="ETERNAL.NS", name="Eternal Ltd.", sector="fmcg", sub_sector="retail", index_tier="NIFTY50",
    ))
    db_session.commit()

    results = apply_taxonomy_repairs(db_session, dry_run=False)

    eternal_result = next(r for r in results if r.ticker == "ETERNAL.NS")
    assert eternal_result.status == "already_correct"
    assert db_session.query(Company).filter_by(ticker="ETERNAL.NS").one().sub_sector == "retail"


def test_missing_ticker_is_reported_not_found_and_does_not_crash(db_session):
    # No Company rows seeded at all -- every repair target is missing.
    results = apply_taxonomy_repairs(db_session, dry_run=False)

    assert all(r.status == "not_found" for r in results)
    assert db_session.query(Company).count() == 0


def test_repair_table_only_contains_supported_fields():
    for ticker, field, expected in TAXONOMY_REPAIRS:
        assert field in ("sector", "sub_sector")
        assert isinstance(ticker, str) and ticker
        assert isinstance(expected, str) and expected


# --- derived pass (Job 2): fixes sector/sub_sector coherence violations not
# covered by the explicit TAXONOMY_REPAIRS table, whenever the sub_sector's
# owning sector is unambiguous. ---

def test_derivable_violation_gets_its_sector_fixed(db_session):
    # two_wheeler is owned by exactly one sector (auto) in
    # SUB_SECTOR_TAXONOMY, so a company sitting under sector="other" with
    # sub_sector="two_wheeler" is exactly the shape the stock-universe
    # merge produced at scale (126 rows): a real sub_sector surviving a
    # sector reset to "other". The derived pass should fix it without any
    # entry in TAXONOMY_REPAIRS naming this ticker.
    db_session.add(Company(
        ticker="TESTBIKE.NS", name="Test Bike Ltd.", sector="other", sub_sector="two_wheeler",
        index_tier="NIFTY50",
    ))
    db_session.commit()

    results = apply_taxonomy_repairs(db_session, dry_run=False)

    derived = next(r for r in results if r.ticker == "TESTBIKE.NS")
    assert derived.status == "applied"
    assert derived.field == "sector"
    assert derived.previous == "other"
    assert derived.expected == "auto"
    assert db_session.query(Company).filter_by(ticker="TESTBIKE.NS").one().sector == "auto"
    # sub_sector itself is never touched by the derived pass.
    assert db_session.query(Company).filter_by(ticker="TESTBIKE.NS").one().sub_sector == "two_wheeler"


def test_ambiguous_or_unknown_sub_sector_is_reported_not_guessed(db_session):
    # No branch of SUB_SECTOR_TAXONOMY contains this made-up value, so
    # _sector_owning (via check_sub_sectors's correct_sector) returns None
    # -- the derived pass must report it and leave the row untouched rather
    # than guess a sector.
    db_session.add(Company(
        ticker="TESTMYSTERY.NS", name="Test Mystery Ltd.", sector="other",
        sub_sector="not_a_real_sub_sector", index_tier="NIFTY50",
    ))
    db_session.commit()

    results = apply_taxonomy_repairs(db_session, dry_run=False)

    reported = next(r for r in results if r.ticker == "TESTMYSTERY.NS")
    assert reported.status == "ambiguous"
    company = db_session.query(Company).filter_by(ticker="TESTMYSTERY.NS").one()
    assert company.sector == "other"
    assert company.sub_sector == "not_a_real_sub_sector"


def test_derived_pass_dry_run_writes_nothing(db_session):
    db_session.add(Company(
        ticker="TESTBIKE.NS", name="Test Bike Ltd.", sector="other", sub_sector="two_wheeler",
        index_tier="NIFTY50",
    ))
    db_session.commit()

    results = apply_taxonomy_repairs(db_session, dry_run=True)

    derived = next(r for r in results if r.ticker == "TESTBIKE.NS")
    assert derived.status == "applied"
    assert derived.expected == "auto"
    # Nothing was actually written.
    assert db_session.query(Company).filter_by(ticker="TESTBIKE.NS").one().sector == "other"


def test_second_run_reports_nothing_left_to_do_for_derived_violations(db_session):
    db_session.add(Company(
        ticker="TESTBIKE.NS", name="Test Bike Ltd.", sector="other", sub_sector="two_wheeler",
        index_tier="NIFTY50",
    ))
    db_session.commit()

    apply_taxonomy_repairs(db_session, dry_run=False)
    second_pass = apply_taxonomy_repairs(db_session, dry_run=False)

    # The row is coherent now (auto/two_wheeler), so it no longer shows up
    # as a check_sub_sectors violation at all -- the derived pass has
    # nothing to report or fix on the second run.
    assert not any(r.ticker == "TESTBIKE.NS" for r in second_pass)
    assert db_session.query(Company).filter_by(ticker="TESTBIKE.NS").one().sector == "auto"


# --- C1: a "*_other" catch-all sub_sector must be reported, never repaired
# -- _sector_owning() still resolves it to exactly one sector (every sector
# has its own catch-all bucket), but that ownership carries no real signal
# about which sector the company actually belongs to. ---

def test_catchall_other_violation_is_reported_and_not_written(db_session):
    # metals_other resolves unambiguously to "metals" in SUB_SECTOR_TAXONOMY,
    # but a company carrying it could be almost anything -- confirmed live,
    # this exact shape promoted ADANIENT.NS (a ports/airports conglomerate)
    # to #1 in the metals fan-out. The derived pass must leave sector alone.
    db_session.add(Company(
        ticker="TESTCONGLOMERATE.NS", name="Test Conglomerate Ltd.", sector="other",
        sub_sector="metals_other", index_tier="NIFTY50",
    ))
    db_session.commit()

    results = apply_taxonomy_repairs(db_session, dry_run=False)

    reported = next(r for r in results if r.ticker == "TESTCONGLOMERATE.NS")
    assert reported.status == "catchall_skipped"
    assert reported.field == "sector"
    company = db_session.query(Company).filter_by(ticker="TESTCONGLOMERATE.NS").one()
    assert company.sector == "other"
    assert company.sub_sector == "metals_other"


def test_genuine_violation_alongside_a_catchall_one_is_still_repaired(db_session):
    # A real, specific sub_sector (two_wheeler) must still be derived and
    # fixed even in the same run as a *_other row that must not be --
    # the catch-all skip must not leak into the handling of other rows.
    db_session.add_all([
        Company(
            ticker="TESTBIKE.NS", name="Test Bike Ltd.", sector="other", sub_sector="two_wheeler",
            index_tier="NIFTY50",
        ),
        Company(
            ticker="TESTFMCGOTHER.NS", name="Test FMCG Other Ltd.", sector="other",
            sub_sector="fmcg_other", index_tier="NIFTY50",
        ),
    ])
    db_session.commit()

    results = apply_taxonomy_repairs(db_session, dry_run=False)

    bike_result = next(r for r in results if r.ticker == "TESTBIKE.NS")
    fmcg_other_result = next(r for r in results if r.ticker == "TESTFMCGOTHER.NS")
    assert bike_result.status == "applied"
    assert fmcg_other_result.status == "catchall_skipped"
    assert db_session.query(Company).filter_by(ticker="TESTBIKE.NS").one().sector == "auto"
    assert db_session.query(Company).filter_by(ticker="TESTFMCGOTHER.NS").one().sector == "other"


def test_catchall_skip_reported_separately_from_ambiguous_and_applied_counts(db_session):
    db_session.add_all([
        Company(
            ticker="TESTBIKE.NS", name="Test Bike Ltd.", sector="other", sub_sector="two_wheeler",
            index_tier="NIFTY50",
        ),
        Company(
            ticker="TESTFMCGOTHER.NS", name="Test FMCG Other Ltd.", sector="other",
            sub_sector="fmcg_other", index_tier="NIFTY50",
        ),
        Company(
            ticker="TESTMYSTERY.NS", name="Test Mystery Ltd.", sector="other",
            sub_sector="not_a_real_sub_sector", index_tier="NIFTY50",
        ),
    ])
    db_session.commit()

    results = apply_taxonomy_repairs(db_session, dry_run=False)

    statuses = {r.ticker: r.status for r in results}
    assert statuses["TESTBIKE.NS"] == "applied"
    assert statuses["TESTFMCGOTHER.NS"] == "catchall_skipped"
    assert statuses["TESTMYSTERY.NS"] == "ambiguous"
    # The two report buckets are distinct statuses, so a caller counting
    # each separately (as main() does) never conflates a catch-all skip
    # with a genuinely ambiguous/unknown sub_sector.
    assert sum(1 for r in results if r.status == "catchall_skipped") == 1
    assert sum(1 for r in results if r.status == "ambiguous") == 1
    assert sum(1 for r in results if r.status == "applied") == 1


def test_catchall_skip_dry_run_writes_nothing(db_session):
    db_session.add(Company(
        ticker="TESTFMCGOTHER.NS", name="Test FMCG Other Ltd.", sector="other",
        sub_sector="fmcg_other", index_tier="NIFTY50",
    ))
    db_session.commit()

    results = apply_taxonomy_repairs(db_session, dry_run=True)

    reported = next(r for r in results if r.ticker == "TESTFMCGOTHER.NS")
    assert reported.status == "catchall_skipped"
    assert db_session.query(Company).filter_by(ticker="TESTFMCGOTHER.NS").one().sector == "other"


# --- post-repair validation guard: apply_taxonomy_repairs must refuse to
# commit (or, under --dry-run, report success on) a run whose own repairs
# leave check_sub_sectors() with a violation that wasn't already there
# before this run started. This is the guard against the ASIANPAINT.NS
# class of bug: an explicit entry that's correct against one environment's
# starting data and silently wrong against another's. ---

def test_asianpaint_two_field_repair_lands_both_fields_with_no_leftover_violation(db_session):
    # The regression case itself: production's real starting state
    # (other/personal_care), repaired via the two ASIANPAINT.NS entries in
    # TAXONOMY_REPAIRS. Both fields must land, and the result must not trip
    # the post-repair validation guard.
    db_session.add(Company(
        ticker="ASIANPAINT.NS", name="Asian Paints Ltd.", sector="other",
        sub_sector="personal_care", index_tier="NIFTY50",
    ))
    db_session.commit()

    results = apply_taxonomy_repairs(db_session, dry_run=False)

    asianpaint_results = [r for r in results if r.ticker == "ASIANPAINT.NS"]
    assert {r.field for r in asianpaint_results} == {"sector", "sub_sector"}
    assert all(r.status == "applied" for r in asianpaint_results)
    company = db_session.query(Company).filter_by(ticker="ASIANPAINT.NS").one()
    assert company.sector == "chemicals"
    assert company.sub_sector == "paints"
    assert check_sub_sectors(db_session) == []


def test_post_repair_validation_catches_a_deliberately_inconsistent_repair_entry(db_session, monkeypatch):
    # Simulates exactly the class of bug the guard exists to catch: an
    # explicit TAXONOMY_REPAIRS entry that repairs `sector` but leaves the
    # row's sub_sector pointing somewhere incompatible, and that mismatch
    # isn't mechanically resolvable by the derived pass (sub_sector unknown
    # to the taxonomy), so it survives as a genuinely fresh violation. The
    # entry table is monkeypatched rather than edited in place -- this test
    # must exercise the guard itself, not the real (already-correct) table.
    monkeypatch.setattr(
        "apply_taxonomy_repairs.TAXONOMY_REPAIRS",
        (("TESTBADENTRY.NS", "sector", "chemicals"),),
    )
    db_session.add(Company(
        ticker="TESTBADENTRY.NS", name="Test Bad Entry Ltd.", sector="fmcg",
        sub_sector="not_a_real_sub_sector", index_tier="NIFTY50",
    ))
    db_session.commit()

    with pytest.raises(TaxonomyRepairIntegrityError, match="TESTBADENTRY.NS"):
        apply_taxonomy_repairs(db_session, dry_run=False)

    # The bad repair must never have been committed -- the row is exactly
    # as it started.
    db_session.rollback()
    company = db_session.query(Company).filter_by(ticker="TESTBADENTRY.NS").one()
    assert company.sector == "fmcg"
    assert company.sub_sector == "not_a_real_sub_sector"


# --- defense sector repairs: six Indian defence manufacturers production
# had classified sector="infra", making candidate_companies(session,
# ["defense"]) return 0 for a defence/aerospace story (SECTOR_DEFINITIONS
# describes "defense" as "defense and aerospace manufacturers", but
# sector='defense' held only global/non-tradeable companies). Their
# sub_sector was NULL, so check_sub_sectors() never flagged them -- the
# derived pass structurally cannot find a sector-only misclassification with
# a NULL sub_sector, so these must be explicit TAXONOMY_REPAIRS entries. ---

def test_defense_tickers_get_sector_and_the_unambiguous_sub_sector_repaired(db_session):
    db_session.add_all([
        Company(ticker="HAL.NS", name="Hindustan Aeronautics Limited", sector="infra", index_tier="NIFTY50"),
        Company(ticker="BEL.NS", name="Bharat Electronics Ltd.", sector="infra", index_tier="NIFTY50"),
        Company(ticker="MAZDOCK.NS", name="Mazagon Dock Shipbuilders Limited", sector="infra", index_tier="NIFTY50"),
        Company(ticker="GRSE.NS", name="Garden Reach Shipbuilders & Engineers Limited", sector="infra", index_tier="NIFTY100"),
        Company(ticker="BDL.NS", name="Bharat Dynamics Limited", sector="infra", index_tier="NIFTY100"),
        Company(ticker="DATAPATTNS.NS", name="Data Patterns (India) Limited", sector="infra", index_tier="NIFTY500"),
    ])
    db_session.commit()

    results = apply_taxonomy_repairs(db_session, dry_run=False)

    # Only these six tickers were seeded -- every OTHER entry in
    # TAXONOMY_REPAIRS (ETERNAL.NS, ASIANPAINT.NS, INDIGO.NS) legitimately
    # reports "not_found" here since their Company rows don't exist in this
    # test's session. Scope the "applied" assertion to the tickers this
    # test actually seeded.
    defense_results = [r for r in results if r.ticker in _DEFENSE_TICKERS]
    assert len(defense_results) == 12  # 6 tickers x (sector + sub_sector) entries each
    assert all(r.status == "applied" for r in defense_results)

    expected_sub_sector = {
        "HAL.NS": "defense_platforms",
        "BEL.NS": "defense_electronics",
        "MAZDOCK.NS": "shipyard",
        "GRSE.NS": "shipyard",
        "BDL.NS": "defense_platforms",
        "DATAPATTNS.NS": "defense_electronics",
    }
    for ticker, sub_sector in expected_sub_sector.items():
        company = db_session.query(Company).filter_by(ticker=ticker).one()
        assert company.sector == "defense"
        assert company.sub_sector == sub_sector

    # The repaired state must be coherent -- every sub_sector set above
    # actually lives in defense's own SUB_SECTOR_TAXONOMY branch.
    assert check_sub_sectors(db_session) == []


def test_defense_repairs_candidate_companies_now_finds_them(db_session):
    # The actual production symptom this fix removes: a defense/aerospace
    # story could name zero companies because candidate_companies(session,
    # ["defense"]) returned nothing (sector='defense' held only global/
    # non-tradeable rows). After the repair, these six are real, tradeable
    # NSE-listed candidates under sector="defense".
    from app.companies.candidates import candidate_companies

    db_session.add_all([
        Company(ticker="HAL.NS", name="Hindustan Aeronautics Limited", sector="infra", index_tier="NIFTY50"),
        Company(ticker="BEL.NS", name="Bharat Electronics Ltd.", sector="infra", index_tier="NIFTY50"),
    ])
    db_session.commit()

    assert candidate_companies(db_session, ["defense"]) == []

    apply_taxonomy_repairs(db_session, dry_run=False)

    tickers = {c.ticker for c in candidate_companies(db_session, ["defense"])}
    assert {"HAL.NS", "BEL.NS"} <= tickers


def test_post_repair_validation_guard_also_fires_under_dry_run(db_session, monkeypatch):
    # The guard must work identically under --dry-run: it reports what the
    # post-repair state WOULD be, without requiring a write, and still
    # raises rather than letting --dry-run report a clean, empty diff.
    monkeypatch.setattr(
        "apply_taxonomy_repairs.TAXONOMY_REPAIRS",
        (("TESTBADENTRY.NS", "sector", "chemicals"),),
    )
    db_session.add(Company(
        ticker="TESTBADENTRY.NS", name="Test Bad Entry Ltd.", sector="fmcg",
        sub_sector="not_a_real_sub_sector", index_tier="NIFTY50",
    ))
    db_session.commit()

    with pytest.raises(TaxonomyRepairIntegrityError, match="TESTBADENTRY.NS"):
        apply_taxonomy_repairs(db_session, dry_run=True)

    db_session.rollback()
    company = db_session.query(Company).filter_by(ticker="TESTBADENTRY.NS").one()
    assert company.sector == "fmcg"
