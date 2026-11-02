"""B-1451: View 4 since-start return, CAGR, XIRR and the daily rolling 30-day ROC series (roc_kpis.py)."""
import datetime as dt

import roc_kpis as rk

D = dt.date


def _row(day, buy_qty=0, buy_amt=0, sell_qty=0, sell_amt=0, prod="CNC", sym="ABC-EQ"):
    return {"day": day, "trdsym": sym, "seg": "nse_cm", "prod": prod, "buy_qty": buy_qty, "buy_amt": buy_amt,
            "sell_qty": sell_qty, "sell_amt": sell_amt}


def test_xirr_one_year_ten_percent():
    assert abs(rk.xirr([(D(2025, 1, 1), -1000), (D(2026, 1, 1), 1100)]) - 0.10) < 1e-6


def test_xirr_undefined_without_both_signs():
    assert rk.xirr([(D(2025, 1, 1), -1000)]) is None
    assert rk.xirr([]) is None


def test_xirr_loss_is_negative():
    assert rk.xirr([(D(2025, 1, 1), -1000), (D(2026, 1, 1), 900)]) < 0


def test_since_start_cagr_and_xirr():
    # buy 10 @100 on day 1, sell 10 @110 on day 11: +100 net (no charges); deployed 1000 for 11 of 20 days
    rows = [_row("2026-10-01", 10, 1000), _row("2026-10-11", sell_qty=10, sell_amt=1100), _row("2026-10-20")]
    out = rk.roc_kpis(rows, D(2026, 10, 20))
    s = out["since_start"]
    assert s["covered_days"] == 20 and s["trades"] == 1 and s["net_pnl_inr"] == 100
    avg = 1000 * 11 / 20
    assert abs(s["return_pct"] - 100 / avg * 100) < 1e-3
    assert abs(s["cagr_pct"] - ((1 + 100 / avg) ** (365 / 20) - 1) * 100) < 0.01
    assert abs(s["xirr_pct"] - (1.1 ** (365 / 10) - 1) * 100) < 0.5
    assert s["unreliable"] is True and "90 days" in s["reason"]


def test_since_start_without_ledger():
    s = rk.roc_kpis([], D(2026, 10, 20))["since_start"]
    assert s["cagr_pct"] is None and s["xirr_pct"] is None and s["reason"]


def test_open_lot_excluded_from_xirr_but_counted_in_deployed():
    rows = [_row("2026-10-01", 10, 1000)]
    s = rk.roc_kpis(rows, D(2026, 10, 5))["since_start"]
    assert s["xirr_pct"] is None and s["open_lots_excluded"] == 1 and s["avg_deployed_inr"] == 1000
    assert s["return_pct"] == 0 and s["cagr_pct"] == 0


def test_rolling_series_matches_rolling_period():
    rows = [_row("2026-09-01", 10, 1000), _row("2026-09-05", sell_qty=10, sell_amt=1050),
            _row("2026-10-01", 10, 1000), _row("2026-10-03", sell_qty=10, sell_amt=980), _row("2026-10-20")]
    out = rk.roc_kpis(rows, D(2026, 10, 20))
    ser = out["rolling_30d_series"]
    assert ser[0]["day"] == "2026-09-01" and ser[-1]["day"] == "2026-10-20" and len(ser) == 50
    assert ser[-1]["roc_pct"] == out["periods"]["rolling_30d"]["roc_pct"]
    assert ser[-1]["full_window"] is True and ser[0]["full_window"] is False
    # on 2026-09-05 the +50 trade is inside the window
    d5 = next(x for x in ser if x["day"] == "2026-09-05")
    assert d5["net_pnl_inr"] == 50 and d5["roc_pct"] > 0
