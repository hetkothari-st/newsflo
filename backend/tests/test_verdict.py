from app.market import verdict


def test_unconfirmed_branch_wins_regardless_of_excess():
    assert verdict.compute_verdict(is_unconfirmed=True, excess_move_pct=10.0) == "UNCONFIRMED"
    assert verdict.compute_verdict(is_unconfirmed=True, excess_move_pct=None) == "UNCONFIRMED"


def test_company_specific_branch():
    assert verdict.compute_verdict(is_unconfirmed=False, excess_move_pct=4.8, threshold_pct=2.0) == "COMPANY_SPECIFIC"
    assert verdict.compute_verdict(is_unconfirmed=False, excess_move_pct=-4.8, threshold_pct=2.0) == "COMPANY_SPECIFIC"


def test_sector_wide_branch():
    assert verdict.compute_verdict(is_unconfirmed=False, excess_move_pct=0.5, threshold_pct=2.0) == "SECTOR_WIDE"


def test_missing_excess_move_treated_as_sector_wide_not_a_crash():
    # No measurement (measurement_status='no_data') must never crash the
    # verdict -- absent excess is treated as not-yet-confirmed-company-
    # specific, i.e. SECTOR_WIDE (the "usually skippable" default).
    assert verdict.compute_verdict(is_unconfirmed=False, excess_move_pct=None, threshold_pct=2.0) == "SECTOR_WIDE"


def test_uses_config_default_threshold_when_not_passed():
    from app import config
    result = verdict.compute_verdict(is_unconfirmed=False, excess_move_pct=config.VERDICT_EXCESS_THRESHOLD_PCT)
    assert result == "COMPANY_SPECIFIC"
