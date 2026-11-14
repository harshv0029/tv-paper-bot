"""B-1567 (BDL 2026-11-12): a paper-only swing row must not silently block the buy engine's own real exit."""
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import main

SYM = "BDL.NS"
CHAN = sorted(main.CHAN_INTRADAY_LONG_TAGS)[0]


def _setup(strategy, real_swing=False):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, "
                  "opened_at, day, strategy) VALUES (?, 'BDL-EQ', 1, 1044.9, 'E', 0, '2026-11-12', ?)", (SYM, strategy))
        c.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, qty, "
                  "entry_ts) VALUES (?, 'gap_and_go', '2026-11-12', 1000.0, 950.0, 1, 0)", (SYM,))
        if real_swing:
            c.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, "
                      "entry_order_id, opened_at, day, strategy, stop_loss) VALUES (?, 'BDL-EQ', 1, 1000.0, 'S', 0, "
                      "'2026-11-12', 'gap_and_go', 950.0)", (SYM,))
        c.commit()


def _run():
    with closing(main.get_db()) as c, patch("main._kotak_symbol_still_open", return_value=False) as chk:
        main._maybe_place_real_exit(c, SYM, reason="flatten_1515")
        ev = [r["event"] for r in c.execute("SELECT event FROM real_order_events WHERE symbol = ?", (SYM,))]
    return chk.called, ev


def test_tagged_intraday_position_not_blocked_by_paper_swing_row():
    _setup(CHAN)
    reached_kotak, ev = _run()
    assert reached_kotak and "refused_swing_owned" not in ev


def test_untagged_position_with_paper_swing_row_refused_and_logged():
    _setup(None)
    reached_kotak, ev = _run()
    assert not reached_kotak and "refused_swing_owned" in ev


def test_real_swing_position_always_refused_and_logged():
    _setup(CHAN, real_swing=True)
    reached_kotak, ev = _run()
    assert not reached_kotak and "refused_swing_owned" in ev
