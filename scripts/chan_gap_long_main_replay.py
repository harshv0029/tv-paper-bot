"""chan_gap BUY-ON-GAP LONG 1d main.py-function replay (backlog B-982).

ENTRY / SELECTION / EXIT are the REAL main functions, never a reimplementation:
  main.chan_gap_entry_signal(daily_through_yesterday, open, "long")   (candidate filter + ATR14)
  main.chan_gap_select_top(cands_of_that_day, "long")                 (cross-sectional top-10 rank)
  main.chan_gap_exit_reason(day_bar, entry, stop, "long")             (stop else close)
Tags = main.CHAN_GAP_LONG_CELLS (atr4d0 / atr2d5 / atr1d5, each its own tag). Same-day trade: entry = the day's open (the
research convention), exit = stop or close; the live 15:10 flatten and late-visit entry price are NOT modelled here (stated in
the result). Cost = main.ROUND_TRIP_COST_PCT/100. Universe = main._load_nse_universe_from_file() (full, NOT
main.NSE_FULL_UNIVERSE). The top-10 rank needs every symbol of a day, so shards emit each day's candidates and the merge step
ranks per date (real chan_gap_select_top) and aggregates. LONG only: the short mirror is its own tag family (owed).

  run    env: SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1 (offline smoke, NOT a result) -> out/chan_gap_s<shard>.json
  merge  python3 scripts/chan_gap_main_replay.py merge DIR [OUT.json] -> rows[] with metrics (schema
         main._replay_verified_tags reads; commit as docs/backtest_data/chan_gap_main_replay_run_<run id>.json)
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
import brk20_replay as br  # noqa: E402

NEED = 92  # CHAN_GAP_STD_WINDOW + 2 completed bars before the trade day
HOURS_PER_BAR = 6.25


def day_candidates(m, df):
    """[(date, signal dict, {tag: (stop, reason, exit_px)})] for every day of one symbol passing the real entry filter."""
    df = df.reset_index(drop=True)
    dates = df["Date"].astype(str).str[:10].to_numpy() if "Date" in df.columns else np.array([str(i) for i in range(len(df))])
    out = []
    for k in range(NEED, len(df)):
        o = float(df["Open"].iloc[k])
        sig = m.chan_gap_entry_signal(df.iloc[:k], o, "long")
        if not sig:
            continue
        bar = df.iloc[k]
        res = {}
        for t, mult in m.CHAN_GAP_LONG_CELLS.items():
            stop = o - mult * sig["atr_at_entry"]
            if not stop > 0:
                continue
            res[t] = (stop,) + tuple(m.chan_gap_exit_reason(bar, o, stop, "long"))
        out.append((dates[k], {k2: sig[k2] for k2 in ("entry_price", "atr_at_entry", "score", "gap")}, res))
    return out


def synthetic_frame(seed, n=400):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0, 0.015, n)
    c = 100 * np.exp(np.cumsum(r))
    o = c * (1 + rng.normal(0, 0.02, n))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    d = pd.bdate_range("2023-01-02", periods=n)
    return pd.DataFrame({"Date": d.strftime("%Y-%m-%d"), "Open": o, "High": hi, "Low": lo, "Close": c,
                         "Volume": rng.integers(2e6, 9e6, n).astype(float)})


def load_frames(m, shard, nshards, limit=None):
    if os.environ.get("SYNTHETIC") == "1":
        return {f"SYN{k}": synthetic_frame(k) for k in range(limit or 4)}
    syms = sorted(set(m._load_nse_universe_from_file()))[shard::nshards]
    if limit:
        syms = syms[:limit]
    out = {}
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, "5y", "1d")
        except Exception:
            continue
        if raw is not None and len(raw) >= NEED + 5:
            out[s] = raw.reset_index(drop=True)
    return out


def run():
    import main as m
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    frames = load_frames(m, shard, nshards, limit)
    cands = []
    for sym, df in frames.items():
        try:
            for d, sig, res in day_candidates(m, df):
                cands.append({"date": d, "symbol": sym, "sig": sig, "res": {t: list(v) for t, v in res.items()}})
        except Exception as ex:
            print("ERROR", sym, ex)
    out = {"family": "chan_gap", "interval": "1d", "period": "5y", "shard": shard, "nshards": nshards,
           "n_symbols": len(frames), "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT,
           "synthetic": os.environ.get("SYNTHETIC") == "1", "direction": "long",
           "short_mirror": "owed: registered as its own tag family, not run here", "candidates": cands}
    os.makedirs("out", exist_ok=True)
    path = f"out/chan_gap_s{shard}.json"
    json.dump(out, open(path, "w"))
    print("wrote", path, "symbols", len(frames), "candidate-days", len(cands))


def merge(d, out_path=None):
    import main as m
    files = sorted(glob.glob(os.path.join(d, "**", "chan_gap_s*.json"), recursive=True))
    cost, nsym, meta, by_date = 0.008, 0, {}, {}
    for f in files:
        r = json.load(open(f))
        nsym += r["n_symbols"]
        cost = r["cost_round_trip_pct"] / 100.0
        meta = {k: r[k] for k in ("family", "interval", "period", "cost_round_trip_pct", "synthetic", "direction",
                                  "short_mirror")}
        for c in r["candidates"]:
            by_date.setdefault(c["date"], {})[c["symbol"]] = c
    aggs = {t: br.agg_new() for t in m.CHAN_GAP_LONG_CELLS}
    for date in sorted(by_date):
        day = by_date[date]
        for s in m.chan_gap_select_top({s: c["sig"] for s, c in day.items()}, "long"):
            ep = day[s]["sig"]["entry_price"]
            for t, v in day[s]["res"].items():
                g = (v[2] - ep) / ep
                br.agg_add(aggs[t], [{"gross": g, "net": g - cost, "held": 1, "reason": v[1]}])
    rows = []
    for t, a in sorted(aggs.items()):
        mt = br.agg_metrics(a)
        mt["avg_held_hours"] = round(mt["avg_held_bars"] * HOURS_PER_BAR, 1)
        rows.append({"tag": t, "n_symbols": nsym, "shards": len(files), "metrics": mt})
    out = {**meta, "note": "entry at the open, exit stop-or-close (no 15:10 flatten / late-entry modelled); schema read by "
           "main._replay_verified_tags", "rows": rows}
    json.dump(out, open(out_path or os.path.join(d, "replay_all.json"), "w"), indent=1)
    for r in rows:
        mt = r["metrics"]
        print(r["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"],
              "hold_h", mt["avg_held_hours"], mt["exit_reasons"])
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        run()
