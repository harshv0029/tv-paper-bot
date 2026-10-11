"""MCX live-path replay (design 2026-10-11). Replays registry MCX proxy cells through the REAL
main._mcx_daily_flags (the exact function _run_mcx_daily_scan calls live), bar by bar on growing
prefixes, so signal drift between the sweep (main.add_strategy_signal on the whole series) and the
live scan is measured, not assumed. Trades: entry next-bar open on a fresh flag, exit next-bar open
when the flag drops, optional underlying ATR(14)*k stop on bar low (k from the tag: atr1d5/atr2d5).
Net of main.ROUND_TRIP_COST_PCT. Output rows keep every field (pfnet, win_pct, n, avg_net_pct,
avg_held_days, exit-reason counts, registry pfnet/n for comparison). Underlying-only: the option
premium trailing SL is NOT simulated (no premium history exists) - stated in every output.
Usage: python scripts/mcx_live_replay.py [--cells all|wired|unwired|tag1,tag2] [--out path]"""
import argparse, json, os, re, sys, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import main
import strategy_registry as sr

SYM = {"gc": "GC=F", "si": "SI=F", "cl": "CL=F", "ng": "NG=F", "hg": "HG=F"}
PARAMS = {"sma_crossover": {"fast": 9, "slow": 21}, "rsi_reversal": {"rsi_period": 14, "oversold": 30, "overbought": 70}}
_TAG = re.compile(r"^([a-z0-9_]+?)__(gc|si|cl|ng|hg)__(long|short)__1d__(atrnone|atr\d+d\d+)__v\d+$")


def parse_tag(tag):
    """-> (strategy, proxy_symbol, is_short, atr_k or None) or None for a non-MCX-1d tag."""
    m = _TAG.match(tag)
    if not m:
        return None
    st, sk, d, a = m.groups()
    k = None if a == "atrnone" else float(a[3:].replace("d", "."))
    return st, SYM[sk], d == "short", k


def registry_mcx_cells():
    return [s for s in sr.REGISTRY if parse_tag(s.name) and s.is_viable()]


def _atr(df, n=14):
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def mirror(df):
    m = df.copy()
    m["Open"], m["Close"] = 1 / df["Open"], 1 / df["Close"]
    m["High"], m["Low"] = 1 / df["Low"], 1 / df["High"]
    return m


def live_flags(df, strat, params, short, warmup=60):
    """Per-bar (fresh, on) from the REAL main._mcx_daily_flags on each prefix. ist_now is pinned far
    in the future so the function's 'drop today's forming bar' rule never trims a replay bar."""
    real = main.ist_now
    main.ist_now = lambda: pd.Timestamp("2100-01-01")
    try:
        fresh = np.zeros(len(df), bool)
        on = np.zeros(len(df), bool)
        for i in range(warmup, len(df)):
            f, o = main._mcx_daily_flags(df.iloc[: i + 1], strat, dict(params), short=short)
            fresh[i], on[i] = f, o
    finally:
        main.ist_now = real
    return fresh, on


def simulate(df, fresh, on, k, short):
    """Trades on the traded-direction series (reciprocal for shorts, like the live flags)."""
    src = mirror(df) if short else df
    o, l, c = (src[x].to_numpy(float) for x in ("Open", "Low", "Close"))
    a = _atr(src).to_numpy(float)
    cost = main.ROUND_TRIP_COST_PCT / 100
    n = len(src)
    rets, held, why = [], [], []
    i = 1
    while i < n - 1:
        if fresh[i - 1] and not np.isnan(a[i - 1]):
            e = o[i]
            stop = e - k * a[i - 1] if k else None
            j = i
            x = None
            r = "end_of_data"
            while j < n:
                if stop is not None and l[j] <= stop:
                    x = min(stop, o[j])
                    r = "atr_stop"
                    break
                if j + 1 < n and not on[j]:
                    x = o[j + 1]
                    j += 1
                    r = "signal_drop"
                    break
                j += 1
            if x is None:
                x = c[n - 1]
                j = n - 1
            rets.append(x / e - 1 - cost)
            held.append(j - i + 1)
            why.append(r)
            i = j + 1
        else:
            i += 1
    return rets, held, why


def stats(rets, held, why):
    if not rets:
        return {"pfnet": None, "win_pct": None, "n": 0, "avg_net_pct": None, "avg_held_days": None, "exits": {}}
    r = np.array(rets)
    w = r[r > 0].sum()
    lo = -r[r < 0].sum()
    return {"pfnet": round(float(w / lo), 3) if lo > 0 else None, "win_pct": round(100 * float((r > 0).mean()), 1),
            "n": len(r), "avg_net_pct": round(100 * float(r.mean()), 3),
            "avg_held_days": round(float(np.mean(held)), 2), "exits": {x: why.count(x) for x in sorted(set(why))}}


def _download(sym):
    import yfinance as yf
    d = yf.download(sym, period="5y", interval="1d", auto_adjust=True, progress=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    return d.dropna()[["Open", "High", "Low", "Close", "Volume"]]


def replay_cell(tag, df=None):
    p = parse_tag(tag)
    if p is None:
        raise ValueError(f"not an MCX 1d tag: {tag}")
    strat, sym, short, k = p
    if df is None:
        df = _download(sym)
    fresh, on = live_flags(df, strat, PARAMS.get(strat, {}), short)
    return stats(*simulate(df, fresh, on, k, short))


def main_cli(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="unwired")
    ap.add_argument("--out", default="docs/mcx_live_replay_results.json")
    a = ap.parse_args(argv)
    wired = {c[0] for c in main._MCX_DAILY_CELLS}
    cells = registry_mcx_cells()
    if a.cells == "wired":
        cells = [s for s in cells if s.name in wired]
    elif a.cells == "unwired":
        cells = [s for s in cells if s.name not in wired]
    elif a.cells != "all":
        want = set(a.cells.split(","))
        cells = [s for s in cells if s.name in want]
    cache, out = {}, {}
    for s in cells:
        sym = parse_tag(s.name)[1]
        if sym not in cache:
            cache[sym] = _download(sym)
        res = replay_cell(s.name, cache[sym])
        res.update({"registry_pfnet": s.metrics.pfnet, "registry_n": s.metrics.n_trades, "wired": s.name in wired,
                    "note": "underlying-only replay of the live signal fn; option-premium trailing SL not simulated"})
        out[s.name] = res
        print(s.name, res["pfnet"], res["n"], "reg", s.metrics.pfnet, s.metrics.n_trades, flush=True)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=1)
    return out


if __name__ == "__main__":
    main_cli()
