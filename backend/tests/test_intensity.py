import pytest

from app.market import intensity
from app import config


def test_normalize_score_min_max_within_group():
    # value is the max of its peer group -> 100
    assert intensity.normalize_score(5.0, [1.0, 3.0, 5.0]) == pytest.approx(100.0)
    # value is the min -> 0
    assert intensity.normalize_score(1.0, [1.0, 3.0, 5.0]) == pytest.approx(0.0)
    # value is the midpoint -> 50
    assert intensity.normalize_score(3.0, [1.0, 3.0, 5.0]) == pytest.approx(50.0)


def test_normalize_score_uses_absolute_value():
    # A -5% excess move among peers [1, 3, 5] should normalize the same as +5.
    assert intensity.normalize_score(-5.0, [1.0, 3.0, 5.0]) == pytest.approx(100.0)


def test_normalize_score_degenerate_group_returns_100():
    # A single-member (or all-equal) peer group has no "less than" to
    # compare against -- the value IS the max there is.
    assert intensity.normalize_score(2.0, [2.0]) == pytest.approx(100.0)
    assert intensity.normalize_score(2.0, [2.0, 2.0, 2.0]) == pytest.approx(100.0)


def test_compute_intensity_matches_hand_computed_value():
    # excess=-4.8 is the max-magnitude peer -> excess_score=100
    # volume_multiple=3.0 is the max-magnitude peer -> volume_score=100
    # breadth_score=40 (already 0-100, used directly)
    result = intensity.compute_intensity(
        excess_move_pct=-4.8, excess_peer_group=[-4.8, -1.0, 0.5],
        volume_multiple=3.0, volume_peer_group=[3.0, 1.0],
        breadth_score=40,
    )
    expected_score = round(100 * 0.55 + 100 * 0.25 + 40 * 0.20)  # 55 + 25 + 8 = 88
    assert result["score"] == expected_score
    assert result["band"] == "High"
    assert len(result["components"]) == 3
    labels = {c["label"] for c in result["components"]}
    assert labels == {"excess", "volume", "breadth"}


def test_compute_intensity_never_returns_a_bare_number():
    result = intensity.compute_intensity(
        excess_move_pct=1.0, excess_peer_group=[1.0],
        volume_multiple=1.0, volume_peer_group=[1.0],
        breadth_score=10,
    )
    assert isinstance(result, dict)
    assert set(result.keys()) == {"score", "band", "components"}
    for component in result["components"]:
        assert set(component.keys()) == {"label", "raw", "weight", "contribution"}


def test_changing_a_config_weight_changes_the_score():
    kwargs = dict(
        excess_move_pct=-4.8, excess_peer_group=[-4.8, -1.0],
        volume_multiple=3.0, volume_peer_group=[3.0, 1.0],
        breadth_score=40,
    )
    default_result = intensity.compute_intensity(**kwargs)
    custom_result = intensity.compute_intensity(
        **kwargs, weights={"excess": 0.10, "volume": 0.10, "breadth": 0.80},
    )
    assert default_result["score"] != custom_result["score"]


def test_within_sector_normalization_gives_consistent_meaning_across_events():
    # Two "70-equivalent" events with wildly different absolute magnitudes
    # should both land on the same excess_score when normalized against
    # their OWN peer group (spec §4.2: normalize within sector/event, not
    # globally).
    small_move_event = intensity.normalize_score(0.7, [0.0, 0.7, 1.0])
    large_move_event = intensity.normalize_score(70.0, [0.0, 70.0, 100.0])
    assert small_move_event == pytest.approx(large_move_event)


def test_band_thresholds():
    high = intensity.compute_intensity(
        excess_move_pct=10, excess_peer_group=[10], volume_multiple=10,
        volume_peer_group=[10], breadth_score=100,
    )
    assert high["score"] >= config.INTENSITY_BAND_HIGH
    assert high["band"] == "High"

    low = intensity.compute_intensity(
        excess_move_pct=0.01, excess_peer_group=[0.01, 100], volume_multiple=0.01,
        volume_peer_group=[0.01, 100], breadth_score=0,
    )
    assert low["score"] < config.INTENSITY_BAND_MODERATE
    assert low["band"] == "Low"
