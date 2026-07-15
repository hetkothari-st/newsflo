# Live Price + Interactive Chart — Design

## Purpose

The company detail page's price chart currently shows only historical daily closes (yfinance), refetched on period change, with no live price and no way to inspect a specific point. This adds a live, continuously-updating current price sourced from Zerodha's real-time market feed, and trading-chart-style tap/hover interactivity on the chart itself.

## Data source

An existing, separately-deployed WebSocket relay (`wss://ws-hub-production-115e.up.railway.app`, from an unrelated project `funnel_eq_zerodha`) maintains a single authenticated connection to Zerodha's Kite Connect market-data feed (`wss://ws.kite.trade`) and rebroadcasts every raw binary tick verbatim to any connected client. The hub already holds the Zerodha API key/access token — newsflo's backend never needs Zerodha credentials, it only needs to speak the hub's own client protocol:

- Subscribe: send `{"a": "subscribe", "v": [instrument_token, ...]}` as a JSON text frame.
- Receive: raw Kite binary tick frames, broadcast to every connected client with no per-client filtering — the backend must ignore ticks for instrument_tokens it didn't ask about (irrelevant, since only tokens we subscribed to will ever be sent back by Zerodha, but the decoder should handle any token defensively).
- The hub also sends `{"type": "auth_error"|"auth_success"}` JSON text frames when its own upstream Zerodha session changes state.

This is a best-effort, delayed-by-hub-uptime feed, not a guaranteed SLA — degrade-gracefully is the operating assumption throughout this design, matching the existing `price_fetcher.py`/`price_series.py` "never raise, return None/unavailable" convention.

## Instrument mapping

Zerodha subscribes by `instrument_token` (a Kite-internal numeric ID), not by ticker. `Company.ticker` is Yahoo-style (`RELIANCE.NS`).

- New nullable column `Company.instrument_token` (`Integer`), added via the existing guarded-`ALTER TABLE` mechanism (`app/db.py`'s `_ADDED_COLUMNS`, same pattern as `isin`).
- New loader `backend/app/companies/kite_instruments.py`: fetches Kite's public instruments dump (`https://api.kite.trade/instruments`, plain CSV, no authentication required), filters to `exchange in {NSE, BSE}` equity rows, and matches each row's `tradingsymbol` + `exchange` against existing companies (ticker suffix `.NS`→NSE, `.BO`→BSE, base symbol = ticker minus suffix). Upsert-by-ticker, same idempotent query-before-write style as `load_nifty_indices`.
- New standalone script `backend/seed_kite_instrument_tokens.py` (mirrors `seed_nifty_indices.py`) to backfill `instrument_token` on the existing `companies` table. Re-runnable safely; a ticker with no match in Kite's dump keeps `instrument_token` as `null` and simply never gets a live price (see Error handling).

## Live price cache + hub client

New module `backend/app/prices/kite_ws_client.py`:

- An asyncio background task, started once at app startup, gated on `settings.zerodha_hub_url` being non-empty (same "empty string disables the feature" convention as `brandfetch_client_id`) — so local dev / CI never attempts an outbound connection unless explicitly configured.
- Connects via the `websockets` library (already a dependency, used today for the app's own alert-push WebSocket) to the hub URL, sends one `subscribe` message listing every company's non-null `instrument_token`.
- On each incoming message: text frames (`auth_error`/`auth_success`) are logged and otherwise ignored; binary frames are parsed as Kite tick packets.
- **Kite binary tick format**: a 2-byte big-endian packet count, then per packet a 2-byte length prefix followed by the payload. Every packet type (`ltp` = 8 bytes, `quote` = 44 bytes, `full` = 184 bytes) shares the same first 8 bytes: 4-byte big-endian `instrument_token`, then 4-byte big-endian `last_traded_price` in paise (divide by 100 for rupees). The decoder reads only those first 8 bytes and ignores the rest of any longer packet — one decode path covers all three packet types.
- Maintains an in-memory `dict[int, {"ltp": float, "as_of": datetime}]` keyed by `instrument_token`. No persistence, no tick history — purely a live cache; a process restart just waits for the next tick per instrument.
- On disconnect, reconnects with a short backoff (mirrors the hub's own "closed → retry in 3s" loop) — a hub outage degrades the live-price feature, never crashes the app.

## New endpoint

`GET /api/companies/{id}/live-price` — public, gated by the same Nifty-only `_get_indian_company_or_404` check as the other two company endpoints.

- Looks up the company's `instrument_token`. If null, or no cache entry exists yet for it, returns `{"ltp": null, "change_pct": null, "as_of": null, "available": false}` with a 200 (never a 5xx — a missing tick is an expected, not exceptional, state).
- Once a cache entry exists: `change_pct` is computed as `(ltp - previous_close) / previous_close * 100`, where `previous_close` comes from a single cheap `fetch_price_series(ticker, period="5d")` call taking the last close strictly before today's date (falls back to the most recent available close if the market hasn't opened yet today) — not a fresh full-history fetch, and not persisted, just computed per request.

## Frontend

- `getCompanyLivePrice(id)` added to `lib/api.ts`, same thin-fetch-wrapper convention as the existing three company calls.
- `CompanyPage.tsx` polls it every ~20 seconds via `setInterval` while mounted, cleared on unmount/company-id change — independent of the historical `/prices` effect (different refresh cadence, different failure mode).
- New `LivePriceReadout` component: large current price, a bullish/bearish-colored change badge, an "as of HH:MM:SS" timestamp; renders a calm "price unavailable" state when `available` is false, matching the existing chart's own unavailable-state convention.
- `PriceChart.tsx`: when a fresh live price arrives, the chart's rendered series is updated in `CompanyPage` before being passed down — if the last historical point is already dated "today," its `close` is replaced with the live LTP; otherwise a synthetic "today" point is appended. The line visibly reflects the live tick without a full chart refetch.
- Crosshair/tooltip interactivity added to `PriceChart.tsx`: pointer (mouse) and touch handlers compute the nearest plotted point to the cursor/touch x-position, render a vertical guide line plus a small tooltip bubble showing that point's date and price. The nearest-point lookup is a pure function added to `priceChartLayout.ts` (keeps it unit-testable without a DOM, consistent with the rest of that module). No new charting dependency — extends the existing hand-rolled SVG.

## Testing

- Backend: unit tests build synthetic Kite tick byte buffers (8/44/184-byte packets) to verify the decoder extracts the right `instrument_token`/`ltp` from each packet shape; the hub client's subscribe/reconnect behavior is tested against a mocked `websockets.connect` (no live network calls in CI, consistent with `price_fetcher.py`/`price_series.py`); `/live-price` endpoint tests cover the available/unavailable/404 cases.
- Frontend: `priceChartLayout.ts`'s new `nearestPoint` function gets its own pure unit tests; `PriceChart.test.tsx` covers pointer-move showing/hiding the tooltip and the correct point being selected; `CompanyPage.test.tsx` covers the live-price poll updating the readout and the chart's last point.

## Error handling

- Hub unreachable, hub reports `auth_error`, or no tick has arrived yet → `/live-price` returns `available: false`; the frontend shows "price unavailable" and keeps polling — never an error boundary, never a failed page load.
- A ticker with no match in Kite's instrument dump keeps `instrument_token` as `null` forever; the endpoint always reports `available: false` for it. No special-casing needed anywhere else — it's the same code path as "no tick yet."
- Hub connection drops → client reconnects with backoff; existing cache entries are left as last-known-price (with their original `as_of`) rather than cleared, so a brief disconnect doesn't blank out the UI. Whether the frontend should visually flag a stale `as_of` (e.g. greyed out after N minutes) is left open for a future pass — the timestamp is already returned, so this is additive later.

## Out of scope (v1)

- True intraday OHLC candles — this is a live last-traded-price overlay on the existing daily-close line, not a candlestick chart.
- Persisting tick history — no new candle-store table, no backfill of intraday granularity.
- Per-viewer subscribe/unsubscribe bookkeeping — v1 subscribes to every Indian company with a mapped `instrument_token` at startup (Kite connections comfortably support thousands of subscriptions), avoiding the complexity of tracking which companies are "currently being viewed."
- Distinct end-user messaging for the hub's `auth_error` state — treated identically to "no data yet" in this version.
