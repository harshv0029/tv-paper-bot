"""B-1746 step 3: option-premium PROXY replay of index triggers (research only, no orders, no live logic touched).

For ^NSEI, ^BSESN and ^NSEBANK on 5m and 15m candles, every fire of the live ORB rule WITHOUT the volume gate
(index_fire_audit.live_orb, use_volume=False) and of the 4 non-volume triggers is expressed as ONE ATM option lot
(LONG -> call, SHORT -> put, single leg) bought at the signal bar close and managed bar by bar on a Black-Scholes
premium proxy (option_premium_proxy.simulate_long_option_trade: initial stop, trail arm, trail) with a quick exit:
max-hold bars or the last bar at/before 15:10 IST, whichever is first. Never held overnight.

!! PROXY, NOT EVIDENCE (option_premium_proxy.PROXY_LABEL). Constant IV, no skew, no IV crush, modelled spread. A pass
!! here only says "worth paper-trading"; it never opens a real entry.

Cost: the proxy's own friction (0.5% half spread each side + fees) AND, separately, the house 0.8% round-trip cost
model applied to the premium return. Both are reported; the 0.8% figure is the decision metric.
Split: first IS_FRAC of session days in-sample, rest out-of-sample (chronological).
Env: FROM/TO (IST dates), IV_<NAME> (default 0.13 NIFTY/SENSEX, 0.15 BANKNIFTY), LOT_<NAME> (assumption: 65/20/30),
IS_FRAC (0.6), OUT_DIR (docs), SYNTH=1 offline dry run.
"""
import datetime as dt
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import index_option_trigger_research as R  # noqa: E402
import index_fire_audit as A  # noqa: E402
import option_premium_proxy as P  # noqa: E402

# name, strike step, expiry weekday (Mon=0), weekly?
UNDERLYING = {"^NSEI": ("NIFTY", 50, 1, True), "^BSESN": ("SENSEX", 100, 3, True), "^NSEBANK": ("BANKNIFTY", 100, 1, False)}
DEFAULT_IV = {"NIFTY": 0.13, "SENSEX": 0.13, "BANKNIFTY": 0.15}
DEFAULT_LOT = {"NIFTY": 65, "SENSEX": 20, "BANKNIFTY": 30}
TFS = ("5m", "15m")
# (initial_stop_pct, trail_arm_pct, trail_pct) of premium; first row = live FO_OPTION_* constants (3/1/1)
EXIT_GRID = [(3.0, 1.0, 1.0), (10.0, 5.0, 5.0), (15.0, 10.0, 10.0), (20.0, 10.0, 10.0), (30.0, 15.0, 15.0)]
MAX_HOLD_MIN = (30, 60, 375)  # 375 = rest of the session
LAST_ENTRY = "14:45"
SQUARE_OFF = "15:10"
COST_08 = 0.8


def days_to_expiry(ts, weekday, weekly):
    """Calendar days (fractional, to 15:30 IST expiry) from bar time ts to the next expiry. Holidays ignored."""
    d = ts.date()
    if weekly:
        ahead = (weekday - d.weekday()) % 7
        exp = d + dt.timedelta(days=ahead)
    else:  # monthly: last <weekday> of the month, roll to next month once passed
        def last_wd(y, m):
            nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
            last = nxt - dt.timedelta(days=1)
            return last - dt.timedelta(days=(last.weekday() - weekday) % 7)
        exp = last_wd(d.year, d.month)
        if exp < d:
            exp = last_wd(d.year + (d.month == 12), d.month % 12 + 1)
    expiry_close = dt.datetime.combine(exp, dt.time(15, 30))
    now = dt.datetime.combine(d, ts.time())
    if now > expiry_close:  # after the close on expiry day: next cycle
        return days_to_expiry(pd.Timestamp(now + dt.timedelta(days=1)).replace(hour=9, minute=15), weekday, weekly)
    return max((expiry_close - now).total_seconds() / 86400.0, 5.0 / 1440.0)


def signals(main, frame, sym, tf):
    orb_m, fast, slow = A.SYMBOLS[sym]
    out = {"live_orb_trend_novol": A.live_orb(main, frame, orb_m, fast, slow, tf, False)}
    for name, fn in R.NV_TRIGGERS.items():
        out[name] = np.asarray(fn(frame), bool)
    return out


def replay(real, sig, right, name, tf, grid_row, max_hold_min, iv, lot, iv_days=None):
    """Strict FIFO per day; one open option at a time. Returns a list of trade dicts."""
    stop_pct, arm_pct, trail_pct = grid_row
    step, weekday, weekly = UNDERLYING_ROW[name]
    bar_min = A.TF_MIN[tf]
    ts = pd.to_datetime(real["Date"].str[:19])
    hhmm = real["Date"].str[11:16].to_numpy()
    day = real["Date"].str[:10].to_numpy()
    close = real["Close"].to_numpy(float)
    trades, i, n = [], 0, len(real)
    max_bars = max(1, max_hold_min // bar_min)
    while i < n - 1:
        if not sig[i] or hhmm[i] > LAST_ENTRY:
            i += 1
            continue
        end = i
        while end + 1 < n and day[end + 1] == day[i] and hhmm[end + 1] <= SQUARE_OFF and end - i < max_bars:
            end += 1
        if end == i:
            i += 1
            continue
        dte = days_to_expiry(ts.iloc[i], weekday, weekly)
        iv_i = iv_days.get(day[i], iv) if iv_days else iv
        r = P.simulate_long_option_trade(list(close[i:end + 1]), dte, step, right, 0, iv_i, lot,
                                         stop_pct, arm_pct, trail_pct, bar_min)
        ret = r["exit_premium"] / r["entry_premium"] - 1.0  # after modelled spread
        trades.append({"day": day[i], "entry": hhmm[i], "hold_bars": r["exit_bar"], "exit": r["exit_reason"],
                       "entry_premium": round(r["entry_premium"], 2), "ret": ret, "net_inr_proxy": r["net_pnl"],
                       "gross_inr": r["gross_pnl"]})
        i = i + r["exit_bar"] + 1
    return trades


def stats(trades, days_total):
    if not trades:
        return {"n": 0}
    r = np.array([t["ret"] for t in trades])
    r08 = r - COST_08 / 100.0

    def pf(x):
        w, l = x[x > 0].sum(), -x[x < 0].sum()
        return round(float(w / l), 3) if l > 0 else (None if w > 0 else 0.0)

    inr = np.array([t["net_inr_proxy"] for t in trades])
    return {"n": len(trades), "win_pct_08": round(float((r08 > 0).mean() * 100), 1), "pfnet_08": pf(r08),
            "avg_ret_pct_08": round(float(r08.mean() * 100), 2), "pfnet_proxy_inr": pf(inr),
            "net_inr_proxy_per_lot": round(float(inr.sum()), 0),
            "gw08": float(r08[r08 > 0].sum()), "gl08": float(-r08[r08 < 0].sum()),
            "net_inr_per_day": round(float(inr.sum()) / max(days_total, 1), 0),
            "avg_hold_bars": round(float(np.mean([t["hold_bars"] for t in trades])), 1),
            "exits": {k: sum(1 for t in trades if t["exit"] == k) for k in {t["exit"] for t in trades}}}


UNDERLYING_ROW = {}
VIX_MULT = {"NIFTY": 1.0, "SENSEX": 1.0, "BANKNIFTY": 1.15}  # BANKNIFTY IV runs above India VIX (assumption)


def vix_by_day():
    """IST date -> PREVIOUS session's India VIX close / 100 (no look-ahead). Empty dict on any failure."""
    try:
        import yfinance as yf
        v = yf.Ticker("^INDIAVIX").history(period="1y", interval="1d", auto_adjust=False)["Close"].dropna()
        days = [str(d)[:10] for d in v.index]
        return {days[k]: float(v.iloc[k - 1]) / 100.0 for k in range(1, len(days))}
    except Exception:
        return {}


def run(main, lo, hi_, synth=False, is_frac=0.6):
    out = {"label": P.PROXY_LABEL, "from": lo, "to": hi_, "cost_pct": COST_08, "is_frac": is_frac, "cells": []}
    vix = {} if synth or os.environ.get("IV_SOURCE", "vix") != "vix" else vix_by_day()
    out["iv_source"] = "india_vix_prev_close" if vix else "constant"
    for sym, (name, step, weekday, weekly) in UNDERLYING.items():
        UNDERLYING_ROW[name] = (step, weekday, weekly)
        iv = float(os.environ.get(f"IV_{name}", DEFAULT_IV[name]))
        lot = int(os.environ.get(f"LOT_{name}", DEFAULT_LOT[name]))
        iv_days = {d: x * VIX_MULT[name] for d, x in vix.items()}
        for tf in TFS:
            df = synthetic_intraday(sym) if synth else R.fetch(sym, tf)
            if df is None or not len(df):
                out["cells"].append({"sym": sym, "tf": tf, "error": "no data"})
                continue
            df = df[(df["Date"].str[:10] >= lo) & (df["Date"].str[:10] <= hi_)].reset_index(drop=True) \
                if not synth else df
            days = sorted(set(df["Date"].str[:10]))
            cut = days[int(len(days) * is_frac)] if days else ""
            for direction, right in (("long", "call"), ("short", "put")):
                frame = df if direction == "long" else R.flip(df)
                for trig, sig in signals(main, frame, sym, tf).items():
                    for grid_row in EXIT_GRID:
                        for mh in MAX_HOLD_MIN:
                            tr = replay(df, sig, right, name, tf, grid_row, mh, iv, lot, iv_days)
                            is_t = [t for t in tr if t["day"] < cut]
                            oos_t = [t for t in tr if t["day"] >= cut]
                            n_is = sum(1 for d in days if d < cut)
                            out["cells"].append({
                                "sym": sym, "tf": tf, "dir": direction, "trigger": trig,
                                "exit": "s{}_a{}_t{}".format(*[int(x) for x in grid_row]), "max_hold_min": mh,
                                "iv": iv, "lot": lot, "all": stats(tr, len(days)),
                                "is": stats(is_t, n_is), "oos": stats(oos_t, len(days) - n_is)})
    return out


def synthetic_intraday(sym, days=12):
    """Offline dry run only: 75 5m bars per weekday session with an IST timestamp string."""
    rng = np.random.default_rng(abs(hash(sym)) % (2 ** 32))
    rows, px = [], 20000.0
    d = dt.date(2026, 10, 1)
    while len({r[0][:10] for r in rows}) < days:
        if d.weekday() < 5:
            t = dt.datetime.combine(d, dt.time(9, 15))
            for _ in range(75):
                o = px
                px *= np.exp(rng.normal(0.0001, 0.0015))
                rows.append((t.strftime("%Y-%m-%d %H:%M:%S+05:30"), o, max(o, px) * 1.0005, min(o, px) * 0.9995, px, 0.0))
                t += dt.timedelta(minutes=5)
        d += dt.timedelta(days=1)
    return pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])


def viable(c):
    """Decision screen: OOS and IS both PFnet(0.8%) > 1.00 with >= 5 OOS trades."""
    o, i = c.get("oos", {}), c.get("is", {})
    return bool(o.get("n", 0) >= 5 and (o.get("pfnet_08") is None or o["pfnet_08"] > 1.0)
                and i.get("n", 0) >= 5 and (i.get("pfnet_08") is None or i["pfnet_08"] > 1.0))


def to_md(out):
    cells = [c for c in out["cells"] if "error" not in c and c["all"].get("n")]
    ok = [c for c in cells if viable(c)]
    best = sorted(cells, key=lambda c: (c["oos"].get("pfnet_08") or 0), reverse=True)[:25]
    lines = [f"# Index option premium-proxy replay (B-1746 step 3), {out['from']} to {out['to']} IST", "",
             f"**{out['label']}**: Black-Scholes proxy, IV = {out.get('iv_source')}, 1 ATM lot, single leg, quick exit (<=15:10 IST).",
             f"Decision metric: PFnet after the {out['cost_pct']}% cost model, IS and OOS both > 1.00, >= 5 OOS trades.",
             "", f"Cells tested: {len(cells)}. Pass both IS and OOS: **{len(ok)}**.", "",
             "Top 25 by OOS PFnet(0.8%):", "",
             "| Sym | TF | Dir | Trigger | Exit | Hold min | n | IS PF | OOS PF | OOS n | OOS avg % | INR/lot (proxy) | Pass |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in best:
        lines.append(f"| {c['sym']} | {c['tf']} | {c['dir']} | {c['trigger']} | {c['exit']} | {c['max_hold_min']} | "
                     f"{c['all']['n']} | {c['is'].get('pfnet_08')} | {c['oos'].get('pfnet_08')} | {c['oos'].get('n', 0)} | "
                     f"{c['oos'].get('avg_ret_pct_08')} | {c['all'].get('net_inr_proxy_per_lot')} | {'yes' if viable(c) else 'no'} |")
    pooled = {}
    for c in cells:
        k = (c["dir"], c["trigger"], c["exit"], c["max_hold_min"])
        g = pooled.setdefault(k, {"n": 0, "gw": 0.0, "gl": 0.0, "n_is": 0, "gw_is": 0.0, "gl_is": 0.0})
        g["n"] += c["oos"].get("n", 0); g["gw"] += c["oos"].get("gw08", 0.0); g["gl"] += c["oos"].get("gl08", 0.0)
        g["n_is"] += c["is"].get("n", 0); g["gw_is"] += c["is"].get("gw08", 0.0); g["gl_is"] += c["is"].get("gl08", 0.0)
    rows = []
    for k, g in pooled.items():
        pf_o = g["gw"] / g["gl"] if g["gl"] > 0 else float("inf")
        pf_i = g["gw_is"] / g["gl_is"] if g["gl_is"] > 0 else float("inf")
        rows.append((pf_o, pf_i, k, g))
    rows.sort(key=lambda x: x[0], reverse=True)
    lines += ["", "Pooled over all 3 indices and both TFs (house wiring rule: pooled PFnet > 1.00), top 15 by OOS:", "",
              "| Dir | Trigger | Exit | Hold min | IS n | IS PF | OOS n | OOS PF | Pass |", "|---|---|---|---|---|---|---|---|---|"]
    for pf_o, pf_i, k, g in rows[:15]:
        ok_p = pf_o > 1.0 and pf_i > 1.0 and g["n"] >= 10
        lines.append(f"| {k[0]} | {k[1]} | {k[2]} | {k[3]} | {g['n_is']} | {pf_i:.2f} | {g['n']} | {pf_o:.2f} | "
                     f"{'yes' if ok_p else 'no'} |")
    out["pooled_pass"] = sum(1 for pf_o, pf_i, k, g in rows if pf_o > 1.0 and pf_i > 1.0 and g["n"] >= 10)
    lines += ["", f"Pooled combos passing IS and OOS: **{out['pooled_pass']}** of {len(rows)}. "
              f"{len(cells)} single cells were tested, so single-cell passes include multiple-testing luck."]
    return "\n".join(lines) + "\n"


def main_cli():
    import main as M
    lo, hi_ = os.environ.get("FROM", "2026-10-01"), os.environ.get("TO", "2026-11-26")
    out = run(M, lo, hi_, synth=os.environ.get("SYNTH") == "1", is_frac=float(os.environ.get("IS_FRAC", "0.6")))
    od = os.environ.get("OUT_DIR", "docs")
    os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, "index_option_premium_replay.json"), "w"), indent=1, sort_keys=True,
              default=str)
    md = to_md(out)
    open(os.path.join(od, "index_option_premium_replay.md"), "w").write(md)
    print(md)


if __name__ == "__main__":
    main_cli()
