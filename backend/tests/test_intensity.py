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
    # All five live-feed signals present (no fundamental): weights
    # renormalize over 0.28+0.12+0.15+0.25+0.10 = 0.90 (spec v2 §4.2).
    # Every signal is the max of its peer group -> each sub-score 100,
    # except delivery (already 0-100 by definition) at 38.
    result = intensity.compute_intensity(
        excess_move_pct=-4.8, excess_peer_group=[-4.8, -1.0, 0.5],
        volume_multiple=3.0, volume_peer_group=[3.0, 1.0],
        delivery_pct=38.0,
        materiality=0.05, materiality_peer_group=[0.05, 0.01],
        vol_normalized=2.5, vol_norm_peer_group=[2.5, 1.0],
    )
    total_w = 0.28 + 0.12 + 0.15 + 0.25 + 0.10
    expected = round(
        100 * 0.28 / total_w + 100 * 0.12 / total_w + 38 * 0.15 / total_w
        + 100 * 0.25 / total_w + 100 * 0.10 / total_w
    )
    assert result["score"] == expected
    assert result["band"] == "High"
    labels = {c["label"] for c in result["components"]}
    assert labels == {"excess", "volume", "delivery", "materiality", "vol_norm"}


def test_compute_intensity_renormalizes_missing_signals():
    # Only excess + volume present (an old MarketMove row): their weights
    # renormalize to sum to 1, never counting a missing signal as zero.
    result = intensity.compute_intensity(
        excess_move_pct=-4.8, excess_peer_group=[-4.8, -1.0],
        volume_multiple=3.0, volume_peer_group=[3.0, 1.0],
    )
    assert {c["label"] for c in result["components"]} == {"excess", "volume"}
    assert sum(c["weight"] for c in result["components"]) == pytest.approx(1.0, abs=0.01)
    # Both signals are the max of their group -> composite must be 100.
    assert result["score"] == 100


def test_compute_intensity_never_returns_a_bare_number():
    result = intensity.compute_intensity(
        excess_move_pct=1.0, excess_peer_group=[1.0],
        volume_multiple=1.0, volume_peer_group=[1.0],
    )
    assert isinstance(result, dict)
    assert set(result.keys()) == {"score", "band", "components"}
    for component in result["components"]:
        assert set(component.keys()) == {"label", "raw", "score", "weight", "contribution"}


def test_changing_a_config_weight_changes_the_score():
    kwargs = dict(
        excess_move_pct=-4.8, excess_peer_group=[-4.8, -1.0],
        volume_multiple=3.0, volume_peer_group=[3.0, 1.0],
        delivery_pct=38.0,
    )
    default_result = intensity.compute_intensity(**kwargs)
    custom_result = intensity.compute_intensity(
        **kwargs,
        weights={**config.INTENSITY_WEIGHTS, "excess": 0.05, "delivery": 0.75},
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
        volume_peer_group=[10],
    )
    assert high["score"] >= config.INTENSITY_BAND_HIGH
    assert high["band"] == "High"

    low = intensity.compute_intensity(
        excess_move_pct=0.01, excess_peer_group=[0.01, 100], volume_multiple=0.01,
        volume_peer_group=[0.01, 100],
    )
    assert low["score"] < config.INTENSITY_BAND_MODERATE
    assert low["band"] == "Low"
