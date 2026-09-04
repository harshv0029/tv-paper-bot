# Trading Constraints (standing rules)

## Trade-view sync: closing the "trade vanished" gap (2026-09-03)

User report: trades known to have executed were inconsistently visible on
`/trade-view` - sometimes missing entirely. Root cause: two closed-trade
sources with different freshness, and the page trusted only one of them.

- `/daily-summary`'s `closed_trades` - live SQLite, real-time, wiped on
  every Render redeploy (no persistent disk).
- `/trade-history` - reads `docs/trade_outcomes_log.json`, durable across
  redeploys, but only as fresh as the last `journal-sync.yml` run.
- `trade-view.html` read only the durable file (to dodge the DB-wipe
  undercounting this same file was built to fix - see
  `docs/KNOWN_ISSUES.md`) - so a trade was invisible from the moment it
  closed until the next sync, and if a redeploy hit inside that window,
  gone from BOTH sources permanently (the DB it hadn't been read from yet
  was wiped before the next sync could read it).

**Fix, three parts:**
1. `trade-view.html` now unions both sources client-side (dedup by
   `symbol+exit_time_utc`, same key `journal-sync.yml` dedups on) - a
   trade is visible the instant it closes (from the DB) and stays visible
   after a redeploy wipes the DB (from the file, once synced).
2. `journal-sync.yml` now also triggers on every push to `main`, not just
   the hourly Routine - a push is what actually causes the redeploy that
   wipes the DB, and a push-triggered sync (~10s) finishes well before
   Render's redeploy (1-3 min), catching trades that closed just before
   *my own* pushes - the dominant redeploy cause during active dev.
3. The hourly hosted Routine ("Journal sync - tv-paper-bot") stays as a
   backstop for redeploys not caused by a push here (e.g. Render's
   free-tier inactivity spin-down/cold-start). Confirmed the platform
   won't allow tightening it below hourly.

Residual gap: a redeploy that lands in the few seconds between a trade
closing and the push-triggered sync completing, with no push involved
(pure inactivity spin-down) can still be lost for up to the hourly
Routine's cycle. Not fully closed without a persistent DB (paid Render
tier) - documented as a known, small residual risk, not pretended away.

## Scope: instruments actually tradeable via Kotak Neo/Zerodha (rescoped 2026-09-03)

Explicit user instruction: "currently work on only Indian stock market and
stocks available to Indian trader via Kotak Neo and Zerodha accounts" -
then, on seeing gold drop out entirely: "why only NSE, but keep all those
assets listed in Zerodha." The actual line isn't "NSE-only," it's "would
Kotak Neo/Zerodha actually let a real account trade this":

- **Removed and staying removed**: crypto (BTC-USD, ETH-USD) and US
  mega-caps/ETFs (SPY, QQQ, AAPL, and 12 more) - neither broker offers
  either at all, so paper-trading them had no path to a real trade. The
  US-options overlay built on top of them is correspondingly disabled.
- **NSE/BSE equity** - `^NSEI` (NIFTY 50), `^NSEBANK` (BANK NIFTY),
  `^BSESN` (SENSEX), and the **Nifty 100** (Nifty 50 + Nifty Next 50, ~97
  stocks - NSE's own published index constituent lists, `NSE_STOCK_UNIVERSE`
  in `main.py`) - `.NS` tickers. Expanded from an earlier hand-picked
  15-name list on direct user pushback ("why not u getting whole set of
  assets... use list from public available listing") - a real public
  index is a defensible "whole set," an editorial pick of 15 wasn't. Still
  short of literally every NSE-listed stock (~2,000+, mostly illiquid) -
  scanning that many every 30s against Yahoo's free endpoint would trip
  rate limits for no benefit, since an un-backtested stock trades at the
  same conservative 1% ceiling regardless of how it was found. Round-robin
  batch size raised 7 -> 12 (`SCHEDULER_ENTRY_SCAN_BATCH_SIZE`) to keep the
  full-rotation time reasonable (~4.3 min) at this larger size. Tell me
  specific tickers, or "go to Nifty 200/500," any time.
  - **Tried and abandoned: fetching NSE's true exhaustive equity list
    (~2,000+ symbols) automatically.** Per "Index are also tradable on
    Zerodha. All listing should be exhaustive" - built
    `refresh-nse-universe.yml` to pull NSE's own `EQUITY_L.csv`
    (`SERIES=EQ`) and write `docs/nse_universe.json` for `main.py` to
    load. Confirmed (3 dispatches, 2026-09-03) this doesn't work from
    GitHub Actions: both `archives.nseindia.com` and
    `nsearchives.nseindia.com` return the identical HTML block page in
    ~1.2s regardless of cookies, a real browser-session handshake, or
    browser-like headers - that's NSE's Akamai bot protection
    edge-blocking the runner's datacenter IP before any app logic runs,
    not a fixable header/cookie gap. The workflow is kept
    (`workflow_dispatch`-only, no schedule) in case NSE's posture ever
    changes, but isn't relied on. The Nifty 100 above is the practical
    ceiling until/unless someone downloads `EQUITY_L.csv` from a real
    browser session and commits it by hand for `main.py` to load - true
    automation of "exhaustive" isn't viable against NSE's current bot
    defenses.
- **MCX commodities - restored**: gold (`GC=F`), silver (`SI=F`), crude oil
  (`CL=F`). These ARE real Zerodha/Kotak-Neo-tradable instruments via the
  MCX segment - unlike crypto/US equities, excluding them was overreach.
  yfinance has no free MCX ticker, so these run on the international
  futures contract as a **price-action proxy** for the real MCX contract
  each maps to - confirmed by the user 2026-09-03, matters once real
  execution needs the actual MCX-side symbol:
  - `GC=F` (COMEX Gold, USD/troy oz) -> MCX **GOLD**
  - `SI=F` (COMEX Silver, USD/troy oz) -> MCX **SILVER** (30 kg, 999-purity contract)
  - `CL=F` (NYMEX WTI Crude, USD/bbl) -> MCX **CRUDEOIL** (MCX's own
    contract is explicitly WTI-benchmarked, per MCX itself)

  MCX's own INR price differs from each of these (import duty, currency,
  local supply/demand) but tracks the same underlying commodity closely
  enough that a candlestick pattern/breakout signal should transfer
  directionally. Gold already has real backtest evidence (100% of 24
  swept combos profitable - docs/strategy_log.xlsx) - full 2% ceiling;
  silver/crude are unproven - half ceiling (1%) until they earn one.

Tell me specific NSE tickers (or other MCX/currency instruments Zerodha
lists) to add beyond this set any time.

Real NSE options/futures data still requires the same Kotak Neo broker
connection this project has always been gated on (not yet wired up) - the
options overlay's code (`select_option_contract`,
`_options_signal_core`, etc.) is left in place, unused
(`OPTIONS_ELIGIBLE_SYMBOLS = []`), ready for real NSE F&O data once that
connection exists. It is never synthesized as a workaround in the
meantime - same standing rule as NSE cash-market tick data.

**Standing instruction (2026-09-03): build and execute an iron condor
strategy on NIFTY once Kotak Neo is connected.** Explicitly asked for,
explicitly deferred to that point - not built now, since it needs
infrastructure this project doesn't have yet:
- **Multi-leg execution** - today's options overlay only ever manages ONE
  leg (a single long call or put, via `select_option_contract`/
  `_options_signal_core`). An iron condor is 4 simultaneous legs (sell an
  OTM call spread + sell an OTM put spread) with net-credit accounting and
  per-leg fill/risk handling - genuinely new infrastructure, not a
  parameter change to the existing single-leg code.
- **A different signal entirely** - every live entry (`orb_breakout`,
  `bullish_engulfing`, the options overlay's directional call/put) wants
  price to MOVE. An iron condor wants the opposite: range-bound price +
  IV compression (theta decay). It needs its own signal (e.g. IV
  percentile vs. expected realized move, no event in the expiry window),
  not a reuse of the trend/breakout logic.
- **Real NIFTY option chain data** - yfinance carries no NSE index options
  chain at all; this literally cannot be built, paper or otherwise, until
  Kotak Neo (or Zerodha) supplies real strikes/IV/quotes. This is the
  actual blocker, not just a nice-to-have.
When that connection lands: revisit this note, design the signal + wing-
width/defined-max-loss rules properly (not guessed), and build multi-leg
execution before wiring an iron condor into the live engine - same
evidence-first standard everything else in this file is held to.

The open GC=F and BTC-USD positions at the time of this change were
force-closed via the kill switch (`action=kill`, then `resume`) before the
new `WATCHLIST` deployed, so nothing was orphaned by their removal.

## Kotak Neo connection (added 2026-09-03)

Explicit user instruction: work toward connecting a real Kotak Neo broker
account, so this app can eventually replace the fake fills with real ones.
Standing constraint, unchanged: **100% paper trading, no real order placed,
no real money moved, until a separate, explicit go-ahead is given for that
specific step.** Everything below is scaffolding toward that, done in
phases so each phase can be verified before the next is built:

- **Phase 0** - account/API registration on Kotak's side (the user's own
  steps: enabling Trade API access, TOTP registration). Done outside this
  repo.
- **Phase 1 (done, verified live 2026-09-03)** - credentials + auth-only
  code. This app can log in to the real account and confirm the session is
  valid. `GET /kotak-neo/test-login` returned `{"logged_in": true}` against
  the real account. It does **not** read or place anything.
- **Phase 2 (done 2026-09-03)** - read-only account data (holdings,
  positions, funds/margin) pulled from the real account, still without
  ever placing an order.
- **Phase 2.5 (in progress 2026-09-03)** - real NSE option chain data (ATM
  and nearby strikes for NIFTY). `search_scrip()` is wired up as a
  diagnostic endpoint (`GET /kotak-neo/search-scrip`) but deliberately NOT
  yet turned into a polished "give me the ATM chain with live quotes"
  endpoint - the SDK's source doesn't document which scrip-master column
  is the instrument token `quotes()` needs, and guessing that on financial
  data risks silently matching the wrong contract. Next step: call
  `/kotak-neo/search-scrip` for real, read the actual field names back,
  then finish the ATM-chain-with-quotes function against confirmed data.
- **Phase 3 (not started, needs its own separate go-ahead)** - real order
  placement. Explicitly deferred; building this is a distinct decision from
  everything above it.

**Credential finding, corrected.** An older Kotak support article describes
a legacy WSO2-portal OAuth2 flow needing a separate "Consumer Secret". That
is not what the actively-maintained SDK actually uses. Verified directly
against Kotak's own SDK source (`github.com/Kotak-Neo/Kotak-neo-api-v2`,
`neo_api.py`): the real, current login only needs a **Consumer Key** (the
"default application" token shown under Neo app/web -> Invest tab -> Trade
API). No secret parameter is read by the current code path.

**Required env vars** (Render -> Environment tab; never committed, never
logged, never returned by any endpoint):
- `KOTAK_NEO_CONSUMER_KEY` - the Trade API "default application" token.
- `KOTAK_NEO_MOBILE_NUMBER` - registered mobile number, with country code.
- `KOTAK_NEO_UCC` - Unique Client Code (Neo app -> Profile).
- `KOTAK_NEO_MPIN` - the account's MPIN.
- `KOTAK_NEO_TOTP_SEED` - the TOTP secret shown once at TOTP setup time
  (the same value the QR code encodes) - needed so an unattended backend
  can generate its own 6-digit codes via `pyotp`, instead of a human typing
  one in every 30 seconds.

**Code.** `kotak_neo.py` is a module deliberately isolated from the trading
engine - nothing in `main.py`'s scheduler/entry/exit logic imports or calls
it. `login()` builds a `NeoAPI` client (`environment="prod"`), calls
`totp_login()` then `totp_validate()`, and confirms a real session via the
SDK's own convention (`client.configuration.edit_token` and `edit_sid`
both set). `holdings()`, `positions()`, and `limits()` (Phase 2) each log
in fresh and return the SDK's own response shape unmodified - no session
caching yet, since these are low-frequency diagnostic calls, not a hot
path. `search_scrip()` (Phase 2.5) wraps the SDK method 1:1, no
reshaping - see the Phase 2.5 note above for why. Six endpoints in
`main.py`:
- `GET /kotak-neo/status` - reports which of the required env vars are
  present (`{"set": bool, "length": int, "preview": "abcd..."}` shape per
  var), never the real values. Unauthenticated - no real data exposed.
- `GET /kotak-neo/test-login` - calls `login()` and returns **only**
  `{"logged_in": true}` or `{"logged_in": false, "error": "..."}`. It
  deliberately never returns holdings, positions, balance, or any other
  real account data. Unauthenticated - no real data exposed.
- `GET /kotak-neo/holdings`, `GET /kotak-neo/positions`,
  `GET /kotak-neo/limits` (Phase 2), `GET /kotak-neo/search-scrip`
  (Phase 2.5, query params `exchange_segment`/`symbol`/`expiry`/
  `option_type`/`strike_price`/`limit`) - return REAL account/market
  data, so unlike every other endpoint in this app they're gated behind a
  shared-secret token (see Security note below). The three Phase 2
  endpoints wrap their result through a JSON-safety pass
  (`_kotak_json_safe`, `json.dumps(..., default=str)`) because the SDK's
  own `positions()`/`holdings()` catch their internal errors and hand back
  `{"Error": <Exception instance>}` - not directly JSON-serializable,
  which would otherwise 500 the endpoint on exactly the failure case a
  caller most needs to see. `search-scrip` truncates its (potentially
  large) match list to `limit` (default 20) rather than wrapping through
  the same helper, since its rows are already plain JSON from a
  `pandas.to_json()` round-trip.

**`GET /watchlist`** (2026-09-03, unauthenticated, no real Kotak data) -
answers "what are you monitoring, and where does the price come from" -
lists every symbol in `WATCHLIST` with its `asset_class` (index /
nse_equity / mcx_commodity_proxy) and `data_source`. As of this writing
every monitored symbol's `data_source` is `"yahoo_finance"` - Kotak Neo is
not used for any monitoring/price data yet, only the account-level Phase
1/2 endpoints above. This is a different question from `/trade-view`,
which shows only currently-open positions, not the full scan universe.

`_asset_class_and_source(symbol)` (`main.py`) is the single source of
truth behind both `/watchlist` and `/scheduler-pipeline`'s
`check_counts_today` rows - added so the same per-asset source label
shows up in two places without drifting apart: the raw API and the
"Checks today, per asset" table on `/trade-view` itself (added a
**Source** column, 2026-09-03 - shows "Yahoo Finance" per row today, with
a hover tooltip naming the real MCX contract for the three commodity
proxies). When real Kotak-sourced pricing exists for any symbol, update
this one function and both surfaces pick it up.

**Security note.** This app has zero authentication on every other
endpoint - fine for fake paper-trading data, not fine for real account
data. The four Phase 2/2.5 endpoints above are the exception: gated
behind `KOTAK_NEO_API_TOKEN` (Render env var), checked via `?token=...` or
an `Authorization: Bearer ...` header. Fails **closed** - if
`KOTAK_NEO_API_TOKEN` isn't set on the server at all, the endpoints refuse
with a 503 rather than silently serving real data unauthenticated. A
proper auth layer for the rest of the app is still undesigned; until then,
no endpoint touching the live Kotak account may expose real data without
this kind of explicit gate (a bare pass/fail boolean, as Phase 1's two
endpoints do, or a fixed set of already-public strings, as `/watchlist`
does, doesn't need one).

**Deploy gotcha found while shipping Phase 1 (2026-09-03): Render doesn't
read this repo's `Procfile`.** The service has an explicit Start Command
configured in the Render dashboard that overrides it - editing `Procfile`
alone silently does nothing. Learned the hard way: `neo_api_client` pins
`websockets==8.1`, and even after dropping uvicorn's own `[standard]`
extra (see `requirements.txt` comment), uvicorn's default `--ws auto`
still auto-imports whatever `websockets` package it finds at startup -
finds the SDK's old pinned copy, which predates the `websockets.legacy`
module uvicorn 0.30 expects, and crash-loops the whole app
(`ModuleNotFoundError: No module named 'websockets.legacy'`). Fixed by
adding `--ws none` to the Start Command directly in the Render dashboard
(this app never uses WebSockets - HTTP only). If a future dependency ever
needs an incompatible `websockets` version again, check the *dashboard*
Start Command, not just `Procfile`.

## Real capital sizing + comprehensive F&O list (added 2026-09-04)

Explicit user instruction: "fetch the actual capital it has and apply %
limit on the trade. fetch eligivel stocks for me and also the futures and
options data too in the comprehensive list." Before this, live position
sizing scaled off `SCHEDULER_CAPITAL = 400000` - a fixed paper number, not
the real account. Verified via a real call 2026-09-04: Kotak Neo's
`limits()` returns a `"Net"` field (confirmed against the actual live
response, not a guess) - that's now the real capital feeding the
scheduler's risk sizing.

**Not fetched on every tick.** `kotak_neo.login()` is a REAL TOTP login
against the live account each call, and the scheduler can touch capital
up to `SCHEDULER_ENTRY_SCAN_BATCH_SIZE` times per 30s tick - hammering
Kotak's real login/limits API that often risks its own 429 rate limit or
looking like abuse on a real broker account. `get_scheduler_capital_inr()`
(`main.py`) caches the value for `REAL_CAPITAL_CACHE_TTL_SECONDS` (10 min)
and only refetches once stale.

**Failure handling, deliberately asymmetric:**
- A fresh-fetch failure (network blip, session hiccup) falls back to the
  **last known good value** - a transient Kotak error doesn't suddenly
  zero out sizing on every open position's next check.
- If there has **never** been a successful fetch at all (e.g. right after
  a redeploy, before the first fetch resolves), falls back to **0.0** -
  deliberately NOT the old fake Rs 4,00,000. Sizing real-shaped trades off
  a number that isn't real would defeat the entire point of this change;
  0.0 correctly sizes every trade to zero rather than trading on a
  fabricated balance. `GET /scheduler-status` exposes the live cache state
  (`scheduler_capital_inr`, `scheduler_capital_source`,
  `scheduler_capital_fetched_at_utc`, `scheduler_capital_fetch_error`).

**Verified real 2026-09-04**: `Net` came back `"0"` right after this
shipped (zero available capital, confirmed real, not a bug - trades would
size to zero), then `"2000"` once the user funded the account - proving
the live wiring actually tracks the real account rather than a cached or
fabricated figure. Don't read either number as a standing fact - `GET
/scheduler-status` always has the current cached value, `Net` will keep
moving as funds/positions change. Trading is separately paused via the
kill switch (below) as of the same session, per explicit user instruction
("we are pausing the paper trading for now").

**No live price feed from Kotak, and none of this changes that** - only
account data (capital, holdings, positions, scrip search) is wired to
Kotak. Every strategy's price/candle data (SMA, ORB, ATR) is still 100%
Yahoo Finance, per the earlier finding in this file that Kotak's Trade
API has no historical-candle endpoint at all. `subscribe()` (Kotak's real
tick-streaming method) has never been called anywhere in this codebase -
no open WebSocket connection exists. Real-time ticks from Kotak would be
a distinct, separate piece of work from anything in this section.

**`GET /kotak-neo/comprehensive`** (token-gated, real Kotak calls) -
`eligible_equities` (same as `GET /watchlist`) plus `fo_universe`: **every**
contract in Kotak's live `nse_fo` scrip master, every strike, every
expiry, completely unfiltered (`search_scrip(exchange_segment="nse_fo",
symbol="")` - an empty symbol skips Kotak's own symbol filter entirely).
Explicit user choice ("full raw dump, no filtering") after being told a
`symbol="nifty"` substring search alone matched 11,822 contracts the same
day - the full segment is markedly larger still, likely tens of thousands
of rows / a multi-MB response. Not artificially truncated in code, per
that instruction; a smaller diagnostic version
(`GET /kotak-neo/search-scrip`, `limit=20` default) already exists for
quick field-name checks without paying that cost.

**Real-data gotcha, caught before it became a bug**: a naive
`symbol="nifty"` search (substring match, not exact) surfaces
**`NIFTYFPI`** contracts - a separate, niche, restricted NSE product, not
the actual liquid NIFTY 50 index options. Anything built on top of
`search_scrip` needs an exact match on `pSymbolName` (e.g. `== "NIFTY"`),
not a substring search. Also confirmed from real records:
`dStrikePrice;` is the strike **x 100** (e.g. `84000.0` means strike
Rs 840), and `pSymbol` (a small integer) is the likely `instrument_token`
`quotes()` needs - not yet exercised end-to-end.

## SDK migration: neo-api-client v2.0.2 -> kotakneoapi v3.0.1 (2026-09-04)

Prompted by the user pasting a claim about a new Kotak WebSocket SDK -
**verified for real before acting on it**, not taken on faith: confirmed
via PyPI's own package metadata (real hashes, real upload timestamps,
`ownership.roles` showing the real `kotak-neo` org as Owner) that
`kotakneoapi` v3.0.1 genuinely exists and supersedes the old
git-installed `neo-api-client`==2.0.2 this project used until now (that
repo, `Kotak-Neo/Kotak-neo-api-v2`, now literally calls itself "legacy"
in its successor's README). One detail in the pasted claim was NOT
independently verified: a specific "September 15, 2026" deprecation date
for the old feed - not present in the package metadata pulled, so it's
treated as unconfirmed, not fact.

**What migrating actually required** - re-cloned the new SDK's repo
(`Kotak-Neo/kotak-neo-python`) and checked every function this project
calls against its real source (not just its docs), same discipline as
every other Kotak claim this session:
- `NeoAPI.__init__`'s parameter order changed (`consumer_key` now comes
  first) and its `environment` default flipped `"uat"` -> `"prod"` - a
  real silent-breakage risk **only for positional calls**. This project's
  `login()` already used keyword arguments throughout, so it needed no
  change.
- `limits()` now takes **zero** parameters (previously
  `segment`/`exchange`/`product`) - this project's `limits()` wrapper
  already called it with no arguments, so no change needed there either.
- `search_scrip()`'s signature, and critically its response field names
  (`pSymbolName`, `pOptionType`, `dStrikePrice;`, the `pandas.to_json
  (orient="records")` shape) - all unchanged, confirmed against the new
  SDK's actual `scrip_search.py`, not assumed from a similar-sounding
  method name.
- Error handling for every method this project calls (`limits()`,
  `search_scrip()`, `holdings()`, `positions()`) is explicitly unchanged
  in the new SDK's own migration guide - still `{"Error": ...}` /
  `{"error": [...]}` dicts, not exceptions. `totp_login()`/
  `totp_validate()` gained one new behavior: a network-level failure now
  raises `ApiException` uncaught (previously it would have surfaced some
  other way) - already handled here, since every endpoint that calls
  `kotak_neo.login()` already wraps it in a broad `except Exception`.
- Order placement, `modify_order`, and the async WebSocket client all
  changed significantly in v3 - **irrelevant here**, since this project
  places no orders and doesn't (yet) use any WebSocket/streaming feature.

**Net result: zero logic changes to `kotak_neo.py`'s actual calls** -
this was a dependency swap (`requirements.txt`) plus doc updates, not a
rewrite. Verified locally against the *real* `kotakneoapi==3.0.1` package
(not a v2 stand-in) with the full existing mocked-`kotak_neo` test suite
- every endpoint still passes.

**Bonus side effect**: `kotakneoapi` pins `websockets>=12.0` (confirmed
`17.1` resolved in a clean install) - well above the `websockets.legacy`
threshold that caused the earlier production crash and the `--ws none`
Start Command workaround. That workaround is left in place regardless
(this app still never uses WebSockets, so it's harmless either way) -
not proven unnecessary now, just no longer the forced fix it was.

**Deliberately NOT part of this migration**: the new SDK's actual live
tick-streaming feature (`create_websocket()` / `subscribe_scrips()` /
`SFeedScrip`) is real and confirmed working per the SDK's own docs, but
building on it is a separate, larger decision - it still doesn't solve
the historical-candle gap this file already documents (live ticks only,
no backfill), and would mean a persistent async connection running
inside this app (reconnect logic, tick storage, a genuinely different
runtime shape from the request/response endpoints here). Not started;
would need its own explicit go-ahead, same as Phase 3.

## Trade-view: real capital + per-trade invested amount (added 2026-09-04)

`static/trade-view.html`'s top trade-log table gets an **Invested (₹)**
column on live rows (`pos.notional_inr`, already computed server-side per
position - just not previously surfaced in this table, only on the
individual position cards below it). Closed rows show a dash there
deliberately, not a guessed figure - closed-trade records don't carry
`notional_inr`/`fx_to_inr`, and computing one for a commodity trade
without the real FX rate at exit risks a silently wrong number.

**Bug fixed in the same change**: the page's own fetch of `/daily-summary`
hardcoded `?capital=400000` - the old fake paper number, now stale since
the scheduler's real capital sizing shipped earlier the same day. Fixed
to fetch `/scheduler-status` first and pass its real
`scheduler_capital_inr` through instead, so `capital_deployed_inr`/
`capital_available_inr`/`budget_remaining`/`pnl_pct_of_capital` all
compute against the same real number the live scheduler actually sizes
trades against - not two different capital figures on two different
pages. A new **Capital available (real, Kotak Neo)** stat tile surfaces
`capital_available_inr` directly. `Math.max(1, ...)` guards the capital
value used against a divide-by-zero in `/daily-summary`'s own
pct-of-capital math if the real fetch hasn't resolved yet (falls back to
0 per `get_scheduler_capital_inr()`'s own contract).

## Kotak Neo live tick feed (added 2026-09-04)

Explicit user instruction: real-time streaming ticks from Kotak Neo,
prompted by the SDK migration above. `kotak_live_feed.py` is a background
asyncio task (launched from `main.py`'s startup event, isolated from the
scheduler's own task - a crash or reconnect loop here can never affect
paper-trading signal generation) that logs in once, resolves real
instrument tokens, subscribes via `create_websocket()`/`subscribe_scrips
()`, and keeps an in-memory `{symbol: {"ltp", "trading_symbol",
"instrument_token", "updated_at_utc"}}` store updated as ticks arrive.
`GET /kotak-neo/live-ticks` (unauthenticated - display data only, not
account-specific, same reasoning as `/watchlist`) exposes the current
store plus feed status (`connected`, `last_error`, `subscribed_symbols`,
`unresolved_symbols`).

**Display data only - this does not change how any trading decision gets
made.** Entry signals (SMA crossover, ORB breakout) and the levels they
compute (stop, target) still run entirely on Yahoo Finance candle
history - Kotak's API has no historical-candle endpoint, unchanged by
this feed. Wiring live ticks into *exit-check timing* specifically
(checking a stop/target against the freshest available price instead of
waiting for the scheduler's next ~30s cycle) was explicitly discussed as
a genuine, bounded follow-up - not done in this change.

**Instrument-token resolution**, `resolve_tokens()`:
- NSE equities (`*.NS` in `WATCHLIST`): ONE `search_scrip(exchange_
  segment="nse_cm", symbol="")` call for the whole segment (not one call
  per symbol - each would re-download the entire scrip master CSV, slow
  and wasteful for ~100 symbols), matched locally by **exact**
  `pSymbolName` - a substring match wrongly matched `NIFTYFPI` for
  "nifty" earlier the same day, so this never uses `.contains()`.
- Indices: literal name-based tokens, not scrip-master rows - `"Nifty
  50"` confirmed from the new SDK's own README example, `"Nifty Bank"`
  independently verified 2026-09-04 via a real `quotes()` call
  (`ltp: 57367.35` - a real Bank Nifty level) since `search_scrip` can't
  confirm an index token at all (indices aren't scrip-master rows).
  `GET /kotak-neo/quotes` was built specifically as this verification
  tool and is kept for future token checks.
- SENSEX and the 3 MCX commodity proxies (`GC=F`/`SI=F`/`CL=F`):
  deliberately unresolved. No confirmed BSE index token exists yet for
  SENSEX; the MCX proxies are stand-ins for a *different* real MCX
  contract each (different currency, different unit - see the "Scope"
  section above), and mapping one to a real, correctly-dated MCX
  contract is an unresolved design question (which strike/expiry), not a
  token-lookup problem to paper over with a guess.

**Render free-tier reality, stated plainly**: the whole process suspends
on inactivity, which kills this task along with everything else. It
isn't "always-on" in the strict sense - it restarts fresh (re-login,
re-resolve, re-subscribe) each time a request wakes the app, via the
same startup event that launches it the first time. `last_error`/
`connected: false` on `/kotak-neo/live-ticks` most commonly means exactly
this - a fresh restart mid-reconnect, not a real failure.

Still 100% paper trading throughout - this module places no order and is
never called by anything that does.

## Kill switch / pause-resume (added 2026-09-03)

Explicit user instruction: "I want to decide when to do trading and when
not." A single master switch, checked by `_auto_signal_core` and
`_options_signal_core` themselves (not just the scheduler, so the
redundant GH Actions backstop calls can't bypass it):

- **`POST /trading-control?action=pause`** - blocks every NEW entry,
  equity and options alike, across every symbol. Does **NOT** stop
  managing an already-open position - stop/target/trend/eod-squareoff all
  keep running exactly as before. A paused account must never mean an
  unwatched open position.
- **`POST /trading-control?action=resume`** - lifts the pause.
- **`POST /trading-control?action=kill`** - the actual kill switch:
  force-closes **every** open position (equity + options) right now at
  the best available current price, regardless of stop/target, tagged
  `exit_reason=manual_kill_switch`, AND pauses (so nothing reopens on the
  very next tick). Standalone code path from the normal exit logic on
  purpose (`_force_close_all_positions`) - an emergency stop should never
  share a code path with, or risk being broken by some future change to,
  the everyday exit logic that protects every other open position.
- **`GET /trading-control`** - current state (`enabled`, who/when/why it
  last changed).
- Survives a Render redeploy the same way an open position's journal does
  - `state/trading_control.json` (written by `journal-sync.yml`,
  restored on startup by `reconcile_trading_control_from_journal`) -
  without this, a pause would silently lift on the next code push.
- Controlled from `/trade-view`'s control bar - a single toggle switch
  (OFF = trading live, ON/red = kill switch: blocks new trades and closes
  everything) - as well as directly via the HTTP endpoints above.

These are the hard limits the live paper-trading engine (`_auto_signal_core`
in `main.py`) enforces on every check, for every market. They are the
canonical reference — if a future change conflicts with this file, the
change is the bug.

| Constraint | Value | Enforced by |
|---|---|---|
| **Capital** | ₹4,00,000 (raised from ₹2,00,000 2026-09-03, per user instruction "for today"), one shared pool across the NSE/BSE watchlist (rescoped to NSE-only 2026-09-03 - see the scope section above) | `capital` param, default across all WATCHLIST entries |
| **Max loss per day** | **2% of TOTAL capital at the start of the day (₹8,000 at current capital)** — resets at IST midnight, every calendar day, automatically | `daily_risk_pct=2.0` + `ist_midnight_epoch()` in `today_realized_pnl()` |
| **Max risk per trade** | **2% of the capital actually INVESTED IN THAT TRADE** (the tranche/available-capital-capped amount it can deploy — `usable_capital_inr`), NOT 2% of total account capital — explicit standing policy, clarified 2026-09-03. A CEILING, not a fixed rate — set lower per symbol where evidence supports it. Both this cap and the daily cap apply independently; whichever binds first forces the exit/entry-block | `risk_per_trade_pct` × `usable_capital_inr`, per-symbol in `WATCHLIST` |
| **Per-trade stop-loss cap** | Same ceiling logic, tighter of this or the strategy's own ORB-low level | `stop_pct`, per-symbol in `WATCHLIST` |
| **Risk:Reward minimum** | **1:3** (target = entry + 3 × stop distance) — raised 2026-09-03 from 1:2 per standing user instruction; a trade is only entered if it clears this | `rr=3.0`, `SCHEDULER_RR` |
| **Capital deployed cap** | Total notional across all open positions never exceeds current `capital` | `deployed_notional()` capital check in the entry path |
| **Position sizing** | Fractional units, not integer-floored — a whole-unit floor was silently blocking every BTC-USD/ETH-USD/gold entry (unit price exceeds a ₹2L pool) regardless of signal quality; fixed 2026-09-03 | qty computed as a float in `_auto_signal_core`, min ₹100 notional guard |
| **Trend exit** | An open LONG position exits early (before stop/target/eod) if the short-term trend that justified holding it flips against the trade — checked on every tick, not just at entry | `trend == "down"` (equity) / `_compute_trend()` vs. call-or-put (options) in the position-management branch |

## Trend health is monitored for the life of the trade, not just at entry (added 2026-09-03)

Direct user instruction: entries already required a favorable trend
(`orb_breakout` requires `trend == "up"`; `bullish_engulfing` has an
optional `trend_sma` filter), but an OPEN position was never re-checked
against it — only stop/target/eod-squareoff/daily-halt could close a
trade early. Now every open-position check also asks "is the trend that
justified this trade still intact?":

- **Equity** (`_auto_signal_core`): `sma_fast`/`sma_slow` are already
  recomputed on every check (used for the entry trend filter) - a long
  position now also exits with `trend_weakened` the moment that same
  read flips to `"down"`, regardless of where price sits between stop and
  target. Checked after target/stop (a live price-level hit still takes
  priority for reason-labeling) and before eod-squareoff.
- **Options overlay** (`_options_signal_core`): a **call** (bullish bet)
  exits `trend_weakened` if the underlying's trend flips to `"down"`; a
  **put** (bearish bet) exits if it flips to `"up"`. Uses the same
  `sma_fast`/`sma_slow` read via a shared helper (`_compute_trend`),
  reusing `fetch_ohlc`'s cache so this doesn't add a real extra network
  call when the underlying was already checked elsewhere this tick.
- This is a genuinely new, lower-priority exit trigger, not a replacement
  for the hard stop/target/daily-cap/expiry limits above it in priority -
  the point is to often exit BEFORE the stop is hit (smaller loss, or
  locking in a partial gain) once the setup's own premise has broken,
  rather than mechanically riding every trade all the way to its stop.
- **Gated at 95% confidence (added 2026-09-03).** Direct user instruction:
  a bare SMA-fast-crosses-SMA-slow flip can be one noisy bar, not a real
  reversal - closing a trade on that alone risks getting shaken out and
  missing the recovery. `_trend_confidence()` turns the SMA gap into a
  one-tailed statistical confidence via the normal CDF (`_norm_cdf` -
  same machinery `_bs_delta` already uses for option delta, not a fudged
  number): it standard-errors the gap against recent per-bar price
  volatility (`sigma_price * sqrt(1/sma_fast + 1/sma_slow)`), then reads
  the z-score's confidence off the normal distribution.
  `TREND_WEAKENED_MIN_CONFIDENCE = 0.95` - `trend_weakened` only fires at
  or above that; below it (including whenever there isn't yet enough
  same-day history to size volatility) the trade is left alone and simply
  continues under its existing stop/target/eod-squareoff, exactly per
  instruction ("else it should not close the entered trade").

## Trailing stop loss (added 2026-09-03) - equity engine only for now

Direct user request: a trailing stop for every entered trade, plus rules to
review. **Equity (`_auto_signal_core`) only** - the options overlay has
zero live trades right now (`OPTIONS_ELIGIBLE_SYMBOLS = []`), so there's
nothing to validate a trailing rule against there yet; same treatment is a
natural fast-follow once that overlay is re-enabled. Two-stage rule,
implemented in `_trailing_stop_target()`:

1. **Activation gate - `TRAIL_ACTIVATE_R = 1.0`.** Below 1R of unrealized
   gain (R = entry_price - the ORIGINAL stop at entry, frozen forever in
   the new `signal_state.initial_stop_loss` column so it doesn't move as
   the live stop trails), nothing changes - the trade still runs on its
   plain fixed stop. Rationale: a trade that hasn't even recovered its own
   risk yet shouldn't have its stop tightened on top of normal opening
   noise - that's how a real winner gets shaken out before it ever gets
   going. Industry-standard practice, not specific to this system.
2. **Breakeven lock, then a Chandelier Exit.** At/above 1R, the stop locks
   to breakeven + `TRAIL_BREAKEVEN_BUFFER_PCT` (0.1%, to clear round-trip
   cost) at minimum - the trade can no longer become a real loss. Beyond
   that, it ratchets further via a **Chandelier Exit**: `highest close
   since this trade's own entry - TRAIL_CHANDELIER_K (3.0) * ATR(14)`,
   whichever of that or the breakeven lock is higher. This is a real,
   widely-published technique (Chuck LeBeau's own default k=3,
   period=14), not invented for this project - it adapts the trail's
   width to each stock's OWN actual volatility (a quiet blue-chip and a
   choppy mid-cap get different-width trails automatically) instead of one
   arbitrary fixed percentage applied to everyone alike. ATR is read off
   the multi-day candle history already fetched every tick (not just
   today's bars), so there's a real reading even early in the session.
3. **Only ever ratchets up, never down** - the caller takes
   `max(current_stop, candidate)`; `_trailing_stop_target` itself never
   proposes loosening. Persisted in place (`signal_state.stop_loss` IS the
   live, possibly-trailed value - `stop_hit` needs no separate check), so
   the trade-view UI's existing stop/ladder display already reflects it
   with no separate field.
4. **Never overrides the fixed target.** `target_hit` still exits
   immediately at the planned R-multiple if price gets there first -
   trailing only ever tightens the floor beneath it. Letting a strong
   trend run PAST the original target once trailing has activated (a
   "let winners run" upgrade) is a separate, bigger design decision I've
   deliberately not made unilaterally - say the word if you want that too.
5. **Runs alongside, not instead of, the 95%-confidence `trend_weakened`
   exit above** - both checks run every tick; whichever condition is met
   first exits the trade. Trailing is mechanical/price-based (fires fast
   once price gives back enough); `trend_weakened` is statistical (fires
   only on a real reversal). Together they cover both "the move already
   gave back its gain" and "the setup itself broke."
6. `rr_achieved` on exit is now measured against the ORIGINAL R
   (`initial_stop_loss`), not the trailed stop - otherwise a trade that
   trailed close to its own exit price would report an inflated R-multiple
   off its own shrunken `stop_dist`. The exit payload also carries
   `initial_stop_loss` and a `trailing_active` flag for genuine visibility
   into which trades it actually engaged on.
7. **Survives a redeploy.** `daily_summary()`'s `open_positions` now
   exposes `initial_stop_loss_native` (the frozen entry stop) alongside
   the existing `stop_loss_native` (the live, possibly-trailed one) - both
   round-trip through the journal file, so `initial_stop_loss` is not lost
   across a redeploy and the R-multiple yardstick trailing measures
   against doesn't reset with it. A journal snapshot from before this
   field existed falls back to whatever `stop_loss_native` it has (that
   trade's true original R is a small, honest known-gap for pre-existing
   positions only, not new ones going forward).

**Activation threshold backtested 2026-09-03** (direct user request -
`.github/workflows/trailing-stop-threshold-backtest.yml`, workflow_dispatch,
read-only). Imports `main.py` directly and calls its own
`_trailing_stop_target`/`_trend_confidence` (not a reimplementation that
could drift from what's live) - only `TRAIL_ACTIVATE_R` varied per
variant; Chandelier k/ATR period/breakeven buffer held at their shipped
defaults. Entries found via the live `orb_breakout` rule, replayed
bar-by-bar across ~59 days of real 5-min data (yfinance's own intraday
window), 12 symbols (the 3 NSE indices + 10 liquid Nifty 50 names -
`TATAMOTORS.NS` skipped, Yahoo now 404s that ticker), 380 pooled entries
per variant:

| Variant | Win % | Total R | Avg R | Profit factor |
|---|---|---|---|---|
| No trailing | 34.7% | -7.77 | -0.020 | 0.93 |
| **0.5R** | **41.6%** | **-3.76** | **-0.010** | **0.96** |
| 1.0R (old default) | 35.8% | -6.20 | -0.016 | 0.95 |
| 1.5R | 34.7% | -9.39 | -0.025 | 0.92 |
| 2.0R | 34.7% | -9.42 | -0.025 | 0.92 |

`TRAIL_ACTIVATE_R` changed **1.0 -> 0.5** - clear winner on every metric.
Mechanism visible in the exit-reason breakdown: at 0.5R, `stop_hit` count
jumps from 24 (no trailing) to 129, converting a lot of what would
otherwise be outright `trend_weakened` losses (248 -> 173) into
scratch/small-win exits near breakeven instead. 1.5R/2.0R are actually
*worse* than no trailing at all - waiting that long to engage lets a few
real winners run into a normal 3xATR pullback and get stopped just short
of the fixed target, giving back more than the early protection saves
elsewhere. Chandelier k=3.0/ATR period=14 themselves were NOT swept in
this pass - still the standard published defaults, not yet evidenced for
this watchlist specifically.

**Bigger finding this backtest also surfaced, unresolved:** every single
variant - including the winning 0.5R - is net LOSING on this sample
(total R negative, profit factor < 1). `trend_weakened` alone accounts for
46-65% of all exits across variants. The trailing-stop threshold is a
second-order lever on top of an `orb_breakout` + exit-stack combination
that loses money in aggregate on this ~59-day window, at least for these
12 symbols. Sample-size/regime caveats apply (one recent window, ~380
trades, could reflect one specific choppy/range-bound stretch rather than
a durable edge - same caution `/sweep`'s own note gives). Flagging this
plainly rather than fixing it unilaterally: worth a real investigation
(a wider backtest window, and/or whether `trend_weakened`'s 95% gate or
`orb_breakout`'s own entry filter needs revisiting) before trusting this
watchlist's current live setup to be profitable over time - separate from,
and larger than, the trailing-stop question this session answered.

## Two independent caps, two different bases (clarified 2026-09-03)

The per-trade cap and the daily cap are measured against **different
amounts of money on purpose** - conflating them was a real bug risk, so
this is spelled out explicitly:

- **Per-trade cap**: `risk_per_trade_pct`% of **that trade's own allocated
  capital** (`usable_capital_inr` = min(capital available right now,
  capital/`CAPITAL_TRANCHES`) - the slice this specific trade can deploy).
  A ₹2,00,000 tranche at the 2% ceiling risks at most ₹4,000 on that one
  trade, not ₹8,000. If the strategy's own stop is tighter than the
  `stop_pct` cap (common - see BTC-USD's live example, where a ~0.65%
  structural stop meant the real risk taken was well under even this),
  the realized risk is smaller still.
- **Daily cap**: `daily_risk_pct`% of **total account capital as of the
  start of the IST day** (`capital`, currently ₹4,00,000 -> ₹8,000/day),
  shared across every open trade and every market.
- Both are hard, independently-enforced exits - hitting either one forces
  the corresponding action (stop-loss exit for the per-trade cap,
  no-new-entries + square-off-everything for the daily cap) regardless of
  the other. A single trade's per-trade cap is always <= the daily cap
  (since a tranche is always a fraction of total capital), so in practice
  the daily cap is the outer bound multiple smaller trades collectively
  respect, and the per-trade cap is what limits any ONE of them.
- **The daily cap is a HALT, not a shrinking allowance (fixed 2026-09-03).**
  Explicit user instruction: "I want net loss to be 2% for all trades for
  the day. Not that loss budget." Before this, a new trade's own sizing
  was ALSO capped at `min(risk_per_trade_pct% of its tranche,
  remaining_budget)` - so as the day's running net P&L got closer to -2%,
  every SUBSEQUENT new trade would silently size smaller than its own
  stated risk_per_trade_pct, even though nothing had actually halted yet.
  That's gone: `risk_amount_inr` is now always the full
  `usable_capital_inr * risk_per_trade_pct / 100`, every time, with no
  reference to the day's running P&L. The daily cap's ONLY remaining job
  is the binary halt itself (`halted = remaining_budget <= 0`, i.e. net
  realized P&L today <= -daily_risk_pct% of capital) - once that trips,
  `blocked_daily_loss_cap` stops every new entry outright and any open
  position gets squared off; until it trips, every entry sizes at its
  full, undiminished risk_per_trade_pct. One consequence worth being
  explicit about: since sizing no longer throttles down as the day
  worsens, a trade taken right before the halt trips can still be
  full-sized - the halt itself is what bounds the day's net loss at ~2%,
  not smaller-and-smaller trades approaching it.

## Capital reallocation - trimming a weaker live position to fund a stronger new one (added 2026-09-03)

Explicit user instruction: when the capital pool is genuinely full and a
stronger new signal appears, decide how much of an existing position to
exit so the stronger one can be taken - "maximising profit is the only
aim of this." Implemented as the "cross-symbol best-signal-wins" step the
capital-sizing code's own comment had already flagged as a future step -
but NOT as license to chase every shinier signal: the trailing-stop
backtest already showed cutting a position early, on its own, tends to
destroy value here (letting a real winner run to its own stop/target
mattered more than reacting fast - see "Trailing stop loss" above). So
this is deliberately narrow, not an aggressive reallocation engine:

- **Only tried when there's a genuine capital shortage** - `usable_capital_inr
  < notional_per_unit_inr` for the new signal, checked right where the
  entry path would otherwise give up with `insufficient_capital`. A
  routinely-available new signal that the account can already afford
  never touches this path at all.
- **The new candidate's edge must be real, not just "different."**
  Measured on the same 0-1 scale the 95%-confidence `trend_weakened` exit
  already uses (`_trend_confidence` - the normal-CDF read on the SMA gap
  vs. recent volatility, not a fudged number). An existing position is
  only a reallocation candidate if the new signal's confidence exceeds
  its OWN current confidence by at least `REALLOCATION_MIN_CONFIDENCE_GAP`
  (0.20) - a clear, auditable gap, not "any edge at all."
- **Never realizes a loss to chase something else.** A candidate position
  must have unrealized P&L >= 0 at the moment of the check - trimming a
  red position for this reason would be panic-selling with extra steps.
- **Never touches a position that's about to exit on its own anyway.**
  Only a position still trending the direction that justified holding it
  ("up") is eligible - one already trending down is on its way out via
  `trend_weakened` regardless, no special handling needed.
- **Weakest link, one position, bounded size.** Among eligible candidates,
  only the SINGLE one with the LOWEST confidence is trimmed - never two
  or more to fund one new entry (bounded blast radius, no cascade). Sized
  to free at most one tranche's worth of headroom
  (`max_single_trade_inr - available_capital_inr`), capped at that
  position's own held quantity - "how many out of N need to exit," never
  more than the minimum needed, never the whole position unless that IS
  the minimum needed.
- **The remainder keeps running normally.** A partial exit reduces
  `signal_state.qty` in place - it does NOT reset or replace the
  position's stop/target/trailing-stop; whatever's left of the original
  position continues exactly as it would have, just smaller.
- **Capped at `REALLOCATION_MAX_PER_DAY` (2) reallocation events per day**,
  hard ceiling, regardless of how many times the pool gets maxed out -
  bounds the churn this can ever introduce.
- **Fully auditable**: logged with its own distinct exit_reason
  (`partial_exit_reallocated`, never folded into an ordinary stop/target/
  trend_weakened exit) carrying both confidence numbers and which symbol
  it freed capital for; the funded entry's own payload carries
  `reallocated_from` pointing back the other way.
- **Equity only, for now** - same scoping as trailing stop loss; the
  options overlay has zero live trades to build this against
  (`OPTIONS_ELIGIBLE_SYMBOLS = []`).
- **Untested against real market data.** Unlike the trailing-stop
  threshold, this genuinely can't be backtested with the existing
  single-symbol bar-by-bar replay harness (`trailing-stop-threshold-
  backtest.yml`/deploy-gate's own check) - reallocation is inherently
  cross-symbol (it depends on which OTHER positions happen to be open at
  the same moment), which that harness doesn't model. Shipped with
  conservative, explicit, auditable gates instead of a backtested number -
  flagged plainly rather than pretended to be evidence-backed. A proper
  multi-symbol portfolio-level backtest would be the real way to validate
  `REALLOCATION_MIN_CONFIDENCE_GAP`/`REALLOCATION_MAX_PER_DAY` before
  trusting them the way `TRAIL_ACTIVATE_R` is now trusted.
- **Watched, not just shipped**: a dedicated read-only CCR agent
  ("Reallocation Auditor - tv-paper-bot", daily 04:30 UTC / 10:00 IST)
  reviews every `partial_exit_reallocated` event after the fact - checks
  it actually followed its own stated rules, and the real substance of
  the review: whether it looks, WITH HINDSIGHT, like it actually served
  "maximising profit" or not. It never executes, resizes, or reallocates
  anything itself - flags the user if something looks off, otherwise a
  quiet one-line all-clear (including "no events to review").

## Per-trade risk: 2% is a ceiling, tuned down by evidence

Current split (as of 2026-09-03):
- **NIFTY, BANKNIFTY, SENSEX: full 2%, strategy `orb_breakout`.** Real
  60-day backtest evidence behind this exact ORB strategy
  (`docs/daily_logs/2026-09-02-entry-trigger-research.md`) — profitable on
  95.8-100% of swept parameter combinations, not a lone lucky spike.
- **AAPL: full 2%, strategy `bullish_engulfing` (trend_sma=20).** Switched
  2026-09-03 from unvalidated `orb_breakout` defaults once real evidence
  existed for a different strategy on this symbol — 100% of 6 swept
  combos profitable (`docs/strategy_log.xlsx`). Live exits still use the
  same bounded-risk framework (stop/target/EOD-squareoff) as every other
  symbol, not the backtest's own open-ended exit — see the docstring on
  `_auto_signal_core` in `main.py`.
- **SPY, QQQ, BTC-USD, ETH-USD: 1% (half the ceiling), strategy
  `orb_breakout`.** No evidence yet that any strategy works on these -
  runs conservative until one earns a track record, the same way
  NIFTY/BANKNIFTY/SENSEX and AAPL did.

Per-symbol `strategy` is set in `main.py`'s `WATCHLIST`; the redundant
GH Actions backstop workflows (`live-signals*.yml`) must pass matching
`strategy`/params for any symbol that isn't plain `orb_breakout`, or the
backstop call and the in-process scheduler will disagree about how that
symbol is being traded.

## The daily loss cap, specifically

- Resets automatically every IST calendar day at midnight — not manually,
  not on a rolling 24h window. This is deliberate: it's the account's "day"
  regardless of which market (NSE/US/crypto) a position is in, since a
  US-session trade spans ~19:00-01:30 IST and needs one consistent day
  boundary for the whole shared pool.
- Once today's realized loss (summed across every symbol/market, converted
  to ₹ via each trade's own `fx_to_inr`) hits ₹4,000: no new entries are
  taken, and any open position is squared off immediately, for the rest of
  that IST calendar day.
- This is a hard numeric check in code (`halted = remaining_budget <= 0`),
  not a judgment call — see the multi-agent architecture doc: Validator-role
  logic like this is deliberately deterministic code, never routed through
  an LLM's discretion.

## Options overlay (calls/puts) - added 2026-09-03

**Disabled 2026-09-03** (`OPTIONS_ELIGIBLE_SYMBOLS = []`) - rescoped to
NSE-only (see the scope section at the top of this file). Every symbol
this ever covered (SPY, QQQ, AAPL, and 12 more) was a US underlier, not
tradeable via Kotak Neo/Zerodha. The mechanics below are left documented
and the code left in place, unused - this is exactly the strike/IV
selection logic real NSE F&O would use once a broker connection (Kotak
Neo) provides real NSE options chain/IV data; **NSE/BSE index and stock
options are NOT covered today** - there is no real chain/IV data for them
without that connection, and this project does not synthesize a fake
options chain as a workaround, the same standing rule as NSE real
tick/futures data.

Every options-eligible symbol also had to be a `WATCHLIST` equity entry
(same `orb_breakout`, 1% ceiling until one earns real evidence the way
AAPL/NIFTY/BANKNIFTY/SENSEX did) - the scheduler needs that entry for
session hours/currency/risk_pct, so an options-eligible symbol missing from
`WATCHLIST` is silently skipped, not an error.

- **Direction -> right**: a bullish signal (ORB breakout with trend, or
  bullish engulfing) buys a **call**; the same patterns' bearish mirror
  (ORB breakdown, bearish engulfing - `_detect_direction_signal` in
  `main.py`) buys a **put**. The equity engine itself stays long-only and
  is untouched by this - direction detection here only decides call vs put.
- **Strike selection - "bigger profit, don't lose sight of IV"**: nearest
  live contract to **0.35 delta** (`OPTIONS_TARGET_DELTA`), computed via
  Black-Scholes from the chain's own quoted IV - moderately OTM for real
  leverage on a win without betting on a near-impossible move. Rejected if
  its IV is more than **1.6x the chain's own ATM IV** (`OPTIONS_MAX_IV_VS_ATM`)
  - a skew/event spike means that strike is priced rich and prone to giving
    the gain back to IV crush even if the direction call is right - or if
  its bid/ask spread is illiquid (>15%, `OPTIONS_MAX_SPREAD_PCT`).
- **Expiry**: nearest with 2-10 days to expiry (`OPTIONS_MIN_DTE`/`MAX_DTE`)
  - skips 0-1 DTE gamma/pin risk and avoids paying for theta on a
    signal-driven intraday entry.
- **Stop/target**: premium-based - stop at **45% below entry premium**
  (`OPTIONS_STOP_PCT`), target at entry + `rr` x that same risk, so the
  standing **1:3 minimum RR still applies**, just to the option's own P&L
  basis instead of the underlying's.
- **Sizing**: same shared capital pool and tranche cap as everything else
  (`deployed_notional` now sums both `signal_state` and `option_state`).
  Contracts = risk budget / risk-per-contract, floored - but never silently
  zeroed by that floor the way un-fixed equity qty once was: if 1 contract's
  own risk still fits inside today's *full* remaining daily-loss budget, it
  takes that 1 contract even if its risk slightly exceeds this one trade's
  own `risk_per_trade_pct` target (the same "one trade can use the whole
  day's budget" ceiling already applied to equities when `risk_per_trade_pct
  == daily_risk_pct`, made explicit for the options case since a 100-share
  multiplier can't size down to a fraction of a contract the way BTC/gold
  size down to a fraction of a unit).
- **Exit**: stop/target/EOD-squareoff exactly like equities, plus a forced
  exit if the contract's own expiry is reached - never held into or past
  expiry.
- Position tracked in `option_state` (DB) + journaled the same way open
  equity positions are (`state/open_positions.json`, restored on every
  Render redeploy via `reconcile_open_positions_from_journal`), and its
  buy/sell legs land in the SAME `trades` table as equities (qty =
  contracts x 100, price = premium/share) tagged `orb-option` - so realized
  P&L, the daily loss cap, and `/daily-summary` automatically include
  options alongside equities as one account, one shared risk budget.

## Where this is currently duplicated (keep in sync if you change a number)

- `main.py`: `SCHEDULER_DAILY_RISK_PCT`, `SCHEDULER_RISK_PER_TRADE_PCT`,
  `SCHEDULER_STOP_PCT`, `SCHEDULER_RR` (used by the in-process scheduler),
  and `OPTIONS_ELIGIBLE_SYMBOLS`/`OPTIONS_TARGET_DELTA`/`OPTIONS_STOP_PCT`/
  `OPTIONS_MAX_IV_VS_ATM` for the options overlay
- `.github/workflows/live-signals.yml`, `live-signals-us.yml`,
  `live-signals-crypto.yml` (redundant GH Actions backstop calls -
  `live-signals-us.yml`'s `OPT_COMMON` block is the options backstop)
- `/dry-run-day`, `/trade-view`, `/live` default query params in their own
  fetch calls
