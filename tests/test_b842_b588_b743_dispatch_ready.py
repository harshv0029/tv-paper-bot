"""B-842 / B-588 / B-743 dispatch readiness: workflows take interval+period, scripts honour them,
yfinance caps are enforced, 4h goes through the 1h resample, outputs carry PFgross/win%/hold/exits."""
import os
import sys

import pandas as pd
import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import research_interval as ri  # noqa: E402

WF = {
    "B-842": ("swing-min-rr-research.yml", "swing_min_rr_research.py"),
    "B-588": ("elder-dirsys-di13-research.yml", "elder_dirsys_di13_research.py"),
    "B-743": ("portfolio-overlay-research.yml", "portfolio_overlay_research.py"),
}


def _wf(name):
    with open(os.path.join(ROOT, ".github", "workflows", name)) as f:
        d = yaml.safe_load(f)
    return d, open(os.path.join(ROOT, ".github", "workflows", name)).read()


def _src(name):
    return open(os.path.join(ROOT, "scripts", name)).read()


@pytest.mark.parametrize("row", list(WF))
def test_workflow_has_interval_and_period_inputs_and_passes_them(row):
    wf, text = WF[row]
    d, raw = _wf(wf)
    on = d.get("on", d.get(True))
    inputs = on["workflow_dispatch"]["inputs"]
    assert "interval" in inputs and "period" in inputs
    assert "--interval" in raw and "--period" in raw
    for iv in ("4h", "1h", "15m", "5m"):
        assert iv in inputs["interval"]["description"], (row, iv)


@pytest.mark.parametrize("row", ["B-842", "B-743"])
def test_scripts_use_capping_fetch_and_full_interval_choices(row):
    s = _src(WF[row][1])
    assert "ri.fetch_interval(" in s
    assert "choices=ri.INTERVALS" in s
    assert "m.fetch_ohlc(s, args.period" not in s


def test_b588_script_caps_and_resamples():
    s = _src("elder_dirsys_di13_research.py")
    for k in ('"1m": "7d"', '"5m": "60d"', '"15m": "60d"', '"1h": "730d"', '"4h": "1h"'):
        assert k in s


def test_default_periods_respect_yfinance_caps():
    assert ri.DEFAULT_PERIOD == {"1d": "5y", "4h": "730d", "1h": "730d", "15m": "60d", "5m": "60d", "1m": "7d"}
    assert ri.cap_period("1m", "60d") == "7d"
    assert ri.cap_period("5m", "5y") == "60d"
    assert ri.cap_period("15m", "730d") == "60d"
    assert ri.cap_period("1h", "5y") == "730d"
    assert ri.cap_period("4h", "") == "730d"
    assert ri.cap_period("1h", "365d") == "365d"
    assert ri.cap_period("1d", "5y") == "5y"
    with pytest.raises(ValueError):
        ri.cap_period("3h", "5d")


def test_fetch_interval_4h_uses_1h_and_resamples():
    calls = []
    idx = pd.date_range("2026-01-05 09:15", periods=7, freq="60min")
    df = pd.DataFrame({"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10}, index=idx)

    class M:
        @staticmethod
        def fetch_ohlc(sym, period, interval):
            calls.append((period, interval))
            return df

    out = ri.fetch_interval(M, "X.NS", "5y", "4h")
    assert calls == [("730d", "1h")]
    assert len(out) == 2 and out["Volume"].iloc[0] == 40
    ri.fetch_interval(M, "X.NS", "5y", "1m")
    assert calls[-1] == ("7d", "1m")


@pytest.mark.parametrize("script,needles", [
    ("swing_min_rr_research.py", ("pf_gross", "win_pct", "avg_hold_bars", "exit_reasons")),
    ("portfolio_overlay_research.py", ("pf_gross", "win_pct", "avg_hold_bars")),
    ("elder_dirsys_di13_research.py", ("win_pct", "avg_hold_bars")),
])
def test_outputs_include_metrics(script, needles):
    s = _src(script)
    for n in needles:
        assert n in s, (script, n)


def test_backlog_rows_have_dispatch_commands():
    b = open(os.path.join(ROOT, "docs", "ACTIONABLES_BACKLOG.md")).read()
    for row in WF:
        assert row in b
    assert "DISPATCH-READY 2026-10-12" in b
    assert "gh workflow run swing-min-rr-research.yml -f interval=4h" in b
    assert "gh workflow run elder-dirsys-di13-research.yml -f interval=1h" in b
    assert "gh workflow run portfolio-overlay-research.yml -f interval=1h" in b
