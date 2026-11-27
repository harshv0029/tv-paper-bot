"""B-1746: per-day index trigger audit (research only, read-only, no orders).

For ^NSEI and ^BSESN (plus ^NSEBANK for context) on 5m, 15m and 1h candles, counts, for every NSE session day in
the window, how often each trigger would have fired, LONG and SHORT (reciprocal-price mirror):
  - live_orb_trend: the live WATCHLIST ORB rule (close > OR high x (1 + ENTRY_BREAKOUT_MARGIN_PCT%), fast MA > slow MA,
    trend confidence >= the live floor) WITH the live volume gate (main._volume_confirms), exactly as main.py.
  - live_orb_trend_novol: the same rule with the volume gate removed (index bars carry zero volume on Yahoo).
  - orb / atr_range_break / ema_cross / rsi_thrust: the 4 non-volume triggers of index_option_trigger_research.py.
Output: docs/index_fire_audit.json and docs/index_fire_audit.md (per-day table). Window: env FROM/TO (IST dates).
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import index_option_trigger_research as R  # noqa: E402

SYMBOLS = {"^NSEI": (30, 5, 50), "^BSESN": (30, 20, 50), "^NSEBANK": (5, 9, 50)}  # orb_minutes, sma_fast, sma_slow
TFS = ("5m", "15m", "1h")
TF_MIN = {"5m": 5, "15m": 15, "1h": 60}
MIN_CONF_PCT = float(os.environ.get("MIN_CONF_PCT", "0"))


def live_orb(main, df, orb_minutes, fast, slow, tf, use_volume):
    """Bool array: the live orb_breakout entry rule evaluated bar by bar (first fire per day kept)."""
    day = df["Date"].astype(str).str[:10].to_numpy()
    hi, cl = df["High"].to_numpy(float), df["Close"].to_numpy(float)
    vol = df["Volume"].to_numpy(float) if "Volume" in df.columns else np.zeros(len(df))
    or_bars = max(1, orb_minutes // TF_MIN[tf])
    sig = np.zeros(len(df), bool)
    start, fired = 0, False
    for i in range(len(df)):
        if i == 0 or day[i] != day[i - 1]:
            start, fired = i, False
        pos = i - start
        if pos < or_bars or fired or i < slow:
            continue
        orh = hi[start:start + or_bars].max()
        closes = cl[: i + 1]
        f, s = main._moving_average(closes, fast, "sma"), main._moving_average(closes, slow, "sma")
        if not (cl[i] > orh * (1 + main.ENTRY_BREAKOUT_MARGIN_PCT / 100) and f > s):
            continue
        if main._trend_confidence(closes, fast, slow, "sma") < MIN_CONF_PCT / 100:
            continue
        if use_volume and not main._volume_confirms(vol[: i + 1])[0]:
            continue
        sig[i], fired = True, True
    return sig


def per_day(df, sig, lo, hi_):
    d = pd.Series(sig, index=df["Date"].astype(str).str[:10])
    d = d[(d.index >= lo) & (d.index <= hi_)]
    return {k: int(v) for k, v in d.groupby(level=0).sum().items()}


def run(main, lo, hi_, synth=False):
    out = {"from": lo, "to": hi_, "cells": {}}
    for sym, (orb_m, fast, slow) in SYMBOLS.items():
        for tf in TFS:
            df = R.synthetic(sym) if synth else R.fetch(sym, tf)
            if df is None or not len(df):
                out["cells"][f"{sym}|{tf}"] = {"error": "no data"}
                continue
            cell = {"bars": len(df), "vol_nonzero_bars": int((df.get("Volume", pd.Series([0])) > 0).sum())}
            for direction, frame in (("long", df), ("short", R.flip(df))):
                trig = {
                    "live_orb_trend": live_orb(main, frame, orb_m, fast, slow, tf, True),
                    "live_orb_trend_novol": live_orb(main, frame, orb_m, fast, slow, tf, False),
                }
                for name, fn in R.NV_TRIGGERS.items():
                    trig[name] = fn(frame)
                for name, s in trig.items():
                    cell[f"{name}|{direction}"] = per_day(frame, s, lo, hi_)
            out["cells"][f"{sym}|{tf}"] = cell
    return out


def to_md(out):
    lines = [f"# Index trigger fire audit (B-1746), {out['from']} to {out['to']} IST", "",
             "Fires per trigger, summed over the window (days with >=1 fire in brackets). Research only.", "",
             "| Symbol | TF | Trigger | Dir | Fires | Days fired |", "|---|---|---|---|---|---|"]
    for key, cell in out["cells"].items():
        sym, tf = key.split("|")
        if "error" in cell:
            lines.append(f"| {sym} | {tf} | - | - | {cell['error']} | |")
            continue
        for k, days in cell.items():
            if "|" not in k:
                continue
            trig, d = k.split("|")
            lines.append(f"| {sym} | {tf} | {trig} | {d} | {sum(days.values())} | {sum(1 for v in days.values() if v)} |")
    return "\n".join(lines) + "\n"


def main_cli():
    import main as M
    lo, hi_ = os.environ.get("FROM", "2026-10-01"), os.environ.get("TO", "2026-11-26")
    out = run(M, lo, hi_, synth=os.environ.get("SYNTH") == "1")
    od = os.environ.get("OUT_DIR", "docs")
    os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, "index_fire_audit.json"), "w"), indent=1, sort_keys=True)
    open(os.path.join(od, "index_fire_audit.md"), "w").write(to_md(out))
    print(to_md(out))


if __name__ == "__main__":
    main_cli()
