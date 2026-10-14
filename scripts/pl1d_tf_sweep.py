"""pl1d (STARC fade + gap runaway) candle-size x ATR x hold sweep, LONG and SHORT, 1h and 4h (backlog B-1150).

Research replay, wires nothing. SIGNAL and EXIT are the REAL main.py functions:
  main.pl1d_long_entry_signal / main.pl1d_short_entry_signal   (rule + entry price + atr_at_entry; the tag only selects the rule)
  main.pl1d_exit_reason / main.pl1d_short_exit_reason          (gap-aware stop, else close of the hold-th bar)
The cell's ATR multiple and hold are swept here: stop = entry -/+ atr_mult * the real signal's atr_at_entry (the same arithmetic the
real function uses with its tag's k), hold = bars. Why entry_day is "0000-00-00": the real exit fns find the first bar whose DATE is
after entry_day, which is right at 1d but would skip the rest of the entry day at 1h/4h; so the driver passes the frame that STARTS at
the bar after entry and an entry_day older than every bar. Entry = close of the signal bar (live convention), exits from the next
bar, strict FIFO per symbol per cell, cost = main.ROUND_TRIP_COST_PCT/100 (0.8%), SL on every trade (no atrnone), universe =
main._load_nse_universe_from_file() (full, NOT main.NSE_FULL_UNIVERSE). Candle sizes: 1h (730d from yfinance), 4h (1h resampled to NSE
session bars by scripts/resample_4h.py, ~2 bars/day, avg 3.5h). Bar-count meaning: the rule's SMA6/ATR15/SMA50 windows and the hold are in
BARS of the chosen size (at 4h a hold of 10 = ~5 sessions; at 1h a hold of 20 = ~3 sessions): stated in every output. 1d baselines
are the existing pl1d replays. Tags: <family>__<variant>__<dir>__<tf>__atr<k>_h<hold>__v1, each cell its own.

  run    env: TF 1h|4h, SHARD, NSHARDS, SYMBOL_LIMIT, ATRS="2.5,4.0", HOLDS (default per tf), SYNTHETIC=1 (smoke, NOT a result)
         -> out/pl1d_tf_<tf>_s<shard>.json (raw sums, exactly mergeable)
  merge  python3 scripts/pl1d_tf_sweep.py merge DIR [OUT.json] -> rows[] (schema main._replay_verified_tags reads)
"""
import glob
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brk20_replay as br  # noqa: E402

try:  # B-1110 shared glitch-bar cleaning when present
    import bar_hygiene as bh  # noqa: E402
except ImportError:  # pragma: no cover
    bh = None

MIN_BARS = 60
FAMILY = {"starc_fade": "starc__fade_full", "gap_runaway": "gap__runaway"}
RULES = ("starc_fade", "gap_runaway")
DEFAULT_ATRS = (2.5, 4.0)
DEFAULT_HOLDS = {"1h": (20, 40, 80), "4h": (10, 20, 40)}
HOURS_PER_BAR = {"1h": 1.0, "4h": 3.5}
BEFORE_ALL = "0000-00-00"


def tag_for(rule, direction, tf, atr, hold):
    return f"{FAMILY[rule]}__{direction}__{tf}__atr{br.fmt(atr)}_h{hold}__v1"


def _row(direction, ep, xp, held, reason, cost, exit_i):
    g = (xp - ep) / ep if direction == "long" else (ep - xp) / ep
    return {"gross": g, "net": g - cost, "held": held, "reason": reason, "exit_i": exit_i}


def pick_tag(cells, rule):
    """Any real PL1D tag with this rule: the real signal fn only uses it to select the rule (its k is replaced by the sweep's)."""
    return next(t for t, c in cells.items() if c[0] == rule)


def replay_symbol(m, df, direction, atrs, holds, tf, cost):
    """-> {tag: [trade rows]} for both rules of one direction on one symbol."""
    df = df.reset_index(drop=True)
    n = len(df)
    long_ = direction == "long"
    cells = m.PL1D_CELLS if long_ else m.PL1D_SHORT_CELLS
    sig_fn = m.pl1d_long_entry_signal if long_ else m.pl1d_short_entry_signal
    exit_fn = m.pl1d_exit_reason if long_ else m.pl1d_short_exit_reason
    out = {tag_for(r, direction, tf, a, h): [] for r in RULES for a in atrs for h in holds}
    if n < MIN_BARS + 3:
        return out
    free = {t: 0 for t in out}
    rule_tag = {r: pick_tag(cells, r) for r in RULES}
    for k in range(MIN_BARS - 1, n - 1):
        sub = df.iloc[:k + 1]
        for r in RULES:
            sig = sig_fn(sub, rule_tag[r])
            if not sig:
                continue
            ep, atr_e = sig["entry_price"], sig["atr_at_entry"]
            for a in atrs:
                stop = ep - a * atr_e if long_ else ep + a * atr_e
                if not (stop > 0):
                    continue
                for h in holds:
                    t = tag_for(r, direction, tf, a, h)
                    if k < free[t]:
                        continue
                    window = df.iloc[k + 1:k + 1 + h]
                    reason, px = exit_fn(window, BEFORE_ALL, stop, h)
                    if reason:
                        held = int(len(window)) if reason.endswith("timeout") else int(np.flatnonzero(
                            (window["Low"].to_numpy(float) <= stop) if long_ else (window["High"].to_numpy(float) >= stop))[0]) + 1
                        row = _row(direction, ep, px, held, reason, cost, k + held)
                    else:  # data ended before the hold: forced close at the last bar
                        row = _row(direction, ep, float(df["Close"].iloc[-1]), n - 1 - k, "data_end_forced_close", cost, n - 1)
                    out[t].append(row)
                    free[t] = row["exit_i"] + 1
    return out


def synthetic_frame(seed, n=500):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, n)))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.012, n))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    d = pd.date_range("2024-01-01 09:15", periods=n, freq="h")
    return pd.DataFrame({"Date": d.astype(str), "Open": o, "High": hi, "Low": lo, "Close": c, "Volume": 1e6})


def fetch_tf(m, sym, tf):
    raw = m.fetch_ohlc(sym, "730d", "1h")
    if tf == "1h" or raw is None or len(raw) == 0:
        return raw
    import resample_4h as r4
    ix = raw.set_index(pd.DatetimeIndex(raw["Date"]))
    out = r4.resample_1h_to_4h(ix[["Open", "High", "Low", "Close"] + (["Volume"] if "Volume" in ix.columns else [])]).copy()
    out.insert(0, "Date", out.index)
    return out.reset_index(drop=True)


def load_frames(m, tf, shard, nshards, limit=None):
    if os.environ.get("SYNTHETIC") == "1":
        return {f"SYN{k}": synthetic_frame(k) for k in range(limit or 3)}
    syms = sorted(set(m._load_nse_universe_from_file()))[shard::nshards]
    if limit:
        syms = syms[:limit]
    out = {}
    for s in syms:
        try:
            f = fetch_tf(m, s, tf)
        except Exception:
            continue
        if f is not None and len(f) >= MIN_BARS + 3:
            out[s] = f.reset_index(drop=True)
    return out


def parse_list(name, default, cast):
    v = os.environ.get(name)
    return tuple(cast(x) for x in v.split(",") if x.strip()) if v else tuple(default)


def run():
    import main as m
    tf = os.environ.get("TF", "4h")
    if tf not in DEFAULT_HOLDS:
        raise SystemExit(f"bad TF {tf}")
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    atrs = parse_list("ATRS", DEFAULT_ATRS, float)
    holds = parse_list("HOLDS", DEFAULT_HOLDS[tf], int)
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    frames = load_frames(m, tf, shard, nshards, limit)
    dropped = 0
    if bh is not None:
        frames, dropped = bh.clean_frames(frames)
    aggs = {}
    for sym, df in frames.items():
        for d in ("long", "short"):
            try:
                res = replay_symbol(m, df, d, atrs, holds, tf, cost)
            except Exception as ex:
                print("ERROR", sym, d, ex)
                continue
            for t, trs in res.items():
                br.agg_add(aggs.setdefault(t, br.agg_new()), trs)
    out = {"family": "pl1d_tf", "interval": tf, "period": "730d", "shard": shard, "nshards": nshards,
           "n_symbols": len(frames), "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT, "bars_dropped_glitch": dropped,
           "synthetic": os.environ.get("SYNTHETIC") == "1", "atrs": list(atrs), "holds": list(holds),
           "cells": {t: {"raw": a} for t, a in aggs.items()}}
    os.makedirs("out", exist_ok=True)
    path = f"out/pl1d_tf_{tf}_s{shard}.json"
    json.dump(out, open(path, "w"), indent=1)
    print("wrote", path, "symbols", len(frames), "cells", len(aggs))


def merge(d, out_path=None):
    tags, meta = {}, {}
    for f in sorted(glob.glob(os.path.join(d, "**", "pl1d_tf_*_s*.json"), recursive=True)):
        r = json.load(open(f))
        for t, c in r["cells"].items():
            e = tags.setdefault(t, {"agg": br.agg_new(), "n_symbols": 0, "shards": 0, "tf": r["interval"]})
            br.agg_merge(e["agg"], c["raw"])
            e["n_symbols"] += r["n_symbols"]
            e["shards"] += 1
        meta = {k: r[k] for k in ("cost_round_trip_pct", "synthetic", "period")}
    rows = []
    for t, e in sorted(tags.items()):
        mt = br.agg_metrics(e["agg"])
        mt["avg_held_hours"] = round(mt["avg_held_bars"] * HOURS_PER_BAR[e["tf"]], 1)
        rows.append({"tag": t, "interval": e["tf"], "n_symbols": e["n_symbols"], "shards": e["shards"], "metrics": mt})
        print(t, "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"], "hold_h", mt["avg_held_hours"])
    out = {**meta, "note": "entry = signal-bar close, exits from the next bar via the real pl1d exit fns, FIFO per cell; hold and rule "
           "windows are BARS of the tf (4h ~2 bars/day, avg 3.5h); 730d sample; schema read by main._replay_verified_tags",
           "rows": rows}
    json.dump(out, open(out_path or os.path.join(d, "replay_all.json"), "w"), indent=1)
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        run()
