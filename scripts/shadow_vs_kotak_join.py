#!/usr/bin/env python3
"""B-547: join signal_shadow_log rows to Kotak trade/order-book fills -> per-tag realised net P&L.

Offline and read-only. Inputs are two JSON files:
  --shadow  list of signal_shadow_log rows (ts, day, strategy_tag, symbol, direction, taken, reason,
            hard_gate; optional predicted_net_pct = shadow-predicted net return % for that signal)
  --fills   Kotak order_report/trade-book rows (trdSym, trnsTp B/S, fldQty, avgPrc, ordSt, ordDtTm);
            either a bare list or {"data": [...]}. Only COMPLETE rows with fldQty>0 are used.
Fills are FIFO-matched per symbol into round trips (long: B opens; short: S opens). Each round trip is
attributed to the TAKEN shadow row for the same symbol+direction on the entry-fill's IST day (a tag is
never merged with another; two differently-tagged taken rows on one symbol/day => bucket AMBIGUOUS).
Net = gross - cost_pct% of entry notional (ROUND_TRIP_COST_PCT, 0.8 in main.py). Open lots are reported
as open_qty, never valued. Usage: shadow_vs_kotak_join.py --shadow s.json --fills f.json [--cost-pct 0.8]
"""
import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_COST_PCT = 0.8  # mirrors main.ROUND_TRIP_COST_PCT (literal so this script never imports main)
_FMTS = ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S")


def norm_symbol(s):
    """RELIANCE.NS / RELIANCE-EQ / RELIANCE -> RELIANCE (Kotak and yfinance spellings meet here)."""
    s = str(s or "").upper().strip()
    s = re.sub(r"\.(NS|BO)$", "", s)
    s = re.sub(r"-(EQ|BE|BZ)$", "", s)
    return s


def parse_ts(v):
    """Kotak ordDtTm string or epoch -> aware IST datetime (None if unparseable)."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(float(v), IST)
    t = str(v).strip()
    for f in _FMTS:
        try:
            return datetime.strptime(t, f).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def _rows(obj):
    if isinstance(obj, dict):
        obj = obj.get("data") or obj.get("rows") or []
    return [r for r in obj if isinstance(r, dict)]


def load_fills(raw):
    out = []
    for i, r in enumerate(_rows(raw)):
        if str(r.get("ordSt", "complete")).lower() != "complete":
            continue
        try:
            q = int(float(r.get("fldQty") or 0))
            p = float(r.get("avgPrc") or 0)
        except (TypeError, ValueError):
            continue
        side = str(r.get("trnsTp", "")).upper()
        t = parse_ts(r.get("ordDtTm"))
        if q <= 0 or p <= 0 or side not in ("B", "S") or t is None:
            continue
        out.append({"sym": norm_symbol(r.get("trdSym")), "side": side, "qty": q, "px": p, "t": t, "i": i})
    out.sort(key=lambda f: (f["t"], f["i"]))
    return out


def round_trips(fills):
    """FIFO per symbol. Returns (trips, open_qty_by_symbol)."""
    books = defaultdict(list)  # sym -> open lots [side, qty_left, px, t]
    trips = []
    for f in fills:
        book = books[f["sym"]]
        left = f["qty"]
        while left > 0 and book and book[0][0] != f["side"]:
            lot = book[0]
            q = min(left, lot[1])
            long = lot[0] == "B"
            gross = q * ((f["px"] - lot[2]) if long else (lot[2] - f["px"]))
            trips.append({"sym": f["sym"], "direction": "long" if long else "short", "qty": q,
                          "entry_t": lot[3], "entry_px": lot[2], "exit_t": f["t"], "exit_px": f["px"], "gross": gross})
            lot[1] -= q
            left -= q
            if lot[1] == 0:
                book.pop(0)
        if left > 0:
            book.append([f["side"], left, f["px"], f["t"]])
    open_qty = {s: sum(l[1] for l in b) for s, b in books.items() if b}
    return trips, open_qty


def _taken_index(shadow):
    idx = defaultdict(set)  # (sym, direction, day) -> {tags}
    pred = defaultdict(list)  # (sym, direction, day, tag) -> predicted pct values
    for r in _rows(shadow):
        if not int(r.get("taken") or 0):
            continue
        key = (norm_symbol(r.get("symbol")), str(r.get("direction") or "").lower(), str(r.get("day") or ""))
        tag = str(r.get("strategy_tag") or "UNTAGGED")
        idx[key].add(tag)
        if r.get("predicted_net_pct") is not None:
            try:
                pred[key + (tag,)].append(float(r["predicted_net_pct"]))
            except (TypeError, ValueError):
                pass
    return idx, pred


def join(shadow, fills_raw, cost_pct=DEFAULT_COST_PCT):
    fills = load_fills(fills_raw)
    trips, open_qty = round_trips(fills)
    idx, pred = _taken_index(shadow)
    tags = defaultdict(lambda: {"trips": 0, "wins": 0, "gross": 0.0, "cost": 0.0, "net": 0.0,
                                "pred_sum": 0.0, "pred_n": 0, "real_pct_sum": 0.0})
    unattributed = []
    for t in trips:
        key = (t["sym"], t["direction"], t["entry_t"].strftime("%Y-%m-%d"))
        cands = idx.get(key, set())
        tag = None if not cands else (next(iter(cands)) if len(cands) == 1 else "AMBIGUOUS")
        notional = t["qty"] * t["entry_px"]
        cost = notional * cost_pct / 100.0
        net = t["gross"] - cost
        if tag is None:
            unattributed.append({"symbol": t["sym"], "direction": t["direction"], "qty": t["qty"],
                                 "entry_day": key[2], "net": round(net, 2)})
            continue
        a = tags[tag]
        a["trips"] += 1
        a["wins"] += 1 if net > 0 else 0
        a["gross"] += t["gross"]
        a["cost"] += cost
        a["net"] += net
        a["real_pct_sum"] += net / notional * 100.0
        p = pred.get(key + (tag,))
        if p:
            a["pred_sum"] += sum(p) / len(p)
            a["pred_n"] += 1
    out_tags = {}
    for tag, a in sorted(tags.items()):
        row = {"round_trips": a["trips"], "win_pct": round(100.0 * a["wins"] / a["trips"], 1),
               "gross_inr": round(a["gross"], 2), "cost_inr": round(a["cost"], 2), "net_inr": round(a["net"], 2),
               "realised_net_pct_avg": round(a["real_pct_sum"] / a["trips"], 3)}
        if a["pred_n"]:
            row["predicted_net_pct_avg"] = round(a["pred_sum"] / a["pred_n"], 3)
            row["realised_minus_predicted_pct"] = round(row["realised_net_pct_avg"] - row["predicted_net_pct_avg"], 3)
        else:
            row["predicted_net_pct_avg"] = None
            row["realised_minus_predicted_pct"] = None
        out_tags[tag] = row
    taken = defaultdict(int)
    skipped = defaultdict(lambda: {"hard_gate": 0, "discretionary": 0})
    for r in _rows(shadow):
        tag = str(r.get("strategy_tag") or "UNTAGGED")
        if int(r.get("taken") or 0):
            taken[tag] += 1
        else:
            skipped[tag]["hard_gate" if int(r.get("hard_gate") or 0) else "discretionary"] += 1
    return {"cost_pct": cost_pct, "tags": out_tags, "shadow_taken_by_tag": dict(taken),
            "shadow_taken_without_kotak_roundtrip": {k: max(0, n - out_tags.get(k, {}).get("round_trips", 0))
                                                     for k, n in taken.items()},
            "shadow_skipped_by_tag": dict(skipped), "unattributed_kotak_roundtrips": unattributed,
            "open_qty_by_symbol": open_qty,
            "total_net_inr": round(sum(v["net_inr"] for v in out_tags.values()), 2)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--shadow", required=True)
    ap.add_argument("--fills", required=True)
    ap.add_argument("--cost-pct", type=float, default=DEFAULT_COST_PCT)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    with open(a.shadow) as f:
        sh = json.load(f)
    with open(a.fills) as f:
        fl = json.load(f)
    txt = json.dumps(join(sh, fl, a.cost_pct), indent=2, sort_keys=True)
    if a.out:
        with open(a.out, "w") as f:
            f.write(txt + "\n")
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
