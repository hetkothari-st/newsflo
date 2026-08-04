from apply_taxonomy_repairs import TAXONOMY_REPAIRS, apply_taxonomy_repairs
from app.models import Company


def _seed_target_companies(db_session):
    db_session.add_all([
        Company(ticker="ETERNAL.NS", name="Eternal Ltd.", sector="fmcg", sub_sector="personal_care", index_tier="NIFTY50"),
        Company(ticker="ASIANPAINT.NS", name="Asian Paints Ltd.", sector="fmcg", sub_sector="paints", index_tier="NIFTY50"),
        Company(ticker="INDIGO.NS", name="InterGlobe Aviation Ltd.", sector="other", index_tier="NIFTY50"),
    ])
    db_session.commit()


def test_applies_every_repair_in_the_table(db_session):
    _seed_target_companies(db_session)

    results = apply_taxonomy_repairs(db_session, dry_run=False)

    assert all(r.status == "applied" for r in results)
    assert db_session.query(Company).filter_by(ticker="ETERNAL.NS").one().sub_sector == "retail"
    assert db_session.query(Company).filter_by(ticker="ASIANPAINT.NS").one().sector == "chemicals"
    assert db_session.query(Company).filter_by(ticker="INDIGO.NS").one().sector == "railways_transport"


def test_dry_run_reports_without_writing(db_session):
    _seed_target_companies(db_session)

    results = apply_taxonomy_repairs(db_session, dry_run=True)

    assert all(r.status == "applied" for r in results)
    # Nothing was actually written.
    assert db_session.query(Company).filter_by(ticker="ETERNAL.NS").one().sub_sector == "personal_care"
    assert db_session.query(Company).filter_by(ticker="ASIANPAINT.NS").one().sector == "fmcg"
    assert db_session.query(Company).filter_by(ticker="INDIGO.NS").one().sector == "other"


def test_idempotent_second_run_reports_already_correct_and_changes_nothing(db_session):
    _seed_target_companies(db_session)
    apply_taxonomy_repairs(db_session, dry_run=False)

    second_pass = apply_taxonomy_repairs(db_session, dry_run=False)

    assert all(r.status == "already_correct" for r in second_pass)
    assert db_session.query(Company).filter_by(ticker="ETERNAL.NS").one().sub_sector == "retail"
    assert db_session.query(Company).filter_by(ticker="ASIANPAINT.NS").one().sector == "chemicals"
    assert db_session.query(Company).filter_by(ticker="INDIGO.NS").one().sector == "railways_transport"


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
