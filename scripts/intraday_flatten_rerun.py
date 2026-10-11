"""B-792: re-run the intraday-bar viable cells with a FORCED flatten before the 15:15 IST exchange cancel.

Why: the exchange cancels every resting order (incl. the protective SL) at 15:15 IST, so an intraday (MIS) position
must be squared off at 15:14. The original runs either flattened at the session's LAST bar (15:25/15:30 close, chan_ext)
or carried trades across days (pattern_lab month/lunar, hold 25 bars). Neither is tradable as an intraday strategy.

Rule implemented (flatten_masks): per IST session day, the cut bar is the LAST bar whose END time <= 15:15
(5m: bar starting 15:10; 15m: 15:00; 1h: 14:15). The trade exits at that bar's close (reason `flatten_1515`; a stop on or
before that bar still wins, gap-aware). No signal may enter on a bar whose entry (next open) would be the cut bar or later,
and none at the session's last bar (that would carry overnight). A day with no bar ending <= 15:15 yields no trades.

Cells (derived at read time from strategy_registry.REGISTRY, never baked in): viable (PFnet >= PFNET_LIVE_FLOOR), non-1d
timeframe, avg hold <= one session (6.25 market hours). Currently chan_kalman__band (5m/15m, both dirs, ATR 1.5/2.5/4 x
ve x z) and the pattern_lab month_effect / lunar_full_new 15m short cells. Each re-run cell is a NEW tag (old stays):
`<old tag minus __v1>_fl1515__v2` (logic change = version bump). The whole (family x ve x z x ATR x dir) grid is emitted
for each requested interval, including 1h (no source cell; labelled source_tag=null) so a 1h reading exists too.

Env: FAMILY (chan_kalman | pattern), INTERVAL (5m|15m|1h), UNI (pattern only: n200 | full), SHARD, NSHARDS, MAXSYM,
OUT_DIR, COST_PCT (default main.ROUND_TRIP_COST_PCT; same 0.8% as the originals so numbers stay comparable - real MIS
costs are lower, so this is conservative). Output out/flat_<family>_<interval>[_<uni>]_s<shard>.json; `--merge files...`.
Caveats stated in the merge output: 60d (5m/15m) / 730d (1h) windows, bar-count constants mean BARS, 4h owed (needs a 1h resample).
"""
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

CUTOFF_MIN = 15 * 60 + 15  # 15:15 IST, exchange purge of resting orders
BAR_MIN = {"5m": 5, "15m": 15, "1h": 60}
PER_DAY = {"5m": 75, "15m": 25, "1h": 6}
PERIOD = {"5m": "60d", "15m": "60d", "1h": "730d"}
SESSION_HOURS = 6.25
BAR_HOURS = {"5m": 5 / 60, "15m": 0.25, "1h": 1.0}
FLAT_TAG_SUFFIX = "_fl1515"
PATTERN_RULES = ("month_effect", "lunar_full_new")


# ------------------------------------------------------------------ flatten helper
def flat_tag(old_tag):
    """New immutable tag for a flattened re-run: `<old minus __v1>_fl1515__v2`."""
    if not old_tag.endswith("__v1"):
        raise ValueError(f"expected a __v1 tag, got {old_tag}")
    return old_tag[:-4] + FLAT_TAG_SUFFIX + "__v2"


def source_tag(new_tag):
    if not (new_tag.endswith("__v2") and FLAT_TAG_SUFFIX in new_tag):
        return None
    return new_tag[:-4].replace(FLAT_TAG_SUFFIX, "", 1) + "__v1"


def _local(index):
    idx = pd.DatetimeIndex(index)
    return idx.tz_convert("Asia/Kolkata") if idx.tz is not None else idx  # naive = already IST


def flatten_masks(index, interval, cutoff_min=CUTOFF_MIN):
    """Return (cut, noentry, day_cut_idx).

    cut[i]          True on the last bar of each IST day whose END (start + bar length) is <= cutoff.
    noentry[i]      True where a signal must be dropped: its entry (next bar open) would be the cut bar or later,
                    the bar is the session's last (overnight carry), or the day has no cut bar at all.
    day_cut_idx[i]  index of the cut bar of bar i's day, -1 if the day has none.
    """
    loc = _local(index)
    n = len(loc)
    bm = BAR_MIN[interval]
    end_min = (loc.hour * 60 + loc.minute + bm).to_numpy()
    days = np.asarray(loc.date)
    cut = np.zeros(n, bool)
    noentry = np.ones(n, bool)
    dci = np.full(n, -1, dtype=int)
    start = 0
    while start < n:
        stop = start
        while stop + 1 < n and days[stop + 1] == days[start]:
            stop += 1
        ok = [i for i in range(start, stop + 1) if end_min[i] <= cutoff_min]
        if ok:
            ci = ok[-1]
            cut[ci] = True
            dci[start:stop + 1] = ci
            # signal at bar i enters at i+1; need i+1 < ci  ->  i <= ci-2
            noentry[start:min(ci - 1, stop + 1)] = False
            # first bar of the day may also precede data gaps; entries need i+1 within the same day (guaranteed: i+1 < ci)
        start = stop + 1
    return cut, noentry, dci


# ------------------------------------------------------------------ pattern_lab flatten simulate
def simulate_flat(sig, o, h, l, c, atr, hold, k, cost, side, noentry, dci):
    """pattern_lab.simulate semantics (signal at close t, entry next open, ATR stop k, k=0 no stop, gap-aware, net of cost,
    non-overlapping) but a trade ends at the earlier of `hold` bars and the day's cut bar (close).
    Returns (net list, gross list, held list, reason list)."""
    nets, grosses, held, reasons = [], [], [], []
    n = len(c)
    nxt = 0
    for t in np.flatnonzero(sig):
        if t < nxt or t + 1 >= n or np.isnan(atr[t]) or noentry[t]:
            continue
        e = t + 1
        ent = o[e]
        if not ent or np.isnan(ent):
            continue
        cutbar = dci[e]
        if cutbar < e:  # day without a cut bar, or entry at/after it
            continue
        stop = (ent - k * atr[t]) if side == 1 else (ent + k * atr[t])
        last = min(e + hold - 1, n - 1, cutbar)
        why = "flatten_1515" if cutbar < e + hold - 1 else "max_hold"
        exitp, j_exit = c[last], last
        if k:
            for j in range(e, last + 1):
                if side == 1 and l[j] <= stop:
                    exitp, j_exit, why = min(stop, o[j]), j, "stop"
                    break
                if side == -1 and h[j] >= stop:
                    exitp, j_exit, why = max(stop, o[j]), j, "stop"
                    break
        g = (exitp / ent - 1) * side
        nets.append(g - cost)
        grosses.append(g)
        held.append(j_exit - e + 1)
        reasons.append(why)
        nxt = j_exit + 1
    return nets, grosses, held, reasons


# ------------------------------------------------------------------ registry-derived cell list
def target_cells(registry=None, floor=None):
    """Viable intraday-bar cells needing a flatten re-run (derived at read time from the registry)."""
    import strategy_registry as sr
    reg = sr.REGISTRY if registry is None else registry
    fl = sr.PFNET_LIVE_FLOOR if floor is None else floor
    out = []
    for d in reg:
        m = d.metrics
        if m is None or m.pfnet < fl or m.avg_held_hrs is None or m.avg_held_hrs > SESSION_HOURS:
            continue
        if d.timeframe not in BAR_MIN:
            continue
        out.append(d)
    return out


def overnight_by_construction(registry=None, floor=None, max_hrs=24.0):
    """Viable intraday-bar cells with avg hold between one session and ~one day (e.g. 1h/4h hold 18h): they hold overnight
    by design, so a 15:15 flatten would be a different strategy; reported as swing, not re-run here (B-792's 38 includes them)."""
    import strategy_registry as sr
    reg = sr.REGISTRY if registry is None else registry
    fl = sr.PFNET_LIVE_FLOOR if floor is None else floor
    return [d for d in reg if d.metrics is not None and d.metrics.pfnet >= fl and d.metrics.avg_held_hrs is not None
            and SESSION_HOURS < d.metrics.avg_held_hrs <= max_hrs and d.timeframe in ("1h", "4h", "15m", "5m")]


def _family_of(name):
    return name.split("__")[0]


def family_map(cells):
    """{family: [tags]} for the re-run harness families."""
    out = {}
    for d in cells:
        out.setdefault(_family_of(d.name), []).append(d.name)
    return out


# ------------------------------------------------------------------ run
def _frames(syms, interval):
    import yfinance as yf
    for b0 in range(0, len(syms), 100):
        batch = syms[b0:b0 + 100]
        try:
            d = yf.download(batch, period=PERIOD[interval], interval=interval, group_by="ticker", auto_adjust=True,
                            progress=False, threads=True)
        except Exception as e:  # noqa: BLE001
            print("batch fail", b0, e, flush=True)
            continue
        for s in batch:
            try:
                df = d[s] if len(batch) > 1 else d
                yield b0, df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            except Exception:  # noqa: BLE001
                continue


def run():
    import main as app
    import chan_research as chn
    import chan_ext_research as cx
    import oneil_research as orx
    family = os.environ["FAMILY"]
    interval = os.environ["INTERVAL"]
    uni = os.environ.get("UNI", "full")
    cost = float(os.environ.get("COST_PCT") or app.ROUND_TRIP_COST_PCT) / 100.0
    shard, nsh = int(os.environ.get("SHARD", 0)), int(os.environ.get("NSHARDS", 1))
    syms = sorted(app._load_nse_universe_from_file())
    if family == "pattern" and uni == "n200":  # same universe the original pattern_lab month/lunar cells used
        syms = sorted(set(app.SWING_WATCHLIST) - set(app.ETF_SYMBOLS))
    cap = int(os.environ.get("MAXSYM", "0") or 0)
    if cap:
        syms = syms[:cap]
    syms = syms[shard::nsh]
    if family == "pattern":
        os.environ["TF"] = interval  # pattern_lab reads TF at import
        import pattern_lab as pl
    cells, kept = {}, 0
    for b0, df in _frames(syms, interval):
        if len(df) < 160:
            continue
        o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
        if (o <= 0).any() or (np.abs(c[1:] / c[:-1] - 1) > 0.4).any():
            continue
        kept += 1
        atr = chn.atr_arr(h, l, c) if family == "chan_kalman" else None
        cut, noentry, dci = flatten_masks(df.index, interval)
        if family == "chan_kalman":
            for fam, var, params, sig, hold, xl, xs in cx.kalman_cells(c, interval):
                sig = np.where(noentry, 0, sig)
                xl_f, xs_f = xl | cut, xs | cut
                for k in chn.KS:
                    tr = chn.simulate(o, h, l, c, atr, sig, k, hold, xl_f, xs_f)
                    for side, nm in ((1, "long"), (-1, "short")):
                        rows = []
                        for t in tr:
                            if t[0] != side:
                                continue
                            why = t[4]
                            orig = xl if side == 1 else xs
                            if why == "state_exit" and cut[t[2]] and not orig[t[2]]:
                                why = "flatten_1515"
                            rows.append((t[3] - cost, t[3], t[2] - t[1] + 1, why))
                        if rows:
                            orx.acc_add(cells, flat_tag(chn.tag(fam, var, nm, interval, {**params, "atr": chn.kfmt(k)})), rows)
        elif family == "pattern":
            atr_p = pl.atr_arr(h, l, c)
            d_ = pl.clean_bars(df)
            if len(d_) != len(df):  # glitch bars dropped by the original lab: recompute on the cleaned frame
                df = d_
                o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
                atr_p = pl.atr_arr(h, l, c)
                cut, noentry, dci = flatten_masks(df.index, interval)
            v = df["Volume"].to_numpy(float)
            sigs = {}
            sigs.update(pl.r_calendar(o, h, l, c, v, idx=df.index))
            sigs.update(pl.r_lunar(o, h, l, c, v, idx=df.index))
            H = PER_DAY[interval]
            for rule, (lg, sh) in sigs.items():
                for dname, sg, side in (("long", lg, 1), ("short", sh, -1)):
                    sg = np.asarray(sg, bool)
                    if not sg.any():
                        continue
                    for k in pl.KS:
                        nets, gross, held, why = simulate_flat(sg, o, h, l, c, atr_p, H, k, cost, side, noentry, dci)
                        if nets:
                            ks = "none" if not k else str(k).replace(".", "d")
                            old = f"{rule.split('_')[0]}__{'_'.join(rule.split('_')[1:]) or 'base'}__{dname}__{interval}__atr{ks}_h{H}__v1"
                            orx.acc_add(cells, flat_tag(old), list(zip(nets, gross, held, why)))
        if kept % 100 == 0:
            print("symbols", kept, "cells", len(cells), flush=True)
    out_dir = os.environ.get("OUT_DIR", os.path.join(ROOT, "out"))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"flat_{family}_{interval}{'_' + uni if family == 'pattern' else ''}_s{shard}.json")
    with open(path, "w") as f:
        json.dump({"family": family, "interval": interval, "uni": uni, "shard": shard, "universe_requested": len(syms),
                   "symbols": kept, "cost_round_trip": cost, "cells": cells}, f,
                  default=lambda x: x.item() if hasattr(x, "item") else str(x))
    print("wrote", path, "symbols", kept, "cells", len(cells))


# ------------------------------------------------------------------ merge
def merge(paths, out=None):
    import oneil_research as orx
    import strategy_registry as sr
    parts = [json.load(open(p)) for p in paths]
    groups = {}
    for p in parts:  # never pool across family/interval/universe: each group is its own result set
        groups.setdefault((p["family"], p["interval"], p.get("uni") if p["family"] == "pattern" else ""), []).append(p)
    reg = {d.name: d for d in sr.REGISTRY}
    results = {}
    meta = []
    for (fam, itv, uni), ps in sorted(groups.items()):
        res = orx.finalize(orx.merge_cells([p["cells"] for p in ps if p.get("cells")]), min_n=1)
        meta.append(dict(family=fam, interval=itv, uni=uni, symbols=sum(p["symbols"] for p in ps),
                         requested=sum(p["universe_requested"] for p in ps), cost_round_trip=ps[0].get("cost_round_trip")))
        for t, m in res.items():
            key = t if fam == "chan_kalman" else f"{t}|{uni}"
            src = source_tag(t)
            sd = reg.get(src) if src else None
            row = dict(m, tag=t, source_tag=src, family=fam, interval=itv, universe=uni or "full",
                       bar_hours=BAR_HOURS[itv],
                       avg_held_hrs=round(m["avg_held_bars"] * BAR_HOURS[itv], 3) if m.get("avg_held_bars") is not None else None)
            if sd is not None and sd.metrics is not None:
                row["orig"] = dict(pfnet=sd.metrics.pfnet, pfgross=sd.metrics.pfgross, win_pct=sd.metrics.win_rate_pct,
                                   n=sd.metrics.n_trades, avg_held_hrs=sd.metrics.avg_held_hrs, universe=sd.metrics.universe)
            # viability derived at READ time from the raw metrics; thresholds are inputs, not stored flags
            row["pfnet_ge_floor"] = bool(m["pfnet"] is not None and m["pfnet"] >= sr.PFNET_LIVE_FLOOR)
            row["n_ge_100"] = m["n"] >= 100
            row["floor_used"] = sr.PFNET_LIVE_FLOOR
            results[key] = row
    outp = out or os.environ.get("OUT", os.path.join(ROOT, "out", "flat_results.json"))
    os.makedirs(os.path.dirname(os.path.abspath(outp)), exist_ok=True)
    json.dump({"rule": "forced exit at last bar ending <= 15:15 IST; no entry whose fill bar is the cut bar or later",
               "owed": ["4h (needs a 1h resample)", "real MIS cost model (0.8% round trip kept for comparability)",
                        "pattern cells on the n200 swing watchlist are calendar effects: check full universe before trusting"],
               "groups": meta, "results": results}, open(outp, "w"), indent=0,
              default=lambda x: x.item() if hasattr(x, "item") else str(x))
    for g in meta:
        print("GROUP", json.dumps(g))
    for key, r in sorted(results.items(), key=lambda kv: -(kv[1]["pfnet"] or 0)):
        print(key, "pfnet", r["pfnet"], "pfgross", r["pfgross"], "win", r["win_pct"], "n", r["n"], "hold_hrs",
              r["avg_held_hrs"], "viable_now", r["pfnet_ge_floor"] and r["n_ge_100"],
              "orig_pfnet", (r.get("orig") or {}).get("pfnet"), "exits", json.dumps(r["exit_reasons"], default=str))
    return results


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--merge":
        merge(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == "--list":
        cells = target_cells()
        print(len(cells), "target cells")
        for fam, tags in sorted(family_map(cells).items()):
            print(fam, len(tags))
            for t in tags:
                print("  ", t, "->", flat_tag(t))
        ov = overnight_by_construction()
        print(len(ov), "overnight-by-construction (not re-run):", [d.name for d in ov])
    else:
        run()
