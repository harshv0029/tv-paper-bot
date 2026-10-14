"""Shared helpers for the B-1090/B-1091 candle-size sweep drivers (research only, nothing here touches main.py).

TFS: per candle size the yfinance period, the fetch interval, and average real hours per bar.
4h = 1h x 730d resampled to NSE-session 4h bars by scripts/resample_4h.py (2 bars/day, avg 3.5h).
prep_frame(): OHLCV frame with a STRING 'Date' column that sorts chronologically ('YYYY-MM-DD' for 1d,
'YYYY-MM-DD HH:MM' IST-naive intraday), as the real main.py exit functions compare dates as strings.
merge_dir(): exact merge of per-shard raw sums (brk20_replay helpers) into rows[].metrics.
"""
import glob
import json
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import brk20_replay as B  # noqa: E402

TFS = {"1d": {"period": "5y", "fetch": "1d", "bar_hours": 6.25},
       "4h": {"period": "730d", "fetch": "1h", "bar_hours": 3.5},
       "1h": {"period": "730d", "fetch": "1h", "bar_hours": 1.0},
       "15m": {"period": "60d", "fetch": "15m", "bar_hours": 0.25},
       "5m": {"period": "60d", "fetch": "5m", "bar_hours": 5 / 60.0}}


def num_token(x):
    """Grammar: decimal point is written 'd' (1.5 -> 1d5, 4.0 -> 4)."""
    return ("%g" % x).replace(".", "d")


def parse_atrs(s, default):
    try:
        out = [float(x) for x in str(s or "").replace(";", ",").split(",") if x.strip()]
    except ValueError:
        raise ValueError("ATR multiples must be numbers (atrnone refused: no trade without a stop)")
    if not out:
        out = list(default)
    if any(a <= 0 for a in out):
        raise ValueError("ATR multiples must be > 0 (no trade without a stop: atrnone refused)")
    return out


def date_strings(ts, tf):
    t = pd.to_datetime(pd.Series(list(ts)))
    if getattr(t.dt, "tz", None) is not None:
        t = t.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    return t.dt.strftime("%Y-%m-%d" if tf == "1d" else "%Y-%m-%d %H:%M").to_numpy()


def prep_frame(raw, tf):
    """raw = main.fetch_ohlc output (has a 'Date' column and/or a datetime index). Returns a reset-index frame
    with string Date; 4h resampled from 1h."""
    if raw is None or len(raw) == 0:
        return None
    ts = raw["Date"] if "Date" in raw.columns else raw.index
    cols = ["Open", "High", "Low", "Close"] + (["Volume"] if "Volume" in raw.columns else [])
    df = raw[cols].copy()
    df.index = pd.DatetimeIndex(pd.to_datetime(pd.Series(list(ts))))
    if tf == "4h":
        import resample_4h as r4
        df = r4.resample_1h_to_4h(df)
        ts = df.index
    df = df.reset_index(drop=True)
    if "Volume" not in df.columns:
        df["Volume"] = 0.0
    df.insert(0, "Date", date_strings(ts, tf))
    return df


def load_frames(m, tf, shard, nshards, min_bars, limit=None, synthetic=None):
    if os.environ.get("SYNTHETIC") == "1":
        return {f"SYN{k}": (synthetic or B.synthetic_frame)(k) for k in range(limit or 3)}
    t = TFS[tf]
    syms = sorted(set(m._load_nse_universe_from_file()))[shard::nshards]
    if limit:
        syms = syms[:limit]
    out = {}
    for s in syms:
        try:
            df = prep_frame(m.fetch_ohlc(s, t["period"], t["fetch"]), tf)
        except Exception:
            continue
        if df is not None and len(df) >= min_bars:
            out[s] = df
    return out


def plan(env, default_shards):
    e = env if env is not None else os.environ
    inc = []
    for tf, d in default_shards.items():
        n = int(e.get("NSHARDS_" + tf.upper(), str(d)))
        inc += [{"tf": tf, "shard": s, "nshards": n} for s in range(n)]
    return {"include": inc}


def merge_dir(d, prefix, out_name):
    tags, meta = {}, {}
    for f in sorted(glob.glob(os.path.join(d, "**", prefix + "_*_s*.json"), recursive=True)):
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
    json.dump(out, open(os.path.join(d, out_name), "w"), indent=1)
    for r in rows:
        mt = r["metrics"]
        print(r["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"],
              "hold_bars", mt["avg_held_bars"], mt["exit_reasons"])
    return out


def write_shard(prefix, tf, shard, nshards, n_symbols, cost_pct, specs, aggs, note):
    res = {"shard": shard, "nshards": nshards, "n_symbols": n_symbols, "tf": tf, "bar_hours": TFS[tf]["bar_hours"],
           "cost_round_trip_pct": cost_pct, "period": TFS[tf]["period"], "fill_model": "signal_close",
           "synthetic": os.environ.get("SYNTHETIC") == "1", "note": note,
           "cells": {t: {"spec": specs[t], "raw": a} for t, a in aggs.items()}}
    os.makedirs("out", exist_ok=True)
    path = f"out/{prefix}_{tf}_s{shard}.json"
    json.dump(res, open(path, "w"), indent=1)
    for t, a in aggs.items():
        mt = B.agg_metrics(a)
        print(t, "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    print("wrote", path)
