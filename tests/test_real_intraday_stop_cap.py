import main


def test_wide_stop_is_capped_and_tight_stop_untouched():
    assert main._cap_real_intraday_stop(123.05, 102.41) == round(123.05 * 0.95, 2)
    assert main._cap_real_intraday_stop(238.81, 203.35) == round(238.81 * 0.95, 2)
    assert main._cap_real_intraday_stop(100.0, 98.0) == 98.0
