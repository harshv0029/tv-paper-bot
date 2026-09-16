"""
Kotak Neo F&O per-strike candle feed - background WebSocket consumer for
the ATM +/- 15 strike band (NIFTY/BANKNIFTY/SENSEX, weekly+monthly,
calls+puts) plus each underlying's near-month future.

Explicit user instruction (2026-09-16): run the existing trading
algorithms on EACH option strike's OWN premium candlestick history, not
just the underlying's price action - see nse_fo_chain.
select_atm_banded_option_strikes's own docstring (DEFAULT_ATM_STRIKE_BAND)
for the capacity math this ATM+/-15 band was chosen against (Kotak's
WebSocket max_subscriptions=3000 cap).

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
import time
from contextlib import closing

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
}

_feed_status = {
    "connected": False,
    "last_error": None,
    "started_at_utc": None,
    "subscribed_instruments": 0,
    "universe_resolved_at_utc": None,
    "unresolved_legs": [],
}

# {instrument_token: {"bucket_start_ts", "open", "high", "low", "close", "tick_count"}}
_in_progress_candles: dict = {}

RESTART_BACKOFF_MIN_SECONDS = 60
RESTART_BACKOFF_MAX_SECONDS = 900  # 15 min ceiling - same reasoning as kotak_live_feed.py

# Universe re-resolved at most this often (ATM shifts as spot moves
# intraday, and expiries roll weekly) - not on every reconnect, to avoid
# hammering search_scrip on a flaky connection the way
# kotak_live_feed.py's own TOKEN_MAP_CACHE_TTL fix addressed for equities.
UNIVERSE_REFRESH_SECONDS = 4 * 60 * 60  # 4h
_universe_cache = {"value": None, "resolved_at": 0.0}


def get_feed_status() -> dict:
    return dict(_feed_status)


def _spot_price(cash_symbol: str):
    import main  # deferred - avoids a circular import at module load time
    try:
        df = main.fetch_ohlc(cash_symbol, "1d", "5m")
        return float(df["Close"].iloc[-1]) if df is not None and len(df) else None
    except Exception:
        return None


def resolve_fo_universe() -> dict:
    """{(exchange_segment, instrument_token): descriptor} for every
    ATM+/-15 option leg (both rights, both expiry classes) plus the
    near-month future, across all three underlyings. descriptor: {"kind":
    "option"|"future", "underlying", "right", "strike", "expiry",
    "expiry_class", "kotak_trading_symbol", "lot_size"}. A leg that fails
    to resolve (bad spot fetch, no matching contract, etc.) is silently
    skipped and recorded in _feed_status["unresolved_legs"] - never
    raises, matching kotak_live_feed.resolve_tokens's own
    one-hiccup-doesn't-take-down-everything-else discipline."""
    universe = {}
    unresolved = []
    for cash_symbol, kotak_name in FO_CANDLE_UNDERLYINGS.items():
        spot = _spot_price(cash_symbol)
        if spot is None or spot <= 0:
            unresolved.append(f"{kotak_name}:spot_unavailable")
            continue

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
            for expiry_class in ("weekly", "monthly"):
                band, err = nse_fo_chain.select_atm_banded_option_strikes(
                    kotak_name, spot, right, expiry_class,
                )
                if err:
                    unresolved.append(f"{kotak_name}:{right}:{expiry_class}:{err}")
                    continue
                for leg in band:
                    key = (leg["exchange_segment"], leg["instrument_token"])
                    universe[key] = {
                        "kind": "option", "underlying": kotak_name, "right": right,
                        "strike": leg["strike"], "expiry": leg["expiry"], "expiry_class": expiry_class,
                        "kotak_trading_symbol": leg["kotak_trading_symbol"], "lot_size": leg["lot_size"],
                    }
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
            cache_age = time.time() - _universe_cache["resolved_at"]
            if _universe_cache["value"] is None or cache_age > UNIVERSE_REFRESH_SECONDS:
                universe = resolve_fo_universe()
                _universe_cache["value"] = universe
                _universe_cache["resolved_at"] = time.time()
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
            client = kotak_neo.login()

            async with client.create_websocket() as ws:
                await ws.subscribe_scrips(ws_tokens)
                _feed_status["connected"] = True
                _feed_status["started_at_utc"] = time.time()
                _feed_status["last_error"] = None
                backoff = RESTART_BACKOFF_MIN_SECONDS
                async for message in ws:
                    if isinstance(message, SFeedScrip):
                        key = (message.exchange_segment, str(message.instrument_token))
                        descriptor = universe.get(key)
                        if descriptor is None:
                            continue
                        with closing(main.get_db()) as conn:
                            apply_tick(
                                str(message.instrument_token), message.last_traded_price,
                                time.time(), descriptor, conn=conn,
                            )
        except Exception as e:
            _feed_status["connected"] = False
            _feed_status["last_error"] = str(e)

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, RESTART_BACKOFF_MAX_SECONDS)
