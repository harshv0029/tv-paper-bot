"""B-1396d: gaps fade LONG 1d (exhaust + common, atr3 nb5): full-universe replay that CALLS the real main.py functions.

The two tags in main.GAPFADE_TAGS (gaps__exhaust_fade__long__1d__atr3_nb5__v1, gaps__common_fade__long__1d__atr3_nb5__v1)
sit in main.REPLAY_OWED_TAGS (real-money gate closed) until a replay that calls the live functions is on file. This is it.

ENTRY = main.gapfade_long_entry_signal(df.iloc[:k+1], tag) (the exact call _gapfade_try_entry makes in the swing scan; the
ATR stop entry - 3 x ATR(Wilder 14) is ALWAYS attached by that function, no trade without SL).
EXIT  = main._gapfade_exit_adapter(df.iloc[:j+1], entry_day, initial_stop, atr, running_max) (the exact call _run_swing_scan
makes for a GAPFADE_TAGS position), evaluated once per completed daily bar j > k; the reason it returns is the exit.
Live convention: signal on the CLOSE of bar k, fill at that close (the paper row's entry_price), exits from bar k+1.
Exit PRICES (the adapter returns reasons only): gapfade_stop_loss = min(open[j], stop) (gap-aware, the resting SL fills at
the stop or the gap-down open); gapfade_rule_exit and gapfade_max_hold_timeout = close[j]; data end = last close (own reason).
Strict FIFO, non-overlapping per symbol per tag (one open position per symbol, as signal_state_swing). Tags are independent
cells here (each its own registry row); live checks the exhaust tag first, but the rules are mutually exclusive by volume.
Universe = main._load_nse_universe_from_file() (full, NOT main.NSE_FULL_UNIVERSE). Bars = yfinance 1d, 5y. Cost =
main.ROUND_TRIP_COST_PCT/100 (0.8%). Glitch bars cleaned with scripts/bar_hygiene.py (count in output). Cheap EXACT
prefilter: the rule needs a down gap on bar k-5 (High < prior Low) and no Low below that bar's Low on bars k-4..k, so only
those bars call the real function. Validation only: wires nothing, no kill switch.

  run    env: SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1 (offline smoke, NOT a result) -> out/gapfade_s<shard>.json
  merge  python3 scripts/gapfade_main_replay.py merge DIR [OUT.json]
         prints ONE line `RESULTS_JSON: {...}` (rows[].metrics, the schema main._replay_verified_tags reads);
         commit the merged JSON as docs/backtest_data/gapfade_main_replay_run_<run id>.json
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
import bar_hygiene as bh  # noqa: E402
import brk20_replay as br  # noqa: E402

INTERVAL = ("1d", "5y")
MIN_BARS = 30  # warm-up: 5 vol bars + gap bar + 5 nb bars + a settled ATR(14)
SOURCE = ("scripts/gapfade_main_replay.py: real main.gapfade_long_entry_signal + main._gapfade_exit_adapter, "
          "full NSE universe (_load_nse_universe_from_file), yfinance 1d 5y, cost main.ROUND_TRIP_COST_PCT, "
          "fill at signal close, gap-aware stop, FIFO per symbol per tag")


def _dates(df):
    if "Date" in df.columns:
        return pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d").to_numpy()
    return pd.DatetimeIndex(df.index).strftime("%Y-%m-%d").to_numpy()


def _prep(df):
    """RangeIndex frame with a 'YYYY-MM-DD' Date column (what the live exit adapter keys on)."""
    d = df.copy()
    d["Date"] = _dates(df)
    return d.reset_index(drop=True)


def _candidates(df, nb):
    """Exact necessary condition of gapfade_long_entry_signal on bar k: down gap on bar i=k-nb and min(Low[i+1..k]) >= Low[i]."""
    h, l = df["High"].to_numpy(float), df["Low"].to_numpy(float)
    n = len(l)
    out = np.zeros(n, bool)
    if n < nb + 2:
        return out
    gap = np.zeros(n, bool)
    gap[1:] = h[1:] < l[:-1]
    win_min = np.lib.stride_tricks.sliding_window_view(l, nb).min(axis=1)  # win_min[s] = min l[s..s+nb-1]
    for k in range(nb + 1, n):
        i = k - nb
        out[k] = gap[i] and win_min[i + 1] >= l[i]
    return out


def trade_metrics(ep, xp, held, reason, cost, entry_i, exit_i):
    """Per-trade long return: gross = (exit - entry)/entry, net = gross - round-trip cost."""
    g = (float(xp) - float(ep)) / float(ep)
    return {"gross": g, "net": g - cost, "held": int(held), "reason": reason, "entry_i": entry_i, "exit_i": exit_i}


def gapfade_trade(m, df, k, sig, cost):
    n = len(df)
    ep, stop0, atr = sig["entry_price"], sig["stop_loss"], sig["atr_at_entry"]
    entry_day = str(df["Date"].iloc[k])[:10]
    o, c = df["Open"].to_numpy(float), df["Close"].to_numpy(float)
    running = ep
    for j in range(k + 1, n):
        reason, running = m._gapfade_exit_adapter(df.iloc[:j + 1], entry_day, stop0, atr, running)
        if reason:
            xp = min(o[j], stop0) if reason == "gapfade_stop_loss" else c[j]
            return trade_metrics(ep, xp, j - k, reason, cost, k + 1, j)
    return trade_metrics(ep, c[-1], n - 1 - k, "data_end_forced_close", cost, k + 1, n - 1)


def replay_symbol(m, df, tags, cost):
    """Strict FIFO per symbol per tag: a new entry only after the previous trade's exit bar."""
    df = _prep(df)
    n = len(df)
    out = {t: [] for t in tags}
    if n < MIN_BARS + 3:
        return out
    cand = _candidates(df, m.GAPFADE_NBARS)
    free = {t: 0 for t in tags}
    for k in np.flatnonzero(cand[:n - 1]):
        k = int(k)
        if k < MIN_BARS - 1:
            continue
        sub = df.iloc[:k + 1]
        for tag in tags:
            if k < free[tag]:
                continue
            sig = m.gapfade_long_entry_signal(sub, tag)
            if not sig:
                continue
            tr = gapfade_trade(m, df, k, sig, cost)
            out[tag].append(tr)
            free[tag] = tr["exit_i"] + 1
    return out


def metrics(agg):
    """brk20_replay metrics plus avg_held_days (1d bars, so held bars == trading days)."""
    mt = br.agg_metrics(agg)
    mt["avg_held_days"] = mt["avg_held_bars"]
    for v in mt["exit_reasons"].values():
        v["avg_held_days"] = v["avg_held_bars"]
    return mt


def run():
    import main as m
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    tags = list(m.GAPFADE_TAGS)
    frames, dropped = bh.clean_frames(br.load_frames(m, "1d", shard, nshards, limit))  # full universe, 1d / 5y
    aggs = {t: br.agg_new() for t in tags}
    for sym, df in frames.items():
        try:
            res = replay_symbol(m, df, tags, cost)
        except Exception as ex:
            print("ERROR", sym, ex)
            continue
        for t, trs in res.items():
            br.agg_add(aggs[t], trs)
    out = {"family": "gapfade", "interval": INTERVAL[0], "period": INTERVAL[1], "shard": shard, "nshards": nshards,
           "n_symbols": len(frames), "bars_dropped_glitch": dropped, "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT,
           "synthetic": os.environ.get("SYNTHETIC") == "1", "direction": "long",
           "cells": {t: {"raw": a} for t, a in aggs.items()}}
    os.makedirs("out", exist_ok=True)
    path = f"out/gapfade_s{shard}.json"
    json.dump(out, open(path, "w"), indent=1)
    for t, a in aggs.items():
        mt = metrics(a)
        print(t, "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold_days", mt["avg_held_days"])
    print("wrote", path)


def merge(d, out_path=None):
    tags, meta, dropped = {}, {}, 0
    for f in sorted(glob.glob(os.path.join(d, "**", "gapfade_s*.json"), recursive=True)):
        r = json.load(open(f))
        if "cells" not in r:
            continue
        dropped += r.get("bars_dropped_glitch", 0)
        for t, c in r["cells"].items():
            e = tags.setdefault(t, {"agg": br.agg_new(), "n_symbols": 0, "shards": 0})
            br.agg_merge(e["agg"], c["raw"])
            e["n_symbols"] += r["n_symbols"]
            e["shards"] += 1
        meta = {k: r[k] for k in ("family", "interval", "period", "cost_round_trip_pct", "synthetic", "direction")}
    rows = [{"tag": t, "n_symbols": e["n_symbols"], "shards": e["shards"], "metrics": metrics(e["agg"])}
            for t, e in sorted(tags.items())]
    rid = os.environ.get("RUN_ID") or None
    out = {"run_id": int(rid) if rid and rid.isdigit() else rid, "source": SOURCE, **meta,
           "bars_dropped_glitch": dropped, "rows": rows,
           "note": "avg_held_days = 1d bars; schema read by main._replay_verified_tags"}
    json.dump(out, open(out_path or os.path.join(d, "replay_all.json"), "w"), indent=1)
    for r in rows:
        mt = r["metrics"]
        print(r["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"],
              "hold_days", mt["avg_held_days"], mt["exit_reasons"])
    print("RESULTS_JSON: " + json.dumps(out, separators=(",", ":")))
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        run()
