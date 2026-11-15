"""Elder descending-triangle breakout main.py-function replay (backlog B-1597).

ENTRY and EXIT decisions are the REAL main.tri_desc_entry_signal (port of scripts/elder_patterns_research.d_triangle
kind="desc", both directions, ATR stop attached) and main.brk20_min_rr_exit_reason (gap-aware stop -> EMA13 rule exit
-> 30-bar max hold, direction-aware). The trailing variants call the real main.swing_trail_level (B-1500 ltp/chand
arithmetic) bar by bar BEFORE the real exit fn, as main.peak_ltp_trail_walk orders it (level off the peak of the bars
before; a hit only when the trail is strictly tighter than the initial stop). Never a reimplementation.
Fill: FILL=close (default, live/island convention: signal close, exits from bar k+1) or FILL=next_open (the research
harness: next bar's open, detector called with entry_price=open). Overlapping fills (v1 style): every signal opens an
independent trade. Cost = main.ROUND_TRIP_COST_PCT/100 (0.8%). Universe = main._load_nse_universe_from_file() (full,
NOT main.NSE_FULL_UNIVERSE). Bars via scripts/research_interval.fetch_interval (1d/4h/1h/15m, period capped).
Only tags of main.TRIDESC_ALL_TAGS whose tf == INTERVAL are replayed. Validation only; wires nothing.

Rows: every main.TRIDESC_ALL_TAGS tag (fixed ATR stop) plus, per tag, the trail set TRAIL_RULES
(<tag minus __v2>_<suffix>__v2). Each row is its own registry tag, never merged.

Modes (argv[1]):
  run    env: SHARD, NSHARDS, INTERVAL (1d), PERIOD (5y), FILL, SYMBOL_LIMIT, TRAIL (1 = on, default),
         SYNTHETIC=1 (offline smoke, NOT a result)  -> out/tridesc_<interval>_s<shard>.json (raw sums)
  merge  python3 scripts/tri_desc_main_replay.py merge DIR [OUT.json] -> per-tag metrics + SUMMARY table
         (tag n pfnet pfgross win% hold {exits}, the elder_patterns_research / b5_merge layout).
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
import brk20_replay as br  # noqa: E402  (exact-mergeable aggregation helpers)

MIN_BARS = 22
TRAIL_RULES = {"trailltp0d5r": ("ltp", 0.5), "trailltp1r": ("ltp", 1.0), "trailchand1r": ("chand", 1.0)}


def trail_tag(tag, suffix):
    assert tag.endswith("__v2")
    return tag[:-len("__v2")] + "_" + suffix + "__v2"


def tags_for_interval(m, interval):
    return [t for t in m.TRIDESC_ALL_TAGS if m.tridesc_params_of_tag(t)[1] == interval]


def collect_signals(m, df, tag, fill="close"):
    """{bar k: sig} from the REAL main.tri_desc_entry_signal on every bar k (gated by the real last-bar detector)."""
    direction, _tf, _am, _vol = m.tridesc_params_of_tag(tag)
    sigs = {}
    n = len(df)
    o = df["Open"].to_numpy(dtype=float)
    for k in range(MIN_BARS - 1, n - 1):
        sub = df.iloc[max(0, k + 1 - m.TRIDESC_CALC_WINDOW):k + 1]
        if not m.tri_desc_signal_on_last_bar(sub, direction, False):  # superset gate (vol only tightens it)
            continue
        s = m.tri_desc_entry_signal(sub, tag, entry_price=(o[k + 1] if fill == "next_open" else None))
        if s:
            sigs[k] = s
    return sigs


def run_trade(m, df, k, sig, dates, cost, trail=None):
    """Exits from bar k+1 (the fill bar for FILL=next_open) via the real exit fn; trail = (kind, N) or None."""
    n = len(df)
    direction = sig["direction"]
    sgn = 1.0 if direction == "long" else -1.0
    ep, stop0 = sig["entry_price"], sig["stop_loss"]
    fill_day = dates[k + 1]
    o, h, lo, c = (df[x].to_numpy(dtype=float) for x in ("Open", "High", "Low", "Close"))
    peak = ep

    def done(px, j, reason):
        g = sgn * (px - ep) / ep
        return {"gross": g, "net": g - cost, "held": j - k, "reason": reason}

    for j in range(k + 1, n):
        if trail:
            kind, nm = trail
            lvl = m.swing_trail_level(kind, direction, ep, stop0, peak, nm)
            if direction == "long" and lvl > stop0 and lo[j] <= lvl:
                return done(min(o[j], lvl), j, "trail_stop")
            if direction == "short" and lvl < stop0 and h[j] >= lvl:
                return done(max(o[j], lvl), j, "trail_stop")
        reason, px = m.brk20_min_rr_exit_reason(df.iloc[:j + 1], fill_day, ep, stop0, direction)
        if reason:
            return done(px, j, reason)
        if trail:
            pk = (h[j] if direction == "long" else lo[j]) if trail[0] == "ltp" else c[j]
            if np.isfinite(pk):
                peak = max(peak, pk) if direction == "long" else min(peak, pk)
    return done(c[-1], n - 1, "data_end_forced_close")


def replay_symbol(m, df, tags, cost, fill="close", trail_on=True):
    """{row_tag: [trades]} for one symbol (overlapping fills)."""
    df = df.reset_index(drop=True)
    rows = list(tags) + ([trail_tag(t, s) for t in tags for s in TRAIL_RULES] if trail_on else [])
    if len(df) < MIN_BARS + 3:
        return {t: [] for t in rows}
    dates = df["Date"].astype(str).to_numpy()
    out = {}
    for tag in tags:
        sigs = collect_signals(m, df, tag, fill)
        out[tag] = [run_trade(m, df, k, s, dates, cost) for k, s in sorted(sigs.items())]
        if trail_on:
            for suf, rule in TRAIL_RULES.items():
                out[trail_tag(tag, suf)] = [run_trade(m, df, k, s, dates, cost, rule) for k, s in sorted(sigs.items())]
    return out


def _tri_long(base, look=20):
    """look+1 bars (o, h, l, c, v): flat bottom at base, falling top, then an upside breakout bar with volume."""
    hs = np.linspace(base * 1.10, base * 1.02, look)
    ls = base * (1 + np.linspace(0, 0.002, look))
    cs = (hs + ls) / 2
    h = np.append(hs, base * 1.14)
    l = np.append(ls, base * 1.0)
    c = np.append(cs, base * 1.12)
    o = np.append(cs, base * 1.01)
    v = np.append(np.full(look, 3e6), 1.2e7)
    return o, h, l, c, v


def synthetic_frame(seed, n=700, start="2021-01-01", freq=None):
    """Synthetic OHLCV with injected descending triangles (long) and their reciprocal mirrors (short)."""
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.012, n)))
    o = c * (1 + rng.normal(0, 0.003, n))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    v = rng.integers(2e6, 9e6, n).astype(float)
    for t, i in enumerate(range(60, n - 30, 50)):
        if t % 2 == 0:
            po, ph, pl, pc, pv = _tri_long(c[i - 1])
        else:  # short = the long pattern on the reciprocal mirror, un-flipped
            fo, fh, fl, fc, pv = _tri_long(1.0 / c[i - 1])
            po, ph, pl, pc = 1 / fo, 1 / fl, 1 / fh, 1 / fc
        s = slice(i, i + len(pc))
        o[s], hi[s], lo[s], c[s], v[s] = po, ph, pl, pc, pv
        k = i + len(pc)  # re-anchor the random walk to the pattern's last close
        if k < n:
            scale = pc[-1] / c[k]
            o[k:], hi[k:], lo[k:], c[k:] = o[k:] * scale, hi[k:] * scale, lo[k:] * scale, c[k:] * scale
    d = pd.date_range(start, periods=n, freq=freq) if freq else pd.bdate_range(start, periods=n)
    fmt = "%Y-%m-%d" if not freq else "%Y-%m-%d %H:%M:%S"
    return pd.DataFrame({"Date": d.strftime(fmt), "Open": o, "High": hi, "Low": lo, "Close": c, "Volume": v})


def load_frames(m, interval, period, shard, nshards, limit=None):
    if os.environ.get("SYNTHETIC") == "1":
        freq = None if interval == "1d" else {"1h": "h", "4h": "4h", "15m": "15min"}.get(interval)
        return {f"SYN{k}": synthetic_frame(k, freq=freq) for k in range(limit or 3)}
    import research_interval as ri
    syms = sorted(set(m._load_nse_universe_from_file()))[shard::nshards]
    if limit:
        syms = syms[:limit]
    out = {}
    for s in syms:
        try:
            raw = ri.fetch_interval(m, s, period, interval)
        except Exception:
            continue
        if raw is None or len(raw) < MIN_BARS + 3:
            continue
        out[s] = raw.reset_index(drop=True)
    return out


def run():
    import main as m
    interval = os.environ.get("INTERVAL", "1d")
    period = os.environ.get("PERIOD", "5y")
    fill = os.environ.get("FILL", "close")
    trail_on = os.environ.get("TRAIL", "1") == "1"
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    tags = tags_for_interval(m, interval)
    if not tags:
        raise SystemExit(f"no TRIDESC_ALL_TAGS tag for interval {interval} (main.TRIDESC_TFS={m.TRIDESC_TFS})")
    frames = load_frames(m, interval, period, shard, nshards, limit)
    rows = list(tags) + ([trail_tag(t, s) for t in tags for s in TRAIL_RULES] if trail_on else [])
    aggs = {t: br.agg_new() for t in rows}
    for sym, df in frames.items():
        try:
            res = replay_symbol(m, df, tags, cost, fill, trail_on)
        except Exception as ex:
            print("ERROR", sym, ex)
            continue
        for t, trs in res.items():
            br.agg_add(aggs[t], trs)
    out = {"interval": interval, "period": period, "fill": fill, "shard": shard, "nshards": nshards,
           "n_symbols": len(frames), "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT,
           "synthetic": os.environ.get("SYNTHETIC") == "1", "mode": "overlap",
           "cells": {t: {"raw": a} for t, a in aggs.items()}}
    os.makedirs("out", exist_ok=True)
    path = f"out/tridesc_{interval}_s{shard}.json"
    json.dump(out, open(path, "w"), indent=1)
    for t, a in aggs.items():
        mt = br.agg_metrics(a)
        print(t, "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    print("wrote", path)
    return out


def merge(d, out_path=None):
    tags, meta, n_symbols = {}, {}, {}
    for f in sorted(glob.glob(os.path.join(d, "**", "tridesc_*_s*.json"), recursive=True)):
        r = json.load(open(f))
        key = (r["interval"], r["shard"])
        n_symbols[key] = r["n_symbols"]
        for t, c in r["cells"].items():
            br.agg_merge(tags.setdefault(t, br.agg_new()), c["raw"])
        meta = {k: r[k] for k in ("period", "fill", "cost_round_trip_pct", "synthetic", "mode")}
    rows = []
    for t, a in sorted(tags.items()):
        mt = br.agg_metrics(a)
        rows.append({"tag": t, "n": mt["n"], "pfnet": mt["pfnet"], "pf_gross": mt["pfgross"], "win_pct": mt["win_pct"],
                     "avg_hold_bars": mt["avg_held_bars"], "avg_net_pct": mt["avg_net_pct"],
                     "exit_reasons": {k: v["n"] for k, v in mt["exit_reasons"].items()}, "metrics": mt})
    out = {**meta, "symbols_fetched": sum(n_symbols.values()), "rows": rows}
    json.dump(out, open(out_path or os.path.join(d, "tridesc_all.json"), "w"), indent=1)
    print(f"SUMMARY  symbols fetched: {out['symbols_fetched']}  round-trip cost: {meta.get('cost_round_trip_pct')}%  "
          f"fill: {meta.get('fill')}  synthetic: {meta.get('synthetic')}")
    print(f"{'tag':96s} {'n':>7s} {'PFnet':>7s} {'PFgross':>8s} {'win%':>6s} {'hold':>5s}  exits")
    for r in rows:
        pn = None if r["pfnet"] is None else round(r["pfnet"], 3)
        pg = None if r["pf_gross"] is None else round(r["pf_gross"], 3)
        print(f"{r['tag']:96s} {r['n']:7d} {str(pn):>7s} {str(pg):>8s} "
              f"{r['win_pct']:6.1f} {r['avg_hold_bars']:5.1f}  {r['exit_reasons']}")
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        run()
