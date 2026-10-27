import main


def test_key_classifier():
    assert main._is_real_ticker_check_key("RELIANCE.NS")
    assert main._is_real_ticker_check_key("^NSEI")
    for k in ("X:RSI2FO", "NIFTY:STRIKE", "TCS.NS:OPT"):
        assert not main._is_real_ticker_check_key(k)


def test_headline_excludes_derivative_legs_but_keeps_counts():
    main._scheduler_check_counts.clear()
    main._scheduler_check_counts_day = main.ist_now().strftime("%Y-%m-%d")
    for _ in range(3):
        main._record_scheduler_check("RELIANCE.NS")
    for _ in range(50):
        main._record_scheduler_check("NIFTY26OCT24500CE:RSI2FO")
    p = main.scheduler_pipeline()
    assert main._scheduler_check_counts["NIFTY26OCT24500CE:RSI2FO"] == 50  # mirror data intact
    if isinstance(p, dict):
        assert p["total_checks_today"] == 3
        assert p["derivative_leg_checks_today"] == 50
    main._scheduler_check_counts.clear()


def _run_scan_with(df, force_close=False):
    from contextlib import closing
    from unittest.mock import patch
    desc = {"kind": "option", "kotak_trading_symbol": "NIFTY26OCT24500CE", "underlying": "NIFTY",
            "expiry": "2026-10-29"}
    main._scheduler_check_counts.clear()
    main._scheduler_skipped_visits.update({"day": "", "n": 0})
    with patch("kotak_fo_candle_feed.get_cached_fo_universe", return_value={("nse_fo", "1"): desc}), \
         patch("kotak_fo_candle_feed.read_fo_candles_as_df", return_value=df), \
         patch("fo_option_strategy.rsi2_mean_reversion_entry_signal", return_value=None), \
         patch("nse_fo_chain.must_force_close_before_expiry", return_value=force_close):
        main._fo_options_scan_last_ts = 0.0
        main.init_db()
        with closing(main.get_db()) as conn:
            main._run_fo_options_scan(conn)


def test_fo_leg_counted_only_when_evaluated():
    import pandas as pd
    _run_scan_with(None)
    assert "NIFTY26OCT24500CE:RSI2FO" not in main._scheduler_check_counts
    assert main._scheduler_skipped_visits_today() == 1
    _run_scan_with(None, force_close=True)
    assert "NIFTY26OCT24500CE:RSI2FO" not in main._scheduler_check_counts
    assert main._scheduler_skipped_visits_today() == 1
    _run_scan_with(pd.DataFrame({"close": [1.0]}))
    assert main._scheduler_check_counts["NIFTY26OCT24500CE:RSI2FO"] == 1
    assert main._scheduler_skipped_visits_today() == 0
    main._scheduler_check_counts.clear()


def test_pipeline_exposes_skipped_visits():
    main._scheduler_skipped_visits.update({"day": main.ist_now().strftime("%Y-%m-%d"), "n": 7})
    p = main.scheduler_pipeline()
    if isinstance(p, dict):
        assert p["derivative_leg_visits_skipped_today"] == 7
    main._scheduler_skipped_visits.update({"day": "", "n": 0})
