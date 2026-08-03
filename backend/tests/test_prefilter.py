"""Phase 3 of the cost-optimization plan: a deterministic rule pass in
front of the relevance LLM call.

Most of these tests are about what the pre-filter must NOT do. Rejecting a
real market story loses it from the feed silently, so the bar is that every
borderline headline -- a sponsorship deal that says "cricket", an
executive's death, a plant accident -- still reaches the LLM.
"""
from app.filtering.prefilter import (
    PASS, REJECT, PrefilterCounters, apply_prefilter, market_signal_in,
    noise_pattern_in, prefilter_verdict,
)
from app.filtering.relevance import filter_new_articles
from app.models import Article

import json
from types import SimpleNamespace


# --- what the rules reject: unambiguous non-market noise ---

CLEAR_NOISE = [
    ("Today's horoscope: what the stars say for Leo", "Leo, patience will serve you well today."),
    ("Recipe: how to make the perfect masala chai at home", "Boil water with ginger and cardamom."),
    ("Watch video: elephant calf plays in the river, netizens delighted", "The clip has been shared widely."),
    ("Weight loss tips that actually work, say experts", "Sleep and hydration matter most."),
    ("Wimbledon: teenager stuns defending champion in five sets", "The match lasted four hours."),
    ("Man arrested for murder of neighbour in Pune", "Police said the accused has confessed."),
    ("Obituary: the poet who shaped a generation", "He is survived by his daughter."),
]


def test_clear_noise_is_rejected():
    for title, content in CLEAR_NOISE:
        verdict, reason = prefilter_verdict(title, content)
        assert verdict == REJECT, f"expected reject for {title!r} ({reason})"


# --- what the rules must never reject: anything with a market angle ---

REAL_MARKET_NEWS = [
    # Plain market news -- no noise pattern at all.
    ("RBI cuts repo rate by 25 basis points", "The central bank lowered its key lending rate."),
    ("Reliance Q2 profit rises 12%", "The company reported higher refining margins."),
    ("Crude slips below $70 on OPEC supply signals", "Traders expect further output increases."),
    # Noise-looking headlines that ARE market news -- the veto must save
    # every one of these. This is the list that matters.
    ("Star Sports wins cricket broadcast rights in ₹5,000 crore deal",
     "The five-year contract covers all home matches."),
    ("Infosys CEO dies at 58, board names interim successor",
     "The company said operations continue uninterrupted."),
    ("Bus crash at cement plant halts production for a week",
     "The factory supplies 8% of regional output."),
    ("Wedding season demand lifts gold imports",
     "Jewellers report the strongest quarter in three years."),
    ("Viral video of unsafe working conditions triggers regulator probe into the firm",
     "The regulator has sought an explanation from the company."),
    ("Man arrested for insider trading in listed pharma stock",
     "Sebi said the trades were placed ahead of an earnings announcement."),
    ("Recipe brand IPO subscribed 12 times on day one",
     "The issue is priced at the upper end of its band."),
]


def test_real_market_news_is_never_rejected():
    for title, content in REAL_MARKET_NEWS:
        verdict, reason = prefilter_verdict(title, content)
        assert verdict == PASS, f"WOULD HAVE LOST A REAL STORY: {title!r} ({reason})"


def test_noise_headline_with_financial_body_is_admitted():
    """The veto reads the body, not just the headline -- a market angle
    buried below the fold still admits the article."""
    verdict, reason = prefilter_verdict(
        "Wimbledon final draws record crowd",
        "Broadcast revenue for the tournament rose to £60 million.",
    )
    assert verdict == PASS
    assert "vetoed by market signal" in reason


def test_monsoon_and_weather_are_never_treated_as_noise():
    """This system has monsoon_weather as a first-class event type, so
    weather stories must reach the analysis path, not be filtered as
    lifestyle content."""
    verdict, _ = prefilter_verdict("Monsoon arrives a week early over Kerala", "Rainfall is 12% above normal.")
    assert verdict == PASS
    assert noise_pattern_in("IMD forecasts heavy rainfall across the west coast") is None


def test_unrecognised_headline_goes_to_the_llm():
    """The rules only ever short-circuit what they positively recognise as
    noise. Anything they have no opinion on is the LLM's call, exactly as
    before this shipped."""
    verdict, reason = prefilter_verdict("Something entirely unfamiliar happened yesterday", "")
    assert verdict == PASS
    assert reason == "no noise pattern in headline"


def test_empty_article_is_admitted_not_rejected():
    assert prefilter_verdict("", "")[0] == PASS
    assert prefilter_verdict(None, None)[0] == PASS


def test_market_signal_lookup_reports_which_signal_matched():
    assert market_signal_in("Profit rose sharply") == "profit"
    assert market_signal_in("the cat sat on the mat") is None


# --- mode handling ---

def _counted(title, content, mode, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "relevance_prefilter_mode", mode)
    counters = PrefilterCounters()
    short_circuited = apply_prefilter(title, content, counters)
    return short_circuited, counters


def test_shadow_mode_counts_but_never_short_circuits(monkeypatch):
    short_circuited, counters = _counted(*CLEAR_NOISE[0], "shadow", monkeypatch)
    assert short_circuited is False
    assert counters.shadow_rejected == 1
    assert counters.rejected == 0
    assert counters.llm_calls_saved == 0


def test_enforce_mode_short_circuits(monkeypatch):
    short_circuited, counters = _counted(*CLEAR_NOISE[0], "enforce", monkeypatch)
    assert short_circuited is True
    assert counters.rejected == 1
    assert counters.llm_calls_saved == 1


def test_off_mode_does_not_run_the_rules_at_all(monkeypatch):
    short_circuited, counters = _counted(*CLEAR_NOISE[0], "off", monkeypatch)
    assert short_circuited is False
    assert counters.shadow_rejected == 0
    assert counters.passed == 1


# --- wiring into filter_new_articles ---

def _counting_client(calls):
    def create(**kwargs):
        calls.append(kwargs)
        tool_call = SimpleNamespace(function=SimpleNamespace(
            name="record_relevance", arguments=json.dumps({"relevant": True}),
        ))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call]))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _seed_articles(db_session):
    db_session.add_all([
        Article(source="s", url="https://example.com/1", title=CLEAR_NOISE[0][0], content=CLEAR_NOISE[0][1], status="NEW"),
        Article(source="s", url="https://example.com/2", title=REAL_MARKET_NEWS[0][0], content=REAL_MARKET_NEWS[0][1], status="NEW"),
    ])
    db_session.commit()


def test_enforce_mode_saves_the_llm_call_and_filters_the_article(db_session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "relevance_prefilter_mode", "enforce")
    _seed_articles(db_session)
    calls = []

    filter_new_articles(db_session, _counting_client(calls))

    statuses = {a.title: a.status for a in db_session.query(Article).all()}
    assert statuses[CLEAR_NOISE[0][0]] == "FILTERED"
    assert statuses[REAL_MARKET_NEWS[0][0]] == "CATEGORIZED"
    assert len(calls) == 1  # only the real story cost a call


def test_shadow_mode_leaves_the_pipeline_byte_identical(db_session, monkeypatch):
    """Shadow mode must produce exactly the outcome a run with the
    pre-filter off produces -- same statuses, same number of LLM calls."""
    from app.config import settings
    monkeypatch.setattr(settings, "relevance_prefilter_mode", "shadow")
    _seed_articles(db_session)
    calls = []

    filter_new_articles(db_session, _counting_client(calls))

    statuses = {a.status for a in db_session.query(Article).all()}
    assert statuses == {"CATEGORIZED"}
    assert len(calls) == 2
