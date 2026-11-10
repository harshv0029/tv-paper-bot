"""B-1537 live probe (run on Actions; session network blocks news hosts): which candidate feeds are alive and
fresh, and what news_signals says right now. Writes docs/news_probe.json (small summary, no full headlines dump)."""
import json, os, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import news_signals as ns

G = lambda q: ns.GOOGLE_NEWS_RSS.format(q=urllib.parse.quote_plus(q))
CANDIDATES = [
    ("mc_marketreports", "https://www.moneycontrol.com/rss/marketreports.xml"),
    ("mc_buzzingstocks", "https://www.moneycontrol.com/rss/buzzingstocks.xml"),
    ("mc_business", "https://www.moneycontrol.com/rss/business.xml"),
    ("mc_latestnews", "https://www.moneycontrol.com/rss/latestnews.xml"),
    ("mc_results", "https://www.moneycontrol.com/rss/results.xml"),
    ("et_markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("et_stocks", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
    ("mint_markets", "https://www.livemint.com/rss/markets"),
    ("mint_companies", "https://www.livemint.com/rss/companies"),
    ("bs_markets", "https://www.business-standard.com/rss/markets-106.rss"),
    ("cnbctv18_market", "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml"),
    ("ndtvprofit", "https://feeds.feedburner.com/ndtvprofit-latest"),
    ("gn_site_moneycontrol_markets", G("site:moneycontrol.com (nifty OR sensex OR stocks OR shares) when:1d")),
    ("gn_site_moneycontrol_sector", G("site:moneycontrol.com (banks OR pharma OR IT OR auto OR metal OR realty OR FMCG) stocks when:1d")),
    ("gn_india_markets", G("(nifty OR sensex) stock market when:1d")),
]
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
NAMES = {"RELIANCE.NS": "Reliance Industries", "HDFCBANK.NS": "HDFC Bank", "IRCTC.NS": "IRCTC", "YESBANK.NS": "Yes Bank",
         "SAIL.NS": "SAIL", "RECLTD.NS": "REC Ltd", "ZYDUSLIFE.NS": "Zydus Lifesciences", "TCS.NS": "TCS"}
for sym, nm in NAMES.items():
    row = {}
    for label, cname in (("ticker_query", None), ("name_query", nm)):
        items = ns.parse_rss(ns._fetch(G(ns.stock_query(sym, cname))), "google-news")
        agg = ns.aggregate(items, now)
        ev = ns.entry_verdict(sym, "long", stock=agg, ms=ms)
        row[label] = {"items": len(items), "n_48h": agg["n"], "score": agg["score"], "hard_neg": [h[0] for h in agg["hard_neg"]],
                      "hard_pos": [h[0] for h in agg["hard_pos"]], "entry_long": ev["action"], "reason": ev["reason"][:140],
                      "exit_long": ns.exit_verdict(sym, "long", stock=agg)["action"],
                      "entry_short": ns.entry_verdict(sym, "short", stock=agg, ms=ms)["action"],
                      "top": [t["title"][:100] for t in agg["top"][:3]]}
    out["stocks"][sym] = row
p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "news_probe.json")
json.dump(out, open(p, "w"), indent=1)
print(json.dumps(out, indent=1))
