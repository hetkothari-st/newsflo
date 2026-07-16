# backend/tests/test_rulebook.py
from app.reasoning.rulebook import RULEBOOK_TEXT, RULES, get_rule


def test_get_rule_returns_text_for_known_id():
    assert get_rule("RULE_REPO_RATE_CUT") is not None
    assert "banks" in get_rule("RULE_REPO_RATE_CUT").lower() or "banking" in get_rule("RULE_REPO_RATE_CUT").lower()


def test_get_rule_returns_none_for_unknown_id():
    assert get_rule("RULE_DOES_NOT_EXIST") is None


def test_rule_ids_are_uppercase_with_prefix():
    for rule_id in RULES:
        assert rule_id.startswith("RULE_")
        assert rule_id == rule_id.upper()


def test_rulebook_text_contains_every_rule_id():
    for rule_id in RULES:
        assert rule_id in RULEBOOK_TEXT
