"""B-1210: Minervini cup 3C cheat 1h LONG, 9 cells: full-universe replay that CALLS the real main.py functions.

ENTRY / EXIT are main.cup_cheat_3c_fires / main.cup_cheat_3c_entry_signal(df, tag) and main.cup_cheat_3c_exit_reason(df,
entry_pos, stop, hold) over main.CUP_CHEAT_1H_CELLS (ATR 2.5/4/6 x hold 6/18/30; every cell has an ATR14 stop; atrnone not
ported). Universe = main._load_nse_universe_from_file() (full). Cost = main.ROUND_TRIP_COST_PCT/100 (0.8%). Signal on the CLOSE
of bar k, fill at that close, exits from bar k+1, strict FIFO per symbol per tag (same convention as the envelope replay).
Glitch bars cleaned via scripts/bar_hygiene.py (count in output). DATA LIMIT: yfinance 1h is capped at 730 days (~2 years);
bar constants are HOURLY bars. Cheap EXACT precondition: the rule requires close > max high of the prior 6 bars, so bars
failing that skip the real function; the tag-independent real rule main.cup_cheat_3c_fires runs once per candidate bar and the
per-tag entry function only where it fires. LONG only: the inverted-cup SHORT mirror is a separate tag family (see
scripts/cup_cheat_short_research.py, main.py port owed). Tags are the registry tags `base__cup_cheat_3c__long__1h__atr<k>_h<N>__v1`
with ALL raw metrics. Validation only: wires nothing, no kill switch.

DIRECTION=short (B-1190/B-1210, 2026-10-23 IST): the inverted-cup / cheat SHORT mirror, RESEARCH-SIDE because main.py has no
short cup-cheat function. Entry/exit come from scripts/cup_cheat_short_research.py (long rule on the reciprocal series, sell
short at the signal close, buy-to-cover stop = entry + k x ATR14 always above entry, gap-aware stop at max(stop, open), else the
hold-th close). Same 9 (ATR, hold) cells, own tags `base__cup_cheat_3c__short__1h__atr<k>_h<N>__v1`, same universe/cost/FIFO
(no averaging: one open trade per symbol per tag). Short gross = (entry - exit) / entry. Exact prefilter mirrored: close below
the min LOW of the prior 6 bars.

  run    env: DIRECTION (long|short, default long), SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1 (offline smoke, NOT a result)
         -> out/cupcheat_s<shard>.json (long) or out/cupcheat_short_s<shard>.json (short)
  merge  python3 scripts/cup_cheat_main_replay.py merge DIR [OUT.json]
         (commit as docs/backtest_data/cup_cheat_main_replay_run_<run id>.json)
"""
import glob
import json
import os
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bar_hygiene as bh  # noqa: E402
import brk20_replay as br  # noqa: E402
import chan_shape_macddiv_main_replay as base  # noqa: E402
import cup_cheat_short_research as short_rule  # noqa: E402

MIN_BARS = 71
INTERVAL = ("1h", "730d")
DIRECTIONS = ("long", "short")


def _rule(m, direction):
    """(cells, fires, entry_signal, exit_reason) for a direction. long = real main.py functions; short = research mirror."""
    if direction == "long":
        return m.CUP_CHEAT_1H_CELLS, m.cup_cheat_3c_fires, m.cup_cheat_3c_entry_signal, m.cup_cheat_3c_exit_reason
    if direction == "short":
        return (short_rule.CUP_CHEAT_SHORT_1H_CELLS, short_rule.cup_cheat_short_fires_df,
                short_rule.cup_cheat_short_entry_signal, short_rule.cup_cheat_short_exit_reason)
    raise ValueError(f"direction must be one of {DIRECTIONS}: {direction!r}")


def _candidates(df, direction="long"):
    """Exact necessary condition of the rule: long = close above the max high of the prior 6 bars; short (reciprocal
    mirror) = close below the min low of the prior 6 bars."""
    h, l, c = (df[x].to_numpy(float) for x in ("High", "Low", "Close"))
    n = len(c)
    out = np.zeros(n, bool)
    if n < 8:
        return out
    if direction == "short":
        ls = np.lib.stride_tricks.sliding_window_view(l, 6).min(axis=1)  # ls[j] = min l[j..j+5]
        out[6:] = c[6:] < ls[:n - 6]
    else:
        hs = np.lib.stride_tricks.sliding_window_view(h, 6).max(axis=1)  # hs[j] = max h[j..j+5]
        out[6:] = c[6:] > hs[:n - 6]
    return out


def _trade(ep, xp, held, reason, cost, entry_i, exit_i, direction="long"):
    g = (xp - ep) / ep if direction == "long" else (ep - xp) / ep
    return {"gross": g, "net": g - cost, "held": held, "reason": reason, "entry_i": entry_i, "exit_i": exit_i}


def cup_trade(m, df, k, sig, tag, cost, direction="long"):
    cells, _fires, _entry, exit_fn = _rule(m, direction)
    n = len(df)
    _kmult, hold = cells[tag]
    ep, stop0 = sig["entry_price"], sig["stop_loss"]
    for j in range(k + 1, n):
        res = exit_fn(df.iloc[:j + 1], k, stop0, hold)
        if res:
            return _trade(ep, res[1], j - k, res[0], cost, k + 1, j, direction)
    return _trade(ep, float(df["Close"].iloc[-1]), n - 1 - k, "data_end_forced_close", cost, k + 1, n - 1, direction)


def replay_symbol(m, df, tags, cost, direction="long"):
    """Strict FIFO per symbol per tag: a new entry only after the previous trade's exit bar (no averaging, no pyramiding)."""
    _cells, fires, entry_fn, _exit = _rule(m, direction)
    df = df.reset_index(drop=True)
    n = len(df)
    out = {t: [] for t in tags}
    if n < MIN_BARS + 3:
        return out
    cand = _candidates(df, direction)
    free = {t: 0 for t in tags}
    for k in np.flatnonzero(cand[:n - 1]):
        k = int(k)
        if k < MIN_BARS - 1:
            continue
        sub = df.iloc[:k + 1]
        if not fires(sub):
            continue
        for tag in tags:
            if k < free[tag]:
                continue
            sig = entry_fn(sub, tag)
            if not sig:
                continue
            tr = cup_trade(m, df, k, sig, tag, cost, direction)
            out[tag].append(tr)
            free[tag] = tr["exit_i"] + 1
    return out


def run():
    import main as m
    direction = os.environ.get("DIRECTION", "long").strip().lower() or "long"
    cells = _rule(m, direction)[0]
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    tags = list(cells)
    frames, dropped = bh.clean_frames(base.load_frames(m, "macddiv", shard, nshards, limit))  # 1h / 730d loader
    aggs = {t: br.agg_new() for t in tags}
    for sym, df in frames.items():
        try:
            res = replay_symbol(m, df, tags, cost, direction)
        except Exception as ex:
            print("ERROR", sym, ex)
            continue
        for t, trs in res.items():
            br.agg_add(aggs[t], trs)
    out = {"family": "cup_cheat", "interval": INTERVAL[0], "period": INTERVAL[1], "shard": shard, "nshards": nshards,
           "n_symbols": len(frames), "bars_dropped_glitch": dropped, "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT,
           "synthetic": os.environ.get("SYNTHETIC") == "1", "direction": direction,
           "rule_source": ("main.py (cup_cheat_3c_*)" if direction == "long"
                           else "research-side scripts/cup_cheat_short_research.py (main.py has no short port)"),
           "note": "yfinance 1h capped at 730d; hold/bar constants are HOURLY bars",
           "cells": {t: {"raw": a} for t, a in aggs.items()}}
    os.makedirs("out", exist_ok=True)
    path = f"out/cupcheat_s{shard}.json" if direction == "long" else f"out/cupcheat_short_s{shard}.json"
    json.dump(out, open(path, "w"), indent=1)
    for t, a in aggs.items():
        mt = br.agg_metrics(a)
        print(t, "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    print("wrote", path)


def merge(d, out_path=None):
    tags, meta, dropped = {}, {}, 0
    for f in sorted(glob.glob(os.path.join(d, "**", "*_s*.json"), recursive=True)):
        r = json.load(open(f))
        if "cells" not in r:
            continue
        dropped += r.get("bars_dropped_glitch", 0)
        for t, c in r["cells"].items():
            e = tags.setdefault(t, {"agg": br.agg_new(), "n_symbols": 0, "shards": 0})
            br.agg_merge(e["agg"], c["raw"])
            e["n_symbols"] += r["n_symbols"]
            e["shards"] += 1
        meta = {k: r[k] for k in ("family", "interval", "period", "cost_round_trip_pct", "synthetic", "direction", "note")}
        meta["rule_source"] = r.get("rule_source", "main.py (cup_cheat_3c_*)")
    rows = []
    for t, e in sorted(tags.items()):
        rows.append({"tag": t, "n_symbols": e["n_symbols"], "shards": e["shards"], "metrics": br.agg_metrics(e["agg"])})
    out = {**meta, "bars_dropped_glitch": dropped, "rows": rows,
           "note2": "avg_held_bars are 1h bars; schema read by main._replay_verified_tags"}
    json.dump(out, open(out_path or os.path.join(d, "replay_all.json"), "w"), indent=1)
    for r in rows:
        mt = r["metrics"]
        print(r["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"],
              "hold_bars", mt["avg_held_bars"], mt["exit_reasons"])
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        run()
