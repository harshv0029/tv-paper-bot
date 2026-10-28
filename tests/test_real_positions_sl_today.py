"""B-1402: View 4 active-positions SL table."""
import time
from contextlib import closing

import main


def _setup():
    main.init_db()
    with closing(main.get_db()) as c:
        for t in ("real_positions", "real_positions_short", "real_positions_swing", "real_positions_swing_short", "signal_state", "real_order_events"):
            c.execute(f"DELETE FROM {t}")
        c.execute("INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, opened_at, day, sl_order_id, sl_trigger_price, target_price, strategy) "
                  "VALUES ('AAA.NS','AAA-EQ',5,100,'E1',?, '2026-10-28','S1',96,110,'orb-universal-score')", (time.time(),))
        c.execute("INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, target, qty, entry_ts) VALUES ('AAA.NS','2026-10-28','long',100,98,110,5,?)", (time.time(),))
        c.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, opened_at, day, stop_loss, sl_order_id, sl_trigger_price, strategy) "
                  "VALUES ('BBB.NS','BBB-EQ',3,200,'E2',?, '2026-10-27',190,'S2',190,'gap_and_go')", (time.time(),))
        c.execute("INSERT INTO real_order_events (ts, symbol, leg, event, new_state) VALUES (?, 'BBB.NS', 'sl', 'placed', 'resting SELL trigger Rs190')", (time.time(),))
        c.commit()


def test_rows_and_sl_verdicts():
    _setup()
    rows = {r["symbol"]: r for r in main.real_positions_sl_today()["positions"]}
    a, b = rows["AAA.NS"], rows["BBB.NS"]
    assert (a["category"], a["sl_type"], a["target_price"], a["qty"]) == ("buy", "trail", 110, 5)
    assert a["sl_as_per_strategy"] is False and "behind strategy stop" in a["sl_status"]
    assert (b["category"], b["sl_type"], b["target_price"]) == ("swing", "fixed", None)
    assert b["sl_as_per_strategy"] is True and b["sl_updates_today"] == 1 and b["last_sl_update_ist"]


def test_no_live_sl_flagged():
    _setup()
    with closing(main.get_db()) as c:
        c.execute("UPDATE real_positions_swing SET sl_order_id = NULL")
        c.commit()
    b = {r["symbol"]: r for r in main.real_positions_sl_today()["positions"]}["BBB.NS"]
    assert b["sl_as_per_strategy"] is False and b["sl_status"].startswith("NO - no live SL")
