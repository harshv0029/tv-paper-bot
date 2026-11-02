"""B-1443: return on deployed capital (ROC) KPIs for View 4's capital block. Pure functions, no I/O.

Input is the durable Kotak fill ledger (``kotak_fill_ledger`` in main.py): one row per IST day, Kotak trading symbol
and product, holding that day's filled buy/sell qty and value straight from Kotak positions() (Kotak wins), plus a
one-time set of ``opening`` rows for holdings that were already open when the ledger started (from tracked_union).

Definitions (shown to the user in the View 4 tooltip):
  * Closed trade: FIFO match per symbol. A day's closing flow first closes lots carried from earlier days (oldest
    first), the rest of the day's buys and sells pair as a same-day round trip, and any remainder opens a new lot.
  * Net P&L = sell value - buy value - estimated statutory charges (STT, exchange, SEBI, stamp, GST; brokerage is
    plan-specific and not in Kotak's data, so it is left out). Booked on the exit day.
  * Deployed capital on a day = sum of the entry value of every lot held at any point that day (a lot occupies its
    entry value on each calendar day from entry day to exit day inclusive; a same-day round trip counts on its day).
    Entry value is the buy value for a long and the sell value for a short.
  * ROC % = net P&L of trades exited in the period / average daily deployed capital over the period's covered days.
    Covered days are calendar days from the ledger's first Kotak day up to today; days before that are not invented.
  * Per trade: return % = (sell value - buy value) / buy value (mirror for a short: / sell value), holding days =
    exit day - entry day (0 for a same-day trade), return per day = return % / max(holding days, 1).
  * B-1445 side of a same-day round trip: Kotak positions() day aggregates carry no fill order, so the side comes
    from the order of fills when known: a ledger row's ``first_fill_side`` ('buy'/'sell', from Kotak trade/order book
    timestamps) wins, else this app's own record of the entry (``side_hints[(trdsym, day)]`` built from
    real_order_events 'entry'/'short_entry' confirmations and real_positions_short). First fill a sell -> short.
    When the order is unknown the side is SIDE_UNKNOWN, never guessed as long. P&L is identical either way.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

DAY = dt.timedelta(days=1)
SIDE_UNKNOWN = "intraday (side unknown)"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def side_hints_from_app_records(order_events=None, open_shorts=None) -> dict:
    """B-1445: {(trdsym, 'YYYY-MM-DD' IST): 'long'|'short'} from this app's own records of what it entered.
    order_events: dicts with ts (epoch s), kotak_trading_symbol, leg, event; the EARLIEST confirmed entry of the day
    decides (leg 'short_entry' -> short, 'entry' -> long). open_shorts: dicts with kotak_trading_symbol, day."""
    first = {}
    for e in order_events or []:
        try:
            if str(e.get("event") or "") != "confirmed":
                continue
            leg = str(e.get("leg") or "")
            side = "short" if leg == "short_entry" else "long" if leg == "entry" else None
            sym = str(e.get("kotak_trading_symbol") or "")
            if not side or not sym:
                continue
            ts = float(e["ts"])
            k = (sym, dt.datetime.fromtimestamp(ts, IST).date().isoformat())
            if k not in first or ts < first[k][0]:
                first[k] = (ts, side)
        except (TypeError, ValueError, KeyError):
            continue
    hints = {k: v[1] for k, v in first.items()}
    for r in open_shorts or []:
        sym, day = str(r.get("kotak_trading_symbol") or ""), str(r.get("day") or "")[:10]
        if sym and day:
            hints.setdefault((sym, day), "short")
    return hints


def _same_day_side(row: dict, sym: str, day: dt.date, side_hints) -> str:
    f = str(row.get("first_fill_side") or "").lower()
    if f in ("buy", "b"):
        return "long"
    if f in ("sell", "s"):
        return "short"
    h = (side_hints or {}).get((sym, day.isoformat()))
    return h if h in ("long", "short") else SIDE_UNKNOWN


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(str(s)[:10])


def period_bounds(today: dt.date) -> dict:
    """IST calendar periods: last calendar month, month-to-date, rolling last 30 calendar days (today inclusive)."""
    first_this = today.replace(day=1)
    last_prev = first_this - DAY
    return {
        "last_month": (last_prev.replace(day=1), last_prev, last_prev.strftime("%b %Y")),
        "mtd": (first_this, today, today.strftime("%b %Y") + " to date"),
        "rolling_30d": (today - 29 * DAY, today, "last 30 days"),
    }


def match_round_trips(ledger_rows: list, charges_fn=None, side_hints=None) -> tuple[list, list, list]:
    """FIFO-match ledger rows into closed trades. Returns (closed, open_lots, notes).
    charges_fn(seg, trdsym, prod, buy_amt, sell_amt) -> INR; None means zero charges.
    side_hints: {(trdsym, day iso): 'long'|'short'} for same-day round trips (B-1445); see module docstring."""
    by_sym = defaultdict(list)
    for r in ledger_rows or []:
        by_sym[r["trdsym"]].append(r)
    closed, open_lots, notes = [], [], []  # notes reserved for data caveats

    def _close(sym, seg, prod, lot, qty, exit_day, exit_px, src):
        long_ = lot["side"] != "short"  # long or side-unknown: buy at lot px, sell at exit px (same P&L)
        buy_v = (lot["px"] if long_ else exit_px) * qty
        sell_v = (exit_px if long_ else lot["px"]) * qty
        ch = float(charges_fn(seg, sym, prod, buy_v, sell_v)) if charges_fn else 0.0
        base = buy_v if long_ else sell_v
        hold = (exit_day - lot["day"]).days
        ret = (sell_v - buy_v) / base * 100 if base else None
        closed.append({"symbol": sym, "side": lot["side"], "qty": qty, "entry_day": lot["day"].isoformat(),
                       "exit_day": exit_day.isoformat(), "buy_value_inr": round(buy_v, 2),
                       "sell_value_inr": round(sell_v, 2), "entry_value_inr": round(base, 2),
                       "gross_pnl_inr": round(sell_v - buy_v, 2), "charges_inr": round(ch, 2),
                       "net_pnl_inr": round(sell_v - buy_v - ch, 2),
                       "return_pct": round(ret, 3) if ret is not None else None, "holding_days": hold,
                       "return_per_day_pct": round(ret / max(hold, 1), 3) if ret is not None else None,
                       "source": src})

    for sym, rows in by_sym.items():
        rows = sorted(rows, key=lambda r: (str(r["day"]), 0 if r.get("source") == "opening" else 1))
        lots = []  # FIFO: {side, qty, px, day}
        for r in rows:
            day = _d(r["day"])
            seg, prod = r.get("seg"), r.get("prod")
            bq, ba = float(r.get("buy_qty") or 0), float(r.get("buy_amt") or 0)
            sq, sa = float(r.get("sell_qty") or 0), float(r.get("sell_amt") or 0)
            bpx = ba / bq if bq > 0 else 0.0
            spx = sa / sq if sq > 0 else 0.0
            src = "opening_lot" if r.get("source") == "opening" else "kotak_positions"
            # 1) close carried lots (oldest first) with the opposite flow
            while lots:
                lot = lots[0]
                avail = sq if lot["side"] == "long" else bq
                if avail <= 0:
                    break
                q = min(avail, lot["qty"])
                _close(sym, seg, prod, lot, q, day, spx if lot["side"] == "long" else bpx, src)
                lot["qty"] -= q
                if lot["side"] == "long":
                    sq -= q
                else:
                    bq -= q
                if lot["qty"] <= 1e-9:
                    lots.pop(0)
            # 2) same-day round trip
            q = min(bq, sq)
            if q > 0:
                side = _same_day_side(r, sym, day, side_hints)
                if side == "short":
                    same = {"side": "short", "qty": q, "px": spx, "day": day}
                    _close(sym, seg, prod, same, q, day, bpx, src)
                else:
                    same = {"side": side, "qty": q, "px": bpx, "day": day}
                    _close(sym, seg, prod, same, q, day, spx, src)
                bq -= q
                sq -= q
            # 3) remainder opens a new lot (step 1 left no opposite lot, step 2 left at most one side)
            if bq > 1e-9:
                lots.append({"side": "long", "qty": bq, "px": bpx, "day": day})
            if sq > 1e-9:
                if str(prod or "").upper() == "CNC":  # a delivery sell with no lot is a pre-ledger holding, not a short
                    notes.append(f"{sym}: {sq:g} sold on {day.isoformat()} with no recorded entry (bought before the "
                                 "ledger started); left out, not guessed")
                else:
                    lots.append({"side": "short", "qty": sq, "px": spx, "day": day})
        for lot in lots:
            open_lots.append({"symbol": sym, "side": lot["side"], "qty": lot["qty"], "entry_day": lot["day"].isoformat(),
                              "entry_value_inr": round(lot["qty"] * lot["px"], 2)})
    return closed, open_lots, notes


def _deployed_by_day(closed: list, open_lots: list, start: dt.date, end: dt.date, as_of: dt.date) -> dict:
    out = {}
    spans = [(_d(t["entry_day"]), _d(t["exit_day"]), t["entry_value_inr"]) for t in closed]
    spans += [(_d(o["entry_day"]), as_of, o["entry_value_inr"]) for o in open_lots]
    d = start
    while d <= end:
        out[d] = sum(v for a, b, v in spans if a <= d <= b)
        d += DAY
    return out


def roc_kpis(ledger_rows: list, today: dt.date, charges_fn=None, trades_limit: int = 50, side_hints=None) -> dict:
    """The three ROC KPIs plus the per-trade list. Never invents data: a period with no covered day, or zero
    average deployed capital, returns roc_pct None with the reason."""
    closed, open_lots, notes = match_round_trips(ledger_rows, charges_fn, side_hints)
    kotak_days = sorted({str(r["day"])[:10] for r in ledger_rows or [] if r.get("source") != "opening"})
    ledger_start = _d(kotak_days[0]) if kotak_days else None
    out = {"ledger_start": ledger_start.isoformat() if ledger_start else None, "as_of": today.isoformat(),
           "periods": {}, "open_lots": len(open_lots), "notes": notes}
    for key, (a, b, label) in period_bounds(today).items():
        p = {"label": label, "start": a.isoformat(), "end": b.isoformat(), "roc_pct": None, "net_pnl_inr": None,
             "avg_deployed_inr": None, "trades": 0, "covered_days": 0, "period_days": (b - a).days + 1, "reason": None}
        if ledger_start is None:
            p["reason"] = "no Kotak fill ledger yet (it fills from Kotak positions from the first capture on)"
        else:
            ca, cb = max(a, ledger_start), min(b, today)
            if ca > cb:
                p["reason"] = f"Kotak fill ledger starts {ledger_start.isoformat()}; no captured day in this period"
            else:
                dep = _deployed_by_day(closed, open_lots, ca, cb, today)
                ts = [t for t in closed if ca <= _d(t["exit_day"]) <= cb]
                net = sum(t["net_pnl_inr"] for t in ts)
                avg = sum(dep.values()) / len(dep)
                p.update(covered_days=len(dep), trades=len(ts), net_pnl_inr=round(net, 2),
                         avg_deployed_inr=round(avg, 2),
                         gross_pnl_inr=round(sum(t["gross_pnl_inr"] for t in ts), 2),
                         charges_inr=round(sum(t["charges_inr"] for t in ts), 2))
                if avg <= 0:
                    p["reason"] = "no capital deployed in the covered days"
                else:
                    p["roc_pct"] = round(net / avg * 100, 3)
                    if len(dep) < p["period_days"]:
                        p["reason"] = (f"partial: covers {len(dep)} of {p['period_days']} days "
                                       f"(ledger starts {ledger_start.isoformat()})")
        out["periods"][key] = p
    out["closed_trades"] = sorted(closed, key=lambda t: (t["exit_day"], t["symbol"]), reverse=True)[:trades_limit]
    out["closed_trades_total"] = len(closed)
    return out
