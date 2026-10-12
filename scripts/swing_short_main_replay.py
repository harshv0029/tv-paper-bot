"""B-881: full-universe replay of main.SWINGMINRR_TAGS (VCP gate rr4/rr3/rr2 + base, long 1d) and
main.SHORT_SWING_TAGS (6 brk20 1d short cells) through the REAL main.py functions.

Entry: main.swingminrr_vcp_entry_signal(df, tag) (long) / main.brk20_min_rr_entry_signal(df, 'short', atr, rr) with
the cell params from main.BRK20_SHORT_SWING_CELLS (the exact call main.short_swing_entry_signal makes per cell,
plus its stop>entry check). Exit: main._swingminrr_exit_adapter / main._short_swing_exit_reason, replayed bar by bar.
Universe: main._load_nse_universe_from_file() (full; NOT main.NSE_FULL_UNIVERSE). Cost: main.ROUND_TRIP_COST_PCT.

FILL MODEL (FILL env): 'signal_close' (default, = LIVE: the scan enters at the signal bar's close) or 'next_open'
(research convention). Stop fills are gap-aware (min/max of open and stop, like a resting SL); timeout/rule exits at
the exit bar's close. Each tag is replayed INDEPENDENTLY (own position book per tag, so gate4 <= gate3 <= gate2 <= base
nesting is visible); live "first firing tag owns the symbol" priority is not applied. VCP rs_percentile=None (research
fallback; live passes a cross-sectional RS percentile). No same-bar re-entry (live swing_done_today).
Bar-count constants are BARS of the 1d candle.

Modes: run (env TAGS csv or GROUP long|short, SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1 smoke) ->
out/swingshort_<group>_s<shard>.json ; merge <dir> -> <dir>/swingshort_all.json ; plan (env REPLAY_GROUPS, NSHARDS).
"""
import glob
import json
import os
import sys
import warnings

import numpy as np  # noqa: F401
import pandas as pd  # noqa: F401

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import brk20_replay as B  # noqa: E402  (exact-mergeable aggregation helpers)

PERIOD = "5y"
INTERVAL = "1d"
MIN_BARS = 62


def tag_specs(m):
    """tag -> spec for every tag in main.SWINGMINRR_TAGS + main.SHORT_SWING_TAGS."""
    specs = {t: {"dir": "long", "gate_rr": m._SWINGMINRR_GATE_RR[t]} for t in m.SWINGMINRR_TAGS}
    for t, a, r in m.BRK20_SHORT_SWING_CELLS:
        specs[t] = {"dir": "short", "atr": a, "rr": r}
    return specs


def _exit_price(direction, reason, stop0, o, c):
    if "stop" in reason:
        return min(o, stop0) if direction == "long" else max(o, stop0)
    return c


def replay_symbol(m, df, tag, spec, cost, fill="signal_close", vcp_gate=None):
    """One symbol, one tag. Returns trade dicts {gross, net, held, reason}."""
    df = df.reset_index(drop=True)
    n = len(df)
    if n < MIN_BARS + 3 or "Date" not in df.columns:
        return []
    direction = spec["dir"]
    sgn = 1.0 if direction == "long" else -1.0
    opens, closes = df["Open"].to_numpy(float), df["Close"].to_numpy(float)
    dates = df["Date"].astype(str).str[:10].to_numpy()
    out, pos, blocked = [], None, -1
    for k in range(MIN_BARS - 1, n):
        sub = df.iloc[:k + 1]
        if pos is not None and k > pos["sig"]:
            if direction == "long":
                reason, _ = m._swingminrr_exit_adapter(sub, pos["day"], pos["stop0"], pos["atr"], pos["ep"])
            else:
                reason = m._short_swing_exit_reason(sub, pos["day"], pos["stop0"], pos["atr"], tag)
            if reason:
                px = _exit_price(direction, reason, pos["stop0"], opens[k], closes[k])
                g = sgn * (px - pos["ep"]) / pos["ep"]
                out.append({"gross": g, "net": g - cost, "held": k - pos["sig"], "reason": reason})
                pos, blocked = None, k
        if pos is None and k > blocked:
            if direction == "long":
                sig = m.swingminrr_vcp_entry_signal(sub, tag) if (vcp_gate is None or vcp_gate(sub)) else None
            else:
                sig = m.brk20_min_rr_entry_signal(sub, "short", spec["atr"], spec["rr"])
                if sig and not sig["stop_loss"] > sig["entry_price"]:
                    sig = None
            if sig:
                if fill == "next_open":
                    if k + 1 >= n:
                        continue
                    shift = float(opens[k + 1]) - sig["entry_price"]  # keep the ATR distance, move to the next open
                    ep, stop0 = float(opens[k + 1]), sig["stop_loss"] + shift
                    if (direction == "long" and not 0 < stop0 < ep) or (direction == "short" and not stop0 > ep):
                        continue
                    pos = {"ep": ep, "stop0": stop0, "atr": sig["atr_at_entry"], "day": dates[k], "sig": k + 1}
                else:
                    pos = {"ep": sig["entry_price"], "stop0": sig["stop_loss"], "atr": sig["atr_at_entry"],
                           "day": dates[k], "sig": k}
    if pos is not None:
        g = sgn * (closes[-1] - pos["ep"]) / pos["ep"]
        out.append({"gross": g, "net": g - cost, "held": n - 1 - pos["sig"], "reason": "data_end_forced_close"})
    return out


def load_frames(m, shard, nshards, limit=None):
    if os.environ.get("SYNTHETIC") == "1":
        return {f"SYN{k}": B.synthetic_frame(k) for k in range(limit or 3)}
    syms = sorted(set(m._load_nse_universe_from_file()))[shard::nshards]
    if limit:
        syms = syms[:limit]
    out = {}
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, PERIOD, INTERVAL)
        except Exception:
            continue
        if raw is not None and len(raw) >= MIN_BARS + 3:
            out[s] = raw.reset_index(drop=True)
    return out


def run():
    import main as m
    specs = tag_specs(m)
    group = os.environ.get("GROUP", "long")
    tags = [t.strip() for t in os.environ["TAGS"].split(",")] if os.environ.get("TAGS") else \
        [t for t, s in specs.items() if s["dir"] == group]
    for t in tags:
        if t not in specs:
            raise SystemExit(f"unknown tag {t}")
    fill = os.environ.get("FILL", "signal_close")
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    frames = load_frames(m, shard, nshards, limit)
    aggs = {t: B.agg_new() for t in tags}
    for sym, df in frames.items():
        # exact prefilter: swingminrr_vcp_entry_signal returns None whenever minervini_vcp_entry_signal does (rs=None)
        cache = {}

        def gate(sub, cache=cache):
            return cache.setdefault(len(sub), bool(m.minervini_vcp_entry_signal(sub)))
        for t in tags:
            try:
                tr = replay_symbol(m, df, t, specs[t], cost, fill, gate if specs[t]["dir"] == "long" else None)
            except Exception as ex:
                print("ERROR", sym, t, ex)
                continue
            B.agg_add(aggs[t], tr)
    res = {"shard": shard, "nshards": nshards, "n_symbols": len(frames), "fill_model": fill,
           "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT, "period": PERIOD, "interval": INTERVAL,
           "synthetic": os.environ.get("SYNTHETIC") == "1",
           "note": "tags replayed independently; bar constants are 1d bars; vcp rs_percentile=None",
           "cells": {t: {"spec": specs[t], "raw": a} for t, a in aggs.items()}}
    os.makedirs("out", exist_ok=True)
    path = f"out/swingshort_{group}_s{shard}.json"
    json.dump(res, open(path, "w"), indent=1)
    for t, a in aggs.items():
        mt = B.agg_metrics(a)
        print(t, "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    print("wrote", path)


def merge(d):
    tags, meta = {}, {}
    for f in sorted(glob.glob(os.path.join(d, "swingshort_*_s*.json"))):
        r = json.load(open(f))
        for t, c in r["cells"].items():
            e = tags.setdefault(t, {"spec": c["spec"], "agg": B.agg_new(), "n_symbols": 0, "shards": 0})
            B.agg_merge(e["agg"], c["raw"])
            e["n_symbols"] += r["n_symbols"]
            e["shards"] += 1
        meta = {k: r[k] for k in ("fill_model", "cost_round_trip_pct", "period", "interval", "synthetic", "note")}
    rows = []
    for t, e in sorted(tags.items()):
        mt = B.agg_metrics(e["agg"])
        mt["avg_held_hours"] = round(mt["avg_held_bars"] * 24.0, 1)  # 1d bars: calendar-hour equivalent
        rows.append({"tag": t, "spec": e["spec"], "n_symbols": e["n_symbols"], "shards": e["shards"], "metrics": mt})
    out = {**meta, "rows": rows}
    json.dump(out, open(os.path.join(d, "swingshort_all.json"), "w"), indent=1)
    for r in rows:
        mt = r["metrics"]
        print(r["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"],
              "hold_bars", mt["avg_held_bars"], mt["exit_reasons"])
    return out


def plan(env=None):
    e = env if env is not None else os.environ
    groups = [g.strip() for g in e.get("REPLAY_GROUPS", "long,short").split(",") if g.strip()]
    ns = int(e.get("NSHARDS", "8"))
    for g in groups:
        if g not in ("long", "short"):
            raise SystemExit(f"bad group {g}")
    return {"include": [{"group": g, "shard": s, "nshards": ns} for g in groups for s in range(ns)]}


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == "plan":
        print(json.dumps(plan()))
    else:
        run()
