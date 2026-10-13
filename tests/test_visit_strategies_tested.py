import main


def test_visit_resets_and_accumulates_strategies_tested():
    main._scheduler_last_visit_strategies.clear()
    main._record_scheduler_check("TESTSYM.NS")
    assert main._scheduler_last_visit_strategies["TESTSYM.NS"] == 0
    main._scheduler_last_visit_strategies["TESTSYM.NS"] += 1 + len(main._INTRADAY_SHORT_SCAN_TAGS)
    assert main._scheduler_last_visit_strategies["TESTSYM.NS"] == 3
    main._record_scheduler_check("TESTSYM.NS")  # next visit starts again from 0, check count keeps growing
    assert main._scheduler_last_visit_strategies["TESTSYM.NS"] == 0
    assert main._scheduler_check_counts["TESTSYM.NS"] >= 2
