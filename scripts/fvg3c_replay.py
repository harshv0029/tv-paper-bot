"""Full-universe replay for the `fvg3c` family (backlog B-32). Calls the REAL
main.fvg3c_scan / main.fvg3c_exit_reason. Only position bookkeeping, costs and
sizing live here (same cost model / sizing as the Pin Bar full-universe replay).

Modes:  python scripts/fvg3c_replay.py shard      (env: SHARD_INDEX, SHARD_COUNT, INTERVAL, PERIOD, GRID)
        python scripts/fvg3c_replay.py aggregate  (reads shards/*/shard_result.json)

GRID is a JSON list of param-override dicts (default: [{}] = baseline). Every
(variant, direction, param-set) cell is its own strategy tag, named per
CLAUDE.md: fvg3c__<variant>__<dir>__<tf>__<params>__v1. Cells are never pooled.
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
import main as m  # noqa: E402

OPEN_MIN, CLOSE_MIN, SQUAREOFF_MIN = 555, 930, 920
TZ_OFF = m.IST_OFFSET_MIN
CAPITAL_INR, RISK_PCT = 400000.0, 1.0
COST = {
    "brokerage_pct": 0.0020, "brokerage_flat": 0.0, "exchange_txn_pct": 0.0000297, "sebi_fee_pct": 0.000001,
    "stamp_duty_buy_pct": 0.00015, "stt_buy_pct": 0.001, "stt_sell_pct": 0.001, "gst_pct": 0.18,
    "slippage_pct": 0.0005, "dp_charge_flat": 15.93,
}
ABBR = {"min_gap_atr": "mg", "strong_body_ratio": "sb", "cons_bars": "cb", "cons_max_range_atr": "cr",
        "max_wait_bars": "mw", "trigger": "tg", "entry_level": "el", "stop_pad_atr": "sp", "rr": "rr",
        "max_hold_bars": "mh", "atr_period": "ap"}


def _fmt(v):
    return str(v).replace(".", "d") if not isinstance(v, str) else v


def cell_tag(variant, direction, tf, params):
    full = dict(m.FVG3C_DEFAULT_PARAMS)
    full.update(params)
    ps = "_".join(f"{ABBR[k]}{_fmt(full[k])}" for k in sorted(full))
    return f"fvg3c__{variant}__{direction}__{tf}__{ps}__v1"


def _buy_cost(q, px):
    n = q * px
    b = n * COST["brokerage_pct"]; ex = n * COST["exchange_txn_pct"]; se = n * COST["sebi_fee_pct"]
    return b + ex + se + n * COST["stamp_duty_buy_pct"] + n * COST["stt_buy_pct"] + (b + ex + se) * COST["gst_pct"] + n * COST["slippage_pct"]


def _sell_cost(q, px):
    n = q * px
    b = n * COST["brokerage_pct"]; ex = n * COST["exchange_txn_pct"]; se = n * COST["sebi_fee_pct"]
    return b + ex + se + n * COST["stt_sell_pct"] + (b + ex + se) * COST["gst_pct"] + n * COST["slippage_pct"]


def _trade(sym, direction, entry, stop, qty, ets, xts, xpx, reason, entry_cost):
    gross = (xpx - entry) * qty if direction == "long" else (entry - xpx) * qty
    exit_cost = _sell_cost(qty, xpx) if direction == "long" else _buy_cost(qty, xpx)
    dp = COST["dp_charge_flat"] * (1 + COST["gst_pct"])
    total = entry_cost + exit_cost + dp
    net = gross - total
    r = abs(entry - stop)
    return {"symbol": sym, "gross_pnl": gross, "net_pnl": net, "total_cost": total, "exit_reason": reason,
            "time_in_trade_min": (xts - ets) / 60.0, "net_r": net / (r * qty) if r > 0 else None}


def replay_cell(sym, df, variant, direction, params, sessions, mins, ts_arr, scanner=None, defaults=None):
    """`scanner(df, params, sessions)` / `defaults` let sibling families (snd_zone)
    reuse this exact bookkeeping; the fvg3c default calls the real main.fvg3c_scan."""
    if scanner is None:
        scan = m.fvg3c_scan(df, variant, direction, params, sessions=sessions)
    else:
        scan = scanner(df, params, sessions)
    p = dict(defaults if defaults is not None else m.FVG3C_DEFAULT_PARAMS); p.update(params)
    sig, ent, stp, tgt = scan["signal"], scan["entry_price"], scan["stop_loss"], scan["target"]
    hi = df["High"].to_numpy(float); lo = df["Low"].to_numpy(float); cl = df["Close"].to_numpy(float)
    n = len(df); trades = []; pos = None
    for i in range(n):
        mn = int(mins[i])
        if mn < OPEN_MIN or mn > CLOSE_MIN:
            continue
        if pos is not None:
            pos["bars"] += 1
            reason, fill = m.fvg3c_exit_reason(hi[i], lo[i], cl[i], direction, pos["stop"], pos["target"], pos["bars"], int(p["max_hold_bars"]))
            if reason is None and (mn >= SQUAREOFF_MIN or sessions[i] != pos["sess"]):
                reason, fill = "eod_squareoff", cl[i]
            if reason:
                trades.append(_trade(sym, direction, pos["entry"], pos["stop"], pos["qty"], pos["ets"], ts_arr[i], fill, reason, pos["cost"]))
                pos = None
            continue
        if mn >= SQUAREOFF_MIN or not sig[i]:
            continue
        entry, stop, target = float(ent[i]), float(stp[i]), float(tgt[i])
        dist = abs(entry - stop)
        if dist <= 0:
            continue
        usable = min(CAPITAL_INR, CAPITAL_INR / m.CAPITAL_TRANCHES)
        qty = int(np.floor(min(usable * RISK_PCT / 100 / dist, usable / entry)))
        if qty <= 0 or qty * entry < 100:
            continue
        cost = _buy_cost(qty, entry) if direction == "long" else _sell_cost(qty, entry)
        pos = {"entry": entry, "stop": stop, "target": target, "qty": qty, "ets": ts_arr[i], "bars": 0, "sess": sessions[i], "cost": cost}
    if pos is not None:
        trades.append(_trade(sym, direction, pos["entry"], pos["stop"], pos["qty"], pos["ets"], ts_arr[-1], cl[-1], "window_end_forced_close", pos["cost"]))
    return trades


def prep(raw):
    df = raw.copy().reset_index(drop=True)
    ts = pd.to_datetime(df["Date"])
    ts = ts.dt.tz_convert("UTC") if ts.dt.tz is not None else ts.dt.tz_localize("UTC")
    loc = ts + pd.Timedelta(minutes=TZ_OFF)
    sessions = pd.factorize(loc.dt.strftime("%Y-%m-%d"))[0]
    mins = (loc.dt.hour * 60 + loc.dt.minute).to_numpy()
    return df, sessions, mins, loc.map(lambda t: t.timestamp()).to_numpy()


def run_shard():
    idx, count = int(os.environ["SHARD_INDEX"]), int(os.environ["SHARD_COUNT"])
    interval, period = os.environ.get("INTERVAL", "5m"), os.environ.get("PERIOD", "60d")
    grid = json.loads(os.environ.get("GRID", "[{}]"))
    cells = [(v, d, g) for g in grid for v in m.FVG3C_VARIANTS for d in ("long", "short")]
    symbols = sorted(set(m._load_nse_universe_from_file()))[idx::count]
    stride = max(1, int(os.environ.get("SAMPLE_EVERY", "1")))  # >1 = cheap screening pilot (every Nth symbol); 1 = FULL universe
    symbols = symbols[::stride]
    print(f"--- shard {idx}/{count}: {len(symbols)} symbols, {len(cells)} cells, {interval}/{period} ---")
    out = {tag: [] for tag in (cell_tag(v, d, interval, g) for v, d, g in cells)}
    fetched = 0
    for sym in symbols:
        try:
            raw = m.fetch_ohlc(sym, period, interval)
        except Exception as e:
            print(f"SKIP {sym}: {e}"); continue
        if raw is None or len(raw) < 60:
            continue
        fetched += 1
        df, sessions, mins, ts_arr = prep(raw)
        for v, d, g in cells:
            try:
                out[cell_tag(v, d, interval, g)].extend(replay_cell(sym, df, v, d, g, sessions, mins, ts_arr))
            except Exception as e:
                print(f"ERROR {sym} {v}/{d}: {e}")
    with open("shard_result.json", "w") as f:
        json.dump({"shard": idx, "fetched": fetched, "universe_size": len(symbols), "cells": out}, f)
    print(f"shard {idx}: fetched {fetched}/{len(symbols)}; " + ", ".join(f"{len(t)}" for t in out.values()))


def _metrics(ts):
    if not ts:
        return None
    n = len(ts)
    w = [t["net_pnl"] for t in ts if t["net_pnl"] > 0]; l = [-t["net_pnl"] for t in ts if t["net_pnl"] <= 0]
    wg = [t["gross_pnl"] for t in ts if t["gross_pnl"] > 0]; lg = [-t["gross_pnl"] for t in ts if t["gross_pnl"] <= 0]
    pf = (sum(w) / sum(l)) if sum(l) > 0 else float("inf")
    pfg = (sum(wg) / sum(lg)) if sum(lg) > 0 else float("inf")
    return {"n": n, "win_rate": 100 * len(w) / n, "pf_net": pf, "pf_gross": pfg,
            "avg_net": sum(t["net_pnl"] for t in ts) / n, "avg_held_min": sum(t["time_in_trade_min"] for t in ts) / n}


def run_aggregate():
    cells, fetched, universe = {}, 0, 0
    for path in sorted(glob.glob("shards/shard-*-result/shard_result.json")):
        d = json.load(open(path))
        fetched += d["fetched"]; universe += d["universe_size"]
        for tag, ts in d["cells"].items():
            cells.setdefault(tag, []).extend(ts)
    print(f"--- pooled: fetched {fetched}/{universe} symbols, {len(cells)} cells ---")
    rows = []
    for tag, ts in cells.items():
        mt = _metrics(ts)
        rows.append((tag, mt, ts))
    rows.sort(key=lambda r: -(r[1]["pf_net"] if r[1] and r[1]["pf_net"] != float("inf") else -1))
    print("\n=== POOLED PER STRATEGY TAG (REAL main.py scan function, cost-net; one row per tag, never pooled across tags) ===")
    for tag, mt, ts in rows:
        if mt is None:
            print(f"{tag}: n=0"); continue
        print(f"{tag}: n={mt['n']} win={mt['win_rate']:.2f}% pf_net={mt['pf_net']:.3f} pf_gross={mt['pf_gross']:.3f} "
              f"avg_net={mt['avg_net']:.2f} avg_held_min={mt['avg_held_min']:.1f}")
        by = {}
        for t in ts:
            by.setdefault(t["exit_reason"], []).append(t)
        for r, rts in sorted(by.items(), key=lambda kv: -len(kv[1])):
            rm = _metrics(rts)
            print(f"    {r}: n={rm['n']} win={rm['win_rate']:.2f}% pf_net={rm['pf_net']:.3f}")


if __name__ == "__main__":
    {"shard": run_shard, "aggregate": run_aggregate}[sys.argv[1]]()
