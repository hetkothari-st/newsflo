from app.analysis.schemas import EVENT_TYPES, SECTORS
from app.companies.sub_sectors import SUB_SECTOR_TAXONOMY
from app.reasoning.rulebook import (
    CHAIN_EXCLUDED_EVENT_TYPES, EDGE_RELATIONS, RULEBOOK_DIGEST, RULEBOOK_TEXT,
    RULES, get_rule,
)


def test_get_rule_returns_text_for_known_id():
    assert get_rule("RULE_REPO_RATE_CUT") is not None
    text = get_rule("RULE_REPO_RATE_CUT").lower()
    assert "bank" in text


def test_get_rule_returns_none_for_unknown_id():
    assert get_rule("RULE_DOES_NOT_EXIST") is None


def test_rule_ids_are_uppercase_with_prefix():
    for rule_id in RULES:
        assert rule_id.startswith("RULE_")
        assert rule_id == rule_id.upper()


def test_rulebook_text_contains_every_rule_id():
    for rule_id in RULES:
        assert rule_id in RULEBOOK_TEXT


def test_legacy_rule_ids_survive():
    # Persisted evidence_refs in production cite these exact ids.
    for rule_id in [
        "RULE_REPO_RATE_CUT", "RULE_REPO_RATE_HIKE", "RULE_INFLATION_RISE",
        "RULE_CRUDE_OIL_UP", "RULE_CURRENCY_INR_WEAKENS", "RULE_GOVERNMENT_CAPEX",
        "RULE_EARNINGS", "RULE_MERGER_ACQUISITION", "RULE_BANKING_METRICS",
    ]:
        assert rule_id in RULES, f"legacy id {rule_id} was renamed or dropped"


def test_every_rule_has_required_fields():
    for rule_id, rule in RULES.items():
        assert rule["trigger"].strip(), rule_id
        assert rule["event_type"] in EVENT_TYPES, f"{rule_id}: bad event_type {rule['event_type']!r}"
        assert isinstance(rule["branches"], list), rule_id
        if rule["branches"]:
            assert rule.get("label"), f"{rule_id}: branch rules need a chart label"


def test_every_branch_is_valid():
    for rule_id, rule in RULES.items():
        for b in rule["branches"]:
            assert b["sector"] in SECTORS, f"{rule_id}: bad sector {b['sector']!r}"
            if b["sub_sector"] is not None:
                assert b["sub_sector"] in SUB_SECTOR_TAXONOMY.get(b["sector"], []), (
                    f"{rule_id}: {b['sub_sector']!r} not in taxonomy for {b['sector']}"
                )
            assert b["direction"] in {"bullish", "bearish"}, rule_id
            assert b["relation"] in EDGE_RELATIONS, f"{rule_id}: bad relation {b['relation']!r}"
            assert b["mechanism"].strip(), f"{rule_id}: empty mechanism"
            assert b["order"] in {1, 2}, rule_id
            if b["order"] == 2:
                assert b["via"], f"{rule_id}: order-2 branch missing via"
            if b["parent_sector"] is not None:
                assert b["parent_sector"] in SECTORS, rule_id


def test_digest_covers_exactly_the_branch_rules():
    for rule_id, rule in RULES.items():
        if rule["branches"]:
            assert rule_id in RULEBOOK_DIGEST, f"{rule_id} missing from digest"
        else:
            assert rule_id not in RULEBOOK_DIGEST, f"company-scoped {rule_id} should not be in digest"


def test_chain_excluded_event_types_are_the_company_scoped_ones():
    assert CHAIN_EXCLUDED_EVENT_TYPES == frozenset({
        "earnings", "merger_acquisition", "banking_metrics",
        "order_win_contract", "corporate_action", "other",
    })


def test_digest_marks_conditional_branches_with_only_if():
    # RULE_IMPORT_DUTY_HIKE's branches are all condition-gated (e.g. "the
    # duty protects steel") -- the stage-2 digest must surface that, or the
    # model reads them as unconditional sector calls.
    lines = [line for line in RULEBOOK_DIGEST.splitlines() if line.startswith("- RULE_IMPORT_DUTY_HIKE:")]
    assert len(lines) == 1
    assert "only if" in lines[0]


def test_rendered_rule_mentions_condition_and_via():
    # RULE_CRUDE_OIL_UP has a conditional branch and (after Task 5) an
    # order-2 branch -- the rendering must surface both markers.
    text = get_rule("RULE_CRUDE_OIL_UP")
    assert "only if" in text
    assert "via packaging and freight" in text
