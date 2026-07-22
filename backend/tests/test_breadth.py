from app.market import breadth


def test_all_moved_meaningfully_scores_100():
    assert breadth.compute_breadth_score([5.0, -6.0, 3.0], meaningful_threshold_pct=1.0) == 100


def test_none_moved_meaningfully_scores_0():
    assert breadth.compute_breadth_score([0.1, -0.2, 0.05], meaningful_threshold_pct=1.0) == 0


def test_half_moved_meaningfully_scores_50():
    assert breadth.compute_breadth_score([5.0, 0.1, -6.0, 0.05], meaningful_threshold_pct=1.0) == 50


def test_empty_list_scores_0():
    assert breadth.compute_breadth_score([], meaningful_threshold_pct=1.0) == 0


def test_uses_config_default_threshold_when_not_passed():
    # One-company earnings beat (a single meaningful move) should score
    # LOW breadth, a sector-wide event (many meaningful moves) HIGH --
    # spec §4.4.
    low = breadth.compute_breadth_score([5.0, 0.1, 0.1, 0.1, 0.1])
    high = breadth.compute_breadth_score([5.0, 4.0, 3.0, 6.0, 5.0])
    assert low < high
