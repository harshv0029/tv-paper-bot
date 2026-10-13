"""chan_gap SHORT (short_on_gap) main.py-function replay (backlog B-981).

ENTRY and EXIT decisions are the REAL main functions, never a reimplementation:
  main.chan_gap_entry_signal(df_completed_daily, open_print, "short", atr_mult)  (entry + ATR stop)
  main.chan_gap_select_top rule (per-day top-10 by gap, descending, ties by symbol)
  main.chan_gap_exit_reason(day_bar, entry, stop, "short")                       (stop, else close = flat before 15:10)
The driver only supplies the day loop. Same-day trade: enter at the day's open, exit at the stop or the close. The day's top-10
needs the WHOLE universe, so shards emit per-day candidates (date, symbol, score, gross, reason) and `merge` ranks each day
across all shards. Cost = main.ROUND_TRIP_COST_PCT/100 (0.8%). Universe = main._load_nse_universe_from_file() (full, NOT
main.NSE_FULL_UNIVERSE). Tag = main.CHAN_GAP_SHORT_TAG (atr1.5, top10). The long mirror is its own tag (registered separately).

Modes (argv[1]):
  run    env: SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1 (offline smoke, NOT a result) -> out/chan_gap_short_s<shard>.json
  merge  python3 scripts/chan_gap_main_replay.py merge DIR [OUT.json] -> rows[] with metrics, the schema
         main._replay_verified_tags() reads (commit as docs/backtest_data/chan_gap_main_replay_run_<id>.json).
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

MIN_BARS = 110
LOOKBACK = 110
HOURS_PER_BAR = 6.25
ATR_MULT = 1.5


def day_candidates(m, df, sym):
    """[(date, symbol, score, gross, reason)] for every day the real short signal fires on this symbol."""
    df = df.reset_index(drop=True)
    out = []
    dates = df["Date"].astype(str).to_numpy()
    for k in range(MIN_BARS, len(df)):
        sub = df.iloc[max(0, k - LOOKBACK):k]
        o = float(df["Open"].iloc[k])
        sig = m.chan_gap_entry_signal(sub, o, "short", ATR_MULT)
        if not sig:
            continue
        reason, px = m.chan_gap_exit_reason(df.iloc[k], sig["entry_price"], sig["stop_loss"], "short")
        gross = (sig["entry_price"] - px) / sig["entry_price"]
        out.append([dates[k][:10], sym, sig["score"], gross, reason])
    return out


def synthetic_frame(seed, n=400):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, n)))
    o = c * (1 + rng.normal(0, 0.02, n))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    d = pd.bdate_range("2021-01-01", periods=n)
    return pd.DataFrame({"Date": d.strftime("%Y-%m-%d"), "Open": o, "High": hi, "Low": lo, "Close": c,
                         "Volume": rng.integers(2e6, 9e6, n).astype(float)})


def load_frames(m, shard, nshards, limit=None):
    if os.environ.get("SYNTHETIC") == "1":
        return {f"SYN{k}": synthetic_frame(k) for k in range(limit or 5)}
    syms = sorted(set(m._load_nse_universe_from_file()))[shard::nshards]
    if limit:
        syms = syms[:limit]
    out = {}
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, "5y", "1d")
        except Exception:
            continue
        if raw is not None and len(raw) >= MIN_BARS + 3:
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
            cands += day_candidates(m, df, sym)
        except Exception as ex:
            print("ERROR", sym, ex)
    os.makedirs("out", exist_ok=True)
    path = f"out/chan_gap_short_s{shard}.json"
    json.dump({"tag": m.CHAN_GAP_SHORT_TAG, "interval": "1d", "period": "5y", "shard": shard, "nshards": nshards,
               "n_symbols": len(frames), "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT, "top_n": m.CHAN_GAP_TOP_N,
               "synthetic": os.environ.get("SYNTHETIC") == "1", "direction": "short", "candidates": cands},
              open(path, "w"))
    print("wrote", path, "symbols", len(frames), "candidates", len(cands))


def select_and_aggregate(cands, cost, top_n):
    """Per-day top_n by gap (descending, ties by symbol), the rule main.chan_gap_select_top applies."""
    by_day = {}
    for d, sym, score, gross, reason in cands:
        by_day.setdefault(d, []).append((sym, score, gross, reason))
    agg = br.agg_new()
    for d in sorted(by_day):
        items = sorted(by_day[d], key=lambda x: (-x[1], x[0]))[:top_n]
        br.agg_add(agg, [{"gross": g, "net": g - cost, "held": 1, "reason": r} for _s, _sc, g, r in items])
    return agg


def merge(d, out_path=None):
    cands, meta, ns = [], {}, 0
    for f in sorted(glob.glob(os.path.join(d, "**", "chan_gap_short_s*.json"), recursive=True)):
        r = json.load(open(f))
        cands += r["candidates"]
        ns += r["n_symbols"]
        meta = {k: r[k] for k in ("tag", "interval", "period", "cost_round_trip_pct", "synthetic", "direction", "top_n")}
    agg = select_and_aggregate(cands, meta["cost_round_trip_pct"] / 100.0, meta["top_n"])
    mt = br.agg_metrics(agg)
    mt["avg_held_hours"] = round(mt["avg_held_bars"] * HOURS_PER_BAR, 1)
    out = {**{k: meta[k] for k in ("interval", "period", "cost_round_trip_pct", "synthetic", "direction")},
           "note": "per-day top-10 ranked across all shards; avg_held_hours = 1 session bar x 6.25h; schema read by main._replay_verified_tags",
           "rows": [{"tag": meta["tag"], "n_symbols": ns, "metrics": mt}]}
    json.dump(out, open(out_path or os.path.join(d, "replay_all.json"), "w"), indent=1)
    print(meta["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"], mt["exit_reasons"])
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        run()
