"""B-1402: View 4 active-positions SL table."""
import time
from contextlib import closing

import pytest

import main


@pytest.fixture(autouse=True)
def _no_network_prices(monkeypatch):
    monkeypatch.setattr(main, "_open_positions_prices", lambda syms, wl, budget_s=None: {"AAA.NS": 104.0, "BBB.NS": 190.0})


def _setup():
    main.init_db()
    with closing(main.get_db()) as c:
        for t in ("real_positions", "real_positions_short", "real_positions_swing", "real_positions_swing_short", "signal_state", "signal_state_swing", "real_order_events"):
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


def test_b1410_entry_day_sl_and_profit_columns():
    """B-1410 (user 2026-10-28): Entry day SL, profit amount and profit % per row."""
    _setup()
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, qty, entry_ts) "
                  "VALUES ('BBB.NS','gap_and_go','2026-10-27',200,185,3,?)", (time.time(),))
        c.commit()
    rows = {r["symbol"]: r for r in main.real_positions_sl_today()["positions"]}
    a, b = rows["AAA.NS"], rows["BBB.NS"]
    assert (a["profit_inr"], a["profit_pct"], a["current_price"]) == (20.0, 4.0, 104.0)
    assert (b["profit_inr"], b["profit_pct"]) == (-30.0, -5.0)
    # BBB's only 'sl placed' event is today, not on its 2026-10-27 entry day -> the strategy's frozen initial stop
    assert (b["entry_day_sl"], b["entry_day_sl_source"]) == (185.0, "strategy")


def test_b1410_entry_day_sl_prefers_kotak_event_on_entry_day():
    _setup()
    d0 = main.dt.datetime(2026, 10, 27, 4, 0, tzinfo=main.dt.timezone.utc).timestamp()  # 09:30 IST on the entry day
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_order_events (ts, symbol, leg, event, new_state) VALUES (?, 'BBB.NS', 'sl', 'placed', "
                  "'resting SELL trigger Rs187.55')", (d0,))
        c.commit()
    b = {r["symbol"]: r for r in main.real_positions_sl_today()["positions"]}["BBB.NS"]
    assert (b["entry_day_sl"], b["entry_day_sl_source"]) == (187.55, "kotak")


def test_b1410_short_profit_sign(monkeypatch):
    _setup()
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_positions_short (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, opened_at, day, "
                  "sl_order_id, sl_trigger_price, strategy) VALUES ('CCC.NS','CCC-EQ',2,50,'E3',?, '2026-10-28','S3',52,'x')",
                  (time.time(),))
        c.commit()
    monkeypatch.setattr(main, "_open_positions_prices", lambda syms, wl, budget_s=None: {"CCC.NS": 45.0})
    cc = {r["symbol"]: r for r in main.real_positions_sl_today()["positions"]}["CCC.NS"]
    assert (cc["profit_inr"], cc["profit_pct"]) == (10.0, 10.0)
