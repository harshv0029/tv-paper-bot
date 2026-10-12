"""B-343/B-344 Part A: MCX commodity strategy sweep, BOTH directions, ATR x candle size.

Proxies (yfinance has no MCX ticker; same convention as the live paper engine):
GC=F gold, SI=F silver, CL=F crude, NG=F natural gas, HG=F copper.
Signals come from the REAL main.add_strategy_signal (long flag). Short = the same
signal run on the reciprocal price series (1/P), which mirrors returns.
Entry next-bar open; exit when flag drops (next open) or at ATR(14)*k stop on bar
low. Net of main.ROUND_TRIP_COST_PCT (0.8%, conservative; MCX futures are cheaper,
so this understates PFnet). Timeframes: 5m/15m (60d), 1h (730d), 1d (5y);
4h: GC/SI/CL/NG/HG trade ~23h on CME so the NSE-session helper scripts/resample_4h.py does
not apply (pass session_open_minute for a custom anchor); still owed for MCX. Output docs/mcx_sweep_results.json.
"""
import json, sys, warnings
import numpy as np, pandas as pd, yfinance as yf
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

SYMS = {"gc": "GC=F", "si": "SI=F", "cl": "CL=F", "ng": "NG=F", "hg": "HG=F"}
TFS = {"5m": ("5m", "60d", 5 / 60), "15m": ("15m", "60d", 15 / 60), "1h": ("1h", "730d", 1.0), "1d": ("1d", "5y", 6.25)}
STRATS = {
    "sma_crossover": {"fast": 9, "slow": 21},
    "rsi_reversal": {"rsi_period": 14, "oversold": 30, "overbought": 70},
    "bollinger_mean_reversion": {},
    "supertrend": {},
    "keltner_channel_breakout": {},
    "donchian_breakout": {},
}
KS = (0, 1.5, 2.5)
COST = 0.008  # = main.ROUND_TRIP_COST_PCT / 100 (0.8%); main_run() re-reads it from main


def atr(df, n=14):
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def mirror(df):
    m = df.copy()
    m["Open"], m["Close"] = 1 / df["Open"], 1 / df["Close"]
    m["High"], m["Low"] = 1 / df["Low"], 1 / df["High"]
    return m


def trade(df, flag, k, bar_h, stops=None):
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    a = atr(df).to_numpy(float)
    f = flag.to_numpy(bool)
    rets, held, i, n = [], [], 1, len(df)
    while i < n - 1:
        if f[i - 1] and not (f[i - 2] if i >= 2 else False) and not np.isnan(a[i - 1]):
            e = o[i]; stop = e - k * a[i - 1] if k else None; j = i; x = None
            while j < n:
                if stop is not None and l[j] <= stop:
                    x = min(stop, o[j]); break
                if j + 1 < n and not f[j]:
                    x = o[j + 1]; j = j + 1; break
                j += 1
            if x is None:
                x = c[n - 1]; j = n - 1
            rets.append(x / e - 1 - COST); held.append((j - i + 1) * bar_h)
            if stops is not None and k:
                stops.append(100.0 * k * a[i - 1] / e)  # planned stop-% of entry (B-775)
            i = j + 1
        else:
            i += 1
    return rets, held


def stats(r, hrs, cost=COST, stops=None):
    if not r:
        return None
    r = np.array(r); w = r[r > 0].sum(); L = -r[r < 0].sum()
    rg = r + cost; gg = rg[rg > 0].sum(); gl = -rg[rg < 0].sum()  # B-804 gross PFnet (round-trip cost added back)
    return {"pfnet": round(float(w / L), 3) if L > 0 else None, "pfgross": round(float(gg / gl), 3) if gl > 0 else None,
            "median_stop_pct": round(float(np.median(stops)), 4) if stops else None,
            "win_pct": round(100 * float((r > 0).mean()), 1),
            "n": len(r), "avg_net_pct": round(100 * float(r.mean()), 3), "avg_held_hrs": round(float(np.mean(hrs)), 2)}


def main_run():
    global COST
    import main
    COST = main.ROUND_TRIP_COST_PCT / 100
    out = {}
    for sk, sym in SYMS.items():
        for tf, (iv, per, bh) in TFS.items():
            try:
                df = yf.download(sym, period=per, interval=iv, auto_adjust=True, progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.dropna()[["Open", "High", "Low", "Close", "Volume"]]
            except Exception as e:
                print("fetch fail", sym, tf, e); continue
            if len(df) < 200:
                print("too short", sym, tf, len(df)); continue
            for d, src in (("long", df), ("short", mirror(df))):
                for st, pr in STRATS.items():
                    try:
                        flag = main.add_strategy_signal(src, st, dict(pr))["long"].fillna(False).astype(bool)
                    except Exception as e:
                        print("sig fail", st, e); continue
                    for k in KS:
                        sp = []
                        r, hr = trade(src, flag, k, bh, stops=sp)
                        s = stats(r, hr, COST, sp)
                        if s:
                            ktag = "none" if not k else str(k).replace(".", "d")
                            out[f"{st}__{sk}__{d}__{tf}__atr{ktag}__v1"] = s
        print("done", sym, len(out), flush=True)

    json.dump(out, open("docs/mcx_sweep_results.json", "w"), indent=1)
    ok = {t: s for t, s in out.items() if s["pfnet"] and s["pfnet"] > 1 and s["n"] >= 30}
    print(f"cells={len(out)} viable(PFnet>1,n>=30)={len(ok)}")
    for t, s in sorted(ok.items(), key=lambda kv: -kv[1]["pfnet"])[:15]:
        print(t, s)


if __name__ == "__main__":
    main_run()
