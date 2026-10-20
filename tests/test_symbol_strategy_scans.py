import main


def _reset():
    main._symbol_strategy_scans.clear()
    main._symbol_strategy_scans_day = ""
    main._current_scan_symbol.set(None)


def test_marker_records_per_symbol_and_clears():
    _reset()
    main._record_strategy_scan("t0")  # no marker -> nothing per-symbol
    seen = []
    for sym in main._scan_visit(["AAA.NS", "BBB.NS"]):
        main._record_strategy_scan("t1")
        if sym == "AAA.NS":
            main._record_strategy_scan("t2")
        seen.append(sym)
    assert seen == ["AAA.NS", "BBB.NS"]
    assert main._symbol_strategy_scans["AAA.NS"] == {"t1", "t2"}
    assert main._symbol_strategy_scans["BBB.NS"] == {"t1"}
    assert main._current_scan_symbol.get() is None
    assert main._symbol_strategies_tested_today("AAA.NS") == 2


def test_items_variant():
    _reset()
    for sym, _v in main._scan_visit_items({"X.NS": 1}.items()):
        main._record_strategy_scan("a")
    assert main._symbol_strategy_scans["X.NS"] == {"a"}


def test_resets_on_day_roll():
    _reset()
    for _ in main._scan_visit(["AAA.NS"]):
        main._record_strategy_scan("t1")
    assert main._symbol_strategies_tested_today("AAA.NS") == 1
    main._symbol_strategy_scans_day = "2000-01-01"
    assert main._symbol_strategies_tested_today("AAA.NS") == 0
    for _ in main._scan_visit(["BBB.NS"]):
        main._record_strategy_scan("t9")
    assert "AAA.NS" not in main._symbol_strategy_scans


def test_coverage_endpoint_uses_set():
    _reset()
    for _ in main._scan_visit(["AAA.NS"]):
        main._record_strategy_scan("power_play")
    r = main.symbol_strategy_coverage("AAA.NS")
    assert r["tested_today"] == 1 and r["tested_tags"] == ["power_play"]


def test_visit_count_driven_by_distinct_tags_and_gap_by_category():
    _reset()
    main._scheduler_last_visit_strategies.pop("AAA.NS", None)
    for _ in main._scan_visit(["AAA.NS"]):
        for t in ("a", "b", "c", "d"):
            main._record_strategy_scan(t)
    assert main._sync_visit_strategy_count("AAA.NS", 1) == 4  # set (4) beats legacy floor (1)
    assert main._sync_visit_strategy_count("ZZZ.NS", 3) == 3  # no set -> legacy floor
    r = main.symbol_strategy_coverage("AAA.NS")
    flat = [t for v in r["not_evaluated_by_category"].values() for t in v]
    assert set(flat) <= set(r["viable_not_tested_today"])
