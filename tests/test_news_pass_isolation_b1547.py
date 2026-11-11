"""B-1547 (LENSKART 2026-11-11): the news pass stopped reaching the open-trades loop after 09:13 IST, so the B-1546
re-base never ran. Open trades now go first and every stage (and every logged candidate) is isolated."""
import time
from unittest.mock import patch

import main


def test_open_trades_run_first_and_a_failing_stage_does_not_stop_the_rest():
    order = []
    with patch.object(main, "_news_open_trades_pass", side_effect=lambda t: order.append("open") or 1), \
         patch.object(main, "_news_monitor_candidates", side_effect=RuntimeError("boom")), \
         patch.object(main, "_news_monitor_evaluate", side_effect=lambda c, t: order.append("eval") or 0), \
         patch.object(main, "_news_sweep_watchlist", side_effect=lambda t: order.append("sweep") or 0), \
         patch.object(main, "_news_exit_real_holdings", side_effect=lambda c, t: order.append("exit") or []):
        out = main._news_monitor_pass()
    assert order == ["open", "eval", "sweep", "exit"]
    assert out["open_trades"] == 1 and any(e.startswith("log: RuntimeError") for e in out["errors"])
    st = main._news_pass_status()
    assert st["stage"] == "done" and st["finished_ist"] and st["result"]["open_trades"] == 1


def test_one_bad_candidate_does_not_stop_the_others(tmp_path):
    main.DB_PATH = str(tmp_path / "t.db")
    main.init_db()
    calls = []

    def verdict(sym, d, sector=None, ms=None):
        calls.append(sym)
        if sym == "BAD.NS":
            raise ValueError("bad feed")
        return {"action": "allow", "reason": "ok", "stock": {"score": 0.0, "n": 0}}
    cands = [("BAD.NS", "long", "entry", "x", 0, None), ("GOOD.NS", "long", "entry", "x", 0, None)]
    from contextlib import closing
    with closing(main.get_db()) as conn, patch("news_signals.entry_verdict", side_effect=verdict), \
            patch.object(main, "_news_live_ltp", return_value=0.0):
        n = main._news_monitor_log(conn, cands, "2026-11-11", time.time(), ms={"market": {}, "sectors": {}})
        rows = [r["symbol"] for r in conn.execute("SELECT symbol FROM news_signal_events")]
    assert calls == ["BAD.NS", "GOOD.NS"] and n == 1 and rows == ["GOOD.NS"]


def test_stuck_pass_is_flagged():
    class T:
        def is_alive(self):
            return True
    with patch.object(main, "_news_monitor_thread", T()):
        main._NEWS_PASS_STATE["started_ts"] = time.time() - 900
        assert main._news_pass_status()["stuck"] is True
    main._NEWS_PASS_STATE["started_ts"] = None
