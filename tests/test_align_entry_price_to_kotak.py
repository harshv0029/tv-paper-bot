"""B-295 part 2: entry_price rewritten to Kotak's fill price of the entry order."""
from contextlib import closing
import main


def test_entry_price_aligned(tmp_path, monkeypatch):
    main.init_db()
    for n in ("_sync_real_positions_external", "_sync_real_positions_short_external", "_sync_real_positions_swing_external"):
        monkeypatch.setattr(main, n, lambda c: None)
    monkeypatch.setattr(main, "_log_real_order_event", lambda *a, **k: None)
    with closing(main.get_db()) as conn:
        for t in ("real_positions", "real_positions_short", "real_positions_swing"):
            conn.execute(f"DELETE FROM {t}")
        ins = ("INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, opened_at, day) "
               "VALUES (?,?,?,?,?,?,?)")
        conn.execute(ins, ("AAA.NS", "AAA-EQ", 1, 100.0, "E1", 0.0, "2026-10-07"))   # complete, differs -> align
        conn.execute(ins, ("BBB.NS", "BBB-EQ", 1, 50.0, "E2", 0.0, "2026-10-07"))    # not complete -> untouched
        conn.execute(ins, ("CCC.NS", "CCC-EQ", 1, 70.0, "E3", 0.0, "2026-10-07"))    # not in book -> untouched
        conn.commit()
        rows = [{"nOrdNo": "E1", "ordSt": "complete", "avgPrc": "101.35"},
                {"nOrdNo": "E2", "ordSt": "open", "avgPrc": "0.00"}]
        out = main._align_entry_prices_to_kotak(conn, rows)
        g = {r["symbol"]: r["entry_price"] for r in conn.execute("SELECT symbol, entry_price FROM real_positions")}
        assert g == {"AAA.NS": 101.35, "BBB.NS": 50.0, "CCC.NS": 70.0}
        assert len(out) == 1
        assert main._align_entry_prices_to_kotak(conn, []) == []


def test_fo_entry_price_aligned(monkeypatch):
    main.init_db()
    for n in ("_sync_real_positions_external", "_sync_real_positions_short_external", "_sync_real_positions_swing_external"):
        monkeypatch.setattr(main, n, lambda c: None)
    monkeypatch.setattr(main, "_log_real_order_event", lambda *a, **k: None)
    with closing(main.get_db()) as conn:
        for t in ("real_positions", "real_positions_short", "real_positions_swing", "real_fo_positions"):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("INSERT INTO real_fo_positions (leg_key, underlying, strategy_tag, kotak_trading_symbol, "
                     "instrument_token, exchange_segment, qty, entry_price, entry_order_id, opened_at, day) "
                     "VALUES ('L1','NIFTY','single_leg_call','NIFTYX','1','nse_fo',50,100.0,'F1',0.0,'2026-10-07')")
        conn.commit()
        out = main._align_entry_prices_to_kotak(conn, [{"nOrdNo": "F1", "ordSt": "complete", "avgPrc": "98.5"}])
        assert len(out) == 1
        assert conn.execute("SELECT entry_price FROM real_fo_positions").fetchone()[0] == 98.5
