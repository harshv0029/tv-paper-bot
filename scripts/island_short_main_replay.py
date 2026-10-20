"""Island-reversal SHORT main.py-function replay (backlog B-891 replay half; sibling of scripts/island_main_replay.py).

ENTRY = the REAL main.island_short_entry_signal (live short detector + filters + ATR 1.5 stop, ALWAYS attached) with a
cheap real-detector pre-gate main.island_top_signal_on_last_bar. EXIT = the REAL main.brk20_min_rr_exit_reason(direction=
'short') (gap-aware stop above -> EMA13 rule exit -> 30-bar max hold), the exact function main._island_short_exit_adapter
wraps; the adapter itself is also CALLED on a sample of trades as a cross-check (reason must match; mismatches reported).
Short-aware PnL: gross = (entry - exit)/entry, net = gross - main.ROUND_TRIP_COST_PCT/100 (0.8%). Signal on the CLOSE of
bar k, fill at that close, exits from bar k+1, strict FIFO per symbol per tag (the nonovl__v2 tags). Universe =
main._load_nse_universe_from_file() (full, NOT main.NSE_FULL_UNIVERSE). Wires nothing; main.py untouched.

Modes (argv[1]):
  run    env: TAG (one of main.ISLAND_SHORT_TAGS; blank = all), SHARD, NSHARDS, INTERVAL (1d), PERIOD (5y),
         SYMBOL_LIMIT, ADAPTER_CHECKS (default 25 trades/tag/shard), SYNTHETIC=1 (offline smoke, NOT a result)
         -> out/island_short_<tagidx>_s<shard>.json (raw exact-mergeable sums)
  merge  python3 scripts/island_short_main_replay.py merge DIR [OUT.json] -> per-tag metrics next to registry numbers
         (docs/backtest_data/island_oos_1d_run_38221645245.json nonovl v2 short cells), every field kept.
"""
import glob
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brk20_replay as br  # noqa: E402
import island_main_replay as ir  # noqa: E402  (load_frames / synthetic_frame helpers; long-only driver untouched)

MIN_BARS = ir.MIN_BARS
HOURS_PER_BAR = ir.TRADING_HOURS_PER_1D_BAR
REGISTRY_JSON = os.path.join(ROOT, "docs", "backtest_data", "island_oos_1d_run_38221645245.json")


def collect_signals(m, df, tag):
    """{bar k: sig} from the REAL main.island_short_entry_signal on every bar."""
    sigs, n = {}, len(df)
    for k in range(MIN_BARS - 1, n - 1):
        sub = df.iloc[:k + 1]
        if not m.island_top_signal_on_last_bar(sub):  # superset gate (gap05 only tightens it)
            continue
        s = m.island_short_entry_signal(sub, tag)
        if s:
            sigs[k] = s
    return sigs


def run_trade(m, df, k, sig, dates, cost):
    """Fill short at signal close; exits from bar k+1 via the real exit fn. Returns (trade, exit_bar)."""
    n = len(df)
    ep, stop0 = sig["entry_price"], sig["stop_loss"]
    fill_day = dates[k + 1]
    for j in range(k + 1, n):
        reason, px = m.brk20_min_rr_exit_reason(df.iloc[:j + 1], fill_day, ep, stop0, "short")
        if reason:
            g = (ep - px) / ep
            return {"gross": g, "net": g - cost, "held": j - k, "reason": "island_short_" + reason, "exit_i": j}, j
    g = (ep - float(df["Close"].iloc[-1])) / ep
    return {"gross": g, "net": g - cost, "held": n - 1 - k, "reason": "data_end_forced_close", "exit_i": n - 1}, n - 1


def replay_symbol(m, df, tag, cost, checks):
    """Trades for one symbol/tag, strict FIFO. checks = {'left': int, 'ok': int, 'bad': [..]} (adapter cross-check)."""
    df = df.reset_index(drop=True)
    if len(df) < MIN_BARS + 3:
        return []
    dates = df["Date"].astype(str).to_numpy()
    out, free = [], 0
    for k, s in sorted(collect_signals(m, df, tag).items()):
        if k < free:
            continue
        tr, free = run_trade(m, df, k, s, dates, cost)
        if checks["left"] > 0 and tr["reason"] != "data_end_forced_close":
            checks["left"] -= 1
            got, _ = m._island_short_exit_adapter(df.iloc[:tr["exit_i"] + 1], dates[k], s["stop_loss"],
                                                  s["atr_at_entry"], 0.0)
            if got == tr["reason"]:
                checks["ok"] += 1
            else:
                checks["bad"].append([tag, int(k), tr["reason"], got])
        out.append({x: tr[x] for x in ("gross", "net", "held", "reason")})
    return out


def run():
    import main as m
    interval = os.environ.get("INTERVAL", "1d")
    period = os.environ.get("PERIOD", "5y")
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    all_tags = list(m.ISLAND_SHORT_TAGS)
    want = os.environ.get("TAG", "").strip()
    tags = [t for t in all_tags if not want or t == want]
    if not tags:
        raise SystemExit("unknown TAG %r; valid: %s" % (want, all_tags))
    n_chk = int(os.environ.get("ADAPTER_CHECKS") or 25)
    frames = ir.load_frames(m, interval, period, shard, nshards, limit)
    aggs = {t: br.agg_new() for t in tags}
    checks = {t: {"left": n_chk, "ok": 0, "bad": []} for t in tags}
    for sym, df in frames.items():
        for t in tags:
            try:
                br.agg_add(aggs[t], replay_symbol(m, df, t, cost, checks[t]))
            except Exception as ex:
                print("ERROR", sym, t, ex)
    out = {"interval": interval, "period": period, "shard": shard, "nshards": nshards, "n_symbols": len(frames),
           "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT, "atr_mult": m.ISLAND_ATR_MULT, "direction": "short",
           "synthetic": os.environ.get("SYNTHETIC") == "1",
           "cells": {t: {"raw": aggs[t], "adapter_ok": checks[t]["ok"], "adapter_bad": checks[t]["bad"]} for t in tags}}
    os.makedirs("out", exist_ok=True)
    idx = all_tags.index(tags[0]) if len(tags) == 1 else "all"
    path = f"out/island_short_{idx}_s{shard}.json"
    json.dump(out, open(path, "w"), indent=1)
    for t in tags:
        mt = br.agg_metrics(aggs[t])
        print(t, "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold", mt["avg_held_bars"],
              "adapter_ok", checks[t]["ok"], "bad", len(checks[t]["bad"]))
    print("wrote", path)


def registry_cells():
    try:
        return json.load(open(REGISTRY_JSON))["cells"]
    except Exception:
        return {}


def merge(d, out_path=None):
    tags, meta = {}, {}
    for f in sorted(glob.glob(os.path.join(d, "**", "island_short_*_s*.json"), recursive=True)):
        r = json.load(open(f))
        for t, c in r["cells"].items():
            e = tags.setdefault(t, {"agg": br.agg_new(), "n_symbols": 0, "shards": 0, "ok": 0, "bad": []})
            br.agg_merge(e["agg"], c["raw"])
            e["n_symbols"] += r["n_symbols"]
            e["shards"] += 1
            e["ok"] += c.get("adapter_ok", 0)
            e["bad"] += c.get("adapter_bad", [])
        meta = {k: r[k] for k in ("interval", "period", "cost_round_trip_pct", "atr_mult", "synthetic", "direction")}
    reg = registry_cells()
    rows = []
    for t, e in sorted(tags.items()):
        mt = br.agg_metrics(e["agg"])
        mt["avg_held_hours"] = round(mt["avg_held_bars"] * HOURS_PER_BAR, 1)
        rg = reg.get(t)
        cmp_ = None
        if rg:
            rer = {("data_end_forced_close" if k.startswith("data_end") else "island_short_" + k): v
                   for k, v in rg.get("exit_reasons", {}).items()}
            cmp_ = {"registry_n": rg["n"], "registry_pfnet": rg["pfnet"], "registry_pfgross": rg["pf_gross"],
                    "registry_win_pct": rg["win_pct"], "registry_avg_hold_bars": rg["avg_hold_bars"],
                    "registry_avg_hold_hours": round(rg["avg_hold_bars"] * HOURS_PER_BAR, 1),
                    "registry_exit_reasons": rer,
                    "delta_pfnet": None if mt["pfnet"] is None else round(mt["pfnet"] - rg["pfnet"], 3)}
        rows.append({"tag": t, "n_symbols": e["n_symbols"], "shards": e["shards"], "metrics": mt,
                     "vs_registry": cmp_,
                     "adapter_crosscheck": {"ok": e["ok"], "n_mismatch": len(e["bad"]), "mismatches": e["bad"][:20]}})
    out = {**meta, "registry_source": os.path.basename(REGISTRY_JSON),
           "note": "avg_held_hours = avg_held_bars x 6.25 trading hours (1d bars); viability is derived at read time",
           "rows": rows}
    json.dump(out, open(out_path or os.path.join(d, "island_short_all.json"), "w"), indent=1)
    for r in rows:
        mt, v = r["metrics"], r["vs_registry"] or {}
        print(r["tag"])
        print("  replay  : n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win%", mt["win_pct"],
              "hold_bars", mt["avg_held_bars"], "hold_h", mt["avg_held_hours"])
        print("  registry: n", v.get("registry_n"), "pfnet", v.get("registry_pfnet"), "pfgross", v.get("registry_pfgross"),
              "win%", v.get("registry_win_pct"), "hold_bars", v.get("registry_avg_hold_bars"),
              "hold_h", v.get("registry_avg_hold_hours"), "delta_pfnet", v.get("delta_pfnet"))
        print("  exits replay  :", json.dumps(mt["exit_reasons"]))
        print("  exits registry:", json.dumps(v.get("registry_exit_reasons")))
        print("  adapter cross-check:", r["adapter_crosscheck"]["ok"], "ok,", r["adapter_crosscheck"]["n_mismatch"], "mismatch")
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        run()
