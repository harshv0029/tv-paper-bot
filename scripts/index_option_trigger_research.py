"""Index option TRIGGER research (backlog B-853): do the viable swing entry functions in main.py work as
index-direction triggers for a long call (LONG signal) or long put (mirrored SHORT signal)?

Why: the options category has no validated entry because option-premium history does not exist, and the
viable setups (power_play, primary_base, minervini_vcp_livermore, order_block_delta, gap_and_go) are daily-chart
swing patterns validated on stocks. This script runs the REAL main.py entry functions on INDEX underlying candles
(^NSEI, ^NSEBANK, ^BSESN) and scores the underlying move after each trigger. It is a trigger-quality test, NOT an
option P&L backtest: no premium, delta, theta or IV is modelled.

Conventions (CLAUDE.md thumb rules):
  * entry functions are main.<name>_entry_signal called on the trailing WINDOW bars ending at bar i (signal on the
    CLOSE of bar i, fill at that close, exactly as the live functions return entry_price). primary_base is given the
    FULL history (its IPO-recency proxy is len(df) <= 756 bars, so a truncated window would fake a young listing);
    on an index it will almost never fire, and that is reported, not hidden.
  * BOTH directions: LONG (=> buy call) and SHORT (=> buy put). The short is the reciprocal-price mirror
    (o'=1/o, h'=1/l, l'=1/h, c'=1/c) fed to the same long function, simulated in that frame, and PnL is then
    computed on the REAL prices (short return = 1 - exit/entry). Each is its own tag, never pooled.
  * exit: chandelier close-trail (running max close - ATR_MULT x ATR frozen at entry, never below the entry
    signal's initial stop) + MAX_HOLD bars. A stop is attached to every trade (no atrnone cell), matching the
    trailing-SL-only rule for single-strike options. ATR sweep ATR_MULTS.
  * STRICT non-overlap FIFO: one position per (index, strategy, direction, atr) at a time; a new signal is ignored
    until the open trade has exited.
  * IS/OOS split: first IS_FRAC (70%) of each index's bars is in-sample, the rest out-of-sample, by entry bar.
  * costs: 0.8% round trip applied to the UNDERLYING return is the repo's stock cost model and is far too harsh for
    an index (index moves are small) while option leverage amplifies the move; so PFnet at COST_PCTS (default
    0.8 and 0.1) and gross are all emitted. Do not read any of them as premium P&L.
  * volume: yfinance index volume is often 0. Volume-gated entries (power_play, order_block, gap_and_go, vcp,
    primary_base) then cannot fire; bars_with_volume is emitted per index so a zero-trade cell is explained.
  * bar-count constants in main.py (lookbacks, hold days) are written for DAILY bars; at 5m/15m/1h they mean bars,
    not days. Stated, not re-derived.
Env: INTERVAL (5m|15m|1h|4h|1d, default 1d; 4h = 1h resample), SYMBOLS (default ^NSEI,^NSEBANK,^BSESN), ATR_MULTS (default 2,3,4.5,6),
MAX_HOLD (bars, default 30), WINDOW (default 500), COST_PCTS, IS_FRAC, OUT (json path), SYNTHETIC=1 (offline dry run,
no network, random-walk data). Output "cells" keyed <strategy>__<dir>__<tf>__atr<m>; registry registration is
deliberately OWED until a real run exists.
"""
import json
import os
import sys
import zlib

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PERIOD = {"5m": "60d", "15m": "60d", "1h": "730d", "4h": "730d", "1d": "10y"}  # 4h = 1h resample
STRATEGIES = {
    "power_play": ("power_play_entry_signal", True),
    "primary_base": ("primary_base_entry_signal", False),
    "minervini_vcp_livermore": ("minervini_vcp_entry_signal_livermore_confirmed", True),
    "order_block_delta": ("order_block_entry_signal", True),
    "gap_and_go": ("gap_and_go_entry_signal", True),
}


def _fnum(x, default):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _norm(df):
    if df is None or len(df) == 0:
        return None
    df = df.reset_index()
    df = df.rename(columns={df.columns[0]: "Date"})
    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Open", "High", "Low", "Close"])
    df["Volume"] = df["Volume"].fillna(0.0)
    df["Date"] = df["Date"].astype(str)
    df = df[(df[["Open", "High", "Low", "Close"]] > 0).all(axis=1)].reset_index(drop=True)
    return df if len(df) else None


def resample_4h(df):
    """1h -> 4h: within each calendar date, group consecutive hourly bars in chunks of 4 (NSE 09:15 session gives
    4+3 bars/day). yfinance has no native 4h. Volume summed (still 0 for indexes)."""
    if df is None or len(df) == 0:
        return df
    d = df.copy()
    d["_day"] = d["Date"].astype(str).str[:10]
    d["_grp"] = d.groupby("_day").cumcount() // 4
    g = d.groupby(["_day", "_grp"], sort=True)
    return g.agg(Date=("Date", "first"), Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"),
                 Close=("Close", "last"), Volume=("Volume", "sum")).reset_index(drop=True)


def fetch(symbol, interval):
    import yfinance as yf
    src = "1h" if interval == "4h" else interval
    df = _norm(yf.Ticker(symbol).history(period=PERIOD[interval], interval=src, auto_adjust=False))
    return resample_4h(df) if interval == "4h" else df


def synthetic(symbol, n=900):
    rng = np.random.default_rng(zlib.crc32(symbol.encode()))
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, n)))
    opn = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.004, n))
    high = np.maximum(opn, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(opn, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    vol = rng.integers(1_000, 5_000, n).astype(float)
    vol[rng.random(n) < 0.05] *= 4
    dates = pd.date_range("2020-01-01", periods=n, freq="B").astype(str)
    return pd.DataFrame({"Date": dates, "Open": opn, "High": high, "Low": low, "Close": close, "Volume": vol})


def flip(df):
    out = df.copy()
    out["Open"], out["High"], out["Low"], out["Close"] = 1 / df["Open"], 1 / df["Low"], 1 / df["High"], 1 / df["Close"]
    return out


def wilder_atr(df, n=14):
    h, l, c = df["High"].to_numpy(float), df["Low"].to_numpy(float), df["Close"].to_numpy(float)
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


# ---- NON-VOLUME triggers (B-866): index bars carry zero volume, so these use price/ATR/trend/momentum only. ----
# Each returns a boolean numpy array over the frame it is given (the LONG frame; SHORT is run on flip(real), the
# reciprocal-price mirror, so a short signal = the same long rule in the mirrored frame). Signal fires on bar i's
# CLOSE using only data up to i (trailing/shifted stats only, no look-ahead).
NV_PARAMS = {"atr_range_break": "n20_k1d2", "orb": "or3", "ema_cross": "f9_s21", "rsi_thrust": "hi60_lo45_p14"}
NV_FAMILY = {  # (family, variant) per naming grammar <family>__<variant>__<dir>__<tf>__<params>__v1
    "atr_range_break": ("atr_range", "expansion_break"),
    "orb": ("opening_range", "break"),
    "ema_cross": ("ema", "cross"),
    "rsi_thrust": ("rsi", "thrust"),
}


def _rsi(close, n=14):
    c = pd.Series(close)
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50).to_numpy()


def trig_atr_range_break(df, n=20, k=1.2):
    """Bar range >= k x prior ATR AND close above the prior n-bar high (volatility-expansion breakout)."""
    atr = pd.Series(wilder_atr(df)).shift(1).to_numpy()
    rng = (df["High"] - df["Low"]).to_numpy(float)
    prior_hi = df["High"].shift(1).rolling(n).max().to_numpy(float)
    return (rng >= k * atr) & (df["Close"].to_numpy(float) > prior_hi)


def trig_orb(df, or_bars=3):
    """Intraday opening-range break: close above the high of the first or_bars bars of the session, first break per
    day only. On 1d (one bar/day) it never fires, by design."""
    day = df["Date"].astype(str).str[:10].to_numpy()
    hi, cl = df["High"].to_numpy(float), df["Close"].to_numpy(float)
    sig = np.zeros(len(df), bool)
    start, fired, orh = 0, False, np.nan
    for i in range(len(df)):
        if i == 0 or day[i] != day[i - 1]:
            start, fired, orh = i, False, np.nan
        pos = i - start
        if pos == or_bars - 1:
            orh = hi[start:i + 1].max()
        elif pos >= or_bars and not fired and cl[i] > orh:
            sig[i], fired = True, True
    return sig


def trig_ema_cross(df, fast=9, slow=21):
    c = df["Close"]
    f, s_ = c.ewm(span=fast, adjust=False).mean(), c.ewm(span=slow, adjust=False).mean()
    return ((f > s_) & (f.shift(1) <= s_.shift(1))).fillna(False).to_numpy()


def trig_rsi_thrust(df, hi=60.0, lo=45.0, n=14, look=10):
    """RSI crosses up through hi after having been below lo within the last `look` bars (momentum thrust)."""
    r = pd.Series(_rsi(df["Close"].to_numpy(float), n))
    crossed = (r > hi) & (r.shift(1) <= hi)
    was_low = r.shift(1).rolling(look).min() < lo
    return (crossed & was_low).fillna(False).to_numpy()


NV_TRIGGERS = {"atr_range_break": trig_atr_range_break, "orb": trig_orb, "ema_cross": trig_ema_cross,
               "rsi_thrust": trig_rsi_thrust}


def nv_tag(trig, direction, interval, atr_mult):
    fam, var = NV_FAMILY[trig]
    return f"{fam}__{var}__{direction}__{interval}__atr{str(atr_mult).replace('.', 'd')}_{NV_PARAMS[trig]}__v1"


def simulate_signals(real, trig, direction, atr_mult, max_hold):
    """Strict-FIFO scan on a precomputed non-volume signal array. Initial stop = entry - atr_mult x ATR (every trade
    carries a stop), then the same chandelier close-trail + MAX_HOLD as simulate()."""
    sim = real if direction == "long" else flip(real)
    sig = NV_TRIGGERS[trig](sim)
    atr = wilder_atr(sim)
    closes, rclose, dates = sim["Close"].to_numpy(float), real["Close"].to_numpy(float), real["Date"].to_numpy()
    trades, n, i = [], len(sim), 30
    while i < n - 1:
        if not sig[i] or not (atr[i] > 0):
            i += 1
            continue
        entry, a = closes[i], float(atr[i])
        stop0 = entry - atr_mult * a
        end = min(i + max_hold, n - 1)
        run_max, reason, j = entry, "max_hold_timeout", end
        for k in range(i + 1, end + 1):
            run_max = max(run_max, closes[k])
            if closes[k] <= max(stop0, run_max - atr_mult * a):
                reason, j = "trail_stop_hit", k
                break
        e_real, x_real = rclose[i], rclose[j]
        ret = (x_real / e_real - 1) if direction == "long" else (1 - x_real / e_real)
        trades.append({"i": i, "j": j, "entry_date": dates[i], "exit_date": dates[j], "hold_bars": j - i,
                       "ret": float(ret), "exit": reason})
        i = j + 1
    return trades


def simulate(main_mod, real, fn_name, windowed, direction, atr_mult, max_hold, window):
    """Strict-FIFO scan of one frame. Returns trades with real-price returns."""
    fn = getattr(main_mod, fn_name)
    sim = real if direction == "long" else flip(real)
    atr = wilder_atr(sim)
    closes = sim["Close"].to_numpy(float)
    rclose = real["Close"].to_numpy(float)
    dates = real["Date"].to_numpy()
    trades = []
    n = len(sim)
    i = 30  # warm-up
    while i < n - 1:
        sub = sim.iloc[max(0, i + 1 - window): i + 1] if windowed else sim.iloc[: i + 1]
        try:
            sig = fn(sub.reset_index(drop=True))
        except Exception:
            sig = None
        if not sig:
            i += 1
            continue
        entry = float(sig["entry_price"])
        stop0 = float(sig["stop_loss"])
        a = _fnum(sig.get("atr_at_entry"), float(atr[i]))
        if not (a > 0) or stop0 >= entry:
            i += 1
            continue
        end = min(i + max_hold, n - 1)
        run_max, reason, j = entry, "max_hold_timeout", end
        for k in range(i + 1, end + 1):
            run_max = max(run_max, closes[k])
            if closes[k] <= max(stop0, run_max - atr_mult * a):
                reason, j = "trail_stop_hit", k
                break
        e_real, x_real = rclose[i], rclose[j]
        ret = (x_real / e_real - 1) if direction == "long" else (1 - x_real / e_real)
        trades.append({"i": i, "j": j, "entry_date": dates[i], "exit_date": dates[j], "hold_bars": j - i,
                       "ret": float(ret), "exit": reason})
        i = j + 1  # strict FIFO: next signal only after exit
    return trades


def metrics(trades, cost_pcts):
    if not trades:
        return {"n": 0}
    r = np.array([t["ret"] for t in trades])

    def pf(x):
        w, l = x[x > 0].sum(), -x[x < 0].sum()
        return float(w / l) if l > 0 else (None if w > 0 else 0.0)  # None = no losing trade (infinite)

    out = {"n": len(trades), "win_pct_gross": float((r > 0).mean() * 100), "pfnet_gross": pf(r),
           "avg_hold_bars": float(np.mean([t["hold_bars"] for t in trades])), "avg_ret_pct_gross": float(r.mean() * 100),
           "net_by_cost_pct": {}}
    for c in cost_pcts:
        rn = r - c / 100.0
        out["net_by_cost_pct"][str(c)] = {"pfnet": pf(rn), "win_pct": float((rn > 0).mean() * 100),
                                          "avg_ret_pct": float(rn.mean() * 100)}
    ex = {}
    for t in trades:
        ex[t["exit"]] = ex.get(t["exit"], 0) + 1
    out["exit_reasons"] = ex
    return out


def run(interval, symbols, atr_mults, max_hold, window, cost_pcts, is_frac, synth):
    import main
    cells, volinfo, frames = {}, {}, {}
    for s in symbols:
        df = synthetic(s) if synth else fetch(s, interval)
        if df is None:
            volinfo[s] = {"bars": 0, "error": "no data"}
            continue
        frames[s] = df
        volinfo[s] = {"bars": len(df), "bars_with_volume": int((df["Volume"] > 0).sum())}
    for strat, (fn_name, windowed) in STRATEGIES.items():
        for direction in ("long", "short"):
            for am in atr_mults:
                key = f"{strat}__{direction}__{interval}__atr{str(am).replace('.', 'd')}"
                allt = {"all": [], "is": [], "oos": []}
                per_index = {}
                for s, df in frames.items():
                    tr = simulate(main, df, fn_name, windowed, direction, am, max_hold, window)
                    cut = int(len(df) * is_frac)
                    per_index[s] = metrics(tr, cost_pcts)
                    for t in tr:
                        allt["all"].append(t)
                        allt["is" if t["i"] < cut else "oos"].append(t)
                cells[key] = {"direction": direction, "option_leg": "buy_call" if direction == "long" else "buy_put",
                              "strategy": strat, "interval": interval, "atr_mult": am,
                              "pooled": {k: metrics(v, cost_pcts) for k, v in allt.items()}, "per_index": per_index}
    # Non-volume triggers (B-866): each (trigger, direction, atr) is its own grammar tag; call-proxy long, put-proxy short.
    for trig in NV_TRIGGERS:
        for direction in ("long", "short"):
            for am in atr_mults:
                key = nv_tag(trig, direction, interval, am)
                allt = {"all": [], "is": [], "oos": []}
                per_index = {}
                for s, df in frames.items():
                    tr = simulate_signals(df, trig, direction, am, max_hold)
                    cut = int(len(df) * is_frac)
                    per_index[s] = metrics(tr, cost_pcts)
                    for t in tr:
                        allt["all"].append(t)
                        allt["is" if t["i"] < cut else "oos"].append(t)
                cells[key] = {"direction": direction, "option_leg": "buy_call" if direction == "long" else "buy_put",
                              "strategy": trig, "volume_gated": False, "interval": interval, "atr_mult": am,
                              "pooled": {k: metrics(v, cost_pcts) for k, v in allt.items()}, "per_index": per_index}
    return {"interval": interval, "max_hold_bars": max_hold, "window": window, "cost_pcts": cost_pcts,
            "is_frac": is_frac, "synthetic": synth, "volume_info": volinfo, "cells": cells,
            "note": "underlying-move trigger test, not option premium P&L; zero-volume indexes cannot fire volume-gated entries"}


def main_cli():
    interval = os.environ.get("INTERVAL", "1d")
    symbols = [s for s in os.environ.get("SYMBOLS", "^NSEI,^NSEBANK,^BSESN").split(",") if s]
    atr_mults = [float(x) for x in os.environ.get("ATR_MULTS", "2,3,4.5,6").split(",")]
    cost_pcts = [float(x) for x in os.environ.get("COST_PCTS", "0.8,0.1").split(",")]
    res = run(interval, symbols, atr_mults, int(os.environ.get("MAX_HOLD", "30")), int(os.environ.get("WINDOW", "500")),
              cost_pcts, float(os.environ.get("IS_FRAC", "0.7")), os.environ.get("SYNTHETIC") == "1")
    out = os.environ.get("OUT", f"docs/index_option_trigger_results_{interval}.json")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as f:
        json.dump(res, f, indent=1, default=str)
    for k, c in res["cells"].items():
        p = c["pooled"]["all"]
        if p.get("n"):
            print(k, "n", p["n"], "win_gross %.1f" % p["win_pct_gross"], "pfnet_gross", p["pfnet_gross"],
                  "pfnet@0.8", p["net_by_cost_pct"].get("0.8", {}).get("pfnet"),
                  "hold %.1f" % p["avg_hold_bars"], p["exit_reasons"])
        else:
            print(k, "n 0")
    print("volume_info", res["volume_info"])


if __name__ == "__main__":
    main_cli()
