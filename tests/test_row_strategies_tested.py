import main


def test_row_counts_all_evaluated_tags_not_visit_counter(monkeypatch):
    day = main.ist_now().strftime("%Y-%m-%d")
    monkeypatch.setattr(main, "_symbol_strategy_scans_day", day)
    monkeypatch.setattr(main, "_symbol_strategy_scans", {
        "ICICIGI.NS": {"universal_score", "range_short_staged_ladder", "trend_down_momentum_short", "gap_and_go"}})
    main._scheduler_last_visit_strategies["ICICIGI.NS"] = 3
    viable = {"gap_and_go", "a", "b", "c", "d", "e"}
    x, n = main._row_strategies_tested("ICICIGI.NS", viable, len(viable))
    assert x == 4 and n == 9 and x <= n


def test_row_fallback_when_no_symbol_record(monkeypatch):
    monkeypatch.setattr(main, "_symbol_strategy_scans", {})
    main._scheduler_last_visit_strategies["ZZ.NS"] = 3
    assert main._row_strategies_tested("ZZ.NS", {"a"}, 1) == (1, 1)
    main._scheduler_last_visit_strategies["ZZ.NS"] = 0
    assert main._row_strategies_tested("ZZ.NS", {"a"}, 1) == (None, 1)
