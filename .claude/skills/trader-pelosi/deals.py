#!/usr/bin/env python3
"""India "smart money" tracker (tv-paper-bot port of trader-pelosi, B-1345).

US Congress PTRs have no Indian equivalent. The closest public, timely signals of who is buying
and selling Indian stocks are:
  - NSE bulk deals  (a single client trading >= 0.5% of a company's shares in a day)
  - NSE block deals (>= Rs 10 crore negotiated trades in the block window)
  - SEBI PIT insider disclosures (promoters, directors, KMP trading their own company's shares)

Read-only, best effort: nseindia.com needs the cookie its home page sets and may throttle or block
some IPs; a failure is printed as a note, never a crash. It never trades and never places an order.

  python3 deals.py check                         # new bulk/block deals + last 7 days of insider trades
  python3 deals.py check --tickers RELIANCE TCS  # flag rows in these stocks
  python3 deals.py check --days 30 --json
  python3 deals.py check --offline DIR           # DIR/largedeal.json and DIR/pit.json, no network
  python3 deals.py check --week                  # this IST week's bulk/block deals (historical endpoints)
  python3 deals.py check --from 2026-10-01 --to 2026-10-23   # any date range (offline: hist_bulk/hist_block.json)
"""
import argparse
import datetime as _dt
import hashlib
import json
import os
import sys

NSE_HOME = "https://www.nseindia.com/"
LARGE_DEALS = "https://www.nseindia.com/api/snapshot-capital-market-largedeal"
HIST = "https://www.nseindia.com/api/historical/%s-deals?from=%s&to=%s"
PIT = "https://www.nseindia.com/api/corporates-pit?index=equities&from_date=%s&to_date=%s"
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))


class DealsError(Exception):
    pass


_OPENER = []


def nse_json(url, name, offline=None):
    if offline:
        path = os.path.join(offline, name)
        if not os.path.isfile(path):
            raise DealsError("offline: no file %s" % path)
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    import http.cookiejar
    import urllib.request
    try:
        if not _OPENER:
            op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            op.addheaders = [("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
                             ("Accept", "application/json,*/*;q=0.8"), ("Accept-Language", "en-IN,en;q=0.9"),
                             ("Referer", NSE_HOME)]
            op.open(NSE_HOME, timeout=20).read()
            _OPENER.append(op)
        with _OPENER[0].open(url, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise DealsError("NSE %s unavailable: %s" % (url.split("?")[0], exc))


def _f(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _rid(*parts):
    # upper-cased so "22-Oct-2026" (snapshot) and "22-OCT-2026" (historical) dedupe to one id
    return hashlib.sha1("|".join(str(p).strip().upper() for p in parts).encode("utf-8")).hexdigest()[:16]


def parse_large_deals(doc):
    """snapshot-capital-market-largedeal -> rows (bulk and block)."""
    out = []
    for kind, key in (("bulk", "BULK_DEALS_DATA"), ("block", "BLOCK_DEALS_DATA")):
        for r in (doc or {}).get(key) or []:
            qty, px = _f(r.get("qty")), _f(r.get("watp"))
            side = str(r.get("buySell") or "").upper()
            out.append({"id": _rid(kind, r.get("date"), r.get("symbol"), r.get("clientName"), side, r.get("qty")),
                        "kind": kind, "date": r.get("date"), "symbol": str(r.get("symbol") or "").upper(),
                        "company": r.get("name"), "who": r.get("clientName"), "role": "client",
                        "side": "buy" if side.startswith("B") else "sell" if side.startswith("S") else side.lower(),
                        "qty": qty, "price": px,
                        "value_cr": round(qty * px / 1e7, 2) if qty and px else None})
    return out


def _g(r, *keys):
    for k in keys:
        if r.get(k) not in (None, ""):
            return r.get(k)
    return None


def parse_hist_deals(doc, kind):
    """api/historical/{bulk,block}-deals -> rows in the parse_large_deals shape (same id scheme)."""
    rows = doc.get("data") if isinstance(doc, dict) else doc
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        d, sym = _g(r, "BD_DT_DATE", "date", "mTd"), _g(r, "BD_SYMBOL", "symbol")
        who, rq = _g(r, "BD_CLIENT_NAME", "clientName", "client"), _g(r, "BD_QTY_TRD", "qty", "quantity")
        qty, px = _f(rq), _f(_g(r, "BD_TP_WATP", "watp", "price"))
        side = str(_g(r, "BD_BUY_SELL", "buySell", "buy_sell") or "").upper()
        out.append({"id": _rid(kind, d, sym, who, side, rq), "kind": kind, "date": d,
                    "symbol": str(sym or "").upper(), "company": _g(r, "BD_SCRIP_NAME", "name", "scripName"),
                    "who": who, "role": "client",
                    "side": "buy" if side.startswith("B") else "sell" if side.startswith("S") else side.lower(),
                    "qty": qty, "price": px, "value_cr": round(qty * px / 1e7, 2) if qty and px else None,
                    "remarks": _g(r, "BD_REMARKS", "remarks")})
    return out


def _day(s):
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y"):
        try:
            return _dt.datetime.strptime(str(s).strip().title(), fmt).date()
        except ValueError:
            pass
    return _dt.date.min


def date_range(args, today):
    """(from, to) dates for --week / --from/--to, else None (snapshot mode)."""
    if args.week:
        return today - _dt.timedelta(days=today.weekday()), today
    if args.frm or args.to:
        to = _dt.date.fromisoformat(args.to) if args.to else today
        frm = _dt.date.fromisoformat(args.frm) if args.frm else to - _dt.timedelta(days=to.weekday())
        if frm > to:
            raise DealsError("--from %s is after --to %s" % (frm, to))
        return frm, to
    return None


def parse_pit(doc):
    """corporates-pit -> insider rows (promoter / director / KMP trades in their own company)."""
    rows = doc.get("data") if isinstance(doc, dict) else doc
    out = []
    for r in rows or []:
        t = str(r.get("tdpTransactionType") or r.get("acqMode") or "").lower()
        side = "buy" if ("buy" in t or "acqui" in t) else "sell" if ("sell" in t or "dispos" in t) else t
        out.append({"id": _rid("pit", r.get("symbol"), r.get("acqName"), r.get("date"), r.get("secAcq"), t),
                    "kind": "insider", "date": r.get("date") or r.get("acqfromDt"),
                    "symbol": str(r.get("symbol") or "").upper(), "company": r.get("company"),
                    "who": r.get("acqName"), "role": r.get("personCategory"), "side": side,
                    "qty": _f(r.get("secAcq")), "price": None,
                    "value_cr": round(_f(r.get("secVal")) / 1e7, 2) if _f(r.get("secVal")) else None,
                    "mode": r.get("acqMode")})
    return out


def load_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"seen": {}}


def save_state(path, state, today, keep_days=60):
    cutoff = (today - _dt.timedelta(days=keep_days)).isoformat()
    state["seen"] = {k: v for k, v in state.get("seen", {}).items() if v >= cutoff}
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")


def watch_symbols(args):
    syms = {t.upper().replace(".NS", "").replace(".BO", "") for t in (args.tickers or [])}
    for path in (args.portfolio, args.watchlist):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        items = doc.get("positions") or doc.get("hits") or doc.get("symbols") or [] if isinstance(doc, dict) else doc
        for it in items:
            s = it.get("symbol") if isinstance(it, dict) else it
            if s:
                syms.add(str(s).upper().replace(".NS", "").replace(".BO", ""))
    return syms


def describe(r):
    val = (" Rs %.2f cr" % r["value_cr"]) if r.get("value_cr") else ""
    px = (" @ Rs %.2f" % r["price"]) if r.get("price") else ""
    qty = (" %s sh" % "{:,.0f}".format(r["qty"])) if r.get("qty") else ""
    role = (" (%s)" % r["role"]) if r.get("role") and r["role"] != "client" else ""
    return "%-7s %-11s %-12s %-4s %s%s%s%s  by %s%s" % (
        r["kind"], r.get("date") or "-", r["symbol"], r["side"], qty, px, val, "", r.get("who") or "-", role)


def cmd_check(args):
    today = _dt.datetime.now(IST).date() if not args.today else _dt.date.fromisoformat(args.today)
    notes, rows = [], []
    try:
        rng = date_range(args, today)
    except (DealsError, ValueError) as e:
        notes.append(str(e))
        rng = None
    if rng:
        f, t = rng[0].strftime("%d-%m-%Y"), rng[1].strftime("%d-%m-%Y")
        for kind in ("bulk", "block"):
            try:
                rows += parse_hist_deals(nse_json(HIST % (kind, f, t), "hist_%s.json" % kind, args.offline), kind)
            except DealsError as e:
                notes.append(str(e))
    else:
        try:
            rows += parse_large_deals(nse_json(LARGE_DEALS, "largedeal.json", args.offline))
        except DealsError as e:
            notes.append(str(e))
    if not args.no_insider:
        frm = (today - _dt.timedelta(days=args.days)).strftime("%d-%m-%Y")
        try:
            rows += parse_pit(nse_json(PIT % (frm, today.strftime("%d-%m-%Y")), "pit.json", args.offline))
        except DealsError as e:
            notes.append(str(e))
    state = load_state(args.state)
    seen = state.setdefault("seen", {})
    watch = watch_symbols(args)
    new = [r for r in rows if args.all or rng or r["id"] not in seen]
    for r in new:
        r["watched"] = r["symbol"] in watch
    if rng:
        new.sort(key=lambda r: (_day(r.get("date")), r.get("value_cr") or 0), reverse=True)
    else:
        new.sort(key=lambda r: (not r["watched"], r["kind"] != "insider", -(r.get("value_cr") or 0)))
    span = ("%s..%s" % (rng[0].isoformat(), rng[1].isoformat())) if rng else None
    if args.json:
        out = {"date_ist": today.isoformat(), "new": new[:args.limit], "notes": notes}
        if span:
            out["range"] = span
        print(json.dumps(out, indent=2))
    else:
        print("NSE bulk/block deals + insider (PIT) trades, %s IST: %d %s%s." % (
            today.isoformat(), len(new), ("in " + span) if span else "new",
            (", %d in your stocks" % sum(r["watched"] for r in new)) if watch else ""))
        for r in new[:args.limit]:
            print(("* " if r["watched"] else "  ") + describe(r))
        for n in notes:
            print("note: " + n)
        print("Read-only signal. A bulk/insider buy is context, not an entry: every trade still needs the bot's "
              "own PFnet-gated setup and a stop-loss.")
    if not args.dry_run:
        for r in rows:
            seen.setdefault(r["id"], today.isoformat())
        save_state(args.state, state, today)
    return 0 if new else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check")
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--watchlist", default="trader/watchlist.json")
    p.add_argument("--days", type=int, default=7, help="insider window (days)")
    p.add_argument("--no-insider", action="store_true")
    p.add_argument("--all", action="store_true", help="show already-seen rows too")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--state", default="trader/state/deals.json")
    p.add_argument("--week", action="store_true", help="Monday of this IST week..today (implies --all)")
    p.add_argument("--from", dest="frm", metavar="YYYY-MM-DD", help="range start (historical endpoints)")
    p.add_argument("--to", metavar="YYYY-MM-DD", help="range end (default today)")
    p.add_argument("--today", help="YYYY-MM-DD (IST), for reproducible runs")
    p.add_argument("--offline", metavar="DIR")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
