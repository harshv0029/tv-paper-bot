"""B-1090 (closes the replay half of B-891): island reversal SHORT (and LONG mirror) x candle size x ATR sweep through the
REAL main.py functions. Research only, nothing wired.

SHORT entry = main.island_short_entry_signal(sub, <1d short tag of the filter>), LONG entry = main.island_swing_entry_signal(
sub, <1d long tag of the filter>) (the tag only selects the liquidity filter none/px20/turn1cr/gap05; detector, ATR14 and
filters are main's). Stop = main.brk20_stop_price(entry, atr_at_entry, k, dir) with the ATR multiple k SWEPT (main fixes 1.5;
the signal does not depend on k), ALWAYS attached (atrnone refused). Exit = main.brk20_min_rr_exit_reason(window, fill_day,
entry, stop, dir) (gap-aware stop -> EMA13 rule exit -> 30-bar max hold), the function both live island exit adapters wrap.
Fill = signal bar close, exits from the next bar. Strict FIFO per symbol per tag. Cost = main.ROUND_TRIP_COST_PCT.
Universe = main._load_nse_universe_from_file() (full). tf: 1d (5y), 4h (1h x 730d resampled, scripts/resample_4h.py),
1h (730d), 15m (60d), 5m (60d). CAVEAT: within8, the 20-bar liquidity window and the 30-bar hold are BARS of the candle in
use (within8 at 5m = 40 minutes: a different pattern from the daily island); intraday windows hold 60d only, so n is thin.
Tags: reversal__island_<filter>__<dir>__<tf>__atr<k>_within8__nonovl__v2 (each its own tag; 1d atr1d5 reproduces the
existing registry names and is the cross-check vs B-881/B-891 runs).
Modes: run (env TF, ATRS "1.5,2.5,4", SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1) -> out/isl_<tf>_s<shard>.json; merge <dir>; plan.
"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import tf_sweep_common as C  # noqa: E402

B = C.B
MIN_BARS = 22
FILTERS = ("none", "px20", "turn1cr", "gap05")
DIRS = ("short", "long")
DEFAULT_ATRS = (1.5, 2.5, 4.0)
DEFAULT_SHARDS = {"1d": 4, "4h": 8, "1h": 8, "15m": 16, "5m": 24}


def make_tag(flt, direction, tf, atr):
    return f"reversal__island_{flt}__{direction}__{tf}__atr{C.num_token(atr)}_within8__nonovl__v2"


def cell_specs(tf, atrs):
    return {make_tag(f, d, tf, a): {"filter": f, "dir": d, "tf": tf, "atr": a} for f in FILTERS for d in DIRS for a in atrs}


def selector_tag(m, flt, direction):
    if direction == "short":
        return {"none": m.ISLAND_SHORT_NONE_TAG, "px20": m.ISLAND_SHORT_PX20_TAG, "turn1cr": m.ISLAND_SHORT_TURN1CR_TAG,
                "gap05": m.ISLAND_SHORT_GAP05_TAG}[flt]
    return {"none": m.ISLAND_NONE_TAG, "px20": m.ISLAND_PX20_TAG, "turn1cr": m.ISLAND_TURN1CR_TAG,
            "gap05": m.ISLAND_GAP05_TAGS[0]}[flt]


def candidate_bars(df, direction, within=8):
    """Exact necessary condition for the island completion bar j (a gap in the signal direction at j and an opposite gap
    in the prior `within` bars); main's detector still decides every signal."""
    h, l = df["High"].to_numpy(float), df["Low"].to_numpy(float)
    n = len(df)
    up = np.zeros(n, bool)
    dn = np.zeros(n, bool)
    up[1:] = l[1:] > h[:-1]
    dn[1:] = h[1:] < l[:-1]
    first, second = (up, dn) if direction == "short" else (dn, up)  # short: gap-up island then gap-down at j
    cs = np.concatenate(([0], np.cumsum(first)))
    ok = np.zeros(n, bool)
    for j in range(1, n):
        lo = max(1, j - within)
        ok[j] = second[j] and (cs[j] - cs[lo]) > 0
    return ok


def collect_signals(m, df, flt, direction):
    """{bar k: sig} from the REAL main entry fn on candidate bars."""
    tag = selector_tag(m, flt, direction)
    fn = m.island_short_entry_signal if direction == "short" else m.island_swing_entry_signal
    cand = candidate_bars(df, direction)
    sigs = {}
    for k in range(MIN_BARS - 1, len(df) - 1):
        if cand[k]:
            s = fn(df.iloc[:k + 1], tag)
            if s:
                sigs[k] = s
    return sigs


def run_trade(m, df, k, ep, stop0, direction, dates, cost):
    n = len(df)
    sgn = 1.0 if direction == "long" else -1.0
    fill_day = dates[k + 1]
    for j in range(k + 1, n):
        reason, px = m.brk20_min_rr_exit_reason(df.iloc[max(0, j - 399):j + 1], fill_day, ep, stop0, direction)
        if reason:
            g = sgn * (px - ep) / ep
            return {"gross": g, "net": g - cost, "held": j - k, "reason": reason}, j
    g = sgn * (float(df["Close"].iloc[-1]) - ep) / ep
    return {"gross": g, "net": g - cost, "held": n - 1 - k, "reason": "data_end_forced_close"}, n - 1


def replay_symbol(m, df, specs, cost):
    """{tag: [trades]} for one symbol; signals computed once per (filter, dir), exits per ATR multiple."""
    df = df.reset_index(drop=True)
    out = {t: [] for t in specs}
    if len(df) < MIN_BARS + 3:
        return out
    dates = df["Date"].astype(str).to_numpy()
    sig_cache = {}
    for tag, sp in specs.items():
        key = (sp["filter"], sp["dir"])
        if key not in sig_cache:
            sig_cache[key] = collect_signals(m, df, *key)
        free = 0
        for k, s in sorted(sig_cache[key].items()):
            if k < free:
                continue
            ep = s["entry_price"]
            stop0 = m.brk20_stop_price(ep, s["atr_at_entry"], sp["atr"], sp["dir"])
            if not ((stop0 < ep) if sp["dir"] == "long" else (stop0 > ep > 0)) or stop0 <= 0:
                continue
            tr, free = run_trade(m, df, k, ep, stop0, sp["dir"], dates, cost)
            out[tag].append(tr)
    return out


def run():
    import main as m
    tf = os.environ.get("TF", "1d")
    if tf not in C.TFS:
        raise ValueError(f"TF must be one of {sorted(C.TFS)}")
    atrs = C.parse_atrs(os.environ.get("ATRS"), DEFAULT_ATRS)
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    specs = cell_specs(tf, atrs)
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
    C.write_shard("isl", tf, shard, nshards, len(frames), m.ROUND_TRIP_COST_PCT, specs, aggs,
                  "within8/liquidity window/30-bar hold are bars of the candle in use; stop on every trade; short pnl=(entry-cover)/entry")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        C.merge_dir(sys.argv[2], "isl", "isl_all.json")
    elif len(sys.argv) > 1 and sys.argv[1] == "plan":
        print(json.dumps(C.plan(None, DEFAULT_SHARDS)))
    else:
        run()
