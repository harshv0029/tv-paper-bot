"""brk20_min_rr in-sample / out-of-sample split harness (backlog B-798).

Same cells, same REAL main.brk20_min_rr_entry_signal / main.brk20_min_rr_exit_reason as scripts/brk20_replay.py
(imported, not reimplemented); the only addition is that each trade is stamped with its ENTRY date and bucketed
IS (entry < cutoff) or OOS (entry >= cutoff). A trade entered before the cutoff stays IS even if it exits after.
Purpose: a filter/overlay claim (e.g. a breakeven ratchet, a regime filter) is only accepted if its OOS number
holds; the pooled run cannot tell a fitted cell from a real one.

Cutoff: env SPLIT_DATE (YYYY-MM-DD) if set, else today minus (1-SPLIT_FRAC) of the interval's fetch period
(default SPLIT_FRAC=0.6, so the last 40% of the window is OOS). The cutoff is written into every output.

Modes: run (env as brk20_replay.py + SPLIT_DATE/SPLIT_FRAC) -> out/brk20_isoos_<tf>_<dir>_s<shard>.json (raw sums
per cell per half, exactly mergeable); merge <dir> -> out/brk20_isoos_all.json with IS/OOS metrics per tag and
derived (never stored-as-gate) flags vs strategy_registry.PFNET_LIVE_FLOOR. Raw data is kept in full.
Bar-count constants are BARS of the interval (1h/15m are hours/quarter-hours, not days).
"""
import datetime as dt
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import brk20_replay as R  # noqa: E402

PERIOD_DAYS = {"1d": 1826, "1h": 730, "15m": 60, "5m": 60}
MIN_OOS_TRADES = 30  # derived-flag threshold only; reported, never baked into a registry gate


def split_cutoff(interval, today=None, frac=None, split_date=None):
    if split_date:
        return str(split_date)[:10]
    frac = 0.6 if frac in (None, "") else float(frac)
    today = today or dt.date.today()
    return (today - dt.timedelta(days=round(PERIOD_DAYS[interval] * (1.0 - frac)))).isoformat()


def replay_symbol_dated(m, df, direction, atr, rr, be, cost):
    """R.replay_symbol's loop, plus an entry-date stamp per trade (calls the same real main.py functions)."""
    df = df.reset_index(drop=True)
    n = len(df)
    if n < R.MIN_BARS + 3:
        return []
    opens = df["Open"].to_numpy(float)
    closes = df["Close"].to_numpy(float)
    dates = df["Date"].astype(str).to_numpy()
    sgn = 1.0 if direction == "long" else -1.0
    out, pos = [], None
    for k in range(R.MIN_BARS - 1, n):
        sub = df.iloc[:k + 1]
        if pos is not None:
            reason, px = m.brk20_min_rr_exit_reason(sub, pos["day"], pos["ep"], pos["stop0"], direction, be)
            if reason:
                g = sgn * (px - pos["ep"]) / pos["ep"]
                out.append({"gross": g, "net": g - cost, "held": k - pos["idx"] + 1, "reason": reason,
                            "entry_date": pos["day"]})
                pos = None
        if pos is None and k + 1 < n:
            sig = m.brk20_min_rr_entry_signal(sub, direction, atr, rr, entry_price=float(opens[k + 1]))
            if sig:
                pos = {"ep": sig["entry_price"], "stop0": sig["stop_loss"], "day": dates[k + 1], "idx": k + 1}
    if pos is not None:
        g = sgn * (closes[-1] - pos["ep"]) / pos["ep"]
        out.append({"gross": g, "net": g - cost, "held": n - pos["idx"], "reason": "data_end_forced_close",
                    "entry_date": pos["day"]})
    return out


def bucket(trades, cutoff):
    """-> (is_trades, oos_trades) by entry date string (lexical compare on the YYYY-MM-DD prefix)."""
    ins, oos = [], []
    for t in trades:
        (oos if str(t["entry_date"])[:10] >= cutoff else ins).append(t)
    return ins, oos


def run():
    import main as m
    interval = os.environ.get("INTERVAL", "1d")
    direction = os.environ.get("DIRECTION", "long")
    cells = json.loads(os.environ.get("CELLS") or '[{"atr":3,"rr":4,"be":null}]')
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cutoff = split_cutoff(interval, frac=os.environ.get("SPLIT_FRAC"), split_date=os.environ.get("SPLIT_DATE"))
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    frames = R.load_frames(m, interval, shard, nshards, limit)

    def tag_of(c):
        return R.make_tag(direction, interval, c["atr"], c["rr"], c.get("be"))

    aggs = {tag_of(c): {"is": R.agg_new(), "oos": R.agg_new()} for c in cells}
    for sym, df in frames.items():
        for c in cells:
            try:
                trades = replay_symbol_dated(m, df, direction, c["atr"], c["rr"], c.get("be"), cost)
            except Exception as ex:
                print("ERROR", sym, c, ex)
                continue
            ins, oos = bucket(trades, cutoff)
            R.agg_add(aggs[tag_of(c)]["is"], ins)
            R.agg_add(aggs[tag_of(c)]["oos"], oos)
    res = {"interval": interval, "direction": direction, "shard": shard, "nshards": nshards,
           "n_symbols": len(frames), "cutoff": cutoff, "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT,
           "period": R.PERIOD_BY_INTERVAL[interval], "synthetic": os.environ.get("SYNTHETIC") == "1",
           "note": "bar-count constants are BARS of this interval; entry date < cutoff = IS, >= cutoff = OOS",
           "cells": {tag_of(c): {"cell": c, "raw": aggs[tag_of(c)]} for c in cells}}
    os.makedirs("out", exist_ok=True)
    path = f"out/brk20_isoos_{interval}_{direction}_s{shard}.json"
    json.dump(res, open(path, "w"), indent=1)
    for t, a in aggs.items():
        i, o = R.agg_metrics(a["is"]), R.agg_metrics(a["oos"])
        print(t, "IS n", i["n"], "pfnet", i["pfnet"], "| OOS n", o["n"], "pfnet", o["pfnet"])
    print("wrote", path, "cutoff", cutoff)


def verdict(is_m, oos_m, floor):
    """Derived at read time from raw metrics. pfnet None (no losses) passes only with n >= MIN_OOS_TRADES."""
    def ok(mt):
        return mt["n"] >= MIN_OOS_TRADES and (mt["pfnet"] is None or mt["pfnet"] >= floor)
    return {"is_clears_floor": ok(is_m), "oos_clears_floor": ok(oos_m),
            "oos_n_enough": oos_m["n"] >= MIN_OOS_TRADES,
            "holds_out_of_sample": ok(is_m) and ok(oos_m)}


def merge(d):
    import strategy_registry as sr
    tags, meta = {}, {}
    for f in sorted(glob.glob(os.path.join(d, "brk20_isoos_*_s*.json"))):
        r = json.load(open(f))
        for t, c in r["cells"].items():
            e = tags.setdefault(t, {"cell": c["cell"], "interval": r["interval"], "direction": r["direction"],
                                    "is": R.agg_new(), "oos": R.agg_new(), "cutoff": r["cutoff"]})
            for half in ("is", "oos"):
                R.agg_merge(e[half], c["raw"][half])
        meta = {k: r[k] for k in ("cost_round_trip_pct", "period", "synthetic", "note")}
    rows = []
    for t, e in sorted(tags.items()):
        i, o = R.agg_metrics(e["is"]), R.agg_metrics(e["oos"])
        rows.append({"tag": t, "cell": e["cell"], "interval": e["interval"], "direction": e["direction"],
                     "cutoff": e["cutoff"], "is": i, "oos": o,
                     "derived": verdict(i, o, sr.PFNET_LIVE_FLOOR)})
    out = {**meta, "floor_at_merge": sr.PFNET_LIVE_FLOOR, "rows": rows}
    json.dump(out, open(os.path.join(d, "brk20_isoos_all.json"), "w"), indent=1)
    for r in rows:
        print(r["tag"], "IS", r["is"]["n"], r["is"]["pfnet"], "OOS", r["oos"]["n"], r["oos"]["pfnet"], r["derived"])
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2])
    else:
        run()
