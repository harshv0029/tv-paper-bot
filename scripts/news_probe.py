"""B-1537 live probe (run on Actions; session network blocks news hosts): which candidate feeds are alive and
fresh, and what news_signals says right now. Writes docs/news_probe.json (small summary, no full headlines dump)."""
import json, os, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import news_signals as ns

CANDIDATES = [(f"{n}_{i}", u) for i, (n, u) in enumerate(ns.MARKET_FEEDS)]
now = time.time()
out = {"as_of_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now)), "feeds": {}, "stocks": {}}
alive = []
for name, url in CANDIDATES:
    raw = ns._fetch(url)
    items = ns.parse_rss(raw, name)
    ages = sorted((now - i["ts"]) / 3600 for i in items if i["ts"])
    fresh = [i for i in items if i["ts"] and now - i["ts"] < 48 * 3600]
    out["feeds"][name] = {"bytes": len(raw), "items": len(items), "fresh_48h": len(fresh),
                          "newest_age_h": round(ages[0], 1) if ages else None,
                          "sample": [i["title"][:110] for i in fresh[:2]],
                          "sources": sorted({(i["source"] or "")[:25] for i in fresh})[:6]}
    alive += fresh
ms = ns.market_and_sector_scores(alive, now)
out["market"] = {k: ms["market"][k] for k in ("score", "n", "top")}
out["sectors"] = {s: {"score": v["score"], "n": v["n"], "top": [t["title"][:100] for t in v["top"][:2]]} for s, v in ms["sectors"].items()}
SYMS = ["RELIANCE.NS", "HDFCBANK.NS", "IRCTC.NS", "YESBANK.NS", "SAIL.NS", "RECLTD.NS", "ZYDUSLIFE.NS", "TCS.NS", "INFY.NS", "TATASTEEL.NS"]
for sym in SYMS:
    nm = ns.company_name(sym)
    raw_items = ns.parse_rss(ns._fetch(ns._gn(ns.stock_query(sym, nm))), "google-news")
    items = [i for i in raw_items if ns.is_relevant(i["title"], sym, nm)]
    agg = ns.aggregate(items, now)
    ev = ns.entry_verdict(sym, "long", stock=agg, ms=ms)
    out["stocks"][sym] = {"name": nm, "fetched": len(raw_items), "relevant": len(items), "n_48h": agg["n"], "score": agg["score"],
                          "hard_neg": [h[0] for h in agg["hard_neg"]], "hard_pos": [h[0] for h in agg["hard_pos"]],
                          "entry_long": ev["action"], "reason": ev["reason"][:140],
                          "exit_long": ns.exit_verdict(sym, "long", stock=agg)["action"],
                          "entry_short": ns.entry_verdict(sym, "short", stock=agg, ms=ms)["action"],
                          "top": [t["title"][:100] for t in agg["top"][:3]]}
p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "news_probe.json")
json.dump(out, open(p, "w"), indent=1)
print(json.dumps(out, indent=1))
