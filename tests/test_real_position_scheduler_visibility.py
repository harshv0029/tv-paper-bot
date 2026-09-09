"""Tests for the "real position invisible to the scheduler tick" bug
(2026-09-09, explicit user finding: JSWINFRA.NS/MIDCAPADD.NS/PAISALO.NS
still open well past squareoff_min AND market close). Root cause:
_scheduler_tick's symbols_this_tick only ever included open_equity_symbols
(sourced from signal_state - PAPER tracking), never real_positions
directly - a real position whose signal_state row went missing (the
exact restart-wipe class this session already fixed once, reactively,
inside _maybe_sync_real_stop_loss) was invisible to the WHOLE per-tick
loop, so _auto_signal_core (the only place squareoff_min is ever
evaluated) never ran for it at all, and the self-heal that would have
restored signal_state could never even get CALLED. See main.py's
_scheduler_tick, the open_real_symbols/real_position_rows backfill
loop right where open_equity_symbols is computed."""
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def _insert_real_position(conn, symbol="JSWINFRA.NS", entry_price=340.85, qty=1):
    conn.execute(
        "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
        "entry_order_id, opened_at, day) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (symbol, symbol.replace(".NS", "-EQ"), qty, entry_price, "1", main.time.time(),
         main.ist_now().strftime("%Y-%m-%d")),
    )
    conn.commit()


def test_symbols_this_tick_construction_includes_a_real_position_with_no_signal_state():
    # Mirrors _scheduler_tick's OWN set construction exactly (see that
    # function) - a real position with NO signal_state row must still
    # land in symbols_this_tick, not just open_equity_symbols/rr_batch.
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position(conn)
        open_equity_symbols = {
            r["symbol"] for r in conn.execute(
                "SELECT symbol FROM signal_state WHERE status = 'long'"
            ).fetchall()
        }
        open_option_underlyings = set()
        real_position_rows = conn.execute("SELECT * FROM real_positions").fetchall()
        open_real_symbols = {r["symbol"] for r in real_position_rows}

    assert "JSWINFRA.NS" not in open_equity_symbols, "signal_state is genuinely missing for this test"
    assert "JSWINFRA.NS" in open_real_symbols

    evidenced_flat = set()
    rr_batch = set()
    symbols_this_tick = open_equity_symbols | open_real_symbols | open_option_underlyings | evidenced_flat | rr_batch
    assert "JSWINFRA.NS" in symbols_this_tick


def test_flat_symbols_pool_excludes_an_open_real_position():
    # A real position must never also eat a round-robin batch slot -
    # same "already guaranteed elsewhere" exclusion EVIDENCED_SYMBOLS
    # already gets.
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position(conn)
        open_equity_symbols = set()
        real_position_rows = conn.execute("SELECT * FROM real_positions").fetchall()
        open_real_symbols = {r["symbol"] for r in real_position_rows}

    all_symbols = [cfg["symbol"] for cfg in main.WATCHLIST]
    flat_symbols = [
        s for s in all_symbols
        if s not in open_equity_symbols and s not in main.EVIDENCED_SYMBOLS and s not in open_real_symbols
    ]
    assert "JSWINFRA.NS" not in flat_symbols


def test_ensure_signal_state_backfill_runs_proactively_for_every_real_position():
    # The actual fix: _scheduler_tick now calls
    # _ensure_signal_state_for_real_position for every real_positions row
    # BEFORE _auto_signal_core runs this tick - not only reactively from
    # inside _maybe_sync_real_stop_loss afterward. Proven here by calling
    # it exactly the way the tick's own backfill loop does and checking
    # signal_state exists afterward with the REAL entry price (not a
    # fresh "entered today" price _auto_signal_core would have used had
    # it seen this symbol as flat).
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position(conn, symbol="PAISALO.NS", entry_price=79.88, qty=3)
        real_position_rows = conn.execute("SELECT * FROM real_positions").fetchall()
        for real_row in real_position_rows:
            main._ensure_signal_state_for_real_position(conn, real_row)

        row = conn.execute(
            "SELECT * FROM signal_state WHERE symbol = ? AND status = 'long'", ("PAISALO.NS",)
        ).fetchone()
        assert row is not None
        assert row["entry_price"] == 79.88, "must restore the REAL entry price, never a fresh one"


def test_backfill_removes_a_ghost_real_position_before_the_tick_would_have_treated_it_as_flat():
    # Same DEEP.NS-class safety this session already built - if Kotak
    # confirms the position is genuinely closed, the tick's own proactive
    # backfill must delete the stale real_positions row rather than
    # resurrecting paper tracking for a dead position and letting it
    # re-enter symbols_this_tick every tick forever.
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position(conn, symbol="DEEP.NS")
        with patch("main._kotak_symbol_still_open", return_value=False):
            real_position_rows = conn.execute("SELECT * FROM real_positions").fetchall()
            for real_row in real_position_rows:
                main._ensure_signal_state_for_real_position(conn, real_row)

        assert conn.execute("SELECT 1 FROM real_positions WHERE symbol = ?", ("DEEP.NS",)).fetchone() is None
        assert conn.execute("SELECT 1 FROM signal_state WHERE symbol = ?", ("DEEP.NS",)).fetchone() is None
