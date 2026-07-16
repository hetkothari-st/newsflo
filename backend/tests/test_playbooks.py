# backend/tests/test_playbooks.py
from app.analysis.schemas import SECTORS
from app.reasoning.playbooks import PLAYBOOKS, PLAYBOOKS_TEXT, get_playbook


def test_get_playbook_returns_text_for_known_sector():
    assert get_playbook("banking") is not None
    assert "NIM" in get_playbook("banking")


def test_get_playbook_returns_none_for_no_sector():
    assert get_playbook(None) is None


def test_get_playbook_returns_none_for_unknown_sector():
    assert get_playbook("not_a_real_sector") is None


def test_every_playbook_key_is_a_real_sector():
    # Guards against a typo'd sector key silently never being injected.
    for sector in PLAYBOOKS:
        assert sector in SECTORS


def test_playbooks_text_contains_every_playbook_sector_name():
    for sector in PLAYBOOKS:
        assert sector in PLAYBOOKS_TEXT
