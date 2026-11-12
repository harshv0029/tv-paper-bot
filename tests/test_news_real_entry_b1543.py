"""B-1543 (user 2026-11-10): the news engine is a real-money entry criterion. A confirmed + confident GOOD-news open
buys at most NEWS_REAL_QTY_CAP (1) real share through the swing engine with the viability gate skipped; the share is
sold when the news trade closes. Shorts stay paper."""
import os
from contextlib import closing
from unittest.mock import patch

import main
from tests.test_pfnet_real_money_gate import _fresh_db

TAG = main.NEWS_TRADE_TAGS["long"]
TICK = {"TESTSTOCK.NS": {"ltp": 100.0, "trading_symbol": "TESTSTOCK-EQ"}}


def _env():
    return (patch("kotak_live_feed.get_live_ticks", return_value=TICK),
            patch("main.get_scheduler_capital_inr", return_value=1000000.0),
            patch("main._real_today_spent_inr", return_value=0.0),
            patch("main._real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}),
            patch("kotak_real_orders.place_real_stop_loss", return_value={"ok": True, "order_id": "SL1", "trigger_price": 97.0}))


def test_news_tag_skips_viability_and_buys_exactly_one_share():
    _fresh_db()
    os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
    try:
        with closing(main.get_db()) as conn:
            a, b, c, d, e = _env()
            with a, b, c, d, e, patch("main._maybe_place_swing_option_leg") as opt, \
                 patch("kotak_real_orders.place_real_entry",
                       return_value={"ok": True, "qty": 1, "fill_price": 100.0, "order_id": "E1", "fill_price_confirmed": True}) as buy:
                assert main._is_strategy_viable_for_real_money(TAG) is False  # unmapped: only the override admits it
                assert main._news_real_open(conn, "TESTSTOCK.NS", "long", 100.0, 97.0, 1.0) is True
            assert buy.call_args[0][1] == 1  # risk sizing wanted far more on Rs10 lakh; the cap holds it to 1
            opt.assert_not_called()
            row = conn.execute("SELECT qty, strategy FROM real_positions_swing WHERE symbol='TESTSTOCK.NS'").fetchone()
            assert (row["qty"], row["strategy"]) == (1, TAG)
            assert conn.execute("SELECT strategy FROM signal_state_swing WHERE symbol='TESTSTOCK.NS'").fetchone()[0] == TAG
            ev = conn.execute("SELECT detail FROM real_order_events WHERE symbol='TESTSTOCK.NS' AND detail LIKE '%news entry%'").fetchone()
            assert "news entry" in ev["detail"] and "viability gate skipped" in ev["detail"]
    finally:
        os.environ.pop("REAL_SWING_TRADING_ENABLED", None)


def test_all_trading_switch_off_still_stops_a_news_buy_and_leaves_no_pending_row():
    _fresh_db()
    os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
    try:
        with closing(main.get_db()) as conn:
            a, b, c, d, e = _env()
            with a, b, c, d, e, patch("main.is_trading_enabled", return_value=False), \
                 patch("kotak_real_orders.place_real_entry") as buy:
                assert main._news_real_open(conn, "TESTSTOCK.NS", "long", 100.0, 97.0, 1.0) is False
            buy.assert_not_called()
            assert conn.execute("SELECT 1 FROM signal_state_swing WHERE symbol='TESTSTOCK.NS'").fetchone() is None
            assert conn.execute("SELECT status FROM real_trades WHERE symbol='TESTSTOCK.NS' ORDER BY id DESC").fetchone()[0] \
                == "skipped_strategy_not_viable"
    finally:
        os.environ.pop("REAL_SWING_TRADING_ENABLED", None)


def test_short_stays_paper_and_another_strategys_symbol_is_not_touched():
    _fresh_db()
    with closing(main.get_db()) as conn:
        with patch("main._maybe_place_real_swing_entry") as entry:
            assert main._news_real_open(conn, "TESTSTOCK.NS", "short", 100.0, 103.0, 1.0) is False
            conn.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, qty, "
                         "entry_ts) VALUES ('TESTSTOCK.NS', 'gap_and_go', '2026-11-10', 100, 90, 5, 1)")
            conn.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
                         "stop_loss, strategy) VALUES ('TESTSTOCK.NS','TESTSTOCK-EQ',5,100,1,'2026-11-10',90,'gap_and_go')")
            conn.commit()  # B-1553: only a REAL holding of another strategy blocks the news buy
            assert main._news_real_open(conn, "TESTSTOCK.NS", "long", 100.0, 97.0, 1.0) is False
        entry.assert_not_called()
        with patch("main._maybe_place_real_swing_exit") as ex:
            assert main._news_real_close(conn, "TESTSTOCK.NS", "long", "sentiment weak") is False
        ex.assert_not_called()
        assert conn.execute("SELECT strategy FROM signal_state_swing WHERE symbol='TESTSTOCK.NS'").fetchone()[0] == "gap_and_go"


def test_close_sells_the_news_share_through_the_swing_exit_with_the_reason():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, qty, "
                     "entry_ts) VALUES ('TESTSTOCK.NS', ?, '2026-11-10', 100, 97, 1, 1)", (TAG,))
        conn.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, "
                     "opened_at, day, stop_loss, strategy) VALUES ('TESTSTOCK.NS','TESTSTOCK-EQ',1,100,'E1',1,'2026-11-10',97,?)", (TAG,))
        with patch("main._maybe_place_real_swing_exit") as ex:
            assert main._news_real_close(conn, "TESTSTOCK.NS", "long", "sentiment weak (score 0.05, peak 0.60)") is True
        assert ex.call_args[1]["reason"].startswith("news_exit: sentiment weak")
        assert conn.execute("SELECT 1 FROM signal_state_swing WHERE symbol='TESTSTOCK.NS'").fetchone() is None


def test_swing_scan_leaves_news_exits_to_the_news_lifecycle():
    src = open("main.py").read()
    assert 'elif pos["strategy"] in NEWS_TRADE_TAGS.values():\n                reason = None' in src
    assert main.NEWS_REAL_QTY_CAP == 1 and main.NEWS_TRADE_MAX_HOLD_DAYS == 7
