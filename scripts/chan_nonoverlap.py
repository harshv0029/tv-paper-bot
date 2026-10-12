"""Chan research cells re-run with strictly NON-OVERLAPPING trades (backlog B-807).
Method: for every (symbol, cell) generate the trade each signal bar WOULD open independently (overlapping, as the
registry n of chan-research run 38183172728 implies), then apply a strict FIFO filter: a trade is accepted only if its
entry bar is after the exit bar of the last accepted trade in that symbol+cell (one position per symbol per cell, long
and short share the slot). Reuses chan_research's signal builders / ATR / cost model unchanged.
Tags: <old tag minus __v1>__nonovl__v2 (old tags untouched). Covers the per-symbol time-series cells and the 1d gap-
momentum cells; the cross-sectional cells (chan_gap, chan_xs_o2c, chan_kl) pick per day across symbols and are one-bar
trades, so they cannot overlap in a symbol, and are listed as not applicable rather than re-run.
Modes: run (env SHARD, NSHARD, INTERVAL, OUT_DIR, MAXSYM) -> small aggregate json; merge (IN_DIR, OUT) -> results json.
Shards emit mergeable aggregates only (sums, counts), not trade lists, so the artifact stays small."""
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chan_research as cr  # noqa: E402

ROOT = cr.ROOT


def nonovl_tag(old):
    base = old[:-4] if old.endswith("__v1") else old
    return base + "__nonovl__v2"


def independent_trade(o, h, l, c, atr, i, s, k, hold, ex):
    """Trade opened by the signal at bar i (entry at open of i+1), evaluated on its own. None if not tradable."""
    n = len(c)
    if i >= n - 2 or np.isnan(atr[i]) or atr[i] <= 0 or o[i + 1] <= 0:
        return None
    e, ep = i + 1, o[i + 1]
    stop = ep - k * atr[i] if s == 1 else ep + k * atr[i]
    xi, xp, why = None, None, None
    for j in range(e, min(n, e + hold)):
        if s == 1 and l[j] <= stop:
            xi, xp, why = j, (min(stop, o[j]) if j > e else stop), "stop"
            break
        if s == -1 and h[j] >= stop:
            xi, xp, why = j, (max(stop, o[j]) if j > e else stop), "stop"
            break
        if ex is not None and ex[j]:
            xi, xp, why = j, c[j], "state_exit"
            break
    if xi is None:
        xi = min(n, e + hold) - 1
        xp, why = c[xi], "max_hold"
    return (int(s), e, xi, (xp / ep - 1) if s == 1 else (1 - xp / ep), why)


def fifo_filter(trades, gap=0):
    """trades: (side, entry_i, exit_i, gross, reason). Keep a trade only if entry_i > last kept exit_i + gap (FIFO).
    gap=0 is strict FIFO (re-enter on the bar after the exit); chan_research.simulate() is equivalent to gap=1
    (it ignores the signal on the exit bar itself)."""
    kept, last_exit = [], -1
    for t in sorted(trades, key=lambda t: (t[1], t[2])):
        if t[1] > last_exit + gap:
            kept.append(t)
            last_exit = t[2]
    return kept


def has_overlap(trades):
    ts = sorted(trades, key=lambda t: t[1])
    return any(b[1] <= a[2] for a, b in zip(ts, ts[1:]))


def cell_trades(o, h, l, c, atr, sig, k, hold, xl, xsx, gap=0):
    """Returns (kept non-overlapping trades, count of independent signal trades before the filter)."""
    raw = []
    for i in np.flatnonzero(sig != 0):
        s = int(sig[i])
        t = independent_trade(o, h, l, c, atr, int(i), s, k, hold, xl if s == 1 else xsx)
        if t:
            raw.append(t)
    return fifo_filter(raw, gap), len(raw)


class Agg:
    __slots__ = ("n", "wins", "gp_n", "gl_n", "gp_g", "gl_g", "sum_net", "sum_hold", "reasons")

    def __init__(self):
        self.n = self.wins = 0
        self.gp_n = self.gl_n = self.gp_g = self.gl_g = self.sum_net = self.sum_hold = 0.0
        self.reasons = {}

    def add(self, net, gross, hold, reasons):
        net, gross = np.asarray(net, float), np.asarray(gross, float)
        self.n += len(net)
        self.wins += int((net > 0).sum())
        self.gp_n += float(net[net > 0].sum())
        self.gl_n += float(-net[net < 0].sum())
        self.gp_g += float(gross[gross > 0].sum())
        self.gl_g += float(-gross[gross < 0].sum())
        self.sum_net += float(net.sum())
        self.sum_hold += float(np.sum(hold))
        for r, q in reasons.items():
            self.reasons[r] = self.reasons.get(r, 0) + int(q)

    def to_dict(self):
        return {s: getattr(self, s) for s in self.__slots__}

    def merge_dict(self, d):
        for s in self.__slots__:
            if s == "reasons":
                for r, q in d[s].items():
                    self.reasons[r] = self.reasons.get(r, 0) + q
            else:
                setattr(self, s, getattr(self, s) + d[s])

    def metrics(self):
        if not self.n:
            return None

        def pf(g, ls):
            return round(g / ls, 3) if ls > 0 else None
        return {"pfnet": pf(self.gp_n, self.gl_n), "pfgross": pf(self.gp_g, self.gl_g),
                "win_pct": round(self.wins / self.n * 100, 1), "n": int(self.n),
                "avg_net_pct": round(self.sum_net / self.n * 100, 4),
                "avg_hold_bars": round(self.sum_hold / self.n, 2), "exit_reasons": self.reasons}


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
    acc = {}
    for b0 in range(0, len(syms), 100):
        batch = syms[b0:b0 + 100]
        try:
            d = cr.download(batch, interval)
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
            o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
            if (o <= 0).any() or (np.abs(c[1:] / c[:-1] - 1) > 0.4).any():
                continue
            atr = cr.atr_arr(h, l, c)
            for fam, var, params, sig, hold, xl, xsx in cr.ts_cells(o, h, l, c, atr, interval):
                for k in cr.KS:
                    kept, _raw_n = cell_trades(o, h, l, c, atr, sig, k, hold, xl, xsx)
                    for side, nm in ((1, "long"), (-1, "short")):
                        sub = [t for t in kept if t[0] == side]
                        if not sub:
                            continue
                        g = np.array([t[3] for t in sub])
                        reasons = {}
                        for t in sub:
                            reasons[t[4]] = reasons.get(t[4], 0) + 1
                        key = nonovl_tag(cr.tag(fam, var, nm, interval, {**params, "atr": cr.kfmt(k)}))
                        acc.setdefault(key, Agg()).add(g - cost, g, [t[2] - t[1] + 1 for t in sub], reasons)
            if interval != "1d":
                continue
            for t, (g, hit) in cr.gap_momentum_cells(o, h, l, c, atr).items():
                # one-bar open->close trades: a symbol-day holds at most one, so FIFO never drops any
                acc.setdefault(nonovl_tag(t), Agg()).add(g - cost, g, [1] * len(g),
                                                         {"stop": int(hit.sum()), "close": int((~hit).sum())})
        print("batch", b0, len(acc), flush=True)
    out_dir = os.environ.get("OUT_DIR", os.path.join(ROOT, "docs"))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"chan_nonovl_shard_{interval}_{shard}.json")
    with open(path, "w") as f:
        json.dump({"interval": interval, "agg": {t: a.to_dict() for t, a in acc.items()}}, f)
    print("wrote", path)


def merge():
    files = sorted(glob.glob(os.path.join(os.environ.get("IN_DIR", "."), "**", "chan_nonovl_shard_*.json"),
                             recursive=True))
    acc = {}
    for f in files:
        with open(f) as fh:
            d = json.load(fh)
        for t, a in d["agg"].items():
            acc.setdefault(t, Agg()).merge_dict(a)
    res = {t: m for t, m in ((t, a.metrics()) for t, a in acc.items()) if m}
    out = os.environ.get("OUT", os.path.join(ROOT, "docs", "chan_nonoverlap_results.json"))
    with open(out, "w") as f:
        json.dump({"method": "strict FIFO, one position per symbol per cell", "results": res},
                  f, separators=(",", ":"))
    for t, m in sorted(res.items(), key=lambda x: -(x[1]["pfnet"] or 0)):
        print(t, m["pfnet"], m["pfgross"], m["win_pct"], m["n"], m["avg_hold_bars"], m["exit_reasons"])


if __name__ == "__main__":
    {"run": run, "merge": merge}[sys.argv[1] if len(sys.argv) > 1 else "run"]()
