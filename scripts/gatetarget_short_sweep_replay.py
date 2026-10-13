"""B-1010: candle-size x ATR sweep of the swingminrr brk20_gatetarget SHORT cell (main.SWINGMINRR_GATETARGET_SHORT_1H_TAG,
registry 1.561 at 1h atr3_rr4) at 4h (1h x 730d resampled by scripts/resample_4h.py), 15m (60d) and 5m (60d).

REAL main.py functions: entry main.brk20_min_rr_entry_signal(sub, 'short', atr, rr) (the exact call behind
main.swingminrr_gate_short_entry_signal, with the ATR multiple swept instead of fixed at 3.0); exit
main.swingminrr_gate_short_exit_reason(bars, stop, max_hold, target) (stop gap-aware first, resting BUY target at
entry - rr x risk, else close of bar max_hold). SL on EVERY trade (stop = entry + atr x ATR14, atrnone refused).
Universe = main._load_nse_universe_from_file() (full, NOT NSE_FULL_UNIVERSE). Cost = main.ROUND_TRIP_COST_PCT (0.8%).
Fill = signal bar close (= live scan). One position per symbol per tag (FIFO); each tag replayed independently.
CAVEAT (stated, not hidden): bar-count constants (20/60-bar breakout/room lookback, 30-bar hold) are BARS of the
candle in use, so their wall-clock meaning changes: 4h = 2 bars/session (30 bars = 15 sessions), 15m = ~25 bars/session
(30 bars ~ 1.2 sessions), 5m = ~75 bars/session (30 bars ~ 0.4 session, the 60-bar room is under a session).
Tags: swingminrr__brk20_gatetarget__short__<tf>__atr<k>_h<H>_rr<R>__v1 (each its own tag; 1h cell keeps its existing tag).
Modes: run (env TF 4h|15m|5m, ATRS "2,3,4,6", RR, HOLD, SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1) -> out/gts_<tf>_s<shard>.json;
merge <dir> -> <dir>/gts_all.json (rows[].metrics, same shape as tsm_all.json); plan.
"""
import glob
import json
import os
import sys
import warnings

import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import brk20_replay as B  # noqa: E402

MIN_BARS = 62
WINDOW = 200
TFS = {"4h": {"period": "730d", "fetch": "1h", "bar_hours": 3.5},
       "15m": {"period": "60d", "fetch": "15m", "bar_hours": 0.25},
       "5m": {"period": "60d", "fetch": "5m", "bar_hours": 5 / 60.0}}
DEFAULT_ATRS = (2.0, 3.0, 4.0, 6.0)
DEFAULT_RR = 4.0
DEFAULT_HOLD = 30
LOOKBACK = 20  # main.BRK20_LOOKBACK_BARS (read from main at run time too)


def num_token(x):
    return ("%g" % x).replace(".", "d")


def make_tag(tf, atr, rr=DEFAULT_RR, hold=DEFAULT_HOLD):
    return f"swingminrr__brk20_gatetarget__short__{tf}__atr{num_token(atr)}_h{int(hold)}_rr{num_token(rr)}__v1"


def parse_atrs(s):
    try:
        out = [float(x) for x in str(s).replace(";", ",").split(",") if x.strip()]
    except ValueError:
        raise ValueError("ATR multiples must be numbers (atrnone refused: no trade without a stop)")
    if not out or any(a <= 0 for a in out):
        raise ValueError("ATR multiples must be > 0 (no trade without a stop: atrnone refused)")
    return out


def cell_specs(tf, atrs, rr, hold):
    return {make_tag(tf, a, rr, hold): {"tf": tf, "atr": a, "rr": rr, "hold": int(hold)} for a in atrs}


def replay_symbol(m, df, spec, cost):
    """One symbol, one cell (SHORT). Returns trade dicts {gross, net, held, reason}. Real main.py entry + exit fns."""
    df = df.reset_index(drop=True)
    n = len(df)
    if n < MIN_BARS + 3:
        return []
    lb = int(getattr(m, "BRK20_LOOKBACK_BARS", LOOKBACK))
    lows, closes = df["Low"].to_numpy(float), df["Close"].to_numpy(float)
    # exact necessary condition (close < prior-lb low) computed once; main's fn still decides every signal
    prior_min = pd.Series(lows).shift(1).rolling(lb).min().to_numpy()
    cand = closes < prior_min
    out, pos, blocked = [], None, -1
    for k in range(MIN_BARS - 1, n):
        if pos is not None and k > pos["sig"]:
            bars = df.iloc[pos["sig"] + 1:k + 1]
            res = m.swingminrr_gate_short_exit_reason(bars, pos["stop0"], max_hold=spec["hold"], target=pos["tgt"])
            if res:
                g = -(res[1] - pos["ep"]) / pos["ep"]
                out.append({"gross": g, "net": g - cost, "held": k - pos["sig"], "reason": res[0]})
                pos, blocked = None, k
        if pos is None and k > blocked and cand[k]:
            sig = m.brk20_min_rr_entry_signal(df.iloc[max(0, k + 1 - WINDOW):k + 1], "short", spec["atr"], spec["rr"])
            if sig and sig["stop_loss"] > sig["entry_price"]:
                ep, stop = sig["entry_price"], sig["stop_loss"]
                pos = {"ep": ep, "stop0": stop, "sig": k, "tgt": ep - spec["rr"] * (stop - ep)}
    if pos is not None:
        g = -(closes[-1] - pos["ep"]) / pos["ep"]
        out.append({"gross": g, "net": g - cost, "held": n - 1 - pos["sig"], "reason": "data_end_forced_close"})
    return out


def fetch_tf(m, sym, tf):
    t = TFS[tf]
    raw = m.fetch_ohlc(sym, t["period"], t["fetch"])
    if raw is None or len(raw) == 0:
        return None
    if tf == "4h":
        import resample_4h as r4
        ix = raw.set_index(pd.DatetimeIndex(raw["Date"])) if "Date" in raw.columns else raw
        cols = ["Open", "High", "Low", "Close"] + (["Volume"] if "Volume" in ix.columns else [])
        raw = r4.resample_1h_to_4h(ix[cols])
    return raw.reset_index(drop=True)


def load_frames(m, tf, shard, nshards, limit=None):
    if os.environ.get("SYNTHETIC") == "1":
        return {f"SYN{k}": B.synthetic_frame(k, 400) for k in range(limit or 3)}
    syms = sorted(set(m._load_nse_universe_from_file()))[shard::nshards]
    if limit:
        syms = syms[:limit]
    out = {}
    for s in syms:
        try:
            raw = fetch_tf(m, s, tf)
        except Exception:
            continue
        if raw is not None and len(raw) >= MIN_BARS + 3:
            out[s] = raw
    return out


def run():
    import main as m
    tf = os.environ.get("TF", "4h")
    if tf not in TFS:
        raise ValueError(f"TF must be one of {sorted(TFS)}")
    atrs = parse_atrs(os.environ.get("ATRS") or ",".join(str(a) for a in DEFAULT_ATRS))
    rr = float(os.environ.get("RR") or DEFAULT_RR)
    hold = int(os.environ.get("HOLD") or DEFAULT_HOLD)
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    specs = cell_specs(tf, atrs, rr, hold)
    frames = load_frames(m, tf, shard, nshards, limit)
    aggs = {t: B.agg_new() for t in specs}
    for sym, df in frames.items():
        for t, sp in specs.items():
            try:
                B.agg_add(aggs[t], replay_symbol(m, df, sp, cost))
            except Exception as ex:
                print("ERROR", sym, t, ex)
    res = {"shard": shard, "nshards": nshards, "n_symbols": len(frames), "tf": tf, "bar_hours": TFS[tf]["bar_hours"],
           "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT, "period": TFS[tf]["period"], "fill_model": "signal_close",
           "synthetic": os.environ.get("SYNTHETIC") == "1",
           "note": "bar constants (20/60 lookback, hold) are bars of the candle in use; stop on every trade",
           "cells": {t: {"spec": specs[t], "raw": a} for t, a in aggs.items()}}
    os.makedirs("out", exist_ok=True)
    path = f"out/gts_{tf}_s{shard}.json"
    json.dump(res, open(path, "w"), indent=1)
    for t, a in aggs.items():
        mt = B.agg_metrics(a)
        print(t, "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    print("wrote", path)


def merge(d):
    tags, meta = {}, {}
    for f in sorted(glob.glob(os.path.join(d, "gts_*_s*.json"))):
        r = json.load(open(f))
        for t, c in r["cells"].items():
            e = tags.setdefault(t, {"spec": c["spec"], "agg": B.agg_new(), "n_symbols": 0, "shards": 0, "bh": r["bar_hours"]})
            B.agg_merge(e["agg"], c["raw"])
            e["n_symbols"] += r["n_symbols"]
            e["shards"] += 1
        meta = {k: r[k] for k in ("fill_model", "cost_round_trip_pct", "synthetic", "note")}
    rows = []
    for t, e in sorted(tags.items()):
        mt = B.agg_metrics(e["agg"])
        mt["avg_held_hours"] = round(mt["avg_held_bars"] * e["bh"], 1)
        rows.append({"tag": t, "spec": e["spec"], "n_symbols": e["n_symbols"], "shards": e["shards"], "metrics": mt})
    out = {**meta, "rows": rows}
    json.dump(out, open(os.path.join(d, "gts_all.json"), "w"), indent=1)
    for r in rows:
        mt = r["metrics"]
        print(r["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"],
              "hold_bars", mt["avg_held_bars"], mt["exit_reasons"])
    return out


def plan(env=None):
    e = env if env is not None else os.environ
    ns = {"4h": int(e.get("NSHARDS_4H", "8")), "15m": int(e.get("NSHARDS_15M", "16")), "5m": int(e.get("NSHARDS_5M", "24"))}
    return {"include": [{"tf": tf, "shard": s, "nshards": n} for tf, n in ns.items() for s in range(n)]}


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == "plan":
        print(json.dumps(plan()))
    else:
        run()
