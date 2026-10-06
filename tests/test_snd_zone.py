"""Unit tests for main.snd_zone_scan / snd_zone_entry_signal (backlog B-33)."""
import numpy as np
import pandas as pd
import pytest

import main

P = {"atr_period": 2, "explosive_body_atr": 1.0, "base_body_atr": 0.5}


def _df(rows):
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"]).assign(Volume=1000.0)


PRE = [(100, 101, 99, 100.5), (100.5, 101, 100, 100.8)]
BASE = (100.0, 100.9, 99.0, 100.1)            # small body, wicks >> body -> zone [99, 100.9]
EXPLOSIVE = (100.2, 104.8, 100.1, 104.5)      # big up candle
AWAY = [(104.5, 105.5, 104.0, 105.0), (105.0, 106.0, 104.5, 105.5), (105.5, 106.0, 105.0, 105.2)]
RETEST = (105.0, 105.1, 100.5, 101.5)         # drops into the zone, closes back above it


def _demand_df(extra=None):
    return _df(PRE + [BASE, EXPLOSIVE] + AWAY + [RETEST] + (extra or []))


def test_demand_retest_long_limit_at_proximal_edge():
    r = main.snd_zone_scan(_demand_df(), "long", P)
    assert list(np.flatnonzero(r["signal"])) == [7]
    e, s, t = r["entry_price"][7], r["stop_loss"][7], r["target"][7]
    assert e == pytest.approx(100.9)          # zone top (proximal edge)
    assert s < 99.0 < e < t                   # stop beyond the distal edge
    assert (e - s) * 2.0 == pytest.approx(t - e)


def test_close_confirm_enters_at_close():
    r = main.snd_zone_scan(_demand_df(), "long", {**P, "entry": "close_confirm"})
    assert list(np.flatnonzero(r["signal"])) == [7]
    assert r["entry_price"][7] == pytest.approx(101.5)


def test_short_supply_is_exact_price_mirror():
    K = 1000.0
    d = _demand_df()
    mirror = pd.DataFrame({"Open": K - d["Open"], "High": K - d["Low"], "Low": K - d["High"],
                           "Close": K - d["Close"], "Volume": 1000.0})
    rs = main.snd_zone_scan(mirror, "short", P)
    assert list(np.flatnonzero(rs["signal"])) == [7]
    assert rs["target"][7] < rs["entry_price"][7] < rs["stop_loss"][7]
    assert rs["entry_price"][7] == pytest.approx(K - 100.9)


def test_retest_before_confirmation_is_ignored():
    early = _df(PRE + [BASE, EXPLOSIVE, AWAY[0], RETEST])  # only 1 bar away < confirm_bars=3
    assert not main.snd_zone_scan(early, "long", P)["signal"].any()


def test_zone_invalidated_by_close_below_distal_edge():
    crash = (105.0, 105.1, 97.0, 98.0)  # closes below zone low 99
    assert not main.snd_zone_scan(_df(PRE + [BASE, EXPLOSIVE] + AWAY + [crash]), "long", P)["signal"].any()


def test_only_first_retest_trades_when_max_retests_is_one():
    leave = [(101.5, 105.0, 101.4, 104.5), (104.5, 105.0, 104.0, 104.8)]
    second = (104.8, 104.9, 100.4, 101.2)
    r = main.snd_zone_scan(_demand_df(leave + [second]), "long", P)
    assert list(np.flatnonzero(r["signal"])) == [7]
    r2 = main.snd_zone_scan(_demand_df(leave + [second]), "long", {**P, "max_retests": 2})
    assert list(np.flatnonzero(r2["signal"])) == [7, 10]


def test_base_must_have_wicks_larger_than_body():
    fat_body = (100.0, 100.6, 99.9, 100.55)   # body .55 > wicks -> not a base candle
    assert not main.snd_zone_scan(_df(PRE + [fat_body, EXPLOSIVE] + AWAY + [RETEST]), "long", {**P, "base_body_atr": 5.0})["signal"].any()


def test_sessions_drop_zone_across_session_break():
    d = _demand_df()
    sess = np.array([0] * 7 + [1])  # retest bar (idx 7) falls in a later session than the zone
    assert not main.snd_zone_scan(d, "long", P, sessions=sess)["signal"].any()
    assert main.snd_zone_scan(d, "long", P, sessions=np.zeros(8, dtype=int))["signal"].any()


def test_entry_signal_wrapper_and_errors():
    assert main.snd_zone_entry_signal(_demand_df(), "long", P)["entry_price"] == pytest.approx(100.9)
    assert main.snd_zone_entry_signal(_demand_df().iloc[:-1], "long", P) is None
    with pytest.raises(ValueError):
        main.snd_zone_scan(_demand_df(), "up", P)
    with pytest.raises(ValueError):
        main.snd_zone_scan(_demand_df(), "long", {**P, "entry": "market"})


def test_no_signal_on_flat_data():
    flat = _df([(100, 100.5, 99.5, 100)] * 40)
    for d in ("long", "short"):
        assert not main.snd_zone_scan(flat, d, P)["signal"].any()
