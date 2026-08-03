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
