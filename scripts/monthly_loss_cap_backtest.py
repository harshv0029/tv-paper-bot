"""B-751: Elder's 6% monthly loss cap as a portfolio overlay on stored trades.

Rule: once month-to-date REALIZED loss (by exit date, calendar month) reaches
cap% of month-start equity, no new entries for the rest of that month. Open
positions keep running (their stops are live). Sizing: fixed-fractional, each
trade risks risk% of current realized equity, so P&L = equity * risk% * net_r.

Input (CSV or JSON list) columns:
  strategy, entry_date, exit_date  (YYYY-MM-DD[...]),
  net_r            net P&L in R (net_pnl / initial risk), OR
  net_return_pct + risk_frac   (net % return on notional; stop distance as a
                                fraction of entry, e.g. 0.04) -> net_r = ret/(100*risk_frac)
Usage: python scripts/monthly_loss_cap_backtest.py trades.csv [--caps 0,4,6,8] [--risks 1,2] [--json out.json]
When risk_frac is given, notional is capped at max_pos_pct (default 25%) of equity, as live tranches do.
"""
import argparse
import csv
import json
import sys


def load_trades(path):
    if path.endswith(".json"):
        rows = json.load(open(path))
    else:
        rows = list(csv.DictReader(open(path)))
    out = []
    for r in rows:
        rf = r.get("risk_frac")
        rf = float(rf) if rf not in (None, "") else None
        if r.get("net_r") not in (None, ""):
            nr = float(r["net_r"])
        else:
            if not rf or rf <= 0:
                continue
            nr = float(r["net_return_pct"]) / (100.0 * rf)
        out.append({"strategy": r.get("strategy") or "all", "entry": str(r["entry_date"])[:10],
                    "exit": str(r["exit_date"])[:10], "net_r": nr, "risk_frac": rf,
                    "side": str(r.get("side") or r.get("direction") or "long").lower()})
    return out


def filter_side(trades, side):
    """B-773: short/intraday coverage. side in (None, 'all', 'long', 'short'); input rows may carry a
    side/direction column (default long). Pure."""
    if side in (None, "", "all"):
        return trades
    return [t for t in trades if t.get("side", "long") == side]


def _pf(pnls):
    w = sum(p for p in pnls if p > 0)
    l = -sum(p for p in pnls if p <= 0)
    return (w / l) if l > 0 else (float("inf") if w > 0 else 0.0)


def simulate(trades, cap_pct, risk_pct, start_equity=1.0, max_pos_pct=25.0, max_open=10):
    """cap_pct=0/None -> no cap. Returns dict of metrics."""
    ev = []
    for i, t in enumerate(trades):
        # exits before entries on a day, except a same-day round trip (entry first)
        ev.append((t["exit"], 0 if t["exit"] > t["entry"] else 2, i))
        ev.append((t["entry"], 1, i))
    ev.sort(key=lambda e: (e[0], e[1]))  # exits before entries on the same day
    eq = start_equity
    peak, max_dd = eq, 0.0
    month, month_start, mtd, halted = None, eq, 0.0, False
    open_pos = {}
    done, skipped = [], []
    for date, kind, i in ev:
        m = date[:7]
        if m != month:
            month, month_start, mtd, halted = m, eq, 0.0, False
        t = trades[i]
        if kind == 1:
            risk = risk_pct / 100.0
            if t["risk_frac"]:  # notional cap: risk / risk_frac <= max_pos_pct%
                risk = min(risk, max_pos_pct / 100.0 * t["risk_frac"])
            if len(open_pos) >= max_open:  # portfolio capacity: live bot cannot hold thousands at once
                continue
            if halted:
                skipped.append({"strategy": t["strategy"], "would": eq * risk * t["net_r"]})
                continue
            open_pos[i] = eq * risk
        else:
            if i not in open_pos:
                continue
            pnl = open_pos.pop(i) * t["net_r"]
            eq += pnl
            mtd += pnl
            done.append({"strategy": t["strategy"], "pnl": pnl})
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak)
            if cap_pct and mtd <= -cap_pct / 100.0 * month_start:
                halted = True
    pnls = [d["pnl"] for d in done]
    per = {}
    for d in done:
        per.setdefault(d["strategy"], []).append(d["pnl"])
    sk = {}
    for s in skipped:
        sk[s["strategy"]] = sk.get(s["strategy"], 0) + 1
    return {
        "cap_pct": cap_pct or 0, "risk_pct": risk_pct, "n_taken": len(done), "n_skipped": len(skipped),
        "pfnet": _pf(pnls), "win_pct": 100.0 * sum(p > 0 for p in pnls) / len(pnls) if pnls else 0.0,
        "total_return_pct": 100.0 * (eq / start_equity - 1), "max_dd_pct": 100.0 * max_dd,
        "profit_forgone": sum(s["would"] for s in skipped if s["would"] > 0),
        "loss_avoided": -sum(s["would"] for s in skipped if s["would"] <= 0),
        "per_strategy": {k: {"n": len(v), "pfnet": _pf(v), "win_pct": 100.0 * sum(p > 0 for p in v) / len(v),
                             "net_pnl": sum(v), "skipped": sk.get(k, 0)} for k, v in per.items()},
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("trades")
    ap.add_argument("--caps", default="0,4,6,8")
    ap.add_argument("--risks", default="1,2")
    ap.add_argument("--json")
    ap.add_argument("--max-open", type=int, default=10, help="max concurrent positions (portfolio capacity)")
    ap.add_argument("--side", default="all", choices=["all", "long", "short"])
    a = ap.parse_args(argv)
    trades = filter_side(load_trades(a.trades), a.side)
    res = []
    print(f"{len(trades)} trades")
    print("risk% cap% taken skip  PFnet  win%  totRet%  maxDD%  forgone  avoided (units of start equity)")
    for rk in [float(x) for x in a.risks.split(",")]:
        for cp in [float(x) for x in a.caps.split(",")]:
            r = simulate(trades, cp, rk, max_open=a.max_open)
            res.append(r)
            print(f"{rk:5.1f} {cp:4.0f} {r['n_taken']:6d} {r['n_skipped']:4d} {r['pfnet']:6.3f} {r['win_pct']:5.1f} "
                  f"{r['total_return_pct']:8.1f} {r['max_dd_pct']:7.1f} {r['profit_forgone']:8.3f} {r['loss_avoided']:8.3f}")
    for r in res:
        if r["cap_pct"] in (0, 6.0):
            print(f"-- per strategy, risk {r['risk_pct']}% cap {r['cap_pct']}%")
            for k, v in sorted(r["per_strategy"].items()):
                print(f"   {k}: n={v['n']} PFnet={v['pfnet']:.3f} win={v['win_pct']:.1f}% pnl={v['net_pnl']:.3f} skipped={v['skipped']}")
    if a.json:
        json.dump(res, open(a.json, "w"), indent=1, default=str)
    return res


if __name__ == "__main__":
    main()
