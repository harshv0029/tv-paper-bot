"""Elder batch-3 main.py-function replay (backlog B-1472 b).

ENTRY and EXIT decisions are the REAL main.elder_b3_last_bar_signals / main.elder_b3_entry_signal /
main.elder_b3_initial_stop / main.elder_b3_exit_reason, called bar by bar on df[:t+1] (never a reimplementation;
the driver only supplies the bar loop and the fill). Conventions = scripts/elder_batch3_research.sim2: signal at
the CLOSE of bar s, fill at the OPEN of bar s+1, stop = fill -/+ atr_mult x ATR14(signal bar), one position per
symbol per tag (a new signal is taken from the exit bar on), a trade touching a bad bar (B-864 guard) is dropped
(entry-bar glitch: skipped without blocking later signals, as sim2). Cost = main.ROUND_TRIP_COST_PCT/100 (0.8%).
Universe = main._load_nse_universe_from_file() (full, NOT main.NSE_FULL_UNIVERSE), 1d, 5y yfinance.

Families (FAMILY env; blank = all): osc_div (div_class kb rsi/macdh), osc_rev (reversal rsi lo30/hi70),
chan_ptl (pivot_tl_break w3/w5). Every tag = (source, long|short, ATR 1.5/2/3), variant suffix "_mr".

Modes (argv[1]):
  run    env: FAMILY, SHARD, NSHARDS, INTERVAL (1d), PERIOD (5y), SYMBOL_LIMIT, SYNTHETIC=1 (offline smoke, NOT a
         result) -> out/eb3_<family>_s<shard>.json (raw exact-mergeable sums)
  merge  python3 scripts/elder_b3_main_replay.py merge DIR [OUT.json] (default docs/elder_b3_main_replay_rows.json)
"""
import glob
import json
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brk20_replay as br  # noqa: E402  (exact-mergeable aggregation helpers)

TRADING_HOURS_PER_1D_BAR = 6.25
MIN_BARS = 120  # research driver skips symbols with < 120 bars
RESEARCH_JSON = os.path.join(ROOT, "docs", "backtest_data", "elder_batch3_n200etf_38211452647_results.json")
REGISTRY_SUFFIX = "_rn38211452647"
DEFAULT_OUT = os.path.join(ROOT, "docs", "elder_b3_main_replay_rows.json")


def families(m, spec=""):
    keys = [f.strip() for f in (spec or "").split(",") if f.strip()] or list(m.ELDER_B3_FAMILY_SOURCES)
    bad = [k for k in keys if k not in m.ELDER_B3_FAMILY_SOURCES]
    if bad:
        raise SystemExit(f"unknown families {bad}; choose from {list(m.ELDER_B3_FAMILY_SOURCES)}")
    return keys


def tags_for_sources(m, sources):
    return [t for t, (s, _d, _a) in m.ELDER_B3_TAG_INFO.items() if s in sources]


def prep(raw):
    df = raw.copy()
    if "Date" in df.columns:
        df = df.sort_values("Date")
    df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"]).reset_index(drop=True)
    for k in ("Open", "High", "Low", "Close", "Volume"):
        df[k] = df[k].astype(float)
    return df


def collect_signals(m, df, source):
    """{bar s: {'long': bool, 'short': bool}} from the REAL main.elder_b3_last_bar_signals on df[:s+1]."""
    out = {}
    for s in range(1, len(df) - 1):
        r = m.elder_b3_last_bar_signals(df.iloc[:s + 1], source)
        if r["long"] or r["short"]:
            out[s] = r
    return out


def simulate_tag(m, df, tag, sig_bars, cost):
    """FIFO trades for one tag. sig_bars: sorted bars where the tag's direction fired. -> (trades, n_dropped_bad)."""
    _src, direction, _am = m.ELDER_B3_TAG_INFO[tag]
    d = 1 if direction == "long" else -1
    o, c = df["Open"].to_numpy(float), df["Close"].to_numpy(float)
    n = len(df)
    trades, free, dropped = [], 0, 0
    for s in sig_bars:
        if s < free or s + 1 >= n:
            continue
        sig = m.elder_b3_entry_signal(df.iloc[:s + 1], tag)
        if sig is None:
            continue
        e = s + 1
        px = float(o[e])
        stop = m.elder_b3_initial_stop(px, sig)
        if stop is None:
            continue
        exit_px, reason, j = None, None, e
        for j in range(e, n):
            reason, exit_px = m.elder_b3_exit_reason(df.iloc[:j + 1], tag, e, px, stop)
            if reason:
                break
        if reason == "bad_bar":
            if j == e:  # sim2: a corrupt entry bar is skipped and does NOT block later signals
                continue
            dropped += 1
            free = j
            continue
        if not reason:
            exit_px, reason, j = float(c[n - 1]), "data_end", n - 1
        g = d * (exit_px - px) / px
        trades.append({"gross": float(g), "net": float(g - cost), "held": int(j - e + 1), "reason": reason,
                       "entry_i": int(e)})
        free = j
    return trades, dropped


def replay_symbol(m, df, sources, cost):
    """{tag: (trades, dropped)} for one symbol; signals computed once per source (both directions)."""
    out = {}
    for src in sources:
        sigs = collect_signals(m, df, src)
        for tag in tags_for_sources(m, (src,)):
            direction = m.ELDER_B3_TAG_INFO[tag][1]
            out[tag] = simulate_tag(m, df, tag, sorted(k for k, v in sigs.items() if v[direction]), cost)
    return out


def synthetic_frame(seed, n=400):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.02, n)) + 0.15 * np.sin(np.arange(n) / 9.0))
    o = c * (1 + rng.normal(0, 0.004, n))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.006, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.006, n)))
    v = rng.integers(1e5, 9e5, n).astype(float)
    d = pd.bdate_range("2021-01-01", periods=n)
    return pd.DataFrame({"Date": d.strftime("%Y-%m-%d"), "Open": o, "High": hi, "Low": lo, "Close": c, "Volume": v})


def load_symbols(m, shard, nshards, limit=None):
    syms = sorted(set(m._load_nse_universe_from_file()))[shard::nshards]
    return syms[:limit] if limit else syms


def run():
    import main as m
    fams = families(m, os.environ.get("FAMILY", ""))
    interval = os.environ.get("INTERVAL", "1d")
    period = os.environ.get("PERIOD", "5y")
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    synthetic = os.environ.get("SYNTHETIC") == "1"
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    sources = [s for f in fams for s in m.ELDER_B3_FAMILY_SOURCES[f]]
    tags = tags_for_sources(m, sources)
    aggs = {t: br.agg_new() for t in tags}
    dropped = {t: 0 for t in tags}
    syms = [f"SYN{k}" for k in range(limit or 3)] if synthetic else load_symbols(m, shard, nshards, limit)
    fetched, t0 = [], time.time()
    for k, sym in enumerate(syms):
        try:
            raw = synthetic_frame(k) if synthetic else m.fetch_ohlc(sym, period, interval)
            if raw is None or len(raw) < MIN_BARS:
                continue
            df = prep(raw)
            if len(df) < MIN_BARS:
                continue
            res = replay_symbol(m, df, sources, cost)
        except Exception as ex:
            print("ERROR", sym, ex)
            continue
        fetched.append(sym)
        for t, (trs, nd) in res.items():
            br.agg_add(aggs[t], trs)
            dropped[t] += nd
        if (k + 1) % 50 == 0:
            print(f"{k + 1}/{len(syms)} symbols, {time.time() - t0:.0f}s", flush=True)
    out = {"families": fams, "interval": interval, "period": period, "shard": shard, "nshards": nshards,
           "universe_slots": len(syms), "n_symbols": len(fetched), "fetched_symbols": fetched,
           "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT, "synthetic": synthetic,
           "cells": {t: {"raw": aggs[t], "dropped_bad_bar": dropped[t]} for t in tags}}
    os.makedirs("out", exist_ok=True)
    path = f"out/eb3_{'-'.join(fams)}_s{shard}.json"
    json.dump(out, open(path, "w"), indent=1)
    for t in tags:
        mt = br.agg_metrics(aggs[t])
        print(t, "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    print("wrote", path)


def _research_rows():
    try:
        return {r["tag"]: r for r in json.load(open(RESEARCH_JSON))["rows"]}
    except Exception:
        return {}


def merge(d, out_path=None):
    tags, meta, fetched, slots = {}, {}, set(), 0
    for f in sorted(glob.glob(os.path.join(d, "**", "eb3_*_s*.json"), recursive=True)):
        r = json.load(open(f))
        fetched.update(r.get("fetched_symbols") or [])
        slots += r.get("universe_slots", 0)
        for t, c in r["cells"].items():
            e = tags.setdefault(t, {"agg": br.agg_new(), "dropped_bad_bar": 0, "shards": 0})
            br.agg_merge(e["agg"], c["raw"])
            e["dropped_bad_bar"] += c.get("dropped_bad_bar", 0)
            e["shards"] += 1
        meta = {k: r[k] for k in ("interval", "period", "cost_round_trip_pct", "synthetic")}
    research = _research_rows()
    rows = []
    for t, e in sorted(tags.items()):
        mt = br.agg_metrics(e["agg"])
        rtag = t.replace("_mr__", "__", 1)
        rr = research.get(rtag) or {}
        rows.append({
            "tag": t, "research_tag": rtag, "registry_tag": rtag[:-len("__v1")] + REGISTRY_SUFFIX + "__v1",
            "research_pfnet": rr.get("pfnet"), "research_n": rr.get("n"),
            "pfnet": mt["pfnet"], "pfgross": mt["pfgross"], "win_pct": mt["win_pct"], "n": mt["n"],
            "avg_net_pct": mt["avg_net_pct"], "avg_held_bars": mt["avg_held_bars"],
            "avg_held_hrs": round(mt["avg_held_bars"] * TRADING_HOURS_PER_1D_BAR, 2),
            "exit_reasons": mt["exit_reasons"], "dropped_bad_bar": e["dropped_bad_bar"], "shards": e["shards"]})
    out = {**meta, "symbols_fetched": len(fetched), "universe_slots": slots,
           "universe": "main._load_nse_universe_from_file() (full NSE universe)",
           "note": ("Calls main.elder_b3_* bar by bar. research_pfnet = run 38211452647 (NIFTY200+182 ETFs, pre-B-864 "
                    "guard, contaminated by a bad-bar trade per B-864) for comparison only. avg_held_hrs = bars x 6.25."),
           "rows": rows}
    json.dump(out, open(out_path or DEFAULT_OUT, "w"), indent=1)
    print(f"symbols fetched {len(fetched)} of {slots} slots")
    for r in rows:
        print(r["tag"], "n", r["n"], "pfnet", r["pfnet"], "pfgross", r["pfgross"], "win", r["win_pct"],
              "hold_h", r["avg_held_hrs"], "research", r["research_pfnet"], "dropped", r["dropped_bad_bar"],
              {k: v["n"] for k, v in r["exit_reasons"].items()})
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        run()
