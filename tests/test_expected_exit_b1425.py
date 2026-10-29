"""B-1425: View 4 active-positions table shows LTP and the expected exit date per each strategy's time stop."""
import pathlib

import main


def test_trading_day_count_skips_weekend_and_holiday():
    # 2026-10-16 is a Friday; 2026-10-20 is an NSE holiday
    assert main._add_nse_trading_days("2026-10-16", 1) == "2026-10-19"
    assert main._add_nse_trading_days("2026-10-16", 2) == "2026-10-21"


def test_legacy_and_grammar_hold_specs():
    assert main._strategy_hold_spec("gap_and_go") == (main.SWING_GAP_AND_GO_MAX_HOLD_DAYS, "1d")
    assert main._strategy_hold_spec("minervini_vcp") == (main.MINERVINI_MAX_HOLD_DAYS, "1d")
    assert main._strategy_hold_spec("envelope__0d05_fade__long__1h__atr6_h30__v1") == (30, "1h")
    assert main._strategy_hold_spec(main.BRK20_SWING_TAG) == (main.BRK20_MAX_HOLD_BARS, "1d")
    assert main._strategy_hold_spec("unknown_tag") is None


def test_swing_expected_exit_date_and_hourly_bars():
    r = main._expected_exit_for_position("swing", "gap_and_go", "2026-10-29")
    assert r["expected_exit"] == main._add_nse_trading_days("2026-10-29", main.SWING_GAP_AND_GO_MAX_HOLD_DAYS)
    r = main._expected_exit_for_position("swing", "envelope__0d05_fade__long__1h__atr6_h30__v1", "2026-10-29")
    assert r["expected_exit"] == main._add_nse_trading_days("2026-10-29", 5)  # 30 x 1h bars, 7 per session
    assert main._expected_exit_for_position("swing", "unknown_tag", "2026-10-29")["expected_exit"] is None


def test_intraday_exits_today_at_square_off():
    r = main._expected_exit_for_position("buy", "universal_score", "2026-10-29", None, {"squareoff_min": 914})
    assert r["expected_exit"].endswith("15:14 IST")


def test_every_live_swing_tag_has_a_time_stop():
    tags = set(main.SWINGMINRR_TAGS) | set(main.ISLAND_ALL_TAGS) | set(main.PL1D_CELLS) | set(main.CHAN_SHAPE_CELLS) \
        | set(main.MACDDIV_LONG_LIVE_CELLS) | set(main.ENVELOPE_LONG_LIVE_CELLS) | set(main.CUP_CHEAT_LONG_LIVE_CELLS) \
        | set(main.GAPFADE_TAGS) | set(main.ONEIL_SWING_CELLS) | set(main.BRK20_SHORT_SWING_ATR_OF_TAG)
    missing = [t for t in tags if main._strategy_hold_spec(t) is None]
    assert not missing, missing


def test_view4_has_ltp_and_expected_exit_columns():
    html = pathlib.Path(__file__).resolve().parents[1].joinpath("static/trade-view4.html").read_text()
    assert "<th>LTP</th>" in html and "Expected exit (as per strategy)" in html
    assert "p.current_price" in html and "p.expected_exit" in html
