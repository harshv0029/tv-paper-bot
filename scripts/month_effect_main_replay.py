"""B-965: full-universe replay of the MONTH-EFFECT SHORT cells through the REAL main.py functions
(main.month_effect_short_entry_signal / month_effect_short_stop / month_effect_short_exit_reason).

Two readings per cell (INTERVAL env, one per run):
  15m (60d, yfinance limit): the registry cells' own timeframe. NOTE this window holds exactly ONE September-1 event per
      symbol (or none), so n ~ number of symbols and the result is a single-market-day sample, not a repeated edge.
  1d  (5y): the same rule on daily bars (first trading day of September, hold in trading days) = 5 September events per
      symbol. Bar-count constants change meaning with the candle size (25 x 15m bars = 1 session; on 1d the hold is H//25
      sessions). These are a DIFFERENT candle size, so they are reported under their own 1d tags (never merged with 15m).
Fill model: entry = open of the bar after the signal bar (the pattern_lab / registry convention); stop gap-aware; timeout at
the close of the hold-th bar. Cost = main.ROUND_TRIP_COST_PCT. Universe = main._load_nse_universe_from_file() (full).
Modes: run (env INTERVAL, SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1 smoke) -> out/month_effect_<tf>_s<shard>.json ;
merge <dir> -> <dir>/month_effect_main_replay_all.json ; plan (env NSHARDS, INTERVALS).
Output rows[].metrics{n,pfnet,...} follow the *main_replay_run_*.json layout main._replay_verified_tags() reads.
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
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import brk20_replay as B  # noqa: E402  (exact-mergeable aggregation helpers)

PERIOD = {"15m": "60d", "1d": "5y"}
PER_DAY = 25


def cell_specs(m, interval):
    """tag -> {atr, hold_bars}: the live cells (15m) or their 1d re-expression (hold in sessions)."""
    out = {}
    for tag, (atr, hold) in m.MONTH_EFFECT_SHORT_CELLS.items():
        if interval == "15m":
            out[tag] = {"atr": atr, "hold": hold}
        else:
            hd = max(1, hold // PER_DAY)
            out[tag.replace("__15m__", "__1d__").replace(f"_h{hold}__", f"_h{hd}__")] = {"atr": atr, "hold": hd}
    return out


def replay_symbol(m, df, spec, cost):
    """One symbol, one cell; non-overlapping. Returns trade dicts {gross, net, held, reason}."""
    n = len(df)
    if n < 40:
        return []
    idx = m._month_effect_bar_times(df)  # B-1396c: same timestamps the live entry reads ("Date" column, IST)
    o = df["Open"].to_numpy(float)
    out, nxt = [], 0
    cand = [i for i in range(16, n - 1) if idx[i].month == m.MONTH_EFFECT_SHORT_MONTH and idx[i - 1].month != idx[i].month]
    for t in cand:
        if t < nxt:
            continue
        sig = m.month_effect_short_entry_signal(df.iloc[:t + 1], spec["atr"])  # REAL main entry
        if not sig:
            continue
        e = t + 1
        ent = float(o[e])
        stop = m.month_effect_short_stop(ent, sig["atr"], spec["atr"])  # REAL main stop; None = no entry
        if not ent or stop is None or stop <= ent or e + spec["hold"] - 1 > n - 1:
            continue
        res = None
        for j in range(e, min(e + spec["hold"] - 1, n - 1) + 1):
            res = m.month_effect_short_exit_reason(df.iloc[:j + 1], e, stop, spec["hold"])  # REAL main exit
            if res:
                break
        if not res:
            continue
        reason, px = res
        g = (ent - px) / ent
        out.append({"gross": g, "net": g - cost, "held": j - e + 1, "reason": reason})
        nxt = j + 1
    return out


INTRADAY_LOOKBACK_DAYS = 59  # B-1396c: yfinance period="60d" for 15m resolved to ~70 days and Yahoo rejected it
#                               ("must be within the last 60 days"), so 15m is fetched by explicit start/end instead.


def synthetic_frame(interval):
    """fetch_ohlc-shaped frame (RangeIndex + "Date" column) that CONTAINS a September-1 month-start event."""
    if interval == "15m":
        days = pd.bdate_range("2026-08-17", "2026-09-30")
        ts = [d + pd.Timedelta(hours=9, minutes=15) + pd.Timedelta(minutes=15 * k) for d in days for k in range(25)]
        idx = pd.DatetimeIndex(ts).tz_localize("Asia/Kolkata")
    else:
        idx = pd.bdate_range("2021-01-01", periods=1300)
    rng = np.random.default_rng(1)
    c = 100 + np.cumsum(rng.normal(0, 0.3, len(idx)))
    return pd.DataFrame({"Date": idx, "Open": c, "High": c + 0.5, "Low": c - 0.5, "Close": c, "Volume": 1000.0})


def fetch_frame(m, sym, interval):
    """1d -> main.fetch_ohlc (the live fetch). 15m -> yfinance start/end inside the 60-day limit, normalised to the
    same fetch_ohlc shape (RangeIndex + "Date" column, OHLC NaN rows dropped)."""
    if interval != "15m":
        return m.fetch_ohlc(sym, PERIOD[interval], interval)
    import yfinance as yf
    end = pd.Timestamp.now("UTC")
    df = yf.download(sym, start=(end - pd.Timedelta(days=INTRADAY_LOOKBACK_DAYS)).to_pydatetime(),
                     end=end.to_pydatetime(), interval="15m", progress=False)
    if df is None or df.empty:
        raise RuntimeError(f"no 15m data for {sym}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    date_col = "Date" if "Date" in df.columns else "Datetime"
    return df.rename(columns={date_col: "Date"}).dropna(subset=["Open", "High", "Low", "Close"]).reset_index(drop=True)


def load_frames(m, interval, shard, nshards, limit=None):
    if os.environ.get("SYNTHETIC") == "1":
        return {"SYN0": synthetic_frame(interval)}
    syms = sorted(set(m._load_nse_universe_from_file()))[shard::nshards]
    if limit:
        syms = syms[:limit]
    out, fails = {}, 0
    for s in syms:
        try:
            raw = fetch_frame(m, s, interval)
        except Exception as ex:
            fails += 1
            if fails <= 3:
                print("FETCH_FAIL", s, interval, str(ex)[:200])
            continue
        if raw is not None and len(raw) >= 40:
            out[s] = raw
    print(f"fetched {len(out)}/{len(syms)} symbols ({fails} failed) interval={interval}")
    return out


def run():
    import main as m
    interval = os.environ.get("INTERVAL", "1d")
    if interval not in PERIOD:
        raise SystemExit(f"bad INTERVAL {interval}")
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    specs = cell_specs(m, interval)
    frames = load_frames(m, interval, shard, nshards, limit)
    aggs = {t: B.agg_new() for t in specs}
    for sym, df in frames.items():
        for t, sp in specs.items():
            try:
                B.agg_add(aggs[t], replay_symbol(m, df, sp, cost))
            except Exception as ex:
                print("ERROR", sym, t, ex)
    res = {"shard": shard, "nshards": nshards, "n_symbols": len(frames), "interval": interval, "period": PERIOD[interval],
           "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT, "synthetic": os.environ.get("SYNTHETIC") == "1",
           "note": "entry=next-bar open; bar constants are bars of the stated candle; 15m window holds ONE Sept-1 event",
           "cells": {t: {"spec": specs[t], "raw": a} for t, a in aggs.items()}}
    os.makedirs("out", exist_ok=True)
    path = f"out/month_effect_{interval}_s{shard}.json"
    json.dump(res, open(path, "w"), indent=1)
    for t, a in aggs.items():
        mt = B.agg_metrics(a)
        print(t, "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    print("wrote", path)


def merge(d):
    tags, meta = {}, {}
    for f in sorted(glob.glob(os.path.join(d, "month_effect_*_s*.json"))):
        r = json.load(open(f))
        for t, c in r["cells"].items():
            e = tags.setdefault(t, {"spec": c["spec"], "agg": B.agg_new(), "n_symbols": 0, "shards": 0, "interval": r["interval"]})
            B.agg_merge(e["agg"], c["raw"])
            e["n_symbols"] += r["n_symbols"]
            e["shards"] += 1
        meta = {k: r[k] for k in ("cost_round_trip_pct", "synthetic", "note")}
    rows = []
    for t, e in sorted(tags.items()):
        mt = B.agg_metrics(e["agg"])
        bar_h = 0.25 if e["interval"] == "15m" else 6.25  # B-1030: 1d bar = 6.25 market hours (was 24.0)
        mt["avg_held_hours"] = round(mt["avg_held_bars"] * bar_h, 1)
        rows.append({"tag": t, "spec": e["spec"], "interval": e["interval"], "n_symbols": e["n_symbols"],
                     "shards": e["shards"], "metrics": mt})
    out = {**meta, "rows": rows}
    json.dump(out, open(os.path.join(d, "month_effect_main_replay_all.json"), "w"), indent=1)
    # B-1396b: the artifact is not downloadable by the coordinator, so the merged result is also printed on ONE log line
    # in the layout main._replay_verified_tags() reads (commit as docs/backtest_data/month_effect_main_replay_run_<id>.json).
    print("RESULTS_JSON: " + json.dumps(results_json(out, os.environ.get("GITHUB_RUN_ID")), separators=(",", ":")))
    for r in rows:
        mt = r["metrics"]
        print(r["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"],
              "hold_bars", mt["avg_held_bars"], mt["exit_reasons"])
    total = sum((r["metrics"].get("n") or 0) for r in rows)
    if total == 0:
        # B-1396c: run 40572995313 "succeeded" with n=0 in every cell (nothing was tested). A silent zero never passes.
        raise SystemExit(f"FAIL: total n=0 across {len(rows)} cells - the replay tested nothing (fetch/signal bug)")
    return out


def results_json(merged, run_id=None):
    """Merged replay -> the *main_replay_run_*.json layout: {"run_id", "source", "rows": [{"tag", "metrics", ...}]}.
    Every measured field is kept (n, pfnet, pfgross, win_pct, avg_held_hours, avg_held_bars, avg_net/gross_pct,
    exit_reasons) plus each row's interval/spec/n_symbols/shards; 15m and 1d rows stay separate tags (never merged)."""
    try:
        rid = int(run_id) if run_id not in (None, "") else None
    except (TypeError, ValueError):
        rid = None
    rows = []
    for r in merged.get("rows", []):
        mt = dict(r.get("metrics") or {})
        for k in ("n", "pfnet", "pfgross", "win_pct", "avg_held_hours"):
            mt.setdefault(k, None)
        rows.append({"tag": r["tag"], "interval": r.get("interval"), "spec": r.get("spec"),
                     "n_symbols": r.get("n_symbols"), "shards": r.get("shards"), "metrics": mt})
    return {"run_id": rid,
            "source": "scripts/month_effect_main_replay.py via .github/workflows/month-effect-main-replay.yml "
                      "(B-965/B-1396b): real main.month_effect_short_entry_signal/_stop/_exit_reason, full NSE universe "
                      "(main._load_nse_universe_from_file), entry=next-bar open, gap-aware stop, cost "
                      f"{merged.get('cost_round_trip_pct')}% round trip",
            "cost_round_trip_pct": merged.get("cost_round_trip_pct"), "synthetic": merged.get("synthetic"),
            "note": merged.get("note"), "rows": rows}


def plan(env=None):
    e = env if env is not None else os.environ
    ns = int(e.get("NSHARDS", "8"))
    ivs = [x.strip() for x in e.get("INTERVALS", "1d,15m").split(",") if x.strip()]
    for i in ivs:
        if i not in PERIOD:
            raise SystemExit(f"bad interval {i}")
    return {"include": [{"interval": i, "shard": s, "nshards": ns} for i in ivs for s in range(ns)]}


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == "plan":
        print(json.dumps(plan()))
    else:
        run()
