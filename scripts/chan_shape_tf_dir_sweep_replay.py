"""B-1180: chan_shape (Chan hybrid momentum/mean-reversion shape) x BOTH directions x candle size x ATR x hold sweep through
the REAL main.py functions. Research only, nothing wired, main.py untouched.

LONG (native in main): signal = main.chan_shape_long_entry_signal(sub, <any CHAN_SHAPE_CELLS tag>) (close < close[30] and
close > close[40]; the signal does not depend on the cell's ATR, the tag is only a selector), stop = entry - k x atr_at_entry
(the fn's own chan_atr14 value; k SWEPT), exit = main.chan_shape_exit_reason.
SHORT (main has no short port): the SAME real functions run on the RECIPROCAL-price frame (tf_sweep_common.inverted_frame),
which is the exact mirror pattern on the original prices (close > close[30] and close < close[40]); stop = entry + k x
main.chan_atr14(original); the exit fn runs on the inverted segment with stop' = 1/stop, so the gap-aware fill max(stop, open)
maps back exactly. Cover/entry prices are mapped back as 1/x. No reimplementation of the rule or the exit.
chan_shape_exit_reason compares dates at DAY granularity (str[:10]), so the driver hands it bar-ordinal date strings for the
entry..j slice (same function, bar-index semantics; fill bar = first bar after the signal). Fill = signal-bar close, strict FIFO
per symbol per tag, stop on every trade (atrnone refused), cost = main.ROUND_TRIP_COST_PCT, universe =
main._load_nse_universe_from_file(). tf: 1d (5y), 4h (1h x 730d, scripts/resample_4h.py), 1h, 15m, 5m (60d).
CAVEAT: the 30/40-bar lookbacks and the 5/10-bar holds are BARS of the candle in use. Registry says the pooled 1d long cells
are 0.64-0.86 (below floor): 1d long atr<k>_hold<H> here reproduces those tag names as the cross-check.
Tags: chan_shape__mom_mr__<dir>__<tf>__atr<k>_hold<H>__nonovl__v2 (each its own tag).
Modes: run (env TF, ATRS "1.5,2.5,4", HOLDS "5,10", SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1) -> out/cshape_<tf>_s<shard>.json;
merge <dir>; plan.
"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import tf_sweep_common as C  # noqa: E402

B = C.B
NEAR, FAR = 30, 40
MIN_BARS = 62
DIRS = ("long", "short")
DEFAULT_ATRS = (1.5, 2.5, 4.0)
DEFAULT_HOLDS = (5, 10)
DEFAULT_SHARDS = {"1d": 4, "4h": 8, "1h": 8, "15m": 16, "5m": 24}


def make_tag(direction, tf, atr, hold):
    a = ("%.1f" % atr).replace(".", "d")  # main's own convention (atr4d0), so 1d tags equal the registry names
    return f"chan_shape__mom_mr__{direction}__{tf}__atr{a}_hold{int(hold)}__nonovl__v2"


def cell_specs(tf, atrs, holds):
    return {make_tag(d, tf, a, h): {"dir": d, "tf": tf, "atr": a, "hold": int(h)} for d in DIRS for a in atrs for h in holds}


def parse_holds(s):
    try:
        out = [int(x) for x in str(s or "").split(",") if x.strip()]
    except ValueError:
        raise ValueError("HOLDS must be integers")
    out = out or list(DEFAULT_HOLDS)
    if any(h < 1 for h in out):
        raise ValueError("hold must be >= 1 bar")
    return out


def prefilter(c, direction):
    """Exact necessary condition for the chan_shape signal on bar k (comparisons of close vs close[-30]/[-40])."""
    n = len(c)
    ok = np.zeros(n, bool)
    if n > FAR:
        a, b, x = c[FAR:], c[:-FAR], c[FAR - NEAR:-NEAR]
        ok[FAR:] = (a < x) & (a > b) if direction == "long" else (a > x) & (a < b)
    return ok


def run_trade(m, df, inv, k, ep, stop, direction, hold, cost):
    n = len(df)
    ent = f"{k:010d}"
    sgn = 1.0 if direction == "long" else -1.0
    src = df if direction == "long" else inv
    stop_x = stop if direction == "long" else 1.0 / stop
    for j in range(k + 1, n):
        seg = src.iloc[k:j + 1].copy()
        seg["Date"] = [f"{i:010d}" for i in range(k, j + 1)]
        reason, px = m.chan_shape_exit_reason(seg, ent, stop_x, hold)
        if reason:
            px = float(px) if direction == "long" else 1.0 / float(px)
            g = sgn * (px - ep) / ep
            return {"gross": g, "net": g - cost, "held": j - k, "reason": reason}, j
    g = sgn * (float(df["Close"].iloc[-1]) - ep) / ep
    return {"gross": g, "net": g - cost, "held": n - 1 - k, "reason": "data_end_forced_close"}, n - 1


def signals(m, df, inv, direction):
    """{k: (entry, atr)} - signal decided by the REAL entry fn (long on the original, short on the inverted frame)."""
    tag = min(m.CHAN_SHAPE_CELLS, key=lambda t: m.CHAN_SHAPE_CELLS[t][0])  # mildest in-fn stop filter; k is swept here
    cand = prefilter(df["Close"].to_numpy(float), direction)
    out = {}
    for k in range(MIN_BARS - 1, len(df) - 1):
        if not cand[k]:
            continue
        lo = max(0, k - 399)
        if direction == "long":
            s = m.chan_shape_long_entry_signal(df.iloc[lo:k + 1], tag)
            if s:
                out[k] = (s["entry_price"], s["atr_at_entry"])
        else:
            if m.chan_shape_long_entry_signal(inv.iloc[lo:k + 1], tag):
                a = float(m.chan_atr14(df["High"].iloc[lo:k + 1].to_numpy(float), df["Low"].iloc[lo:k + 1].to_numpy(float),
                                       df["Close"].iloc[lo:k + 1].to_numpy(float))[-1])
                if np.isfinite(a) and a > 0:
                    out[k] = (float(df["Close"].iloc[k]), a)
    return out


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
            stop = ep - sp["atr"] * atr if sp["dir"] == "long" else ep + sp["atr"] * atr
            if not ((0 < stop < ep) if sp["dir"] == "long" else (stop > ep > 0)):
                continue
            tr, free = run_trade(m, df, inv, k, ep, stop, sp["dir"], sp["hold"], cost)
            out[tag].append(tr)
    return out


def run():
    import main as m
    tf = os.environ.get("TF", "1d")
    if tf not in C.TFS:
        raise ValueError(f"TF must be one of {sorted(C.TFS)}")
    atrs = C.parse_atrs(os.environ.get("ATRS"), DEFAULT_ATRS)
    holds = parse_holds(os.environ.get("HOLDS"))
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    specs = cell_specs(tf, atrs, holds)
    frames = C.load_frames(m, tf, shard, nshards, MIN_BARS + 3, limit)
    aggs = {t: B.agg_new() for t in specs}
    for sym, df in frames.items():
        try:
            res = replay_symbol(m, df, specs, cost)
        except Exception as ex:
            print("ERROR", sym, ex)
            continue
        for t, trs in res.items():
            B.agg_add(aggs[t], trs)
    C.write_shard("cshape", tf, shard, nshards, len(frames), m.ROUND_TRIP_COST_PCT, specs, aggs,
                  "short = real fns on reciprocal-price frame (exact mirror); 30/40 lookbacks and holds are bars of the candle; stop on every trade")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        C.merge_dir(sys.argv[2], "cshape", "cshape_all.json")
    elif len(sys.argv) > 1 and sys.argv[1] == "plan":
        print(json.dumps(C.plan(None, DEFAULT_SHARDS)))
    else:
        run()
