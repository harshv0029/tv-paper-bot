import os
import tempfile

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def test_sl_fill_logged_once_from_kotak_order_book():
    _fresh_db()
    c = main.get_db()
    main._log_real_order_event(c, "AAA.NS", "sl", "placed", kotak_trading_symbol="AAA-EQ", order_id="900",
                               new_state="resting SELL trigger Rs95")
    rows = [{"nOrdNo": "900", "ordSt": "complete", "avgPrc": "94.8", "trdSym": "AAA-EQ", "trnsTp": "S", "qty": "10"},
            {"nOrdNo": "901", "ordSt": "complete", "avgPrc": "50", "trdSym": "ZZZ-EQ", "trnsTp": "S"},
            {"nOrdNo": "902", "ordSt": "open", "avgPrc": "0", "trdSym": "AAA-EQ"}]
    assert main._log_sl_fills_from_kotak(c, rows) == 1
    assert main._log_sl_fills_from_kotak(c, rows) == 0  # idempotent
    fills = main._sl_fills_today(c, 0)
    c.close()
    assert fills == [("AAA.NS", 94.8, "S")]


def test_sl_close_counts_in_per_tag_closed_and_win_rate():
    _fresh_db()
    c = main.get_db()
    main._log_real_attempt(c, "AAA.NS", "B", "confirmed", qty=10, strategy="gap_and_go")
    c.execute("UPDATE real_trades SET price_est = 100 WHERE symbol = 'AAA.NS'")
    c.commit()
    main._log_real_order_event(c, "AAA.NS", "sl", "placed", kotak_trading_symbol="AAA-EQ", order_id="900")
    main._log_sl_fills_from_kotak(c, [{"nOrdNo": "900", "ordSt": "complete", "avgPrc": "94",
                                       "trdSym": "AAA-EQ", "trnsTp": "S", "qty": "10"}])
    c.close()
    res = main.strategy_scan_activity(include_unwired=True)
    row = [s for s in res["strategies"] if s.get("strategy_tag") == "gap_and_go"][0]
    assert row["closed_today"] == 1
    assert row["win_rate_today_pct"] == 0.0  # SL close below entry is a counted loss
