import main


def test_budget_message_not_contradictory():
    # Rs 33 free, Rs 11 unit: cannot cover Rs-100 dust floor -> insufficient, never "budget too small for 1 unit"
    assert main.usable_capital_inr_for_msg(33, 11, 100.0) is True
    # enough for the floor but qty rounds to dust -> the other message
    assert main.usable_capital_inr_for_msg(500, 11, 100.0) is False
    assert main.usable_capital_inr_for_msg(50, 400, 100.0) is True


def test_tested_never_exceeds_applicable(monkeypatch):
    day = main.ist_now().strftime("%Y-%m-%d")
    monkeypatch.setattr(main, "_symbol_strategy_scans_day", day)
    tags = {f"t{i}" for i in range(123)}
    monkeypatch.setattr(main, "_symbol_strategy_scans", {"X.NS": tags})
    x, n = main._row_strategies_tested("X.NS", {f"v{i}" for i in range(61)}, 61)
    assert x == 123 and n >= x
    main._scheduler_last_visit_strategies["Y.NS"] = 500
    monkeypatch.setattr(main, "_symbol_strategy_scans", {})
    x, n = main._row_strategies_tested("Y.NS", {"a"}, 61)
    assert x <= n
