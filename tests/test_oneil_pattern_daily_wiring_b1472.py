"""B-1472 b: O'Neil cup-family 1d cells (main.py replay run 41958449455) in the live swing scan: every replay row is
registered under its own srcmain tag, the three wired cells map 1:1 to their rows (pooled PFnet > 1, n >= 30, hold
<= 30 bars), the entry calls the real pattern function with today's live price as bar t+1's open, stop < entry, no
live price -> no signal, and the exit uses each cell's own max hold."""
import json
import os

import numpy as np
import pandas as pd
import pytest

import main
import strategy_registry as sr
import strategy_registry_b1472oneil as b

CELLS = {main.ONEIL_CUP_HANDLE_1D_TAG: (1.541, 1396, 60, 2.0, 0.10, "qual1"),
         main.ONEIL_CUP_NOHANDLE_1D_TAG: (1.269, 1009, 40, 3.0, 0.05, "none"),
         main.ONEIL_SAUCER_1D_TAG: (1.134, 131, 40, 2.0, 0.10, "none")}
END = "2026-10-30"


def _df(n=320):
    dates = pd.bdate_range(end=END, periods=n)
    c = 100 + np.sin(np.arange(n) / 9.0) * 5
    df = pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": np.full(n, 1e5)}, index=dates)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in dates]
    return df


def test_every_replay_row_registered_own_tag():
    p = os.path.join(os.path.dirname(main.__file__), "docs", "backtest_data", "oneil_pattern_replay_41958449455.json")
    rows = json.load(open(p))["rows"]
    names = {s.name for s in sr.REGISTRY}
    assert len(rows) == 1296 and all(r["tag"] in names and r["tag"] == b.srcmain_tag(r["research_tag"]) for r in rows)
    assert b.srcmain_tag("x__y__long__1d__atr3_chase5_h40_rsnone_trl1__v2") == "x__y__long__1d__atr3_chase5_h40_rsnone_srcmain_trl1__v2"


def test_wired_cells_mapping_metrics_rules():
    names = {s.name: s for s in sr.REGISTRY}
    for tag, (pf, n, hold, mult, chase, rsf) in CELLS.items():
        m = names[tag].metrics
        assert m.pfnet == pytest.approx(pf) and m.n_trades == n and m.avg_held_bars <= 30 and m.pfnet > 1.0
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[tag] == tag and main._is_strategy_wired(tag)
        assert tag not in main.REPLAY_OWED_TAGS
        assert main.ONEIL_DAILY_CELLS[tag] == ((tag.split("__")[0], "breakout", chase, rsf), mult, hold, False)
        assert main._strategy_hold_spec(tag) == (hold, "1d")
        assert f"{mult:g}xATR14" in main._SWING_SL_RULES[tag]
        assert "rs80" not in tag


@pytest.mark.parametrize("tag", list(CELLS))
def test_entry_calls_pattern_fn_with_live_open(monkeypatch, tag):
    df = _df()
    seen = {}

    def fake(fam, d, tf, o, h, l, c, v, rs, chase, rsf):
        seen.update(fam=fam, n=len(o), o_last=o[-1], chase=chase, rsf=rsf, d=d, tf=tf)
        out = np.zeros(len(o), bool)
        out[-2] = True
        return out

    monkeypatch.setattr(main, "oneil_pattern_signal_array", fake)
    today = main._add_nse_trading_days(END, 1)
    assert main.oneil_daily_entry_signal(df, tag, today=today) is None  # no live price -> fail closed
    sig = main.oneil_daily_entry_signal(df, tag, live_px=103.0, today=today)
    _, mult, _, _ = main.ONEIL_DAILY_CELLS[tag][0], *main.ONEIL_DAILY_CELLS[tag][1:]
    atr = main.oneil_atr14(df["High"].to_numpy(float), df["Low"].to_numpy(float), df["Close"].to_numpy(float))[-1]
    assert seen == dict(fam=tag.split("__")[0], n=len(df) + 1, o_last=103.0, chase=CELLS[tag][4], rsf=CELLS[tag][5],
                        d="long", tf="1d")
    assert sig["entry_price"] == 103.0 and sig["stop_loss"] == pytest.approx(103.0 - main.ONEIL_DAILY_CELLS[tag][1] * atr)
    assert 0 < sig["stop_loss"] < sig["entry_price"] and sig["signal_day"] == END
    assert main.oneil_daily_entry_signal(df, tag, live_px=103.0, today=main._add_nse_trading_days(END, 2)) is None


def test_no_fire_no_signal(monkeypatch):
    monkeypatch.setattr(main, "oneil_pattern_signal_array", lambda *a, **k: np.zeros(len(a[4]), bool))
    tag = main.ONEIL_SAUCER_1D_TAG
    assert main.oneil_daily_entry_signal(_df(), tag, live_px=103.0, today=main._add_nse_trading_days(END, 1)) is None


def test_signal_ignores_appended_bar_except_open():
    """The appended live bar only feeds the chase test: h/l/c/v of bar t+1 never change the signal at t."""
    rng = np.random.default_rng(7)
    n = 520
    c = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, n)))
    o, h, l, v = c * (1 + rng.normal(0, 0.004, n)), c * 1.012, c * 0.988, rng.uniform(1e5, 3e5, n)
    for fam, ch, rf in [("oneil_cup_handle", 0.10, "qual1"), ("oneil_cup_nohandle", 0.05, "none")]:
        full = main.oneil_pattern_signal_array(fam, "long", "1d", o, h, l, c, v, None, ch, rf)
        for t in range(300, n - 1, 7):
            a = main.oneil_pattern_signal_array(fam, "long", "1d", o[:t + 2], np.append(h[:t + 1], 1e9),
                                                np.append(l[:t + 1], -1.0), np.append(c[:t + 1], 1.0),
                                                np.append(v[:t + 1], 0.0), None, ch, rf)
            assert bool(a[-2]) == bool(full[t])
