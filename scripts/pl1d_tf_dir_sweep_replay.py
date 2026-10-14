"""B-1091: pattern-lab 'pl1d' cells (STARC band fade, gap runaway) x BOTH directions x candle size x ATR sweep through the REAL
main.py functions (closes the 'candle-size/ATR sweep owed after baseline' half of B-1001 and the long half of B-983). Research
only, nothing wired.

Entry = main.pl1d_long_entry_signal / main.pl1d_short_entry_signal (rule + ATR14 stop), exit = main.pl1d_exit_reason /
main.pl1d_short_exit_reason (gap-aware stop, else close of the hold-th bar). Both cells are cell-bound in main
(PL1D_CELLS / PL1D_SHORT_CELLS map tag -> (rule, ATR multiple, hold)), so this research PROCESS registers each swept tag in
those dicts at start-up (in-process only, nothing written back, live code never sees it) and then calls the unmodified main
functions with that tag. The exit fns compare dates at DAY granularity (str[:10]); for intraday bars the driver therefore hands
them bar-ordinal date strings ('0000000123') for the slice entry-bar..j, which makes 'dates > entry_day' mean 'bars after the
signal bar' exactly (same function, bar-index semantics). Fill = signal bar close, stop on every trade (atrnone refused),
strict FIFO per symbol per tag, cost = main.ROUND_TRIP_COST_PCT, full universe main._load_nse_universe_from_file().
CAVEAT: SMA6/ATR15/SMA50 windows, 'gap' = open vs the PRIOR BAR's high/low x 1.01/0.99 and the 20-bar hold are BARS of the
candle in use (at 5m a 1% bar-to-bar gap is rare, and 20 bars is under 2 hours); 1d is not re-run here (existing workflows).
Tags: <family>__<variant>__<dir>__<tf>__atr<k>_h20__v1 (starc__fade_full, gap__runaway), each its own tag.
Modes: run (env TF 4h|1h|15m|5m, ATRS "2.5,4,6", HOLD, SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1) -> out/pl1d_<tf>_s<shard>.json;
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
MIN_BARS = 62
RULES = {"starc_fade": "starc__fade_full", "gap_runaway": "gap__runaway"}
DIRS = ("long", "short")
DEFAULT_ATRS = (2.5, 4.0, 6.0)
DEFAULT_HOLD = 20
DEFAULT_SHARDS = {"4h": 8, "1h": 8, "15m": 16, "5m": 24}


def make_tag(rule, direction, tf, atr, hold=DEFAULT_HOLD):
    fam = RULES[rule]
    return f"{fam}__{direction}__{tf}__atr{C.num_token(atr)}_h{int(hold)}__v1"


def cell_specs(tf, atrs, hold):
    return {make_tag(r, d, tf, a, hold): {"rule": r, "dir": d, "tf": tf, "atr": a, "hold": int(hold)}
            for r in RULES for d in DIRS for a in atrs}


def register_cells(m, specs):
    """In-process only: let the cell-bound main entry/exit fns resolve the swept tags (rule, ATR multiple, hold)."""
    for tag, sp in specs.items():
        (m.PL1D_CELLS if sp["dir"] == "long" else m.PL1D_SHORT_CELLS)[tag] = (sp["rule"], sp["atr"], sp["hold"])


def run_trade(m, df, k, sig, tag, sp, cost):
    n = len(df)
    sgn = 1.0 if sp["dir"] == "long" else -1.0
    ep, stop0 = sig["entry_price"], sig["stop_loss"]
    fn = m.pl1d_exit_reason if sp["dir"] == "long" else m.pl1d_short_exit_reason
    ent = f"{k:010d}"
    for j in range(k + 1, n):
        seg = df.iloc[k:j + 1].copy()
        seg["Date"] = [f"{i:010d}" for i in range(k, j + 1)]
        reason, px = fn(seg, ent, stop0, sp["hold"])
        if reason:
            g = sgn * (px - ep) / ep
            return {"gross": g, "net": g - cost, "held": j - k, "reason": reason}, j
    g = sgn * (float(df["Close"].iloc[-1]) - ep) / ep
    return {"gross": g, "net": g - cost, "held": n - 1 - k, "reason": "data_end_forced_close"}, n - 1


def replay_symbol(m, df, specs, cost):
    df = df.reset_index(drop=True)
    out = {t: [] for t in specs}
    n = len(df)
    if n < MIN_BARS + 3:
        return out
    free = {t: 0 for t in specs}
    for k in range(MIN_BARS - 1, n - 1):
        sub = df.iloc[:k + 1]
        fires = {}
        for tag, sp in specs.items():
            if k < free[tag]:
                continue
            key = (sp["rule"], sp["dir"])
            if key not in fires:  # real rule fn once per (rule, dir) per bar
                fires[key] = (m.pl1d_rule_fires(sub, sp["rule"]) if sp["dir"] == "long"
                              else m.pl1d_short_rule_fires(sub, sp["rule"]))
            if not fires[key]:
                continue
            sig = (m.pl1d_long_entry_signal(sub, tag) if sp["dir"] == "long" else m.pl1d_short_entry_signal(sub, tag))
            if not sig:
                continue
            tr, free[tag] = run_trade(m, df, k, sig, tag, sp, cost)
            out[tag].append(tr)
    return out


def run():
    import main as m
    tf = os.environ.get("TF", "4h")
    if tf not in C.TFS or tf == "1d":
        raise ValueError("TF must be one of 4h, 1h, 15m, 5m (1d has its own pl1d workflows)")
    atrs = C.parse_atrs(os.environ.get("ATRS"), DEFAULT_ATRS)
    hold = int(os.environ.get("HOLD") or DEFAULT_HOLD)
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    specs = cell_specs(tf, atrs, hold)
    register_cells(m, specs)
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
    C.write_shard("pl1d", tf, shard, nshards, len(frames), m.ROUND_TRIP_COST_PCT, specs, aggs,
                  "rule windows/gap/hold are bars of the candle in use; exits use bar-ordinal dates; stop on every trade")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        C.merge_dir(sys.argv[2], "pl1d", "pl1d_all.json")
    elif len(sys.argv) > 1 and sys.argv[1] == "plan":
        print(json.dumps(C.plan(None, DEFAULT_SHARDS)))
    else:
        run()
