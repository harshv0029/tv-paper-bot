"""B-1561 (2026-11-11 IST): six viable swing setups were refused `skipped_no_live_tick` on the first pass after each
restart (feed not connected yet), and the next pass came 15 min later, after the 15:14 cutoff."""
from contextlib import closing

import pytest

import kotak_live_feed
import main


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    main.init_db()
    monkeypatch.setattr(main, "is_nse_trading_day", lambda *a, **k: True)
    monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda: True)
    monkeypatch.setattr(main, "_switch_allows_entries", lambda c: True)
    monkeypatch.setattr(main, "_sync_signal_state_swing_external", lambda c: None)
    monkeypatch.setattr(main, "_swing_last_pass_ts", 0.0)
    return tmp_path


def _ticks(n):
    return {f"S{i}.NS": {"ltp": 100.0, "trading_symbol": f"S{i}-EQ"} for i in range(n)}


def test_cold_feed_defers_the_pass_without_consuming_it(db, monkeypatch):
    monkeypatch.setattr(kotak_live_feed, "get_live_ticks", lambda: _ticks(3))
    ran = []
    monkeypatch.setattr(main, "_run_swing_scan_pass", lambda c: ran.append(1))
    with closing(main.get_db()) as c:
        main._run_swing_scan(c)
        assert ran == [] and main._swing_last_pass_ts == 0.0
        assert not c.execute("SELECT 1 FROM swing_scan_log").fetchone()   # first pass still owed


def test_warm_feed_runs_the_pass(db, monkeypatch):
    monkeypatch.setattr(kotak_live_feed, "get_live_ticks", lambda: _ticks(30))
    ran = []
    monkeypatch.setattr(main, "_run_swing_scan_pass", lambda c: ran.append(1))
    with closing(main.get_db()) as c:
        main._run_swing_scan(c)
    assert ran == [1]


def test_a_no_tick_refusal_brings_the_next_pass_forward(db, monkeypatch):
    import time
    monkeypatch.setattr(kotak_live_feed, "get_live_ticks", lambda: _ticks(30))

    def _pass(c):
        main._swing_no_tick_seen = True
    monkeypatch.setattr(main, "_run_swing_scan_pass", _pass)
    with closing(main.get_db()) as c:
        main._run_swing_scan(c)
    wait = main._swing_last_pass_ts + main.SWING_PASS_INTERVAL_SEC - time.time()
    assert 0 < wait <= main.SWING_NO_TICK_RETRY_SEC + 1


def test_normal_pass_keeps_the_15_min_interval(db, monkeypatch):
    import time
    monkeypatch.setattr(kotak_live_feed, "get_live_ticks", lambda: _ticks(30))
    monkeypatch.setattr(main, "_run_swing_scan_pass", lambda c: None)
    with closing(main.get_db()) as c:
        main._run_swing_scan(c)
    assert main._swing_last_pass_ts + main.SWING_PASS_INTERVAL_SEC - time.time() > 800


def test_feed_module_error_never_blocks(monkeypatch):
    monkeypatch.setattr(kotak_live_feed, "get_live_ticks", lambda: 1 / 0)
    assert main._swing_feed_warm() is True
