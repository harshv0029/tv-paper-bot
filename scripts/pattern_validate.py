"""Out-of-sample re-run of the pattern-lab cells wired live (and the best others), on symbols the lab never saw.
The lab scanned ~2,300 cells in-sample, so its winners are inflated by selection. Rule + hold + ATR stop are
re-simulated on a seeded 500-symbol sample of the full NSE universe minus the swing watchlist and ETFs.
Output docs/pattern_validate_results.json keyed by the live tag (stock-universe tags)."""
import importlib.util, json, os, random, sys, warnings
import numpy as np
warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["UNI"] = "n200"
spec = importlib.util.spec_from_file_location("pattern_lab", os.path.join(ROOT, "scripts", "pattern_lab.py"))
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)
OUT = os.path.join(ROOT, "docs", "pattern_validate_results.json")
CELLS = {
    "gap__runaway__long__1d__atr6_h20__v1": ("gap_runaway", 20, 6.0),
    "starc__fade__long__1d__atr6_h20__v1": ("starc_fade", 20, 6.0),
    "donchian__8wk_fade__long__1d__atr6_h20__v1": ("donchian_8wk_fade", 20, 6.0),
    "envelope__0d05_fade__long__1d__atr6_h20__v1": ("envelope_0d05_fade", 20, 6.0),
    "baseline__every_bar__long__1d__atr6_h20__v1": ("baseline_every_bar", 20, 6.0),
}


def main_run():
    import yfinance as yf
    import main as app
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    seen = set(app.SWING_WATCHLIST)
    pool = [s for s in app._load_nse_universe_from_file() if s not in seen and s not in app.ETF_SYMBOLS]
    random.Random(11).shuffle(pool)
    pool = pool[:500]
    acc = {t: [[], []] for t in CELLS}
    done = 0
    for b0 in range(0, len(pool), 100):
        batch = pool[b0:b0 + 100]
        try:
            d = yf.download(batch, period="5y", interval="1d", group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception as ex:
            print("batch fail", ex)
            continue
        for s in batch:
            try:
                df = pl.clean_bars(d[s].dropna(subset=["Close"])[["Open", "High", "Low", "Close", "Volume"]].dropna())
            except Exception:
                continue
            if len(df) < 200:
                continue
            sigs = pl.all_signals(df)
            o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
            atr = pl.atr_arr(h, l, c)
            for t, (rule, H, k) in CELLS.items():
                if rule not in sigs:
                    continue
                r, hd = pl.simulate(np.asarray(sigs[rule][0], bool), o, h, l, c, atr, H, k, cost, 1)
                if r:
                    acc[t][0].extend(r)
                    acc[t][1].extend(hd)
            done += 1
        print("oos symbols", done, flush=True)
    res = {}
    for t, (r, hd) in acc.items():
        if len(r) < 100:
            continue
        r = np.array(r)
        g, lo = r[r > 0].sum(), -r[r < 0].sum()
        rs = np.sort(r)
        tr = rs[:-max(1, int(len(rs) * 0.01))]
        tl = -tr[tr < 0].sum()
        res[t] = {"pfnet": round(float(g / lo), 3) if lo else None, "pfnet_trim1": round(float(tr[tr > 0].sum() / tl), 3) if tl else None,
                  "win_pct": round(float((r > 0).mean() * 100), 1), "n": int(len(r)), "median_net_pct": round(float(np.median(r) * 100), 3),
                  "avg_net_pct": round(float(r.mean() * 100), 3), "avg_held_bars": round(float(np.mean(hd)), 2), "oos_symbols": done}
    json.dump({"results": res}, open(OUT, "w"), indent=0)
    for t, m in res.items():
        print(t, m)


if __name__ == "__main__":
    main_run()
