from app.config import settings
from app.models import Company


def test_start_hub_client_noop_when_url_not_configured(db_session, monkeypatch):
    monkeypatch.setattr(settings, "zerodha_hub_url", "")
    calls = []
    monkeypatch.setattr("app.main.asyncio.create_task", lambda coro: calls.append(coro))
    monkeypatch.setattr("app.main.SessionLocal", lambda: db_session)

    from app.main import _start_hub_client_if_configured
    _start_hub_client_if_configured()

    assert calls == []


def test_start_hub_client_starts_task_with_known_instrument_tokens(db_session, monkeypatch):
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1.0, instrument_token=738561,
    ))
    db_session.add(Company(
        ticker="TCS.NS", name="TCS", sector="it",
        index_tier="NIFTY50", market_cap=1.0,  # no instrument_token
    ))
    db_session.commit()
    monkeypatch.setattr(settings, "zerodha_hub_url", "wss://fake-hub")
    monkeypatch.setattr("app.main.SessionLocal", lambda: db_session)
    started_with = {}

    def fake_run_hub_client(hub_url, instrument_tokens, cache):
        started_with["hub_url"] = hub_url
        started_with["instrument_tokens"] = instrument_tokens
        async def _noop():
            pass
        return _noop()

    monkeypatch.setattr("app.main.run_hub_client", fake_run_hub_client)
    created_tasks = []
    monkeypatch.setattr("app.main.asyncio.create_task", lambda coro: created_tasks.append(coro) or coro.close())

    from app.main import _start_hub_client_if_configured
    _start_hub_client_if_configured()

    assert started_with["hub_url"] == "wss://fake-hub"
    assert started_with["instrument_tokens"] == [738561]
    assert len(created_tasks) == 1
