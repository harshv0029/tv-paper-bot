"""Daily snapshot of the most recent SL / SL-M order per tracked-union symbol,
read from Kotak's own order book (2026-10-06, explicit user instruction:
Kotak cannot return a past day's order book, so it must be captured daily
before EOD). READ-ONLY toward Kotak. Writes docs/sl_snapshots/<IST date>.json
(re-runs the same day overwrite it, never other days). Account-style keys are
stripped (public repo). Usage: kotak_sl_snapshot.py <base_url> <token>"""
import datetime, json, os, subprocess, sys

B, TOKEN = sys.argv[1], sys.argv[2]
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
FALLBACK = ("NYKAA", "DRREDDY", "GMRAIRPORT", "INDHOTEL", "RVNL")
BAD = ("acc", "client", "ucc", "pan", "name", "mob", "email", "actid", "act_id")


def get(path):
    out = subprocess.run(["curl", "-sS", "--retry", "4", "--retry-delay", "8", "-m", "90", B + path],
                         capture_output=True, text=True).stdout
    try:
        return json.loads(out)
    except Exception:
        return {}


def rows_of(d):
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for v in d.values():
            r = rows_of(v)
            if r and isinstance(r[0], dict):
                return r
    return []


def ts(r):
    s = str(r.get("ordDtTm", "")).strip()
    for f in ("%d-%b-%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.datetime.strptime(s, f)
        except ValueError:
            pass
    return None


union = get("/tracked-union").get("rows") or []
union_syms = sorted({str(r.get("kotak_trading_symbol", "")) for r in union if r.get("kotak_trading_symbol")})
print("tracked-union rows:", len(union_syms), union_syms)
print("expected five present:", {k: any(k in s for s in union_syms) for k in FALLBACK})
orders = rows_of(get(f"/kotak-neo/order-report?token={TOKEN}"))
print("order rows:", len(orders))
if not orders:
    print("NO order rows (market closed / error) - snapshot not written"); sys.exit(1)

targets = union_syms or list(FALLBACK)
snap = {"date_ist": datetime.datetime.now(IST).strftime("%Y-%m-%d"),
        "captured_at_ist": datetime.datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        "union_source": "tracked-union" if union_syms else "fallback-list", "symbols": {}}
for t in targets:
    sl = [(i, r) for i, r in enumerate(orders)
          if (t == str(r.get("trdSym", "")) or (not union_syms and t in str(r.get("trdSym", ""))))
          and str(r.get("prcTp", "")).upper() in ("SL", "SL-M")]
    clean = lambda r: {k: v for k, v in r.items() if not any(b in k.lower() for b in BAD)}
    ent = {"sl_order_count_today": len(sl), "latest_sl": None, "selection_basis": None}
    if sl:
        if all(ts(r) for _, r in sl):
            _, best = max(sl, key=lambda x: ts(x[1])); ent["selection_basis"] = "max ordDtTm"
        else:
            _, best = sl[0]; ent["selection_basis"] = "first in Kotak list (ordDtTm unparsed)"
        ent["latest_sl"] = clean(best)
    snap["symbols"][t] = ent
    print(t, "SL/SLM orders today:", len(sl), "| latest:",
          {k: (ent["latest_sl"] or {}).get(k) for k in ("trnsTp", "prcTp", "trgPrc", "qty", "ordSt", "ordDtTm")})
os.makedirs("docs/sl_snapshots", exist_ok=True)
path = f"docs/sl_snapshots/{snap['date_ist']}.json"
json.dump(snap, open(path, "w"), indent=1, sort_keys=True)
print("wrote", path)
