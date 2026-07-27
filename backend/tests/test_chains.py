import pytest

from app.analysis.schemas import SECTORS
from app.reasoning.rulebook import CHAINS, EDGE_RELATIONS, NODE_MECHANISM, NODE_SECTOR, get_chain


def test_every_sector_node_label_is_a_real_sector():
    for event_type, edges in CHAINS.items():
        for edge in edges:
            for endpoint in (edge["from"], edge["to"]):
                if endpoint["kind"] == NODE_SECTOR:
                    assert endpoint["label"] in SECTORS, f"{event_type}: {endpoint['label']!r} not in SECTORS"


def test_every_node_kind_is_mechanism_or_sector():
    for event_type, edges in CHAINS.items():
        for edge in edges:
            for endpoint in (edge["from"], edge["to"]):
                assert endpoint["kind"] in {NODE_MECHANISM, NODE_SECTOR}, f"{event_type}: bad kind {endpoint['kind']!r}"


def test_every_relation_is_valid():
    for event_type, edges in CHAINS.items():
        for edge in edges:
            assert edge["relation"] in EDGE_RELATIONS, f"{event_type}: bad relation {edge['relation']!r}"


def test_every_direction_is_valid():
    for event_type, edges in CHAINS.items():
        for edge in edges:
            assert edge["direction"] in {"bullish", "bearish"}, f"{event_type}: bad direction {edge['direction']!r}"


def test_every_edge_has_a_nonempty_note():
    for event_type, edges in CHAINS.items():
        for edge in edges:
            assert edge["note"].strip(), f"{event_type}: edge has an empty note"


def test_get_chain_none_event_type_returns_none():
    assert get_chain(None) is None


@pytest.mark.parametrize("event_type", [
    "repo_rate_change", "crude_oil", "government_spending", "currency_move",
    "inflation", "macro_data", "fiscal_policy", "monsoon_weather",
    "commodity_price", "global_rates", "geopolitics", "fii_dii_flows",
    "government_policy", "trade_policy", "regulation", "pricing_action",
])
def test_broad_mechanism_event_types_have_a_nonempty_chain(event_type):
    chain = get_chain(event_type)
    assert chain is not None
    assert len(chain) > 0


@pytest.mark.parametrize("event_type", [
    "earnings", "merger_acquisition", "banking_metrics",
    "order_win_contract", "corporate_action", "other",
])
def test_company_specific_event_types_have_no_chain(event_type):
    assert get_chain(event_type) is None


def test_get_chain_unknown_event_type_returns_none():
    assert get_chain("not_a_real_event_type") is None


def test_chains_text_is_nonempty_and_mentions_every_event_type():
    from app.reasoning.rulebook import CHAINS_TEXT
    assert CHAINS_TEXT
    for event_type in CHAINS:
        assert event_type in CHAINS_TEXT


def test_every_chain_event_type_is_chain_bearing():
    from app.reasoning.rulebook import CHAIN_EXCLUDED_EVENT_TYPES
    for event_type in CHAINS:
        assert event_type not in CHAIN_EXCLUDED_EVENT_TYPES


def test_canonical_chain_labels_are_stable():
    # _build_chains picks the first-declared rule per event_type; these
    # mechanism-node labels pin the canonical directional variant so a
    # later insertion cannot silently flip a chart chain's direction.
    expected = {
        "repo_rate_change": "Repo Rate ↓",
        "inflation": "Inflation ↑",
        "crude_oil": "Crude Oil ↑",
        "currency_move": "INR ↓",
        "fiscal_policy": "GST Cut",
        "commodity_price": "Metal Prices ↑",
        "global_rates": "Global Risk-Off",
        "government_policy": "PLI Scheme",
        "trade_policy": "Import Duty ↑",
        "regulation": "RBI Tightening",
        "pricing_action": "Telecom Tariff ↑",
        "macro_data": "GDP Growth ↑",
        "monsoon_weather": "Good Monsoon",
        "geopolitics": "Geopolitical Conflict",
        "government_spending": "Govt Capex ↑",
        "fii_dii_flows": "FII Outflows",
    }
    for event_type, label in expected.items():
        mech_labels = [e["from"]["label"] for e in CHAINS[event_type]
                       if e["from"]["kind"] == "mechanism"]
        assert label in mech_labels, f"{event_type}: canonical chain is not {label!r}"
