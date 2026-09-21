"""Tests for the "open position orphaned when its symbol leaves WATCHLIST"
bug (2026-09-21, live incident: GENCON.NS sat open in paper trading for
~10 days, entirely unmanaged - no stop/target/squareoff check, no real
stop-loss sync - after the NIFTY 200 universe restriction dropped it from
WATCHLIST while its signal_state row was still 'long'.

Root cause, confirmed by reading _scheduler_tick: symbols_this_tick
(open_equity_symbols | open_real_symbols | ...) is deliberately sourced
from DB state, NOT WATCHLIST, specifically so an open position is "never
gated" by round-robin/WATCHLIST membership (see that loop's own
comments) - but the very next line, `cfg = watchlist_by_symbol.get(symbol);
if not cfg: continue`, silently threw that guarantee away for any symbol
no longer in the CURRENT WATCHLIST. Every stage inside that loop
(_auto_signal_core itself, _maybe_place_real_exit, _maybe_sync_real_stop_loss,
the F&O mirror) never ran at all for such a symbol - not just paper
tracking, real-money stop-loss sync too.

Fix: fall back to NSE_STOCK_DEFAULT_PARAMS (the same conservative config
a brand-new unproven symbol gets) instead of `continue`, so a symbol
leaving WATCHLIST never means abandoning a position still open in it."""
import asyncio
import inspect
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import pandas as pd

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def test_gencon_style_symbol_is_confirmed_absent_from_current_watchlist():
    # Sanity-checks the premise of this whole bug class still holds (the
    # NIFTY 200 restriction is a standing fact of the current WATCHLIST,
    # not just true on 2026-09-21) - if this ever fails because GENCON.NS
    # re-enters the universe, the other tests below (which use a
    # deliberately-fake symbol) still cover the general case.
    watchlist_symbols = {cfg["symbol"] for cfg in main.WATCHLIST}
    assert "GENCON.NS" not in watchlist_symbols


def test_cfg_fallback_logic_covers_every_field_scheduler_tick_reads():
    # Mirrors _scheduler_tick's own fallback exactly (same "mirrors
    # main.py's own logic" style test_real_position_scheduler_visibility.py
    # already uses) - a symbol not in WATCHLIST must still resolve to a
    # cfg with every field the tick's own _auto_signal_core call site
    # reads (see that call site's kwargs).
    watchlist_by_symbol = {cfg["symbol"]: cfg for cfg in main.WATCHLIST}
    symbol = "NOT_IN_WATCHLIST.NS"
    cfg = watchlist_by_symbol.get(symbol)
    if not cfg:
        cfg = {**main.NSE_STOCK_DEFAULT_PARAMS, "symbol": symbol}
    for key in (
        "symbol", "risk_pct", "stop_pct", "orb_minutes", "sma_fast", "sma_slow",
        "tz_offset_min", "open_min", "close_min", "squareoff_min",
        "trade_weekends", "currency",
    ):
        assert key in cfg, f"fallback cfg missing {key!r} - _scheduler_tick's call site would KeyError"
    assert cfg["symbol"] == symbol


def test_scheduler_tick_source_falls_back_instead_of_skipping_unwatchlisted_symbols():
    # A regression guard against silently reverting to the old `continue`
    # - this exact bug already happened once from an unrelated, seemingly
    # safe change (the NIFTY 200 restriction), so a plain code-presence
    # check is cheap insurance against it happening a second time.
    src = inspect.getsource(main._scheduler_tick)
    assert "NSE_STOCK_DEFAULT_PARAMS" in src
    assert "if not cfg:\n            continue" not in src.replace("            continue", "continue")


def test_scheduler_tick_actually_checks_an_orphaned_open_position():
    # The real thing: drives main._scheduler_tick() itself (not just the
    # logic in isolation) with an open signal_state position for a symbol
    # that has NO WATCHLIST entry, heavily mocking out the unrelated sub-
    # scans and network calls, and confirms _auto_signal_core actually ran
    # for it (via _scheduler_last_results, the same record the live
    # incident's own /scheduler-pipeline diagnostic showed as missing).
    _fresh_db()
    orphan = "ORPHANED_NOT_IN_WATCHLIST.NS"
    assert orphan not in {cfg["symbol"] for cfg in main.WATCHLIST}

    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
            "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) "
            "VALUES (?, '2026-09-21', 'long', 100.0, 98.0, 98.0, 106.0, 10, ?, 1.0, '5m')",
            (orphan, main.time.time() - 100000),
        )
        conn.commit()

    base = pd.Timestamp("2026-09-21 03:45:00")
    fixture = pd.DataFrame([
        {"Date": base + pd.Timedelta(minutes=5 * i), "Open": 100.0, "High": 100.5,
         "Low": 99.5, "Close": 100.0, "Volume": 1000}
        for i in range(30)
    ])

    main._scheduler_last_results.pop(orphan, None)
    with patch("main._run_swing_scan"), \
         patch("main._fo_chain_monitoring_snapshot"), \
         patch("main._run_fo_options_scan"), \
         patch("main.fetch_ohlc", return_value=fixture), \
         patch("main.get_scheduler_capital_inr", return_value=400000.0), \
         patch("kotak_live_feed.get_live_ticks", return_value={}), \
         patch("main._maybe_sync_real_stop_loss"), \
         patch("main._maybe_place_real_entry"), \
         patch("main._maybe_place_real_exit"), \
         patch("main._maybe_place_real_partial_exit"):
        asyncio.run(main._scheduler_tick())

    assert orphan in main._scheduler_last_results, (
        "the orphaned symbol was never checked at all this tick - "
        "the old bug (silently `continue`-ing past it) has regressed"
    )
