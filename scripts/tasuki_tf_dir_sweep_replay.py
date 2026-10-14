"""B-1181: tasuki gap x BOTH directions x candle size x ATR x universe sweep through the REAL main.py functions. Research
only, nothing wired, main.py untouched.

SHORT (native in main, registry tasuki__gap_etf__short__1d__atr{6,4,2d5}_h3): signal main.tasuki_short_signal(sub), stop
main.tasuki_short_stop(entry, main._compute_atr_value(sub, 14), k) with k SWEPT, exit main.tasuki_short_exit_reason(bars after the
signal bar, stop, hold). LONG (main has no port): the SAME real functions on the RECIPROCAL-price frame
(tf_sweep_common.inverted_frame) detect the exact bullish mirror (upside tasuki gap) on the original prices; stop_long =
entry - k x ATR14(original) computed as 2 x entry - main.tasuki_short_stop(...) (the fn's own symmetric arithmetic), the exit
fn runs on the inverted bars with stop' = 1/stop_long (high' >= stop' is low <= stop, fill max(open', stop') is min(open, stop)),
and prices map back as 1/x. Fill = signal-bar close, strict FIFO per symbol per tag, stop on every trade (atrnone refused),
cost = main.ROUND_TRIP_COST_PCT. Universes (each its own tag family, never merged): etf = main.ETF_SYMBOLS (the universe the
short registry rows were measured on; the NIFTY-200 equity cut was 0.69), full = main._load_nse_universe_from_file().
tf: 1d (5y), 4h (1h x 730d via scripts/resample_4h.py), 1h, 15m, 5m (60d). CAVEAT: the 3-bar pattern and the 3-bar hold are
BARS of the candle in use (3 bars at 5m = 15 minutes); 1d etf short atr<k> reproduces the existing registry names as the cross-check.
Tags: tasuki__gap_<etf|full>__<dir>__<tf>__atr<k>_h<H>__v1.
Modes: run (env TF, UNIV etf|full, ATRS "2.5,4,6", HOLDS "3", SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1) ->
out/tasuki_<univ>_<tf>_s<shard>.json; merge <dir>; plan.
"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import tf_sweep_common as C  # noqa: E402

B = C.B
MIN_BARS = 20
DIRS = ("short", "long")
DEFAULT_ATRS = (2.5, 4.0, 6.0)
DEFAULT_HOLDS = (3,)
DEFAULT_SHARDS = {"1d": 4, "4h": 8, "1h": 8, "15m": 16, "5m": 24}
ETF_SHARDS = 1


def make_tag(univ, direction, tf, atr, hold):
    return f"tasuki__gap_{univ}__{direction}__{tf}__atr{C.num_token(atr)}_h{int(hold)}__v1"


def cell_specs(univ, tf, atrs, holds):
    return {make_tag(univ, d, tf, a, h): {"univ": univ, "dir": d, "tf": tf, "atr": a, "hold": int(h)}
            for d in DIRS for a in atrs for h in holds}


def parse_holds(s):
    try:
        out = [int(x) for x in str(s or "").split(",") if x.strip()]
    except ValueError:
        raise ValueError("HOLDS must be integers")
    out = out or list(DEFAULT_HOLDS)
    if any(h < 1 for h in out):
        raise ValueError("hold must be >= 1 bar")
    return out


def prefilter(df, direction):
    """Exact necessary condition (first-bar-of-three down candle for short / up candle for long) to skip most real calls."""
    o, c = df["Open"].to_numpy(float), df["Close"].to_numpy(float)
    ok = np.zeros(len(df), bool)
    if len(df) > 2:
        ok[2:] = (c[:-2] < o[:-2]) if direction == "short" else (c[:-2] > o[:-2])
    return ok


def signals(m, df, inv, direction):
    """{k: (entry, atr)} from the REAL tasuki_short_signal (short: original frame; long: inverted frame)."""
    cand = prefilter(df, direction)
    out = {}
    for k in range(MIN_BARS - 1, len(df) - 1):
        if not cand[k]:
            continue
        src = df if direction == "short" else inv
        if not m.tasuki_short_signal(src.iloc[max(0, k - 2):k + 1]):
            continue
        atr = m._compute_atr_value(df.iloc[max(0, k - 199):k + 1], 14)
        if atr and float(atr) > 0:
            out[k] = (float(df["Close"].iloc[k]), float(atr))
    return out


def stop_for(m, ep, atr, k, direction):
    s = m.tasuki_short_stop(ep, atr, k)
    if s is None:
        return None
    return s if direction == "short" else 2.0 * ep - s


def run_trade(m, df, inv, k, ep, stop, direction, hold, cost):
    n = len(df)
    bars_src = df if direction == "short" else inv
    stop_x = stop if direction == "short" else 1.0 / stop
    for j in range(k + 1, min(n, k + hold + 1)):
        res = m.tasuki_short_exit_reason(bars_src.iloc[k + 1:j + 1], stop_x, hold)
        if res:
            px = float(res[1]) if direction == "short" else 1.0 / float(res[1])
            g = (ep - px) / ep if direction == "short" else (px - ep) / ep
            return {"gross": g, "net": g - cost, "held": j - k, "reason": res[0]}, j
    g = (ep - float(df["Close"].iloc[-1])) / ep if direction == "short" else (float(df["Close"].iloc[-1]) - ep) / ep
    return {"gross": g, "net": g - cost, "held": n - 1 - k, "reason": "data_end_forced_close"}, n - 1


def replay_symbol(m, df, specs, cost):
    df = df.reset_index(drop=True)
    out = {t: [] for t in specs}
    if len(df) < MIN_BARS + 3:
        return out
    inv = C.inverted_frame(df)
    cache = {}
    for tag, sp in specs.items():
        if sp["dir"] not in cache:
            cache[sp["dir"]] = signals(m, df, inv, sp["dir"])
        free = 0
        for k, (ep, atr) in sorted(cache[sp["dir"]].items()):
            if k < free:
                continue
            stop = stop_for(m, ep, atr, sp["atr"], sp["dir"])
            if stop is None or not ((stop > ep) if sp["dir"] == "short" else (0 < stop < ep)):
                continue
            tr, free = run_trade(m, df, inv, k, ep, stop, sp["dir"], sp["hold"], cost)
            out[tag].append(tr)
    return out


def run():
    import main as m
    tf = os.environ.get("TF", "1d")
    univ = os.environ.get("UNIV", "etf")
    if tf not in C.TFS or univ not in ("etf", "full"):
        raise ValueError("TF in 1d/4h/1h/15m/5m, UNIV in etf/full")
    atrs = C.parse_atrs(os.environ.get("ATRS"), DEFAULT_ATRS)
    holds = parse_holds(os.environ.get("HOLDS"))
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    specs = cell_specs(univ, tf, atrs, holds)
    frames = C.load_frames(m, tf, shard, nshards, MIN_BARS + 3, limit, pool=(m.ETF_SYMBOLS if univ == "etf" else None))
    aggs = {t: B.agg_new() for t in specs}
    for sym, df in frames.items():
        try:
            res = replay_symbol(m, df, specs, cost)
        except Exception as ex:
            print("ERROR", sym, ex)
            continue
        for t, trs in res.items():
            B.agg_add(aggs[t], trs)
    C.write_shard(f"tasuki_{univ}", tf, shard, nshards, len(frames), m.ROUND_TRIP_COST_PCT, specs, aggs,
                  "long = real fns on reciprocal-price frame (exact mirror); pattern/hold are bars of the candle; stop on every trade")


def plan(env=None):
    e = env if env is not None else os.environ
    inc = [{"univ": "etf", "tf": tf, "shard": 0, "nshards": ETF_SHARDS} for tf in DEFAULT_SHARDS]
    for tf, d in DEFAULT_SHARDS.items():
        n = int(e.get("NSHARDS_" + tf.upper(), str(d)))
        inc += [{"univ": "full", "tf": tf, "shard": s, "nshards": n} for s in range(n)]
    return {"include": inc}


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        C.merge_dir(sys.argv[2], "tasuki", "tasuki_all.json")
    elif len(sys.argv) > 1 and sys.argv[1] == "plan":
        print(json.dumps(plan()))
    else:
        run()
