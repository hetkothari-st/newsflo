# Live Price + Interactive Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a continuously-updating live price (sourced from a Zerodha Kite WebSocket relay) to the company detail page's price chart, plus trading-chart-style tap/hover crosshair interactivity on the chart.

**Architecture:** Backend runs one persistent background WebSocket client connecting to an already-deployed relay hub (`wss://ws-hub-production-115e.up.railway.app`), decodes Zerodha's binary tick protocol, and keeps an in-memory `{instrument_token: {ltp, as_of}}` cache. A new public REST endpoint serves that cache per company; the frontend polls it every ~20s, merges the live price into the chart's last point, and shows a big price readout. The chart gains pure-function nearest-point lookup plus pointer/touch handlers for a crosshair tooltip. No new charting library, no new persistent price-history table — same "degrade gracefully, never raise" convention as the rest of the price code.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite/Postgres (backend, unchanged), `httpx` + `websockets` (both already dependencies — no new backend deps), React + Vite + Tailwind + Vitest/RTL (frontend, unchanged), no new frontend deps.

## Global Constraints

- Backend: no new pip dependencies — `httpx` and `websockets` are already in `requirements.txt`.
- No Alembic in this project — any new column goes through the guarded `_ADDED_COLUMNS` / `ALTER TABLE` mechanism in `backend/app/db.py`.
- Every price-fetching function must degrade to `None`/`available: false` on failure, never raise — matches `app/outcomes/price_fetcher.py` and `app/companies/price_series.py`.
- No live network calls in CI — every test mocks `httpx.get` / `websockets.connect` at the module level the same way `tests/test_price_fetcher.py`, `tests/test_price_series.py`, `tests/test_poller.py` already do.
- Frontend: no new charting dependency — the crosshair/tooltip is built on the existing hand-rolled SVG (`frontend/src/features/visualize/PriceChart.tsx` / `priceChartLayout.ts`).
- New backend package `backend/app/prices/` needs its own `__init__.py` (empty file) — every existing package (`app/companies/`, `app/calibration/`, `app/outcomes/`) has one.

---

### Task 1: `Company.instrument_token` column

**Files:**
- Modify: `backend/app/models.py` (the `Company` class, currently ends at the `isin` column, around line 22)
- Modify: `backend/app/db.py` (`_ADDED_COLUMNS` list, around line 24)
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `Company.instrument_token: int | None` — the Kite instrument ID, `None` until matched by Task 2's loader.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_models.py`:

```python
def test_company_instrument_token_column(db_session):
    company = Company(
        ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1_800_000.0, instrument_token=738561,
    )
    db_session.add(company)
    db_session.commit()

    fetched = db_session.query(Company).filter_by(ticker="RELIANCE.NS").one()
    assert fetched.instrument_token == 738561


def test_company_instrument_token_defaults_to_none(db_session):
    company = Company(
        ticker="TCS.NS", name="TCS", sector="it",
        index_tier="NIFTY50", market_cap=1_500_000.0,
    )
    db_session.add(company)
    db_session.commit()

    fetched = db_session.query(Company).filter_by(ticker="TCS.NS").one()
    assert fetched.instrument_token is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_models.py -k instrument_token -v` (from `backend/`)
Expected: FAIL with `TypeError: 'instrument_token' is an invalid keyword argument for Company`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/models.py`, the `Company` class currently looks like:

```python
class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    ticker = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    sector = Column(String, nullable=False)
    index_tier = Column(String, nullable=False)  # NIFTY50 | NIFTY100 | NIFTY500 | OTHER
    market_cap = Column(Float, nullable=True)
    isin = Column(String, nullable=True, unique=True)
```

Add one line after `isin`:

```python
class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    ticker = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    sector = Column(String, nullable=False)
    index_tier = Column(String, nullable=False)  # NIFTY50 | NIFTY100 | NIFTY500 | OTHER
    market_cap = Column(Float, nullable=True)
    isin = Column(String, nullable=True, unique=True)
    instrument_token = Column(Integer, nullable=True)  # Zerodha Kite instrument ID; null until matched
```

In `backend/app/db.py`, `_ADDED_COLUMNS` currently is:

```python
_ADDED_COLUMNS = [
    ("articles", "image_url", "VARCHAR"),
    ("alert_companies", "key_points_json", "TEXT"),
    ("companies", "isin", "VARCHAR"),
    ("users", "email_alerts_enabled", "INTEGER DEFAULT 1"),
]
```

Add one entry:

```python
_ADDED_COLUMNS = [
    ("articles", "image_url", "VARCHAR"),
    ("alert_companies", "key_points_json", "TEXT"),
    ("companies", "isin", "VARCHAR"),
    ("users", "email_alerts_enabled", "INTEGER DEFAULT 1"),
    ("companies", "instrument_token", "INTEGER"),
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_models.py -v`
Expected: PASS (all tests in the file, not just the two new ones)

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/db.py backend/tests/test_models.py
git commit -m "feat: add Company.instrument_token column for Zerodha live-price matching"
```

---

### Task 2: Kite instrument-token loader

**Files:**
- Create: `backend/app/companies/kite_instruments.py`
- Test: `backend/tests/test_kite_instruments.py`

**Interfaces:**
- Consumes: `Company.instrument_token` (Task 1), `httpx.get` (already a dependency).
- Produces: `fetch_kite_instruments() -> list[dict]`, `match_instrument_tokens(session: Session, rows: list[dict]) -> int`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_kite_instruments.py`:

```python
import httpx
import pytest

from app.companies.kite_instruments import fetch_kite_instruments, match_instrument_tokens
from app.models import Company

CSV_BODY = (
    "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,"
    "tick_size,lot_size,instrument_type,segment,exchange\n"
    "738561,2885,RELIANCE,RELIANCE INDUSTRIES,0,,0,0.05,1,EQ,NSE,NSE\n"
    "5633,22,ONGC,OIL AND NATURAL GAS CORP,0,,0,0.05,1,EQ,BSE,BSE\n"
    "999999,1,SOMEFUTURE,SOME FUTURE,0,2026-08-28,0,0.05,1,FUT,NFO-FUT,NFO\n"
)


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def test_fetch_kite_instruments_filters_to_equity_nse_bse(monkeypatch):
    monkeypatch.setattr(
        "app.companies.kite_instruments.httpx.get",
        lambda url, timeout=None: _FakeResponse(CSV_BODY),
    )

    rows = fetch_kite_instruments()

    assert {r["tradingsymbol"] for r in rows} == {"RELIANCE", "ONGC"}


def test_fetch_kite_instruments_raises_on_http_error(monkeypatch):
    class _FailingResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    monkeypatch.setattr(
        "app.companies.kite_instruments.httpx.get",
        lambda url, timeout=None: _FailingResponse(),
    )

    with pytest.raises(httpx.HTTPStatusError):
        fetch_kite_instruments()


def test_match_instrument_tokens_sets_token_by_ticker_and_exchange_suffix(db_session):
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1.0,
    ))
    db_session.add(Company(
        ticker="ONGC.BO", name="ONGC BSE", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1.0,
    ))
    db_session.commit()
    rows = [
        {"tradingsymbol": "RELIANCE", "exchange": "NSE", "instrument_token": "738561"},
        {"tradingsymbol": "ONGC", "exchange": "BSE", "instrument_token": "5633"},
        {"tradingsymbol": "NOMATCH", "exchange": "NSE", "instrument_token": "1"},
    ]

    updated = match_instrument_tokens(db_session, rows)

    assert updated == 2
    reliance = db_session.query(Company).filter_by(ticker="RELIANCE.NS").one()
    ongc = db_session.query(Company).filter_by(ticker="ONGC.BO").one()
    assert reliance.instrument_token == 738561
    assert ongc.instrument_token == 5633
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_kite_instruments.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies.kite_instruments'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/companies/kite_instruments.py`:

```python
import csv

import httpx
from sqlalchemy.orm import Session

from app.models import Company

INSTRUMENTS_URL = "https://api.kite.trade/instruments"

# Kite's own suffix-free "exchange" column value -> the ".NS"/".BO" ticker
# suffix this codebase already uses (see nifty_indices_seed.py / test fixtures
# like "500325.BO"). Only cash-equity NSE/BSE rows are relevant here --
# futures/options segments (NFO-FUT, NFO-OPT, MCX-FUT, ...) never match a
# Company row.
_EXCHANGE_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}


def fetch_kite_instruments() -> list[dict]:
    """Fetch Zerodha's public instrument dump (no auth required) and return
    only NSE/BSE cash-equity rows. Raises on any HTTP failure -- this is a
    one-off/periodic maintenance script's data source, not a request-path
    call, so "fail loudly" is correct here (unlike price_series.py's
    request-path degrade-to-None contract).
    """
    response = httpx.get(INSTRUMENTS_URL, timeout=30.0)
    response.raise_for_status()
    reader = csv.DictReader(response.text.splitlines())
    return [
        row for row in reader
        if row["exchange"] in _EXCHANGE_SUFFIX and row["instrument_type"] == "EQ"
    ]


def match_instrument_tokens(session: Session, rows: list[dict]) -> int:
    """Set ``Company.instrument_token`` for every company whose ticker
    matches a row's ``tradingsymbol`` + the exchange's ticker suffix (e.g.
    "RELIANCE" on NSE -> "RELIANCE.NS"). Returns the number of companies
    updated; a row with no matching ticker is silently skipped -- that
    company's instrument_token simply stays null (see live_price.py's
    "no token -> not available" degrade path).
    """
    updated = 0
    for row in rows:
        suffix = _EXCHANGE_SUFFIX.get(row["exchange"])
        if suffix is None:
            continue
        ticker = f"{row['tradingsymbol']}{suffix}"
        company = session.query(Company).filter_by(ticker=ticker).one_or_none()
        if company is None:
            continue
        company.instrument_token = int(row["instrument_token"])
        updated += 1
    session.commit()
    return updated
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_kite_instruments.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies/kite_instruments.py backend/tests/test_kite_instruments.py
git commit -m "feat: add Kite instrument-token fetch + matching against existing companies"
```

---

### Task 3: Standalone seed script

**Files:**
- Create: `backend/seed_kite_instrument_tokens.py`

**Interfaces:**
- Consumes: `fetch_kite_instruments`, `match_instrument_tokens` (Task 2), `SessionLocal`, `init_db` (existing, `app/db.py`).

- [ ] **Step 1: Write the script**

Create `backend/seed_kite_instrument_tokens.py` (mirrors the existing `backend/seed_nifty_indices.py` convention exactly):

```python
from app.companies.kite_instruments import fetch_kite_instruments, match_instrument_tokens
from app.db import SessionLocal, init_db

if __name__ == "__main__":
    init_db()
    session = SessionLocal()
    try:
        rows = fetch_kite_instruments()
        updated = match_instrument_tokens(session, rows)
        print(f"Matched instrument_token for {updated} companies out of {len(rows)} Kite equity rows")
    finally:
        session.close()
```

This has no dedicated test file — it is a thin composition of two already-tested functions (`backend/seed_nifty_indices.py` has none either, for the same reason).

- [ ] **Step 2: Verify it imports cleanly**

Run: `.venv/Scripts/python.exe -c "import ast; ast.parse(open('seed_kite_instrument_tokens.py').read())"` (from `backend/`)
Expected: no output (parses without a `SyntaxError`)

- [ ] **Step 3: Commit**

```bash
git add backend/seed_kite_instrument_tokens.py
git commit -m "feat: add standalone script to backfill Kite instrument tokens"
```

---

### Task 4: Kite binary tick decoder

**Files:**
- Create: `backend/app/prices/__init__.py` (empty)
- Create: `backend/app/prices/kite_ticks.py`
- Test: `backend/tests/test_kite_ticks.py`

**Interfaces:**
- Produces: `decode_ticks(payload: bytes) -> list[dict]` (each dict: `{"instrument_token": int, "ltp": float}`), `update_cache(cache: dict[int, dict], ticks: list[dict], now) -> None`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_kite_ticks.py`:

```python
import struct
from datetime import datetime, timezone

from app.prices.kite_ticks import decode_ticks, update_cache


def _packet(instrument_token: int, ltp_rupees: float, extra_bytes: int = 0) -> bytes:
    """Build one Kite tick packet: instrument_token(4) + ltp-in-paise(4) +
    optional zero-filled padding (simulating the extra fields a "quote"/"full"
    mode packet carries after the first 8 bytes, which the decoder must
    ignore)."""
    return struct.pack(">Ii", instrument_token, round(ltp_rupees * 100)) + b"\x00" * extra_bytes


def _message(*packets: bytes) -> bytes:
    header = struct.pack(">H", len(packets))
    body = b"".join(struct.pack(">H", len(p)) + p for p in packets)
    return header + body


def test_decode_ticks_single_ltp_packet():
    message = _message(_packet(738561, 2500.50))

    ticks = decode_ticks(message)

    assert ticks == [{"instrument_token": 738561, "ltp": 2500.50}]


def test_decode_ticks_multiple_packets():
    message = _message(_packet(738561, 2500.50), _packet(5633, 150.25))

    ticks = decode_ticks(message)

    assert ticks == [
        {"instrument_token": 738561, "ltp": 2500.50},
        {"instrument_token": 5633, "ltp": 150.25},
    ]


def test_decode_ticks_ignores_bytes_past_the_first_eight_in_a_quote_packet():
    # A 44-byte "quote" mode packet -- decoder must still read only the
    # leading instrument_token+ltp and ignore the other 36 bytes.
    message = _message(_packet(738561, 2500.50, extra_bytes=36))

    ticks = decode_ticks(message)

    assert ticks == [{"instrument_token": 738561, "ltp": 2500.50}]


def test_decode_ticks_returns_empty_list_for_too_short_payload():
    assert decode_ticks(b"") == []
    assert decode_ticks(b"\x00") == []


def test_decode_ticks_stops_gracefully_on_truncated_packet():
    # Claims 1 packet of length 8 but only 4 bytes follow.
    truncated = struct.pack(">H", 1) + struct.pack(">H", 8) + b"\x00\x00\x00\x00"

    assert decode_ticks(truncated) == []


def test_update_cache_stores_ltp_and_timestamp():
    cache: dict[int, dict] = {}
    now = datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc)

    update_cache(cache, [{"instrument_token": 738561, "ltp": 2500.50}], now)

    assert cache[738561] == {"ltp": 2500.50, "as_of": now}


def test_update_cache_overwrites_prior_value_for_same_token():
    cache = {738561: {"ltp": 2400.0, "as_of": datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)}}
    now = datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc)

    update_cache(cache, [{"instrument_token": 738561, "ltp": 2500.50}], now)

    assert cache[738561]["ltp"] == 2500.50
    assert cache[738561]["as_of"] == now
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_kite_ticks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.prices'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/prices/__init__.py` (empty file).

Create `backend/app/prices/kite_ticks.py`:

```python
import struct


def decode_ticks(payload: bytes) -> list[dict]:
    """Decode one Kite WebSocket binary message into a list of
    ``{"instrument_token": int, "ltp": float}``.

    Wire format (all big-endian): 2-byte packet count, then per packet a
    2-byte length prefix followed by that many bytes. Every packet mode
    (ltp=8 bytes, quote=44 bytes, full=184 bytes) shares the same first 8
    bytes -- 4-byte instrument_token, then 4-byte last_traded_price in paise
    (divide by 100 for rupees) -- so one decode path reads just those 8
    bytes and ignores anything past them, regardless of packet length.

    Never raises -- a malformed/truncated payload (a dropped byte mid-frame,
    a corrupted relay hop) yields whatever packets parsed cleanly before the
    truncation, matching this codebase's "degrade, don't crash" convention
    for anything on a live external-feed path.
    """
    if len(payload) < 2:
        return []
    num_packets = struct.unpack_from(">H", payload, 0)[0]
    ticks = []
    offset = 2
    for _ in range(num_packets):
        if offset + 2 > len(payload):
            break
        packet_len = struct.unpack_from(">H", payload, offset)[0]
        offset += 2
        if offset + packet_len > len(payload) or packet_len < 8:
            break
        packet = payload[offset:offset + packet_len]
        offset += packet_len
        instrument_token = struct.unpack_from(">I", packet, 0)[0]
        ltp_paise = struct.unpack_from(">i", packet, 4)[0]
        ticks.append({"instrument_token": instrument_token, "ltp": ltp_paise / 100})
    return ticks


def update_cache(cache: dict[int, dict], ticks: list[dict], now) -> None:
    """Write each tick into ``cache`` keyed by instrument_token, overwriting
    any prior value -- the cache only ever holds the latest known price per
    instrument, never a history."""
    for tick in ticks:
        cache[tick["instrument_token"]] = {"ltp": tick["ltp"], "as_of": now}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_kite_ticks.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/prices/__init__.py backend/app/prices/kite_ticks.py backend/tests/test_kite_ticks.py
git commit -m "feat: add Kite binary tick decoder and in-memory price cache updater"
```

---

### Task 5: Kite hub WebSocket client

**Files:**
- Create: `backend/app/prices/kite_ws_client.py`
- Test: `backend/tests/test_kite_ws_client.py`

**Interfaces:**
- Consumes: `decode_ticks`, `update_cache` (Task 4).
- Produces: `handle_message(message, cache) -> None`, `async run_hub_client(hub_url, instrument_tokens, cache, connect=websockets.connect) -> None`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_kite_ws_client.py`:

```python
import json
import struct

import pytest

from app.prices.kite_ws_client import handle_message, run_hub_client


def _ltp_message(instrument_token: int, ltp_rupees: float) -> bytes:
    packet = struct.pack(">Ii", instrument_token, round(ltp_rupees * 100))
    return struct.pack(">H", 1) + struct.pack(">H", len(packet)) + packet


def test_handle_message_updates_cache_for_binary_tick():
    cache: dict[int, dict] = {}

    handle_message(_ltp_message(738561, 2500.50), cache)

    assert cache[738561]["ltp"] == 2500.50


def test_handle_message_ignores_text_frames():
    cache: dict[int, dict] = {}

    handle_message(json.dumps({"type": "auth_success"}), cache)

    assert cache == {}


class _FakeWebSocket:
    def __init__(self, messages):
        self._messages = messages
        self.sent = []

    async def send(self, data):
        self.sent.append(data)

    def __aiter__(self):
        return self._iter_messages()

    async def _iter_messages(self):
        for message in self._messages:
            yield message


def _fake_connect(messages_per_connection):
    """Build a fake replacement for ``websockets.connect`` -- an async
    generator function yielding one FakeWebSocket per entry in
    ``messages_per_connection``, exactly matching how ``async for websocket
    in websockets.connect(url):`` iterates real reconnecting connections."""
    async def connect(url):
        for messages in messages_per_connection:
            yield _FakeWebSocket(messages)
    return connect


@pytest.mark.asyncio
async def test_run_hub_client_subscribes_and_updates_cache():
    cache: dict[int, dict] = {}
    fake_connect = _fake_connect([[_ltp_message(738561, 2500.50)]])

    await run_hub_client("wss://fake-hub", [738561], cache, connect=fake_connect)

    assert cache[738561]["ltp"] == 2500.50


@pytest.mark.asyncio
async def test_run_hub_client_sends_subscribe_message_on_connect():
    cache: dict[int, dict] = {}
    sent_messages = []

    async def connect(url):
        ws = _FakeWebSocket([])
        yield ws
        sent_messages.extend(ws.sent)

    await run_hub_client("wss://fake-hub", [738561, 5633], cache, connect=connect)

    assert json.loads(sent_messages[0]) == {"a": "subscribe", "v": [738561, 5633]}


@pytest.mark.asyncio
async def test_run_hub_client_survives_a_connection_that_raises():
    cache: dict[int, dict] = {}

    async def connect(url):
        class _BoomWebSocket:
            async def send(self, data):
                raise ConnectionResetError("boom")

            def __aiter__(self):
                async def _gen():
                    return
                    yield  # pragma: no cover - never reached
                return _gen()
        yield _BoomWebSocket()
        yield _FakeWebSocket([_ltp_message(5633, 150.25)])

    await run_hub_client("wss://fake-hub", [738561], cache, connect=connect)

    assert cache[5633]["ltp"] == 150.25
```

This needs `pytest-asyncio` for the `@pytest.mark.asyncio` marker. Check first whether it's already installed:

Run: `.venv/Scripts/python.exe -c "import pytest_asyncio"` (from `backend/`)

If that raises `ModuleNotFoundError`, add it:

```bash
echo "pytest-asyncio" >> requirements.txt
.venv/Scripts/python.exe -m pip install pytest-asyncio
```

Then add asyncio mode to `backend/pytest.ini` (check its current contents first — if it already has an `[pytest]` section, add the line inside it rather than creating a second section):

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_kite_ws_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.prices.kite_ws_client'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/prices/kite_ws_client.py`:

```python
import json
import logging

import websockets

from app.models import utcnow
from app.prices.kite_ticks import decode_ticks, update_cache

logger = logging.getLogger(__name__)


def handle_message(message: str | bytes, cache: dict[int, dict]) -> None:
    """Route one incoming hub message: binary frames are Kite ticks (decoded
    and folded into ``cache``); text frames are the hub's own status
    messages (``auth_error``/``auth_success``) -- logged, not cached, since
    they carry no price data."""
    if not isinstance(message, bytes):
        logger.info("[kite-hub] status message: %s", message)
        return
    ticks = decode_ticks(message)
    update_cache(cache, ticks, utcnow())


async def run_hub_client(
    hub_url: str,
    instrument_tokens: list[int],
    cache: dict[int, dict],
    connect=websockets.connect,
) -> None:
    """Persistent client for the Zerodha tick-relay hub. Subscribes to every
    given instrument_token on each (re)connection and folds every incoming
    tick into ``cache``.

    ``connect`` defaults to the real ``websockets.connect``, whose reconnect
    behavior (``async for websocket in websockets.connect(url): ...``)
    already retries with backoff on disconnect -- this function relies on
    that built-in reconnect loop rather than implementing its own. Tests
    substitute a fake async-generator ``connect`` that yields a fixed
    sequence of fake connections instead of retrying forever.

    Any error on one connection (send failure, decode error, the hub
    closing) is caught and logged so the outer reconnect loop keeps going --
    a hub outage degrades the live-price feature, it never crashes the
    caller.
    """
    async for websocket in connect(hub_url):
        try:
            await websocket.send(json.dumps({"a": "subscribe", "v": instrument_tokens}))
            async for message in websocket:
                handle_message(message, cache)
        except Exception:
            logger.exception("[kite-hub] connection error, will reconnect")
            continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_kite_ws_client.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full backend suite to confirm no regressions**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass (the pre-existing count plus the new ones)

- [ ] **Step 6: Commit**

```bash
git add backend/app/prices/kite_ws_client.py backend/tests/test_kite_ws_client.py backend/requirements.txt backend/pytest.ini
git commit -m "feat: add persistent Kite hub WebSocket client with auto-reconnect"
```

---

### Task 6: Live-price compute helpers + shared cache

**Files:**
- Create: `backend/app/prices/live_price.py`
- Test: `backend/tests/test_live_price.py`

**Interfaces:**
- Produces: `LIVE_PRICE_CACHE: dict[int, dict]` (module-level, shared singleton), `get_previous_close(points: list[dict]) -> float | None`, `compute_change_pct(ltp: float, previous_close: float | None) -> float | None`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_live_price.py`:

```python
from datetime import datetime, timezone

from app.prices.live_price import compute_change_pct, get_previous_close


def test_get_previous_close_returns_last_close_strictly_before_today(monkeypatch):
    monkeypatch.setattr(
        "app.prices.live_price._today",
        lambda: "2026-07-15",
    )
    points = [
        {"date": "2026-07-13", "close": 100.0},
        {"date": "2026-07-14", "close": 105.0},
        {"date": "2026-07-15", "close": 110.0},  # today -- not "previous"
    ]

    assert get_previous_close(points) == 105.0


def test_get_previous_close_falls_back_to_last_point_if_none_before_today(monkeypatch):
    monkeypatch.setattr(
        "app.prices.live_price._today",
        lambda: "2026-07-10",
    )
    points = [{"date": "2026-07-15", "close": 110.0}]  # all "today or later" relative to fake _today

    assert get_previous_close(points) == 110.0


def test_get_previous_close_returns_none_for_empty_points():
    assert get_previous_close([]) is None


def test_compute_change_pct_positive_move():
    assert compute_change_pct(ltp=110.0, previous_close=100.0) == 10.0


def test_compute_change_pct_negative_move():
    assert compute_change_pct(ltp=90.0, previous_close=100.0) == -10.0


def test_compute_change_pct_returns_none_without_a_previous_close():
    assert compute_change_pct(ltp=110.0, previous_close=None) is None


def test_compute_change_pct_returns_none_for_zero_previous_close():
    assert compute_change_pct(ltp=110.0, previous_close=0.0) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_live_price.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.prices.live_price'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/prices/live_price.py`:

```python
from datetime import datetime, timezone

# Shared, process-wide cache written by kite_ws_client.run_hub_client and
# read by the /live-price endpoint -- a plain module-level dict (like
# app/ws/manager.py's `manager` singleton) rather than a class instance,
# since there is exactly one cache for the whole process.
LIVE_PRICE_CACHE: dict[int, dict] = {}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def get_previous_close(points: list[dict]) -> float | None:
    """The most recent close strictly before today, from a list of
    ``{"date": "YYYY-MM-DD", "close": float}`` points (as returned by
    ``fetch_price_series``). Falls back to the single most recent point if
    every point is dated today or later (e.g. a short lookback window
    fetched right at/after today's first print). ``None`` for an empty list.
    """
    if not points:
        return None
    today = _today()
    before_today = [p for p in points if p["date"] < today]
    if before_today:
        return before_today[-1]["close"]
    return points[-1]["close"]


def compute_change_pct(ltp: float, previous_close: float | None) -> float | None:
    """Percent change of ``ltp`` versus ``previous_close``. ``None`` if
    there's no previous close to compare against, or it's zero (division
    would be undefined/meaningless)."""
    if not previous_close:
        return None
    return (ltp - previous_close) / previous_close * 100
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_live_price.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/prices/live_price.py backend/tests/test_live_price.py
git commit -m "feat: add previous-close/change-pct helpers and shared live-price cache"
```

---

### Task 7: Config setting + startup wiring

**Files:**
- Modify: `backend/app/config.py` (add one field)
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_main_startup.py`

**Interfaces:**
- Consumes: `run_hub_client` (Task 5), `LIVE_PRICE_CACHE` (Task 6), `Company` (Task 1), `SessionLocal` (existing).
- Produces: `settings.zerodha_hub_url: str`, `_start_hub_client_if_configured() -> None` (importable from `app.main` for the test).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_main_startup.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_main_startup.py -v`
Expected: FAIL — `settings.zerodha_hub_url` doesn't exist (`AttributeError` when monkeypatch.setattr targets a nonexistent attribute — pytest's `monkeypatch.setattr` raises `AttributeError` by default unless the attribute already exists, so this fails immediately)

- [ ] **Step 3: Write minimal implementation**

In `backend/app/config.py`, add one field to the `Settings` class (after `brandfetch_client_id`):

```python
    brandfetch_client_id: str = os.environ.get("BRANDFETCH_CLIENT_ID", "")
    # Empty disables the live-price feature entirely (same convention as
    # brandfetch_client_id) -- local dev/CI never opens an outbound
    # WebSocket connection unless this is explicitly set.
    zerodha_hub_url: str = os.environ.get("ZERODHA_HUB_URL", "")
```

In `backend/app/main.py`, currently:

```python
import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from app.config import settings
from app.db import init_db
from app.routers import alerts, articles, auth, categories, companies, holdings, translation, watchlist, ws
from app.scheduler import start_scheduler
from app.ws.manager import manager

app = FastAPI(title="NewsFlo")

app.include_router(articles.router)
app.include_router(alerts.router)
app.include_router(auth.router)
app.include_router(holdings.router)
app.include_router(companies.router)
app.include_router(categories.router)
app.include_router(watchlist.router)
app.include_router(translation.router)
app.include_router(ws.router)

init_db()

if settings.enable_scheduler:
    start_scheduler()


@app.on_event("startup")
async def _capture_event_loop() -> None:
    # Capture the running loop so the synchronous pipeline can schedule async
    # broadcasts onto it from a worker thread via run_coroutine_threadsafe.
    manager.loop = asyncio.get_running_loop()


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
```

Change to:

```python
import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Company
from app.prices.kite_ws_client import run_hub_client
from app.prices.live_price import LIVE_PRICE_CACHE
from app.routers import alerts, articles, auth, categories, companies, holdings, translation, watchlist, ws
from app.scheduler import start_scheduler
from app.ws.manager import manager

app = FastAPI(title="NewsFlo")

app.include_router(articles.router)
app.include_router(alerts.router)
app.include_router(auth.router)
app.include_router(holdings.router)
app.include_router(companies.router)
app.include_router(categories.router)
app.include_router(watchlist.router)
app.include_router(translation.router)
app.include_router(ws.router)

init_db()

if settings.enable_scheduler:
    start_scheduler()


def _start_hub_client_if_configured() -> None:
    """Kick off the persistent Zerodha hub client if a hub URL is
    configured. Extracted from the startup event so it can be unit-tested
    without spinning up the whole ASGI lifespan."""
    if not settings.zerodha_hub_url:
        return
    db = SessionLocal()
    try:
        instrument_tokens = [
            row[0] for row in
            db.query(Company.instrument_token).filter(Company.instrument_token.isnot(None)).all()
        ]
    finally:
        db.close()
    asyncio.create_task(run_hub_client(settings.zerodha_hub_url, instrument_tokens, LIVE_PRICE_CACHE))


@app.on_event("startup")
async def _capture_event_loop() -> None:
    # Capture the running loop so the synchronous pipeline can schedule async
    # broadcasts onto it from a worker thread via run_coroutine_threadsafe.
    manager.loop = asyncio.get_running_loop()
    _start_hub_client_if_configured()


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_main_startup.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full backend suite to confirm no regressions**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/app/main.py backend/tests/test_main_startup.py
git commit -m "feat: wire Zerodha hub client startup behind ZERODHA_HUB_URL config"
```

---

### Task 8: `/live-price` endpoint

**Files:**
- Modify: `backend/app/routers/companies.py`
- Test: `backend/tests/test_companies_api.py`

**Interfaces:**
- Consumes: `LIVE_PRICE_CACHE`, `compute_change_pct`, `get_previous_close` (Task 6), `fetch_price_series` (existing, `app/companies/price_series.py`), `_get_indian_company_or_404` (existing, same file).
- Produces: `GET /api/companies/{company_id}/live-price` → `{"ltp": float | None, "change_pct": float | None, "as_of": str | None, "available": bool}`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_companies_api.py` (near the other `/prices` tests):

```python
def test_get_company_live_price_unavailable_when_no_instrument_token(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    client = TestClient(app)

    body = client.get(f"/api/companies/{company.id}/live-price").json()

    assert body == {"ltp": None, "change_pct": None, "as_of": None, "available": False}
    app.dependency_overrides.clear()


def test_get_company_live_price_unavailable_when_no_tick_cached_yet(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(
        ticker="RELIANCE.NS", name="Reliance", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1.0, instrument_token=738561,
    )
    db_session.add(company)
    db_session.commit()
    client = TestClient(app)

    body = client.get(f"/api/companies/{company.id}/live-price").json()

    assert body == {"ltp": None, "change_pct": None, "as_of": None, "available": False}
    app.dependency_overrides.clear()


def test_get_company_live_price_returns_cached_tick_with_change_pct(db_session, monkeypatch):
    from datetime import datetime, timezone
    from app.prices.live_price import LIVE_PRICE_CACHE
    from app.routers import companies as companies_router

    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(
        ticker="RELIANCE.NS", name="Reliance", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1.0, instrument_token=738561,
    )
    db_session.add(company)
    db_session.commit()
    as_of = datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc)
    LIVE_PRICE_CACHE[738561] = {"ltp": 2530.0, "as_of": as_of}
    monkeypatch.setattr(
        companies_router, "fetch_price_series",
        lambda ticker, period: [{"date": "2026-07-14", "close": 2500.0}],
    )
    client = TestClient(app)

    body = client.get(f"/api/companies/{company.id}/live-price").json()

    assert body["ltp"] == 2530.0
    assert body["available"] is True
    assert body["as_of"] == as_of.isoformat()
    assert body["change_pct"] == pytest.approx(1.2)
    LIVE_PRICE_CACHE.clear()
    app.dependency_overrides.clear()


def test_get_company_live_price_404_for_global_company(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market_cap=None)
    db_session.add(company)
    db_session.commit()
    client = TestClient(app)

    resp = client.get(f"/api/companies/{company.id}/live-price")

    assert resp.status_code == 404
    app.dependency_overrides.clear()
```

Add `import pytest` at the top of `backend/tests/test_companies_api.py` if it isn't already imported (check the file's existing imports first).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_companies_api.py -k live_price -v`
Expected: FAIL with `404 Not Found` for all four (the route doesn't exist yet, so every request hits FastAPI's default 404 — that also happens to match the one test that *expects* 404, so watch for that: 3 of the 4 should fail, 1 (`test_get_company_live_price_404_for_global_company`) passes for the wrong reason. Both outcomes confirm the route is missing.)

- [ ] **Step 3: Write minimal implementation**

In `backend/app/routers/companies.py`, add these imports (alongside the existing ones):

```python
from app.prices.live_price import LIVE_PRICE_CACHE, compute_change_pct, get_previous_close
```

Add this endpoint at the end of the file, after `get_company_prices`:

```python
@router.get("/{company_id}/live-price")
def get_company_live_price(company_id: int, db: Session = Depends(get_db)):
    company = _get_indian_company_or_404(db, company_id)
    entry = LIVE_PRICE_CACHE.get(company.instrument_token) if company.instrument_token else None
    if entry is None:
        return {"ltp": None, "change_pct": None, "as_of": None, "available": False}

    points = fetch_price_series(company.ticker, "5d") or []
    previous_close = get_previous_close(points)
    return {
        "ltp": entry["ltp"],
        "change_pct": compute_change_pct(entry["ltp"], previous_close),
        "as_of": entry["as_of"].isoformat(),
        "available": True,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_companies_api.py -v`
Expected: PASS (all tests in the file, including the 4 new ones)

- [ ] **Step 5: Run the full backend suite to confirm no regressions**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/companies.py backend/tests/test_companies_api.py
git commit -m "feat: add GET /api/companies/{id}/live-price endpoint"
```

---

### Task 9: Frontend `getCompanyLivePrice` API client

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/src/lib/api.test.ts`

**Interfaces:**
- Produces: `interface LivePrice { ltp: number | null; change_pct: number | null; as_of: string | null; available: boolean }`, `getCompanyLivePrice(id: number): Promise<LivePrice>`.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/lib/api.test.ts` (add `getCompanyLivePrice` to the existing import list from `./api`, then add this test near the other `getCompany*` tests):

```ts
  it('getCompanyLivePrice fetches the live-price endpoint', async () => {
    const fetchMock = mockFetchOnce({ ltp: 2530.0, change_pct: 1.2, as_of: '2026-07-15T09:30:00+00:00', available: true });
    const result = await getCompanyLivePrice(1);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/companies/1/live-price');
    expect(result.ltp).toBe(2530.0);
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/lib/api.test.ts` (from `frontend/`)
Expected: FAIL with `TypeError: getCompanyLivePrice is not a function`

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/lib/api.ts`, add this interface after `PriceSeries` (around line 162):

```ts
export interface LivePrice {
  ltp: number | null;
  change_pct: number | null;
  as_of: string | null;
  available: boolean;
}
```

Add this function after `getCompanyPrices` (around line 221):

```ts
export async function getCompanyLivePrice(id: number): Promise<LivePrice> {
  const res = await fetch(`/api/companies/${id}/live-price`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as LivePrice;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/lib/api.test.ts`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/api.test.ts
git commit -m "feat: add getCompanyLivePrice API client function"
```

---

### Task 10: `nearestPointIndex` pure function

**Files:**
- Modify: `frontend/src/features/visualize/priceChartLayout.ts`
- Test: `frontend/src/features/visualize/priceChartLayout.test.ts`

**Interfaces:**
- Consumes: `ChartCoord` (existing, same file).
- Produces: `nearestPointIndex(points: ChartCoord[], x: number): number`.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/features/visualize/priceChartLayout.test.ts` (add `nearestPointIndex` to the existing import from `./priceChartLayout`):

```ts
describe('nearestPointIndex', () => {
  const coords = [{ x: 0, y: 10 }, { x: 50, y: 20 }, { x: 100, y: 30 }];

  it('returns the index of the closest point to x', () => {
    expect(nearestPointIndex(coords, 5)).toBe(0);
    expect(nearestPointIndex(coords, 48)).toBe(1);
    expect(nearestPointIndex(coords, 96)).toBe(2);
  });

  it('picks the earlier index on an exact tie', () => {
    expect(nearestPointIndex(coords, 25)).toBe(0);
  });

  it('clamps to the last index for an x beyond the final point', () => {
    expect(nearestPointIndex(coords, 500)).toBe(2);
  });

  it('clamps to the first index for a negative x', () => {
    expect(nearestPointIndex(coords, -50)).toBe(0);
  });

  it('returns 0 for an empty points array', () => {
    expect(nearestPointIndex([], 10)).toBe(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/features/visualize/priceChartLayout.test.ts` (from `frontend/`)
Expected: FAIL with `TypeError: nearestPointIndex is not a function`

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/features/visualize/priceChartLayout.ts`, add after `layoutPriceChart`:

```ts
export function nearestPointIndex(points: ChartCoord[], x: number): number {
  if (points.length === 0) return 0;
  let closestIndex = 0;
  let closestDistance = Infinity;
  points.forEach((point, i) => {
    const distance = Math.abs(point.x - x);
    if (distance < closestDistance) {
      closestDistance = distance;
      closestIndex = i;
    }
  });
  return closestIndex;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/features/visualize/priceChartLayout.test.ts`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/priceChartLayout.ts frontend/src/features/visualize/priceChartLayout.test.ts
git commit -m "feat: add nearestPointIndex pure function for chart crosshair lookup"
```

---

### Task 11: `PriceChart` crosshair/tooltip interactivity

**Files:**
- Modify: `frontend/src/features/visualize/PriceChart.tsx`
- Test: `frontend/src/features/visualize/PriceChart.test.tsx`

**Interfaces:**
- Consumes: `nearestPointIndex` (Task 10), `layoutPriceChart` (existing, same file), `PricePoint` (existing, `lib/api.ts`).
- Produces: `PriceChart` renders a `data-testid="chart-tooltip"` element with the hovered point's price/date when the pointer is over the chart.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/features/visualize/PriceChart.test.tsx`:

```tsx
  it('shows a tooltip with the price and date of the nearest point on mouse move', () => {
    const points: PricePoint[] = [
      { date: '2026-07-13', close: 100 },
      { date: '2026-07-14', close: 105 },
      { date: '2026-07-15', close: 95 },
    ];
    const { container } = render(<PriceChart points={points} unavailableLabel="Chart unavailable" />);
    const svg = container.querySelector('svg')!;
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ left: 0, width: 300, top: 0, height: 100, right: 300, bottom: 100, x: 0, y: 0, toJSON: () => ({}) });

    fireEvent.mouseMove(svg, { clientX: 150 });

    expect(screen.getByTestId('chart-tooltip')).toHaveTextContent('105');
    expect(screen.getByTestId('chart-tooltip')).toHaveTextContent('Jul 14');
  });

  it('hides the tooltip when the pointer leaves the chart', () => {
    const points: PricePoint[] = [
      { date: '2026-07-13', close: 100 },
      { date: '2026-07-14', close: 105 },
    ];
    const { container } = render(<PriceChart points={points} unavailableLabel="Chart unavailable" />);
    const svg = container.querySelector('svg')!;
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ left: 0, width: 300, top: 0, height: 100, right: 300, bottom: 100, x: 0, y: 0, toJSON: () => ({}) });
    fireEvent.mouseMove(svg, { clientX: 150 });
    expect(screen.queryByTestId('chart-tooltip')).toBeInTheDocument();

    fireEvent.mouseLeave(svg);

    expect(screen.queryByTestId('chart-tooltip')).not.toBeInTheDocument();
  });

  it('shows the tooltip on touch move', () => {
    const points: PricePoint[] = [
      { date: '2026-07-13', close: 100 },
      { date: '2026-07-14', close: 105 },
    ];
    const { container } = render(<PriceChart points={points} unavailableLabel="Chart unavailable" />);
    const svg = container.querySelector('svg')!;
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ left: 0, width: 300, top: 0, height: 100, right: 300, bottom: 100, x: 0, y: 0, toJSON: () => ({}) });

    fireEvent.touchStart(svg, { touches: [{ clientX: 10 }] });

    expect(screen.getByTestId('chart-tooltip')).toHaveTextContent('100');
  });
```

Add `fireEvent` to the existing `@testing-library/react` import at the top of the file, and `vi` from `vitest` if not already imported (check the file's current imports first).

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/features/visualize/PriceChart.test.tsx` (from `frontend/`)
Expected: FAIL — `screen.getByTestId('chart-tooltip')` throws (element not found)

- [ ] **Step 3: Write minimal implementation**

Replace the full contents of `frontend/src/features/visualize/PriceChart.tsx` with:

```tsx
import { useRef, useState } from 'react';
import type { PricePoint } from '../../lib/api';
import { layoutPriceChart, nearestPointIndex } from './priceChartLayout';

const WIDTH = 300;
const HEIGHT = 100;
const PADDING_Y = 8; // keeps the line off the top/bottom edge of the viewBox

function formatTooltipDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export default function PriceChart({
  points,
  unavailableLabel,
}: {
  points: PricePoint[];
  unavailableLabel: string;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const layout = layoutPriceChart(points, WIDTH, HEIGHT - PADDING_Y * 2);

  if (!layout) {
    return <p className="text-xs text-muted">{unavailableLabel}</p>;
  }

  function updateHoverFromClientX(clientX: number) {
    const svg = svgRef.current;
    if (!svg || !layout) return;
    const rect = svg.getBoundingClientRect();
    const relativeX = ((clientX - rect.left) / rect.width) * WIDTH;
    setHoverIndex(nearestPointIndex(layout.points, relativeX));
  }

  const strokeClass = layout.trend === 'bullish' ? 'stroke-bullish' : 'stroke-bearish';
  const polylinePoints = layout.points.map((p) => `${p.x},${p.y + PADDING_Y}`).join(' ');
  const hovered = hoverIndex !== null ? { coord: layout.points[hoverIndex], point: points[hoverIndex] } : null;

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        role="img"
        aria-label={`Price chart, ${layout.trend}`}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-24 w-full"
        onMouseMove={(e) => updateHoverFromClientX(e.clientX)}
        onMouseLeave={() => setHoverIndex(null)}
        onTouchStart={(e) => updateHoverFromClientX(e.touches[0].clientX)}
        onTouchMove={(e) => updateHoverFromClientX(e.touches[0].clientX)}
      >
        <polyline points={polylinePoints} fill="none" strokeWidth={2} className={strokeClass} />
        {hovered && (
          <line
            x1={hovered.coord.x}
            x2={hovered.coord.x}
            y1={0}
            y2={HEIGHT}
            className="stroke-muted"
            strokeWidth={1}
            strokeDasharray="2,2"
          />
        )}
      </svg>
      {hovered && (
        <div
          data-testid="chart-tooltip"
          className="pointer-events-none absolute top-0 rounded-md border border-hairline bg-surface px-2 py-1 text-xs text-ink shadow-sm"
          style={{ left: `${(hovered.coord.x / WIDTH) * 100}%` }}
        >
          {formatTooltipDate(hovered.point.date)} · {hovered.point.close.toFixed(2)}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/features/visualize/PriceChart.test.tsx`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/PriceChart.tsx frontend/src/features/visualize/PriceChart.test.tsx
git commit -m "feat: add crosshair tooltip interactivity to PriceChart"
```

---

### Task 12: `LivePriceReadout` component

**Files:**
- Create: `frontend/src/components/LivePriceReadout.tsx`
- Test: `frontend/src/components/LivePriceReadout.test.tsx`
- Modify: `frontend/src/lib/i18n.ts` (one new key)

**Interfaces:**
- Consumes: `LivePrice` (Task 9), `useLanguage` (existing, `lib/language.tsx`).
- Produces: `<LivePriceReadout price={livePrice} />`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/LivePriceReadout.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import LivePriceReadout from './LivePriceReadout';
import { LanguageProvider } from '../lib/language';
import type { LivePrice } from '../lib/api';

function renderWithLanguage(price: LivePrice) {
  return render(
    <LanguageProvider>
      <LivePriceReadout price={price} />
    </LanguageProvider>,
  );
}

describe('LivePriceReadout', () => {
  it('shows the price and a positive change badge', () => {
    renderWithLanguage({ ltp: 2530.5, change_pct: 1.2, as_of: '2026-07-15T09:30:00+00:00', available: true });
    expect(screen.getByText('₹2530.50')).toBeInTheDocument();
    expect(screen.getByText('+1.20%')).toBeInTheDocument();
  });

  it('shows a negative change badge in bearish styling', () => {
    renderWithLanguage({ ltp: 2470.0, change_pct: -1.2, as_of: '2026-07-15T09:30:00+00:00', available: true });
    expect(screen.getByText('-1.20%')).toHaveClass('text-bearish');
  });

  it('shows an unavailable message when available is false', () => {
    renderWithLanguage({ ltp: null, change_pct: null, as_of: null, available: false });
    expect(screen.getByText('Price unavailable right now.')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/LivePriceReadout.test.tsx` (from `frontend/`)
Expected: FAIL — cannot find module `./LivePriceReadout`

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/lib/i18n.ts`, add one new key (near the other `company.*` keys, e.g. right after `company.chartUnavailable`):

```ts
  'company.livePriceUnavailable': {
    en: 'Price unavailable right now.', hi: 'अभी मूल्य उपलब्ध नहीं है।', mr: 'सध्या किंमत उपलब्ध नाही.',
    gu: 'હાલમાં ભાવ ઉપલબ્ધ નથી.', ml: 'ഇപ്പോൾ വില ലഭ്യമല്ല.', te: 'ప్రస్తుతం ధర అందుబాటులో లేదు.',
    ta: 'இப்போது விலை கிடைக்கவில்லை.', kn: 'ಈಗ ಬೆಲೆ ಲಭ್ಯವಿಲ್ಲ.', pa: 'ਹੁਣ ਕੀਮਤ ਉਪਲਬਧ ਨਹੀਂ ਹੈ।',
    bn: 'এখন মূল্য পাওয়া যাচ্ছে না।',
  },
```

Create `frontend/src/components/LivePriceReadout.tsx`:

```tsx
import type { LivePrice } from '../lib/api';
import { useLanguage } from '../lib/language';

export default function LivePriceReadout({ price }: { price: LivePrice }) {
  const { t } = useLanguage();

  if (!price.available || price.ltp === null) {
    return <p className="text-xs text-muted">{t('company.livePriceUnavailable')}</p>;
  }

  const changePct = price.change_pct;
  const bullish = (changePct ?? 0) >= 0;

  return (
    <div className="flex items-baseline gap-2">
      <span className="font-display text-3xl font-bold text-ink">₹{price.ltp.toFixed(2)}</span>
      {changePct !== null && (
        <span className={`text-sm ${bullish ? 'text-bullish' : 'text-bearish'}`}>
          {bullish ? '+' : ''}
          {changePct.toFixed(2)}%
        </span>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/LivePriceReadout.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/LivePriceReadout.tsx frontend/src/components/LivePriceReadout.test.tsx frontend/src/lib/i18n.ts
git commit -m "feat: add LivePriceReadout component"
```

---

### Task 13: Wire live price into `CompanyPage`

**Files:**
- Modify: `frontend/src/pages/CompanyPage.tsx`
- Test: `frontend/src/pages/CompanyPage.test.tsx`

**Interfaces:**
- Consumes: `getCompanyLivePrice` (Task 9), `LivePriceReadout` (Task 12), `LivePrice` (Task 9).

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/CompanyPage.test.tsx` (add `getCompanyLivePrice` to the mocked-per-test API spies where needed, and extend `mockHistoryAndPrices` or add a new helper):

```tsx
  it('shows the live price readout once it loads, and polls again after 20s', async () => {
    vi.spyOn(api, 'getCompanyProfile').mockResolvedValue(baseProfile);
    vi.spyOn(api, 'getCompanyHistory').mockResolvedValue({ mentions: [], has_more: false });
    vi.spyOn(api, 'getCompanyPrices').mockResolvedValue({ period: '6mo', points: [{ date: '2026-07-14', close: 2500 }], available: true });
    const liveSpy = vi.spyOn(api, 'getCompanyLivePrice').mockResolvedValue({
      ltp: 2530, change_pct: 1.2, as_of: '2026-07-15T09:30:00+00:00', available: true,
    });

    renderPage();
    // Real timers for the initial render/fetch -- findByText's internal
    // polling would deadlock under fake timers unless they're advanced in
    // lockstep, which is needless complexity for "did the first call happen".
    expect(await screen.findByText('₹2530.00')).toBeInTheDocument();
    expect(liveSpy).toHaveBeenCalledTimes(1);

    // Switch to fake timers only to force the interval's second tick.
    // advanceTimersByTimeAsync also flushes the microtask queue as it
    // advances, so the mocked promise from the second poll() call resolves
    // within this same await instead of needing a separate waitFor.
    vi.useFakeTimers();
    await vi.advanceTimersByTimeAsync(20000);
    vi.useRealTimers();

    expect(liveSpy).toHaveBeenCalledTimes(2);
  });

  it("appends today's live price as the chart's last point when the historical series ends before today", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-15T10:00:00Z'));
    vi.spyOn(api, 'getCompanyProfile').mockResolvedValue(baseProfile);
    vi.spyOn(api, 'getCompanyHistory').mockResolvedValue({ mentions: [], has_more: false });
    vi.spyOn(api, 'getCompanyPrices').mockResolvedValue({ period: '6mo', points: [{ date: '2026-07-14', close: 2500 }], available: true });
    vi.spyOn(api, 'getCompanyLivePrice').mockResolvedValue({
      ltp: 2530, change_pct: 1.2, as_of: '2026-07-15T09:30:00+00:00', available: true,
    });

    renderPage();
    // Flush the initial mount's pending promises without relying on
    // findByText/waitFor, which poll via setTimeout and would hang under
    // fake timers -- advancing by 0ms still drains the microtask queue.
    await vi.advanceTimersByTimeAsync(0);

    expect(screen.getByText('₹2530.00')).toBeInTheDocument();
    // Historical series ends 2026-07-14; system time is 2026-07-15, so
    // withLivePoint must have appended (not replaced) a new point --
    // 2500 -> 2530 reads as bullish only if that append happened.
    expect(screen.getByRole('img', { name: /price chart, bullish/i })).toBeInTheDocument();

    vi.useRealTimers();
  });
```

This needs `getCompanyLivePrice` added to the file's existing `import * as api from '../lib/api'` usage (already imported as a namespace, so no import list change needed) — just confirm the top of the test file uses `import * as api from '../lib/api';` (it already does, per the existing `vi.spyOn(api, 'getCompanyProfile')` calls).

The `CompanyPage` implementation below adds a `.catch(() => {})` to the live-price poll, so any test that doesn't mock `getCompanyLivePrice` (every test in this file that predates this task) safely falls back to a real, rejected `fetch` call that's silently swallowed — the live-price readout just renders its "unavailable" state, which none of those tests assert on either way. Only update the shared `mockHistoryAndPrices` helper for cleanliness (avoids an unhandled-rejection console warning in every other test), not each test individually:

```ts
function mockHistoryAndPrices() {
  vi.spyOn(api, 'getCompanyHistory').mockResolvedValue({ mentions: [], has_more: false });
  vi.spyOn(api, 'getCompanyPrices').mockResolvedValue({ period: '6mo', points: [], available: false });
  vi.spyOn(api, 'getCompanyLivePrice').mockResolvedValue({ ltp: null, change_pct: null, as_of: null, available: false });
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/pages/CompanyPage.test.tsx` (from `frontend/`)
Expected: FAIL — `₹2530.00` never appears (the page doesn't fetch or render a live price yet)

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/pages/CompanyPage.tsx`, update the imports:

```tsx
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  getCompanyHistory,
  getCompanyLivePrice,
  getCompanyPrices,
  getCompanyProfile,
  type CompanyHistoryPage,
  type CompanyProfile,
  type LivePrice,
  type PricePeriod,
  type PriceSeries,
} from '../lib/api';
import type { TranslationKey } from '../lib/i18n';
import { useLanguage } from '../lib/language';
import { splitRationaleIntoPoints } from '../lib/reasoning';
import CompanyAvatar from '../components/CompanyAvatar';
import DirectionArrow from '../components/DirectionArrow';
import LivePriceReadout from '../components/LivePriceReadout';
import MentionRow from '../components/MentionRow';
import PriceChart from '../features/visualize/PriceChart';

const PERIODS: PricePeriod[] = ['1mo', '3mo', '6mo', '1y'];
const PERIOD_LABEL_KEY: Record<PricePeriod, TranslationKey> = {
  '1mo': 'company.period1mo',
  '3mo': 'company.period3mo',
  '6mo': 'company.period6mo',
  '1y': 'company.period1y',
};
const LIVE_PRICE_POLL_INTERVAL_MS = 20000;
```

Add a new state variable and polling effect right after the existing `prices`/`pricesError`/`period` state block:

```tsx
  const [livePrice, setLivePrice] = useState<LivePrice | null>(null);

  useEffect(() => {
    let active = true;
    setLivePrice(null);

    function poll() {
      // Deliberately no error state: a single missed poll shouldn't flip a
      // working readout to "unavailable" -- just keep the last known value
      // and let the next interval tick retry.
      getCompanyLivePrice(companyId)
        .then((price) => {
          if (active) setLivePrice(price);
        })
        .catch(() => {});
    }

    poll();
    const interval = setInterval(poll, LIVE_PRICE_POLL_INTERVAL_MS);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [companyId]);
```

Add a helper function above the component (after the `PERIOD_LABEL_KEY` constant) that merges the live price into the chart's points:

```tsx
function withLivePoint(points: { date: string; close: number }[], live: LivePrice): { date: string; close: number }[] {
  if (live.ltp === null) return points;
  const today = new Date().toISOString().slice(0, 10);
  if (points.length > 0 && points[points.length - 1].date === today) {
    return [...points.slice(0, -1), { date: today, close: live.ltp }];
  }
  return [...points, { date: today, close: live.ltp }];
}
```

In the chart section's JSX, change:

```tsx
        {pricesError ? (
          <p className="text-xs text-muted">{t('company.chartLoadFailed')}</p>
        ) : (
          <PriceChart points={prices?.points ?? []} unavailableLabel={t('company.chartUnavailable')} />
        )}
```

to:

```tsx
        <LivePriceReadout price={livePrice ?? { ltp: null, change_pct: null, as_of: null, available: false }} />
        {pricesError ? (
          <p className="text-xs text-muted">{t('company.chartLoadFailed')}</p>
        ) : (
          <PriceChart
            points={livePrice ? withLivePoint(prices?.points ?? [], livePrice) : (prices?.points ?? [])}
            unavailableLabel={t('company.chartUnavailable')}
          />
        )}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/pages/CompanyPage.test.tsx`
Expected: PASS (all tests in the file, including the pre-existing ones now updated with the `getCompanyLivePrice` mock)

- [ ] **Step 5: Run the full frontend suite and typecheck to confirm no regressions**

Run: `npx vitest run` (from `frontend/`)
Expected: all tests pass

Run: `npx tsc --noEmit` (from `frontend/`)
Expected: no output

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/CompanyPage.tsx frontend/src/pages/CompanyPage.test.tsx
git commit -m "feat: poll live price into CompanyPage and merge it into the chart's last point"
```

---

### Task 14: Manual verification

**Files:** none (verification only)

- [ ] **Step 1: Seed instrument tokens against local dev DB**

Run (from `backend/`): `.venv/Scripts/python.exe seed_kite_instrument_tokens.py`
Expected: prints `Matched instrument_token for N companies out of M Kite equity rows` with `N > 0`

- [ ] **Step 2: Set the hub URL and start the backend**

Set `ZERODHA_HUB_URL=wss://ws-hub-production-115e.up.railway.app` in `backend/.env` (or export it in the shell before starting uvicorn), then run the backend dev server and confirm the log shows no connection errors within a few seconds.

- [ ] **Step 3: Confirm the live-price endpoint responds**

For a company with a matched `instrument_token` (from Step 1), during NSE market hours (9:15am–3:30pm IST, Mon–Fri):

```bash
curl -s http://127.0.0.1:8000/api/companies/<id>/live-price
```

Expected: `"available": true` with a non-null `ltp` within ~30 seconds of startup (allowing time for the first tick to arrive).

- [ ] **Step 4: Confirm the frontend**

Start the frontend dev server, navigate to `/company/<id>` for that same company, and confirm: the live price readout shows a number and change badge, the price chart's last point matches it, and hovering/tapping the chart shows a tooltip with the date/price at that position.

- [ ] **Step 5: Commit (if any fixes were needed during manual verification)**

Only if Steps 1–4 surfaced a bug requiring a code change — otherwise this task has nothing to commit.

---

## Self-Review

**Spec coverage:**
- Instrument mapping → Tasks 1–3.
- Hub client + binary decode → Tasks 4–5.
- Live-price cache/compute + endpoint → Tasks 6, 8.
- Startup wiring gated on config → Task 7.
- Frontend live readout + polling → Tasks 9, 12, 13.
- Chart crosshair/tooltip interactivity → Tasks 10–11.
- Chart's last point reflecting the live price → Task 13.
- Manual end-to-end check against the real hub → Task 14.
- Error handling (unavailable states, reconnect, no-match tickers) → covered inline in Tasks 5, 6, 8, 12 per the spec's Error Handling section.

**Placeholder scan:** every step has complete, runnable code — no "TBD"/"similar to above" placeholders found.

**Type consistency:** `LivePrice` (Task 9) is the same shape used in `LivePriceReadout` (Task 12) and `CompanyPage` (Task 13). `instrument_token` (Task 1) is read the same way in Task 7 (`db.query(Company.instrument_token)...`) and Task 8 (`company.instrument_token`). `LIVE_PRICE_CACHE` (Task 6) is imported identically in Task 7 (`main.py`) and Task 8 (`routers/companies.py`) — same module path, same dict shape (`{"ltp": float, "as_of": datetime}`) written in Task 5/6 and read in Task 8. `nearestPointIndex`'s signature (Task 10) matches its call site in `PriceChart.tsx` (Task 11) exactly (`(points: ChartCoord[], x: number) => number`).
