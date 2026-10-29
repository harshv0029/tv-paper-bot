"""B-1411 (pre-clamp SL to the price band + log band rejections), B-1412 (one swing stop, logged cancels),
B-1414 (skip a real intraday entry whose stop is too close to the live price). Live cases from 2026-10-29."""
import time
from contextlib import closing

import kotak_real_orders as k
import main


def _band(monkeypatch, prev, last):
    monkeypatch.setattr(k, "_reference_prices", lambda s: (prev, last))
    monkeypatch.setattr(k, "_tick_size_for", lambda s: 0.01)
    k._BAND_REF_CACHE.clear()


def test_b1411_long_stop_below_band_is_raised_before_first_send(monkeypatch):
    _band(monkeypatch, 132.9, 133.5)  # BANKINDIA 09:15: floor 132.9 x 0.9 x 1.003 = 119.97
    sent = []
    monkeypatch.setattr(k, "_place_real_stop_loss_once",
                        lambda sym, q, t: sent.append(t) or {"ok": True, "order_id": "1", "trigger_price": t})
    r = k.place_real_stop_loss("BANKINDIA-EQ", 8, 115.72)
    assert sent == [119.97] and r["ok"] and r["band_clamped_from"] == 115.72


def test_b1411_stop_inside_band_is_sent_unchanged(monkeypatch):
    _band(monkeypatch, 132.9, 133.5)
    sent = []
    monkeypatch.setattr(k, "_place_real_stop_loss_once",
                        lambda sym, q, t: sent.append(t) or {"ok": True, "order_id": "1", "trigger_price": t})
    r = k.place_real_stop_loss("BANKINDIA-EQ", 8, 126.73)
    assert sent == [126.73] and "band_clamped_from" not in r


def test_b1411_short_stop_above_band_is_lowered_before_first_send(monkeypatch):
    _band(monkeypatch, 100.0, 104.0)  # ceiling 100 x 1.1 x 0.997 = 109.67
    sent = []
    monkeypatch.setattr(k, "_place_real_short_stop_loss_once",
                        lambda sym, q, t, p="MIS": sent.append(t) or {"ok": True, "order_id": "1", "trigger_price": t})
    r = k.place_real_short_stop_loss("X-EQ", 1, 115.0)
    assert sent == [109.67] and r["band_clamped_from"] == 115.0


def test_b1411_band_rejection_reason_reaches_the_order_log(monkeypatch):
    _band(monkeypatch, 100.0, 99.0)  # 92 is inside the 10% band, so it is sent; a 5% band then rejects it

    def once(sym, q, t):
        if t < 95.2:
            return {"ok": False, "detail": "order 111 rejected: Circuit breach", "rejected_order_id": "111"}
        return {"ok": True, "order_id": "222", "trigger_price": t}

    monkeypatch.setattr(k, "_place_real_stop_loss_once", once)
    assert k.place_real_stop_loss("X-EQ", 1, 92.0)["ok"]
    assert "outside the day's price band" in k.order_reason("111")

    main.init_db()
    with closing(main.get_db()) as c:
        c.execute("DELETE FROM real_order_events")
        c.commit()
        monkeypatch.setattr(main, "sync_generic_tables_external", lambda **kw: None)
        main._log_unlogged_kotak_orders(c, [{"nOrdNo": "111", "trdSym": "X-EQ", "ordSt": "rejected"}])
        d = c.execute("SELECT detail FROM real_order_events WHERE order_id = '111'").fetchone()[0]
    assert "outside the day's price band" in d and "UNLOGGED" not in d


def test_b1412_replace_logs_each_cancel_and_real_trigger(monkeypatch):
    main.init_db()
    with closing(main.get_db()) as c:
        c.execute("DELETE FROM real_order_events")
        c.commit()
        main._log_swing_ensure_sl_result(
            c, "BANKINDIA.NS", "BANKINDIA-EQ",
            {"ok": True, "order_id": "N2", "trigger_price": 126.73, "action": "replaced", "cancelled": ["N1"]},
            126.73, "test")
        rows = c.execute("SELECT event, order_id, prev_state, detail FROM real_order_events ORDER BY id").fetchall()
    assert [(r[0], r[1]) for r in rows] == [("cancelled", "N1"), ("placed", "N2")]
    assert "N1" in rows[1][2] and "Rs126.73" in rows[1][3]


def test_b1412_band_clamped_wording_shows_both_levels(monkeypatch):
    main.init_db()
    with closing(main.get_db()) as c:
        c.execute("DELETE FROM real_order_events")
        c.commit()
        main._log_swing_ensure_sl_result(
            c, "SUZLON.NS", "SUZLON-EQ",
            {"ok": True, "order_id": "S1", "trigger_price": 33.67, "action": "placed", "band_clamped_from": 28.91},
            28.91, "test")
        d = c.execute("SELECT detail FROM real_order_events").fetchone()[0]
    assert "placed at Rs33.67" in d and "Rs28.91 is outside the day's price band" in d


def test_b1412_adopted_is_not_logged_as_placed():
    main.init_db()
    with closing(main.get_db()) as c:
        c.execute("DELETE FROM real_order_events")
        c.commit()
        main._log_swing_ensure_sl_result(
            c, "X.NS", "X-EQ", {"ok": True, "order_id": "A1", "trigger_price": 50.0, "action": "adopted_existing"},
            49.0, "test")
        assert c.execute("SELECT event FROM real_order_events").fetchone()[0] == "adopted"


def test_b1414_stop_too_close():
    # JSWENERGY 2026-10-29: tick 501.80, short stop 504.15 -> 0.47% -> skip
    assert main._real_entry_stop_too_close("short", 501.80, 504.15)
    assert main._real_entry_stop_too_close("short", 505.0, 504.15)  # already through the stop
    assert main._real_entry_stop_too_close("short", 500.0, 510.0) is None
    assert main._real_entry_stop_too_close("long", 100.0, 99.8)
    assert main._real_entry_stop_too_close("long", 100.0, 98.0) is None
    assert main._real_entry_stop_too_close("long", 100.0, None) is None
