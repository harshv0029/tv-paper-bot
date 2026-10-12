"""B-871: short-swing engine (1d brk20_min_rr SHORT cells, BUY protective stop, own tables).

Covers: tag mapping + PFnet gate, ATR param parity with the tag, entry/exit signal behaviour, no-trade-without-SL
(unwind), no new kill switch, overnight-product guard, engine ownership (intraday short engine and reconcile
adoption), Upstash mirror registration + simulated-wipe restore, 5-minute governance heal, reasoned logging.
NOT covered (cannot be): a full-universe replay of this path, and a real Kotak overnight short.
"""
import dataclasses
import json
import os
import re
import tempfile
from contextlib import closing
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

import main
import strategy_registry as sr


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def _frame(close, high=None, low=None, open_=None, start="2024-01-01"):
    close = np.asarray(close, float)
    o = close.copy() if open_ is None else np.asarray(open_, float)
    h = np.maximum(close, o) + 0.3 if high is None else np.asarray(high, float)
    l = np.minimum(close, o) - 0.3 if low is None else np.asarray(low, float)
    idx = pd.bdate_range(start, periods=len(close))
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": close, "Volume": 1000.0}, index=idx)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in idx]
    return df


def _breakdown(n=100):
    c = np.full(n, 100.0)
    c[-1] = 99.0          # closes below the prior 20-bar low (99.7)
    lo = c - 0.3
    lo[40] = 60.0         # room: prior 60-bar low far below
    return _frame(c, low=lo)


def test_tags_map_one_to_one_and_follow_grammar():
    assert len(main.SHORT_SWING_TAGS) == 6 == len(set(main.SHORT_SWING_TAGS))
    for tag, atr, rr in main.BRK20_SHORT_SWING_CELLS:
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[tag] == tag
        m = re.match(r"^brk20_min_rr__main_replay__short__1d__atr(\d)_rr(\d)(d5)?__v1$", tag)
        assert m, tag
        assert float(m.group(1)) == atr                      # ATR multiple parsed from the tag == the one used
        assert float(m.group(2)) + (0.5 if m.group(3) else 0) == rr
        assert "be1" not in tag                              # ratchet cells deliberately not wired


def test_every_wired_cell_is_registered_short_and_viable():
    for tag in main.SHORT_SWING_TAGS:
        strat = next(s for s in sr.REGISTRY if s.name == tag)
        assert strat.metrics.pfnet >= sr.PFNET_LIVE_FLOOR >= 1.1
        assert main._is_strategy_viable_for_real_money(tag, check_switch=False) is True


def test_gate_closes_below_floor():
    tag = main.SHORT_SWING_TAGS[0]
    strat = next(s for s in sr.REGISTRY if s.name == tag)
    orig = strat.metrics
    object.__setattr__(strat, "metrics", dataclasses.replace(orig, pfnet=1.05))
    try:
        assert main._is_strategy_viable_for_real_money(tag, check_switch=False) is False
    finally:
        object.__setattr__(strat, "metrics", orig)


def test_entry_signal_stop_is_above_entry_and_first_cell_wins():
    tag, sig = main.short_swing_entry_signal(_breakdown())
    assert sig is not None and tag == main.SHORT_SWING_TAGS[0]   # strictest atr4_rr4 fires first
    assert sig["stop_loss"] > sig["entry_price"]
    assert sig["stop_loss"] == pytest.approx(sig["entry_price"] + 4.0 * sig["atr_at_entry"])
    assert main.short_swing_entry_signal(_frame(np.full(100, 100.0))) == (None, None)


def test_sizing_uses_mirrored_stop_distance():
    _fresh_db()
    with closing(main.get_db()) as conn:
        up = main._short_swing_size(conn, 200000.0, 1.0, 100.0, 104.0)
        down = main._swing_position_size(conn, 200000.0, 1.0, 100.0, 96.0)
        assert up == down > 0
        assert main._short_swing_size(conn, 200000.0, 1.0, 100.0, 99.0) == 0   # stop not above entry


def test_exit_stop_rule_and_timeout():
    atr, entry, mult = 1.0, 100.0, 4.0
    tag = main.SHORT_SWING_TAGS[0]
    stop = entry + mult * atr
    n = 100
    base = _frame(np.full(n, 100.0))
    day = base["Date"].iloc[-1]
    assert main._short_swing_exit_reason(base, day, stop, atr, tag) is None
    nxt = _frame(np.full(n + 1, 100.0))
    hi = nxt["High"].to_numpy().copy()
    hi[-1] = 110.0       # high through the BUY-stop on the first bar after entry
    nxt["High"] = hi
    r = main._short_swing_exit_reason(nxt, day, stop, atr, tag)
    assert r == "short_swing_stop_loss"
    # 30 quiet bars after the fill bar -> max-hold timeout (rule exit needs a falling EMA13 of 1/close: flat price, none)
    long_df = _frame(np.full(n + 32, 100.0))
    r2 = main._short_swing_exit_reason(long_df, day, stop, atr, tag)
    assert r2 == "short_swing_max_hold_timeout"


# ---- tables, mirror, ownership -------------------------------------------------------------------------------------

def test_new_tables_exist_and_are_upstash_mirrored():
    _fresh_db()
    assert "signal_state_swing_short" in main._GENERIC_MIRROR_TABLES
    assert "real_positions_swing_short" in main._GENERIC_MIRROR_TABLES
    with closing(main.get_db()) as conn:
        for t in ("signal_state_swing_short", "real_positions_swing_short"):
            conn.execute(f"SELECT * FROM {t}")


def test_simulated_wipe_restores_real_short_swing_row_from_upstash():
    _fresh_db()
    rows = [{"symbol": "ABC.NS", "kotak_trading_symbol": "ABC-EQ", "qty": 3, "entry_price": 100.0, "entry_order_id": "E1",
             "opened_at": 1.0, "day": "2026-10-12", "stop_loss": 108.0, "sl_order_id": "S1", "sl_trigger_price": 108.0,
             "strategy": main.SHORT_SWING_TAGS[0]}]
    store = {main._generic_mirror_key("real_positions_swing_short", "meta"): json.dumps({"chunks": 1}),
             main._generic_mirror_key("real_positions_swing_short", "c0"): json.dumps(rows)}
    with patch("main._upstash_get", side_effect=lambda k: store.get(k)):
        with closing(main.get_db()) as conn:
            assert main._generic_hydrate_table(conn, "real_positions_swing_short") is True
            got = conn.execute("SELECT * FROM real_positions_swing_short").fetchone()
    assert got["symbol"] == "ABC.NS" and got["sl_order_id"] == "S1"


def test_intraday_short_entry_refuses_swing_short_symbol():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute("INSERT INTO real_positions_swing_short (symbol, kotak_trading_symbol, qty, entry_price, opened_at, "
                     "day, stop_loss, strategy) VALUES ('ABC.NS','ABC-EQ',3,100,1,'2026-10-12',108,'t')")
        conn.commit()
        with patch("main.is_real_trading_enabled", return_value=True), \
                patch("main._asset_class_and_source", return_value=("nse_equity", None, None)), \
                patch("main._etf_entry_range_ok", return_value=(True, "")), \
                patch.dict("sys.modules", {"kotak_real_orders": MagicMock()}) as _:
            main._maybe_place_real_short_entry(conn, "ABC.NS")
        st = conn.execute("SELECT status FROM real_trades ORDER BY id DESC LIMIT 1").fetchone()
    assert st["status"] == "skipped_owned_by_swing_short_engine"


def test_intraday_short_exit_cannot_see_swing_short_row():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute("INSERT INTO real_positions_swing_short (symbol, kotak_trading_symbol, qty, entry_price, opened_at, "
                     "day, stop_loss, strategy) VALUES ('ABC.NS','ABC-EQ',3,100,1,'2026-10-12',108,'t')")
        conn.commit()
        fake = MagicMock()
        with patch.dict("sys.modules", {"kotak_real_orders": fake}):
            main._maybe_place_real_short_exit(conn, "ABC.NS", reason="test")
        fake.place_real_short_cover.assert_not_called()
        assert conn.execute("SELECT COUNT(*) FROM real_positions_swing_short").fetchone()[0] == 1


def test_reconcile_adopts_swing_short_signal_into_swing_short_table_and_is_not_untracked():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute("INSERT INTO signal_state_swing_short (symbol, strategy, entry_day, entry_price, initial_stop_loss, qty, "
                     "entry_ts, fx_to_inr, atr_at_entry) VALUES ('ABC.NS',?, '2026-10-09',100,108,3,1,1,2)",
                     (main.SHORT_SWING_TAGS[0],))
        conn.commit()
    pos = {"data": [{"exSeg": "nse_cm", "trdSym": "ABC-EQ", "flBuyQty": "0", "flSellQty": "3", "sellAmt": "300"}]}
    with patch("kotak_neo.positions", return_value=pos), patch("kotak_neo.limits", return_value={"Net": "1000"}), \
            patch("kotak_neo.order_report", return_value={"data": []}), \
            patch("main._nse_equity_market_open_now", return_value=False), \
            patch("main._ensure_resting_short_sl", return_value={"ok": False, "detail": "x"}):
        result = main._reconcile_real_positions_core(adopt="*")
    with closing(main.get_db()) as conn:
        row = conn.execute("SELECT * FROM real_positions_swing_short WHERE symbol='ABC.NS'").fetchone()
        assert row is not None and row["stop_loss"] == 108.0 and row["strategy"] == main.SHORT_SWING_TAGS[0]
        assert conn.execute("SELECT COUNT(*) FROM real_positions_short").fetchone()[0] == 0
    assert result["untracked_open_positions_count"] == 0


def test_reconcile_clears_swing_short_ghost_when_kotak_shows_no_short():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute("INSERT INTO real_positions_swing_short (symbol, kotak_trading_symbol, qty, entry_price, opened_at, "
                     "day, stop_loss, strategy) VALUES ('ABC.NS','ABC-EQ',3,100,1,'2026-10-12',108,'t')")
        conn.commit()
    with patch("kotak_neo.positions", return_value={"data": []}), patch("kotak_neo.limits", return_value={"Net": "1000"}), \
            patch("kotak_neo.order_report", return_value={"data": []}), \
            patch("main._nse_equity_market_open_now", return_value=False):
        main._reconcile_real_positions_core(adopt=None)
    with closing(main.get_db()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM real_positions_swing_short").fetchone()[0] == 0


# ---- real entry path -------------------------------------------------------------------------------------------------

def _entry_env(monkeypatch, confirmed=True, sl_ok=True, viable=True):
    monkeypatch.setattr(main, "SHORT_SWING_OVERNIGHT_PRODUCT_CONFIRMED", confirmed)
    monkeypatch.setattr(main, "is_real_swing_trading_enabled", lambda: True)
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda *_a, **_k: viable)
    monkeypatch.setattr(main, "_kotak_bought_today", lambda *_a, **_k: False)
    monkeypatch.setattr(main, "_effective_real_daily_cap_inr", lambda *_a, **_k: 100000.0)
    monkeypatch.setattr(main, "_real_today_spent_inr", lambda *_a, **_k: 0.0)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 100000.0)
    monkeypatch.setattr(main, "_real_loss_budget", lambda *_a, **_k: {"ok": True, "real_pnl_today": 0.0, "detail": ""})
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda *a, **k: 0)
    monkeypatch.setattr(main, "_ensure_resting_short_sl",
                        lambda *a, **k: ({"ok": True, "order_id": "SL1", "trigger_price": 108.0} if sl_ok
                                         else {"ok": False, "detail": "rejected"}))
    fake_feed = MagicMock()
    fake_feed.get_live_ticks.return_value = {"ABC.NS": {"ltp": 100.0, "trading_symbol": "ABC-EQ"}}
    fake_ko = MagicMock()
    fake_ko.place_real_short_entry.return_value = {"ok": True, "order_id": "E1", "qty": 3, "fill_price": 100.0,
                                                   "fill_price_confirmed": True}
    fake_ko.place_real_short_cover.return_value = {"ok": True, "order_id": "C1", "qty": 3, "fill_price": 100.5}
    monkeypatch.setitem(__import__("sys").modules, "kotak_live_feed", fake_feed)
    monkeypatch.setitem(__import__("sys").modules, "kotak_real_orders", fake_ko)
    return fake_ko


def test_real_entry_blocked_when_switch_off_logs_nothing(monkeypatch):
    _fresh_db()
    ko = _entry_env(monkeypatch)
    monkeypatch.setattr(main, "is_real_swing_trading_enabled", lambda: False)
    with closing(main.get_db()) as conn:
        main._maybe_place_real_swing_short_entry(conn, "ABC.NS", 3, 100.0, 108.0, main.SHORT_SWING_TAGS[0])
    ko.place_real_short_entry.assert_not_called()


def test_real_entry_held_while_overnight_product_unconfirmed(monkeypatch):
    _fresh_db()
    ko = _entry_env(monkeypatch, confirmed=False)
    with closing(main.get_db()) as conn:
        main._maybe_place_real_swing_short_entry(conn, "ABC.NS", 3, 100.0, 108.0, main.SHORT_SWING_TAGS[0])
        st = conn.execute("SELECT status FROM real_trades ORDER BY id DESC LIMIT 1").fetchone()["status"]
    ko.place_real_short_entry.assert_not_called()
    assert st == "skipped_overnight_short_product_unconfirmed"
    assert main.SHORT_SWING_OVERNIGHT_PRODUCT_CONFIRMED is False   # shipped default


def test_real_entry_blocked_when_not_viable(monkeypatch):
    _fresh_db()
    ko = _entry_env(monkeypatch, viable=False)
    with closing(main.get_db()) as conn:
        main._maybe_place_real_swing_short_entry(conn, "ABC.NS", 3, 100.0, 108.0, main.SHORT_SWING_TAGS[0])
    ko.place_real_short_entry.assert_not_called()


def test_real_entry_places_short_with_sl_row_and_reasoned_log(monkeypatch):
    _fresh_db()
    ko = _entry_env(monkeypatch)
    with closing(main.get_db()) as conn:
        main._maybe_place_real_swing_short_entry(conn, "ABC.NS", 3, 100.0, 108.0, main.SHORT_SWING_TAGS[0])
        row = conn.execute("SELECT * FROM real_positions_swing_short WHERE symbol='ABC.NS'").fetchone()
        ev = [dict(r) for r in conn.execute("SELECT leg, event, detail FROM real_order_events").fetchall()]
    assert ko.place_real_short_entry.call_args.kwargs["product"] == main.SHORT_SWING_PRODUCT
    assert row["sl_order_id"] == "SL1" and row["stop_loss"] == 108.0 and row["qty"] == 3
    assert any(e["leg"] == "short_sl" and e["event"] == "placed" and "reason:" in (e["detail"] or "") for e in ev)
    assert any(e["leg"] == "entry" and "reason:" in (e["detail"] or "") for e in ev)
    ko.place_real_short_cover.assert_not_called()


def test_no_trade_without_sl_unwinds_the_entry(monkeypatch):
    _fresh_db()
    ko = _entry_env(monkeypatch, sl_ok=False)
    with closing(main.get_db()) as conn:
        main._maybe_place_real_swing_short_entry(conn, "ABC.NS", 3, 100.0, 108.0, main.SHORT_SWING_TAGS[0])
        n = conn.execute("SELECT COUNT(*) FROM real_positions_swing_short").fetchone()[0]
        ev = [dict(r) for r in conn.execute("SELECT leg, event, detail FROM real_order_events").fetchall()]
    ko.place_real_short_cover.assert_called_once()
    assert ko.place_real_short_cover.call_args.kwargs["product"] == main.SHORT_SWING_PRODUCT
    assert n == 0
    assert any(e["leg"] == "short_cover" and "unwind" in (e["detail"] or "") for e in ev)


def test_unwind_failure_keeps_row_so_heal_keeps_protecting(monkeypatch):
    _fresh_db()
    ko = _entry_env(monkeypatch, sl_ok=False)
    ko.place_real_short_cover.return_value = {"ok": False, "detail": "rejected"}
    with closing(main.get_db()) as conn:
        main._maybe_place_real_swing_short_entry(conn, "ABC.NS", 3, 100.0, 108.0, main.SHORT_SWING_TAGS[0])
        row = conn.execute("SELECT * FROM real_positions_swing_short").fetchone()
    assert row is not None and row["sl_order_id"] is None


def test_stop_not_above_price_is_refused(monkeypatch):
    _fresh_db()
    ko = _entry_env(monkeypatch)
    with closing(main.get_db()) as conn:
        main._maybe_place_real_swing_short_entry(conn, "ABC.NS", 3, 100.0, 99.0, main.SHORT_SWING_TAGS[0])
        st = conn.execute("SELECT status FROM real_trades ORDER BY id DESC LIMIT 1").fetchone()["status"]
    ko.place_real_short_entry.assert_not_called()
    assert st == "skipped_stop_not_above_price"


# ---- exit ------------------------------------------------------------------------------------------------------------

def _seed_real_row(conn, sl_id="SL1"):
    conn.execute("INSERT INTO real_positions_swing_short (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
                 "stop_loss, sl_order_id, sl_trigger_price, strategy) VALUES ('ABC.NS','ABC-EQ',3,100,1,'2026-10-12',108,?,108,'t')",
                 (sl_id,))
    conn.commit()


def test_exit_cancels_sl_covers_and_logs_reason(monkeypatch):
    _fresh_db()
    fake = MagicMock()
    fake.cancel_real_order.return_value = {"ok": True}
    fake.place_real_short_cover.return_value = {"ok": True, "order_id": "C1", "qty": 3, "fill_price": 95.0}
    monkeypatch.setitem(__import__("sys").modules, "kotak_real_orders", fake)
    monkeypatch.setattr(main, "_kotak_symbol_still_open_short", lambda *_a, **_k: True)
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda *a, **k: 0)
    with closing(main.get_db()) as conn:
        _seed_real_row(conn)
        main._maybe_place_real_swing_short_exit(conn, "ABC.NS", reason="rule exit test")
        assert conn.execute("SELECT COUNT(*) FROM real_positions_swing_short").fetchone()[0] == 0
        ev = [dict(r) for r in conn.execute("SELECT leg, event, detail FROM real_order_events").fetchall()]
    fake.cancel_real_order.assert_called_once_with("SL1")
    assert fake.place_real_short_cover.call_args.kwargs["product"] == main.SHORT_SWING_PRODUCT
    assert any("rule exit test" in (e["detail"] or "") for e in ev if e["leg"] == "short_cover")
    assert not any("UNSTATED" in (e["detail"] or "") for e in ev)


def test_exit_stale_row_sends_no_order(monkeypatch):
    _fresh_db()
    fake = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "kotak_real_orders", fake)
    monkeypatch.setattr(main, "_kotak_symbol_still_open_short", lambda *_a, **_k: False)
    with closing(main.get_db()) as conn:
        _seed_real_row(conn)
        main._maybe_place_real_swing_short_exit(conn, "ABC.NS", reason="x")
        assert conn.execute("SELECT COUNT(*) FROM real_positions_swing_short").fetchone()[0] == 0
    fake.place_real_short_cover.assert_not_called()


def test_paper_exit_books_short_pnl_and_calls_real_exit_with_reason(monkeypatch):
    _fresh_db()
    seen = {}
    monkeypatch.setattr(main, "_maybe_place_real_swing_short_exit", lambda c, s, reason=None: seen.update(reason=reason))
    with closing(main.get_db()) as conn:
        conn.execute("INSERT INTO signal_state_swing_short (symbol, strategy, entry_day, entry_price, initial_stop_loss, qty, "
                     "entry_ts, fx_to_inr, atr_at_entry) VALUES ('ABC.NS','tagx','2026-10-09',100,108,10,1,1,2)")
        conn.commit()
        pos = conn.execute("SELECT * FROM signal_state_swing_short").fetchone()
        main._short_swing_close_paper(conn, "ABC.NS", pos, 90.0, "short_swing_rule_exit")
        pnl = conn.execute("SELECT pnl_inr, strategy FROM short_trades_closed").fetchone()
        assert conn.execute("SELECT COUNT(*) FROM signal_state_swing_short").fetchone()[0] == 0
    assert pnl["pnl_inr"] == pytest.approx(100.0) and pnl["strategy"] == "tagx"
    assert "short_swing_rule_exit" in seen["reason"]


# ---- 5-minute heal ---------------------------------------------------------------------------------------------------

def test_heal_places_missing_sl_every_run_and_aligns_dead_ids(monkeypatch):
    _fresh_db()
    monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda: True)
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda *a, **k: 0)
    placed = []
    monkeypatch.setattr(main, "_ensure_resting_short_sl",
                        lambda sym, qty, trg, product=None: placed.append((sym, qty, trg)) or
                        {"ok": True, "order_id": "NEW", "trigger_price": trg})
    with closing(main.get_db()) as conn:
        _seed_real_row(conn, sl_id="DEAD")   # app thinks SL DEAD rests; Kotak order book shows none
        out = main._heal_real_swing_short_sl(conn, [])
        row = conn.execute("SELECT * FROM real_positions_swing_short").fetchone()
    assert placed == [("ABC-EQ", 3, 108.0)]
    assert out and out[0]["sl_placed"] is True and row["sl_order_id"] == "NEW"


def test_heal_adopts_live_kotak_sl_without_placing(monkeypatch):
    _fresh_db()
    monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda: True)
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda *a, **k: 0)
    monkeypatch.setattr(main, "_ensure_resting_short_sl", lambda *a, **k: pytest.fail("must not place"))
    live = [{"trdSym": "ABC-EQ", "trnsTp": "B", "prcTp": "SL", "ordSt": "trigger pending", "nOrdNo": "K9", "trgPrc": "107.5"}]
    with closing(main.get_db()) as conn:
        _seed_real_row(conn, sl_id=None)
        main._heal_real_swing_short_sl(conn, live)
        row = conn.execute("SELECT * FROM real_positions_swing_short").fetchone()
    assert row["sl_order_id"] == "K9" and row["sl_trigger_price"] == 107.5


def test_ensure_resting_short_sl_adopts_and_places(monkeypatch):
    import kotak_real_orders as ko
    monkeypatch.setattr(ko, "_in_closing_session", lambda: False)
    placed = []
    monkeypatch.setattr(ko, "place_real_short_stop_loss",
                        lambda s, q, t, product="MIS": placed.append((s, q, t, product)) or
                        {"ok": True, "order_id": "P1", "trigger_price": t})
    rows = [{"trdSym": "ABC-EQ", "trnsTp": "B", "prcTp": "SL", "ordSt": "open", "nOrdNo": "K1", "trgPrc": "107", "qty": "3"}]
    with patch("kotak_neo.order_report", return_value={"data": rows}):
        r = main._ensure_resting_short_sl("ABC-EQ", 3, 108.0)
        assert r["action"] == "adopted_existing" and not placed          # tighter live stop adopted, nothing placed
        r2 = main._ensure_resting_short_sl("ABC-EQ", 3, 105.0)           # wanted stop is tighter than what rests
        assert r2["action"] == "placed" and placed[0][3] == main.SHORT_SWING_PRODUCT
    with patch("kotak_neo.order_report", return_value={"data": []}):
        r3 = main._ensure_resting_short_sl("ABC-EQ", 3, 108.0)
        assert r3["action"] == "placed"
    monkeypatch.setattr(ko, "_in_closing_session", lambda: True)
    assert main._ensure_resting_short_sl("ABC-EQ", 3, 108.0)["action"] == "skipped_closing_session"


def test_kotak_short_functions_default_to_mis_and_accept_product():
    import inspect
    import kotak_real_orders as ko
    for fn in (ko.place_real_short_entry, ko.place_real_short_cover, ko.place_real_short_stop_loss):
        assert inspect.signature(fn).parameters["product"].default == "MIS"   # intraday short engine unchanged


def test_no_new_kill_switch_env_var():
    src = open(main.__file__).read()
    i = src.index("B-871 (2026-10-12): SHORT-SWING engine (1d")
    section = src[i:src.index("# ---- Sector rotation momentum long (B-336")]
    assert "os.environ" not in section and "REAL_SHORT_SWING" not in section
    assert "is_real_swing_trading_enabled()" in section


def test_scan_pass_hooks_short_swing_pass_and_deployed_notional_counts_it():
    import inspect
    assert "_run_short_swing_pass(conn, dfs, capital, today, _done_syms)" in inspect.getsource(main._run_swing_scan_pass)
    _fresh_db()
    with closing(main.get_db()) as conn:
        before = main.deployed_notional(conn)
        conn.execute("INSERT INTO signal_state_swing_short (symbol, strategy, entry_day, entry_price, initial_stop_loss, qty, "
                     "entry_ts, fx_to_inr, atr_at_entry) VALUES ('ABC.NS','t','2026-10-09',100,108,10,1,1,2)")
        conn.commit()
        assert main.deployed_notional(conn) == pytest.approx(before + 1000.0)


def test_run_short_swing_pass_enters_then_exits(monkeypatch):
    _fresh_db()
    monkeypatch.setattr(main, "_maybe_place_real_swing_short_entry", lambda *a, **k: None)
    monkeypatch.setattr(main, "_maybe_place_real_swing_short_exit", lambda *a, **k: None)
    df = _breakdown()
    with closing(main.get_db()) as conn:
        main._run_short_swing_pass(conn, {"ABC.NS": df}, 200000.0, df["Date"].iloc[-1], set())
        pos = conn.execute("SELECT * FROM signal_state_swing_short WHERE symbol='ABC.NS'").fetchone()
        assert pos is not None and pos["initial_stop_loss"] > pos["entry_price"]
        # a long swing position on the symbol blocks a short entry
        conn.execute("DELETE FROM signal_state_swing_short")
        conn.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, qty, entry_ts) "
                     "VALUES ('ABC.NS','gap_and_go','2026-10-01',100,90,1,1)")
        conn.commit()
        main._run_short_swing_pass(conn, {"ABC.NS": df}, 200000.0, df["Date"].iloc[-1], set())
        assert conn.execute("SELECT COUNT(*) FROM signal_state_swing_short").fetchone()[0] == 0
