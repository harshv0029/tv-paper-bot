"""B-112: lunar full-moon / new-moon rule, full-universe sweep (both directions, ATR x hold x candle size).

Rule under test (Murphy, Technical Analysis of the Financial Markets, ch.14; the folk "buy at full moon, sell at new
moon"): a signal on the first bar at/after each phase instant. Moon phases come from a DETERMINISTIC astronomical
calculation (Meeus, Astronomical Algorithms ch.49, mean phase + the main periodic terms; accurate to roughly 10 minutes,
no network, no ephemeris download). Times are TT/UT-equivalent to well under a bar for >=5m candles' purposes of a
folk-lore rule; delta-T (about 69 s) is ignored and stated here.

Variants, each its OWN tag per the naming grammar, long AND short as separate strategies (never a flag):
  full     signal on the full-moon bar   (the original rule's BUY leg when long; its mirror when short)
  new      signal on the new-moon bar    (the original rule's SELL leg when short; its mirror when long)
  quarter  PLACEBO control: signal on first/last-quarter bars (not part of the folk rule). A moon rule is only credible
           if full/new beat this control; every-bar market beta (about 1.04-1.16 long at h20, pattern_lab) is the other
           yardstick.
The original pooled rule (long at full + short at new) is derived at MERGE as a bidirectional pooled row from the
`full`-long and `new`-short cells of the same interval/ATR/hold; it is a printed derivation, not a stored flag.

Tag: lunar__<variant>__<dir>__<tf>__atr<k>_hd<days>__v1   (hd = hold in TRADING DAYS, converted to bars per candle size:
1d 1, 4h 2, 1h 7, 15m 25, 5m 75 bars per NSE session). ATR 1.5/2.5/4.0 stop on EVERY trade (no stopless cell), holds of
1/3/5/10 trading days, 0.8% round trip (main.ROUND_TRIP_COST_PCT). Entry at the open of the bar AFTER the signal bar,
non-overlapping per symbol, gap-aware stops (chan_research.simulate: the real trade loop is reused, not reimplemented).

HONEST CAVEATS carried into the merge output:
  * every stock sees the SAME phase dates, so pooled n is not independent: the merge prints the number of DISTINCT phase
    events covered per candle size (about 60 in 5y of 1d, about 2 full+2 new in the 60-day 5m/15m window). A cell on a
    handful of events is market-beta of those weeks, not evidence.
  * holds longer than one session on intraday candles are CARRY (swing/CNC) trades, not MIS; 5m/15m windows are 60 days.
  * 4h = 1h bars resampled per NSE session (cell_tsv.resample_4h); bar-count constants mean BARS at every interval.

Env: INTERVAL (1d|4h|1h|15m|5m), PERIOD (yfinance period override; default 1d 5y, 4h/1h 730d, 15m/5m 60d), SHARD, NSHARDS,
MAXSYM (pilot cap, 0 = full universe), PIN_FILE (B-841 pinned universe), OUT_DIR. `--merge files...` pools shards.
Output: out/lunar_<interval>_s<shard>.json. Viability is derived at read time from the raw cells; nothing is trimmed.
"""
import json
import math
import os
import sys
import warnings
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import chan_research as chn  # noqa: E402
import oneil_research as orx  # noqa: E402
import cell_tsv  # noqa: E402

KS = chn.KS
HOLD_DAYS = (1, 3, 5, 10)
PER_DAY = {"1d": 1, "4h": 2, "1h": 7, "15m": 25, "5m": 75}
PERIOD = {"1d": "5y", "4h": "730d", "1h": "730d", "15m": "60d", "5m": "60d"}
VARIANTS = ("full", "new", "quarter")
IST = timedelta(hours=5, minutes=30)
JD_UNIX_EPOCH = 2440587.5


# ------------------------------------------------------------------ deterministic moon phase (Meeus ch.49)
def _rad(x):
    return math.radians(x % 360.0)


def phase_jde(k):
    """Julian Ephemeris Day of the lunar phase with index k (integer = new moon, +0.25 first quarter, +0.5 full,
    +0.75 last quarter), Meeus Astronomical Algorithms ch.49 incl. the quarter corrections."""
    T = k / 1236.85
    jde = 2451550.09766 + 29.530588861 * k + 0.00015437 * T ** 2 - 0.000000150 * T ** 3 + 0.00000000073 * T ** 4
    E = 1 - 0.002516 * T - 0.0000074 * T ** 2
    M = 2.5534 + 29.10535670 * k - 0.0000014 * T ** 2 - 0.00000011 * T ** 3
    Mp = 201.5643 + 385.81693528 * k + 0.0107582 * T ** 2 + 0.00001238 * T ** 3 - 0.000000058 * T ** 4
    F = 160.7108 + 390.67050284 * k - 0.0016118 * T ** 2 - 0.00000227 * T ** 3 + 0.000000011 * T ** 4
    Om = 124.7746 - 1.56375588 * k + 0.0020672 * T ** 2 + 0.00000215 * T ** 3
    frac = round((k % 1.0) * 4) % 4  # 0 new, 1 first quarter, 2 full, 3 last quarter
    sM, sMp, sF = _rad(M), _rad(Mp), _rad(F)
    if frac == 0:
        c = (-0.40720 * math.sin(sMp) + 0.17241 * E * math.sin(sM) + 0.01608 * math.sin(2 * sMp)
             + 0.01039 * math.sin(2 * sF) + 0.00739 * E * math.sin(sMp - sM) - 0.00514 * E * math.sin(sMp + sM)
             + 0.00208 * E * E * math.sin(2 * sM) - 0.00111 * math.sin(sMp - 2 * sF) - 0.00057 * math.sin(sMp + 2 * sF)
             + 0.00056 * E * math.sin(2 * sMp + sM) - 0.00042 * math.sin(3 * sMp) + 0.00042 * E * math.sin(sM + 2 * sF)
             + 0.00038 * E * math.sin(sM - 2 * sF) - 0.00024 * E * math.sin(2 * sMp - sM) - 0.00017 * math.sin(_rad(Om)))
    elif frac == 2:
        c = (-0.40614 * math.sin(sMp) + 0.17302 * E * math.sin(sM) + 0.01614 * math.sin(2 * sMp)
             + 0.01043 * math.sin(2 * sF) + 0.00734 * E * math.sin(sMp - sM) - 0.00515 * E * math.sin(sMp + sM)
             + 0.00209 * E * E * math.sin(2 * sM) - 0.00111 * math.sin(sMp - 2 * sF) - 0.00057 * math.sin(sMp + 2 * sF)
             + 0.00056 * E * math.sin(2 * sMp + sM) - 0.00042 * math.sin(3 * sMp) + 0.00042 * E * math.sin(sM + 2 * sF)
             + 0.00038 * E * math.sin(sM - 2 * sF) - 0.00024 * E * math.sin(2 * sMp - sM) - 0.00017 * math.sin(_rad(Om)))
    else:
        c = (-0.62801 * math.sin(sMp) + 0.17172 * E * math.sin(sM) - 0.01183 * E * math.sin(sMp + sM)
             + 0.00862 * math.sin(2 * sMp) + 0.00804 * math.sin(2 * sF) + 0.00454 * E * math.sin(sMp - sM)
             + 0.00204 * E * E * math.sin(2 * sM) - 0.00180 * math.sin(sMp - 2 * sF) - 0.00070 * math.sin(sMp + 2 * sF)
             - 0.00040 * math.sin(3 * sMp) - 0.00034 * E * math.sin(2 * sMp - sM) + 0.00032 * E * math.sin(sM + 2 * sF)
             + 0.00032 * E * math.sin(sM - 2 * sF) - 0.00028 * E * E * math.sin(sMp + 2 * sM)
             + 0.00027 * E * math.sin(2 * sMp + sM) - 0.00017 * math.sin(_rad(Om)))
        W = 0.00306 - 0.00038 * E * math.cos(sM) + 0.00026 * math.cos(sMp) - 0.00002 * math.cos(sMp - sM) \
            + 0.00002 * math.cos(sMp + sM) + 0.00002 * math.cos(2 * sF)
        c += W if frac == 1 else -W
    return jde + c


def jde_to_utc(jde):
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(days=jde - JD_UNIX_EPOCH)


def phase_events(start, end):
    """[(kind, UTC datetime)] for kind in new|first_quarter|full|last_quarter within [start, end] (datetimes, UTC).
    Pure function of the dates: deterministic, no I/O."""
    out = []
    k0 = int(math.floor((start.year + (start.timetuple().tm_yday - 1) / 365.25 - 2000.0) * 12.3685)) - 2
    k1 = int(math.ceil((end.year + (end.timetuple().tm_yday - 1) / 365.25 - 2000.0) * 12.3685)) + 2
    names = ("new", "first_quarter", "full", "last_quarter")
    for q in range((k0 - 1) * 4, (k1 + 1) * 4 + 1):
        k = q / 4.0
        t = jde_to_utc(phase_jde(k))
        if start <= t <= end:
            out.append((names[q % 4], t))
    return sorted(out, key=lambda x: x[1])


def signal_masks(index, interval):
    """Boolean arrays (full, new, quarter) over a bar index: True on the FIRST bar at/after each phase instant.
    The instants are known in advance (deterministic), so there is no look-ahead. Daily bars compare on the IST date."""
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Kolkata").tz_localize(None)
    n = len(idx)
    masks = {v: np.zeros(n, bool) for v in VARIANTS}
    if n == 0:
        return masks
    lo = (idx[0] - pd.Timedelta(days=2)).to_pydatetime().replace(tzinfo=timezone.utc)
    hi = (idx[-1] + pd.Timedelta(days=2)).to_pydatetime().replace(tzinfo=timezone.utc)
    vals = idx.values.astype("datetime64[ns]").astype("int64")
    for kind, t_utc in phase_events(lo - IST, hi):
        t_ist = (t_utc + IST).replace(tzinfo=None)
        ts = pd.Timestamp(t_ist)
        if interval == "1d":
            ts = ts.normalize()
        pos = int(np.searchsorted(vals, ts.value, side="left"))
        if pos <= 0 or pos >= n:      # before the data starts / after it ends: not a tradable bar in this window
            continue
        masks["full" if kind == "full" else "new" if kind == "new" else "quarter"][pos] = True
    return masks


# ------------------------------------------------------------------ tags and cells
def tag(variant, d, tf, k, hd):
    return f"lunar__{variant}__{d}__{tf}__atr{chn.kfmt(k)}_hd{hd}__v1"


def sim_rows(o, h, l, c, atr, sig_bool, side, k, hold_bars, cost):
    sig = np.where(sig_bool, side, 0)
    tr = chn.simulate(o, h, l, c, atr, sig, k, hold_bars)
    return [(t[3] - cost, t[3], t[2] - t[1] + 1, t[4]) for t in tr if t[0] == side]


def cells_for_frame(df, interval, cost, cells):
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    atr = chn.atr_arr(h, l, c)
    masks = signal_masks(df.index, interval)
    for var in VARIANTS:
        if not masks[var].any():
            continue
        for d, side in (("long", 1), ("short", -1)):
            for k in KS:
                for hd in HOLD_DAYS:
                    rows = sim_rows(o, h, l, c, atr, masks[var], side, k, hd * PER_DAY[interval], cost)
                    if rows:
                        orx.acc_add(cells, tag(var, d, interval, k, hd), rows)


# ------------------------------------------------------------------ run / merge
def download(batch, interval, period):
    import yfinance as yf
    return yf.download(batch, period=period, interval=("1h" if interval == "4h" else interval), group_by="ticker",
                       auto_adjust=True, progress=False, threads=True)


def run():
    import main as app
    import universe_pin as up
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    interval = os.environ.get("INTERVAL", "1d")
    if interval not in PER_DAY:
        raise SystemExit(f"unsupported INTERVAL {interval}")
    period = os.environ.get("PERIOD") or PERIOD[interval]
    shard, nsh = int(os.environ.get("SHARD", 0)), int(os.environ.get("NSHARDS", 1))
    pin_file, pin_tol = up.env_args()
    syms = up.select_universe(app._load_nse_universe_from_file(), pin_file)   # NOT main.NSE_FULL_UNIVERSE (NIFTY-200)
    cap = int(os.environ.get("MAXSYM", "0") or 0)
    if cap:
        syms = syms[:cap]
    syms = syms[shard::nsh]
    cells, kept, got, ev_idx = {}, 0, [], None
    for b0 in range(0, len(syms), 100):
        batch = syms[b0:b0 + 100]
        try:
            d = download(batch, interval, period)
        except Exception as e:
            print("batch fail", b0, e, flush=True)
            continue
        for s in batch:
            try:
                df = d[s] if len(batch) > 1 else d
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
                if interval == "4h":
                    df = cell_tsv.resample_4h(df)
            except Exception:
                continue
            if len(df) < 60:
                continue
            o, c = df["Open"].to_numpy(float), df["Close"].to_numpy(float)
            if (o <= 0).any() or (np.abs(c[1:] / c[:-1] - 1) > 0.4).any():   # bad-tick / split guard (B-458)
                continue
            kept += 1
            got.append(s)
            if ev_idx is None or len(df) > len(ev_idx):
                ev_idx = df.index
            cells_for_frame(df, interval, cost, cells)
        print("batch", b0, "kept", kept, "cells", len(cells), flush=True)
    out_dir = os.environ.get("OUT_DIR", os.path.join(ROOT, "out"))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"lunar_{interval}_s{shard}.json")
    with open(path, "w") as f:
        json.dump({"interval": interval, "period": period, "shard": shard, "universe_requested": len(syms),
                   "symbols": kept, "cost_round_trip": cost,
                   "events": {k: int(v.sum()) for k, v in signal_masks(ev_idx, interval).items()} if ev_idx is not None else {},
                   "cells": cells, **up.shard_meta(syms, got, pin_file, pin_tol)}, f,
                  default=lambda x: x.item() if hasattr(x, "item") else str(x))
    print("wrote", path, "symbols", kept, "cells", len(cells))


def pooled_pair(merged):
    """Derived bidirectional pooled rule (long at full + short at new) per (interval, atr, hd): sums the two legs' raw
    accumulators. Printed as tag lunar__pair__bidirectional__..., a derivation not a stored flag."""
    out = {}
    for t in merged:
        if not t.startswith("lunar__full__long__"):
            continue
        short_t = t.replace("lunar__full__long__", "lunar__new__short__")
        if short_t in merged:
            out[t.replace("lunar__full__long__", "lunar__pair__bidirectional__")] = orx.merge_cells([{"x": merged[t]}, {"x": merged[short_t]}])["x"]
    return out


def merge(paths):
    parts = [json.load(open(p)) for p in paths]
    groups = {}
    for p in parts:   # never pool across candle sizes
        groups.setdefault(p["interval"], []).append(p)
    import universe_pin as up
    allres, meta = {}, []
    for itv, ps in sorted(groups.items()):
        merged = orx.merge_cells([p["cells"] for p in ps])
        merged.update(pooled_pair(merged))
        res = orx.finalize(merged, min_n=1)
        allres.update(res)
        meta.append(dict(interval=itv, period=ps[0].get("period"), symbols=sum(p["symbols"] for p in ps),
                         requested=sum(p["universe_requested"] for p in ps),
                         distinct_phase_events=max((p.get("events") or {} for p in ps), key=lambda e: sum(e.values()) if e else 0)))
    out = os.environ.get("OUT", os.path.join(ROOT, "out", "lunar_results.json"))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    json.dump({"cost_round_trip": parts[0].get("cost_round_trip"), "groups": meta,
               "fetched_symbols": up.merge_fetched(parts), "results": allres}, open(out, "w"), indent=0,
              default=lambda x: x.item() if hasattr(x, "item") else str(x))
    cell_tsv.emit_full(allres, os.environ.get("TSV_OUT", os.path.join(ROOT, "out", "lunar_cells.tsv")), "lunar_sweep")
    for g in meta:
        print("GROUP", json.dumps(g))
    print("CAVEAT: all stocks share the same phase dates; read distinct_phase_events, not pooled n, as the sample size.")
    for pf, t in sorted(((m["pfnet"] or 0, t) for t, m in allres.items()), reverse=True)[:60]:
        m = allres[t]
        print(t, "pfnet", pf, "pfgross", m["pfgross"], "win", m["win_pct"], "n", m["n"], "hold_bars", m["avg_held_bars"],
              "exits", json.dumps(m["exit_reasons"], default=str))
    return allres


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--merge":
        merge(sys.argv[2:])
    else:
        run()
