"""B-345 MCX daily engine: gate, scan counters, entry/exit wiring, ownership."""
import pandas as pd
import main

GOLD = "sma_crossover__gc__long__1d__atrnone__v1"
SILVER = "keltner_channel_breakout__si__long__1d__atrnone__v1"


def test_gate_open_only_for_wired_viable_cells():
    assert main._is_strategy_viable_for_real_money(GOLD)
    assert main._is_strategy_viable_for_real_money(SILVER)
    assert not main._is_strategy_viable_for_real_money("sma_crossover__gc__long__5m__atrnone__v1")
    assert not main._is_strategy_viable_for_real_money("unknown_tag")


def test_scan_counts_each_tag_and_enters_on_fresh_signal(monkeypatch):
    main._strategy_scan_counts.clear()
    idx = pd.date_range("2025-01-01", periods=80, freq="D")
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1}, index=idx)
    monkeypatch.setattr(main, "fetch_ohlc", lambda *a, **k: df)
    monkeypatch.setattr(main, "_mcx_daily_flags", lambda d, s, p: (True, True))
    calls = []
    monkeypatch.setattr(main, "_maybe_place_real_fo_option_entry",
                        lambda conn, sym, spot, tag, right, tag_col=None: calls.append((sym, tag, right, tag_col)))

    class C:
        def execute(self, *a, **k):
            class R:
                def fetchone(self_): return None
            return R()
    main._run_mcx_daily_scan(C(), force=True)
    assert {c[1] for c in calls} == {GOLD, SILVER, "supertrend__si__long__1d__atrnone__v1"}
    assert all(c[2] == "call" and c[3] == f"single_leg_mcx_{c[1]}" for c in calls)
    assert main._strategy_scan_counts.get(GOLD) == 1 and main._strategy_scan_counts.get(SILVER) == 1


def test_exit_on_signal_drop_and_paper_exit_does_not_close_it(monkeypatch):
    closed = []
    monkeypatch.setattr(main, "_close_real_fo_option_leg", lambda conn, row, reason: closed.append(reason))
    monkeypatch.setattr(main, "fetch_ohlc", lambda *a, **k: pd.DataFrame(
        {"Close": [1.0] * 80}, index=pd.date_range("2025-01-01", periods=80)))
    monkeypatch.setattr(main, "_mcx_daily_flags", lambda d, s, p: (False, False))

    class C:
        def execute(self, *a, **k):
            class R:
                def fetchone(self_): return {"strategy_tag": "single_leg_mcx_" + main._MCX_DAILY_CELLS[0][0], "leg_key": "x"}
            return R()
    main._run_mcx_daily_scan(C(), force=True)
    assert len(closed) == 1 and "daily signal dropped" in closed[0]
    closed.clear()
    main._maybe_place_real_fo_option_exit(C(), "GC=F", "call", "paper exit")
    assert closed == []


def test_scan_activity_counts_mcx_entries():
    import time
    from contextlib import closing
    with closing(main.get_db()) as c:
        c.execute("DELETE FROM real_fo_trades")
        main._log_real_fo_attempt(c, "GOLDM:CALL", "B", "confirmed",
                                  detail=f"reason: call bought on viable setup strategy_tag={GOLD} index signal")
    rows = main.strategy_scan_activity()
    rows = rows.get("strategies", rows) if isinstance(rows, dict) else rows
    r = next(x for x in rows if x["strategy_tag"] == GOLD)
    assert r["successful_entries_today"] == 1
