"""
Kotak Neo live tick feed - background WebSocket consumer.

Explicit user instruction (2026-09-04): stream real live ticks from Kotak
Neo via its SFeed WebSocket (kotakneoapi v3's create_websocket()/
subscribe_scrips(), confirmed real against the SDK's actual source before
building on it - see docs/TRADING_CONSTRAINTS.md "Kotak Neo connection").

This is DISPLAY data only. Nothing here feeds any strategy's entry/exit
decisions - those still run entirely on Yahoo Finance candle history,
which this feed cannot replace (Kotak's Trade API has no historical/
candle endpoint at all, documented at length elsewhere in this repo).
Also does NOT place, modify, or cancel any order - read-only market data,
same isolation-from-the-trading-engine rule as kotak_neo.py's other
functions.

Runs as a background asyncio task (see main.py's startup event),
completely isolated from the scheduler's own task - a crash or reconnect
loop here never affects paper-trading signal generation.

Render free-tier reality, stated plainly rather than glossed over: the
whole process suspends on inactivity, which kills this task along with
everything else. It isn't "always-on" in the strict sense - it's "on
whenever the app process itself is," restarting fresh (re-login,
re-resolve tokens, re-subscribe) each time a request wakes the app back
up, via the same startup event that launches it the first time.
"""
import asyncio
import time

import kotak_neo

# In-memory tick store - deliberately not persisted. This is live display
# data, stale the instant the process restarts, and nothing downstream
# needs it to survive a restart (unlike the journal-synced trading state).
# {watchlist_symbol: {"ltp": float, "trading_symbol": str,
#                      "instrument_token": str, "updated_at_utc": float}}
_live_ticks: dict = {}

_feed_status = {
    "connected": False,
    "last_error": None,
    "started_at_utc": None,
    "subscribed_symbols": [],
    "unresolved_symbols": [],
}

# After the SDK's own built-in initial-connect retries (max_connect_retries,
# default 3) are exhausted, or after a post-connect failure exhausts
# max_reconnect_attempts, this task waits before trying the whole
# login+resolve+connect sequence again from scratch - each attempt is a
# REAL TOTP login against the live account, so a sustained outage must
# never turn into a login every RESTART_BACKOFF_MIN_SECONDS for hours
# (found in a real-money risk review 2026-09-04) - backoff doubles on
# each consecutive failure, capped at RESTART_BACKOFF_MAX_SECONDS, and
# resets to the minimum the moment a connection actually succeeds.
RESTART_BACKOFF_MIN_SECONDS = 60
RESTART_BACKOFF_MAX_SECONDS = 900  # 15 min ceiling


def get_live_ticks() -> dict:
    """A snapshot copy - callers never get a reference into the live dict
    a background task is still mutating."""
    return dict(_live_ticks)


def get_feed_status() -> dict:
    return dict(_feed_status)


# Kotak's own literal, name-based instrument tokens for indices - NOT
# resolved via search_scrip (indices aren't equity rows in the nse_cm
# scrip master). "Nifty 50" is confirmed directly from the new SDK's own
# README example (WsToken("nse_cm", "Nifty 50")); "Nifty Bank" verified
# 2026-09-04 the same way every other Kotak claim this session was -
# against a real API response, not assumed from the naming pattern alone.
# SENSEX deliberately excluded: no equivalent confirmation found for a
# BSE index token, and guessing one risks silently subscribing to nothing
# or the wrong instrument.
_INDEX_TOKENS = {
    "^NSEI": ("nse_cm", "Nifty 50"),
    "^NSEBANK": ("nse_cm", "Nifty Bank"),
}


def _bare_nse_symbol(watchlist_symbol: str) -> str | None:
    """'RELIANCE.NS' -> 'RELIANCE'. None for anything that isn't a plain
    NSE equity ticker (indices, MCX proxies) - those are resolved
    differently or not at all (see resolve_tokens's docstring)."""
    if watchlist_symbol.endswith(".NS"):
        return watchlist_symbol[:-3]
    return None


# Explicit user-confirmed mapping (2026-09-04) - matches
# docs/TRADING_CONSTRAINTS.md's existing "Scope" section:
#   GC=F (COMEX Gold)      -> MCX GOLD
#   SI=F (COMEX Silver)    -> MCX SILVER
#   CL=F (NYMEX WTI Crude) -> MCX CRUDEOIL
# Exact pSymbolName - "gold" alone real-matched 4,287 rows on 2026-09-04
# across GOLD/GOLDM (mini)/GOLDGUINEA/GOLDTEN - different contracts, not
# variants of the same one, confirmed from real search_scrip data.
_MCX_SYMBOL_MAP = {"GC=F": "GOLD", "SI=F": "SILVER", "CL=F": "CRUDEOIL"}


def _resolve_mcx_tokens(client, watchlist_symbols: list) -> dict:
    """One search_scrip(exchange_segment="mcx_fo", symbol="") call for the
    WHOLE segment - confirmed from the SDK's own source that it downloads
    the full scrip-master CSV regardless of the `symbol` filter value (the
    filter is applied client-side, after download), so one unfiltered
    call costs the same as a filtered one and avoids downloading the same
    large CSV three times for three symbols.

    For each of GC=F/SI=F/CL=F, picks the real contract with the
    EARLIEST lExpiryDate that hasn't already passed - MCX futures have
    many concurrent expiry months per underlying (GOLD alone had 05Feb2027
    and 05Apr2027 contracts live simultaneously, confirmed 2026-09-04);
    the nearest one is the conventional "current" contract a price-action
    proxy should track."""
    wanted = {sym: _MCX_SYMBOL_MAP[sym] for sym in watchlist_symbols if sym in _MCX_SYMBOL_MAP}
    if not wanted:
        return {}
    try:
        all_mcx = client.search_scrip(exchange_segment="mcx_fo", symbol="")
    except Exception:
        return {}
    if not isinstance(all_mcx, list):
        return {}

    now_ts = time.time()
    nearest_by_kotak_name = {}
    for row in all_mcx:
        name = row.get("pSymbolName")
        if name not in wanted.values():
            continue
        exp = row.get("lExpiryDate")
        if not isinstance(exp, (int, float)) or exp <= now_ts:
            continue  # skip malformed rows and already-expired contracts
        current_best = nearest_by_kotak_name.get(name)
        if current_best is None or exp < current_best["lExpiryDate"]:
            nearest_by_kotak_name[name] = row

    resolved = {}
    for watchlist_sym, kotak_name in wanted.items():
        row = nearest_by_kotak_name.get(kotak_name)
        if row and row.get("pSymbol") is not None:
            resolved[watchlist_sym] = ("mcx_fo", str(row["pSymbol"]))
    return resolved


def resolve_tokens(client, watchlist_symbols: list) -> dict:
    """{watchlist_symbol: (exchange_segment, instrument_token)} for every
    symbol this feed can actually resolve a real Kotak instrument for.

    Indices: the literal names in _INDEX_TOKENS above.
    NSE equities ('*.NS'): ONE search_scrip(exchange_segment="nse_cm",
    symbol="") call for the WHOLE segment (not one call per symbol, which
    would re-download the entire scrip master CSV up to ~100 times - slow
    and wasteful), matched locally by EXACT pSymbolName - a substring
    match wrongly matched NIFTYFPI for "nifty" earlier the same day, so
    this uses '==', never .contains()/.str.contains().
    MCX proxies (GC=F/SI=F/CL=F): resolved via _resolve_mcx_tokens() - see
    its own docstring (explicit user-confirmed mapping to the real
    MCX GOLD/SILVER/CRUDEOIL contracts, nearest live expiry).

    Never raises - a segment whose search_scrip call itself fails just
    leaves those symbols unresolved (they show up in _feed_status's
    unresolved_symbols via run_feed's own check, not tracked in here), so
    one Kotak-side hiccup doesn't take down resolution for symbols in
    other segments.
    """
    resolved = {}

    for sym in watchlist_symbols:
        if sym in _INDEX_TOKENS:
            resolved[sym] = _INDEX_TOKENS[sym]

    nse_names = {}
    for sym in watchlist_symbols:
        bare = _bare_nse_symbol(sym)
        if bare:
            nse_names[bare] = sym

    if nse_names:
        try:
            all_nse_cm = client.search_scrip(exchange_segment="nse_cm", symbol="")
            if isinstance(all_nse_cm, list):
                by_name = {}
                for row in all_nse_cm:
                    name = row.get("pSymbolName")
                    if name and name not in by_name:  # first hit wins - EQ series is what WATCHLIST means
                        by_name[name] = row
                for bare_name, watchlist_sym in nse_names.items():
                    row = by_name.get(bare_name)
                    if row and row.get("pSymbol") is not None:
                        resolved[watchlist_sym] = ("nse_cm", str(row["pSymbol"]))
        except Exception:
            pass  # left unresolved - run_feed's own check reports this

    mcx_wanted = [sym for sym in watchlist_symbols if sym in _MCX_SYMBOL_MAP]
    if mcx_wanted:
        resolved.update(_resolve_mcx_tokens(client, mcx_wanted))

    return resolved


async def run_feed(watchlist_symbols: list):
    """The background task main.py's startup event launches. Runs forever
    (until the process itself stops) - login, resolve tokens, connect,
    stream, and on any failure wait (capped exponential backoff - see
    RESTART_BACKOFF_MIN/MAX_SECONDS above) and start the whole sequence
    over. See module docstring for the Render free-tier caveat this
    design accepts rather than hides."""
    backoff = RESTART_BACKOFF_MIN_SECONDS
    while True:
        try:
            client = kotak_neo.login()
            token_map = resolve_tokens(client, watchlist_symbols)
            _feed_status["subscribed_symbols"] = sorted(token_map.keys())
            _feed_status["unresolved_symbols"] = sorted(
                s for s in watchlist_symbols
                if s not in token_map
                and (s in _INDEX_TOKENS or _bare_nse_symbol(s) or s in _MCX_SYMBOL_MAP)
            )
            if not token_map:
                _feed_status["last_error"] = "No instrument tokens resolved - nothing to subscribe to"
                _feed_status["connected"] = False
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RESTART_BACKOFF_MAX_SECONDS)
                continue

            # WsToken/SFeedScrip import deferred to inside the function
            # (not module top-level) so a broken/missing kotakneoapi
            # install can't crash the whole app at import time - same
            # reasoning as kotak_neo.py's lazy `import kotak_neo` in
            # main.py's endpoints.
            from neo_api_client.websocket.feed import WsToken, SFeedScrip

            reverse_lookup = {}  # (exchange_segment, instrument_token) -> watchlist_symbol
            ws_tokens = []
            for watchlist_sym, (seg, tok) in token_map.items():
                ws_tokens.append(WsToken(seg, tok))
                reverse_lookup[(seg, tok)] = watchlist_sym

            async with client.create_websocket() as ws:
                await ws.subscribe_scrips(ws_tokens)
                _feed_status["connected"] = True
                _feed_status["started_at_utc"] = time.time()
                _feed_status["last_error"] = None
                backoff = RESTART_BACKOFF_MIN_SECONDS  # a real connection succeeded - reset the backoff
                async for message in ws:
                    if isinstance(message, SFeedScrip):
                        key = reverse_lookup.get((message.exchange_segment, str(message.instrument_token)))
                        if key:
                            _live_ticks[key] = {
                                "ltp": message.last_traded_price,
                                "trading_symbol": message.trading_symbol,
                                "instrument_token": str(message.instrument_token),
                                "updated_at_utc": time.time(),
                            }
        except Exception as e:
            _feed_status["connected"] = False
            _feed_status["last_error"] = str(e)

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, RESTART_BACKOFF_MAX_SECONDS)
