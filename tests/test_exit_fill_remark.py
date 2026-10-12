"""B-815: Kotak exit-fill remark states the reason with numbers (no more 'not linked')."""
import os, tempfile
from contextlib import closing
import main


def _db():
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd)
    main.DB_PATH = p; main.init_db()


def _day():
    return main.ist_now().strftime("%d-%b-%Y")


def _buy(tsym, px):
    return {"nOrdNo": "1", "trdSym": tsym, "trnsTp": "B", "ordSt": "complete", "fldQty": "10", "avgPrc": str(px), "ordDtTm": f"{_day()} 09:20:00"}


def _sell(oid, tsym, px, **kw):
    d = {"nOrdNo": oid, "trdSym": tsym, "trnsTp": "S", "ordSt": "complete", "fldQty": "10", "avgPrc": str(px), "ordDtTm": f"{_day()} 13:00:00"}
    d.update(kw)
    return d


def test_exchange_triggered_stop_loss_has_trigger_fill_entry_loss():
    _db()
    with closing(main.get_db()) as c:
        rows = [_buy("DABUR-EQ", 500), _sell("9", "DABUR-EQ", 489.5, prcTp="SL", trgPrc="490")]
        out = main._kotak_exit_fills_today(rows, set(), c)
    r = out[0]["exit_remark"]
    assert out[0]["exit_kind"] == "stop_loss_triggered_at_kotak"
    assert "triggered at Kotak" in r and "trigger 490.00" in r and "fill 489.50" in r and "entry 500.00" in r and "loss 2.10%" in r
    assert "not linked" not in r


def test_trailing_stop_above_entry_is_labelled_trailing():
    _db()
    with closing(main.get_db()) as c:
        rows = [_buy("A-EQ", 100), _sell("9", "A-EQ", 109.9, prcTp="SL-M", trgPrc="110")]
        out = main._kotak_exit_fills_today(rows, set(), c)
    assert out[0]["exit_kind"] == "trailing_stop_triggered_at_kotak" and "ratcheted" in out[0]["exit_remark"]


def test_app_exit_uses_logged_reason_and_swing_levels():
    _db()
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_positions_swing (symbol,kotak_trading_symbol,qty,entry_price,opened_at,day,stop_loss,sl_trigger_price) "
                  "VALUES ('X.NS','X-EQ',10,200,1,'d',190,191)")
        c.execute("INSERT INTO real_order_events (ts,symbol,kotak_trading_symbol,leg,event,order_id,detail) "
                  "VALUES (1,'X.NS','X-EQ','exit','placed','77','reason: RSI 78 above 75 rule exit')")
        c.commit()
        out = main._kotak_exit_fills_today([_sell("77", "X-EQ", 230, prcTp="L")], set(), c)
    r = out[0]["exit_remark"]
    assert out[0]["exit_kind"] == "app_exit" and "RSI 78 above 75 rule exit" in r
    assert "entry 200.00" in r and "fill 230.00" in r and "SL level 191.00" in r and "gain 15.00%" in r
    assert out[0]["pnl_inr"] == 300.0


def test_target_hit_and_square_off():
    _db()
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_positions (symbol,kotak_trading_symbol,qty,entry_price,opened_at,day,sl_trigger_price,target_price) "
                  "VALUES ('T.NS','T-EQ',10,100,1,'d',98,105)")
        c.execute("INSERT INTO real_order_events (ts,symbol,kotak_trading_symbol,leg,event,order_id,detail) "
                  "VALUES (1,'S.NS','S-EQ','exit','placed','5','reason: 3:14pm intraday square-off')")
        c.commit()
        out = main._kotak_exit_fills_today([_sell("4", "T-EQ", 105, prcTp="L"), _sell("5", "S-EQ", 50)], set(), c)
    by = {o["symbol"]: o for o in out}
    assert by["T-EQ"]["exit_kind"] == "target_hit" and "target 105.00" in by["T-EQ"]["exit_remark"]
    assert by["S-EQ"]["exit_kind"] == "square_off"


def test_fallback_still_carries_best_numbers():
    _db()
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_order_events (ts,symbol,kotak_trading_symbol,leg,event,order_id,new_state) "
                  "VALUES (1,'Q.NS','Q-EQ','sl','placed','3','resting SELL trigger Rs95.50')")
        c.commit()
        out = main._kotak_exit_fills_today([_buy("Q-EQ", 100), _sell("8", "Q-EQ", 96, prcTp="L")], set(), c)
    r = out[0]["exit_remark"]
    assert out[0]["exit_kind"] == "unmatched" and "entry 100.00" in r and "fill 96.00" in r and "SL level 95.50" in r
