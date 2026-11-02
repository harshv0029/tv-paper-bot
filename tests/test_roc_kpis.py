"""B-1442/B-1443: View 4 ROC KPIs (last month, MTD, rolling 30d) from the durable Kotak fill ledger, and the memory
label. Run: pytest tests/test_roc_kpis.py"""
import datetime as dt
import os
import re
import tempfile
from contextlib import closing

import roc_kpis
import main

D = dt.date


def _row(day, sym, bq=0, ba=0, sq=0, sa=0, prod="CNC", source="kotak_positions", seg="nse_cm"):
    return {"day": day, "trdsym": sym, "prod": prod, "source": source, "seg": seg,
            "buy_qty": bq, "buy_amt": ba, "sell_qty": sq, "sell_amt": sa}


def test_period_bounds_ist_month_edges():
    p = roc_kpis.period_bounds(D(2026, 11, 2))
    assert p["last_month"][:2] == (D(2026, 10, 1), D(2026, 10, 31))
    assert p["mtd"][:2] == (D(2026, 11, 1), D(2026, 11, 2))
    assert p["rolling_30d"][:2] == (D(2026, 10, 4), D(2026, 11, 2))
    j = roc_kpis.period_bounds(D(2027, 1, 1))  # year wrap
    assert j["last_month"][:2] == (D(2026, 12, 1), D(2026, 12, 31)) and j["mtd"][:2] == (D(2027, 1, 1), D(2027, 1, 1))
    m = roc_kpis.period_bounds(D(2028, 3, 15))  # leap February
    assert m["last_month"][:2] == (D(2028, 2, 1), D(2028, 2, 29))


def test_swing_trade_return_holding_days_and_return_per_day():
    rows = [_row("2026-10-20", "A-EQ", bq=10, ba=1000), _row("2026-10-25", "A-EQ", sq=10, sa=1100)]
    closed, open_lots, _ = roc_kpis.match_round_trips(rows)
    assert not open_lots and len(closed) == 1
    t = closed[0]
    assert t["return_pct"] == 10.0 and t["holding_days"] == 5 and t["return_per_day_pct"] == 2.0
    assert t["buy_value_inr"] == 1000 and t["sell_value_inr"] == 1100


def test_intraday_round_trip_and_short_mirror():
    rows = [_row("2026-11-02", "B-EQ", bq=5, ba=500, sq=5, sa=510, prod="MIS"),
            _row("2026-11-02", "C-EQ", bq=2, ba=196, sq=2, sa=200, prod="MIS")]
    closed, open_lots, _ = roc_kpis.match_round_trips(rows)
    assert not open_lots
    b = next(t for t in closed if t["symbol"] == "B-EQ")
    assert b["holding_days"] == 0 and b["return_per_day_pct"] == 2.0  # 0 days -> divide by 1
    # multi-day MIS short: sell first, cover next day
    s, _, _ = roc_kpis.match_round_trips([_row("2026-11-02", "S-EQ", sq=4, sa=400, prod="NRML"),
                                          _row("2026-11-03", "S-EQ", bq=4, ba=360, prod="NRML")])
    assert s[0]["side"] == "short" and s[0]["return_pct"] == 10.0 and s[0]["entry_value_inr"] == 400


def test_cnc_sell_without_entry_is_left_out_not_guessed():
    closed, open_lots, notes = roc_kpis.match_round_trips([_row("2026-11-02", "X-EQ", sq=3, sa=300)])
    assert not closed and not open_lots and notes and "no recorded entry" in notes[0]


def test_costs_applied_to_net_pnl():
    rows = [_row("2026-11-02", "A-EQ", bq=10, ba=1000, sq=10, sa=1100, prod="MIS")]
    k = roc_kpis.roc_kpis(rows, D(2026, 11, 2), charges_fn=lambda seg, s, p, b, x: 7.5)
    m = k["periods"]["mtd"]
    assert m["gross_pnl_inr"] == 100 and m["charges_inr"] == 7.5 and m["net_pnl_inr"] == 92.5
    assert m["covered_days"] == 1 and m["avg_deployed_inr"] == 1000 and m["roc_pct"] == 9.25


def test_mtd_rolling_and_last_month_partial_and_na():
    rows = [_row("2026-10-30", "A-EQ", bq=10, ba=1000), _row("2026-11-02", "A-EQ", sq=10, sa=1050)]
    k = roc_kpis.roc_kpis(rows, D(2026, 11, 2))
    assert k["ledger_start"] == "2026-10-30"
    lm, mtd, r30 = k["periods"]["last_month"], k["periods"]["mtd"], k["periods"]["rolling_30d"]
    # last month: covered 30-31 Oct, deployed 1000 both days, no exit in Oct -> ROC 0, partial
    assert lm["covered_days"] == 2 and lm["avg_deployed_inr"] == 1000 and lm["roc_pct"] == 0 and "partial" in lm["reason"]
    # MTD: Nov 1-2 deployed 1000 each, exit +50 on Nov 2 -> 5%
    assert mtd["covered_days"] == 2 and mtd["roc_pct"] == 5.0 and mtd["reason"] is None
    # rolling 30d: Oct 30 - Nov 2 covered (4 days), 50 / 1000 = 5%
    assert r30["covered_days"] == 4 and r30["roc_pct"] == 5.0 and "partial" in r30["reason"]
    assert k["closed_trades"][0]["holding_days"] == 3


def test_period_before_ledger_start_is_na_with_reason():
    k = roc_kpis.roc_kpis([_row("2026-11-02", "A-EQ", bq=1, ba=100)], D(2026, 11, 2))
    lm = k["periods"]["last_month"]
    assert lm["roc_pct"] is None and "ledger starts 2026-11-02" in lm["reason"]
    assert roc_kpis.roc_kpis([], D(2026, 11, 2))["periods"]["mtd"]["reason"].startswith("no Kotak fill ledger")


def test_zero_deployed_capital_is_na():
    # ledger started (an empty-flow day is impossible from Kotak, so use an opening lot closed before the period)
    rows = [_row("2026-09-01", "A-EQ", bq=1, ba=100, source="opening"), _row("2026-10-02", "A-EQ", sq=1, sa=110)]
    k = roc_kpis.roc_kpis(rows, D(2026, 11, 2))
    m = k["periods"]["mtd"]
    assert m["roc_pct"] is None and m["reason"] == "no capital deployed in the covered days"


def _db(monkeypatch):
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(main, "DB_PATH", p)
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "")
    main.init_db()


NOW = dt.datetime(2026, 11, 2, 14, 0)  # naive IST


def test_capture_never_shrinks_and_seeds_opening_lots(monkeypatch):
    _db(monkeypatch)
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO tracked_union (kotak_trading_symbol,qty,owner,entry_price,day,updated_at) "
                  "VALUES ('OLD-EQ',4,'swing',50,'2026-10-20',1)")
        c.commit()
    pos = [{"trdSym": "A-EQ", "prod": "MIS", "exSeg": "nse_cm", "flBuyQty": "10", "flSellQty": "10",
            "buyAmt": "1000", "sellAmt": "1010", "hsUpTm": "2026/11/02 13:00:00"},
           {"trdSym": "OLD-EQ", "prod": "CNC", "exSeg": "nse_cm", "flBuyQty": "0", "flSellQty": "4",
            "buyAmt": "0", "sellAmt": "220", "hsUpTm": "2026/11/02 13:00:00"},
           {"trdSym": "Y-EQ", "prod": "MIS", "flBuyQty": "1", "flSellQty": "0", "buyAmt": "5",
            "hsUpTm": "2026/11/01 13:00:00"}]  # not today: skipped
    assert main._capture_kotak_fill_ledger(pos, NOW) == 3
    shrunk = [dict(pos[0], flBuyQty="2", flSellQty="2", buyAmt="200", sellAmt="202")]
    main._capture_kotak_fill_ledger(shrunk, NOW)
    with closing(main.get_db()) as c:
        r = c.execute("SELECT buy_qty FROM kotak_fill_ledger WHERE trdsym='A-EQ'").fetchone()
        assert r[0] == 10
        assert c.execute("SELECT COUNT(*) FROM kotak_fill_ledger WHERE trdsym='Y-EQ'").fetchone()[0] == 0
    out = main._roc_kpis_payload(today=D(2026, 11, 2))
    old = next(t for t in out["closed_trades"] if t["symbol"] == "OLD-EQ")
    assert old["holding_days"] == 13 and old["return_pct"] == 10.0 and old["source"] == "kotak_positions"
    assert out["periods"]["mtd"]["net_pnl_inr"] < 230  # charges deducted from gross 10 + 20
    assert "order_id" not in str(out)


def test_ledger_is_in_upstash_mirror():
    assert "kotak_fill_ledger" in main._GENERIC_MIRROR_TABLES
    assert "kotak_fill_ledger" not in main._GENERIC_MIRROR_GIT_TIER


def test_simulated_wipe_restores_ledger(monkeypatch):
    store = {}
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "http://fake")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    monkeypatch.setattr(main, "_upstash_set", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(main, "hydrate_git_tier_tables", lambda: 0)
    for x in (main._generic_mirror_hydrated, main._generic_mirror_last_hash, main._generic_mirror_last_push_ts,
              main._generic_hydrate_last_try):
        x.clear()
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(main, "DB_PATH", p)
    main.init_db()
    main.hydrate_generic_tables_from_external()
    main._capture_kotak_fill_ledger([{"trdSym": "A-EQ", "prod": "MIS", "flBuyQty": "1", "flSellQty": "1",
                                      "buyAmt": "100", "sellAmt": "101", "hsUpTm": "2026/11/02 10:00:00"}], NOW)
    main.sync_generic_tables_external(only=("kotak_fill_ledger",))
    fd, p2 = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(main, "DB_PATH", p2)
    main.init_db()
    main._generic_mirror_hydrated.clear()
    main._generic_hydrate_last_try.clear()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        assert c.execute("SELECT sell_amt FROM kotak_fill_ledger WHERE trdsym='A-EQ'").fetchone()[0] == 101


def test_view4_memory_label_is_current_ram_not_a_quota():
    html = open(os.path.join(os.path.dirname(__file__), "..", "static", "trade-view4.html")).read()
    assert "of Render limit" not in html
    assert "rss_now_mb" in html and "not a daily/monthly quota" in html
    assert "/roc-kpis" in html and "Return/day" in html
    assert re.search(r"ROC", html)
