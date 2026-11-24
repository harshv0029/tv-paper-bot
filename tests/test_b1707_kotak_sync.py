"""B-1707 (user 2026-11-24 "make them sync with kotak numbers"): View 4 capital/ROC card matches Kotak: DP debit in
realised charges, open lots counted as Kotak shows them, unrealised at Kotak MTM, and an account reconcile line."""
import datetime as dt

import main
import roc_kpis

D = dt.date


def _row(day, sym, bq=0, ba=0, sq=0, sa=0, prod="CNC"):
    return {"day": day, "trdsym": sym, "prod": prod, "source": "kotak_positions", "seg": "nse_cm",
            "buy_qty": bq, "buy_amt": ba, "sell_qty": sq, "sell_amt": sa}


def test_dp_once_per_scrip_per_delivery_sell_day():
    rows = [_row("2026-11-02", "A-EQ", bq=1, ba=100), _row("2026-11-03", "A-EQ", bq=1, ba=102),
            _row("2026-11-05", "A-EQ", sq=2, sa=210),                       # 2 lots, one sell day -> one DP
            _row("2026-11-05", "B-EQ", bq=1, ba=50, sq=1, sa=51),           # same-day CNC: intraday, no DP
            _row("2026-11-04", "C-EQ", bq=1, ba=50, prod="MIS"), _row("2026-11-06", "C-EQ", sq=1, sa=55, prod="MIS")]
    closed, _, _ = roc_kpis.match_round_trips(rows)
    total = roc_kpis.apply_dp_charges(closed, 23.60)
    assert total == 23.60
    a = [t for t in closed if t["symbol"] == "A-EQ"]
    assert sum(t.get("dp_charge_inr") or 0 for t in a) == 23.60
    assert round(sum(t["net_pnl_inr"] for t in a), 2) == round(8 - 23.60, 2)


def test_roc_kpis_since_start_carries_dp():
    rows = [_row("2026-11-02", "A-EQ", bq=10, ba=1000), _row("2026-11-04", "A-EQ", sq=10, sa=1100)]
    base = roc_kpis.roc_kpis(rows, D(2026, 11, 5))["since_start"]
    dp = roc_kpis.roc_kpis(rows, D(2026, 11, 5), dp_per_sell_inr=23.60)
    assert dp["dp_charges_inr"] == 23.60 and dp["since_start"]["dp_charges_inr"] == 23.60
    assert dp["since_start"]["net_pnl_inr"] == round(base["net_pnl_inr"] - 23.60, 2)


def test_running_mtm_total_and_dp_once_per_symbol():
    ss = {"net_pnl_inr": 83.72, "covered_days": 23, "avg_deployed_inr": 13474.99}
    lots = [{"symbol": "F-EQ", "side": "long", "qty": 1, "entry_px": 100.0, "seg": "nse_cm", "prod": "CNC"},
            {"symbol": "F-EQ", "side": "long", "qty": 1, "entry_px": 102.0, "seg": "nse_cm", "prod": "CNC"}]
    out = roc_kpis.running_kpis(ss, lots, {"F-EQ": 101.0}, charges_fn=lambda *a: 0.0, dp_per_sell_inr=23.60)
    assert out["unrealised_gross_inr"] == 0.0 and out["unrealised_charges_inr"] == 23.60  # DP once, not twice
    assert out["total_mtm_inr"] == 83.72 and out["total_net_inr"] == round(83.72 - 23.60, 2)


def test_ledger_lots_kotak_no_longer_shows_open():
    ledger = [{"symbol": "G-EQ", "side": "long", "qty": 2, "entry_day": "2026-11-03", "entry_px": 10.0},
              {"symbol": "H-EQ", "side": "long", "qty": 1, "entry_day": "2026-11-04", "entry_px": 20.0}]
    kotak = [{"symbol": "G-EQ", "qty": 1, "source": "kotak_fill"}]
    gone = main._roc_ledger_lots_gone(ledger, kotak)
    assert [(g["symbol"], g["qty"]) for g in gone] == [("G-EQ", 1.0), ("H-EQ", 1.0)]


def test_card_shows_kotak_sync_fields():
    html = open("static/trade-view4.html").read()
    assert 'id="reconLine"' in html and "function reconRender(" in html
    assert "(Kotak MTM)" in html and "ledger_lots_not_open_at_kotak" in html and "S.dp_charges_inr" in html
