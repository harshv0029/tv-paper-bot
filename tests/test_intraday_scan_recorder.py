import main


def test_long_scan_recorded_under_engine_tag():
    main._strategy_scan_counts.clear()
    main._strategy_scan_counts_day = main.ist_now().strftime("%Y-%m-%d")
    main._record_intraday_strategy_scan({"symbol": "X.NS"})
    main._record_intraday_strategy_scan({"strategy": "bullish_engulfing"})
    assert main._strategy_scan_counts["universal_score"] == 1
    assert main._strategy_scan_counts["bullish_engulfing"] == 1


def test_short_scan_recorded_under_both_short_tags():
    main._strategy_scan_counts.clear()
    main._strategy_scan_counts_day = main.ist_now().strftime("%Y-%m-%d")
    main._record_short_strategy_scans()
    for t in ("range_short_staged_ladder", "trend_down_momentum_short"):
        assert main._strategy_scan_counts[t] == 1
