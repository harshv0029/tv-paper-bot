"""B-1564: Kotak contract-note fills win in the ROC/CAGR/XIRR ledger, so every exit since 2026-11-01 counts."""
import datetime as dt
import json
from pathlib import Path

import roc_kpis

NOTE = json.loads(Path(__file__).resolve().parents[1].joinpath("docs", "kotak_contract_note_fills.json").read_text())


def _live_like_ledger():
    # what the live ledger held on 2026-11-12: 11-11 positions() rows + tracked_union opening rows
    rows = [{"day": "2026-11-11", "trdsym": "BANKBARODA-EQ", "prod": "CNC", "source": "kotak_positions", "seg": "nse_cm",
             "buy_qty": 2, "buy_amt": 536.62, "sell_qty": 2, "sell_amt": 542.52},
            {"day": "2026-11-11", "trdsym": "COCHINSHIP-EQ", "prod": "CNC", "source": "kotak_positions", "seg": "nse_cm",
             "buy_qty": 0, "buy_amt": 0, "sell_qty": 1, "sell_amt": 1203.7}]
    for sym, day, q, px in (("TATASTEEL-EQ", "2026-11-09", 1, 189.2), ("IOC-EQ", "2026-11-02", 1, 135.67),
                            ("BANKINDIA-EQ", "2026-10-20", 8, 134.39)):
        rows.append({"day": day, "trdsym": sym, "prod": "CNC", "source": "opening", "seg": None,
                     "buy_qty": q, "buy_amt": q * px, "sell_qty": 0, "sell_amt": 0})
    return rows


def test_all_november_exits_counted_and_no_double_buys():
    merged = roc_kpis.merge_contract_note_fills(_live_like_ledger(), NOTE)
    out = roc_kpis.roc_kpis(merged, dt.date(2026, 11, 12))
    syms = sorted(t["symbol"] for t in out["closed_trades"])
    assert syms == sorted(["BANKBARODA-EQ", "COCHINSHIP-EQ", "IRCTC-EQ", "RECLTD-EQ", "RELIANCE-EQ", "SAIL-EQ", "WIPRO-EQ"])
    gross = {t["symbol"]: t["gross_pnl_inr"] for t in out["closed_trades"]}
    assert gross["SAIL-EQ"] == 21.0 and gross["RECLTD-EQ"] == 56.8 and gross["IRCTC-EQ"] == 31.6
    assert gross["WIPRO-EQ"] == 5.36 and gross["COCHINSHIP-EQ"] == -36.0 and gross["BANKBARODA-EQ"] == 5.9
    assert out["ledger_start"] == "2026-11-02" and out["periods"]["mtd"]["trades"] == 7
    assert not out["notes"]  # COCHINSHIP's sale now has its 11-09 buy
    opens = {}
    for r in merged:
        if r["trdsym"] in ("TATASTEEL-EQ", "IOC-EQ") and float(r["buy_qty"]) > 0:
            opens[r["trdsym"]] = opens.get(r["trdsym"], 0) + 1
    assert opens == {"TATASTEEL-EQ": 1, "IOC-EQ": 1}  # the tracked_union guess is replaced, not doubled
    assert any(r["trdsym"] == "BANKINDIA-EQ" for r in merged)  # pre-window holding kept


def test_no_note_is_a_no_op():
    rows = _live_like_ledger()
    assert roc_kpis.merge_contract_note_fills(rows, None) == rows


def test_note_file_has_no_account_identifiers():
    raw = Path(__file__).resolve().parents[1].joinpath("docs", "kotak_contract_note_fills.json").read_text()
    for bad in ("XUAEZ", "PAN", "client", "Client"):
        assert bad not in raw
