"""Task 11 (corrective plan 2026-08-13): a company proposed by TWO
mechanisms in the same graph must never silently lose one of them to a
best-wins discard. Same-direction proposals merge into one record with
both mechanisms preserved; genuinely conflicting proposals (one positive,
one negative) become an honest `mixed` verdict instead of a coin flip."""
from app.analysis.impact_graph.engine import _merge_company, analyze_article_v3
from app.analysis.impact_graph.schemas import GraphCompany

from tests.test_impact_graph import FACTS, FakeRouter, _company, _company_entry, _edge


def _co(**overrides):
    payload = dict(
        ticker="A.NS", name="A", direction="bullish", impact_strength=0.5,
        confidence=0.7, materiality=0.5, causal_distance=1, mechanism="mech",
        rationale="r", net_direction="bullish", economic_effect="positive",
    )
    payload.update(overrides)
    return GraphCompany(**payload)


# --- _merge_company unit tests ---------------------------------------------

def test_merge_with_no_incumbent_returns_newcomer_unchanged():
    newcomer = _co(mechanism="only one")
    merged = _merge_company(None, newcomer)
    assert merged is newcomer


def test_same_direction_merge_keeps_higher_impact_and_appends_mechanism():
    held = _co(impact_strength=0.5, confidence=0.7, materiality=0.5,
               mechanism="mech1", economic_effect="positive",
               positive_channels=["chan1"])
    newcomer = _co(impact_strength=0.8, confidence=0.6, materiality=0.6,
                   mechanism="mech2", economic_effect="positive",
                   positive_channels=["chan2"])
    merged = _merge_company(held, newcomer)

    # Higher-impact record (newcomer) is the base.
    assert merged.impact_strength == 0.8
    assert merged.mechanism == "mech2"
    assert merged.economic_effect == "positive"
    # The loser's mechanism is preserved, never dropped.
    assert merged.secondary_mechanisms == ["mech1"]
    assert set(merged.positive_channels) == {"chan1", "chan2"}


def test_same_direction_merge_symmetric_when_incumbent_has_higher_impact():
    held = _co(impact_strength=0.9, mechanism="strong mech", economic_effect="positive")
    newcomer = _co(impact_strength=0.3, mechanism="weak mech", economic_effect="positive")
    merged = _merge_company(held, newcomer)
    assert merged.impact_strength == 0.9
    assert merged.mechanism == "strong mech"
    assert merged.secondary_mechanisms == ["weak mech"]


def test_conflicting_effects_merge_to_mixed_with_both_channels_preserved():
    held = _co(impact_strength=0.5, confidence=0.9, materiality=0.4,
               mechanism="tailwind mechanism", economic_effect="positive",
               positive_channels=["rural demand"])
    newcomer = _co(impact_strength=0.7, confidence=0.6, materiality=0.8,
                   mechanism="headwind mechanism", economic_effect="negative",
                   negative_channels=["input costs"])
    merged = _merge_company(held, newcomer)

    assert merged.economic_effect == "mixed"
    assert merged.net_direction == "mixed"
    assert merged.direction == "neutral"
    # confidence = min (the conflict IS the uncertainty)
    assert merged.confidence == 0.6
    # materiality = max (bigger channel governs display-worthiness)
    assert merged.materiality == 0.8
    # Primary mechanism is the higher-impact record's (newcomer, 0.7 > 0.5).
    assert merged.mechanism == "headwind mechanism"
    assert merged.secondary_mechanisms == ["tailwind mechanism"]
    # Both channel lists must be non-empty.
    assert merged.positive_channels == ["rural demand"]
    assert merged.negative_channels == ["input costs"]


def test_conflicting_effects_fill_empty_channel_side_from_mechanism():
    """Neither side stated an explicit channel bullet -- the mechanism
    sentence itself is the honest fallback so the mixed verdict never
    displays one side empty."""
    held = _co(impact_strength=0.5, mechanism="tailwind mechanism",
               economic_effect="positive", positive_channels=[])
    newcomer = _co(impact_strength=0.3, mechanism="headwind mechanism",
                   economic_effect="negative", negative_channels=[])
    merged = _merge_company(held, newcomer)
    assert merged.economic_effect == "mixed"
    assert merged.positive_channels == ["tailwind mechanism"]
    assert merged.negative_channels == ["headwind mechanism"]


def test_mixed_incumbent_absorbs_directional_newcomer_and_stays_mixed():
    held = _co(impact_strength=0.6, mechanism="already mixed story",
               economic_effect="mixed", net_direction="mixed")
    newcomer = _co(impact_strength=0.4, mechanism="new positive channel",
                   economic_effect="positive")
    merged = _merge_company(held, newcomer)
    assert merged.economic_effect == "mixed"
    assert merged.net_direction == "mixed"
    assert merged.mechanism == "already mixed story"
    assert merged.secondary_mechanisms == ["new positive channel"]


def test_uncertain_incumbent_absorbing_directional_newcomer_becomes_mixed():
    held = _co(impact_strength=0.3, mechanism="unclear story", economic_effect="uncertain")
    newcomer = _co(impact_strength=0.6, mechanism="clear negative", economic_effect="negative")
    merged = _merge_company(held, newcomer)
    assert merged.economic_effect == "mixed"
    assert merged.net_direction == "mixed"


def test_chained_three_way_merge_preserves_all_mechanisms():
    """Review finding: a 3-way collision (three proposals for the SAME
    ticker, e.g. three entries in one batched narrow-path call) must not
    lose the FIRST loser's mechanism when a THIRD proposal later wins
    overall. merge(A,B) demotes B to secondary; merge(that, C) with C
    winning must fold BOTH the running secondary_mechanisms list AND the
    displaced primary's own mechanism -- not just C's immediate opponent's
    bare mechanism string, or B silently vanishes on the second merge."""
    a = _co(mechanism="mech_A", impact_strength=0.5, economic_effect="positive")
    b = _co(mechanism="mech_B", impact_strength=0.3, economic_effect="positive")
    c = _co(mechanism="mech_C", impact_strength=0.9, economic_effect="positive")

    ab = _merge_company(None, a)
    ab = _merge_company(ab, b)
    assert ab.mechanism == "mech_A"
    assert ab.secondary_mechanisms == ["mech_B"]

    abc = _merge_company(ab, c)
    assert abc.mechanism == "mech_C"  # highest overall impact wins
    # Neither earlier loser is dropped by the second merge.
    assert set(abc.secondary_mechanisms) == {"mech_A", "mech_B"}
    assert len(abc.secondary_mechanisms) == 2  # no duplicates either


def test_chained_three_way_merge_through_conflicting_effects():
    """The same fold-through must hold when the chain crosses a
    conflicting (mixed) merge partway through."""
    a = _co(mechanism="mech_A", impact_strength=0.4, economic_effect="positive")
    b = _co(mechanism="mech_B", impact_strength=0.6, economic_effect="negative")
    c = _co(mechanism="mech_C", impact_strength=0.5, economic_effect="positive")

    ab = _merge_company(None, a)
    ab = _merge_company(ab, b)  # conflicting -> mixed, b wins as primary (0.6 > 0.4)
    assert ab.economic_effect == "mixed"
    assert ab.mechanism == "mech_B"
    assert ab.secondary_mechanisms == ["mech_A"]

    abc = _merge_company(ab, c)  # b (0.6) still beats c (0.5)
    assert abc.mechanism == "mech_B"
    assert set(abc.secondary_mechanisms) == {"mech_A", "mech_C"}


# --- end-to-end: same ticker proposed under two nodes (narrow path) -------

def test_narrow_path_conflicting_mechanisms_merge_end_to_end(db_session):
    """The narrow tier's company mapping is ONE batched call covering every
    sector node -- so a model response naming the SAME ticker under two
    different parent nodes is a real, reachable shape (unlike the broad
    path's per-node pool exclusion, which removes an already-registered
    ticker from later candidate pools before the model ever sees it
    again). This exercises the real merge site in engine._narrow_single_call."""
    _company(db_session, "MULTI.NS", "Multi Co", "fmcg")
    _company(db_session, "AUTOCO.NS", "Auto Co", "auto")
    router = FakeRouter({
        "extract_facts": dict(FACTS, event_type="earnings"),
        "narrow_graph": {
            "shocks": [],
            "edges": [
                _edge("event", "fmcg", child_type="sector", parent_type="event", mat=0.6, conf=0.8),
                _edge("event", "auto", child_type="sector", parent_type="event", mat=0.6, conf=0.8),
            ],
        },
        "narrow_companies": {"companies": [
            dict(_company_entry("MULTI.NS", "Multi Co", direction="bullish", impact=0.6, conf=0.8, mat=0.5),
                 parent_id="fmcg", net_direction="bullish", economic_effect="positive",
                 mechanism="rural demand tailwind", positive_channels=["rural demand"]),
            dict(_company_entry("AUTOCO.NS", "Auto Co", direction="bearish", impact=0.5, conf=0.8, mat=0.5),
                 parent_id="auto", net_direction="bearish", economic_effect="negative",
                 mechanism="auto demand hit"),
            dict(_company_entry("MULTI.NS", "Multi Co", direction="bearish", impact=0.4, conf=0.7, mat=0.4),
                 parent_id="auto", net_direction="bearish", economic_effect="negative",
                 mechanism="input cost headwind", negative_channels=["raw material cost"]),
        ]},
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)

    tickers = sorted(c.ticker for c in result.companies)
    assert tickers == ["AUTOCO.NS", "MULTI.NS"]  # one company, not a duplicate

    multi = next(c for c in result.companies if c.ticker == "MULTI.NS")
    assert multi.economic_effect == "mixed"
    assert multi.positive_channels and multi.negative_channels  # both sides survive
    # Higher impact_strength (0.6 > 0.4) mechanism is primary.
    assert multi.mechanism == "rural demand tailwind"
    assert "input cost headwind" in multi.secondary_mechanisms

    auto = next(c for c in result.companies if c.ticker == "AUTOCO.NS")
    assert auto.economic_effect == "negative"  # untouched single-mechanism company


def test_narrow_path_same_direction_mechanisms_merge_end_to_end(db_session):
    """Three entries for the same ticker (DUAL.NS) in one batched response
    -- a real 3-way collision, not just two. All three mechanisms must
    survive: the highest-impact one as primary, the other two folded into
    secondary_mechanisms (review finding: a naive chained merge drops the
    FIRST loser once a third, higher-impact proposal arrives)."""
    _company(db_session, "DUAL.NS", "Dual Co", "fmcg")
    _company(db_session, "OTHER.NS", "Other Co", "auto")
    router = FakeRouter({
        "extract_facts": dict(FACTS, event_type="earnings"),
        "narrow_graph": {
            "shocks": [],
            "edges": [
                _edge("event", "fmcg", child_type="sector", parent_type="event", mat=0.6, conf=0.8),
                _edge("event", "auto", child_type="sector", parent_type="event", mat=0.6, conf=0.8),
            ],
        },
        "narrow_companies": {"companies": [
            dict(_company_entry("DUAL.NS", "Dual Co", direction="bearish", impact=0.4, conf=0.7, mat=0.4),
                 parent_id="fmcg", net_direction="bearish", economic_effect="negative",
                 mechanism="input cost pressure", negative_channels=["raw material cost"]),
            dict(_company_entry("OTHER.NS", "Other Co", direction="bearish", impact=0.5, conf=0.8, mat=0.5),
                 parent_id="auto", net_direction="bearish", economic_effect="negative",
                 mechanism="demand hit"),
            dict(_company_entry("DUAL.NS", "Dual Co", direction="bearish", impact=0.6, conf=0.8, mat=0.5),
                 parent_id="auto", net_direction="bearish", economic_effect="negative",
                 mechanism="second segment demand hit", negative_channels=["segment demand"]),
            dict(_company_entry("DUAL.NS", "Dual Co", direction="bearish", impact=0.55, conf=0.7, mat=0.4),
                 parent_id="auto", net_direction="bearish", economic_effect="negative",
                 mechanism="third channel pressure", negative_channels=["channel cost"]),
        ]},
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)

    tickers = sorted(c.ticker for c in result.companies)
    assert tickers == ["DUAL.NS", "OTHER.NS"]

    dual = next(c for c in result.companies if c.ticker == "DUAL.NS")
    assert dual.economic_effect == "negative"  # same-direction, never flips to mixed
    assert dual.impact_strength == 0.6  # highest-impact record wins as base
    assert dual.mechanism == "second segment demand hit"
    # All three mechanisms survive: one primary + two secondary -- neither
    # earlier-displaced mechanism is silently dropped by the third merge.
    assert set(dual.secondary_mechanisms) == {"input cost pressure", "third channel pressure"}
    assert len(dual.secondary_mechanisms) == 2
    assert set(dual.negative_channels) == {"raw material cost", "segment demand", "channel cost"}
