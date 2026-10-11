"""O'Neil research batch (backlog B-460, B-466, B-473, B-483, B-488, B-489, B-491, B-493, B-502).

Daily (1d) and weekly (1w) bars, FULL NSE universe (main._load_nse_universe_from_file()), BOTH directions.
Signal at the close of bar t -> entry at the open of t+1. EVERY trade carries a stop (no stop-less cell).
Net of main.ROUND_TRIP_COST_PCT (0.8%). Cells are additive sums so shards merge exactly.

Entry families (tag family / variant):
  oneil_pivot__breakout      B-460 close through base high/low on >=1.5x 50-bar avg volume, no-chase sweep 5/10%
  oneil_flatbase__breakout   B-466 tight flat base (range <=12%) after a >=30% advance (short: decline), pivot break
  oneil_newhigh__first       B-473/B-488 52-week-high (short: low) close on >=1.5x volume
  oneil_rsscreen__top        B-483 standalone RS-rank screen (RS>=90 near 52w high / RS<=20 near 52w low)
RS rank (B-483): 12-month return percentile (1-99) across the symbols loaded in the shard (interleaved
shards => an unbiased ~1/N sample of the universe; stated honestly, not the exact full-universe rank).
Filter: rsnone | rs80 (long RS>=80, short RS<=30).
Exit modes (all with a stop): atr2/atr3 fixed ATR stop (compare), pct7/pct8 O'Neil percentage stop (B-489),
tgt20 = 8% stop + 20% target (B-491), trl1 = ATR3 initial then trailing stop under the latest confirmed swing
low (B-493), avg1 = NEGATIVE CONTROL for B-502 (adds a 2nd unit 1.5 ATR against, same stop; the live engine
invariant is never-average-down, this only measures what it would have cost).
Tag: <family>__<variant>__<dir>__<tf>__<params sorted>__v1 ; decimals written d.
Env: TF (1d|1w), SHARD, NSHARDS, MAXSYM (debug). Output docs/oneil_research_<tf>_s<shard>.json (cell sums);
`--merge files...` pools shards and prints pfnet/win%/n/avg hold/exit-reason breakdown.
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

# bar-count constants change meaning with candle size (stated in the workflow header)
CFG = {
    "1d": dict(period="5y", base=40, vol=50, smalt=200, flat=35, adv_lb=60, rs_lb=252, yr=252, swing=3,
               holds=(20, 40, 60), min_bars=300),
    "1w": dict(period="10y", base=8, vol=10, smalt=40, flat=7, adv_lb=12, rs_lb=52, yr=52, swing=2,
               holds=(8, 12, 26), min_bars=120),
}
CHASES = (0.05, 0.10)
RS_FILTERS = ("none", "80")
EXITS = (("atr", 2.0), ("atr", 3.0), ("pct", 7.0), ("pct", 8.0), ("tgt", 20.0), ("trl", 3.0), ("avg", 3.0))
VOL_MULT = 1.5
FLAT_RANGE = 0.12
ADV_MIN = 0.30
DEPTH_MAX = 0.35


# ---------- helpers ----------
def shift(x, k=1):
    x = np.asarray(x, float)
    out = np.full_like(x, np.nan)
    if k > 0:
        out[k:] = x[:-k]
    elif k < 0:
        out[:k] = x[-k:]
    else:
        out[:] = x
    return out


def sma(x, n):
    return pd.Series(x).rolling(n).mean().to_numpy()


def rmax(x, n):
    return pd.Series(x).rolling(n).max().to_numpy()


def rmin(x, n):
    return pd.Series(x).rolling(n).min().to_numpy()


def atr_arr(h, l, c, n=14):
    pc = shift(c)
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    return pd.Series(tr).rolling(n).mean().to_numpy()


def clean_bars(df, max_move=0.35):
    """Drop vendor glitch bars (same rule as scripts/pattern_lab.clean_bars)."""
    o, h, l, c = df["Open"], df["High"], df["Low"], df["Close"]
    ok = (o <= h * 1.001) & (o >= l * 0.999) & (c <= h * 1.001) & (c >= l * 0.999) & (l > 0) & ((h / l) < 1.6)
    jump = (c / c.shift(1) - 1).abs() > max_move
    return df[ok & ~jump.fillna(False)]


def rs_rank_matrix(closes: pd.DataFrame, lb: int) -> pd.DataFrame:
    """12-month return percentile 1-99 per date across columns (symbols)."""
    ret = closes / closes.shift(lb) - 1
    return ret.rank(axis=1, pct=True) * 98 + 1


def fnum(v):
    return ("%g" % v).replace(".", "d")


def make_tag(family, variant, direction, tf, params):
    p = "_".join(f"{k}{v if isinstance(v, str) else fnum(v)}" for k, v in sorted(params.items()))
    return f"{family}__{variant}__{direction}__{tf}__{p}__v1"


# ---------- signals ----------
def entry_signals(o, h, l, c, v, rs, cfg):
    """Return {(family, variant, dir, chase, rsf): bool array} (signal at close of t)."""
    n = len(c)
    base, vol_n, smalt = cfg["base"], cfg["vol"], cfg["smalt"]
    vavg = shift(sma(v, vol_n))
    ma = sma(c, smalt)
    nxt_o = shift(o, -1)
    out = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        volok = v >= VOL_MULT * vavg
        pivH = shift(rmax(h, base))
        pivL = shift(rmin(l, base))
        depth = (pivH - pivL) / pivH
        long_brk = (c > pivH) & volok & (c > ma) & (depth <= DEPTH_MAX)
        short_brk = (c < pivL) & volok & (c < ma) & (depth <= DEPTH_MAX)
        fb = cfg["flat"]
        fbH = shift(rmax(h, fb))
        fbL = shift(rmin(l, fb))
        flat = (fbH - fbL) / fbH <= FLAT_RANGE
        adv = shift(c, fb) / shift(c, fb + cfg["adv_lb"])
        fl_long = flat & (adv >= 1 + ADV_MIN) & (c > fbH) & volok
        fl_short = flat & (adv <= 1 - ADV_MIN) & (c < fbL) & volok
        yr = cfg["yr"]
        nh_long = (c > shift(rmax(c, yr))) & volok
        nh_short = (c < shift(rmin(c, yr))) & volok
        rs_long_c = (rs >= 90) & (c > ma) & (c >= 0.95 * rmax(c, yr))
        rs_short_c = (rs <= 20) & (c < ma) & (c <= 1.05 * rmin(c, yr))
        rs_long = rs_long_c & (shift(rs_long_c.astype(float)) != 1)
        rs_short = rs_short_c & (shift(rs_short_c.astype(float)) != 1)
        ok_l = {"none": np.ones(n, bool), "80": rs >= 80}
        ok_s = {"none": np.ones(n, bool), "80": rs <= 30}  # tag value "80" = RS-filter on; short side uses RS<=30
        for ch in CHASES:
            cl_l = (nxt_o / pivH - 1) <= ch
            cl_s = (1 - nxt_o / pivL) <= ch
            fl_l = (nxt_o / fbH - 1) <= ch
            fl_s = (1 - nxt_o / fbL) <= ch
            for rsf in RS_FILTERS:
                out[("oneil_pivot", "breakout", "long", ch, rsf)] = long_brk & cl_l & ok_l[rsf]
                out[("oneil_pivot", "breakout", "short", ch, rsf)] = short_brk & cl_s & ok_s[rsf]
                out[("oneil_flatbase", "breakout", "long", ch, rsf)] = fl_long & fl_l & ok_l[rsf]
                out[("oneil_flatbase", "breakout", "short", ch, rsf)] = fl_short & fl_s & ok_s[rsf]
        for rsf in RS_FILTERS:
            out[("oneil_newhigh", "first", "long", None, rsf)] = nh_long & ok_l[rsf]
            out[("oneil_newhigh", "first", "short", None, rsf)] = nh_short & ok_s[rsf]
        out[("oneil_rsscreen", "top", "long", None, "90")] = rs_long
        out[("oneil_rsscreen", "top", "short", None, "20")] = rs_short
    return {k: np.nan_to_num(np.asarray(m, float)).astype(bool) for k, m in out.items()}


# ---------- simulation ----------
def simulate(sig, o, h, l, c, atr, hold, mode, val, side, cost, swing_w):
    """Non-overlapping trades. Returns list of (net_ret, gross_ret, held_bars, reason). Always has a stop."""
    res = []
    n = len(c)
    nxt = 0
    for t in np.flatnonzero(sig):
        if t < nxt or t + 1 >= n or np.isnan(atr[t]) or atr[t] <= 0:
            continue
        e = t + 1
        ent = o[e]
        if not ent or np.isnan(ent):
            continue
        last = min(e + hold - 1, n - 1)
        if last - e + 1 < hold:
            continue
        if mode == "pct":
            stop = ent * (1 - side * val / 100.0)
        elif mode == "tgt":
            stop = ent * (1 - side * 0.08)
        else:  # atr / trl / avg
            stop = ent - side * val * atr[t]
        init_stop = stop
        target = ent * (1 + side * 0.20) if mode == "tgt" else None
        add_px = ent - side * 1.5 * atr[t] if mode == "avg" else None
        add_done = False
        exitp, jx, reason = c[last], last, "timeout"
        for j in range(e, last + 1):
            if mode == "trl":
                k = j - 1 - swing_w  # swing point confirmed by bars up to j-1
                if k - swing_w >= e:
                    if side == 1 and l[k] == np.min(l[k - swing_w:k + swing_w + 1]):
                        stop = max(stop, l[k])
                    elif side == -1 and h[k] == np.max(h[k - swing_w:k + swing_w + 1]):
                        stop = min(stop, h[k])
            if side == 1 and l[j] <= stop:
                exitp, jx = min(stop, o[j]), j
                reason = "trail_stop" if stop > init_stop else "stop"
                break
            if side == -1 and h[j] >= stop:
                exitp, jx = max(stop, o[j]), j
                reason = "trail_stop" if stop < init_stop else "stop"
                break
            if target is not None:
                if side == 1 and h[j] >= target:
                    exitp, jx, reason = max(target, o[j]), j, "target"
                    break
                if side == -1 and l[j] <= target:
                    exitp, jx, reason = min(target, o[j]), j, "target"
                    break
            if add_px is not None and not add_done and j > e:
                if (side == 1 and l[j] <= add_px) or (side == -1 and h[j] >= add_px):
                    add_done = True
        g = (exitp / ent - 1) * side
        if add_done:
            g = (g + (exitp / add_px - 1) * side) / 2.0
            reason += "+avgdown"
        res.append((g - cost, g, jx - e + 1, reason))
        nxt = jx + 1
    return res


def _new_cell():
    return dict(gain=0.0, loss=0.0, gain_g=0.0, loss_g=0.0, n=0, wins=0, held=0, maxr=-9.0, reasons={})


def acc_add(cells, tag, rows):
    c = cells.setdefault(tag, _new_cell())
    for net, gross, held, reason in rows:
        if net > 0:
            c["gain"] += net
        else:
            c["loss"] -= net
        if gross > 0:
            c["gain_g"] += gross
        else:
            c["loss_g"] -= gross
        c["n"] += 1
        c["wins"] += int(net > 0)
        c["held"] += held
        c["maxr"] = max(c["maxr"], net)
        r = c["reasons"].setdefault(reason, [0, 0.0])
        r[0] += 1
        r[1] += net


def tag_for(fam, var, d, tf, ch, rsf, mode, val, hold):
    p = {"h": hold, "rs": rsf if rsf == "none" else f"{rsf}"}
    if ch is not None:
        p["chase"] = int(round(ch * 100))
    if mode == "atr":
        p["atr"] = val
    elif mode == "pct":
        p["pct"] = int(val)
    elif mode == "tgt":
        p["pct"] = 8
        p["tgt"] = int(val)
    elif mode == "trl":
        p["atr"] = val
        p["trl"] = 1
    elif mode == "avg":
        p["atr"] = val
        p["avg"] = 1
    return make_tag(fam, var, d, tf, p)


def process_symbol(df, rs_series, cfg, cost, tf, cells):
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    v = df["Volume"].to_numpy(float)
    rs = rs_series.reindex(df.index).to_numpy(float)
    atr = atr_arr(h, l, c)
    for (fam, var, d, ch, rsf), sg in entry_signals(o, h, l, c, v, rs, cfg).items():
        if not sg.any():
            continue
        side = 1 if d == "long" else -1
        for hold in cfg["holds"]:
            for mode, val in EXITS:
                rows = simulate(sg, o, h, l, c, atr, hold, mode, val, side, cost, cfg["swing"])
                if rows:
                    acc_add(cells, tag_for(fam, var, d, tf, ch, rsf, mode, val, hold), rows)


def finalize(cells, min_n=30):
    out = {}
    for tag, c in cells.items():
        if c["n"] < min_n:
            continue
        out[tag] = dict(
            pfnet=round(c["gain"] / c["loss"], 3) if c["loss"] > 0 else None,
            pfgross=round(c["gain_g"] / c["loss_g"], 3) if c["loss_g"] > 0 else None,
            win_pct=round(100.0 * c["wins"] / c["n"], 1), n=c["n"],
            avg_held_bars=round(c["held"] / c["n"], 2),
            avg_net_pct=round(100.0 * (c["gain"] - c["loss"]) / c["n"], 3),
            max_trade_net_pct=round(100.0 * c["maxr"], 1),
            exit_reasons={k: dict(n=r[0], avg_net_pct=round(100.0 * r[1] / r[0], 3)) for k, r in c["reasons"].items()})
    return out


def merge_cells(parts):
    tot = {}
    for p in parts:
        for tag, c in p.items():
            t = tot.setdefault(tag, _new_cell())
            for k in ("gain", "loss", "gain_g", "loss_g", "n", "wins", "held"):
                t[k] += c[k]
            t["maxr"] = max(t["maxr"], c["maxr"])
            for rk, (rn, rsum) in c["reasons"].items():
                r = t["reasons"].setdefault(rk, [0, 0.0])
                r[0] += rn
                r[1] += rsum
    return tot


def main_run():
    import yfinance as yf
    import main as app
    tf = os.environ.get("TF", "1d")
    cfg = CFG[tf]
    shard, nsh = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    syms = sorted(app._load_nse_universe_from_file())[shard::nsh]
    cap = int(os.environ.get("MAXSYM", "0") or 0)
    if cap:
        syms = syms[:cap]
    data = {}
    for b0 in range(0, len(syms), 100):
        batch = syms[b0:b0 + 100]
        try:
            d = yf.download(batch, period=cfg["period"], interval="1wk" if tf == "1w" else "1d", group_by="ticker",
                            auto_adjust=True, progress=False, threads=True)
        except Exception as e:
            print("batch fail", b0, e, flush=True)
            continue
        for s in batch:
            try:
                df = d[s].dropna(subset=["Close"]) if len(batch) > 1 else d.dropna(subset=["Close"])
                df = clean_bars(df[["Open", "High", "Low", "Close", "Volume"]].dropna())
            except Exception:
                continue
            if len(df) >= cfg["min_bars"]:
                data[s] = df
        print("downloaded", b0, "kept", len(data), flush=True)
    closes = pd.DataFrame({s: df["Close"] for s, df in data.items()})
    rs_all = rs_rank_matrix(closes, cfg["rs_lb"])
    cells = {}
    for i, (s, df) in enumerate(data.items()):
        process_symbol(df, rs_all[s], cfg, cost, tf, cells)
        if i % 100 == 0:
            print("processed", i, "cells", len(cells), flush=True)
    out = os.path.join(ROOT, "docs", f"oneil_research_{tf}_s{shard}.json")
    json.dump({"tf": tf, "shard": shard, "nshards": nsh, "symbols": len(data), "cells": cells}, open(out, "w"))
    print("wrote", out, "cells", len(cells))


def merge_run(paths):
    res = finalize(merge_cells([json.load(open(p))["cells"] for p in paths]))
    out = os.path.join(ROOT, "docs", "oneil_research_results.json")
    json.dump({"results": res}, open(out, "w"), indent=0)
    ok = sorted([(m["pfnet"], m["n"], t) for t, m in res.items() if m["pfnet"] and m["pfnet"] >= 1.1 and m["n"] >= 300], reverse=True)
    print(f"cells={len(res)} viable(PFnet>=1.1,n>=300)={len(ok)}")
    for pf, n, t in ok[:40]:
        m = res[t]
        print(f"{t} pfnet={pf} win={m['win_pct']} n={n} hold={m['avg_held_bars']} reasons={json.dumps(m['exit_reasons'])}")
    print("TOP10 any n>=100:")
    for m, t in sorted(((m["pfnet"] or 0, t) for t, m in res.items() if m["n"] >= 100), reverse=True)[:10]:
        print(t, m, res[t]["win_pct"], res[t]["n"])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--merge":
        merge_run(sys.argv[2:])
    else:
        main_run()
