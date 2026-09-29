"""Tests for the Minervini Trend Template + VCP swing strategy
(2026-09-29, explicit user instruction: "Implement Minervini VCP
strategy"). Every threshold mirrors the validated research workflow
(.github/workflows/swing-minervini-trend-template-vcp-research.yml,
tt_vcp variant, PFnet 0.90 on n=325 full-universe trades) with zero
retuning. These tests cover the building blocks
(_minervini_trend_template_ok, _compute_minervini_rs_percentiles,
_find_minervini_vcp_pivot) plus the entry/exit signal functions, using
hand-engineered fixtures the same way test_trend_short_selling.py and
test_short_selling.py do for their own strategies. Not wired into
main.py's live scan/scheduler/order path - see strategy_registry.py's
"registering != trading" principle."""
import numpy as np
import pandas as pd
import pytest

import main


# ---- shared fixture: a qualifying uptrend + a genuine tightening VCP base ---

def _minervini_vcp_fixture():
    """220 bars of a strong uptrend (50->150, qualifies the Trend Template)
    followed by an 80-bar tail that traces a real zigzag through two
    contraction legs (leg1 depth ~22.5%, leg2 depth ~5.3%, satisfying both
    the <=15% final-leg cap and the >=2x tightening ratio) and ends on a
    breakout bar above the base's pivot high with a volume surge. High/Low
    are a constant +/-0.3 offset around one zigzag path, so a genuine local
    max/min in the path is automatically a genuine local max/min in the
    High/Low columns - this is what makes the fractal swing-point detector
    find exactly the intended two legs instead of spurious artifacts from
    an unrelated flat baseline (the first attempt at this fixture used a
    flat baseline + isolated spikes and failed: a spike set to sit ABOVE a
    flat "low" baseline is not a local minimum at all, so it was silently
    never detected as a swing low)."""
    close1 = np.linspace(50.0, 150.0, 220)
    verts_x = [220, 240, 252, 264, 276, 298, 299]
    verts_y = [150.0, 180.0, 140.0, 175.0, 166.25, 170.0, 182.0]
    tail_idx = np.arange(220, 300)
    mid_tail = np.interp(tail_idx, verts_x, verts_y)
    mid = np.concatenate([close1, mid_tail])
    high = mid + 0.3
    low = mid - 0.3
    close = mid.copy()
    volume = np.full(300, 1000.0)
    volume[-1] = 5000.0
    return pd.DataFrame({"High": high, "Low": low, "Close": close, "Volume": volume})


# ---- _minervini_trend_template_ok -------------------------------------------

def test_trend_template_ok_true_for_a_qualifying_uptrend():
    df = _minervini_vcp_fixture()
    assert main._minervini_trend_template_ok(df) is True


def test_trend_template_ok_none_when_not_enough_history():
    df = _minervini_vcp_fixture().iloc[-100:].reset_index(drop=True)
    assert main._minervini_trend_template_ok(df) is None


def test_trend_template_ok_false_for_a_downtrend():
    close = np.linspace(150.0, 50.0, 280)
    df = pd.DataFrame({"High": close + 0.5, "Low": close - 0.5, "Close": close})
    assert main._minervini_trend_template_ok(df) is False


def test_trend_template_ok_respects_rs_percentile_gate():
    df = _minervini_vcp_fixture()
    assert main._minervini_trend_template_ok(df, rs_percentile=90.0) is True
    assert main._minervini_trend_template_ok(df, rs_percentile=10.0) is False


# ---- _compute_minervini_rs_percentiles --------------------------------------

def test_rs_percentiles_ranks_strongest_momentum_highest():
    closes_by_symbol = {
        "STRONG.NS": np.linspace(100.0, 150.0, 130),
        "WEAK.NS": np.linspace(100.0, 105.0, 130),
        "NEGATIVE.NS": np.linspace(100.0, 90.0, 130),
    }
    pct = main._compute_minervini_rs_percentiles(closes_by_symbol)
    assert pct["STRONG.NS"] > pct["WEAK.NS"] > pct["NEGATIVE.NS"]
    assert pct["STRONG.NS"] == 100.0


def test_rs_percentiles_omits_symbols_with_insufficient_history():
    closes_by_symbol = {
        "OK.NS": np.linspace(100.0, 150.0, 130),
        "TOO_SHORT.NS": np.linspace(100.0, 200.0, 50),
    }
    pct = main._compute_minervini_rs_percentiles(closes_by_symbol)
    assert "OK.NS" in pct
    assert "TOO_SHORT.NS" not in pct


# ---- _find_minervini_vcp_pivot -----------------------------------------------

def test_find_vcp_pivot_detects_a_genuine_tightening_base():
    df = _minervini_vcp_fixture()
    pivot = main._find_minervini_vcp_pivot(df)
    assert pivot is not None
    assert pivot["pivot_high"] == pytest.approx(175.3)
    assert pivot["final_leg_low"] == pytest.approx(165.95)


def test_find_vcp_pivot_none_when_final_leg_too_deep():
    # Same shape, but widen the second pullback well past the 15% cap.
    close1 = np.linspace(50.0, 150.0, 220)
    verts_x = [220, 240, 252, 264, 276, 298, 299]
    verts_y = [150.0, 180.0, 140.0, 175.0, 120.0, 150.0, 182.0]  # leg2 depth ~31%
    tail_idx = np.arange(220, 300)
    mid_tail = np.interp(tail_idx, verts_x, verts_y)
    mid = np.concatenate([close1, mid_tail])
    df = pd.DataFrame({"High": mid + 0.3, "Low": mid - 0.3, "Close": mid,
                        "Volume": np.full(300, 1000.0)})
    assert main._find_minervini_vcp_pivot(df) is None


def test_find_vcp_pivot_none_on_too_short_a_history():
    df = _minervini_vcp_fixture().iloc[:25].reset_index(drop=True)
    assert main._find_minervini_vcp_pivot(df) is None


# ---- minervini_vcp_entry_signal ----------------------------------------------

def test_entry_signal_fires_on_a_clean_breakout_with_volume_surge():
    df = _minervini_vcp_fixture()
    sig = main.minervini_vcp_entry_signal(df)
    assert sig is not None
    assert sig["entry_price"] == pytest.approx(182.0)
    assert sig["stop_loss"] == pytest.approx(165.95)
    assert sig["stop_loss"] < sig["entry_price"]
    assert sig["atr_at_entry"] > 0


def test_entry_signal_none_without_a_close_above_pivot():
    df = _minervini_vcp_fixture()
    df.loc[299, ["Close", "High", "Low"]] = [170.0, 170.3, 169.7]
    assert main.minervini_vcp_entry_signal(df) is None


def test_entry_signal_none_without_a_volume_surge():
    df = _minervini_vcp_fixture()
    df.loc[299, "Volume"] = 1000.0
    assert main.minervini_vcp_entry_signal(df) is None


def test_entry_signal_none_when_trend_template_fails():
    df = _minervini_vcp_fixture()
    df.loc[299, "Close"] = 90.0
    assert main.minervini_vcp_entry_signal(df) is None


# ---- minervini_vcp_exit_reason ------------------------------------------------

def test_exit_reason_fires_on_the_chandelier_trail_stop():
    close = np.concatenate([np.linspace(100.0, 130.0, 20), np.linspace(130.0, 110.0, 10)])
    dates = pd.date_range("2026-01-01", periods=len(close)).astype(str).to_numpy()
    entry_day = dates[19]
    running_max = close[19]
    reason = None
    for i in range(20, len(close)):
        sub = pd.DataFrame({"Close": close[: i + 1], "Date": dates[: i + 1]})
        reason, running_max = main.minervini_vcp_exit_reason(sub, entry_day, 90.0, 2.0, running_max)
        if reason:
            break
    assert reason == "trail_stop_hit"


def test_exit_reason_fires_on_max_hold_timeout_for_a_flat_price():
    close = np.full(80, 100.0)
    dates = pd.date_range("2026-01-01", periods=len(close)).astype(str).to_numpy()
    entry_day = dates[0]
    running_max = 100.0
    reason = None
    for i in range(len(close)):
        sub = pd.DataFrame({"Close": close[: i + 1], "Date": dates[: i + 1]})
        reason, running_max = main.minervini_vcp_exit_reason(sub, entry_day, 90.0, 1.0, running_max)
        if reason:
            break
    assert reason == "max_hold_timeout"


def test_exit_reason_none_and_running_max_ratchets_up_while_position_is_healthy():
    # Evaluates ONLY the last row (today), same convention as
    # gap_and_go_exit_reason - the caller carries running_max_close
    # forward call-by-call, so a single call only ever compares today's
    # close against the running max passed in, never scans the whole df.
    close = np.array([100.0, 101.0, 103.0])
    dates = pd.date_range("2026-01-01", periods=3).astype(str).to_numpy()
    df = pd.DataFrame({"Close": close, "Date": dates})
    reason, running_max = main.minervini_vcp_exit_reason(df, dates[0], 80.0, 5.0, 100.0)
    assert reason is None
    assert running_max == 103.0

