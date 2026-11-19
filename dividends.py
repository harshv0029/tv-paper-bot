"""B-1635 (user 2026-11-19: "consider dividend as a part of return or profit calculations ... implement that").

Price-only P&L books the ex-date price drop of a held long as a loss but never adds back the dividend, so swing/CNC
returns were understated. This module credits dividends to long lots held across an ex-date.

Entitlement (NSE, T+1 rolling settlement, ex-date == record date): a long is entitled when it was BOUGHT before the
ex-date (entry day < ex-date) and still held at the start of the ex-date (exit day >= ex-date; selling ON the ex-date
keeps the dividend). Intraday (same-day) lots can never qualify. Shorts: NSE cash shorts are intraday-only and futures
pay no dividend (NSE adjusts the contract only for an extraordinary dividend), so shorts get no adjustment.

TDS: a resident individual's dividends from one company above Rs 5,000 in a financial year carry 10% TDS (Sec 194).
We report gross, an estimated TDS and net; the cash goes to the bank account, not the Kotak ledger, so Kotak's own
P&L never shows it. Read-only: nothing here places, sizes or exits a trade.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from collections import defaultdict, deque

TDS_RATE = 0.10
TDS_THRESHOLD_INR_PER_COMPANY_FY = 5000.0
_CACHE_TTL_SECONDS = 12 * 3600
_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()


def _to_date(x) -> dt.date:
    if isinstance(x, dt.datetime):
        return x.date()
    if isinstance(x, dt.date):
        return x
    if isinstance(x, (int, float)):
        return (dt.datetime.utcfromtimestamp(float(x)) + dt.timedelta(hours=5, minutes=30)).date()  # IST day
    return dt.date.fromisoformat(str(x)[:10])


def dividend_events(symbol: str, fetch=None) -> list:
    """[(ex_date, amount_per_share)] for a Yahoo symbol, cached 12 h. `fetch(symbol)` is injectable for tests; the
    default reads yfinance Ticker(symbol).dividends (ex-date index, INR per share for .NS). Failure -> []."""
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(symbol)
        if hit and now - hit[0] < _CACHE_TTL_SECONDS:
            return hit[1]
    try:
        if fetch is not None:
            raw = fetch(symbol)
        else:
            import yfinance as yf
            raw = yf.Ticker(symbol).dividends
        items = raw.items() if hasattr(raw, "items") else raw
        ev = sorted((_to_date(d), float(a)) for d, a in items if a and float(a) > 0)
    except Exception:  # noqa: BLE001
        ev = []
    with _CACHE_LOCK:
        _CACHE[symbol] = (now, ev)
    return ev


def lot_dividend(events, qty: float, entry_day, exit_day=None, today=None) -> list:
    """Dividends one long lot earns: [(ex_date, per_share, qty*per_share)]. exit_day None = still open (counted up to
    `today`, i.e. ex-dates already passed)."""
    if not qty or qty <= 0:
        return []
    e = _to_date(entry_day)
    x = _to_date(exit_day) if exit_day is not None else _to_date(today or dt.date.today())
    return [(d, a, round(a * qty, 2)) for d, a in events if e < d <= x]


def fifo_dividends(trades, events_of, today=None) -> dict:
    """trades: iterable of dicts {symbol, side ('B'/'S' or 'buy'/'sell'), qty, ts or day}, in time order. FIFO-matches
    sells to buys per symbol and credits each long lot for the ex-dates it was held across. Sells beyond the held qty
    open a short, and a later buy covers it first; shorts earn no dividend. events_of(symbol) -> dividend_events. Returns totals plus per-credit rows."""
    lots: dict = defaultdict(deque)  # symbol -> deque[[qty, entry_day]]
    short: dict = defaultdict(float)  # symbol -> open short qty
    credits = []

    def _credit(sym, q, entry, exit_):
        if exit_ is not None and _to_date(exit_) <= _to_date(entry):
            return  # same-day (intraday) lot: no ex-date can fall inside it, so skip the dividend lookup
        for d, a, amt in lot_dividend(events_of(sym), q, entry, exit_, today):
            credits.append({"symbol": sym, "ex_date": d.isoformat(), "per_share": a, "qty": q, "gross_inr": amt,
                            "open": exit_ is None})

    for t in trades:
        sym = t["symbol"]
        side = str(t["side"]).upper()[:1]
        q = float(t.get("qty") or 0)
        day = t.get("day") or t.get("ts")
        if q <= 0 or day is None:
            continue
        if side == "B":
            cover = min(q, short[sym])  # a buy first covers an open short; only the rest opens a long lot
            short[sym] -= cover
            if q - cover > 1e-9:
                lots[sym].append([q - cover, day])
        elif side == "S":
            while q > 1e-9 and lots[sym]:
                lot = lots[sym][0]
                take = min(q, lot[0])
                _credit(sym, take, lot[1], day)
                lot[0] -= take
                q -= take
                if lot[0] <= 1e-9:
                    lots[sym].popleft()
            short[sym] += max(0.0, q)  # selling more than held opens a short (no dividend adjustment)
    for sym, dq in lots.items():
        for q, entry in dq:
            _credit(sym, q, entry, None)
    return summarize(credits)


def _fy(d: dt.date) -> int:
    return d.year if d.month >= 4 else d.year - 1


def summarize(credits: list) -> dict:
    """Gross, estimated TDS (10% once a company's FY total passes Rs 5,000) and net, overall and per symbol."""
    per_co_fy: dict = defaultdict(float)
    for c in credits:
        per_co_fy[(c["symbol"], _fy(_to_date(c["ex_date"])))] += c["gross_inr"]
    by_sym: dict = defaultdict(lambda: {"gross_inr": 0.0, "tds_est_inr": 0.0})
    for c in credits:
        tds = c["gross_inr"] * TDS_RATE if per_co_fy[(c["symbol"], _fy(_to_date(c["ex_date"])))] > TDS_THRESHOLD_INR_PER_COMPANY_FY else 0.0
        c["tds_est_inr"] = round(tds, 2)
        by_sym[c["symbol"]]["gross_inr"] += c["gross_inr"]
        by_sym[c["symbol"]]["tds_est_inr"] += tds
    gross = round(sum(v["gross_inr"] for v in by_sym.values()), 2)
    tds = round(sum(v["tds_est_inr"] for v in by_sym.values()), 2)
    return {"gross_inr": gross, "tds_est_inr": tds, "net_inr": round(gross - tds, 2),
            "by_symbol": {s: {k: round(v, 2) for k, v in d.items()} for s, d in by_sym.items()},
            "credits": credits}


def backtest_dividend_return(events, entry_ts, exit_ts, entry_price: float) -> float:
    """Fractional return a long backtest trade earns from dividends (sum per-share / entry price) for ex-dates held
    across. For UNADJUSTED intraday bars only: yfinance daily bars are already dividend-adjusted (auto_adjust=True),
    so adding this to a 1d backtest would double count."""
    if not entry_price or entry_price <= 0:
        return 0.0
    return sum(a for d, a, _ in lot_dividend(events, 1.0, entry_ts, exit_ts)) / float(entry_price)
