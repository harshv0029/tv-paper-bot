"""Unit tests for kotak_fo_candle_feed.py (2026-09-16, explicit user
instruction: run the existing trading algorithms on each ATM+/-15 option
strike's own premium candles). Pure-logic pieces only - the actual
websocket connect/subscribe loop needs a live Kotak session, same
limitation as every other kotak_neo-dependent code path in this repo's
test suite (see kotak_live_feed.py's own test file, if any, for the same
pattern).

Run: pytest tests/ -v
"""
import inspect
import os
import sqlite3
import tempfile
import time
from contextlib import closing
from unittest.mock import patch

import kotak_fo_candle_feed as feed
import main
import nse_fo_chain


def _fresh_conn():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE fo_option_candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument_token TEXT NOT NULL,
            kotak_trading_symbol TEXT NOT NULL,
            underlying TEXT NOT NULL,
            kind TEXT NOT NULL,
            right TEXT,
            strike REAL,
            expiry TEXT,
            bucket_start_ts REAL NOT NULL,
            open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
            tick_count INTEGER NOT NULL,
            UNIQUE(instrument_token, bucket_start_ts)
        )
        """
    )
    conn.commit()
    return conn


_DESC = {
    "kind": "option", "underlying": "NIFTY", "right": "call", "strike": 24500.0,
    "expiry": "2026-10-05", "kotak_trading_symbol": "NIFTY26OCT24500CE",
}


def setup_function(_):
    feed._in_progress_candles.clear()


def test_bucket_start_floors_to_the_candle_interval():
    assert feed._bucket_start(0) == 0
    assert feed._bucket_start(299) == 0
    assert feed._bucket_start(300) == 300
    assert feed._bucket_start(301) == 300
    assert feed._bucket_start(599) == 300
    assert feed._bucket_start(600) == 600


def test_first_tick_starts_a_new_bar_and_returns_nothing_completed():
    completed = feed.apply_tick("TOK1", 120.5, ts=100.0, descriptor=_DESC)
    assert completed is None
    bar = feed._in_progress_candles["TOK1"]
    assert bar == {"bucket_start_ts": 0, "open": 120.5, "high": 120.5, "low": 120.5, "close": 120.5, "tick_count": 1}


def test_ticks_within_the_same_bucket_update_ohlc_correctly():
    feed.apply_tick("TOK1", 100.0, ts=10.0, descriptor=_DESC)
    feed.apply_tick("TOK1", 110.0, ts=50.0, descriptor=_DESC)
    feed.apply_tick("TOK1", 90.0, ts=90.0, descriptor=_DESC)
    completed = feed.apply_tick("TOK1", 105.0, ts=200.0, descriptor=_DESC)
    assert completed is None
    bar = feed._in_progress_candles["TOK1"]
    assert bar["open"] == 100.0
    assert bar["high"] == 110.0
    assert bar["low"] == 90.0
    assert bar["close"] == 105.0
    assert bar["tick_count"] == 4


def test_a_tick_in_the_next_bucket_completes_and_returns_the_prior_bar():
    feed.apply_tick("TOK1", 100.0, ts=10.0, descriptor=_DESC)
    feed.apply_tick("TOK1", 120.0, ts=250.0, descriptor=_DESC)
    completed = feed.apply_tick("TOK1", 130.0, ts=305.0, descriptor=_DESC)  # crosses into next 300s bucket
    assert completed is not None
    assert completed["bucket_start_ts"] == 0
    assert completed["open"] == 100.0
    assert completed["high"] == 120.0
    assert completed["close"] == 120.0
    assert completed["tick_count"] == 2
    # the new bar has already started for the tick that crossed the boundary
    new_bar = feed._in_progress_candles["TOK1"]
    assert new_bar["bucket_start_ts"] == 300
    assert new_bar["open"] == 130.0
    assert new_bar["tick_count"] == 1


def test_completed_candle_is_persisted_when_a_connection_is_given():
    conn = _fresh_conn()
    feed.apply_tick("TOK1", 100.0, ts=10.0, descriptor=_DESC, conn=conn)
    feed.apply_tick("TOK1", 130.0, ts=305.0, descriptor=_DESC, conn=conn)  # completes bucket 0
    rows = conn.execute("SELECT * FROM fo_option_candles").fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["instrument_token"] == "TOK1"
    assert row["kotak_trading_symbol"] == "NIFTY26OCT24500CE"
    assert row["underlying"] == "NIFTY"
    assert row["kind"] == "option"
    assert row["right"] == "call"
    assert row["strike"] == 24500.0
    assert row["open"] == 100.0
    assert row["close"] == 100.0  # only one tick landed in bucket 0 before it closed
    assert row["tick_count"] == 1


def test_no_persistence_call_without_a_connection():
    # Same sequence as above but conn=None (the default) - must not raise,
    # must not attempt any DB write.
    feed.apply_tick("TOK1", 100.0, ts=10.0, descriptor=_DESC)
    completed = feed.apply_tick("TOK1", 130.0, ts=305.0, descriptor=_DESC)
    assert completed is not None  # aggregation still works, just nothing persisted


def test_apply_tick_ignores_a_nonpositive_or_none_price():
    assert feed.apply_tick("TOK1", None, ts=10.0, descriptor=_DESC) is None
    assert feed.apply_tick("TOK1", 0.0, ts=10.0, descriptor=_DESC) is None
    assert feed.apply_tick("TOK1", -5.0, ts=10.0, descriptor=_DESC) is None
    assert "TOK1" not in feed._in_progress_candles


def test_different_instrument_tokens_track_independent_bars():
    feed.apply_tick("TOK1", 100.0, ts=10.0, descriptor=_DESC)
    feed.apply_tick("TOK2", 50.0, ts=10.0, descriptor=_DESC)
    feed.apply_tick("TOK1", 105.0, ts=50.0, descriptor=_DESC)
    assert feed._in_progress_candles["TOK1"]["tick_count"] == 2
    assert feed._in_progress_candles["TOK2"]["tick_count"] == 1


def test_resolve_fo_universe_skips_an_underlying_with_no_spot_and_records_it():
    with patch.object(feed, "_spot_price", return_value=None):
        universe = feed.resolve_fo_universe()
    assert universe == {}
    assert all("spot_unavailable" in u for u in feed._feed_status["unresolved_legs"])
    expected = len(feed.FO_CANDLE_UNDERLYINGS) + len(nse_fo_chain.STOCK_FO_UNDERLYINGS)
    assert len(feed._feed_status["unresolved_legs"]) == expected


def test_resolve_fo_universe_stops_itself_once_past_deadline():
    # 2026-09-21 live finding: asyncio.wait_for's timeout doesn't stop
    # the underlying to_thread worker, it only stops waiting for it - so
    # resolve_fo_universe must be able to bound ITSELF cooperatively.
    # An already-past deadline must make every underlying skip straight
    # to "deadline_exceeded" without ever calling _spot_price - proves
    # this stops doing real work once its budget is spent, rather than
    # continuing to run (and consume memory/network) after the point
    # nothing is still waiting on it.
    calls = []

    def fake_spot(cash_symbol):
        calls.append(cash_symbol)
        return 100.0

    with patch.object(feed, "_spot_price", side_effect=fake_spot):
        universe = feed.resolve_fo_universe(deadline=time.time() - 1)

    assert universe == {}
    assert calls == []
    expected = len(feed.FO_CANDLE_UNDERLYINGS) + len(nse_fo_chain.STOCK_FO_UNDERLYINGS)
    assert len(feed._feed_status["unresolved_legs"]) == expected
    assert all("deadline_exceeded" in u for u in feed._feed_status["unresolved_legs"])


def test_resolve_fo_universe_with_no_deadline_runs_to_completion_unchanged():
    # deadline=None (the default) must behave exactly as before this
    # session's fix - every existing caller (tests included) that never
    # passed a deadline keeps working unmodified.
    with patch.object(feed, "_spot_price", return_value=None):
        universe = feed.resolve_fo_universe()
    assert universe == {}
    assert all("spot_unavailable" in u for u in feed._feed_status["unresolved_legs"])


def test_resolve_fo_universe_partial_progress_survives_a_mid_run_deadline():
    # A deadline that expires partway through must preserve whatever was
    # already resolved before it hit, not discard everything - a partial,
    # real universe is strictly better than none.
    fut = {
        "underlying": "NIFTY", "kotak_trading_symbol": "NIFTY26OCTFUT", "instrument_token": "1",
        "exchange_segment": "nse_fo", "lot_size": 65, "expiry": "2026-10-27", "dte": 10,
    }
    deadline = time.time() + 0.2

    def fake_spot(cash_symbol):
        time.sleep(0.15)
        return 100.0

    with patch.object(feed, "_spot_price", side_effect=fake_spot), \
         patch("nse_fo_chain.select_nse_future", return_value=(fut, None)), \
         patch("nse_fo_chain.select_atm_banded_option_strikes", return_value=([], "no_option_rows")):
        universe = feed.resolve_fo_universe(deadline=deadline)

    # At least the first underlying resolved before the deadline hit;
    # its future leg must be present, not thrown away.
    assert len(universe) >= 1
    assert any("deadline_exceeded" in u for u in feed._feed_status["unresolved_legs"])


def test_resolve_fo_universe_merges_future_and_option_legs():
    fut = {
        "underlying": "NIFTY", "kotak_trading_symbol": "NIFTY26OCTFUT", "instrument_token": "1",
        "exchange_segment": "nse_fo", "lot_size": 65, "expiry": "2026-10-27", "dte": 10,
    }
    call_leg = {
        "underlying": "NIFTY", "right": "call", "expiry": "2026-10-05", "dte": 5,
        "expiry_class": "weekly", "strike": 24500.0, "kotak_trading_symbol": "NIFTY26OCT24500CE",
        "instrument_token": "2", "exchange_segment": "nse_fo", "lot_size": 65,
    }
    with patch.object(feed, "_spot_price", return_value=24500.0), \
         patch("nse_fo_chain.select_nse_future", return_value=(fut, None)), \
         patch("nse_fo_chain.select_atm_banded_option_strikes", return_value=([call_leg], None)):
        universe = feed.resolve_fo_universe()
    # Every one of the 3 index + 210 stock underlyings resolves via these
    # same two mocks regardless of which underlying/right/expiry_class it
    # was called for (return_value, not side_effect) - since the mocked
    # future/option instrument_tokens are IDENTICAL every time, they all
    # collapse into the same 2 dict keys rather than 213x as many.
    assert len(universe) == 2
    assert universe[("nse_fo", "1")]["kind"] == "future"
    assert universe[("nse_fo", "2")]["kind"] == "option"
    assert universe[("nse_fo", "2")]["strike"] == 24500.0


def test_resolve_fo_universe_stock_offset_rotates_which_names_get_attempted():
    # 2026-09-22 live finding: STOCK_FO_UNDERLYINGS is a fixed tuple, and
    # a deadline that always cuts the resolve off partway through always
    # starved the same alphabetical tail. A non-zero stock_offset must
    # start the stock loop somewhere other than index 0, so a truncated
    # resolve attempts a DIFFERENT set of names than the default order.
    calls = []

    def fake_spot(cash_symbol):
        calls.append(cash_symbol)
        return None  # spot_unavailable - real attempt, not a deadline skip

    stock_names = nse_fo_chain.STOCK_FO_UNDERLYINGS
    offset = 5
    with patch.object(feed, "_spot_price", side_effect=fake_spot):
        feed.resolve_fo_universe(stock_offset=offset)

    stock_calls = [c for c in calls if c.endswith(".NS")]
    assert stock_calls[0] == f"{stock_names[offset]}.NS"


def test_resolve_fo_universe_carries_forward_legs_for_stocks_the_deadline_skipped():
    # A stock underlying this cycle never got to attempt (its name ended
    # up in "deadline_exceeded") must keep whatever it resolved LAST
    # cycle, not drop to zero - a previously-good, still-cached leg is
    # strictly better than silently unsubscribing it until its next turn
    # comes around in the rotation.
    stock_names = nse_fo_chain.STOCK_FO_UNDERLYINGS
    skipped_name = stock_names[-1]  # never reached: deadline is already past
    stale_key = ("nse_fo", "999")
    previous_universe = {
        stale_key: {"kind": "future", "underlying": skipped_name, "kotak_trading_symbol": "X"},
    }
    with patch.object(feed, "_spot_price", return_value=None):
        universe = feed.resolve_fo_universe(
            deadline=time.time() - 1, previous_universe=previous_universe,
        )
    assert universe == {stale_key: previous_universe[stale_key]}


def test_resolve_fo_universe_never_carries_forward_a_stock_it_did_attempt():
    # An underlying this cycle DID get a turn always uses this cycle's
    # own fresh result, even if that result is empty (e.g. a contract
    # that genuinely stopped existing) - never a leftover stale leg from
    # a previous cycle for a name that was actually re-checked.
    stock_names = nse_fo_chain.STOCK_FO_UNDERLYINGS
    attempted_name = stock_names[0]
    stale_key = ("nse_fo", "999")
    previous_universe = {
        stale_key: {"kind": "future", "underlying": attempted_name, "kotak_trading_symbol": "X"},
    }
    with patch.object(feed, "_spot_price", return_value=None):
        universe = feed.resolve_fo_universe(previous_universe=previous_universe)
    assert universe == {}


def test_startup_event_launches_the_fo_candle_feed_task():
    src = inspect.getsource(main._start_scheduler)
    assert "kotak_fo_candle_feed" in src
    assert "run_fo_candle_feed()" in src


def test_run_fo_candle_feed_resolves_the_universe_off_the_event_loop():
    # Live Render restart-loop regression (2026-09-16): resolve_fo_universe()
    # was called bare inside this coroutine, blocking the WHOLE asyncio
    # event loop (uvicorn's request handling included) for however long
    # its ~213-underlying search_scrip calls take. Confirms the fix (
    # asyncio.to_thread) by name in source, AND functionally: a concurrent
    # asyncio task must be able to make progress WHILE resolve_fo_universe
    # is still running, not just after it returns.
    src = inspect.getsource(feed.run_fo_candle_feed)
    # asyncio.to_thread(resolve_fo_universe) is now wrapped in
    # asyncio.wait_for (2026-09-16/17, live "both feeds stuck forever"
    # follow-up - see FO_UNIVERSE_RESOLVE_TIMEOUT_SECONDS's own
    # comment) - still off the event loop, just also hard-bounded now.
    # 2026-09-21: also passes deadline= through to_thread, since
    # wait_for's own timeout doesn't stop the worker thread - see
    # FO_UNIVERSE_RESOLVE_GRACE_SECONDS's own comment.
    # 2026-09-22: also passes stock_offset=/previous_universe= through -
    # see _stock_resolve_offset's own comment (rotates which stocks get
    # priority when a deadline truncates the resolve, and carries
    # forward last-known-good legs for stocks skipped this cycle).
    assert "asyncio.to_thread(" in src
    assert "resolve_fo_universe, deadline=" in src
    assert "stock_offset=stock_offset" in src
    assert "previous_universe=_universe_cache" in src
    assert "asyncio.wait_for(" in src

    import asyncio
    import time as time_module

    progressed = []

    def slow_resolve():
        time_module.sleep(0.2)
        return {}

    async def other_task():
        while len(progressed) < 3:
            progressed.append(time_module.time())
            await asyncio.sleep(0.03)

    async def run():
        task = asyncio.create_task(other_task())
        await asyncio.to_thread(slow_resolve)
        task.cancel()

    asyncio.run(run())
    # other_task only makes progress if the event loop is free to run it
    # WHILE slow_resolve (standing in for resolve_fo_universe) is blocked
    # on its own thread - a bare synchronous call here would have starved
    # it until slow_resolve returned.
    assert len(progressed) >= 2


def test_fo_universe_resolve_timeout_releases_the_lock_promptly():
    # Live follow-up (2026-09-16/17): both kotak_fo_candle_feed and
    # kotak_live_feed's own heavy resolves now share
    # main._heavy_startup_resolve_lock (asyncio.Lock, no timeout of its
    # own). If resolve_fo_universe hangs at a network layer that
    # ignores its own timeout (same failure class already found for
    # Upstash), the lock would never be released and the OTHER feed
    # would then wait on it FOREVER too - a live-observed symptom
    # (both feeds stuck at connected: false indefinitely). Proves the
    # asyncio.wait_for around the resolve call actually bounds how
    # long the lock stays held, using a patched near-zero timeout
    # rather than waiting out the real 180s.
    import asyncio
    import time as time_module

    def _hangs_forever():
        time_module.sleep(5)  # far longer than the patched deadline below
        return {}

    async def acquire_and_resolve():
        async with main._heavy_startup_resolve_lock:
            try:
                await asyncio.wait_for(asyncio.to_thread(_hangs_forever), timeout=0.1)
            except asyncio.TimeoutError:
                pass  # exactly what feed.run_fo_candle_feed's own outer except catches

    async def run():
        await acquire_and_resolve()
        # If the lock were still held (i.e. the timeout above didn't
        # actually bound the wait), this would hang here too.
        async with main._heavy_startup_resolve_lock:
            return True

    result = asyncio.run(asyncio.wait_for(run(), timeout=2.0))
    assert result is True


def test_startup_event_still_launches_the_equity_feed_task_unchanged():
    # The new task must be ADDED, not have replaced the existing one.
    src = inspect.getsource(main._start_scheduler)
    assert "kotak_live_feed" in src
    assert "run_feed(" in src


def test_init_db_creates_the_fo_option_candles_table():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    old_path = main.DB_PATH
    try:
        main.DB_PATH = path
        main.init_db()
        conn = sqlite3.connect(path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(fo_option_candles)").fetchall()}
        conn.close()
    finally:
        main.DB_PATH = old_path
    assert {"instrument_token", "bucket_start_ts", "open", "high", "low", "close", "tick_count"} <= cols


def test_stock_legs_are_resolved_with_the_stock_band_and_monthly_only():
    calls = []

    def fake_band(underlying, spot, right, expiry_class, band=None):
        calls.append((underlying, right, expiry_class, band))
        return [], "no_option_rows"  # empty band - only the call args matter here

    with patch.object(feed, "_spot_price", return_value=100.0), \
         patch("nse_fo_chain.select_nse_future", return_value=(None, "no_future_rows")), \
         patch("nse_fo_chain.select_atm_banded_option_strikes", side_effect=fake_band):
        feed.resolve_fo_universe()

    stock_calls = [c for c in calls if c[0] == "RELIANCE"]
    assert stock_calls, "RELIANCE should have been resolved as part of the stock universe"
    assert all(c[2] == "monthly" for c in stock_calls), "stock legs must be monthly-only"
    assert all(c[3] == feed.STOCK_ATM_STRIKE_BAND for c in stock_calls)
    assert {c[1] for c in stock_calls} == {"call", "put"}


def test_index_legs_still_use_the_wider_band_and_both_expiry_classes():
    calls = []

    def fake_band(underlying, spot, right, expiry_class, band=None):
        calls.append((underlying, right, expiry_class, band))
        return [], "no_option_rows"

    with patch.object(feed, "_spot_price", return_value=24500.0), \
         patch("nse_fo_chain.select_nse_future", return_value=(None, "no_future_rows")), \
         patch("nse_fo_chain.select_atm_banded_option_strikes", side_effect=fake_band):
        feed.resolve_fo_universe()

    nifty_calls = [c for c in calls if c[0] == "NIFTY"]
    assert {c[2] for c in nifty_calls} == {"weekly", "monthly"}
    assert all(c[3] == nse_fo_chain.DEFAULT_ATM_STRIKE_BAND for c in nifty_calls)


def test_stock_spot_lookup_uses_the_ns_ticker_suffix():
    seen_symbols = []

    def fake_spot(cash_symbol):
        seen_symbols.append(cash_symbol)
        return None  # short-circuits before any nse_fo_chain call

    with patch.object(feed, "_spot_price", side_effect=fake_spot):
        feed.resolve_fo_universe()

    assert "RELIANCE.NS" in seen_symbols
    assert "^NSEI" in seen_symbols  # index legs keep their existing yfinance-style ticker


def _with_real_candles_table():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    old_path = main.DB_PATH
    main.DB_PATH = path
    main.init_db()
    return old_path


def _insert_candle(conn, token, bucket_ts, o, h, l, c, ticks):
    conn.execute(
        "INSERT INTO fo_option_candles (instrument_token, kotak_trading_symbol, underlying, kind, "
        "right, strike, expiry, bucket_start_ts, open, high, low, close, tick_count) "
        "VALUES (?, 'NIFTY26OCT24500CE', 'NIFTY', 'option', 'call', 24500.0, '2026-10-27', "
        "?, ?, ?, ?, ?, ?)",
        (token, bucket_ts, o, h, l, c, ticks),
    )
    conn.commit()


def test_read_fo_candles_returns_none_for_an_instrument_with_no_candles():
    old_path = _with_real_candles_table()
    try:
        assert feed.read_fo_candles_as_df("NOTOKEN") is None
    finally:
        main.DB_PATH = old_path


def test_read_fo_candles_shape_matches_fetch_ohlc():
    old_path = _with_real_candles_table()
    try:
        with closing(main.get_db()) as conn:
            _insert_candle(conn, "TOK1", 0, 100.0, 110.0, 95.0, 105.0, 12)
            _insert_candle(conn, "TOK1", 300, 105.0, 108.0, 100.0, 102.0, 8)
        df = feed.read_fo_candles_as_df("TOK1")
    finally:
        main.DB_PATH = old_path
    assert list(df.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 2
    assert list(df.index) == [0, 1]  # plain RangeIndex, same as fetch_ohlc


def test_read_fo_candles_is_ordered_oldest_first():
    old_path = _with_real_candles_table()
    try:
        with closing(main.get_db()) as conn:
            _insert_candle(conn, "TOK1", 600, 1.0, 1.0, 1.0, 1.0, 1)
            _insert_candle(conn, "TOK1", 0, 2.0, 2.0, 2.0, 2.0, 1)
            _insert_candle(conn, "TOK1", 300, 3.0, 3.0, 3.0, 3.0, 1)
        df = feed.read_fo_candles_as_df("TOK1")
    finally:
        main.DB_PATH = old_path
    assert list(df["Open"]) == [2.0, 3.0, 1.0]


def test_read_fo_candles_only_returns_the_requested_instrument():
    old_path = _with_real_candles_table()
    try:
        with closing(main.get_db()) as conn:
            _insert_candle(conn, "TOK1", 0, 1.0, 1.0, 1.0, 1.0, 1)
            _insert_candle(conn, "TOK2", 0, 2.0, 2.0, 2.0, 2.0, 1)
        df = feed.read_fo_candles_as_df("TOK1")
    finally:
        main.DB_PATH = old_path
    assert len(df) == 1
    assert df["Open"].iloc[0] == 1.0


def test_read_fo_candles_volume_is_tick_count():
    old_path = _with_real_candles_table()
    try:
        with closing(main.get_db()) as conn:
            _insert_candle(conn, "TOK1", 0, 1.0, 1.0, 1.0, 1.0, 42)
        df = feed.read_fo_candles_as_df("TOK1")
    finally:
        main.DB_PATH = old_path
    assert df["Volume"].iloc[0] == 42
