"""B-1467: main.py-calling full-universe replay of the chan_kalman "v1 band" family.

Registry evidence for chan_kalman__band__{long,short}__{5m,15m,1h,1d}__atr{1d5,2d5,4d0}_hold40_ve{1d0e4,10d0e4}_z{1d0,2d0}__v1
is the research harness scripts/chan_ext_research.py (chan-ext-research.yml run 38147514850), not main.py. This script replays
the same 24 cells per timeframe calling ONLY the real main.py port (UNWIRED):
  main.chan_kalman_band_v1_precompute   (Kalman err/sqrtQ, band signal, state exits, 5m/15m day-last flat, ATR14)
  main.chan_kalman_band_v1_entry_signal (signal at the close of bar i, side + valid ATR)
  main.chan_kalman_band_v1_stop         (entry -/+ k*ATR, always set: no trade without SL)
  main.chan_kalman_band_v1_exit_reason  (gap-aware stop -> state exit / eod flat -> max hold 40 bars)
Universe = main._load_nse_universe_from_file() (full NSE list, NOT main.NSE_FULL_UNIVERSE), cost = main.ROUND_TRIP_COST_PCT
per round trip, entry at the next bar open, one position per symbol at a time, BOTH directions, IS/OOS 70/30 split by
entry time (global cutoff = first + 0.7 x span of all bars in the job). Data guard copied from the research run (skip a
symbol with < 160 bars, any open <= 0, or any |close-to-close| > 40%) so the universe matches the evidence run.

Two walk modes, each its OWN tag (naming grammar, never pooled):
  chan_kalman__band_srcmain__<dir>__...__v1       one position per symbol PER DIRECTION (a separate long walk and short
                                                  walk, like the separate buy and short engines would trade it)
  chan_kalman__band_srcmain_comb__<dir>__...__v1  one position per symbol across BOTH directions (the research walk: a
                                                  long blocks a short and vice versa); directly comparable to the registry
Each row carries source_tag (the research tag) and research_pfnet / research_n for comparison.

Env: TF = job name. Jobs to dispatch through .github/workflows/sector-rotation-backtest.yml
     (script=scripts/chan_kalman_main_replay_job.py, tf=<job>, results=docs/backtest_data/chan_kalman_main_replay_<job>.json):
       5m    15m    1h    1d        (one job each; 24 cells x 2 modes = 48 rows per job)
     Optional sharding if a job ever nears the 90-min limit: "<tf>_s<k>of<N>" (e.g. 5m_s0of2, 5m_s1of2), merge the shard
     files offline (rows are per shard). SYMBOL_LIMIT=<n> caps the universe; SYNTHETIC=1 = offline smoke (NOT a result).
Output: docs/backtest_data/chan_kalman_main_replay_<job>.json {rows: [{tag, source_tag, metrics{n, pfnet, pfgross,
win_pct, avg_held_bars, avg_held_hours, exit_reasons, is{...}, oos{...}}}]}.

B-1485 (B-1484 stage 2, user 2026-11-05 "backtest TRAILING SL rules on each wired FIXED SL strategy; wire the trail only
if it beats the fixed one"): BAND_CAP=trail (or live, or a comma list of swing_bandcap modes) replays ONLY the WIRED live
cells of the job's tf (main.CHAN_KALMAN_1D_CELLS for 1d, main.CHAN_KALMAN_1H_CELLS for 1h; per-direction long walk)
under: off (the same-run fixed-stop baseline, the wired tag itself), live (Kotak resting stop with the 10% band floor) and
every scripts/swing_bandcap.TRAIL_MODES overlay (the resting stop raised by the trail, checked intraday from the bar AFTER
the fill, BEFORE main.chan_kalman_band_v1_exit_reason runs with its frozen stop). Each mode is its own tag
(swing_bandcap.band_tag). Output: docs/backtest_data/chan_kalman_main_replay_<job>_bandcap.json. BAND_CAP unset/off = the
original grid replay, bit-identical.
"""
import json
import os
import re
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import b412_helpers as H  # noqa: E402
import swing_bandcap as bc  # noqa: E402

KS = (1.5, 2.5, 4.0)
VES = (1e-4, 1e-3)
ZS = (1.0, 2.0)
HOLD = 40
IS_FRAC = 0.7
PERIOD = {"1d": "5y", "1h": "730d", "15m": "60d", "5m": "60d"}
BAR_HOURS = {"1d": 6.25, "1h": 1.0, "15m": 0.25, "5m": 5 / 60}
MIN_BARS = 160
JOBS = ("5m", "15m", "1h", "1d")


def kf(x):
    return str(x).replace(".", "d")


def params_tok(k, ve, z):
    p = {"atr": kf(k), "hold": HOLD, "ve": kf(ve * 1e4) + "e4", "z": kf(z)}
    return "_".join(f"{key}{p[key]}" for key in sorted(p))


def make_tag(variant, direction, tf, k, ve, z):
    return f"chan_kalman__{variant}__{direction}__{tf}__{params_tok(k, ve, z)}__v1"


def parse_job(job):
    m_ = re.fullmatch(r"(5m|15m|1h|1d)(?:_s(\d+)of(\d+))?", job or "")
    if not m_:
        raise SystemExit(f"unknown job {job!r}; jobs: {JOBS} (optionally _s<k>of<N>)")
    return m_.group(1), int(m_.group(2) or 0), int(m_.group(3) or 1)


def walk(m, df, interval, pre, k, sides, hold=HOLD, band=None):
    """One-position walk over df for the given sides ((1,) / (-1,) / (1, -1)) using ONLY main.py functions.
    Returns [(side, signal_i, entry_i, exit_i, gross, reason)]. Boundary = research simulate (signal bar i < n-2).
    B-1485: band = bc.make_band(df, mode) (None = off, unchanged): the resting (band-floored, optionally trailed) stop is
    checked on every bar AFTER the fill bar, before the real exit fn (which keeps the frozen stop)."""
    o = df["Open"].to_numpy(float)
    bars = {"Open": o, "High": df["High"].to_numpy(float), "Low": df["Low"].to_numpy(float),
            "Close": df["Close"].to_numpy(float)}
    n = len(o)
    sig = pre["sig"]
    cand = np.flatnonzero(np.isin(sig, sides))
    out, busy = [], -1
    for i in cand:
        if i <= busy or i >= n - 2:
            continue
        direction = "long" if sig[i] == 1 else "short"
        ent = m.chan_kalman_band_v1_entry_signal(df, interval, direction, atr_mult=k, pos=int(i), pre=pre)
        if ent is None or o[i + 1] <= 0:
            continue
        e = int(i) + 1
        ep = float(o[e])
        stop = m.chan_kalman_band_v1_stop(ep, ent["atr"], k, direction)
        if stop is None:
            continue
        res, xi = None, None
        if band is not None:
            bc.reset_trail()  # trail state is per trade
        for j in range(e, min(n, e + hold)):
            if band is not None and j > e:
                hit = bc.band_hit(band, df, j, stop, direction, ep)
                if hit is not None:
                    res, xi = (hit[1], hit[0]), j
                    break
            res = m.chan_kalman_band_v1_exit_reason(bars, direction, e, stop, hold, pos=j, pre=pre)
            if res is not None:
                xi = j
                break
        if res is None:  # data ended before max hold
            xi = n - 1
            res = ("data_end", float(bars["Close"][xi]))
        reason, px = res
        g = (px / ep - 1) if direction == "long" else (1 - px / ep)
        out.append((1 if direction == "long" else -1, int(i), e, xi, g, reason))
        busy = xi
    return out


def symbol_rows(m, df, interval):
    """{(variant, direction, k, ve, z): [trade dict]} for one symbol (all 24 cells x 2 modes)."""
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    ts = pd.DatetimeIndex(df.index).asi8
    out = {}
    for ve in VES:
        for z in ZS:
            pre = m.chan_kalman_band_v1_precompute(df, interval, z, ve)
            for k in KS:
                runs = (("band_srcmain", (1,)), ("band_srcmain", (-1,)), ("band_srcmain_comb", (1, -1)))
                for variant, sides in runs:
                    for side, _i, e, xi, g, reason in walk(m, df, interval, pre, k, sides):
                        d = "long" if side == 1 else "short"
                        out.setdefault((variant, d, k, ve, z), []).append(
                            {"gross": g, "net": g - cost, "held": xi - e + 1, "reason": reason, "ts": int(ts[e])})
    return out


def live_cells(m, interval):
    """B-1485: {wired tag: (z, ve, k, hold, direction)} for the tf (1d / 1h); other tfs have no wired cell."""
    cells = {"1d": getattr(m, "CHAN_KALMAN_1D_CELLS", {}), "1h": getattr(m, "CHAN_KALMAN_1H_CELLS", {})}.get(interval, {})
    return {t: (z, ve, k, hold, t.split("__")[2]) for t, (z, ve, k, hold) in cells.items()}


def run_modes(spec):
    """BAND_CAP = off | live | trail (off + live + every live_<trail> mode) | a comma list of modes."""
    s = (spec or "off").strip().lower()
    if s == "trail":
        return ["off", "live"] + list(bc.TRAIL_MODES)
    mds = [bc.normalize_mode(x) for x in s.split(",") if x.strip()] or ["off"]
    return ["off"] + [md for md in dict.fromkeys(mds) if md != "off"]


def symbol_rows_bandcap(m, df, interval, modes):
    """B-1485: {(wired tag, mode): [trade dict]} for one symbol: every wired cell of the tf under every mode."""
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    ts = pd.DatetimeIndex(df.index).asi8
    out = {}
    for tag, (z, ve, k, hold, d) in live_cells(m, interval).items():
        pre = m.chan_kalman_band_v1_precompute(df, interval, z, ve)
        for md in modes:
            band = bc.make_band(df, md)
            for _side, _i, e, xi, g, reason in walk(m, df, interval, pre, k, (1 if d == "long" else -1,), hold, band):
                out.setdefault((tag, md), []).append(
                    {"gross": g, "net": g - cost, "held": xi - e + 1, "reason": reason, "ts": int(ts[e])})
    return out


def run_job_bandcap(m, job, frames_iter, modes):
    """B-1485: wired cells x band modes; every row carries the same-run fixed baseline (mode off) for comparison."""
    interval, shard, nsh = parse_job(job)
    cells = live_cells(m, interval)
    if not cells:
        raise SystemExit(f"no wired chan_kalman cell for tf {interval!r} (BAND_CAP needs 1d or 1h)")
    acc, kept, seen, t_lo, t_hi = {}, 0, 0, None, None
    for _s, df in frames_iter:
        seen += 1
        if not keep_frame(df):
            continue
        kept += 1
        a = pd.DatetimeIndex(df.index).asi8
        t_lo = a[0] if t_lo is None else min(t_lo, a[0])
        t_hi = a[-1] if t_hi is None else max(t_hi, a[-1])
        for key, tr in symbol_rows_bandcap(m, df, interval, modes).items():
            acc.setdefault(key, []).extend(tr)
    cutoff = int(t_lo + IS_FRAC * (t_hi - t_lo)) if t_lo is not None else 0
    rows = []
    for tag, (z, ve, k, hold, d) in cells.items():
        base = cell_metrics(acc.get((tag, "off"), []), cutoff, BAR_HOURS[interval])
        for md in modes:
            mt = base if md == "off" else cell_metrics(acc.get((tag, md), []), cutoff, BAR_HOURS[interval])
            rows.append({"tag": bc.band_tag(tag, md), "wired_tag": tag, "band_cap": md, "direction": d, "tf": interval,
                         "atr": k, "ve": ve, "z": z, "hold_bars": hold, "walk": "per_direction", "metrics": mt,
                         "fixed_baseline": {x: base.get(x) for x in ("n", "pfnet", "win_pct", "avg_held_bars")},
                         "beats_fixed": (None if md == "off" or mt["pfnet"] is None or base["pfnet"] is None
                                         else mt["pfnet"] > base["pfnet"])})
    return {"job": job, "tf": interval, "shard": shard, "nshards": nsh, "symbols_seen": seen, "symbols_kept": kept,
            "band_cap_modes": modes,
            "is_oos_cutoff_utc": str(pd.Timestamp(cutoff, tz="UTC")) if cutoff else None,
            "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT, "synthetic": os.environ.get("SYNTHETIC") == "1",
            "universe_requested": "main._load_nse_universe_from_file()",
            "functions": ["main.chan_kalman_band_v1_precompute", "main.chan_kalman_band_v1_entry_signal",
                          "main.chan_kalman_band_v1_stop", "main.chan_kalman_band_v1_exit_reason",
                          "scripts/swing_bandcap.band_hit (resting stop + trail)"],
            "note": "B-1485 trail overlay on the wired chan_kalman cells; off = same-run fixed-stop baseline",
            "rows": rows}


def synthetic_frames(interval, count):
    frames = {}
    step = {"5m": 5, "15m": 15, "1h": 60}.get(interval)
    for s in range(count):
        rng = np.random.default_rng(100 + s)
        if step:
            idx = []
            for d in pd.bdate_range("2026-08-03", periods=30 if step < 60 else 120):
                t0 = pd.Timestamp(d.date()).tz_localize("Asia/Kolkata") + pd.Timedelta(hours=9, minutes=15)
                idx += [t0 + pd.Timedelta(minutes=step * q) for q in range(int(375 / step))]
        else:
            idx = list(pd.bdate_range("2021-01-04", periods=1200))
        n = len(idx)
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
        o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.001, n))
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
        lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
        frames[f"SYN{s}.NS"] = pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c, "Volume": 1e5},
                                            index=pd.DatetimeIndex(idx))
    return frames


def iter_frames(m, interval, shard, nsh, limit):
    """Yields (symbol, df). Batched yfinance download, same call as the research run."""
    if os.environ.get("SYNTHETIC") == "1":
        yield from synthetic_frames(interval, limit or 6).items()
        return
    import yfinance as yf
    syms = sorted(set(m._load_nse_universe_from_file()))
    if limit:
        syms = syms[:limit]
    syms = syms[shard::nsh]
    for b0 in range(0, len(syms), 100):
        batch = syms[b0:b0 + 100]
        try:
            d = yf.download(batch, period=PERIOD[interval], interval=interval, group_by="ticker", auto_adjust=True,
                            progress=False, threads=True)
        except Exception as e:
            print("batch fail", b0, e, flush=True)
            continue
        for s in batch:
            try:
                df = d[s] if len(batch) > 1 else d
                if isinstance(df.columns, pd.MultiIndex):
                    df = df.droplevel(0, axis=1) if s in df.columns.get_level_values(0) else df.droplevel(1, axis=1)
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            except Exception:
                continue
            yield s, df
        print("batch", b0, "of", len(syms), flush=True)


def keep_frame(df):
    """Research data guard (scripts/chan_ext_research.run): >= 160 bars, no open <= 0, no |ret| > 40%."""
    if len(df) < MIN_BARS:
        return False
    o, c = df["Open"].to_numpy(float), df["Close"].to_numpy(float)
    return not ((o <= 0).any() or (np.abs(c[1:] / c[:-1] - 1) > 0.4).any())


def cell_metrics(trades, cutoff, bar_hours):
    mt = H.metrics(trades)
    mt["avg_held_hours"] = round(mt["avg_held_bars"] * bar_hours, 3)
    for key, sel in (("is", [t for t in trades if t["ts"] < cutoff]), ("oos", [t for t in trades if t["ts"] >= cutoff])):
        sub = H.metrics(sel)
        sub["avg_held_hours"] = round(sub["avg_held_bars"] * bar_hours, 3)
        mt[key] = sub
    return mt


def run_job(m, job, frames_iter):
    interval, shard, nsh = parse_job(job)
    acc, kept, seen, t_lo, t_hi = {}, 0, 0, None, None
    for _s, df in frames_iter:
        seen += 1
        if not keep_frame(df):
            continue
        kept += 1
        a = pd.DatetimeIndex(df.index).asi8
        t_lo = a[0] if t_lo is None else min(t_lo, a[0])
        t_hi = a[-1] if t_hi is None else max(t_hi, a[-1])
        for key, tr in symbol_rows(m, df, interval).items():
            acc.setdefault(key, []).extend(tr)
    cutoff = int(t_lo + IS_FRAC * (t_hi - t_lo)) if t_lo is not None else 0
    try:
        import strategy_registry as sr
        reg = {s.name: s.metrics for s in sr.REGISTRY}
    except Exception:
        reg = {}
    rows = []
    for variant in ("band_srcmain", "band_srcmain_comb"):
        for d in ("long", "short"):
            for k in KS:
                for ve in VES:
                    for z in ZS:
                        src = make_tag("band", d, interval, k, ve, z)
                        rm = reg.get(src)
                        rows.append({"tag": make_tag(variant, d, interval, k, ve, z), "source_tag": src,
                                     "direction": d, "tf": interval, "atr": k, "ve": ve, "z": z, "hold_bars": HOLD,
                                     "walk": "per_direction" if variant == "band_srcmain" else "combined_both_sides",
                                     "research_pfnet": getattr(rm, "pfnet", None),
                                     "research_n": getattr(rm, "n_trades", None),
                                     "metrics": cell_metrics(acc.get((variant, d, k, ve, z), []), cutoff,
                                                             BAR_HOURS[interval])})
    return {"job": job, "tf": interval, "shard": shard, "nshards": nsh, "symbols_seen": seen, "symbols_kept": kept,
            "is_oos_cutoff_utc": str(pd.Timestamp(cutoff, tz="UTC")) if cutoff else None,
            "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT, "synthetic": os.environ.get("SYNTHETIC") == "1",
            "universe_requested": "main._load_nse_universe_from_file()",
            "functions": ["main.chan_kalman_band_v1_precompute", "main.chan_kalman_band_v1_entry_signal",
                          "main.chan_kalman_band_v1_stop", "main.chan_kalman_band_v1_exit_reason"],
            "note": "B-1467 chan_kalman v1 band main.py replay; entry next open; one position per symbol (per direction, "
                    "or across both sides for _comb); hold/ATR in bars of this tf; data_end = open at data end",
            "rows": rows}


def main_():
    import main as m
    job = os.environ.get("TF", "5m")
    interval, shard, nsh = parse_job(job)
    lim = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    t0 = time.time()
    modes = run_modes(os.environ.get("BAND_CAP"))
    if modes != ["off"]:
        res = run_job_bandcap(m, job, iter_frames(m, interval, shard, nsh, lim), modes)
    else:
        res = run_job(m, job, iter_frames(m, interval, shard, nsh, lim))
    res["elapsed_s"] = round(time.time() - t0, 1)
    out_dir = os.environ.get("OUT_DIR", os.path.join(ROOT, "docs", "backtest_data"))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"chan_kalman_main_replay_{job}{'_bandcap' if modes != ['off'] else ''}.json")
    with open(path, "w") as f:
        json.dump(res, f, indent=1, default=str)
    for r in sorted(res["rows"], key=lambda x: -(x["metrics"]["pfnet"] or 0)):
        mt = r["metrics"]
        print(r["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "oos", mt["oos"]["pfnet"],
              "hold", mt["avg_held_bars"], "research", r.get("research_pfnet"), "exits", mt.get("exit_reasons"),
              flush=True)
    print("wrote", path, "kept", res["symbols_kept"], "elapsed_s", res["elapsed_s"])
    return path


if __name__ == "__main__":
    main_()
