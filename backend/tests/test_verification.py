import json
from types import SimpleNamespace

from app.analysis.schemas import CompanyMention
from app.analysis.verification import build_verification_tool, verify_companies


class _FakeClient:
    def __init__(self, payload, raises=None):
        self._payload = payload
        self._raises = raises
        self.calls = 0
        self.last_kwargs = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self._raises is not None:
            raise self._raises
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            tool_calls=[SimpleNamespace(function=SimpleNamespace(
                name="record_company_verdicts", arguments=json.dumps(self._payload),
            ))],
        ))])


def _mention(ticker, name="X Ltd."):
    return CompanyMention(
        name=name, ticker=ticker, is_direct=True, sector="oil_gas",
        direction="bullish", magnitude_low=1.0, magnitude_high=3.0,
        rationale="r", time_horizon="Short-Term",
    )


def test_tool_enum_constrains_tickers_to_the_assembled_list():
    tool = build_verification_tool(["A.NS", "B.NS"])
    ticker_schema = (
        tool["function"]["parameters"]["properties"]["verdicts"]
        ["items"]["properties"]["ticker"]
    )
    assert ticker_schema["enum"] == ["A.NS", "B.NS"]


def test_a_company_marked_not_belonging_is_dropped():
    client = _FakeClient({"verdicts": [
        {"ticker": "A.NS", "belongs": True},
        {"ticker": "B.NS", "belongs": False, "reason": "no mechanism reaches it"},
    ]})

    kept = verify_companies(client, "facts", "title", [_mention("A.NS"), _mention("B.NS")])

    assert [m.ticker for m in kept] == ["A.NS"]


def test_a_company_the_model_never_judged_is_kept():
    # Omission is not a rejection -- same "omit rather than mismatch"
    # discipline as generate_impact_whys.
    client = _FakeClient({"verdicts": [{"ticker": "A.NS", "belongs": True}]})

    kept = verify_companies(client, "facts", "title", [_mention("A.NS"), _mention("B.NS")])

    assert [m.ticker for m in kept] == ["A.NS", "B.NS"]


def test_a_verdict_for_an_unknown_ticker_is_ignored():
    client = _FakeClient({"verdicts": [{"ticker": "GHOST.NS", "belongs": False}]})

    kept = verify_companies(client, "facts", "title", [_mention("A.NS")])

    assert [m.ticker for m in kept] == ["A.NS"]


def test_a_failed_call_keeps_every_company():
    client = _FakeClient(None, raises=RuntimeError("provider down"))

    kept = verify_companies(client, "facts", "title", [_mention("A.NS"), _mention("B.NS")])

    assert [m.ticker for m in kept] == ["A.NS", "B.NS"]


def test_companies_without_a_ticker_are_never_judged_or_dropped():
    # Sector fan-out mentions have no ticker; they are not the verification
    # pass's business.
    tickerless = CompanyMention(
        name="fmcg sector", ticker=None, is_direct=False, sector="fmcg",
        direction="bullish", magnitude_low=1.0, magnitude_high=3.0,
        rationale="r", time_horizon="Short-Term",
    )
    client = _FakeClient({"verdicts": [{"ticker": "A.NS", "belongs": False}]})

    kept = verify_companies(client, "facts", "title", [_mention("A.NS"), tickerless])

    assert [m.name for m in kept] == ["fmcg sector"]


def test_no_call_is_made_for_an_empty_or_tickerless_list():
    client = _FakeClient({"verdicts": []})

    assert verify_companies(client, "facts", "title", []) == []
    assert client.calls == 0


# Malformed-shape regression tests: a tool-calling model is not reliably
# schema-shaped even at the top level (the same unreliability documented at
# cascade.py:282 for nested array items). Each of these reproduces a real
# crash against the shipped code -- the verdict-processing loop originally
# sat OUTSIDE the try/except, so a malformed "verdicts" sub-field raised
# straight out of verify_companies. The call site in cascade.py wraps this
# module's own call with NO try/except of its own (deliberately -- the
# contract is that this module is self-contained), so an uncaught exception
# here would propagate all the way to app.pipeline, which retries once and
# then marks the WHOLE ARTICLE as failed -- discarding a fully successful
# analysis over one malformed optional judge-only pass. Every case here must
# degrade to "keep every company", exactly like a failed call.

def test_verdicts_as_a_dict_instead_of_a_list_keeps_every_company():
    client = _FakeClient({"verdicts": {"ticker": "A.NS", "belongs": False}})

    kept = verify_companies(client, "facts", "title", [_mention("A.NS"), _mention("B.NS")])

    assert [m.ticker for m in kept] == ["A.NS", "B.NS"]


def test_verdicts_null_keeps_every_company():
    client = _FakeClient({"verdicts": None})

    kept = verify_companies(client, "facts", "title", [_mention("A.NS"), _mention("B.NS")])

    assert [m.ticker for m in kept] == ["A.NS", "B.NS"]


def test_a_non_dict_verdict_in_the_list_is_skipped_others_processed_normally():
    client = _FakeClient({"verdicts": [
        "not a verdict object",
        {"ticker": "A.NS", "belongs": True},
    ]})

    kept = verify_companies(client, "facts", "title", [_mention("A.NS"), _mention("B.NS")])

    # The malformed entry doesn't crash the pass, and doesn't cause any
    # unintended rejection either -- A.NS is judged (kept), B.NS is simply
    # never judged (also kept -- omission is not rejection).
    assert [m.ticker for m in kept] == ["A.NS", "B.NS"]


def test_a_non_string_ticker_is_ignored_not_a_crash():
    # A list ticker would raise TypeError on `ticker not in known` (a list
    # is unhashable) if not guarded before the membership check.
    client = _FakeClient({"verdicts": [{"ticker": ["A.NS"], "belongs": False}]})

    kept = verify_companies(client, "facts", "title", [_mention("A.NS")])

    assert [m.ticker for m in kept] == ["A.NS"]
