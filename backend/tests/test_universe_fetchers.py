from datetime import date

import pytest

from app.companies.universe import fetchers


class FakeOpener:
    """Stands in for the urllib opener. Records URLs, returns canned bytes."""

    def __init__(self, payloads):
        self.payloads = payloads
        self.urls = []

    def __call__(self, url, timeout=None):
        self.urls.append(url)
        if isinstance(self.payloads, Exception):
            raise self.payloads
        return self.payloads


def test_fetch_nse_equity_list_writes_snapshot(tmp_path):
    opener = FakeOpener(b"SYMBOL,NAME OF COMPANY\nRELIANCE,Reliance Industries Ltd\n")
    path = fetchers.fetch_nse_equity_list(str(tmp_path), date(2026, 8, 3), opener=opener)
    assert path.read_bytes().startswith(b"SYMBOL,")
    assert opener.urls == [fetchers.NSE_EQUITY_L_URL]


def test_fetch_bse_scrip_list_writes_snapshot(tmp_path):
    opener = FakeOpener(b'[{"SCRIP_CD":"500325"}]')
    path = fetchers.fetch_bse_scrip_list(str(tmp_path), date(2026, 8, 3), opener=opener)
    assert path.name == "bse_scrips.json"
    assert b"500325" in path.read_bytes()


def test_fetcher_propagates_failure_loudly(tmp_path):
    opener = FakeOpener(OSError("connection reset"))
    with pytest.raises(OSError):
        fetchers.fetch_nse_equity_list(str(tmp_path), date(2026, 8, 3), opener=opener)


def test_empty_response_is_rejected_before_writing(tmp_path):
    opener = FakeOpener(b"")
    with pytest.raises(ValueError):
        fetchers.fetch_nse_equity_list(str(tmp_path), date(2026, 8, 3), opener=opener)
    assert not fetchers.snapshot.master_path(
        str(tmp_path), date(2026, 8, 3), "nse_equity_l.csv"
    ).exists()


class ScriptedOpener:
    """Returns a queued response per call; an Exception instance in the
    queue is raised instead of returned."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def __call__(self, url, timeout=None):
        self.urls.append(url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_fetch_bse_details_writes_one_file_per_scrip(tmp_path):
    opener = ScriptedOpener([b'{"ISIN":"INE002A01018"}', b'{"ISIN":"INE009A01021"}'])
    result = fetchers.fetch_bse_details(
        str(tmp_path), date(2026, 8, 3), ["500325", "500209"],
        opener=opener, sleep=lambda _s: None,
    )
    assert result["fetched"] == 2
    assert result["failed"] == []
    assert fetchers.snapshot.detail_path(str(tmp_path), date(2026, 8, 3), "500325").exists()


def test_fetch_bse_details_skips_codes_already_on_disk(tmp_path):
    day = date(2026, 8, 3)
    existing = fetchers.snapshot.detail_path(str(tmp_path), day, "500325")
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text('{"ISIN":"cached"}', encoding="utf-8")

    opener = ScriptedOpener([b'{"ISIN":"INE009A01021"}'])
    result = fetchers.fetch_bse_details(
        str(tmp_path), day, ["500325", "500209"], opener=opener, sleep=lambda _s: None,
    )
    assert result["skipped"] == 1
    assert result["fetched"] == 1
    assert existing.read_text(encoding="utf-8") == '{"ISIN":"cached"}'


def test_fetch_bse_details_retries_then_records_failure(tmp_path):
    opener = ScriptedOpener([OSError("429"), OSError("429"), OSError("429")])
    result = fetchers.fetch_bse_details(
        str(tmp_path), date(2026, 8, 3), ["500325"],
        opener=opener, sleep=lambda _s: None, max_retries=3,
    )
    assert result["failed"] == ["500325"]
    assert result["fetched"] == 0
    assert len(opener.urls) == 3


def test_fetch_bse_details_backs_off_between_retries(tmp_path):
    delays = []
    opener = ScriptedOpener([OSError("429"), b'{"ISIN":"INE002A01018"}'])
    fetchers.fetch_bse_details(
        str(tmp_path), date(2026, 8, 3), ["500325"],
        opener=opener, sleep=delays.append, max_retries=3, throttle_seconds=0.0,
    )
    assert delays and delays[0] > 0


def test_detail_pass_aborts_when_the_source_refuses_everything():
    """BSE answers ~2 of 18 requests from Railway's egress IP (measured
    2026-08-05). Without a breaker the monthly job walks ~4,700 scrips at
    three 60s timeouts each -- days of wall-clock to accomplish nothing."""
    attempts = []

    def refusing(url):
        attempts.append(url)
        raise TimeoutError("blocked")

    result = fetchers.fetch_bse_details(
        "unused", date(2026, 8, 5), [str(500000 + i) for i in range(500)],
        opener=refusing, sleep=lambda _s: None, throttle_seconds=0,
        max_retries=1, abort_after_consecutive_failures=10,
    )
    assert result["aborted"] is True
    assert result["fetched"] == 0
    # 10 failures trip it, and the breaker is checked before the 11th.
    assert len(result["failed"]) == 10
    assert len(attempts) == 10


def test_a_successful_scrip_resets_the_breaker(tmp_path):
    """Intermittent failures are normal and must not abort a healthy run."""
    calls = {"n": 0}

    def flaky(url):
        calls["n"] += 1
        if calls["n"] % 3:
            raise TimeoutError("transient")
        return b'{"Table":[{"scrip_cd":"1"}]}'

    result = fetchers.fetch_bse_details(
        str(tmp_path), date(2026, 8, 5), [str(500000 + i) for i in range(9)],
        opener=flaky, sleep=lambda _s: None, throttle_seconds=0,
        max_retries=3, abort_after_consecutive_failures=2,
    )
    assert result["aborted"] is False
    assert result["fetched"] == 9
