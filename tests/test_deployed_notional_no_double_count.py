"""B-896: deployed_notional() must not subtract capital Kotak has already deducted.

Sizing `capital` is Kotak limits()["Net"], already net of every open real position's
margin. A paper row mirrored by a real row is therefore counted by Kotak; only the
paper-only remainder may still count in deployed_notional().
"""
import os
import tempfile
from contextlib import closing

import pytest

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def _swing_paper(conn, sym, qty, px):
    conn.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, qty, "
                 "entry_ts) VALUES (?, 'gap_and_go', '2026-10-20', ?, ?, ?, 1)", (sym, px, px * 0.9, qty))


def _swing_real(conn, sym, qty, px):
    conn.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
                 "stop_loss) VALUES (?, ?, ?, ?, 1, '2026-10-20', ?)", (sym, sym.split('.')[0] + "-EQ", qty, px, px * 0.9))


def test_real_backed_swing_position_not_counted_twice():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _swing_paper(conn, "AAA.NS", 10, 100.0)  # paper-only: Kotak Net never saw it
        _swing_paper(conn, "BBB.NS", 20, 50.0)   # fully mirrored real: Kotak Net already net of it
        _swing_real(conn, "BBB.NS", 20, 50.0)
        _swing_paper(conn, "CCC.NS", 10, 30.0)   # real fill capped below paper qty
        _swing_real(conn, "CCC.NS", 4, 30.0)
        conn.commit()
        # 1000 (AAA) + 0 (BBB) + 6*30 (CCC paper-only remainder)
        assert main.deployed_notional(conn) == pytest.approx(1180.0)


def test_swing_sizing_uses_full_kotak_net_when_all_open_positions_are_real():
    """Kotak Net 20,000 after a real Rs 15,000 holding: the next trade must size off 20,000,
    not 20,000 - 15,000 (the pre-B-896 double count)."""
    _fresh_db()
    with closing(main.get_db()) as conn:
        _swing_paper(conn, "BBB.NS", 150, 100.0)
        _swing_real(conn, "BBB.NS", 150, 100.0)
        conn.commit()
        assert main.deployed_notional(conn) == pytest.approx(0.0)
        capital = 20000.0
        qty = main._swing_position_size(conn, capital, 100.0, 100.0, 50.0)
        expected_usable = capital / main.CAPITAL_TRANCHES
        assert qty == int(min(expected_usable / 50.0, expected_usable / 100.0))
        assert qty > 0


def test_intraday_and_short_real_rows_offset_their_own_paper_rows_only():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute("INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, qty, fx_to_inr) "
                     "VALUES ('LLL.NS', '2026-10-20', 'long', 200, 190, 5, 1)")
        conn.execute("INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day) "
                     "VALUES ('LLL.NS', 'LLL-EQ', 5, 200, 1, '2026-10-20')")
        conn.execute("INSERT INTO signal_state_short (symbol, day, status, entry_price, stop_loss, qty, fx_to_inr) "
                     "VALUES ('SSS.NS', '2026-10-20', 'short', 100, 105, 8, 1)")
        # a real row in a DIFFERENT engine's table must not offset this short (engine ownership)
        conn.execute("INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day) "
                     "VALUES ('SSS.NS', 'SSS-EQ', 8, 100, 1, '2026-10-20')")
        conn.commit()
        assert main.deployed_notional(conn) == pytest.approx(800.0)
