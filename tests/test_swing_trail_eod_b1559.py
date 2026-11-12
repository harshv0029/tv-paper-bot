"""B-1559 (user 2026-11-12, COCHINSHIP): at 15:10 IST every trading day the trailing swing stop folds TODAY's price
(entry day included) into its stored peak and ratchets the resting stop; fixed-stop positions are untouched."""
import datetime as dt
import time
from contextlib import closing

import pytest

import main

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    main.init_db()
    for n in ("_sync_real_positions_external", "_sync_real_positions_swing_external", "_sync_signal_state_swing_external"):
        monkeypatch.setattr(main, n, lambda c: None)
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, qty, "
                  "entry_ts) VALUES ('COCHINSHIP.NS', 'trailtag', '2026-11-09', 1240.0, 1172.4, 1, ?)", (time.time(),))
        c.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
                  "stop_loss, sl_order_id, sl_trigger_price, strategy) VALUES ('COCHINSHIP.NS','COCHINSHIP-EQ',1,1240.0,"
                  "0,'2026-11-09',1203.7,'OID',1203.7,'trailtag')")
        c.commit()
    ratchets = []
    monkeypatch.setattr(main, "_sync_swing_resting_sl_to_strategy",
                        lambda c: ratchets.append(1) or [{"symbol": "COCHINSHIP.NS", "ok": True, "to": 1259.2}])
    return ratchets


def _peak():
    with closing(main.get_db()) as c:
        return main._swing_trail_peak_get(c, "COCHINSHIP.NS", "long", "2026-11-09")


def test_entry_day_high_is_folded_into_the_peak_and_the_stop_ratchets(db, monkeypatch):
    monkeypatch.setattr(main, "_swing_long_trail_rule", lambda c, s, st, d: ("ltp", 0.5))
    monkeypatch.setattr(main, "_swing_live_ltp_peak", lambda s: (1290.0, 1293.0))
    with closing(main.get_db()) as c:
        out = main._swing_trail_eod_update(c)
    assert _peak() == 1293.0 and out[0]["stop"] == 1259.2 and db == [1]
    lvl = main.swing_trail_level("ltp", "long", 1240.0, 1172.4, 1293.0, 0.5)
    assert abs(lvl - (1293.0 - 0.5 * 67.6)) < 0.01


def test_fixed_stop_position_is_untouched(db, monkeypatch):
    monkeypatch.setattr(main, "_swing_long_trail_rule", lambda c, s, st, d: None)
    monkeypatch.setattr(main, "_swing_live_ltp_peak", lambda s: (1290.0, 1293.0))
    with closing(main.get_db()) as c:
        out = main._swing_trail_eod_update(c)
    assert out == [] and _peak() is None


def test_peak_never_loosens(db, monkeypatch):
    monkeypatch.setattr(main, "_swing_long_trail_rule", lambda c, s, st, d: ("ltp", 0.5))
    with closing(main.get_db()) as c:
        main._swing_trail_peak_put(c, "COCHINSHIP.NS", "long", "2026-11-09", 1300.0)
    monkeypatch.setattr(main, "_swing_live_ltp_peak", lambda s: (1250.0, 1260.0))
    with closing(main.get_db()) as c:
        out = main._swing_trail_eod_update(c)
    assert out == [] and _peak() == 1300.0


def test_chandelier_kind_uses_the_latest_price(db, monkeypatch):
    monkeypatch.setattr(main, "_swing_long_trail_rule", lambda c, s, st, d: ("chand", 1.0))
    monkeypatch.setattr(main, "_swing_live_ltp_peak", lambda s: (1280.0, 1293.0))
    with closing(main.get_db()) as c:
        main._swing_trail_eod_update(c)
    assert _peak() == 1280.0


@pytest.mark.parametrize("hm,ok", [((15, 9), False), ((15, 10), True), ((15, 14), True), ((15, 15), False)])
def test_window_is_15_10_to_15_14_ist_on_trading_days(monkeypatch, hm, ok):
    monkeypatch.setattr(main, "is_nse_trading_day", lambda d=None: True)
    assert main._swing_trail_eod_due(dt.datetime(2026, 11, 12, *hm, tzinfo=IST)) is ok


def test_not_on_a_holiday(monkeypatch):
    monkeypatch.setattr(main, "is_nse_trading_day", lambda d=None: False)
    assert main._swing_trail_eod_due(dt.datetime(2026, 11, 12, 15, 11, tzinfo=IST)) is False
