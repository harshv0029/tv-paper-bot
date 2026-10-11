import sqlite3, main


def _conn():
    c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE swing_scan_log (scan_date TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE signal_state_swing (symbol TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE swing_done_today (day TEXT NOT NULL, symbol TEXT NOT NULL, PRIMARY KEY (day, symbol))")
    c.execute("CREATE TABLE strategy_scan_counts (day TEXT NOT NULL, tag TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY (day, tag))")
    return c


def _setup(monkeypatch, market_open):
    calls = []
    monkeypatch.setattr(main, "_switch_allows_entries", lambda c: True)
    monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda: market_open)
    monkeypatch.setattr(main, "_run_swing_scan_pass", lambda c: calls.append(1))
    monkeypatch.setattr(main, "_swing_last_pass_ts", 0.0)
    return calls


def test_first_pass_then_gated_by_interval_and_market(monkeypatch):
    calls = _setup(monkeypatch, True)
    c = _conn()
    main._run_swing_scan(c)
    assert len(calls) == 1
    main._run_swing_scan(c)          # within 15 min: no repeat
    assert len(calls) == 1
    monkeypatch.setattr(main, "_swing_last_pass_ts", 0.0)
    main._run_swing_scan(c)          # interval elapsed, market open: repeat pass
    assert len(calls) == 2


def test_no_repeat_when_market_closed(monkeypatch):
    calls = _setup(monkeypatch, False)
    c = _conn()
    main._run_swing_scan(c)
    monkeypatch.setattr(main, "_swing_last_pass_ts", 0.0)
    main._run_swing_scan(c)
    assert len(calls) == 1


def test_entered_symbol_marked_done_and_counts_persist(monkeypatch):
    _setup(monkeypatch, True)
    c = _conn()
    monkeypatch.setattr(main, "_run_swing_scan_pass", lambda cc: cc.execute("INSERT INTO signal_state_swing VALUES ('TCS.NS')"))
    main._strategy_scan_counts["gap_and_go"] = 7
    main._run_swing_scan(c)
    assert c.execute("SELECT symbol FROM swing_done_today").fetchone()[0] == "TCS.NS"
    assert c.execute("SELECT n FROM strategy_scan_counts WHERE tag='gap_and_go'").fetchone()[0] == 7
    main._strategy_scan_counts.clear()
    main._restore_strategy_scan_counts(c)
    assert main._strategy_scan_counts["gap_and_go"] == 7


def test_every_viable_row_has_an_sl_rule_or_pct():
    d = main.strategy_scan_activity()
    rows = d if isinstance(d, list) else next(v for v in d.values() if isinstance(v, list))
    bad = [r["strategy_tag"] for r in rows if r.get("sl_pct") is None and not r.get("sl_rule")]
    assert not bad, bad
