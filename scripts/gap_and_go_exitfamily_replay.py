"""B-1427: gap_and_go ENTRY x alternative EXIT families, replayed through REAL main.py code.

The research sim (scripts/exit_family_research.py, run 40951289638) put five gap_and_go exit-family cells above the
live gap_and_go exit (1.148 band off / 1.107 band live, B-1417). Research-sim numbers never open a gate (B-1416,
B-1417), so this driver re-runs those cells calling only main.py functions:
  entry : main.gap_and_go_entry_signal on the trailing 150-bar window (as the gap_and_go validation / B-1417)
  exit  : main.exitfamily_walk (port of simulate() kinds inval elder/ema13w, exhaust roc/volclimax), cells =
          main.GAP_AND_GO_EXITFAMILY_CELLS; the frame passed is the FULL prefix so the daily / weekly EMAs seed
          exactly as in the sim (a 150/250-row window would change them)
  ATR   : main.exitfamily_atr_at_entry (ATR14, _atr_array) at the entry bar; stop = entry - atr x ATR
  control: the live gap_and_go exit, via swing_classic_main_replay.replay_symbol (main.gap_and_go_exit_reason), the
          SAME code B-1417 used, so its row reproduces 1.148 / 1.107 when run on the same data.
Book-keeping = swing_classic_main_replay: one position per symbol per tag, enter at the signal close, no re-entry on a
bar a position was open/closed (live `continue`), force-close at the last close, net = gross % - main.ROUND_TRIP_COST_PCT.
band_cap (scripts/swing_bandcap.py, same model as B-1417): each job runs off AND the BAND_CAP mode (default live): the
resting stop = main.exitfamily_stop_level (inval frozen / exhaust chandelier through yesterday), raised to the 10% band
floor, triggered on the low from the day after entry, filled at min(open, trigger), checked before the cell's own exit.
Universe = main._load_nse_universe_from_file() (full NSE, never NSE_FULL_UNIVERSE). Daily bars, 5y.

Differences vs the sim, disclosed: no clean_bars() spike filter and ETFs not excluded (replay convention); no re-entry
on the exit bar (the v2 sim allows it); main.weekly_ema13_down_flags (live code) is all-False on a prefix with
< 30 weeks, so ema13w exits in a symbol's first ~150 bars differ from the sim (which sees the whole 5y series); % return with flat 0.8% cost instead of the sim's 1%-risk INR sizing + itemized
cost + DP (swing_classic_main_replay convention, comparable to the B-1417 control).

Modes: plan (env NSHARDS) -> matrix JSON; run (env SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1 smoke, BAND_CAP)
-> $OUT_DIR (default out)/ggxf_s<shard>.json; merge <dir> [out] -> per-tag SUMMARY lines + one RESULTS_JSON line.
"""
import glob
import json
import os
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brk20_replay as br  # noqa: E402
import swing_bandcap as bc  # noqa: E402
import swing_classic_main_replay as cl  # noqa: E402

CONTROL_TAG = "gap_and_go"
ENTRY_WINDOW = 150
MIN_BARS = 30


def tags(m):
    return [CONTROL_TAG] + list(m.GAP_AND_GO_EXITFAMILY_CELLS)


def entry_signals(m, df):
    """{bar index: signal dict} from the REAL main.gap_and_go_entry_signal. The gap prefilter only skips bars where the
    real function provably returns None (gap below SWING_GAP_PCT_THRESHOLD is one of its necessary conditions)."""
    o = df["Open"].to_numpy(float)
    c = df["Close"].to_numpy(float)
    out = {}
    for i in range(max(1, MIN_BARS), len(df)):
        if not (c[i - 1] > 0 and (o[i] - c[i - 1]) / c[i - 1] * 100 >= m.SWING_GAP_PCT_THRESHOLD):
            continue
        win = df.iloc[max(0, i + 1 - ENTRY_WINDOW):i + 1]
        sig = m.gap_and_go_entry_signal(win)
        if sig:
            out[i] = (sig, m.exitfamily_atr_at_entry(win))
    return out


def replay_exitfamily(m, df, tag, cost, band_cap="off", sigs=None):
    """One symbol, one exit-family tag. Trade dicts {gross, net, held, reason}."""
    df = df.reset_index(drop=True)
    n = len(df)
    if n < MIN_BARS + 3 or "Date" not in df.columns:
        return []
    cell = m.GAP_AND_GO_EXITFAMILY_CELLS[tag]
    sigs = entry_signals(m, df) if sigs is None else sigs
    opens, lows, highs, closes = (df[x].to_numpy(float) for x in ("Open", "Low", "High", "Close"))
    dates = df["Date"].astype(str).str[:10].to_numpy()
    band = bc.normalize_mode(band_cap) != "off"
    prevc = bc.prev_session_close(df) if band else None
    out, pos = [], None
    for i in range(MIN_BARS, n):
        if pos is not None:
            if band and i > pos["idx"]:
                strat = m.exitfamily_stop_level(cell, pos["stop"], pos["atr"], pos["rmc"])
                hit = bc.resting_stop_exit(band_cap, "long", strat, prevc[i], opens[i], lows[i], highs[i])
                if hit:
                    out.append(_fin(pos, hit[0], i, hit[1], cost))
                    pos = None
                    continue
            r = m.exitfamily_walk(df.iloc[:i + 1], pos["day"], pos["ep"], pos["atr"], cell)
            if r["reason"]:
                out.append(_fin(pos, r["fill"], i, r["reason"], cost))
                pos = None
            else:
                pos["rmc"] = max(pos["rmc"], float(r["running_max"]))
            continue  # live: never also enter the day a position is/was open
        got = sigs.get(i)
        if not got:
            continue
        sig, atr = got
        if not (np.isfinite(atr) and atr > 0):
            continue  # the sim drops an entry with unusable ATR
        ep = float(sig["entry_price"])
        pos = {"ep": ep, "atr": float(atr), "stop": m.exitfamily_initial_stop(ep, atr, cell), "rmc": ep,
               "day": dates[i], "idx": i}
    if pos is not None:
        out.append(_fin(pos, float(closes[-1]), n - 1, "data_end_forced_close", cost))
    return out


def _fin(pos, xp, i, reason, cost):
    g = (float(xp) - pos["ep"]) / pos["ep"]
    return {"gross": g, "net": g - cost, "held": i - pos["idx"], "reason": reason}


def replay_symbol(m, df, tag, cost, band_cap="off", sigs=None):
    if tag == CONTROL_TAG:
        return cl.replay_symbol(m, df, "gap_and_go", "gap_and_go", cost, band_cap)
    return replay_exitfamily(m, df, tag, cost, band_cap, sigs)


def plan(env=None):
    e = os.environ if env is None else env
    ns = int(e.get("NSHARDS") or 4)
    return {"include": [{"shard": s, "nshards": ns} for s in range(ns)]}


def run():
    import main as m
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    live = bc.mode_from_env()
    modes = ["off"] + ([live] if live != "off" else [])
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    frames = cl.load_frames(m, shard, nshards, limit)
    tg = tags(m)
    aggs = {md: {t: br.agg_new() for t in tg} for md in modes}
    for sym, df in frames.items():
        df = df.reset_index(drop=True)
        try:
            sigs = entry_signals(m, df)
        except Exception as ex:
            print("ERROR entry", sym, ex)
            continue
        for md in modes:
            for t in tg:
                try:
                    br.agg_add(aggs[md][t], replay_symbol(m, df, t, cost, md, sigs))
                except Exception as ex:
                    print("ERROR", sym, t, md, ex)
    res = {"backlog": "B-1427", "interval": cl.INTERVAL, "period": cl.PERIOD, "shard": shard, "nshards": nshards,
           "n_symbols": len(frames), "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT,
           "synthetic": os.environ.get("SYNTHETIC") == "1", "control": CONTROL_TAG,
           "modes": {md: {t: a for t, a in aggs[md].items()} for md in modes}}
    od = os.environ.get("OUT_DIR") or "out"
    os.makedirs(od, exist_ok=True)
    path = os.path.join(od, f"ggxf_s{shard}.json")
    json.dump(res, open(path, "w"), indent=1)
    for md in modes:
        for t, a in aggs[md].items():
            mt = br.agg_metrics(a)
            print(bc.band_tag(t, md), "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    print("wrote", path)
    return res


def _fmt(v, nd=3):
    return "NA" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def merge(d, out_path=None):
    pooled, nsym, order = {}, 0, []
    for f in sorted(glob.glob(os.path.join(d, "**", "ggxf_s*.json"), recursive=True)):
        r = json.load(open(f))
        nsym += r["n_symbols"]
        for md, cells in r["modes"].items():
            for t, raw in cells.items():
                if t not in order:
                    order.append(t)
                br.agg_merge(pooled.setdefault((t, md), br.agg_new()), raw)
    rows = []
    for t in order:
        off = br.agg_metrics(pooled[(t, "off")]) if (t, "off") in pooled else None
        for md in sorted(md for tt, md in pooled if tt == t and md != "off") or [None]:
            rows.append({"tag": t, "control": t == CONTROL_TAG, "band_cap": md, "band_tag": bc.band_tag(t, md or "off"),
                         "off": off, "live": br.agg_metrics(pooled[(t, md)]) if md else None})
    res = {"backlog": "B-1427", "cost_round_trip_pct": 0.8, "run_id": os.environ.get("GITHUB_RUN_ID"),
           "universe": "main._load_nse_universe_from_file() (full NSE)", "n_symbols": nsym,
           "sim_reference_run": "40951289638", "rows": rows}
    json.dump(res, open(out_path or os.path.join(d, "gap_and_go_exitfamily_all.json"), "w"), indent=1)
    print("SUMMARY tag | n off/live | win% off/live | PFnet off/live | hold off/live | live tag")
    for r in rows:
        o, lv = r["off"] or {}, r["live"] or {}
        print(f"{r['tag']}{' (CONTROL)' if r['control'] else ''} | n {o.get('n')}/{lv.get('n')}"
              f" | win {_fmt(o.get('win_pct'), 1)}/{_fmt(lv.get('win_pct'), 1)}"
              f" | PFnet {_fmt(o.get('pfnet'))}/{_fmt(lv.get('pfnet'))}"
              f" | hold {_fmt(o.get('avg_held_bars'), 1)}/{_fmt(lv.get('avg_held_bars'), 1)} | {r['band_tag']}")
    print("RESULTS_JSON: " + json.dumps(res, separators=(",", ":")))
    return res


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif len(sys.argv) > 1 and sys.argv[1] == "plan":
        print(json.dumps(plan()))
    else:
        run()
