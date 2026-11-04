"""B-1467: Minervini lab-exit family replayed on main.py code, full NSE universe, both directions, one position per symbol.

The ~65 viable minervini_vcp__*__long__1d__h60__v1/v2 registry rows came from scripts/minervini_lab.py (research harness:
real entry, lab-only exits, overlapping trades). This replay calls main.py for every decision:
  entry  : main.minervini_vcp_entry_signal (long) / main.minervini_vcp_entry_signal_short (short mirror), RS gate skipped
           (rs_percentile=None, as the lab did), evaluated on df.iloc[:i+1] (bars <= i only). A cheap exact-implied
           prefilter (close vs SMA50 and the 1.5x volume surge, both conditions the entry fn itself requires, with a 1e-9
           tolerance) only skips bars where the fn must return None.
  exits  : main.minervini_lab_simulate_trade -> main.minervini_lab_exit_reason (port of minervini_lab.run_variant)
  filters: main.minervini_lab_features + main.minervini_lab_rs_nhnl_panels (port of minervini_lab.features), and
           main.minervini_lab_stopout_cluster_flags for the B-259 cluster rule (look-ahead in the original, flagged)
The driver supplies only the bar loop: signals thinned exactly like the lab (>= 5 bars after the previous raw signal),
entry at bar i+1 open, STRICT one open position per symbol per tag (a signal at or before the previous trade's exit bar is
skipped), net of main.ROUND_TRIP_COST_PCT/100 per trade. Universe = main._load_nse_universe_from_file() minus
main.ETF_SYMBOLS (never main.NSE_FULL_UNIVERSE), 6y daily yfinance bars cleaned by scripts/bar_hygiene.clean_bars, >= 300
bars. IS/OOS by entry date: the first 70% of the union of trading dates = IS.

Short mirror semantics: exits mirrored inside main.minervini_lab_exit_reason; regime variants require the index BELOW its
SMA50/200; the feature filters are the long-side definitions applied unchanged to short signals (not mirrored); baseline
controls use stop0 = 1.1 x close. Each mirror is its own tag.

Tags (naming grammar, never pooled with the lab tags):  minervini_vcp__<labvariant>_srcmain__<dir>__1d__h60__v1
  e.g. minervini_vcp__pct8_hard_f_dryup_on_srcmain__long__1d__h60__v1.  `source_tag` names the lab row it re-measures.

Jobs (env TF = job name; run via sector-rotation-backtest.yml with script=scripts/minervini_lab_main_replay_job.py,
tf=<job>, results=docs/backtest_data/minervini_lab_main_replay_<job>.json; each sized well under the 90-min timeout):
  long            15 exit variants + every feature filter on/off for base and pct8_hard + stopout cluster (long)
  short           the same set, short mirror
  baseline_long   lab control: every 10th bar entry, pct8_hard / rr3 / ma200_break exits (long)
  baseline_short  the same control, short mirror
Smoke: SYNTHETIC=1 (offline random-walk frames, NOT a result; written to out/ unless OUT_DIR) and/or SYMBOL_LIMIT=N.
Output: docs/backtest_data/minervini_lab_main_replay_<job>.json
"""
import json
import os
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
import bar_hygiene as bh  # noqa: E402

JOBS = ("long", "short", "baseline_long", "baseline_short", "long_h30", "long_h40")  # _hNN: max-hold sweep (B-1469)
MAXH = 60
IS_FRAC = 0.7
COOLDOWN = 5
FIRST_BAR = 210
BASELINE_VARIANTS = ("pct8_hard", "rr3", "ma200_break")
TOL = 1e-9


def new_tag(variant, direction, maxh=None):
    maxh = MAXH if maxh is None else maxh
    return f"minervini_vcp__{variant}_srcmain__{direction}__1d__h{maxh}__v1"


def source_tag(variant, direction, maxh=None):
    maxh = MAXH if maxh is None else maxh
    return f"minervini_vcp__{variant}__{direction}__1d__h{maxh}__v1"


def job_spec(job):
    if job not in JOBS:
        raise SystemExit(f"unknown job {job!r}; jobs: {JOBS}")
    direction = "short" if "short" in job else "long"
    return direction, job.startswith("baseline")


def synthetic_frame(seed, n=900):
    rng = np.random.default_rng(seed)
    drift = 0.0012 if seed % 2 == 0 else -0.0012
    r = rng.normal(drift, 0.018, n)
    c = 100 * np.exp(np.cumsum(r))
    o = c * (1 + rng.normal(0, 0.004, n))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.008, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.008, n)))
    v = rng.integers(1e5, 1e6, n).astype(float)
    v[rng.random(n) < 0.08] *= 3.0
    return pd.DataFrame({"Open": o, "High": hi, "Low": lo, "Close": c, "Volume": v},
                        index=pd.bdate_range("2020-01-01", periods=n))


def load_frames(m, limit=None):
    if os.environ.get("SYNTHETIC") == "1":
        return {f"SYN{k}": synthetic_frame(k) for k in range(limit or 6)}, 0, limit or 6
    import yfinance as yf
    syms = sorted(set(m._load_nse_universe_from_file()))
    syms = [s for s in syms if s not in m.ETF_SYMBOLS]
    if limit:
        syms = syms[:limit]
    frames, dropped = {}, 0
    for b0 in range(0, len(syms), 50):
        batch = syms[b0:b0 + 50]
        try:
            d = yf.download(batch, period="6y", interval="1d", group_by="ticker", auto_adjust=True, progress=False,
                            threads=True)
        except Exception as ex:
            print("batch fail", b0, ex, flush=True)
            continue
        for s in batch:
            try:
                df = d[s].dropna(subset=["Close"]) if len(batch) > 1 else d.dropna(subset=["Close"])
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
                g = bh.clean_bars(df)
            except Exception:
                continue
            dropped += len(df) - len(g)
            if len(g) >= 300:
                g.index = pd.DatetimeIndex(g.index).tz_localize(None)
                frames[s] = g
        print("download", b0, len(frames), flush=True)
    return frames, dropped, len(syms)


def load_index(frames):
    if os.environ.get("SYNTHETIC") == "1":
        return pd.DataFrame({s: f["Close"] for s, f in frames.items()}).mean(axis=1)
    import yfinance as yf
    ix = yf.download("^NSEI", period="6y", interval="1d", auto_adjust=True, progress=False)
    if isinstance(ix.columns, pd.MultiIndex):
        ix.columns = ix.columns.get_level_values(0)
    ic = ix["Close"].dropna()
    ic.index = pd.DatetimeIndex(ic.index).tz_localize(None)
    return ic


def strategy_signals(m, df, direction):
    """Lab-thinned signal list [(i, entry, stop0, atr)] from the REAL main entry fn."""
    fn = m.minervini_vcp_entry_signal if direction == "long" else m.minervini_vcp_entry_signal_short
    c = df["Close"].to_numpy(float)
    v = df["Volume"].to_numpy(float)
    ma50 = pd.Series(c).rolling(50).mean().to_numpy()
    va = pd.Series(v).rolling(m.MINERVINI_VOL_LOOKBACK).mean().shift(1).to_numpy()
    out, last = [], -10
    for i in range(FIRST_BAR, len(df) - 2):
        if i - last < COOLDOWN:
            continue
        trend = c[i] > ma50[i] * (1 - TOL) if direction == "long" else c[i] < ma50[i] * (1 + TOL)
        if not trend or not (va[i] > 0) or v[i] < m.MINERVINI_VOL_SURGE_MULT * va[i] * (1 - TOL):
            continue
        try:
            sig = fn(df.iloc[: i + 1], None)
        except Exception:
            sig = None
        if sig:
            out.append((i, float(sig["entry_price"]), float(sig["stop_loss"]), float(sig["atr_at_entry"])))
            last = i
    return out


def baseline_signals(df, direction):
    c = df["Close"].to_numpy(float)
    k = 0.9 if direction == "long" else 1.1
    return [(i, float(c[i]), float(c[i]) * k, 1.0) for i in range(FIRST_BAR, len(df) - 2, 10)]


def walk(m, variant, df, arrs, sigs, direction, cost, accept=None):
    """Strict one position per symbol: a signal at or before the previous trade's exit bar is skipped."""
    o, h, l, c, mas = arrs
    sgn = 1.0 if direction == "long" else -1.0
    trades, free_from = [], 0
    for sg in sigs:
        i = sg[0]
        if i < free_from or (accept is not None and not accept(i)):
            continue
        r = m.minervini_lab_simulate_trade(variant, o, h, l, c, sg, direction, MAXH, mas)
        if r is None:
            continue
        x, px, held, reason, ent = r
        g = sgn * (px / ent - 1)
        trades.append({"gross": g, "net": g - cost, "held": held, "reason": reason, "entry_date": df.index[i + 1]})
        free_from = x + 1
    return trades


def summarize(trades, split_date):
    mt = H.metrics(trades)
    if trades:
        r = np.sort(np.array([t["net"] for t in trades]))
        tr = r[:-max(1, int(len(r) * 0.01))]
        tl = -tr[tr < 0].sum()
        mt["pfnet_trim1"] = round(float(tr[tr > 0].sum() / tl), 4) if tl > 0 else None
        mt["median_net_pct"] = round(float(np.median(r) * 100), 4)
    for k, sel in (("is", [t for t in trades if t["entry_date"] < split_date]),
                   ("oos", [t for t in trades if t["entry_date"] >= split_date])):
        s = H.metrics(sel)
        mt[k] = {x: s[x] for x in ("n", "pfnet", "pfgross", "win_pct", "avg_net_pct", "avg_held_bars")}
    mt["oos_pfnet"] = mt["oos"]["pfnet"]
    return mt


def run(job):
    import main as m
    global MAXH
    direction, baseline = job_spec(job)
    if "_h" in job:
        MAXH = int(job.rsplit("_h", 1)[1])
    lim = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    t0 = time.time()
    frames, dropped, requested = load_frames(m, lim)
    print(f"minervini_lab_main_replay job={job}: {len(frames)} symbols with >=300 bars of {requested}", flush=True)
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    all_dates = sorted(set().union(*[set(f.index) for f in frames.values()])) if frames else []
    split_date = all_dates[int(len(all_dates) * IS_FRAC)] if all_dates else None
    acc = {}
    nsig = 0
    if baseline:
        for s, df in frames.items():
            o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
            arrs = (o, h, l, c, m.minervini_lab_moving_averages(c))
            sigs = baseline_signals(df, direction)
            nsig += len(sigs)
            for v in BASELINE_VARIANTS:
                acc.setdefault("baseline_" + v, []).extend(walk(m, v, df, arrs, sigs, direction, cost))
    else:
        ic = load_index(frames)
        sma50, sma200 = ic.rolling(50).mean(), ic.rolling(200).mean()
        reg50 = (ic > sma50) if direction == "long" else (ic < sma50)
        reg200 = (ic > sma200) if direction == "long" else (ic < sma200)
        closes = pd.DataFrame({s: f["Close"] for s, f in frames.items()})
        highs = pd.DataFrame({s: f["High"] for s, f in frames.items()})
        lows = pd.DataFrame({s: f["Low"] for s, f in frames.items()})
        rs_rank, nhnl_ok = m.minervini_lab_rs_nhnl_panels(closes, highs, lows)
        cluster_stream = []
        for k, (s, df) in enumerate(frames.items()):
            sigs = strategy_signals(m, df, direction)
            if k % 200 == 0:
                print("signals", k, nsig, round(time.time() - t0), flush=True)
            if not sigs:
                continue
            nsig += len(sigs)
            dates = df.index
            o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
            arrs = (o, h, l, c, m.minervini_lab_moving_averages(c))
            r50 = reg50.reindex(dates, method="ffill").fillna(False).to_numpy(bool)
            r200 = reg200.reindex(dates, method="ffill").fillna(False).to_numpy(bool)
            idx_arr = ic.reindex(dates, method="ffill").to_numpy(float)
            rs_arr = rs_rank[s].reindex(dates).to_numpy(float)
            nn_arr = nhnl_ok.reindex(dates).fillna(False).to_numpy(bool)
            feats = {}
            for sg in sigs:
                i = sg[0]
                try:
                    feats[i] = m.minervini_lab_features(df, i, idx_arr, None if np.isnan(rs_arr[i]) else rs_arr[i], nn_arr[i])
                except Exception:
                    feats[i] = {}
            for v in m.MINERVINI_LAB_EXIT_VARIANTS:
                acc_fn = (lambda i: bool(r50[i])) if v == "regime_nifty50" else (lambda i: bool(r200[i])) if v == "regime_nifty200" else None
                tr = walk(m, v, df, arrs, sigs, direction, cost, acc_fn)
                acc.setdefault(v, []).extend(tr)
                if v == "pct8_hard":
                    cluster_stream.extend(tr)
            for ex in ("base", "pct8_hard"):
                for name in m.MINERVINI_LAB_FEATURE_NAMES:
                    for flag in ("on", "off"):
                        want = flag == "on"
                        okf = (lambda i, name=name, want=want: name in feats.get(i, {}) and bool(feats[i][name]) == want)
                        acc.setdefault(f"{ex}_f_{name}_{flag}", []).extend(walk(m, ex, df, arrs, sigs, direction, cost, okf))
        cluster_stream.sort(key=lambda t: t["entry_date"])
        flags = m.minervini_lab_stopout_cluster_flags([t["net"] for t in cluster_stream])
        acc["pct8_hard_f_after_stopout_cluster_on"] = [t for t, f in zip(cluster_stream, flags) if f]
        acc["pct8_hard_f_after_stopout_cluster_off"] = [t for t, f in zip(cluster_stream, flags) if not f]
    rows = {}
    for v, trades in acc.items():
        if not trades:
            continue
        rows[new_tag(v, direction)] = {
            "variant": v, "direction": direction, "source_tag": source_tag(v, direction), "metrics": summarize(trades, split_date),
            "note": ("stopout-cluster flag reads earlier-entered trades' final results (lab look-ahead, ported verbatim)"
                     if "stopout_cluster" in v else None)}
    out = {"job": job, "direction": direction, "tf": "1d", "max_hold_bars": MAXH, "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT,
           "universe": "main._load_nse_universe_from_file() minus ETF_SYMBOLS", "universe_requested": requested,
           "n_symbols": len(frames), "bars_dropped_glitch": dropped, "n_signals": nsig, "is_frac": IS_FRAC,
           "is_oos_split_date": str(split_date)[:10] if split_date is not None else None,
           "one_position_per_symbol": True,
           "entry_source": ("lab control: every 10th bar" if baseline else
                            f"main.{'minervini_vcp_entry_signal' if direction == 'long' else 'minervini_vcp_entry_signal_short'} (real, RS gate skipped)"),
           "exit_source": "main.minervini_lab_simulate_trade / main.minervini_lab_exit_reason (port of scripts/minervini_lab.run_variant)",
           "synthetic": os.environ.get("SYNTHETIC") == "1", "elapsed_s": round(time.time() - t0, 1), "rows": rows}
    # a synthetic smoke never overwrites a real result file
    od = os.environ.get("OUT_DIR") or (os.path.join(ROOT, "out") if out["synthetic"] else os.path.join(ROOT, "docs", "backtest_data"))
    os.makedirs(od, exist_ok=True)
    path = os.path.join(od, f"minervini_lab_main_replay_{job}.json")
    json.dump(out, open(path, "w"), indent=1, default=str)
    print("wrote", path, "elapsed", out["elapsed_s"], flush=True)
    for t, r in sorted(rows.items(), key=lambda kv: -(kv[1]["metrics"]["pfnet"] or 0))[:40]:
        mt = r["metrics"]
        print(t, mt["pfnet"], mt["pfgross"], mt["win_pct"], mt["n"], mt["avg_held_bars"], mt["oos_pfnet"], flush=True)
    return out


if __name__ == "__main__":
    run(os.environ.get("TF", "long"))
