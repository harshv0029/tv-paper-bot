"""
Kotak Neo F&O per-strike candle feed - background WebSocket consumer for
two universes at two different band sizes, sized to jointly fit under
Kotak's WebSocket max_subscriptions=3000 cap alongside the existing
206-symbol equity feed:
  - 3 index underlyings (NIFTY/BANKNIFTY/SENSEX) at
    nse_fo_chain.DEFAULT_ATM_STRIKE_BAND (15), weekly+monthly, calls+puts
  - all 210 nse_fo_chain.STOCK_FO_UNDERLYINGS at STOCK_ATM_STRIKE_BAND
    (2), monthly only, calls+puts
plus each underlying's near-month future, across both universes.

Explicit user instruction (2026-09-16): run the existing trading
algorithms on EACH option strike's OWN premium candlestick history, not
just the underlying's price action - see nse_fo_chain.
select_atm_banded_option_strikes's own docstring (DEFAULT_ATM_STRIKE_BAND)
and STOCK_ATM_STRIKE_BAND's own comment below for the capacity math both
band sizes were chosen against, worked out live with the user
step by step (180 stocks -> a real live-confirmed 210 -> band=5 monthly-
only still over the cap -> band=2 monthly-only lands at 2,894 of 3,000).

ISOLATED from kotak_live_feed.py on purpose: that module's ticks are
explicitly display-only, never feeding a trading decision (see its own
module docstring). This feed's ticks WILL eventually feed real trading
decisions via the candle aggregation below, so it gets its own WebSocket
connection, its own background task, and its own failure isolation - a
crash/reconnect here must never touch the equity display feed, and vice
versa (same "isolated from the scheduler's own task" reasoning
kotak_live_feed.py already documents for itself).

Historical data reality (documented at length elsewhere in this repo for
equities/underlying indices): Kotak's Trade API has NO historical/candle
endpoint for ANYTHING, options included. This feed is the ONLY source of
candle history for these instruments - it starts genuinely empty on
first deploy and accumulates forward tick by tick. A strategy needing N
bars of history will report "insufficient data" for however long it
takes N intervals to actually accumulate after this feed first connects
- there is no faster path, no synthetic backfill, no historical option
premium data exists to seed it with.

Persistence: only a COMPLETED candle (its bucket has closed) is written
to fo_option_candles - an in-progress candle live in memory at the
moment of a restart is lost, not persisted-then-resumed. Same risk
tolerance this app already accepts for kotak_live_feed.py's ticks and
for Render's own free-tier "suspends on inactivity" reality - adding
partial-candle persistence would cost real complexity for a candle
interval (5 min) that's a small fraction of a trading day.
"""
import asyncio
import concurrent.futures
import time
from contextlib import closing

import pandas as pd

import kotak_live_feed
import kotak_neo
import nse_fo_chain

CANDLE_INTERVAL_SECONDS = 300  # 5-minute bars - matches this app's dominant intraday bar size

# cash_symbol (for spot, via fetch_ohlc) -> Kotak pSymbolName - explicit
# user request 2026-09-16 was NIFTY/BANKNIFTY/SENSEX specifically, not
# the MCX commodities FO_MONITORED_UNDERLYINGS (main.py) also covers.
FO_CANDLE_UNDERLYINGS = {
    "^NSEI": "NIFTY",
    "^NSEBANK": "BANKNIFTY",
    "^BSESN": "SENSEX",
    # 2026-10-08, explicit user request: add FINNIFTY and MIDCPNIFTY. No
    # WATCHLIST/yfinance index symbol, so the spot is read from the Kotak
    # future's LTP (see _spot_price_for). Their weekly series no longer
    # exists on NSE; an unresolved class is simply recorded and skipped.
    "FINNIFTY_SPOT": "FINNIFTY",
    "MIDCPNIFTY_SPOT": "MIDCPNIFTY",
}
# 2026-10-08, explicit user request: monitor and trade 10 strikes ITM + 10 OTM
# (+ ATM) on both calls and puts, for every index underlying. 5 indices x 21
# strikes x 2 rights x 2 expiry classes = 420 legs (was 372), still inside
# the 3000-subscription cap (2,310 stock + 206 equity + 420 = 2,936).
INDEX_ATM_STRIKE_BAND = 10
INDEX_EXPIRY_CLASSES = ("weekly", "monthly")

# Single-stock F&O (2026-09-16, explicit user request: "Update this to
# all tickers Not just equity"). Capacity math worked out live against
# Kotak's WebSocket max_subscriptions=3000 cap, shared with the existing
# 206-symbol equity feed and the 378 index F&O legs above: 210 stocks x
# (2*STOCK_ATM_STRIKE_BAND+1) strikes x 2 rights x 1 expiry class (see
# STOCK_EXPIRY_CLASSES) + 210 futures = 2,310, leaving the combined total
# at 2,894 of 3,000 - fits, with essentially no headroom to spare (106
# free). Both numbers were explicitly chosen this tight by the user after
# seeing the real arithmetic - do not widen either without redoing this
# capacity math first (a wider band or a second expiry class on the
# stock leg alone would blow through the cap given 210 stocks).
#
# monthly-only (not weekly+monthly like the index legs): halves the
# stock leg's subscription cost outright, the single largest lever
# available before the count itself became the deciding constraint.
STOCK_ATM_STRIKE_BAND = 2
STOCK_EXPIRY_CLASSES = ("monthly",)

_feed_status = {
    # B-902: where the feed currently is (waiting_lock / resolving_universe / logging_in /
    # subscribing / streaming), so a feed stuck at connected=false shows WHERE.
    "phase": "starting",
    "phase_since_utc": None,
    "resolve_progress": None,
    "connected": False,
    "last_error": None,
    "started_at_utc": None,
    "subscribed_instruments": 0,
    "universe_resolved_at_utc": None,
    "unresolved_legs": [],
    # B-865 diagnostics (read-only): is the socket actually delivering ticks?
    "connect_count": 0,
    "ticks_received": 0,
    "last_tick_ts": None,
    "last_disconnect_reason": None,
    "refresh_reconnects": 0,
}

# {instrument_token: {"bucket_start_ts", "open", "high", "low", "close", "tick_count"}}
_in_progress_candles: dict = {}

RESTART_BACKOFF_MIN_SECONDS = 60
RESTART_BACKOFF_MAX_SECONDS = 900  # 15 min ceiling - same reasoning as kotak_live_feed.py

# Hard ceiling on one resolve_fo_universe() call (2026-09-16, live
# incident) - see run_fo_candle_feed's own asyncio.wait_for comment for
# why this must be bounded now that it runs under a lock shared with
# kotak_live_feed.py.
#
# 2026-09-21, raised 180 -> 600: live diagnostics this session (see
# /kotak-neo/fo-candle-feed-status checks throughout 2026-09-21) showed
# this resolve NEVER ONCE completing at 180s - connected stayed false,
# subscribed_instruments stayed 0, indefinitely, every cycle. This
# function makes ~1,000+ genuinely sequential network calls per resolve
# (210 yfinance spot lookups + up to ~645 Kotak search_scrip calls across
# future+call+put legs), which the 180s budget never actually covered
# under real network conditions, comment above notwithstanding. A
# same-session attempt to fix this via ThreadPoolExecutor parallelism
# instead (8, then 3, concurrent workers) triggered a live Render OOM
# crash-loop and was reverted - see this file's git history around
# 2026-09-21 for that incident. This is the deliberately conservative
# follow-up: stay fully sequential (no concurrency, no change to memory
# profile - only one HTTP response/DataFrame alive at a time, same as
# before this session started), and instead give the serial resolve
# enough wall-clock time to actually finish. 600s is a generous estimate,
# not measured against real production timing (no Render log access this
# session) - needs live validation before being trusted as final; if a
# full serial resolve still doesn't complete inside this window, the
# actual per-call latency needs to be measured directly (e.g. instrument
# _resolve_underlying_legs/_spot_price to log elapsed time), not another
# blind timeout bump. Safe to run this long: resolve_fo_universe() runs
# via asyncio.to_thread (see run_fo_candle_feed below), so a long resolve
# does not block the event loop or Render's own health check - Render
# staying responsive during this window was already confirmed by the
# 2026-09-16 asyncio.to_thread fix, unrelated to this specific ceiling.
FO_UNIVERSE_RESOLVE_TIMEOUT_SECONDS = 600

# 2026-09-21, second live finding the same evening: asyncio.wait_for
# does NOT stop the asyncio.to_thread worker thread on timeout - it only
# stops WAITING for it (documented asyncio behavior; a ThreadPoolExecutor
# job already running can't be cancelled from outside). Confirmed live:
# after a wait_for timeout fired, this module's own unresolved_legs was
# found fully populated for all 213 underlyings several minutes later -
# the "cancelled" resolve had kept running to completion the whole time,
# its real result silently discarded, while main._heavy_startup_resolve_
# lock had ALREADY been released (it's only held around the wait_for
# call, not around the orphaned thread it abandons) - so the NEXT cycle
# could start a fresh resolve while the previous one was still running
# unprotected. resolve_fo_universe(deadline=...) now checks its own
# budget cooperatively between underlyings and stops ITSELF, so in the
# normal case wait_for's outer timeout should never even fire. This
# grace margin is deliberately small (not doubled or generous) - if the
# cooperative deadline is working, wait_for firing at all here means
# something is stuck mid-underlying (a single hung network call, the
# one case cooperative checking between underlyings can't catch), which
# is exactly the genuine-hang case wait_for still exists to bound.
FO_UNIVERSE_RESOLVE_GRACE_SECONDS = 60

# Universe re-resolved at most this often (ATM shifts as spot moves
# intraday, and expiries roll weekly) - not on every reconnect, to avoid
# hammering search_scrip on a flaky connection the way
# kotak_live_feed.py's own TOKEN_MAP_CACHE_TTL fix addressed for equities.
UNIVERSE_REFRESH_SECONDS = 4 * 60 * 60  # 4h
_universe_cache = {"value": None, "resolved_at": 0.0, "partial": False}
# B-1388: the full (index + 210 stock) resolve runs in the background while the socket streams; the stream
# reconnects onto the new universe once it lands, instead of going dark for the ~10-min resolve.
_bg_resolve = {"task": None, "failed_at": 0.0, "swapped": False}
BG_RESOLVE_RETRY_SECONDS = 5 * 60
INDEX_ONLY_RESOLVE_TIMEOUT_SECONDS = 180

# Live finding (2026-09-22): STOCK_FO_UNDERLYINGS is a fixed alphabetical
# tuple and resolve_fo_universe() always walked it start-to-end - so once
# a resolve hit its deadline partway through (confirmed live: ~146/210
# stocks resolved before 600s ran out), the SAME ~64 alphabetically-last
# names (PAGEIND..ZYDUSLIFE) were skipped as "deadline_exceeded" on every
# single 4h refresh forever, never once getting a turn. This offset
# rotates the stock loop's own starting point forward by however many
# stocks got a real attempt last cycle, so the next cycle picks up where
# the last one left off instead of restarting at "360ONE" every time.
_stock_resolve_offset = {"value": 0}


# B-865: while the websocket stays connected the top-of-loop refresh check in
# run_fo_candle_feed never runs again (the loop only iterates on a disconnect),
# so the 4h ATM refresh and the expiry roll were silently skipped for as long
# as the socket lived. The message loop now asks this each tick.
INDEX_UNDERLYING_NAMES = tuple(FO_CANDLE_UNDERLYINGS.values())
# A universe missing an index underlying (spot lookup failed at resolve time)
# is re-resolved after this much, not after the full 4h.
INCOMPLETE_UNIVERSE_RETRY_SECONDS = 5 * 60


def universe_missing_index_underlyings(universe) -> list:
    have = {d.get("underlying") for d in (universe or {}).values()}
    return [n for n in INDEX_UNDERLYING_NAMES if n not in have]


def universe_refresh_due(now=None, universe=None, resolved_at=None) -> bool:
    """True when the cached universe should be re-resolved now: older than
    UNIVERSE_REFRESH_SECONDS, expiry-rolled, or (B-865) missing an index
    underlying and older than INCOMPLETE_UNIVERSE_RETRY_SECONDS."""
    now = time.time() if now is None else now
    uni = _universe_cache["value"] if universe is None else universe
    ts = _universe_cache["resolved_at"] if resolved_at is None else resolved_at
    if uni is None:
        return True
    age = now - ts
    if age > UNIVERSE_REFRESH_SECONDS:
        return True
    if universe_needs_expiry_roll(universe=uni, resolved_at=ts):
        return True
    if age > INCOMPLETE_UNIVERSE_RETRY_SECONDS and universe_missing_index_underlyings(uni):
        return True
    return False


def get_feed_status() -> dict:
    return dict(_feed_status)


def _ist_today():
    import datetime as _dt
    return (_dt.datetime.utcnow() + _dt.timedelta(hours=5, minutes=30)).date()


def universe_needs_expiry_roll(today=None, universe=None, resolved_at=None) -> bool:
    """True when the cached universe must be re-resolved NOW because of
    expiry rollover (2026-10-08, user: weekly expiry strikes are removed and
    added as per their expiry date): it holds a leg whose expiry is already
    past, or it was resolved on an earlier IST day (so a new weekly series
    that opened since is picked up, and expired ones drop out) - instead of
    waiting for the 4-hour timer."""
    import datetime as _dt
    today = today or _ist_today()
    uni = _universe_cache["value"] if universe is None else universe
    if not uni:
        return False
    ts = _universe_cache["resolved_at"] if resolved_at is None else resolved_at
    resolved_day = (_dt.datetime.utcfromtimestamp(ts) + _dt.timedelta(hours=5, minutes=30)).date()
    if resolved_day < today:
        return True
    for d in uni.values():
        try:
            if d.get("expiry") and _dt.date.fromisoformat(str(d["expiry"])[:10]) < today:
                return True
        except ValueError:
            continue
    return False


def get_cached_fo_universe() -> dict:
    """{(exchange_segment, instrument_token): descriptor} as last resolved
    by run_fo_candle_feed's own resolve_fo_universe() call (see that
    function's docstring for the descriptor shape) - {} if the feed
    hasn't resolved a universe yet (e.g. right after a restart, before
    the background task's first loop iteration completes). Read-only
    snapshot for callers (the RSI2 paper-position scan in main.py) that
    need to iterate the same leg set the feed is actually subscribed to,
    without reaching into this module's private _universe_cache
    directly."""
    return dict(_universe_cache["value"] or {})


def _spot_price(cash_symbol: str):
    import main  # deferred - avoids a circular import at module load time
    if cash_symbol.endswith("_SPOT"):  # index with no yfinance symbol: use the Kotak future's LTP
        try:
            fut, _err = nse_fo_chain.select_nse_future(cash_symbol[:-5])
            if not fut:
                return None
            q = kotak_neo.quotes([{"instrument_token": str(fut["instrument_token"]),
                                   "exchange_segment": fut["exchange_segment"]}], quote_type="ltp")
            v = nse_fo_chain._extract_ltp(q)
            return float(v) if v and v > 0 else None
        except Exception:
            return None
    try:
        df = main.fetch_ohlc(cash_symbol, "1d", "5m")
        return float(df["Close"].iloc[-1]) if df is not None and len(df) else None
    except Exception:
        return None


def _resolve_underlying_legs(kotak_name: str, spot: float, band: int, expiry_classes: tuple,
                              universe: dict, unresolved: list):
    """Resolves one underlying's future + option legs into `universe`
    (mutated in place), recording any failure in `unresolved` - shared by
    both the index legs (band=DEFAULT_ATM_STRIKE_BAND, both expiry
    classes) and the single-stock legs (band=STOCK_ATM_STRIKE_BAND,
    monthly only) below, so the two universes are resolved identically
    apart from those parameters."""
    fut, err = nse_fo_chain.select_nse_future(kotak_name)
    if fut:
        key = (fut["exchange_segment"], fut["instrument_token"])
        universe[key] = {
            "kind": "future", "underlying": kotak_name, "right": None, "strike": None,
            "expiry": fut["expiry"], "expiry_class": None,
            "kotak_trading_symbol": fut["kotak_trading_symbol"], "lot_size": fut["lot_size"],
        }
    else:
        unresolved.append(f"{kotak_name}:future:{err}")

    for right in ("call", "put"):
        for expiry_class in expiry_classes:
            leg_band, err = nse_fo_chain.select_atm_banded_option_strikes(
                kotak_name, spot, right, expiry_class, band=band,
            )
            if err:
                unresolved.append(f"{kotak_name}:{right}:{expiry_class}:{err}")
                continue
            for leg in leg_band:
                key = (leg["exchange_segment"], leg["instrument_token"])
                universe[key] = {
                    "kind": "option", "underlying": kotak_name, "right": right,
                    "strike": leg["strike"], "expiry": leg["expiry"], "expiry_class": expiry_class,
                    "kotak_trading_symbol": leg["kotak_trading_symbol"], "lot_size": leg["lot_size"],
                }


def resolve_fo_universe(deadline: float | None = None, stock_offset: int = 0,
                         previous_universe: dict | None = None, index_only: bool = False) -> dict:
    """{(exchange_segment, instrument_token): descriptor} for every leg
    this feed subscribes to: the 3 index underlyings at
    nse_fo_chain.DEFAULT_ATM_STRIKE_BAND (weekly+monthly) plus all 210
    STOCK_FO_UNDERLYINGS at STOCK_ATM_STRIKE_BAND (monthly only) - see
    that constant's own comment for the capacity math both band sizes
    were chosen against. descriptor: {"kind": "option"|"future",
    "underlying", "right", "strike", "expiry", "expiry_class",
    "kotak_trading_symbol", "lot_size"}. A leg that fails to resolve (bad
    spot fetch, no matching contract, etc.) is silently skipped and
    recorded in _feed_status["unresolved_legs"] - never raises, matching
    kotak_live_feed.resolve_tokens's own one-hiccup-doesn't-take-down-
    everything-else discipline.

    `stock_offset` (2026-09-22 live finding, see _stock_resolve_offset's
    own comment above): rotates where the STOCK_FO_UNDERLYINGS loop below
    starts, so a deadline that cuts a resolve short doesn't strand the
    same alphabetical tail unresolved on every cycle forever. 0 (the
    default) walks the tuple in its normal order, unchanged for any
    caller that doesn't pass it.

    `previous_universe` (optional, the prior cycle's return value): legs
    for a stock underlying this call never got to attempt (skipped
    straight to "deadline_exceeded" below) are carried forward from here
    instead of being dropped to zero - a stock that resolved fine two
    cycles ago and simply wasn't its turn this cycle should stay
    subscribed, not flap in and out based on where the rotation happens
    to be. An underlying this call DID attempt always uses this call's
    own fresh result (even if that result is worse, e.g. a contract that
    genuinely stopped existing) - never a stale mix of old-and-new legs
    for the same name.

    `deadline` (a time.time()-style timestamp, optional - None means run
    to completion regardless of how long it takes, the old behavior,
    still the default for direct/test callers): 2026-09-21 live finding -
    run_fo_candle_feed wraps this call in asyncio.wait_for(), but that
    only stops WAITING on timeout, it does NOT stop the underlying
    to_thread worker thread (documented asyncio behavior - a
    ThreadPoolExecutor job already running can't be cancelled from
    outside). Confirmed live: after a wait_for timeout, this function's
    own unresolved_legs still showed up fully populated for all 213
    underlyings minutes later - the "cancelled" resolve had kept running
    the whole time, its real work silently thrown away, while
    main._heavy_startup_resolve_lock had ALREADY been released (it's
    only held around the wait_for call, not around this function's own
    orphaned thread) - meaning a new resolve could start on the next
    cycle while the old one was still running unprotected, network calls
    and memory both. `deadline` makes this function cooperatively check
    its OWN budget between underlyings (not mid-call - a single hung
    network call still needs the outer wait_for as a backstop) and stop
    itself, returning whatever it resolved so far, instead of running on
    indefinitely after nobody's still waiting for it."""
    universe = {}
    unresolved = []

    for cash_symbol, kotak_name in FO_CANDLE_UNDERLYINGS.items():
        if deadline is not None and time.time() >= deadline:
            unresolved.append(f"{kotak_name}:deadline_exceeded")
            continue
        _feed_status["resolve_progress"] = {"done": 0, "of": 0, "last": kotak_name, "at": time.time()}
        spot = _spot_price(cash_symbol)
        if spot is None or spot <= 0:
            unresolved.append(f"{kotak_name}:spot_unavailable")
            continue
        _resolve_underlying_legs(
            kotak_name, spot, INDEX_ATM_STRIKE_BAND, INDEX_EXPIRY_CLASSES,
            universe, unresolved,
        )

    if index_only:
        # B-1388: cold-start fast path - index legs only, so the socket connects in about a minute; the stock
        # legs follow from a background resolve while streaming (_background_full_resolve).
        _feed_status["unresolved_legs"] = unresolved + ["stocks:deferred_to_background_resolve"]
        return universe

    stock_underlyings = nse_fo_chain.STOCK_FO_UNDERLYINGS
    n_stocks = len(stock_underlyings)
    stock_offset = stock_offset % n_stocks if n_stocks else 0
    deadline_exceeded_stocks = set()
    for i in range(n_stocks):
        kotak_name = stock_underlyings[(stock_offset + i) % n_stocks]
        if deadline is not None and time.time() >= deadline:
            unresolved.append(f"{kotak_name}:deadline_exceeded")
            deadline_exceeded_stocks.add(kotak_name)
            continue
        _feed_status["resolve_progress"] = {"done": i, "of": n_stocks, "last": kotak_name, "at": time.time()}
        spot = _spot_price(f"{kotak_name}.NS")
        if spot is None or spot <= 0:
            unresolved.append(f"{kotak_name}:spot_unavailable")
            continue
        _resolve_underlying_legs(
            kotak_name, spot, STOCK_ATM_STRIKE_BAND, STOCK_EXPIRY_CLASSES,
            universe, unresolved,
        )

    if previous_universe:
        for key, descriptor in previous_universe.items():
            if descriptor.get("underlying") in deadline_exceeded_stocks and key not in universe:
                universe[key] = descriptor

    _feed_status["unresolved_legs"] = unresolved
    return universe


def _bucket_start(ts: float) -> float:
    return (ts // CANDLE_INTERVAL_SECONDS) * CANDLE_INTERVAL_SECONDS


def _persist_candle(conn, instrument_token: str, descriptor: dict, bar: dict):
    conn.execute(
        "INSERT OR IGNORE INTO fo_option_candles (instrument_token, kotak_trading_symbol, underlying, "
        "kind, right, strike, expiry, bucket_start_ts, open, high, low, close, tick_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            instrument_token, descriptor["kotak_trading_symbol"], descriptor["underlying"],
            descriptor["kind"], descriptor["right"], descriptor["strike"], descriptor["expiry"],
            bar["bucket_start_ts"], bar["open"], bar["high"], bar["low"], bar["close"], bar["tick_count"],
        ),
    )
    conn.commit()


def apply_tick(instrument_token: str, price: float, ts: float, descriptor: dict, conn=None) -> dict | None:
    """Pure-ish candle-aggregation step, factored out of the websocket
    loop so it's unit-testable without a live connection. Updates
    _in_progress_candles in place; when `ts` crosses into a new bucket,
    the just-completed bar is persisted (if `conn` given) and returned -
    otherwise returns None. Never raises on a bad price/ts (skips the
    tick) - a single malformed message must never kill the feed."""
    if price is None or price <= 0:
        return None
    bucket = _bucket_start(ts)
    existing = _in_progress_candles.get(instrument_token)
    completed = None

    if existing is None or existing["bucket_start_ts"] != bucket:
        if existing is not None:
            completed = dict(existing)
            if conn is not None:
                _persist_candle(conn, instrument_token, descriptor, completed)
        _in_progress_candles[instrument_token] = {
            "bucket_start_ts": bucket, "open": price, "high": price, "low": price,
            "close": price, "tick_count": 1,
        }
    else:
        existing["high"] = max(existing["high"], price)
        existing["low"] = min(existing["low"], price)
        existing["close"] = price
        existing["tick_count"] += 1

    return completed


def process_fo_ticks(messages, universe: dict, scrip_cls) -> int:
    """B-1382: apply a batch of feed messages to the in-progress candles. One DB connection per batch, opened only
    if some tick closes its instrument's candle. Returns how many ticks were applied."""
    now = time.time()
    bucket = _bucket_start(now)
    conn = None
    applied = 0
    try:
        for message in messages:
            if not isinstance(message, scrip_cls):
                continue
            _feed_status["ticks_received"] += 1
            _feed_status["last_tick_ts"] = now
            tok = str(message.instrument_token)
            descriptor = universe.get((message.exchange_segment, tok))
            if descriptor is None:
                continue
            existing = _in_progress_candles.get(tok)
            if conn is None and existing is not None and existing["bucket_start_ts"] != bucket:
                import main
                conn = main.get_db()
            apply_tick(tok, message.last_traded_price, now, descriptor, conn=conn)
            applied += 1
    finally:
        if conn is not None:
            conn.close()
    return applied


MIN_BARS_FOR_SIGNAL_CHECK = 40  # see read_fo_candles_as_df's own docstring


def read_fo_candles_as_df(instrument_token: str) -> pd.DataFrame | None:
    """Every COMPLETED candle for `instrument_token` from fo_option_candles,
    shaped exactly like data_fetch.fetch_ohlc's own return value (Date/
    Open/High/Low/Close/Volume columns, oldest-first, integer
    RangeIndex) so any existing strategy function in main.py can run
    against it completely unmodified. Returns None if this instrument
    has zero completed candles yet - never an empty DataFrame, so a
    caller can use a plain `if df is None` check the same way every
    fetch_ohlc call site already does for "no data".

    Volume here is `tick_count` (this contract's own per-bar Kotak tick
    count), NOT real traded volume or open interest - Kotak's live
    quotes()/WebSocket feed exposes neither for F&O (see the "KNOWN GAP"
    comment above FO_MONITORED_UNDERLYINGS in main.py; this module's
    tick-driven candles inherit that same gap). A reasonable liquidity-
    ish proxy - more ticks in an interval roughly tracks more trading
    activity - but must never be read as literal contracts traded, same
    disclosed-proxy-not-a-guess discipline kotak_live_feed.py's own MCX
    price-proxy futures already established.

    MIN_BARS_FOR_SIGNAL_CHECK exists here as a documented constant, not
    because this function enforces it (it returns whatever history
    exists, however short) - individual F&O contracts have
    fundamentally SHORT, DISCONTINUOUS candle histories compared to an
    underlying equity/index: a contract drops out of the ATM band (and
    stops accumulating new candles) the moment spot moves it out of
    range on the next universe re-resolution, and every contract expires
    outright within weeks (weekly options) to a couple months (monthly
    options, the only class kept for single stocks). Strategies needing
    deep lookbacks (e.g. a 50/200-bar SMA crossover) will realistically
    never accumulate enough history on any single contract's own candles
    to fire at all - this is a real constraint on which existing
    strategy functions make sense to wire against this data source, not
    a bug in this reader."""
    import main  # deferred - avoids a circular import at module load time
    with closing(main.get_db()) as conn:
        rows = conn.execute(
            "SELECT bucket_start_ts, open, high, low, close, tick_count "
            "FROM fo_option_candles WHERE instrument_token = ? ORDER BY bucket_start_ts ASC",
            (instrument_token,),
        ).fetchall()
    if not rows:
        return None
    df = pd.DataFrame(
        [dict(r) for r in rows],
    ).rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close", "tick_count": "Volume",
    })
    df["Date"] = pd.to_datetime(df["bucket_start_ts"], unit="s", utc=True)
    return df[["Date", "Open", "High", "Low", "Close", "Volume"]].reset_index(drop=True)


def _set_phase(phase: str) -> None:
    _feed_status["phase"] = phase
    _feed_status["phase_since_utc"] = time.time()


async def _resolve_full_universe(main_mod):
    """The full resolve (heavy lock, deadline, stock-offset rotation), storing the result in _universe_cache."""
    stock_offset = _stock_resolve_offset["value"]
    async with main_mod._heavy_startup_resolve_lock:
        if _bg_resolve["task"] is None:
            _set_phase("resolving_universe")
        resolve_deadline = time.time() + FO_UNIVERSE_RESOLVE_TIMEOUT_SECONDS
        universe = await asyncio.wait_for(
            asyncio.to_thread(
                resolve_fo_universe, deadline=resolve_deadline,
                stock_offset=stock_offset, previous_universe=_universe_cache["value"],
            ),
            timeout=FO_UNIVERSE_RESOLVE_TIMEOUT_SECONDS + FO_UNIVERSE_RESOLVE_GRACE_SECONDS,
        )
    _universe_cache["value"] = universe
    _universe_cache["resolved_at"] = time.time()
    _universe_cache["partial"] = False
    n_stocks = len(nse_fo_chain.STOCK_FO_UNDERLYINGS)
    if n_stocks:
        stock_names = set(nse_fo_chain.STOCK_FO_UNDERLYINGS)
        deadline_exceeded = sum(
            1 for entry in _feed_status["unresolved_legs"]
            if entry.endswith(":deadline_exceeded")
            and entry[:-len(":deadline_exceeded")] in stock_names
        )
        attempted = n_stocks - deadline_exceeded
        _stock_resolve_offset["value"] = (stock_offset + attempted) % n_stocks
    return universe


async def _background_full_resolve(main_mod):
    try:
        await _resolve_full_universe(main_mod)
        _bg_resolve["swapped"] = True
    except Exception as e:
        _bg_resolve["failed_at"] = time.time()
        _feed_status["last_error"] = f"background resolve: {str(e) or type(e).__name__}"


def background_resolve_step(main_mod, now=None) -> bool:
    """B-1388, called per stream wake-up: starts the background full resolve when due (partial index-only
    universe, or universe_refresh_due) and not already running or recently failed. Returns True once a finished
    resolve has replaced the cached universe, so the caller reconnects onto it."""
    now = time.time() if now is None else now
    task = _bg_resolve["task"]
    if task is not None and task.done():
        _bg_resolve["task"] = None
        if _bg_resolve["swapped"]:
            _bg_resolve["swapped"] = False
            return True
        return False
    if task is None and (_universe_cache["partial"] or universe_refresh_due()) \
            and now - _bg_resolve["failed_at"] >= BG_RESOLVE_RETRY_SECONDS:
        _bg_resolve["task"] = asyncio.ensure_future(_background_full_resolve(main_mod))
        _feed_status["background_resolves"] = _feed_status.get("background_resolves", 0) + 1
    return False


async def run_fo_candle_feed():
    """The background task main.py's startup event launches alongside
    (never instead of) kotak_live_feed.run_feed. Runs forever until the
    process stops - resolve universe, connect, stream, aggregate, and on
    any failure wait (capped exponential backoff, same shape as
    kotak_live_feed.run_feed) before starting over."""
    import main  # deferred - see _spot_price's own comment

    backoff = RESTART_BACKOFF_MIN_SECONDS
    while True:
        try:
            if _universe_cache["value"] is None:
                # B-1388: cold start - index legs only (no heavy lock: a few calls), connect at once; the stock
                # legs arrive from the background resolve below while the socket streams.
                _set_phase("resolving_index_legs")
                universe = await asyncio.wait_for(
                    asyncio.to_thread(resolve_fo_universe, index_only=True,
                                      deadline=time.time() + INDEX_ONLY_RESOLVE_TIMEOUT_SECONDS),
                    timeout=INDEX_ONLY_RESOLVE_TIMEOUT_SECONDS + FO_UNIVERSE_RESOLVE_GRACE_SECONDS,
                )
                _universe_cache["value"] = universe
                _universe_cache["resolved_at"] = time.time()
                _universe_cache["partial"] = True
                if not universe:
                    # no index leg resolved (spot lookups failed): fall back to the full foreground resolve
                    _set_phase("waiting_lock")
                    universe = await _resolve_full_universe(main)
            elif _bg_resolve["task"] is None and (time.time() - _universe_cache["resolved_at"] > UNIVERSE_REFRESH_SECONDS
                                                  or universe_refresh_due()) and not _universe_cache["partial"]:
                # Not streaming (reconnect after a failure) and the universe is stale: resolve in the foreground
                # as before. While streaming, refreshes run in the background instead (background_resolve_step).
                _set_phase("waiting_lock")
                universe = await _resolve_full_universe(main)
            else:
                universe = _universe_cache["value"]
            _feed_status["subscribed_instruments"] = len(universe)
            _feed_status["universe_resolved_at_utc"] = _universe_cache["resolved_at"]

            if not universe:
                _feed_status["last_error"] = "No F&O instruments resolved - nothing to subscribe to"
                _feed_status["connected"] = False
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RESTART_BACKOFF_MAX_SECONDS)
                continue

            from neo_api_client.websocket.feed import WsToken, SFeedScrip

            ws_tokens = [WsToken(seg, tok) for (seg, tok) in universe]
            _set_phase("logging_in")
            client = kotak_neo.login()
            _set_phase("subscribing")

            async with client.create_websocket() as ws:
                await ws.subscribe_scrips(ws_tokens)
                _set_phase("streaming")
                _feed_status["connected"] = True
                _feed_status["started_at_utc"] = time.time()
                _feed_status["last_error"] = None
                _feed_status["connect_count"] += 1
                backoff = RESTART_BACKOFF_MIN_SECONDS
                refresh_now = False
                async for first in ws:
                    if background_resolve_step(main):
                        # B-865/B-1388: reconnect onto the freshly resolved universe (stock legs after a cold
                        # start, ATM drift, expiry roll); the resolve itself ran in the background while streaming.
                        refresh_now = True
                        break
                    # B-1382: take every queued tick in this wake-up (the SDK queue is unbounded) and open the DB
                    # only when a tick closes a candle, not once per tick.
                    process_fo_ticks(kotak_live_feed.drain_pending(ws, first), universe, SFeedScrip)
                # B-865: the stream ended without raising (SDK gave up
                # reconnecting, or we broke out for a refresh). The old code
                # left connected=True here, a stale "healthy" reading.
                _feed_status["connected"] = False
                if refresh_now:
                    _feed_status["refresh_reconnects"] += 1
                    _feed_status["last_disconnect_reason"] = "universe_refresh_due"
                    continue
                _feed_status["last_disconnect_reason"] = "stream_ended_without_error"
        except Exception as e:
            _feed_status["connected"] = False
            _feed_status["last_error"] = str(e) or type(e).__name__
            _feed_status["last_disconnect_reason"] = f"exception:{type(e).__name__}"

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, RESTART_BACKOFF_MAX_SECONDS)
