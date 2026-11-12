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
  * B-1451 since-start KPIs (ledger start to today, covered days only):
      - Return on deployed capital R = total net P&L of exited trades / average daily deployed capital.
      - CAGR % = ((1 + R) ^ (365 / covered days) - 1) x 100: R compounded to a yearly rate.
      - XIRR % = the annual rate that makes the net present value of every closed trade's cash flows zero
        (entry day: -entry value; exit day: +entry value + net P&L), i.e. the money-weighted annual return of the
        realised trades. Open lots are left out (no Kotak exit price yet), and said so.
      Both are annualised; under MIN_ANNUALISE_DAYS covered days they are still computed but flagged unreliable.
  * B-1451 rolling 30-day series: for each covered day d, the ROC % over the 30 calendar days ending on d
    (same formula as the rolling_30d period), so the trend is visible, not only today's value.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

DAY = dt.timedelta(days=1)
MIN_ANNUALISE_DAYS = 90
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


def merge_contract_note_fills(ledger_rows: list, note: dict | None) -> list:
    """B-1564: Kotak's own contract notes win. On each covered day, the note's rows replace the ledger's rows for the
    same symbol; a ledger 'opening' row (tracked_union guess) dated on or after the first covered day is dropped for
    any symbol the notes record a buy for, since the note carries that buy. Note 'opening' rows (pre-window buys
    whose exit falls in the window) are added unless the ledger already has an opening row for that symbol and day."""
    if not note or not note.get("rows"):
        return list(ledger_rows or [])
    days = set(note.get("covered_days") or [])
    first = min(days) if days else None
    nrows = [dict(r) for r in note["rows"]]
    bought = {r["trdsym"] for r in nrows if float(r.get("buy_qty") or 0) > 0}
    out = []
    for r in ledger_rows or []:
        d, sym = str(r["day"])[:10], r["trdsym"]
        if r.get("source") == "opening":
            if first and d >= first and sym in bought:
                continue
        elif d in days:
            continue  # a covered day: Kotak's contract note is the full record of that day's fills
        out.append(r)
    have_open = {(str(r["day"])[:10], r["trdsym"]) for r in out if r.get("source") == "opening"}
    for r in nrows:
        if r.get("source") == "opening" and (r["day"], r["trdsym"]) in have_open:
            continue
        out.append(r)
    return out


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
            src = {"opening": "opening_lot", "contract_note": "kotak_contract_note"}.get(r.get("source"), "kotak_positions")
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
                              "entry_value_inr": round(lot["qty"] * lot["px"], 2), "entry_px": lot["px"],
                              "seg": seg, "prod": prod})  # B-1461: seg/prod/px for the mark-to-market running CAGR
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
    out["since_start"] = since_start_kpis(closed, open_lots, ledger_start, today)
    out["rolling_30d_series"] = rolling_30d_series(closed, open_lots, ledger_start, today)
    out["closed_trades"] = sorted(closed, key=lambda t: (t["exit_day"], t["symbol"]), reverse=True)[:trades_limit]
    out["closed_trades_total"] = len(closed)
    out["open_lot_rows"] = open_lots  # B-1461: for the running (mark-to-market) CAGR
    return out


def xirr(flows: list) -> float | None:
    """B-1451: annual rate r with sum(cf / (1 + r) ** (days / 365)) = 0 over [(date, cf)]. None when undefined
    (no flows of both signs) or when no root is found. Bisection on a bracket, so it never diverges."""
    flows = [(d, float(cf)) for d, cf in flows if cf]
    if not flows or not any(cf > 0 for _, cf in flows) or not any(cf < 0 for _, cf in flows):
        return None
    d0 = min(d for d, _ in flows)

    def npv(r):
        return sum(cf / (1.0 + r) ** ((d - d0).days / 365.0) for d, cf in flows)

    lo, hi = -0.9999, 1.0
    f_lo = npv(lo)
    while npv(hi) * f_lo > 0:
        hi *= 4
        if hi > 1e9:
            return None
    for _ in range(300):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7 or hi - lo < 1e-12:
            break
        if f_mid * f_lo > 0:
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2


def since_start_kpis(closed: list, open_lots: list, ledger_start, today: dt.date) -> dict:
    """B-1451: return, CAGR and XIRR from the ledger's first Kotak day to today. Never invents data."""
    out = {"start": ledger_start.isoformat() if ledger_start else None, "end": today.isoformat(),
           "covered_days": 0, "trades": 0, "net_pnl_inr": None, "avg_deployed_inr": None, "return_pct": None,
           "cagr_pct": None, "xirr_pct": None, "open_lots_excluded": len(open_lots), "reason": None,
           "unreliable": False}
    if ledger_start is None or ledger_start > today:
        out["reason"] = "no Kotak fill ledger yet"
        return out
    dep = _deployed_by_day(closed, open_lots, ledger_start, today, today)
    ts = [t for t in closed if ledger_start <= _d(t["exit_day"]) <= today]
    net = sum(t["net_pnl_inr"] for t in ts)
    avg = sum(dep.values()) / len(dep)
    days = len(dep)
    out.update(covered_days=days, trades=len(ts), net_pnl_inr=round(net, 2), avg_deployed_inr=round(avg, 2),
               gross_pnl_inr=round(sum(t["gross_pnl_inr"] for t in ts), 2),  # B-1460: before charges
               charges_inr=round(sum(t["charges_inr"] for t in ts), 2))
    notes = []
    if avg > 0:
        r = net / avg
        out["return_pct"] = round(r * 100, 3)
        if 1 + r > 0:
            out["cagr_pct"] = round(((1 + r) ** (365.0 / days) - 1) * 100, 2)
        else:
            notes.append("CAGR undefined: loss larger than the average deployed capital")
    else:
        notes.append("no capital deployed yet")
    flows = []
    for t in ts:
        flows.append((_d(t["entry_day"]), -t["entry_value_inr"]))
        flows.append((_d(t["exit_day"]), t["entry_value_inr"] + t["net_pnl_inr"]))
    x = xirr(flows)
    if x is not None:
        out["xirr_pct"] = round(x * 100, 2)
    elif ts:
        notes.append("XIRR undefined for these cash flows")
    if days < MIN_ANNUALISE_DAYS:
        out["unreliable"] = True
        notes.append(f"annualised from only {days} days, so CAGR and XIRR swing widely; reliable after "
                     f"{MIN_ANNUALISE_DAYS} days")
    if open_lots:
        notes.append(f"XIRR uses closed trades only; {len(open_lots)} open lot(s) left out until exited")
    out["reason"] = "; ".join(notes) or None
    return out


def rolling_30d_series(closed: list, open_lots: list, ledger_start, today: dt.date) -> list:
    """B-1451: [{day, roc_pct, net_pnl_inr, avg_deployed_inr, full_window}] for every covered day, oldest first.
    roc_pct None on a day with no capital deployed in its window."""
    if ledger_start is None or ledger_start > today:
        return []
    dep = _deployed_by_day(closed, open_lots, ledger_start, today, today)
    pnl_by_day = defaultdict(float)
    for t in closed:
        pnl_by_day[_d(t["exit_day"])] += t["net_pnl_inr"]
    out = []
    d = ledger_start
    while d <= today:
        a = max(d - 29 * DAY, ledger_start)
        win = [dep[x] for x in dep if a <= x <= d]
        avg = sum(win) / len(win)
        net = sum(v for x, v in pnl_by_day.items() if a <= x <= d)
        out.append({"day": d.isoformat(), "roc_pct": round(net / avg * 100, 3) if avg > 0 else None,
                    "net_pnl_inr": round(net, 2), "avg_deployed_inr": round(avg, 2),
                    "full_window": (d - a).days == 29})
        d += DAY
    return out


def running_kpis(since_start: dict, open_lots: list, price_by_symbol: dict, charges_fn=None) -> dict:
    """B-1461: running (mark-to-market) return and CAGR since start = realised net P&L of exited trades PLUS the
    unrealised net P&L of every open lot (holdings and positions) valued at its live price, over the same average
    deployed capital and covered days as since_start. Unrealised net deducts the statutory charges an exit at that
    price would cost (brokerage not included). A lot with no live price is left out and counted, never guessed."""
    out = {"realised_net_inr": since_start.get("net_pnl_inr"), "unrealised_gross_inr": None,
           "unrealised_charges_inr": None, "unrealised_net_inr": None, "total_net_inr": None, "return_pct": None,
           "cagr_pct": None, "open_lots": len(open_lots), "priced_lots": 0, "unpriced": [], "lots": [], "reason": None}
    days, avg = since_start.get("covered_days") or 0, since_start.get("avg_deployed_inr") or 0
    if since_start.get("net_pnl_inr") is None or days <= 0:
        out["reason"] = since_start.get("reason") or "no Kotak fill ledger yet"
        return out
    ug = uc = 0.0
    for o in open_lots:
        px = price_by_symbol.get(o["symbol"])
        try:
            px = float(px) if px is not None else None
        except (TypeError, ValueError):
            px = None
        if not px or px <= 0 or not o.get("entry_px"):
            out["unpriced"].append(o["symbol"])
            continue
        q, epx, long_ = o["qty"], o["entry_px"], o["side"] != "short"
        buy_v, sell_v = (epx if long_ else px) * q, (px if long_ else epx) * q
        ch = float(charges_fn(o.get("seg"), o["symbol"], o.get("prod"), buy_v, sell_v)) if charges_fn else 0.0
        ug += sell_v - buy_v
        uc += ch
        out["priced_lots"] += 1
        out["lots"].append({"symbol": o["symbol"], "side": o["side"], "qty": q, "entry_px": round(epx, 2),
                            "ltp": round(px, 2), "unrealised_net_inr": round(sell_v - buy_v - ch, 2)})
    total = since_start["net_pnl_inr"] + ug - uc
    out.update(unrealised_gross_inr=round(ug, 2), unrealised_charges_inr=round(uc, 2), unrealised_net_inr=round(ug - uc, 2),
               total_net_inr=round(total, 2))
    notes = []
    if avg > 0:
        r = total / avg
        out["return_pct"] = round(r * 100, 3)
        if 1 + r > 0:
            out["cagr_pct"] = round(((1 + r) ** (365.0 / days) - 1) * 100, 2)
        else:
            notes.append("CAGR undefined: loss larger than the average deployed capital")
    if out["unpriced"]:
        notes.append(f"{len(out['unpriced'])} open lot(s) had no live price or entry price and are left out")
    if days < MIN_ANNUALISE_DAYS:
        notes.append(f"annualised from only {days} days; swings widely until {MIN_ANNUALISE_DAYS} days")
    out["reason"] = "; ".join(notes) or None
    return out
