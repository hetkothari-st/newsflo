import json
from pathlib import Path

import pytest

from app.companies.matching import aliases, matcher
from app.models import Company

ADVERSARIAL = Path(__file__).parent / "fixtures" / "matching" / "adversarial.json"
REGRESSION = Path(__file__).parent / "fixtures" / "matching" / "regression_corpus.json"


def _seed(session, companies):
    for entry in companies:
        session.add(Company(
            ticker=entry["ticker"], name=entry["name"], sector=entry["sector"],
            index_tier="OTHER", tradeability="NORMAL",
        ))
    session.commit()
    aliases.rebuild_aliases(session)


def test_adversarial_set_has_zero_mismatches(db_session):
    payload = json.loads(ADVERSARIAL.read_text(encoding="utf-8"))
    _seed(db_session, payload["companies"])

    mismatches = []
    for case in payload["cases"]:
        result = matcher.resolve(db_session, ticker=None, name=case["mention"])
        actual = (
            db_session.get(Company, result.company_id).ticker if result else None
        )
        # A miss (None where a ticker was expected) is tolerated. Returning
        # the WRONG company is the failure this gate exists to prevent.
        if actual is not None and actual != case["expect"]:
            mismatches.append((case["mention"], case["expect"], actual))

    assert mismatches == [], f"matcher returned wrong companies: {mismatches}"


def test_adversarial_set_hit_rate_is_acceptable(db_session):
    payload = json.loads(ADVERSARIAL.read_text(encoding="utf-8"))
    _seed(db_session, payload["companies"])

    expected = [c for c in payload["cases"] if c["expect"] is not None]
    hits = 0
    for case in expected:
        result = matcher.resolve(db_session, ticker=None, name=case["mention"])
        if result and db_session.get(Company, result.company_id).ticker == case["expect"]:
            hits += 1
    assert hits >= len(expected) - 1, f"only {hits}/{len(expected)} resolved"


@pytest.mark.skipif(not REGRESSION.exists(), reason="run export_match_corpus.py first")
def test_regression_corpus_has_zero_mismatches(db_session):
    payload = json.loads(REGRESSION.read_text(encoding="utf-8"))
    _seed(db_session, payload["companies"])

    mismatches = []
    for case in payload["cases"]:
        result = matcher.resolve(db_session, ticker=None, name=case["mention"])
        actual = (
            db_session.get(Company, result.company_id).ticker if result else None
        )
        if actual is not None and actual != case["expect"]:
            mismatches.append((case["mention"], case["expect"], actual))
    assert mismatches == []
