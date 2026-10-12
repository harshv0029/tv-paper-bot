"""B-817: short cover (BUY) fills get an exit remark; pnl sign mirrored; longs unchanged."""
import os, tempfile
from contextlib import closing
import main


def _db():
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd)
    main.DB_PATH = p; main.init_db()


def _day():
    return main.ist_now().strftime("%d-%b-%Y")


def _o(oid, tsym, side, px, **kw):
    d = {"nOrdNo": oid, "trdSym": tsym, "trnsTp": side, "ordSt": "complete", "fldQty": "10",
         "avgPrc": str(px), "ordDtTm": f"{_day()} 10:00:00"}
    d.update(kw)
    return d


def _short_row(c, tsym="Z-EQ"):
    c.execute("INSERT INTO real_positions_short (symbol,kotak_trading_symbol,qty,entry_price,opened_at,day,sl_trigger_price) "
              "VALUES ('Z.NS',?,10,100,1,'d',103)", (tsym,))
    c.commit()


def test_short_cover_stop_gets_remark_and_negative_pnl_on_loss():
    _db()
    with closing(main.get_db()) as c:
        _short_row(c)
        rows = [_o("1", "Z-EQ", "S", 100), _o("2", "Z-EQ", "B", 103.2, prcTp="SL", trgPrc="103")]
        out = main._kotak_exit_fills_today(rows, set(), c)
    assert len(out) == 1 and out[0]["side"] == "short"
    assert out[0]["exit_kind"] == "stop_loss_triggered_at_kotak"
    assert "entry 100.00" in out[0]["exit_remark"] and "loss 3.20%" in out[0]["exit_remark"]
    assert out[0]["pnl_inr"] == -32.0


def test_short_cover_profit_pnl_is_entry_minus_exit():
    _db()
    with closing(main.get_db()) as c:
        _short_row(c)
        rows = [_o("1", "Z-EQ", "S", 100), _o("2", "Z-EQ", "B", 96, prcTp="L")]
        out = main._kotak_exit_fills_today(rows, set(), c)
    assert out[0]["pnl_inr"] == 40.0 and "gain 4.00%" in out[0]["exit_remark"]


def test_trailing_short_stop_below_entry():
    _db()
    with closing(main.get_db()) as c:
        _short_row(c)
        rows = [_o("1", "Z-EQ", "S", 100), _o("2", "Z-EQ", "B", 97.1, prcTp="SL-M", trgPrc="97")]
        out = main._kotak_exit_fills_today(rows, set(), c)
    assert out[0]["exit_kind"] == "trailing_stop_triggered_at_kotak" and "below entry" in out[0]["exit_remark"]


def test_buy_without_short_row_is_not_listed():
    _db()
    with closing(main.get_db()) as c:
        out = main._kotak_exit_fills_today([_o("1", "Q-EQ", "B", 50)], set(), c)
    assert out == []


def test_long_sell_unchanged():
    _db()
    with closing(main.get_db()) as c:
        rows = [_o("1", "L-EQ", "B", 100), _o("2", "L-EQ", "S", 110, prcTp="L")]
        out = main._kotak_exit_fills_today(rows, set(), c)
    assert len(out) == 1 and out[0]["pnl_inr"] == 100.0 and out[0]["side"] == "long"
