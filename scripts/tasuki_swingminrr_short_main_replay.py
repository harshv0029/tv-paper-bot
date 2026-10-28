"""B-965: replay of main.TASUKI_SHORT_CELLS (tasuki gap short 1d, ETF universe) and main.SWINGMINRR_GATE_SHORT_1H_TAG
(swingminrr brk20_gate short 1h atr3_rr4) through the REAL main.py functions.

Tasuki : entry main.tasuki_short_signal + main.tasuki_short_stop(close, main._compute_atr_value(sub, 14), atr_mult);
         exit main.tasuki_short_exit_reason (stop, gap-aware / close of the 3rd bar after the signal).
Swm 1h : entry main.swingminrr_gate_short_entry_signal; exit main.swingminrr_gate_short_exit_reason (stop / bar 30).
Universe: tasuki = main.ETF_SYMBOLS (the universe the registry rows were measured on); swm1h = full
main._load_nse_universe_from_file() (NOT main.NSE_FULL_UNIVERSE). Cost: main.ROUND_TRIP_COST_PCT.
FILL: signal_close (default, = live: the scan enters at the signal bar's close) or next_open. Stop fills gap-aware.
Each tag replayed INDEPENDENTLY (own position book per tag). Bar-count constants are bars of the candle in use.

Modes: run (env GROUP tasuki|swm1h, SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1 smoke) -> out/tsm_<group>_s<shard>.json ;
merge <dir> -> <dir>/tsm_all.json (rows[].metrics, the shape main._replay_verified_tags reads) + one stdout line
`RESULTS_JSON: {...}`; plan (stdlib only, B-1396c).

B-1396c root cause (run 38451258979): the plan job installs no requirements, but this file imported pandas and brk20_replay
(numpy/pandas) at module top, so `plan` crashed, `$(...)` swallowed the error, the job wrote `matrix=` (empty), the replay
job's `fromJSON('')` failed before any shard started, and aggregate (if: always()) found no artifacts. Fix: heavy imports are
lazy (plan needs only the stdlib), the workflow validates the plan output, merge creates its dir and fails on zero shards.
"""
import glob
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def _B():
    """Lazy: brk20_replay pulls numpy/pandas, which the plan job does not install (B-1396c)."""
    import brk20_replay as B  # exact-mergeable aggregation helpers
    return B

MIN_BARS = 62
WINDOW = 200
GROUPS = {"tasuki": {"period": "5y", "interval": "1d", "bar_hours": 24.0},
          "swm1h": {"period": "730d", "interval": "1h", "bar_hours": 1.0}}


def tag_specs(m):
    specs = {t: {"group": "tasuki", "atr": a} for t, a in m.TASUKI_SHORT_CELLS.items()}
    for t, rr in m.SWINGMINRR_SHORT_1H_CELLS.items():  # B-985: gate cell + gatetarget cell (rr = BUY target multiple or None)
        specs[t] = {"group": "swm1h", "rr": rr}
    return specs


def replay_symbol(m, df, tag, spec, cost, fill="signal_close"):
    """One symbol, one tag (always SHORT). Returns trade dicts {gross, net, held, reason}."""
    df = df.reset_index(drop=True)
    n = len(df)
    if n < MIN_BARS + 3:
        return []
    opens, closes = df["Open"].to_numpy(float), df["Close"].to_numpy(float)
    out, pos, blocked = [], None, -1
    for k in range(MIN_BARS - 1, n):
        if pos is not None and k > pos["sig"]:
            bars = df.iloc[pos["sig"] + 1:k + 1]
            if spec["group"] == "tasuki":
                res = m.tasuki_short_exit_reason(bars, pos["stop0"])
            else:
                rr = spec.get("rr")  # same target arithmetic as main._swingminrr_gate_short_exit
                tgt = None if rr is None else pos["ep"] - rr * (pos["stop0"] - pos["ep"])
                res = m.swingminrr_gate_short_exit_reason(bars, pos["stop0"], target=tgt)
            if res:
                g = -(res[1] - pos["ep"]) / pos["ep"]
                out.append({"gross": g, "net": g - cost, "held": k - pos["sig"], "reason": res[0]})
                pos, blocked = None, k
        if pos is None and k > blocked:
            sub = df.iloc[max(0, k + 1 - WINDOW):k + 1]
            ep = stop = atr_v = None
            if spec["group"] == "tasuki":
                if m.tasuki_short_signal(sub):
                    atr_v = m._compute_atr_value(sub, 14)
                    ep = float(sub["Close"].iloc[-1])
                    stop = m.tasuki_short_stop(ep, atr_v, spec["atr"])
            else:
                sig = m.swingminrr_gate_short_entry_signal(sub)
                if sig:
                    ep, stop = sig["entry_price"], sig["stop_loss"]
            if ep is not None and stop is not None and stop > ep:
                if fill == "next_open":
                    if k + 1 >= n:
                        continue
                    shift = float(opens[k + 1]) - ep
                    ep, stop = float(opens[k + 1]), stop + shift
                    if not stop > ep:
                        continue
                    pos = {"ep": ep, "stop0": stop, "sig": k + 1}
                else:
                    pos = {"ep": ep, "stop0": stop, "sig": k}
    if pos is not None:
        g = -(closes[-1] - pos["ep"]) / pos["ep"]
        out.append({"gross": g, "net": g - cost, "held": n - 1 - pos["sig"], "reason": "data_end_forced_close"})
    return out


def load_frames(m, group, shard, nshards, limit=None):
    import pandas as pd
    B = _B()
    if os.environ.get("SYNTHETIC") == "1":
        return {f"SYN{k}": B.synthetic_frame(k) for k in range(limit or 3)}
    g = GROUPS[group]
    pool = m.ETF_SYMBOLS if group == "tasuki" else m._load_nse_universe_from_file()
    syms = sorted(set(pool))[shard::nshards]
    if limit:
        syms = syms[:limit]
    out, errs, short = {}, [], 0
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, g["period"], g["interval"])
        except Exception as ex:
            errs.append(f"{s}: {type(ex).__name__}: {ex}")
            continue
        if raw is not None and group == "swm1h":
            raw = m._hourly_with_str_date(raw, now_naive=pd.Timestamp("2100-01-01"))
        if raw is None or len(raw) < MIN_BARS + 3:
            short += 1
            continue
        out[s] = raw.reset_index(drop=True)
    print(f"fetch {group} s{shard}/{nshards}: {len(syms)} symbols, {len(out)} loaded, {short} too short/empty, {len(errs)} errors")
    for e in errs[:5]:
        print("fetch error", e)
    if syms and not out:
        raise SystemExit("no symbol loaded - refusing to write an all-zero shard")
    return out


def run():
    import main as m
    B = _B()
    specs = tag_specs(m)
    group = os.environ.get("GROUP", "tasuki")
    tags = [t for t, s in specs.items() if s["group"] == group]
    fill = os.environ.get("FILL", "signal_close")
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    frames = load_frames(m, group, shard, nshards, limit)
    aggs = {t: B.agg_new() for t in tags}
    for sym, df in frames.items():
        for t in tags:
            try:
                B.agg_add(aggs[t], replay_symbol(m, df, t, specs[t], cost, fill))
            except Exception as ex:
                print("ERROR", sym, t, ex)
    res = {"shard": shard, "nshards": nshards, "n_symbols": len(frames), "fill_model": fill,
           "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT, "period": GROUPS[group]["period"],
           "interval": GROUPS[group]["interval"], "bar_hours": GROUPS[group]["bar_hours"],
           "synthetic": os.environ.get("SYNTHETIC") == "1",
           "note": "tags replayed independently; bar constants are bars of the candle in use",
           "cells": {t: {"spec": specs[t], "raw": a} for t, a in aggs.items()}}
    os.makedirs("out", exist_ok=True)
    path = f"out/tsm_{group}_s{shard}.json"
    json.dump(res, open(path, "w"), indent=1)
    for t, a in aggs.items():
        mt = B.agg_metrics(a)
        print(t, "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    print("wrote", path)


def results_payload(out, source):
    """The one-line RESULTS_JSON payload, in the rows[].metrics shape main._replay_verified_tags reads; every measured
    field (incl. exit-reason breakdown, spec, n_symbols, shards, fill/cost meta) is kept, never trimmed."""
    meta = {k: v for k, v in out.items() if k != "rows"}
    return {"run_id": None, "source": source, **meta, "rows": out["rows"]}


def merge(d):
    B = _B()
    os.makedirs(d, exist_ok=True)
    files = sorted(glob.glob(os.path.join(d, "tsm_*_s*.json")))
    if not files:
        raise SystemExit(f"merge: zero shard files (tsm_*_s*.json) in {d!r} - the replay matrix produced nothing; refusing to "
                         "write an empty result (B-1396c)")
    tags, meta = {}, {}
    for f in files:
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
    if not rows:
        raise SystemExit("merge: shard files held no cells - refusing to write an empty result")
    out = {**meta, "shard_files": len(files), "rows": rows}
    with open(os.path.join(d, "tsm_all.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    for r in rows:
        mt = r["metrics"]
        print(r["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"],
              "hold_bars", mt["avg_held_bars"], mt["exit_reasons"])
    src = "scripts/tasuki_swingminrr_short_main_replay.py (real main.py fns; tasuki=ETF_SYMBOLS 1d, swm1h=full NSE 1h)"
    print("RESULTS_JSON: " + json.dumps(results_payload(out, src), separators=(",", ":")))
    return out


def plan(env=None):
    e = env if env is not None else os.environ
    ns = int(e.get("NSHARDS") or "8")
    if ns < 1:
        raise ValueError(f"NSHARDS must be >= 1, got {ns}")
    inc = [{"group": "tasuki", "shard": 0, "nshards": 1}]
    inc += [{"group": "swm1h", "shard": s, "nshards": ns} for s in range(ns)]
    return {"include": inc}


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == "plan":
        print(json.dumps(plan()))
    else:
        run()
