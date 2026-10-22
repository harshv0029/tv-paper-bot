"""brk20_min_rr main.py-function replay (backlog B-798).

ENTRY and EXIT decisions are the REAL main.brk20_min_rr_entry_signal / main.brk20_min_rr_exit_reason
(never a reimplementation). The driver only supplies the bar loop: signal on the close of bar s, fill at
bar s+1's open (the research convention), one position per symbol at a time, a re-entry may be signalled
on the exit bar itself (research: `s >= free`), forced close at data end. Cost = main.ROUND_TRIP_COST_PCT/100.
Universe = main._load_nse_universe_from_file() (full, NOT main.NSE_FULL_UNIVERSE).

Modes (argv[1]):
  run    env: INTERVAL (1d|4h|1h|15m), DIRECTION (long|short), CELLS (json list of {"atr","rr","be"}; be null =
         no breakeven ratchet), SHARD, NSHARDS, SYMBOL_LIMIT (smoke), SYNTHETIC=1 (offline smoke, NOT a result)
         -> out/brk20_<interval>_<direction>_s<shard>.json holding per-cell RAW SUMS (mergeable exactly).
  merge  python3 scripts/brk20_replay.py merge out/  -> out/brk20_all.json with every metric per tag:
         n, win_pct, pfnet, pfgross, avg_net_pct, avg_gross_pct, avg_held_bars, exit_reasons breakdown.
Bar-count constants (20-bar breakout, 60-bar room, EMA13, 30-bar max hold, ATR14) are in BARS: on 1h/15m
they mean hours/quarter-hours, not days (stated in every output).
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

PERIOD_BY_INTERVAL = {"1d": "5y", "4h": "730d", "1h": "730d", "15m": "60d", "5m": "60d"}  # 4h = 1h x 730d resampled (B-1151)
MIN_BARS = 62  # brk20_min_rr_entry_signal needs 62 bars (60-bar room window + signal bar + 1)


def fmt(v) -> str:
    """Naming grammar number format: integers bare, decimals with 'd' (3.5 -> 3d5)."""
    v = float(v)
    return str(int(v)) if v.is_integer() else str(v).replace(".", "d")


def make_tag(direction: str, interval: str, atr, rr, be=None, universe: str = "full", cost_pct=None) -> str:
    """B-1339: universe=fno (NSE stock-futures underlyings only) is its own variant; a cost override is its
    own param (alphabetical: atr, be, cost, rr), so a futures-cost run never shares a tag with the cash run."""
    params = (f"atr{fmt(atr)}" + (f"_be{fmt(be)}" if be is not None else "")
              + (f"_cost{fmt(cost_pct)}" if cost_pct is not None else "") + f"_rr{fmt(rr)}")
    variant = "main_replay" if universe == "full" else f"main_replay_{universe}"
    return f"brk20_min_rr__{variant}__{direction}__{interval}__{params}__v1"


def universe_symbols(m, universe: str):
    """full = main._load_nse_universe_from_file(); fno = its intersection with nse_fo_chain.STOCK_FO_UNDERLYINGS
    (B-1339: a multi-day short can only be held overnight as a stock future, Kotak rejects NRML cash shorts)."""
    syms = sorted(set(m._load_nse_universe_from_file()))
    if universe == "fno":
        import nse_fo_chain
        fo = set(nse_fo_chain.STOCK_FO_UNDERLYINGS)
        syms = [s for s in syms if s.split(".")[0].upper() in fo]
    elif universe != "full":
        raise SystemExit(f"bad universe {universe}")
    return syms


# ------------------------------------------------------------------ exact-mergeable aggregation
def agg_new():
    return {"n": 0, "wins": 0, "win_net": 0.0, "loss_net": 0.0, "win_gross": 0.0, "loss_gross": 0.0,
            "sum_net": 0.0, "sum_gross": 0.0, "hold_sum": 0, "reasons": {}}


def _bump(a, t):
    a["n"] += 1
    a["hold_sum"] += t["held"]
    a["sum_net"] += t["net"]
    a["sum_gross"] += t["gross"]
    if t["net"] > 0:
        a["wins"] += 1
        a["win_net"] += t["net"]
    else:
        a["loss_net"] += -t["net"]
    if t["gross"] > 0:
        a["win_gross"] += t["gross"]
    else:
        a["loss_gross"] += -t["gross"]


def agg_add(agg, trades):
    for t in trades:
        _bump(agg, t)
        _bump(agg["reasons"].setdefault(t["reason"], {**agg_new(), "reasons": None}), t)


def agg_merge(a, b):
    for k in ("n", "wins", "win_net", "loss_net", "win_gross", "loss_gross", "sum_net", "sum_gross", "hold_sum"):
        a[k] += b[k]
    for r, rb in (b.get("reasons") or {}).items():
        ra = a["reasons"].setdefault(r, {**agg_new(), "reasons": None})
        agg_merge_flat(ra, rb)
    return a


def agg_merge_flat(a, b):
    for k in ("n", "wins", "win_net", "loss_net", "win_gross", "loss_gross", "sum_net", "sum_gross", "hold_sum"):
        a[k] += b[k]


def _pf(w, l):
    return float(w / l) if l > 0 else None  # None = no losses (JSON-safe)


def agg_metrics(a):
    n = a["n"]
    if n == 0:
        return {"n": 0, "win_pct": 0.0, "pfnet": None, "pfgross": None, "avg_net_pct": 0.0,
                "avg_gross_pct": 0.0, "avg_held_bars": 0.0, "exit_reasons": {}}
    return {
        "n": n, "win_pct": round(100.0 * a["wins"] / n, 2),
        "pfnet": _pf(a["win_net"], a["loss_net"]), "pfgross": _pf(a["win_gross"], a["loss_gross"]),
        "avg_net_pct": round(100.0 * a["sum_net"] / n, 4), "avg_gross_pct": round(100.0 * a["sum_gross"] / n, 4),
        "avg_held_bars": round(a["hold_sum"] / n, 2),
        "exit_reasons": {r: {"n": v["n"], "pfnet": _pf(v["win_net"], v["loss_net"]),
                             "win_pct": round(100.0 * v["wins"] / v["n"], 2),
                             "avg_held_bars": round(v["hold_sum"] / v["n"], 2)}
                         for r, v in (a.get("reasons") or {}).items() if v["n"]},
    }


# ------------------------------------------------------------------ replay (calls the real main.py fns)
def replay_symbol(m, df, direction, atr, rr, be, cost):
    """One symbol, one cell. Returns trade dicts {gross, net, held, reason}."""
    df = df.reset_index(drop=True)
    n = len(df)
    if n < MIN_BARS + 3:
        return []
    opens = df["Open"].to_numpy(float)
    closes = df["Close"].to_numpy(float)
    dates = df["Date"].astype(str).to_numpy()
    sgn = 1.0 if direction == "long" else -1.0
    out, pos = [], None
    for k in range(MIN_BARS - 1, n):
        sub = df.iloc[:k + 1]
        if pos is not None:
            reason, px = m.brk20_min_rr_exit_reason(sub, pos["day"], pos["ep"], pos["stop0"], direction, be)
            if reason:
                g = sgn * (px - pos["ep"]) / pos["ep"]
                out.append({"gross": g, "net": g - cost, "held": k - pos["idx"] + 1, "reason": reason})
                pos = None
        if pos is None and k + 1 < n:
            sig = m.brk20_min_rr_entry_signal(sub, direction, atr, rr, entry_price=float(opens[k + 1]))
            if sig:
                pos = {"ep": sig["entry_price"], "stop0": sig["stop_loss"], "day": dates[k + 1], "idx": k + 1}
    if pos is not None:
        g = sgn * (closes[-1] - pos["ep"]) / pos["ep"]
        out.append({"gross": g, "net": g - cost, "held": n - pos["idx"], "reason": "data_end_forced_close"})
    return out


def synthetic_frame(seed, n=700):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0006, 0.017, n)
    c = 100 * np.exp(np.cumsum(r))
    o = c * (1 + rng.normal(0, 0.004, n))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.006, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.006, n)))
    v = rng.integers(1e5, 1e6, n).astype(float)
    d = pd.bdate_range("2021-01-01", periods=n)
    return pd.DataFrame({"Date": d.strftime("%Y-%m-%d"), "Open": o, "High": hi, "Low": lo, "Close": c, "Volume": v})


def fetch_interval(m, sym, interval):
    """yfinance has no 4h: build NSE-session 4h bars from 1h (scripts/resample_4h.py, ~2 bars/day, avg 3.5h). Others fetch directly."""
    if interval != "4h":
        return m.fetch_ohlc(sym, PERIOD_BY_INTERVAL[interval], interval)
    raw = m.fetch_ohlc(sym, "730d", "1h")
    if raw is None or len(raw) == 0:
        return raw
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import resample_4h as r4
    ix = raw.set_index(pd.DatetimeIndex(raw["Date"]))
    out = r4.resample_1h_to_4h(ix[["Open", "High", "Low", "Close"] + (["Volume"] if "Volume" in ix.columns else [])]).copy()
    out.insert(0, "Date", out.index)
    return out.reset_index(drop=True)


def load_frames(m, interval, shard, nshards, limit=None, universe="full"):
    if os.environ.get("SYNTHETIC") == "1":
        return {f"SYN{k}": synthetic_frame(k) for k in range(limit or 5)}
    syms = universe_symbols(m, universe)
    syms = syms[shard::nshards]
    if limit:
        syms = syms[:limit]
    period = PERIOD_BY_INTERVAL[interval]
    out, errs, short = {}, [], 0
    for s in syms:
        try:
            raw = fetch_interval(m, s, interval)
        except Exception as ex:
            errs.append(f"{s}: {type(ex).__name__}: {ex}")
            continue
        if raw is None or len(raw) < MIN_BARS + 3:
            short += 1
            continue
        out[s] = raw.reset_index(drop=True)
    # B-1339: a silent all-fail fetch produced n=0 cells once (run 39853287437); always say why symbols dropped
    print(f"fetch: {len(syms)} symbols, {len(out)} loaded, {short} too short/empty, {len(errs)} errors")
    for e in errs[:5]:
        print("fetch error", e)
    if syms and not out:
        raise SystemExit("no symbol loaded - refusing to write an all-zero result")
    return out


def run():
    import main as m
    interval = os.environ.get("INTERVAL", "1d")
    direction = os.environ.get("DIRECTION", "long")
    cells = json.loads(os.environ.get("CELLS") or '[{"atr":3,"rr":4,"be":null}]')
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    universe = os.environ.get("UNIVERSE") or "full"
    cost_override = float(os.environ["COST_PCT"]) if os.environ.get("COST_PCT") else None
    cost_pct = cost_override if cost_override is not None else m.ROUND_TRIP_COST_PCT
    cost = cost_pct / 100.0
    frames = load_frames(m, interval, shard, nshards, limit, universe)
    tag = lambda c: make_tag(direction, interval, c["atr"], c["rr"], c.get("be"), universe, cost_override)
    aggs = {tag(c): agg_new() for c in cells}
    for sym, df in frames.items():
        for c in cells:
            try:
                trades = replay_symbol(m, df, direction, c["atr"], c["rr"], c.get("be"), cost)
            except Exception as ex:
                print("ERROR", sym, c, ex)
                continue
            agg_add(aggs[tag(c)], trades)
    res = {"interval": interval, "direction": direction, "shard": shard, "nshards": nshards,
           "n_symbols": len(frames), "cost_round_trip_pct": cost_pct, "universe": universe,
           "period": PERIOD_BY_INTERVAL[interval], "synthetic": os.environ.get("SYNTHETIC") == "1",
           "bar_constants_in_bars": {k: getattr(m, k) for k in dir(m) if k.startswith("BRK20_") and k.isupper()},
           "note": "bar-count constants are BARS of this interval (1h/15m: hours/quarter-hours, not days)",
           "cells": {t: {"cell": next(c for c in cells if tag(c) == t),
                         "raw": a} for t, a in aggs.items()}}
    os.makedirs("out", exist_ok=True)
    path = f"out/brk20_{interval}_{direction}_s{shard}.json"
    json.dump(res, open(path, "w"), indent=1)
    for t, a in aggs.items():
        mt = agg_metrics(a)
        print(t, "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    print("wrote", path)


def merge(d):
    tags = {}
    meta = {}
    for f in sorted(glob.glob(os.path.join(d, "brk20_*_s*.json"))):
        r = json.load(open(f))
        for t, c in r["cells"].items():
            e = tags.setdefault(t, {"cell": c["cell"], "interval": r["interval"], "direction": r["direction"],
                                    "agg": agg_new(), "n_symbols": 0, "shards": 0})
            agg_merge(e["agg"], c["raw"])
            e["n_symbols"] += r["n_symbols"]
            e["shards"] += 1
        meta = {k: r.get(k) for k in ("cost_round_trip_pct", "universe", "period", "synthetic", "bar_constants_in_bars", "note")}
    rows = []
    for t, e in sorted(tags.items()):
        rows.append({"tag": t, **{k: e[k] for k in ("cell", "interval", "direction", "n_symbols", "shards")},
                     "metrics": agg_metrics(e["agg"])})
    out = {**meta, "rows": rows}
    json.dump(out, open(os.path.join(d, "brk20_all.json"), "w"), indent=1)
    for r in rows:
        mt = r["metrics"]
        print(r["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"],
              "hold", mt["avg_held_bars"], mt["exit_reasons"])
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2])
    else:
        run()
