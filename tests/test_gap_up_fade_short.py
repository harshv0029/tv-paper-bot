"""Tests for the Gap-Up Fade short strategy (2026-09-30, explicit user
instruction "Read about it and backtest"). Not wired into main.py's live
scan/scheduler/order path - see strategy_registry.py's "registering !=
trading" principle. RESEARCH-STAGE ONLY until a full-universe validation
replay reports real numbers.

Standard definition: a stock gaps UP strongly at the open, but fails to
hold that gap during the session - price falls back below its own opening
print, signaling the initial buying enthusiasm has reversed. Short entry
fires on that reversal-below-open confirmation, not on the gap itself.
Intraday timeframe - distinct from gap_and_go_short_fade (a "gap DOWN and
continue" momentum trade, not a fade) and from gap_and_go itself (which
needs the gap to HOLD).

Run: pytest tests/test_gap_up_fade_short.py -v
"""
import pandas as pd

import main


def _bars(day, start_time, n, prices, vol=1000.0):
    ts = pd.date_range(f"{day} {start_time}", periods=n, freq="5min")
    return pd.DataFrame({
        "Date": ts, "Open": prices, "High": [p + 0.3 for p in prices],
        "Low": [p - 0.3 for p in prices], "Close": prices, "Volume": [vol] * n,
    })


def _gap_up_fade_fixture(prev_close=100.0, gap_pct=4.0, fade_close=None, bars_into_session=5):
    """Prior day's session (flat, ending at prev_close) followed by today's
    session: opens at a gap up of `gap_pct`%, drifts, and by the last bar
    has faded to `fade_close` (default: back below the open)."""
    prior = _bars("2026-01-02", "09:15", 10, [prev_close] * 10)
    today_open = prev_close * (1 + gap_pct / 100)
    if fade_close is None:
        fade_close = today_open - 2.0  # comfortably below the open
    today_prices = [today_open + 1.0, today_open + 1.5] + [today_open - 0.5] * (bars_into_session - 3) + [fade_close]
    today_prices = today_prices[:bars_into_session]
    while len(today_prices) < bars_into_session:
        today_prices.append(fade_close)
    today = _bars("2026-01-03", "09:15", bars_into_session, today_prices)
    return pd.concat([prior, today], ignore_index=True)


# ---- gap_up_fade_entry_signal_short ----------------------------------------

def test_entry_fires_when_gap_fails_to_hold():
    df = _gap_up_fade_fixture()
    sig = main.gap_up_fade_entry_signal_short(df)
    assert sig is not None
    assert sig["entry_price"] == df["Close"].iloc[-1]
    assert sig["stop_loss"] > sig["entry_price"]  # short: stop ABOVE entry
    assert sig["atr_at_entry"] > 0


def test_entry_none_when_gap_is_too_small():
    df = _gap_up_fade_fixture(gap_pct=0.5)  # under GAP_UP_FADE_GAP_PCT_THRESHOLD
    assert main.gap_up_fade_entry_signal_short(df) is None


def test_entry_none_when_gap_still_holding_above_open():
    # Close stays comfortably above today's own open - no fade yet.
    df = _gap_up_fade_fixture(fade_close=None)
    today_open = 100.0 * 1.04
    # Rebuild with a fade_close ABOVE the open instead.
    df = _gap_up_fade_fixture(fade_close=today_open + 1.0)
    assert main.gap_up_fade_entry_signal_short(df) is None


def test_entry_none_too_few_bars_into_session():
    df = _gap_up_fade_fixture(bars_into_session=main.GAP_UP_FADE_MIN_BARS_INTO_SESSION - 1)
    assert main.gap_up_fade_entry_signal_short(df) is None


def test_entry_none_without_a_prior_day_to_measure_gap_against():
    df = _bars("2026-01-03", "09:15", 5, [100.0, 101.0, 99.0, 98.0, 97.0])
    assert main.gap_up_fade_entry_signal_short(df) is None


def test_stop_sits_above_todays_own_session_high():
    df = _gap_up_fade_fixture()
    sig = main.gap_up_fade_entry_signal_short(df)
    today_str = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d").iloc[-1]
    today_rows = df[pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d") == today_str]
    assert sig["stop_loss"] == today_rows["High"].max()


# ---- gap_up_fade_exit_reason_short ------------------------------------------

def test_exit_trail_stop_hit_on_a_bounce():
    df = pd.DataFrame({
        "Date": pd.to_datetime(["2026-01-03 09:30", "2026-01-03 09:35", "2026-01-03 09:40"]),
        "Close": [100.0, 80.0, 92.0],
    })
    # running_min ratchets to 80; trail_stop = 80 + 1.5*5 = 87.5 < initial_stop(110)
    reason, running_min = main.gap_up_fade_exit_reason_short(
        df, "2026-01-03 09:30", 110.0, 5.0, 80.0,
    )
    assert reason == "trail_stop_hit"
    assert running_min == 80.0


def test_exit_none_while_price_keeps_falling():
    df = pd.DataFrame({
        "Date": pd.to_datetime(["2026-01-03 09:30", "2026-01-03 09:35"]),
        "Close": [100.0, 95.0],
    })
    reason, running_min = main.gap_up_fade_exit_reason_short(df, "2026-01-03 09:30", 110.0, 5.0, 100.0)
    assert reason is None
    assert running_min == 95.0


def test_exit_max_hold_timeout():
    entry_ts = pd.Timestamp("2026-01-03 09:30")
    now_ts = entry_ts + pd.Timedelta(minutes=main.GAP_UP_FADE_MAX_HOLD_MINUTES + 5)
    df = pd.DataFrame({"Date": [now_ts], "Close": [100.0]})
    reason, _ = main.gap_up_fade_exit_reason_short(df, str(entry_ts), 150.0, 5.0, 100.0)
    assert reason == "max_hold_timeout"


def test_exit_not_yet_at_max_hold():
    entry_ts = pd.Timestamp("2026-01-03 09:30")
    now_ts = entry_ts + pd.Timedelta(minutes=main.GAP_UP_FADE_MAX_HOLD_MINUTES - 10)
    df = pd.DataFrame({"Date": [now_ts], "Close": [100.0]})
    reason, _ = main.gap_up_fade_exit_reason_short(df, str(entry_ts), 150.0, 5.0, 100.0)
    assert reason is None
