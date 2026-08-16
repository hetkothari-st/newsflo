"""TASK 0.6 tests -- claim compiler + entailment firewall (spec §11.2/§11.3).

docs/v5/01_PHASE_0_canonical_truth.md TESTS/test_firewall.py:
  * sentence containing a numeral absent from record_set is deleted
  * sentence naming an entity absent from record_set is deleted
  * sentence fully entailed survives
  * firewall deletion leaves valid output (fallback path)
  * PRIMARY prose on the fixture corpus has deletion rate == 0

OFFLINE (controller adaptation): stage 2 is an entailment judge that must be
INJECTED. It is exercised here with a fake judge; no test may construct a
real client, and the suite's autouse `_no_real_anthropic_client` fixture
would fail loudly if one tried.
"""
import ast
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db import Base
from tests.phase0 import fixtures

OUTPUT = Path(__file__).resolve().parents[2] / "app" / "output"


@pytest.fixture()
def impact():
    from app.core.reducer import reduce_company_impact

    return reduce_company_impact(
        fixtures.signals(fixtures.PRIMARY_COMPANY_ID), fixtures.reducer_config())


@pytest.fixture()
def record_set(impact):
    from app.output.firewall import record_set_from

    return record_set_from(impact, fixtures.claims(fixtures.PRIMARY_COMPANY_ID),
                           fixtures.evidence())


@pytest.fixture()
def firewall_db(tmp_path):
    from app import models  # noqa: F401

    engine = create_engine(f"sqlite:///{tmp_path / 'fw.db'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class _Judge:
    """Injected stage-2 entailment judge. Binary, and it is the ONLY thing
    the firewall is allowed to ask -- never a rewrite."""

    model_id = "fake-judge-v1"

    def __init__(self, verdicts=None, default=True):
        self.verdicts = verdicts or {}
        self.default = default
        self.seen = []

    def entails(self, sentence, record_set):
        self.seen.append(sentence)
        return self.verdicts.get(sentence, self.default)


# --- compiler --------------------------------------------------------------

def test_compiler_is_deterministic(impact):
    from app.output.compiler import compile_prose

    claims = fixtures.claims(fixtures.PRIMARY_COMPANY_ID)
    assert compile_prose(impact, claims) == compile_prose(impact, claims)


def test_compiler_templates_contain_no_literal_numerals():
    """Spec §11.2: 'Every numeral inserted via template variable, never free
    text.' A digit inside a template string is a fabricated number waiting
    to happen."""
    from app.output.compiler import TEMPLATES

    for key, template in TEMPLATES.items():
        assert not any(ch.isdigit() for ch in template), (
            f"template {key} contains a literal digit: {template!r}")


def test_compiler_templates_are_keyed_by_claim_type_direction_materiality():
    from app.output.compiler import TEMPLATES

    for key in TEMPLATES:
        assert len(key) == 3, key
        claim_type, direction, materiality = key
        assert direction in ("POSITIVE", "NEGATIVE", "MIXED", "UNCERTAIN")
        assert materiality in ("HIGH", "MEDIUM", "LOW")


def test_compiler_uses_no_llm():
    """The optional fluency pass must be injected, exactly like the judge."""
    source = (OUTPUT / "compiler.py").read_text(encoding="utf-8")
    for needle in ("anthropic", "openai", "ClaudeJSONClient", "messages.create"):
        assert needle not in source


def test_the_system_is_fully_functional_with_the_fluency_pass_off(impact):
    """Phase file: 'This pass is skippable via config; the system must be
    fully functional with it off.'"""
    from app.output.compiler import compile_prose, render

    claims = fixtures.claims(fixtures.PRIMARY_COMPANY_ID)
    assert compile_prose(impact, claims)
    text_off = render(impact, claims, rewriter=None)
    assert text_off and text_off.strip()


# --- firewall stage 1 ------------------------------------------------------

def test_sentence_with_an_unsourced_numeral_is_deleted(record_set):
    from app.output.firewall import firewall

    result = firewall(["FIXCO1.NS passed on 97 percent of the increase."],
                      record_set)
    assert result.kept == []
    assert result.deletions[0].stage == "STAGE_1"
    assert "numeral" in result.deletions[0].reason


def test_sentence_naming_an_unknown_entity_is_deleted(record_set):
    from app.output.firewall import firewall

    result = firewall(["Reliance Industries faces the same cost pressure."],
                      record_set)
    assert result.kept == []
    assert result.deletions[0].stage == "STAGE_1"
    assert "entity" in result.deletions[0].reason


def test_sentence_with_an_unknown_date_is_deleted(record_set):
    from app.output.firewall import firewall

    result = firewall(["The exposure was disclosed on 2019-01-15."], record_set)
    assert result.kept == []
    assert "date" in result.deletions[0].reason


def test_fully_entailed_sentence_survives(impact, record_set):
    from app.output.compiler import compile_prose
    from app.output.firewall import firewall

    sentences = compile_prose(impact, fixtures.claims(fixtures.PRIMARY_COMPANY_ID))
    result = firewall(sentences, record_set)
    assert result.kept == sentences
    assert result.deletions == []


def test_failing_sentences_are_deleted_never_repaired(record_set):
    from app.output.firewall import firewall

    good = "FIXCO1.NS is exposed through the crude input cost channel."
    bad = "FIXCO1.NS hedged 90 percent of its exposure."
    result = firewall([good, bad], record_set)
    assert result.kept == [good], "a kept sentence was altered, not passed through"
    assert [d.sentence for d in result.deletions] == [bad]


def test_deletion_leaves_valid_output_via_the_template_fallback(record_set):
    """Phase file: 'If deletion leaves output under MIN_PROSE_CHARS, fall
    back to the deterministic template output verbatim.'"""
    from app.output.firewall import MIN_PROSE_CHARS, firewall

    fallback = "F" * (MIN_PROSE_CHARS + 10)
    result = firewall(["FIXCO1.NS hedged 90 percent of its exposure."],
                      record_set, fallback_text=fallback)
    assert result.fallback_used is True
    assert result.text == fallback
    assert len(result.text) >= MIN_PROSE_CHARS


def test_primary_prose_has_deletion_rate_zero_on_the_fixture_corpus(impact, record_set):
    """DEFINITION OF DONE: 'Firewall deletion rate on PRIMARY prose == 0 for
    fixtures.'"""
    from app.output.compiler import compile_prose
    from app.output.firewall import firewall

    assert impact.publication_tier == "PRIMARY"
    sentences = compile_prose(impact, fixtures.claims(fixtures.PRIMARY_COMPANY_ID))
    result = firewall(sentences, record_set, judge=_Judge(default=True))
    assert result.deletion_rate == 0.0, [d.sentence for d in result.deletions]


# --- firewall stage 2 ------------------------------------------------------

def test_stage_two_runs_only_when_a_judge_is_injected(record_set):
    from app.output.firewall import firewall

    sentence = "FIXCO1.NS is exposed through the crude input cost channel."
    judge = _Judge(default=True)

    firewall([sentence], record_set)                 # no judge -> skipped
    assert judge.seen == []

    firewall([sentence], record_set, judge=judge)    # injected -> runs
    assert judge.seen == [sentence]


def test_stage_two_non_entailed_sentence_is_deleted_and_attributed(record_set):
    from app.output.firewall import firewall

    sentence = "FIXCO1.NS is exposed through the crude input cost channel."
    judge = _Judge(verdicts={sentence: False})
    result = firewall([sentence], record_set, judge=judge)

    assert result.kept == []
    deletion = result.deletions[0]
    assert deletion.stage == "STAGE_2"
    assert deletion.model_id == "fake-judge-v1"


def test_stage_one_always_runs_even_with_a_permissive_judge(record_set):
    from app.output.firewall import firewall

    result = firewall(["FIXCO1.NS hedged 90 percent of its exposure."],
                      record_set, judge=_Judge(default=True))
    assert result.kept == []
    assert result.deletions[0].stage == "STAGE_1"


def test_firewall_module_constructs_no_client():
    source = (OUTPUT / "firewall.py").read_text(encoding="utf-8")
    for needle in ("anthropic", "openai", "ClaudeJSONClient", "messages.create"):
        assert needle not in source
    tree = ast.parse(source)
    imported = {n.module for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.module}
    assert not any(m.startswith("app.analysis") or m.startswith("app.reasoning")
                   for m in imported)


# --- deletion log + metric -------------------------------------------------

def test_deletions_are_logged_to_the_firewall_deletion_table(firewall_db, record_set):
    from app.output.firewall import firewall, log_deletions

    result = firewall(["FIXCO1.NS hedged 90 percent of its exposure."], record_set)
    log_deletions(firewall_db, event_id="fixture:crude-shock-1",
                  company_id=fixtures.PRIMARY_COMPANY_ID, result=result)
    firewall_db.commit()

    rows = firewall_db.execute(text(
        "SELECT sentence, reason, stage FROM firewall_deletion")).all()
    assert len(rows) == 1
    assert rows[0][2] == "STAGE_1"


def test_deletion_rate_is_exposed_as_a_prometheus_metric(record_set):
    from app.output import firewall as fw

    fw.reset_metrics()
    fw.firewall(["FIXCO1.NS hedged 90 percent of its exposure."], record_set)
    exposition = fw.metrics_text()
    assert "newsflo_firewall_sentences_total" in exposition
    assert "newsflo_firewall_deletions_total" in exposition
    assert 'stage="STAGE_1"' in exposition


# --- fix round 1: I3, digit-bearing tickers ---------------------------------

class _TickerImpact:
    """Minimal CompanyImpact-shaped stand-in for record_set_from. Real NSE
    tickers START WITH DIGITS (3MINDIA.NS, 5PAISA.NS, 63MOONS.NS), which is
    the case the first cut of stage 1 got wrong."""
    ticker = "3MINDIA.NS"
    isin = None
    channels = ()
    mechanism_id = "input_cost"
    net_effect = "NEGATIVE"
    materiality_bucket = "HIGH"
    directness = "DIRECT"
    discovery_source = "MENTION"
    publication_tier = "PRIMARY"
    graph_distance = 1
    sign_consistency = 1.0


@pytest.fixture()
def ticker_record_set():
    from app.output.firewall import RecordSet, record_set_from

    base = record_set_from(_TickerImpact())
    # 5PAISA.NS and 63MOONS.NS are real, resolved entities of this event too.
    return RecordSet(
        numerals=base.numerals,
        entities=base.entities | {"5PAISA.NS", "63MOONS.NS"},
        dates=base.dates)


@pytest.mark.parametrize("ticker", ["3MINDIA.NS", "5PAISA.NS", "63MOONS.NS"])
def test_digit_bearing_ticker_is_not_read_as_a_numeral(ticker, ticker_record_set):
    """I3: the digits inside a ticker are part of its NAME. Reading them as
    claims made the firewall delete honest sentences the moment a real NSE
    ticker appeared."""
    from app.output.firewall import firewall

    sentence = f"{ticker} is exposed through the input cost channel."
    result = firewall([sentence], ticker_record_set)
    assert result.kept == [sentence], (
        [(d.reason, d.stage) for d in result.deletions])


@pytest.mark.parametrize("ticker", ["3MINDIA.NS", "5PAISA.NS", "63MOONS.NS"])
def test_a_real_numeral_next_to_a_ticker_is_still_checked(ticker, ticker_record_set):
    """The mask must remove the TICKER, not the numbers around it."""
    from app.output.firewall import firewall

    sentence = f"{ticker} hedged 90 percent of its exposure."
    result = firewall([sentence], ticker_record_set)
    assert result.kept == []
    assert "numeral" in result.deletions[0].reason
    assert "90" in result.deletions[0].reason


def test_a_digit_bearing_token_that_is_not_a_known_entity_is_deleted(ticker_record_set):
    """Masking applies only to VALIDATED entities -- an unknown ticker-shaped
    token is still an unsupported entity, not a free pass."""
    from app.output.firewall import firewall

    result = firewall(["7SEAS.NS is exposed through the input cost channel."],
                      ticker_record_set)
    assert result.kept == []
    assert "entity" in result.deletions[0].reason
    assert "7SEAS.NS" in result.deletions[0].reason


def test_record_set_captures_digit_leading_entities():
    from app.output.firewall import record_set_from

    record_set = record_set_from(_TickerImpact())
    assert "3MINDIA.NS" in record_set.entities
