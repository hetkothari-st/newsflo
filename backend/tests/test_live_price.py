from datetime import datetime, timezone

from app.prices.live_price import compute_change_pct, get_previous_close


def test_get_previous_close_returns_last_close_strictly_before_today(monkeypatch):
    monkeypatch.setattr(
        "app.prices.live_price._today",
        lambda: "2026-07-15",
    )
    points = [
        {"date": "2026-07-13", "close": 100.0},
        {"date": "2026-07-14", "close": 105.0},
        {"date": "2026-07-15", "close": 110.0},  # today -- not "previous"
    ]

    assert get_previous_close(points) == 105.0


def test_get_previous_close_falls_back_to_last_point_if_none_before_today(monkeypatch):
    monkeypatch.setattr(
        "app.prices.live_price._today",
        lambda: "2026-07-10",
    )
    points = [{"date": "2026-07-15", "close": 110.0}]  # all "today or later" relative to fake _today

    assert get_previous_close(points) == 110.0


def test_get_previous_close_returns_none_for_empty_points():
    assert get_previous_close([]) is None


def test_compute_change_pct_positive_move():
    assert compute_change_pct(ltp=110.0, previous_close=100.0) == 10.0


def test_compute_change_pct_negative_move():
    assert compute_change_pct(ltp=90.0, previous_close=100.0) == -10.0


def test_compute_change_pct_returns_none_without_a_previous_close():
    assert compute_change_pct(ltp=110.0, previous_close=None) is None


def test_compute_change_pct_returns_none_for_zero_previous_close():
    assert compute_change_pct(ltp=110.0, previous_close=0.0) is None
