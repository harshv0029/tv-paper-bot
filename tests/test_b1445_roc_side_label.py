"""B-1445: /roc-kpis same-day round trip side comes from fill order / app records, never a default "long".
Run: pytest tests/test_b1445_roc_side_label.py"""
import datetime as dt
from contextlib import closing

import roc_kpis

D = dt.date
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _row(day, sym, bq=0, ba=0, sq=0, sa=0, prod="MIS", **kw):
    r = {"day": day, "trdsym": sym, "prod": prod, "source": "kotak_positions", "seg": "nse_cm",
         "buy_qty": bq, "buy_amt": ba, "sell_qty": sq, "sell_amt": sa}
    r.update(kw)
    return r


RELIANCE = _row("2026-11-02", "RELIANCE-EQ", bq=3, ba=4170.0, sq=3, sa=4200.0)  # sell 3, buy-to-cover 3


def _ts(h, m):
    return dt.datetime(2026, 11, 2, h, m, tzinfo=IST).timestamp()


def test_unknown_order_is_not_labelled_long():
    closed, open_lots, _ = roc_kpis.match_round_trips([RELIANCE])
    assert not open_lots and len(closed) == 1
    assert closed[0]["side"] == roc_kpis.SIDE_UNKNOWN != "long"
    assert closed[0]["gross_pnl_inr"] == 30.0


def test_app_record_short_entry_labels_short_and_pnl_unchanged():
    base, _, _ = roc_kpis.match_round_trips([RELIANCE])
    hints = roc_kpis.side_hints_from_app_records(
        [{"ts": _ts(9, 40), "kotak_trading_symbol": "RELIANCE-EQ", "leg": "short_entry", "event": "confirmed"}])
    assert hints == {("RELIANCE-EQ", "2026-11-02"): "short"}
    closed, _, _ = roc_kpis.match_round_trips([RELIANCE], side_hints=hints)
    t = closed[0]
    assert t["side"] == "short"
    assert t["buy_value_inr"] == 4170.0 and t["sell_value_inr"] == 4200.0 and t["entry_value_inr"] == 4200.0
    for k in ("gross_pnl_inr", "net_pnl_inr", "charges_inr", "holding_days"):
        assert t[k] == base[0][k]


def test_first_fill_side_from_trade_book_wins():
    closed, _, _ = roc_kpis.match_round_trips([dict(RELIANCE, first_fill_side="sell")],
                                               side_hints={("RELIANCE-EQ", "2026-11-02"): "long"})
    assert closed[0]["side"] == "short"
    closed, _, _ = roc_kpis.match_round_trips([dict(RELIANCE, first_fill_side="BUY")])
    assert closed[0]["side"] == "long" and closed[0]["entry_value_inr"] == 4170.0


def test_earliest_confirmed_entry_decides_and_open_short_row_counts():
    ev = [{"ts": _ts(11, 0), "kotak_trading_symbol": "X-EQ", "leg": "entry", "event": "confirmed"},
          {"ts": _ts(9, 20), "kotak_trading_symbol": "X-EQ", "leg": "short_entry", "event": "confirmed"},
          {"ts": _ts(9, 30), "kotak_trading_symbol": "Y-EQ", "leg": "entry", "event": "placed"},  # not a fill
          {"ts": _ts(10, 0), "kotak_trading_symbol": "Z-EQ", "leg": "entry", "event": "confirmed"}]
    h = roc_kpis.side_hints_from_app_records(ev, [{"kotak_trading_symbol": "W-EQ", "day": "2026-11-02"}])
    assert h == {("X-EQ", "2026-11-02"): "short", ("Z-EQ", "2026-11-02"): "long", ("W-EQ", "2026-11-02"): "short"}


def test_payload_uses_real_order_events(tmp_path, monkeypatch):
    import main
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    main.init_db()
    with closing(main.get_db()) as conn:
        conn.execute("INSERT INTO kotak_fill_ledger (day, trdsym, prod, source, seg, buy_qty, buy_amt, sell_qty, "
                     "sell_amt) VALUES ('2026-11-02','RELIANCE-EQ','MIS','kotak_positions','nse_cm',3,4170,3,4200)")
        conn.execute("INSERT INTO real_order_events (ts, symbol, kotak_trading_symbol, leg, event) "
                     "VALUES (?, 'RELIANCE.NS', 'RELIANCE-EQ', 'short_entry', 'confirmed')", (_ts(9, 40),))
        conn.commit()
    out = main._roc_kpis_payload(today=D(2026, 11, 2))
    assert [t["side"] for t in out["closed_trades"]] == ["short"]
