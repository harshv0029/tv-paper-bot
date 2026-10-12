#!/usr/bin/env python3
"""Minimum reward:risk exit on the registered swing entries (backlog B-842). Research only: no live
wiring, no main.py edits.

Prompted by trademgmt_exit__brk20_min_rr__short__1d__atr3_rr4 (PFnet 2.468, run 38174269343). The
SAME management cells are replayed on every registered swing entry, BOTH directions, ATR 1.5/2/3,
one protective stop on EVERY trade, 0.8% round trip, entry at the NEXT bar open after the signal,
strict non-overlap (one position per symbol per cell; a new signal must come on or after the prior
exit bar), 30-bar max hold, full universe via main._load_nse_universe_from_file().

Entries (the REAL main.py functions confirm every signal; a cheap vectorised necessary-condition
prefilter only decides which bars are worth calling them on, so no signal is lost):
  gap_and_go     main.gap_and_go_entry_signal / _short (native short)         daily only
  minervini_vcp  main.minervini_vcp_entry_signal / _short (native short)      daily only
  brk20          main.brk20_min_rr_entry_signal(min_rr=0, direction=...)      any candle
  order_block    main.order_block_entry_signal (long); short = reciprocal-price mirror   any candle
  volume_profile main.volume_profile_poc_entry_signal (long); short = reciprocal mirror  any candle
The native stop of each entry is NOT used: one ATR stop for all, so only the exit overlay differs.

Cells (each its own tag, family swingminrr, variant <entry>_<cell>):
  base        stop + 30-bar timeout only (baseline for the overlay)
  gate        enter only if room to the prior 60-bar extreme >= rr x risk  (the brk20_min_rr mechanism), rr 2/3/4
  target      resting profit target at rr x risk (+ the stop), rr 1.5/2/3/4  (what a live Kotak
              limit exit beside the protective SL would do)
  gatetarget  gate rr4 AND target rr4

Per tag: n, PFnet, PFnet gross, win %, avg hold, avg net return, exit reasons, top-5 winning trades
(symbol, date, ret) and PFnet excluding them (trimmed). Bad-bar guard: a bar whose Open or Close
is outside [0.5x, 2x] of the prior Close (corrupt yfinance print, B-864) is never an entry bar and
drops any trade it falls inside. Nothing is trimmed from the raw JSON.
Candle size: bar-count constants (20/60-bar lookbacks, 30-bar hold) mean bars, not days, at other
candle sizes; gap_and_go and minervini_vcp are daily constructs and are skipped off 1d.

  python3 scripts/swing_min_rr_research.py --entry brk20 --shard 0 --nshards 4 --out out/
  python3 scripts/swing_min_rr_research.py --merge out/ --json merged.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elder_indicators_research as er  # noqa: E402
from elder_batch3_research import bad_bar_mask  # noqa: E402

FAMILY = "swingminrr"
ENTRIES = ("gap_and_go", "minervini_vcp", "brk20", "order_block", "volume_profile")
DAILY_ONLY = ("gap_and_go", "minervini_vcp")
NATIVE_SHORT = ("gap_and_go", "minervini_vcp", "brk20")
WINDOW = {"gap_and_go": 60, "minervini_vcp": 420, "brk20": 150, "order_block": 130, "volume_profile": 160}
COST = er.COST_ROUND_TRIP
MAX_HOLD = 30
TOP_K = 5
GATE_RRS = (2.0, 3.0, 4.0)
TARGET_RRS = (1.5, 2.0, 3.0, 4.0)
ROOM_N = 60


def cells():
    """-> list of (variant_suffix, params, opt)"""
    out = [("base", {}, {})]
    out += [("gate", {"rr": r}, {"gate": r}) for r in GATE_RRS]
    out += [("target", {"rr": r}, {"target": r}) for r in TARGET_RRS]
    out += [("gatetarget", {"rr": 4.0}, {"gate": 4.0, "target": 4.0})]
    return out


# ------------------------------------------------------------------ mirror + signals
def mirror(dfm: pd.DataFrame) -> pd.DataFrame:
    """Reciprocal-price mirror: a short on the original is a long on this frame."""
    m = dfm.copy()
    m["Open"], m["Close"] = 1.0 / dfm["Open"], 1.0 / dfm["Close"]
    m["High"], m["Low"] = 1.0 / dfm["Low"], 1.0 / dfm["High"]
    return m


def _prefilter(df: pd.DataFrame, entry: str, direction: str) -> np.ndarray:
    """Necessary conditions only (never excludes a bar the real function would fire on)."""
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close", "Volume"))
    s = pd.Series
    pc = s(c).shift(1).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        if entry == "gap_and_go":
            gap = (o - pc) / pc * 100 if direction == "long" else (pc - o) / pc * 100
            return (gap >= 2.0) & ((c > o) if direction == "long" else (c < o))
        if entry == "brk20":
            if direction == "long":
                return c > s(h).shift(1).rolling(20).max().to_numpy()
            return c < s(l).shift(1).rolling(20).min().to_numpy()
        if entry == "minervini_vcp":
            va = s(v).rolling(20).mean().shift(1).to_numpy()
            return v >= 1.5 * va
        if entry == "order_block":     # evaluated on the (possibly mirrored) long frame
            ret = (c / pc - 1) * 100
            return s((ret >= 3.0).astype(float)).shift(1).rolling(20, min_periods=1).max().to_numpy() > 0
        if entry == "volume_profile":
            return c > o
    raise ValueError(entry)


def signal_bars(dfm: pd.DataFrame, entry: str, direction: str, mn) -> np.ndarray:
    """Boolean array over dfm rows: the real main.py entry function fires on the bar."""
    n = len(dfm)
    native = entry in NATIVE_SHORT
    frame = dfm if (direction == "long" or native) else mirror(dfm)
    pf = _prefilter(frame, entry, direction if native else "long")
    w = WINDOW[entry]
    out = np.zeros(n, dtype=bool)
    for i in np.flatnonzero(pf):
        if i < 30:
            continue
        win = frame.iloc[max(0, i - w + 1):i + 1]
        try:
            if entry == "gap_and_go":
                r = (mn.gap_and_go_entry_signal if direction == "long" else mn.gap_and_go_entry_signal_short)(win)
            elif entry == "minervini_vcp":
                r = (mn.minervini_vcp_entry_signal if direction == "long" else mn.minervini_vcp_entry_signal_short)(win)
            elif entry == "brk20":
                r = mn.brk20_min_rr_entry_signal(win, direction=direction, min_rr=0.0)
            elif entry == "order_block":
                r = mn.order_block_entry_signal(win)
            else:
                r = mn.volume_profile_poc_entry_signal(win)
        except Exception:
            r = None
        if r:
            out[i] = True
    return out


# ------------------------------------------------------------------ simulator
def sim(df: pd.DataFrame, sig: np.ndarray, direction: str, am: float, opt: dict, max_hold=MAX_HOLD, cost=COST):
    """Strict non-overlap R-aware simulator -> (trades, glitch_dropped). Stop is checked before the
    target inside a bar (conservative); a stop gapped through fills at the open."""
    d = 1 if direction == "long" else -1
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    a = er.atr(df).to_numpy()
    n = len(df)
    bad = bad_bar_mask(o, c)
    ext = (pd.Series(h).shift(1).rolling(ROOM_N).max().to_numpy() if d == 1
           else pd.Series(l).shift(1).rolling(ROOM_N).min().to_numpy())
    trades, free, glitch = [], 0, 0
    for s in np.flatnonzero(sig):
        if s < free or s + 1 >= n or np.isnan(a[s]) or a[s] <= 0:
            continue
        e = s + 1
        px = o[e]
        if px <= 0 or bad[e]:
            continue
        stop = px - d * am * a[s]
        risk = d * (px - stop)
        if risk <= 0 or (d == 1 and stop <= 0):
            continue
        if opt.get("gate"):
            room = d * (ext[s] - px) if not np.isnan(ext[s]) else -1.0
            if room < opt["gate"] * risk:
                continue
        tgt = px + d * opt["target"] * risk if opt.get("target") else None
        reason, xp, j, dropped = None, None, e, False
        for j in range(e, min(n, e + max_hold + 1)):
            if bad[j]:
                dropped = True
                break
            if (d == 1 and l[j] <= stop) or (d == -1 and h[j] >= stop):
                g = o[j] if j > e else None
                xp = stop if g is None else (min(g, stop) if d == 1 else max(g, stop))
                reason = "stop_loss"
                break
            if tgt is not None and ((d == 1 and h[j] >= tgt) or (d == -1 and l[j] <= tgt)):
                xp, reason = tgt, "target"
                break
            if j == e + max_hold:
                xp, reason = c[j], "max_hold_timeout"
                break
        if dropped:
            glitch += 1
            free = j
            continue
        if reason is None:                      # data ended inside the hold window
            xp, reason = c[min(j, n - 1)], "data_end"
        ret = d * (xp - px) / px - cost
        trades.append({"ret": float(ret), "hold": int(j - e + 1), "reason": reason, "e": int(e)})
        free = j
    return trades, glitch


# ------------------------------------------------------------------ aggregation
def new_agg():
    return {"n": 0, "wins": 0, "win_sum": 0.0, "loss_sum": 0.0, "gwin_sum": 0.0, "gloss_sum": 0.0,
            "hold_sum": 0, "ret_sum": 0.0, "reasons": {}, "top": [], "glitch_dropped": 0}


def add_trades(agg, trades, sym, idx, glitch=0, cost=COST):
    agg["glitch_dropped"] += glitch
    for t in trades:
        r = t["ret"]
        agg["n"] += 1
        agg["hold_sum"] += t["hold"]
        agg["ret_sum"] += r
        agg["reasons"][t["reason"]] = agg["reasons"].get(t["reason"], 0) + 1
        if r > 0:
            agg["wins"] += 1
            agg["win_sum"] += r
            agg["top"] = sorted(agg["top"] + [[round(r, 5), sym, str(idx[t["e"]])[:10], t["reason"]]],
                                key=lambda x: -x[0])[:TOP_K]
        else:
            agg["loss_sum"] += -r
        g = r + cost
        if g > 0:
            agg["gwin_sum"] += g
        else:
            agg["gloss_sum"] += -g


def merge_aggs(a, b):
    for k in ("n", "wins", "win_sum", "loss_sum", "gwin_sum", "gloss_sum", "hold_sum", "ret_sum", "glitch_dropped"):
        a[k] += b[k]
    for r, v in b["reasons"].items():
        a["reasons"][r] = a["reasons"].get(r, 0) + v
    a["top"] = sorted(a["top"] + b["top"], key=lambda x: -x[0])[:TOP_K]
    return a


def _pf(w, l):
    return round(w / l, 3) if l > 0 else None


def summarize(agg):
    n = agg["n"]
    top_sum = sum(t[0] for t in agg["top"])
    return {"n": n, "pfnet": _pf(agg["win_sum"], agg["loss_sum"]), "pf_gross": _pf(agg["gwin_sum"], agg["gloss_sum"]),
            "pfnet_ex_top5": _pf(agg["win_sum"] - top_sum, agg["loss_sum"]),
            "win_pct": round(100.0 * agg["wins"] / n, 2) if n else 0.0,
            "avg_hold_bars": round(agg["hold_sum"] / n, 2) if n else 0.0,
            "avg_net_ret_pct": round(100.0 * agg["ret_sum"] / n, 3) if n else 0.0,
            "win_sum": round(agg["win_sum"], 4), "loss_sum": round(agg["loss_sum"], 4),
            "exit_reasons": dict(sorted(agg["reasons"].items())), "top5": agg["top"],
            "glitch_dropped": agg["glitch_dropped"]}


def run_symbol(df, entry, tf, aggs, mn, sym=""):
    """df = er.prep frame (DatetimeIndex). Real main.py functions get a Date-column frame."""
    dfm = df.copy()
    dfm.insert(0, "Date", dfm.index.astype(str))
    dfm = dfm.reset_index(drop=True)
    for direction in ("long", "short"):
        sig = signal_bars(dfm, entry, direction, mn)
        if not sig.any():
            continue
        for am in er.ATR_MULTS:
            for suffix, params, opt in cells():
                tag = er.make_tag(FAMILY, f"{entry}_{suffix}", direction, tf, {**params, "atr": am})
                trades, glitch = sim(df, sig, direction, am, opt)
                if trades or glitch:
                    add_trades(aggs.setdefault(tag, new_agg()), trades, sym, df.index, glitch)


def merge_dir(path):
    merged, fetched, universe = {}, 0, 0
    for f in sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True)):
        d = json.load(open(f))
        if "aggs" not in d:
            continue
        fetched += d.get("fetched", 0)
        universe += d.get("universe", 0)
        for tag, ag in d["aggs"].items():
            merge_aggs(merged.setdefault(tag, new_agg()), ag)
    rows = [{"tag": t, **summarize(a)} for t, a in merged.items()]
    rows.sort(key=lambda r: (r["pfnet"] is None, -(r["pfnet"] or 0)))
    return {"symbols_fetched": fetched, "universe_size": universe, "cost_round_trip": COST, "max_hold_bars": MAX_HOLD,
            "rows": rows}


def _main_shard(args):
    sys.path.insert(0, ".")
    import main as m
    if args.entry in DAILY_ONLY and args.interval != "1d":
        print(f"{args.entry} is a daily construct; skipped at {args.interval}")
        return
    syms = sorted(set(m._load_nse_universe_from_file()))
    syms = [s for k, s in enumerate(syms) if k % args.nshards == args.shard]
    if args.max_symbols:
        syms = syms[:args.max_symbols]
    aggs, fetched = {}, 0
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, args.period, args.interval)
            if raw is None or len(raw) < 120:
                continue
            df = er.prep(raw)
            fetched += 1
            run_symbol(df, args.entry, args.interval, aggs, m, s)
        except Exception as ex:
            print("ERROR", s, ex, file=sys.stderr)
    print(f"{args.entry} shard {args.shard}: fetched {fetched}/{len(syms)}, tags {len(aggs)}")
    os.makedirs(args.out, exist_ok=True)
    json.dump({"entry": args.entry, "interval": args.interval, "fetched": fetched, "universe": len(syms), "aggs": aggs},
              open(os.path.join(args.out, f"{args.entry}_{args.interval}_{args.shard}.json"), "w"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", choices=ENTRIES)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=4)
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--period", default="5y")
    ap.add_argument("--max-symbols", type=int, default=0)
    ap.add_argument("--out", default="out")
    ap.add_argument("--merge")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    if args.merge:
        res = merge_dir(args.merge)
        print(f"universe symbols: {res['universe_size']}  fetched: {res['symbols_fetched']}  cost: {res['cost_round_trip']}")
        print(f"{'tag':84s} {'n':>6s} {'PFnet':>7s} {'exTop5':>7s} {'PFgr':>7s} {'win%':>6s} {'hold':>5s}  exits")
        for r in res["rows"]:
            print(f"{r['tag']:84s} {r['n']:6d} {str(r['pfnet']):>7s} {str(r['pfnet_ex_top5']):>7s} {str(r['pf_gross']):>7s} "
                  f"{r['win_pct']:6.1f} {r['avg_hold_bars']:5.1f}  {r['exit_reasons']}")
        if args.json:
            json.dump(res, open(args.json, "w"), indent=1)
        return 0
    if not args.entry:
        ap.error("--entry or --merge required")
    _main_shard(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
