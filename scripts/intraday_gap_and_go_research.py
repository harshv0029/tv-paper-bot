"""True same-day intraday Gap and Go, both directions, ATR sweep, sharded (B-45 optional follow-up).

Extracted from the inline heredoc of .github/workflows/intraday-gap-and-go-research.yml (2026-09-16 harness;
rules 1:1 as documented in that workflow header) and made dispatch-ready: --interval 5m|15m, ATR stop sweep,
long AND short mirror (2026-10-06 bidirectional rule), full-universe sharding (2026-09-29 rule), universe pin
(B-841), bad-bar guard + trimmed PFnet + top-5 trades (B-864 lesson: one glitch trade must not decide a cell).
Research only, nothing wired. Every cell is its OWN tag and never the swing tag (gap_and_go__swing__long__1d__*):

    gap_and_go_intraday__gap_hold__<long|short>__<5m|15m>__atr<2d5>_tr2d0_win30__v1

Params: atr = stop ATR multiple, tr = target R multiple (2.0, a-priori), win = entry window in minutes (30).
Bar-count constants (ATR 14, volume lookback 20 bars) change meaning with the interval; the entry window is held
at 30 MINUTES (6 bars at 5m, 2 bars at 15m). 1h is not applicable (one opening bar: the window would be empty);
4h is not applicable to a same-day opening-drive thesis. Flagged, not silently skipped.

Short mirror: gap DOWN >= 2.0% at the 9:15 print, close below the day open and in the lower half of the
open-to-low range, volume > 1.5x 20-bar average, entry in the first 30 minutes, stop entry + ATR*mult, target
entry - R*dist, exit gap_filled when close > day-high-so-far at entry. Short costs: sell-side on entry, buy-side
on exit, NO delivery DP charge (an intraday short cannot be delivery); the long keeps the original model's DP
charge (conservative, unchanged from the 2026-09-16 harness).

Usage:
  python3 scripts/intraday_gap_and_go_research.py run --shard 0 --nshards 8 --interval 5m --period 60d --out out/
  python3 scripts/intraday_gap_and_go_research.py merge out/ --json intraday_gap_and_go_results.json
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
import universe_pin as up  # noqa: E402

m = None  # the real main module, loaded lazily (tests inject a fake)

OPEN_MIN, CLOSE_MIN, SQUAREOFF_MIN = 555, 930, 920   # 9:15 / 15:30 / 15:20 IST
GAP_PCT_THRESHOLD = 2.0
VOL_MULT = 1.5
VOL_AVG_LOOKBACK_BARS = 20
ATR_N = 14
ENTRY_WINDOW_MINUTES = 30
TARGET_R_MULT = 2.0
ATR_MULTS = (1.5, 2.0, 2.5, 3.0)
BAR_MINUTES = {"5m": 5, "15m": 15}
BAD_TICK_LO, BAD_TICK_HI = 0.5, 2.0
CAPITAL_INR = 400000.0
TOP_KEEP = 5

DEFAULT_COST_MODEL = {
    "brokerage_pct": 0.0020, "brokerage_flat": 0.0,
    "exchange_txn_pct": 0.0000297, "sebi_fee_pct": 0.000001,
    "stamp_duty_buy_pct": 0.00015, "stt_buy_pct": 0.001, "stt_sell_pct": 0.001,
    "gst_pct": 0.18, "slippage_pct": 0.0005, "dp_charge_flat": 15.93,
}

UNEVIDENCED_SAMPLE = [
    "ADANIPOWER.NS", "ASIANPAINT.NS", "BAJAJ-AUTO.NS", "BEL.NS", "BHARTIARTL.NS", "BPCL.NS",
    "BRITANNIA.NS", "COALINDIA.NS", "DABUR.NS", "DRREDDY.NS", "EICHERMOT.NS", "HAL.NS",
    "HCLTECH.NS", "HDFCBANK.NS", "HDFCLIFE.NS", "ICICIGI.NS", "ICICIPRULI.NS", "IOC.NS",
    "IRFC.NS", "JINDALSTEL.NS", "KOTAKBANK.NS", "LT.NS", "LUPIN.NS", "MARICO.NS",
    "MOTHERSON.NS", "NESTLEIND.NS", "PNB.NS", "POLYCAB.NS", "SBIN.NS", "SRF.NS",
    "SUNPHARMA.NS", "TATACONSUM.NS", "TATAPOWER.NS", "TATASTEEL.NS", "TORNTPHARM.NS",
    "UBL.NS", "UPL.NS", "VEDL.NS", "WIPRO.NS", "ZYDUSLIFE.NS",
]


def _fmt(x):
    return str(x).replace(".", "d")


def make_tag(direction, interval, atr_mult):
    return (f"gap_and_go_intraday__gap_hold__{direction}__{interval}__"
            f"atr{_fmt(atr_mult)}_tr{_fmt(TARGET_R_MULT)}_win{ENTRY_WINDOW_MINUTES}__v1")


def prep(df):
    """Adds IST minute-of-day, local date, ATR and volume average columns; flags glitch bars."""
    df = df.copy()
    if "Date" not in df.columns:
        df = df.reset_index().rename(columns={df.index.name or "index": "Date"})
    ts = pd.to_datetime(df["Date"])
    ts_utc = ts.dt.tz_convert("UTC") if ts.dt.tz is not None else ts.dt.tz_localize("UTC")
    df = df.assign(ts_local=ts_utc + pd.Timedelta(minutes=m.IST_OFFSET_MIN))
    df["date_local"] = df["ts_local"].dt.strftime("%Y-%m-%d")
    df["mins"] = df["ts_local"].dt.hour * 60 + df["ts_local"].dt.minute
    df = df.reset_index(drop=True)
    closes, highs, lows = (df[k].to_numpy(dtype=float) for k in ("Close", "High", "Low"))
    volumes = df["Volume"].to_numpy(dtype=float)
    prev = np.concatenate(([np.nan], closes[:-1]))
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev), np.abs(lows - prev)))
    df["atr"] = pd.Series(tr).rolling(ATR_N).mean().to_numpy()
    df["vol_avg"] = pd.Series(volumes).rolling(VOL_AVG_LOOKBACK_BARS).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        ro, rc = df["Open"].to_numpy(float) / prev, closes / prev
        ok = np.isnan(ro) | ((ro >= BAD_TICK_LO) & (ro <= BAD_TICK_HI) & (rc >= BAD_TICK_LO) & (rc <= BAD_TICK_HI))
    df["bad"] = (~ok) | (highs < lows) | (df["Open"].to_numpy(float) <= 0) | (closes <= 0)
    return df


def _buy_cost(qty, price, cm):
    n = qty * price
    brk = cm["brokerage_flat"] if cm["brokerage_pct"] == 0 and cm["brokerage_flat"] else n * cm["brokerage_pct"]
    exch, sebi = n * cm["exchange_txn_pct"], n * cm["sebi_fee_pct"]
    return brk + exch + sebi + n * cm["stamp_duty_buy_pct"] + n * cm["stt_buy_pct"] + (brk + exch + sebi) * cm["gst_pct"] + n * cm["slippage_pct"]


def _sell_cost(qty, price, cm):
    n = qty * price
    brk = cm["brokerage_flat"] if cm["brokerage_pct"] == 0 and cm["brokerage_flat"] else n * cm["brokerage_pct"]
    exch, sebi = n * cm["exchange_txn_pct"], n * cm["sebi_fee_pct"]
    return brk + exch + sebi + n * cm["stt_sell_pct"] + (brk + exch + sebi) * cm["gst_pct"] + n * cm["slippage_pct"]


def _finalize(direction, symbol, entry, stop0, qty, exit_px, reason, entry_cost, cm, hold_bars):
    if direction == "long":
        gross = (exit_px - entry) * qty
        exit_cost = _sell_cost(qty, exit_px, cm)
        dp = cm["dp_charge_flat"] * (1 + cm["gst_pct"])
        r = entry - stop0
    else:
        gross = (entry - exit_px) * qty
        exit_cost = _buy_cost(qty, exit_px, cm)
        dp = 0.0
        r = stop0 - entry
    total = entry_cost + exit_cost + dp
    net = gross - total
    return {"symbol": symbol, "reason": reason, "gross_pnl": gross, "net_pnl": net, "total_cost": total,
            "net_ret": net / (entry * qty), "gross_ret": gross / (entry * qty), "hold": int(hold_bars),
            "net_r": net / (r * qty) if r > 0 else None}


def replay_symbol(symbol, df, direction, atr_mult, risk_pct, capital, cm, interval, day_stats=None):
    """One symbol, one direction, one ATR multiple. At most one entry per gap day; flat by 15:20 IST."""
    d = 1 if direction == "long" else -1
    bar_min = BAR_MINUTES[interval]
    window_bars = max(1, ENTRY_WINDOW_MINUTES // bar_min)
    trades = []
    days = [(day, g.reset_index(drop=True)) for day, g in df.groupby("date_local", sort=True)]
    prev_close = {days[i][0]: float(days[i - 1][1]["Close"].iloc[-1]) for i in range(1, len(days))}
    for day, g in days:
        g = g[(g["mins"] >= OPEN_MIN) & (g["mins"] <= CLOSE_MIN)].reset_index(drop=True)
        pc = prev_close.get(day)
        if g.empty or pc is None or not np.isfinite(pc) or pc <= 0 or bool(g["bad"].any()):
            continue
        day_open = float(g["Open"].iloc[0])
        gap_pct = (day_open - pc) / pc * 100
        if day_stats is not None:
            day_stats["days_seen"] = day_stats.get("days_seen", 0) + 1
        if d * gap_pct < GAP_PCT_THRESHOLD:
            continue
        if day_stats is not None:
            day_stats["days_gapped"] = day_stats.get("days_gapped", 0) + 1
        op, hi, lo, cl, vo, at, va, mi = (g[k].to_numpy(dtype=float) for k in
                                         ("Open", "High", "Low", "Close", "Volume", "atr", "vol_avg", "mins"))
        pos, entered, hso, lso = None, False, -np.inf, np.inf
        for i in range(len(g)):
            hso, lso = max(hso, hi[i]), min(lso, lo[i])
            if pos is not None:
                reason = None
                if d * (cl[i] - pos["stop"]) <= 0:
                    reason = "stop_hit"
                elif d * (cl[i] - pos["gap_ref"]) < 0:
                    reason = "gap_filled"
                elif d * (cl[i] - pos["target"]) >= 0:
                    reason = "target_hit"
                elif mi[i] >= SQUAREOFF_MIN:
                    reason = "eod_squareoff"
                if reason:
                    trades.append(_finalize(direction, symbol, pos["entry"], pos["stop0"], pos["qty"], cl[i], reason,
                                            pos["entry_cost"], cm, i - pos["i0"] + 1))
                    pos = None
                continue
            if entered:
                continue
            if i >= window_bars:
                entered = True
                continue
            if np.isnan(at[i]) or at[i] <= 0 or np.isnan(va[i]) or va[i] <= 0:
                continue
            held = d * (cl[i] - day_open) > 0
            strong = d * (cl[i] - day_open) >= 0.5 * d * ((hso if d == 1 else lso) - day_open)
            if not (held and strong and vo[i] > va[i] * VOL_MULT):
                continue
            entry = cl[i]
            stop = entry - d * atr_mult * at[i]
            dist = abs(entry - stop)
            if dist <= 0:
                continue
            target = entry + d * TARGET_R_MULT * dist
            if m._target_move_pct(target, entry) <= m.ROUND_TRIP_COST_PCT:
                continue
            usable = min(capital, capital / m.CAPITAL_TRANCHES)
            qty = int(np.floor(min(usable * risk_pct / 100 / dist, usable / entry)))
            if qty <= 0 or qty * entry < 100:
                continue
            ec = _buy_cost(qty, entry, cm) if d == 1 else _sell_cost(qty, entry, cm)
            pos = {"entry": entry, "stop0": stop, "stop": stop, "target": target, "qty": qty, "entry_cost": ec,
                   "gap_ref": lso if d == 1 else hso, "i0": i}
            entered = True
            if day_stats is not None:
                day_stats["days_entered"] = day_stats.get("days_entered", 0) + 1
        if pos is not None:   # fetch window ended mid-session: forced flat, never overnight
            trades.append(_finalize(direction, symbol, pos["entry"], pos["stop0"], pos["qty"], float(cl[-1]),
                                    "data_end_forced_close", pos["entry_cost"], cm, len(g) - pos["i0"]))
    return trades


def new_agg():
    return {"n": 0, "wins": 0, "win_sum": 0.0, "loss_sum": 0.0, "gwin_sum": 0.0, "gloss_sum": 0.0, "hold_sum": 0,
            "reasons": {}, "best": []}


def add_trades(agg, trades):
    for t in trades:
        r, g = t["net_ret"], t["gross_ret"]
        agg["n"] += 1
        agg["hold_sum"] += t["hold"]
        agg["reasons"][t["reason"]] = agg["reasons"].get(t["reason"], 0) + 1
        if r > 0:
            agg["wins"] += 1
            agg["win_sum"] += r
        else:
            agg["loss_sum"] += -r
        agg["gwin_sum" if g > 0 else "gloss_sum"] += abs(g)
        agg["best"].append(float(r))
        agg["best"] = sorted(agg["best"], reverse=True)[:TOP_KEEP]


def merge_aggs(a, b):
    for k in ("n", "wins", "win_sum", "loss_sum", "gwin_sum", "gloss_sum", "hold_sum"):
        a[k] += b[k]
    for k, v in b["reasons"].items():
        a["reasons"][k] = a["reasons"].get(k, 0) + v
    a["best"] = sorted(a["best"] + b["best"], reverse=True)[:TOP_KEEP]


def summarize(a):
    n = a["n"]
    pf = (a["win_sum"] / a["loss_sum"]) if a["loss_sum"] > 0 else (float("inf") if n else 0.0)
    pg = (a["gwin_sum"] / a["gloss_sum"]) if a["gloss_sum"] > 0 else (float("inf") if n else 0.0)
    trim = ((a["win_sum"] - (a["best"][0] if a["best"] else 0.0)) / a["loss_sum"]) if a["loss_sum"] > 0 else None
    fin = lambda x: None if x == float("inf") else round(x, 3)
    return {"n": n, "pfnet": fin(pf), "pf_gross": fin(pg), "pfnet_trim1": None if trim is None else round(trim, 3),
            "win_pct": round(100 * a["wins"] / n, 2) if n else 0.0,
            "avg_hold_bars": round(a["hold_sum"] / n, 2) if n else 0.0,
            "top5_net_ret_pct": [round(100 * x, 2) for x in a["best"]], "exit_reasons": a["reasons"]}


def sample_universe():
    return sorted(set(m.NSE_STOCK_PARAM_OVERRIDES.keys()) | set(UNEVIDENCED_SAMPLE))


def run_shard(args):
    global m
    if m is None:
        sys.path.insert(0, ".")
        import main as _m
        m = _m
    full = m._load_nse_universe_from_file() if args.universe == "full" else sample_universe()
    syms = up.select_universe(full, args.pin_file)
    syms = [s for k, s in enumerate(syms) if k % args.nshards == args.shard]
    dirs = [x for x in args.directions.split(",") if x]
    aggs, got, stats = {}, [], {}
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, args.period, args.interval)
            if raw is None or len(raw) < 50:
                continue
            df = prep(raw)
            got.append(s)
            cfg = m.NSE_STOCK_PARAM_OVERRIDES.get(s, m.NSE_STOCK_DEFAULT_PARAMS)
            for direction in dirs:
                for am in ATR_MULTS:
                    tr = replay_symbol(s, df, direction, am, cfg["risk_pct"], CAPITAL_INR, DEFAULT_COST_MODEL,
                                       args.interval, stats if am == ATR_MULTS[0] else None)
                    add_trades(aggs.setdefault(make_tag(direction, args.interval, am), new_agg()), tr)
        except Exception as ex:
            print("ERROR", s, ex, file=sys.stderr)
    print(f"shard {args.shard}: fetched {len(got)}/{len(syms)}, cells {len(aggs)}, days {stats}")
    os.makedirs(args.out, exist_ok=True)
    json.dump({"interval": args.interval, "period": args.period, "universe": len(syms), "fetched": len(got),
               "aggs": aggs, "day_stats": stats, **up.shard_meta(syms, got, args.pin_file, args.pin_tolerance)},
              open(os.path.join(args.out, f"igg_{args.shard}.json"), "w"))


def merge_dir(path):
    merged, parts, fetched, uni, ds = {}, [], 0, 0, {}
    for f in sorted(glob.glob(os.path.join(path, "**", "igg_*.json"), recursive=True)):
        d = json.load(open(f))
        parts.append(d)
        fetched += d.get("fetched", 0)
        uni += d.get("universe", 0)
        for k, v in d.get("day_stats", {}).items():
            ds[k] = ds.get(k, 0) + v
        for tag, ag in d["aggs"].items():
            merge_aggs(merged.setdefault(tag, new_agg()), ag)
    rows = [{"tag": t, **summarize(a)} for t, a in merged.items()]
    rows.sort(key=lambda r: (r["pfnet"] is None, -(r["pfnet"] or 0)))
    return {"symbols_fetched": fetched, "fetched_symbols": up.merge_fetched(parts), "universe": uni,
            "day_stats": ds, "rows": rows}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--shard", type=int, default=0)
    r.add_argument("--nshards", type=int, default=8)
    r.add_argument("--interval", choices=sorted(BAR_MINUTES), default="5m")
    r.add_argument("--period", default="60d")
    r.add_argument("--universe", choices=("full", "sample"), default="full")
    r.add_argument("--directions", default="long,short")
    r.add_argument("--out", default="out")
    up.add_args(r)
    g = sub.add_parser("merge")
    g.add_argument("dir")
    g.add_argument("--json")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        run_shard(args)
        return 0
    res = merge_dir(args.dir)
    print(f"fetched {res['symbols_fetched']} of universe slots {res['universe']}; days {res['day_stats']}")
    print(f"{'tag':84s} {'n':>6s} {'PFnet':>7s} {'trim1':>7s} {'PFgross':>8s} {'win%':>6s} {'hold':>5s}  exits")
    for x in res["rows"]:
        print(f"{x['tag']:84s} {x['n']:6d} {str(x['pfnet']):>7s} {str(x['pfnet_trim1']):>7s} {str(x['pf_gross']):>8s} "
              f"{x['win_pct']:6.1f} {x['avg_hold_bars']:5.1f}  {x['exit_reasons']}")
    if args.json:
        json.dump(res, open(args.json, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
