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
