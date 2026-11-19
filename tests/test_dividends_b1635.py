"""B-1635: dividends credited to long lots held across an ex-date (live P&L add-back and backtest helper)."""
import datetime as dt

import dividends as dv

D = dt.date


def test_entitlement_rules():
    ev = [(D(2026, 8, 10), 5.0)]
    assert dv.lot_dividend(ev, 10, D(2026, 8, 9), D(2026, 8, 10)) == [(D(2026, 8, 10), 5.0, 50.0)]  # sold ON ex-date: kept
    assert dv.lot_dividend(ev, 10, D(2026, 8, 10), D(2026, 8, 20)) == []  # bought on ex-date: not entitled
    assert dv.lot_dividend(ev, 10, D(2026, 8, 1), D(2026, 8, 9)) == []  # sold before ex-date
    assert dv.lot_dividend(ev, 10, D(2026, 8, 1), None, today=D(2026, 8, 15))[0][2] == 50.0  # open lot


def test_fifo_partial_sells_and_open_lot():
    ev = {"A.NS": [(D(2026, 8, 10), 2.0), (D(2026, 9, 10), 3.0)]}
    trades = [{"symbol": "A.NS", "side": "B", "qty": 10, "day": "2026-08-01"},
              {"symbol": "A.NS", "side": "S", "qty": 4, "day": "2026-08-20"},
              {"symbol": "A.NS", "side": "B", "qty": 5, "day": "2026-09-01"}]
    r = dv.fifo_dividends(trades, lambda s: ev.get(s, []), today=D(2026, 9, 30))
    # 4 sold after Aug ex: 8; 6 open: Aug 12 + Sep 18; 5 bought Sep 1 open: Sep 15
    assert r["gross_inr"] == 53.0 and r["tds_est_inr"] == 0.0


def test_short_then_cover_opens_no_long_lot():
    ev = [(D(2026, 8, 10), 5.0)]
    trades = [{"symbol": "A.NS", "side": "S", "qty": 10, "day": "2026-08-05"},
              {"symbol": "A.NS", "side": "B", "qty": 10, "day": "2026-08-05"}]
    assert dv.fifo_dividends(trades, lambda s: ev, today=D(2026, 9, 1))["gross_inr"] == 0.0


def test_intraday_lot_skips_lookup():
    calls = []
    trades = [{"symbol": "A.NS", "side": "buy", "qty": 1, "ts": 1790000000},
              {"symbol": "A.NS", "side": "sell", "qty": 1, "ts": 1790000100}]
    dv.fifo_dividends(trades, lambda s: calls.append(s) or [])
    assert calls == []


def test_tds_over_threshold_per_company_fy():
    ev = [(D(2026, 8, 10), 60.0)]
    r = dv.fifo_dividends([{"symbol": "A.NS", "side": "B", "qty": 100, "day": "2026-08-01"}], lambda s: ev,
                          today=D(2026, 9, 1))
    assert r["gross_inr"] == 6000.0 and r["tds_est_inr"] == 600.0 and r["net_inr"] == 5400.0


def test_events_fetch_injected_and_failure_safe():
    dv._CACHE.clear()
    assert dv.dividend_events("X.NS", fetch=lambda s: {dt.datetime(2026, 8, 10): 4.0}) == [(D(2026, 8, 10), 4.0)]
    dv._CACHE.clear()
    assert dv.dividend_events("Y.NS", fetch=lambda s: (_ for _ in ()).throw(RuntimeError("x"))) == []


def test_backtest_dividend_return():
    ev = [(D(2026, 8, 10), 5.0)]
    assert dv.backtest_dividend_return(ev, D(2026, 8, 1), D(2026, 8, 12), 100.0) == 0.05
    assert dv.backtest_dividend_return(ev, D(2026, 8, 11), D(2026, 8, 12), 100.0) == 0.0


def test_real_dividends_endpoint(monkeypatch, tmp_path):
    import main
    from contextlib import closing
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    main.init_db()
    monkeypatch.setattr(dv, "dividend_events", lambda s, fetch=None: [(dt.date.today() - dt.timedelta(days=5), 7.0)])
    old = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_trades (ts, day, symbol, side, qty, status) VALUES (?,?,?,?,?,?)",
                  (1.0, old, "DIVTEST.NS", "B", 3, "confirmed"))
        c.commit()
    r = main.get_real_dividends(days=365)
    assert r["by_symbol"]["DIVTEST.NS"]["gross_inr"] == 21.0
