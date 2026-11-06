"""B-1492: entries rejected because the Kotak balance cannot fund them are their own reason and are counted on View 4."""
import sqlite3

import main
from tests.test_viability_rejections_counter import _db


def test_skip_status_by_balance():
    assert main._real_qty_skip_status(0) == "skipped_low_balance"
    assert main._real_qty_skip_status(-3) == "skipped_low_balance"
    assert main._real_qty_skip_status(None) == "skipped_low_balance"
    assert main._real_qty_skip_status(5) == "skipped_insufficient_real_qty"


def test_counts_low_balance_fo_margin_and_kotak_funds_rejects_only(monkeypatch):
    c = _db()
    monkeypatch.setitem(main._real_capital_cache, "value", 1500.0)
    main._log_real_attempt(c, "TCS.NS", "B", "skipped_low_balance", price_est=3200.0, strategy="gap_and_go")
    main._log_real_attempt(c, "SBIN.NS", "B", "skipped_low_balance", price_est=820.0, strategy="gap_and_go")
    main._log_real_attempt(c, "INFY.NS", "B", "failed", detail="RMS:Margin Exceeds, Required:5000, Available:1500",
                           price_est=1500.0, strategy="brk20")
    main._log_real_attempt(c, "ITC.NS", "B", "failed", detail="RMS:Rule: Check T1 holdings", strategy="brk20")  # not balance
    main._log_real_attempt(c, "NHPC.NS", "B", "failed", detail="insufficient funds", strategy="gap_and_go", leg="exit")  # exit
    main._log_real_attempt(c, "WIPRO.NS", "B", "skipped_insufficient_real_qty", strategy="gap_and_go")  # daily cap, not balance
    main._log_real_fo_attempt(c, "NIFTY:CE", "B", "skipped_margin_unaffordable", price_est=120.0, detail="strategy_tag=opt_x")
    day = main.ist_now().strftime("%Y-%m-%d")
    r = main._balance_rejections_today(c, day)
    assert r["total"] == 4 and r["symbols"] == 4
    by = {(x["strategy"], x["segment"]): x["count"] for x in r["by_strategy"]}
    assert by == {("gap_and_go", "equity"): 2, ("brk20", "equity"): 1, ("opt_x", "fo"): 1}
    assert r["kotak_net_inr"] == 1500.0 and r["cheapest_rejected_price_inr"] == 120.0
    # viability counter is unaffected
    assert main._viability_rejections_today(c, day)["total"] == 0


def test_empty_never_raises():
    assert main._balance_rejections_today(sqlite3.connect(":memory:"), "2026-11-06")["total"] == 0
