"""Ernest Chan (Algorithmic Trading) research pass, backlog rows B-424..B-436, B-440, B-447(partial), B-452.
Daily/hourly OHLCV only. Every strategy is run LONG and SHORT as separate tags, ATR stop on every trade
(k swept, no stopless cell), 0.8% round-trip cost (main.ROUND_TRIP_COST_PCT), full universe from
main._load_nse_universe_from_file(). Naming: <family>__<variant>__<dir>__<tf>__<params>__v1.
Modes:  run   (env SHARD, NSHARD, INTERVAL, OUT_DIR, MAXSYM)  -> one shard json
        merge (env IN_DIR, OUT)                                -> pooled results json + table
PFnet is computed on per-trade fractional returns (equal weight, same convention as overnight_anomaly.py).
Cross-sectional rows (B-424..B-430) need the whole universe per day, so shards emit pruned candidate rows and
merge does the per-day top-N / decile selection. Shorts held overnight are not MIS-legal; registered anyway."""
import json, math, os, sys, glob
import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
KS = (1.5, 2.5, 4.0)          # ATR-stop multiples; no stopless cell (SL on every trade)
LIQ_MIN_TURNOVER = 2e7        # INR, median 20-bar close*volume, xs modes only
LOCAL_KEEP = 0.20             # shard-level prune fraction for decile modes


def kfmt(x):
    return str(x).replace(".", "d")


def atr_arr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out = np.full(len(c), np.nan)
    if len(c) > n:
        cs = np.cumsum(np.r_[0, tr])
        out[n:] = (cs[n + 1:] - cs[1:len(c) - n + 1]) / n
    return out


def day_returns(E, o, h, l, c, A, k, side, gap_aware=False):
    """Gross fractional return of a one-bar trade entered at E, stop k*A away, exit at close. Vectorised.
    gap_aware: bar opens through the stop -> exit at the open (entry before the bar, e.g. at prior close)."""
    E, o, h, l, c, A = (np.atleast_1d(np.asarray(x, float)) for x in (E, o, h, l, c, A))
    if side == 1:
        stop = E - k * A
        hit = l <= stop
        px = np.where(hit, np.minimum(stop, o) if gap_aware else stop, c)
        return px / E - 1, hit
    stop = E + k * A
    hit = h >= stop
    px = np.where(hit, np.maximum(stop, o) if gap_aware else stop, c)
    return 1 - px / E, hit


def simulate(o, h, l, c, atr, sig, k, hold, exit_long=None, exit_short=None):
    """Signal at close of bar i (sig[i] = +1/-1), entry at open of i+1, stop k*ATR[i] (gap-aware),
    exit on stop / state-exit array / `hold` bars / data end. Non-overlapping.
    Returns list of (side, entry_i, exit_i, gross_ret, reason)."""
    n = len(c)
    out = []
    i = 0
    while i < n - 2:
        s = sig[i]
        if s == 0 or np.isnan(atr[i]) or atr[i] <= 0 or o[i + 1] <= 0:
            i += 1
            continue
        e = i + 1
        ep = o[e]
        stop = ep - k * atr[i] if s == 1 else ep + k * atr[i]
        xi, xp, why = None, None, None
        for j in range(e, min(n, e + hold)):
            if s == 1 and l[j] <= stop:
                xi, xp, why = j, (min(stop, o[j]) if j > e else stop), "stop"
                break
            if s == -1 and h[j] >= stop:
                xi, xp, why = j, (max(stop, o[j]) if j > e else stop), "stop"
                break
            ex = exit_long if s == 1 else exit_short
            if ex is not None and ex[j]:
                xi, xp, why = j, c[j], "state_exit"
                break
        if xi is None:
            xi = min(n, e + hold) - 1
            xp, why = c[xi], "max_hold"
        out.append((int(s), e, xi, (xp / ep - 1) if s == 1 else (1 - xp / ep), why))
        i = xi + 1
    return out


def stats(net, gross, hold, reasons):
    net, gross = np.asarray(net, float), np.asarray(gross, float)
    if len(net) == 0:
        return None

    def pf(r):
        g, ls = r[r > 0].sum(), -r[r < 0].sum()
        return round(float(g / ls), 3) if ls > 0 else None
    return {"pfnet": pf(net), "pfgross": pf(gross), "win_pct": round(float((net > 0).mean() * 100), 1),
            "n": int(len(net)), "avg_net_pct": round(float(net.mean() * 100), 4),
            "avg_hold_bars": round(float(np.mean(hold)), 2) if len(hold) else None,
            "exit_reasons": reasons}


def half_life(y):
    """Chan: regress dy on y[t-1]; lambda<0 -> mean reverting, half-life=-ln2/lambda. Returns (lam, hl)."""
    y = np.asarray(y, float)
    dy, yl = np.diff(y), y[:-1] - y[:-1].mean()
    d = (yl * yl).sum()
    if d <= 0:
        return 0.0, math.inf
    lam = float((yl * (dy - dy.mean())).sum() / d)
    return lam, (-math.log(2) / lam if lam < 0 else math.inf)


# ---------------------------------------------------------------- signal builders (arrays at bar close)
def sig_tsm(c, lb):
    s = np.zeros(len(c))
    s[lb:] = np.sign(c[lb:] - c[:-lb])
    return s


def sig_shape(c):   # Chan hybrid: long if c<c[30] and c>c[40]; short reverse
    s = np.zeros(len(c))
    for i in range(40, len(c)):
        if c[i] < c[i - 30] and c[i] > c[i - 40]:
            s[i] = 1
        elif c[i] > c[i - 30] and c[i] < c[i - 40]:
            s[i] = -1
    return s


def ema(c, n):
    a, out = 2 / (n + 1), np.empty(len(c))
    out[0] = c[0]
    for i in range(1, len(c)):
        out[i] = a * c[i] + (1 - a) * out[i - 1]
    return out


def sig_ema_cross(c, lb):
    e = ema(c, lb)
    s = np.zeros(len(c))
    up, dn = (c[1:] > e[1:]) & (c[:-1] <= e[:-1]), (c[1:] < e[1:]) & (c[:-1] >= e[:-1])
    s[1:][up], s[1:][dn] = 1, -1
    s[:lb] = 0
    return s


def sig_alexander(c, x):
    """Zig-zag (Alexander/Fama-Blume filter): in a down-state emit +1 when close >= run-low*(1+x);
    in an up-state emit -1 when close <= run-high*(1-x). Initial state set by the first x-move."""
    s = np.zeros(len(c))
    state, lo, hi = 0, c[0], c[0]
    for i in range(1, len(c)):
        lo, hi = min(lo, c[i]), max(hi, c[i])
        if state <= 0 and c[i] >= lo * (1 + x):
            state, s[i], hi = 1, 1, c[i]
        elif state >= 0 and c[i] <= hi * (1 - x):
            state, s[i], lo = -1, -1, c[i]
    return s


def sig_updays_bb(c, w=20):
    s = np.zeros(len(c))
    if len(c) <= w + 1:
        return s
    d = np.sign(np.diff(c))
    for i in range(w, len(c)):
        win = c[i - w + 1:i + 1]
        mu, sd = win.mean(), win.std()
        up, dn = (d[i - w:i] > 0).sum(), (d[i - w:i] < 0).sum()
        if up > dn and c[i] > mu + 2 * sd:
            s[i] = 1
        elif dn > up and c[i] < mu - 2 * sd:
            s[i] = -1
    return s


LSET = (5, 10, 20, 40, 60)


def zscores(c, lset=LSET):
    import pandas as pd
    s = pd.Series(c)
    return {L: ((s - s.rolling(L).mean()) / s.rolling(L).std()).to_numpy() for L in lset}


def sig_zmr(c, variant):
    """variant: halflife (lookback=clamped half-life, gate lam<0 & hl<=30), fixed20, trendma100 (fixed20 + MA100 filter).
    Entry z<-1 long / z>1 short; returns (sig, z_used)."""
    import pandas as pd
    n = len(c)
    Z = zscores(c)
    z = Z[20].copy()
    gate = np.ones(n, bool)
    if variant == "halflife":
        gate[:] = False
        z = np.full(n, np.nan)
        cur = None
        for i in range(130, n):
            if cur is None or i % 10 == 0:
                cur = half_life(c[i - 120:i + 1])
            lam, hl = cur
            if lam < 0 and hl <= 30:
                L = min(LSET, key=lambda q: abs(q - max(5, min(60, hl))))
                z[i], gate[i] = Z[L][i], True
    ma100 = pd.Series(c).rolling(100).mean().to_numpy()
    s = np.zeros(n)
    ok = gate & ~np.isnan(z)
    lo, sh = ok & (z < -1), ok & (z > 1)
    if variant == "trendma100":
        lo, sh = lo & (c > ma100), sh & (c < ma100)
    s[lo], s[sh] = 1, -1
    return s, z


def ts_cells(o, h, l, c, atr, tf):
    """Yield (family, variant, params-without-atr, sig, hold, exit_long, exit_short) for time-series strategies.
    Bar-count constants mean bars, not days, at tf != 1d (lookbacks scaled up for 1h)."""
    lbs = (20, 60, 120) if tf == "1d" else (50, 150, 300)
    for lb in lbs:
        s = sig_tsm(c, lb)
        for H in (5, 25):
            yield "chan_tsm", "lookback_sign", {"hold": H, "lb": lb}, s, H, None, None
    for x in (0.10, 0.20):
        s = sig_alexander(c, x)
        yield "chan_alexander", "zigzag", {"hold": 30, "x": kfmt(x)}, s, 30, s == -1, s == 1
    for H in (5, 10):
        yield "chan_shape", "mom_mr", {"hold": H}, sig_shape(c), H, None, None
    for lb in (50, 100, 200):
        s = sig_ema_cross(c, lb)
        yield "chan_ema_regime", "cross", {"hold": 60, "lb": lb}, s, 60, s == -1, s == 1
    for H in (5, 10):
        yield "chan_updays", "bb_upper", {"hold": H}, sig_updays_bb(c), H, None, None
    for var in ("halflife", "fixed20", "trendma100"):
        s, z = sig_zmr(c, var)
        yield "chan_zmr", var, {"hold": 40}, s, 40, z >= 0, z <= 0


def tag(fam, var, d, tf, params):
    p = dict(params)
    return f"{fam}__{var}__{d}__{tf}__" + "_".join(f"{k}{p[k]}" for k in sorted(p)) + "__v1"


# ---------------------------------------------------------------- 1d per-symbol gap momentum (B-426/427)
def gap_momentum_cells(o, h, l, c, atr):
    import pandas as pd
    ret = pd.Series(c).pct_change()
    std90 = ret.rolling(90).std().shift(1).to_numpy()
    out = {}
    pH, pL = np.r_[np.nan, h[:-1]], np.r_[np.nan, l[:-1]]
    A = np.r_[np.nan, atr[:-1]]
    with np.errstate(invalid="ignore"):
        for z in (0.05, 0.1, 0.25, 0.5):
            for side, nm, m in ((1, "long", o > pH * (1 + z * std90)), (-1, "short", o < pL * (1 - z * std90))):
                m = m & ~np.isnan(std90) & ~np.isnan(A) & (A > 0)
                if not m.any():
                    continue
                for k in KS:
                    g, hit = day_returns(o[m], o[m], h[m], l[m], c[m], A[m], k, side)
                    out[tag("chan_gapmom", "open_vs_prev_extreme", nm, "1d", {"atr": kfmt(k), "z": kfmt(z)})] = (g, hit)
    return out


# ---------------------------------------------------------------- cross-sectional rows
def xs_rows(dates, o, h, l, c, v, atr):
    """Per-symbol candidate rows for xs modes. Returns (dict mode -> dict of lists, dates of liquid base rows) or None."""
    import pandas as pd
    if len(c) < 130:
        return None
    s = pd.Series(c)
    ret = s.pct_change()
    std90 = ret.rolling(90).std().shift(1).to_numpy()
    ma20 = s.rolling(20).mean().shift(1).to_numpy()
    liq = pd.Series(c * v).rolling(20).median().shift(1).to_numpy() >= LIQ_MIN_TURNOVER
    pH, pL, pC = np.r_[np.nan, h[:-1]], np.r_[np.nan, l[:-1]], np.r_[np.nan, c[:-1]]
    A = np.r_[np.nan, atr[:-1]]
    with np.errstate(invalid="ignore"):
        base = liq & ~np.isnan(std90) & ~np.isnan(ma20) & ~np.isnan(A) & (A > 0) & (pC > 0) & (o > 0)
        gap = o / pC - 1
        cc = np.r_[np.nan, ret.to_numpy()[:-1]]          # return of the PRIOR bar, known at its close
        rows = {}

        def add(mode, mask, score, side, E, gap_aware):
            if not mask.any():
                return
            d = {"date": dates[mask].tolist(), "score": np.round(score[mask], 5).tolist()}
            for k in KS:
                g, hit = day_returns(E[mask], o[mask], h[mask], l[mask], c[mask], A[mask], k, side, gap_aware)
                d[f"G{k}"], d[f"S{k}"] = np.round(g, 5).tolist(), hit.astype(int).tolist()
            rows[mode] = d
        add("gapz_long", base & (o < pL * (1 - std90)) & (o > ma20), gap, 1, o, False)
        add("gapz_short", base & (o > pH * (1 + std90)) & (o < ma20), gap, -1, o, False)
        add("dec_long", base, gap, 1, o, False)
        add("dec_short", base, gap, -1, o, False)
        ccm = base & ~np.isnan(cc)
        add("cc_long", ccm, cc, 1, pC, True)
        add("cc_short", ccm, cc, -1, pC, True)
    return rows, dates[base]


def prune_local(mode_rows):
    """Per-day shard prune for decile modes: keep the most extreme LOCAL_KEEP fraction on the relevant side."""
    import pandas as pd
    out = {}
    for mode, d in mode_rows.items():
        if not mode.startswith(("dec_", "cc_")):
            out[mode] = d
            continue
        df = pd.DataFrame({"date": d["date"], "score": d["score"]})
        pct = df.groupby("date")["score"].rank(pct=True)
        keep = (pct <= LOCAL_KEEP) if mode.endswith("long") else (pct >= 1 - LOCAL_KEEP)
        idx = np.flatnonzero(keep.to_numpy())
        out[mode] = {key: [vals[j] for j in idx] for key, vals in d.items()}
    return out


def select_xs(mode, rows, day_counts, cost, top=10, dec=0.10):
    """rows: concatenated candidate rows; day_counts: date -> liquid base-universe size.
    Returns {k: (net, gross, stopped)} after per-day top-N (gapz) or decile (dec/cc) selection."""
    import pandas as pd
    df = pd.DataFrame({"date": rows["date"], "score": rows["score"]})
    for k in KS:
        df[f"G{k}"], df[f"S{k}"] = rows[f"G{k}"], rows[f"S{k}"]
    long = mode.endswith("long")
    df["r"] = df.groupby("date")["score"].rank(method="first", ascending=long)
    if mode.startswith("gapz"):
        lim = top
    else:
        lim = df["date"].map(lambda d: max(1, int(math.ceil(dec * day_counts.get(str(d), 0)))))
    sel = df[df["r"] <= lim]
    return {k: (sel[f"G{k}"].to_numpy() - cost, sel[f"G{k}"].to_numpy(), sel[f"S{k}"].to_numpy()) for k in KS}


XS_TAGS = {"gapz_long": ("chan_gap", "buy_on_gap", "long", {"top": 10}),
           "gapz_short": ("chan_gap", "short_on_gap", "short", {"top": 10}),
           "dec_long": ("chan_xs_o2c", "decile_gap_reversion", "long", {"dec": 10}),
           "dec_short": ("chan_xs_o2c", "decile_gap_reversion", "short", {"dec": 10}),
           "cc_long": ("chan_kl", "cc_reversion", "long", {"dec": 10}),
           "cc_short": ("chan_kl", "cc_reversion", "short", {"dec": 10})}


# ---------------------------------------------------------------- driver
def download(batch, interval):
    import yfinance as yf
    period = "5y" if interval == "1d" else "730d"
    return yf.download(batch, period=period, interval=interval, group_by="ticker", auto_adjust=True,
                       progress=False, threads=True)


def run():
    import main as app
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    shard, nshard = int(os.environ.get("SHARD", 0)), int(os.environ.get("NSHARD", 1))
    interval = os.environ.get("INTERVAL", "1d")
    syms = list(app._load_nse_universe_from_file())
    cap = int(os.environ.get("MAXSYM", "0") or 0)
    if cap:
        syms = syms[:cap]
    syms = syms[shard::nshard]
    acc, xs_all, day_counts = {}, {}, {}

    def put(t, net, gross, hold, reasons):
        a = acc.setdefault(t, {"net": [], "gross": [], "hold": [], "reasons": {}})
        a["net"] += [float(x) for x in net]
        a["gross"] += [float(x) for x in gross]
        a["hold"] += [int(x) for x in hold]
        for r, q in reasons.items():
            a["reasons"][r] = a["reasons"].get(r, 0) + int(q)
    for b0 in range(0, len(syms), 100):
        batch = syms[b0:b0 + 100]
        try:
            d = download(batch, interval)
        except Exception as e:
            print("batch fail", b0, e, flush=True)
            continue
        for s in batch:
            try:
                df = d[s] if len(batch) > 1 else d
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            except Exception:
                continue
            if len(df) < 160:
                continue
            o, h, l, c, v = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close", "Volume"))
            if (o <= 0).any() or (np.abs(c[1:] / c[:-1] - 1) > 0.4).any():   # bad-tick / split guard (B-458)
                continue
            atr = atr_arr(h, l, c)
            for fam, var, params, sig, hold, xl, xsx in ts_cells(o, h, l, c, atr, interval):
                for k in KS:
                    tr = simulate(o, h, l, c, atr, sig, k, hold, xl, xsx)
                    for side, nm in ((1, "long"), (-1, "short")):
                        sub = [t for t in tr if t[0] == side]
                        if not sub:
                            continue
                        g = np.array([t[3] for t in sub])
                        reasons = {}
                        for t in sub:
                            reasons[t[4]] = reasons.get(t[4], 0) + 1
                        put(tag(fam, var, nm, interval, {**params, "atr": kfmt(k)}), g - cost, g,
                            [t[2] - t[1] + 1 for t in sub], reasons)
            if interval != "1d":
                continue
            for t, (g, hit) in gap_momentum_cells(o, h, l, c, atr).items():
                put(t, g - cost, g, [1] * len(g), {"stop": hit.sum(), "close": (~hit).sum()})
            dates = df.index.strftime("%Y%m%d").to_numpy().astype(int)
            res = xs_rows(dates, o, h, l, c, v, atr)
            if res:
                rows, base_dates = res
                for dd in base_dates.tolist():
                    day_counts[dd] = day_counts.get(dd, 0) + 1
                for mode, dct in rows.items():
                    tgt = xs_all.setdefault(mode, {})
                    for key, vals in dct.items():
                        tgt.setdefault(key, []).extend(vals)
        print("batch", b0, len(acc), flush=True)
    xs_all = prune_local(xs_all)
    out_dir = os.environ.get("OUT_DIR", os.path.join(ROOT, "docs"))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"chan_shard_{interval}_{shard}.json")
    with open(path, "w") as f:
        json.dump({"interval": interval, "ts": acc, "xs": xs_all,
                   "day_counts": {str(k): v for k, v in day_counts.items()}}, f)
    print("wrote", path)


def merge():
    import main as app
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    files = sorted(glob.glob(os.path.join(os.environ.get("IN_DIR", "."), "**", "chan_shard_*.json"), recursive=True))
    acc, xs, counts = {}, {}, {}
    for f in files:
        with open(f) as fh:
            d = json.load(fh)
        for t, a in d["ts"].items():
            m = acc.setdefault(t, {"net": [], "gross": [], "hold": [], "reasons": {}})
            m["net"] += a["net"]
            m["gross"] += a["gross"]
            m["hold"] += a["hold"]
            for r, q in a["reasons"].items():
                m["reasons"][r] = m["reasons"].get(r, 0) + q
        for mode, dct in d["xs"].items():
            tgt = xs.setdefault(mode, {})
            for key, vals in dct.items():
                tgt.setdefault(key, []).extend(vals)
        for dd, q in d["day_counts"].items():
            counts[dd] = counts.get(dd, 0) + q
    res = {t: stats(a["net"], a["gross"], a["hold"], a["reasons"]) for t, a in acc.items() if a["net"]}
    for mode, rows in xs.items():
        fam, var, dr, p = XS_TAGS[mode]
        for k, (net, gross, hit) in select_xs(mode, rows, counts, cost).items():
            reasons = {"stop": int(hit.sum()), "close": int((1 - hit).sum())}
            res[tag(fam, var, dr, "1d", {**p, "atr": kfmt(k)})] = stats(net, gross, [1] * len(net), reasons)
    res = {t: m for t, m in res.items() if m}
    out = os.environ.get("OUT", os.path.join(ROOT, "docs", "chan_research_results.json"))
    with open(out, "w") as f:
        json.dump({"cost_round_trip": cost, "results": res}, f, indent=0)
    for t, m in sorted(res.items(), key=lambda x: -(x[1]["pfnet"] or 0)):
        print(t, m["pfnet"], m["pfgross"], m["win_pct"], m["n"], m["avg_hold_bars"], m["exit_reasons"])


if __name__ == "__main__":
    {"run": run, "merge": merge}[sys.argv[1] if len(sys.argv) > 1 else "run"]()
