"""Tests for the Minervini Trend Template + VCP short mirror (2026-09-29,
explicit user instruction "Prep short mirror for others too" per
CLAUDE.md's 2026-09-28 standing thumb rule: every strategy gets checked for
both directions). Mirrors _minervini_trend_template_ok/
_find_minervini_vcp_pivot/minervini_vcp_entry_signal/
minervini_vcp_exit_reason direction only - every weight/lookback/threshold
constant is reused verbatim from the long side. Not wired into main.py's
live scan/scheduler/order path - see strategy_registry.py's "registering
!= trading" principle."""
import numpy as np
import pandas as pd

import main


def _minervini_vcp_short_fixture():
    """220 bars of a downtrend (150->50, qualifies the Stage-4 mirror of
    the Trend Template) followed by an 80-bar tail tracing a real zigzag
    through two contracting RELIEF-RALLY legs (leg1 bounce ~60%, leg2
    bounce ~10.9%, satisfying both the <=15% final-leg cap and the >=2x
    tightening ratio) and ending on a breakdown bar below the base's pivot
    low with a volume surge. Structurally the mirror image of
    test_minervini_vcp.py's own _minervini_vcp_fixture."""
    close1 = np.linspace(150.0, 50.0, 220)
    verts_x = [220, 240, 252, 264, 276, 298, 299]
    verts_y = [50.0, 20.0, 32.0, 23.0, 25.5, 24.0, 15.0]
    tail_idx = np.arange(220, 300)
    mid_tail = np.interp(tail_idx, verts_x, verts_y)
    mid = np.concatenate([close1, mid_tail])
    high = mid + 0.3
    low = mid - 0.3
    close = mid.copy()
    volume = np.full(300, 1000.0)
    volume[-1] = 5000.0
    dates = pd.date_range("2020-01-01", periods=300, freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({"High": high, "Low": low, "Close": close, "Volume": volume, "Date": dates})


# ---- _minervini_trend_template_ok_short --------------------------------------

def test_trend_template_short_true_for_a_qualifying_downtrend():
    df = _minervini_vcp_short_fixture()
    assert main._minervini_trend_template_ok_short(df) is True


def test_trend_template_short_none_when_not_enough_history():
    df = _minervini_vcp_short_fixture().iloc[-100:].reset_index(drop=True)
    assert main._minervini_trend_template_ok_short(df) is None


def test_trend_template_short_false_for_an_uptrend():
    close = np.linspace(50.0, 150.0, 280)
    df = pd.DataFrame({"High": close + 0.5, "Low": close - 0.5, "Close": close})
    assert main._minervini_trend_template_ok_short(df) is False


def test_trend_template_short_respects_rs_percentile_gate():
    df = _minervini_vcp_short_fixture()
    assert main._minervini_trend_template_ok_short(df, rs_percentile=10.0) is True
    assert main._minervini_trend_template_ok_short(df, rs_percentile=90.0) is False


# ---- _find_minervini_vcp_pivot_short ------------------------------------------

def test_find_vcp_pivot_short_detects_the_tightening_relief_rally_base():
    df = _minervini_vcp_short_fixture()
    pivot = main._find_minervini_vcp_pivot_short(df)
    assert pivot is not None
    assert pivot["final_leg_high"] > pivot["pivot_low"]


def test_find_vcp_pivot_short_none_on_insufficient_history():
    df = _minervini_vcp_short_fixture().iloc[-10:].reset_index(drop=True)
    assert main._find_minervini_vcp_pivot_short(df) is None


# ---- minervini_vcp_entry_signal_short -----------------------------------------

def test_entry_signal_short_fires_on_a_clean_breakdown():
    df = _minervini_vcp_short_fixture()
    sig = main.minervini_vcp_entry_signal_short(df)
    assert sig is not None
    assert sig["entry_price"] == df["Close"].iloc[-1]
    assert sig["stop_loss"] > sig["entry_price"]
    assert sig["atr_at_entry"] > 0


def test_entry_signal_short_none_when_trend_template_fails(monkeypatch):
    df = _minervini_vcp_short_fixture()
    monkeypatch.setattr(main, "_minervini_trend_template_ok_short", lambda *a, **k: False)
    assert main.minervini_vcp_entry_signal_short(df) is None


def test_entry_signal_short_none_without_a_breakdown():
    df = _minervini_vcp_short_fixture()
    df = df.copy()
    df.loc[df.index[-1], "Close"] = 30.0  # still above the pivot low (~22.7)
    assert main.minervini_vcp_entry_signal_short(df) is None


def test_entry_signal_short_none_without_a_volume_surge():
    df = _minervini_vcp_short_fixture()
    df = df.copy()
    df.loc[df.index[-1], "Volume"] = 1000.0  # no surge over the trailing average
    assert main.minervini_vcp_entry_signal_short(df) is None


# ---- minervini_vcp_exit_reason_short ------------------------------------------

def test_exit_short_none_while_holding():
    df = pd.DataFrame({
        "Date": ["2026-01-02", "2026-01-05", "2026-01-06"],
        "Close": [100.0, 98.0, 96.0],
    })
    reason, running_min = main.minervini_vcp_exit_reason_short(df, "2026-01-02", 110.0, 5.0, 100.0)
    assert reason is None
    assert running_min == 96.0


def test_exit_short_trail_stop_hit():
    df = pd.DataFrame({
        "Date": ["2026-01-02", "2026-01-05", "2026-01-06"],
        "Close": [100.0, 70.0, 81.0],
    })
    # running_min ratchets to 70 after bar 2; trail_stop = 70 + 2*5 = 80 < initial_stop(110)
    reason, running_min = main.minervini_vcp_exit_reason_short(df, "2026-01-02", 110.0, 5.0, 70.0)
    assert reason == "trail_stop_hit"
    assert running_min == 70.0


def test_exit_short_max_hold_timeout():
    dates = pd.bdate_range("2026-01-02", periods=main.MINERVINI_MAX_HOLD_DAYS + 2).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"Date": dates, "Close": [100.0] * len(dates)})
    reason, _ = main.minervini_vcp_exit_reason_short(df, dates[0], 150.0, 5.0, 100.0)
    assert reason == "max_hold_timeout"


def test_exit_short_not_yet_at_max_hold():
    dates = pd.bdate_range("2026-01-02", periods=main.MINERVINI_MAX_HOLD_DAYS - 5).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"Date": dates, "Close": [100.0] * len(dates)})
    reason, _ = main.minervini_vcp_exit_reason_short(df, dates[0], 150.0, 5.0, 100.0)
    assert reason is None
