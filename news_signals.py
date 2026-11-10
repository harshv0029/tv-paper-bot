"""B-1537: news add-on - market, sector and stock headline scores as an ADVISORY input for entry and exit.

Sources (RSS, no login, no API key): Moneycontrol, Economic Times Markets, Mint Markets for market/sector
headlines; Google News RSS (India edition) per stock, where Moneycontrol/ET/Mint/Business Standard/Reuters
items weigh 1.0 and every other publisher 0.6.

What it computes: each headline gets a lexicon score in [-1, 1] plus HARD event flags (fraud, SEBI action,
default, downgrade ... / order win, upgrade, buyback ...). Headlines are aggregated per scope (market, sector,
stock) with a 12-hour half-life recency decay and shrinkage, so a single headline can never read as +/-1.

SHADOW ONLY. entry_verdict()/exit_verdict() return what the add-on WOULD do; nothing in main.py's order paths
calls them. A rule that decides real-money entries or exits ships only after the user confirms it (CLAUDE.md
2026-11-06). Fail-open everywhere: no data, a blocked feed or a parse error returns "allow"/"hold".

State: the cache is a pure re-fetchable cache (in memory only, nothing to mirror to Upstash).
"""
import email.utils
import json
import os
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET

import requests

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"


def _gn(query: str) -> str:
    return GOOGLE_NEWS_RSS.format(q=urllib.parse.quote_plus(query))


# Live probe 2026-11-10 09:45 IST (docs/news_probe.json): Moneycontrol's own RSS files return HTTP 200 but are frozen
# at Apr 2024, so Moneycontrol headlines are read through Google News site:moneycontrol.com (100 fresh items each).
MARKET_FEEDS = (
    ("moneycontrol", _gn("site:moneycontrol.com (nifty OR sensex OR stocks OR shares) when:1d")),
    ("moneycontrol", _gn("site:moneycontrol.com (banks OR pharma OR IT OR auto OR metal OR realty OR FMCG) stocks when:1d")),
    ("economictimes", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("economictimes", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
    ("livemint", "https://www.livemint.com/rss/markets"),
    ("livemint", "https://www.livemint.com/rss/companies"),
    ("business-standard", "https://www.business-standard.com/rss/markets-106.rss"),
    ("cnbctv18", "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml"),
    ("ndtv profit", "https://feeds.feedburner.com/ndtvprofit-latest"),
)
TRUSTED_PUBLISHERS = ("moneycontrol", "economictimes", "economic times", "livemint", "mint",
                      "business-standard", "business standard", "reuters", "cnbctv18", "cnbc tv18", "ndtv profit")
_PUBLISHER_ALIAS = {"moneycontrol": "moneycontrol", "economictimes": "economictimes", "economic times": "economictimes",
                    "livemint": "livemint", "mint": "livemint", "business-standard": "business-standard",
                    "business standard": "business-standard", "reuters": "reuters", "cnbctv18": "cnbctv18",
                    "cnbc tv18": "cnbctv18", "ndtv profit": "ndtvprofit"}
CONFIRM_MIN_PUBLISHERS = 2   # "confirmed": the same kind of hard event from at least 2 different trusted publishers
CONFIDENT_SCORE = 0.2        # "confident": overall stock score at least this far against the trade, no opposing hard event
UNTRUSTED_WEIGHT = 0.6
HALF_LIFE_HOURS = 12.0
MAX_AGE_HOURS = 48.0
CACHE_TTL_SECONDS = 600
MAX_FEED_BYTES = 2_000_000
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

# Lexicon: phrase -> weight. Longer phrases are matched first and consumed, so "profit falls" is not also "profit".
POSITIVE = {
    "surge": 1, "surges": 1, "soar": 1, "soars": 1, "rally": 1, "rallies": 1, "jump": 1, "jumps": 1, "gain": 1,
    "gains": 1, "rise": 0.7, "rises": 0.7, "climbs": 0.7, "record high": 1.5, "all-time high": 1.5, "52-week high": 1.2,
    "upgrade": 1.5, "upgrades": 1.5, "upgraded": 1.5, "outperform": 1, "buy rating": 1.2, "target raised": 1.2,
    "raises target": 1.2, "beats estimates": 1.5, "beat estimates": 1.5, "profit rises": 1.2, "profit jumps": 1.5,
    "profit surges": 1.5, "profit up": 1, "strong results": 1.2, "order win": 1.5, "wins order": 1.5,
    "bags order": 1.5, "secures order": 1.5, "buyback": 1.2, "bonus issue": 1, "dividend": 0.5, "stake buy": 0.8,
    "approval": 0.8, "usfda nod": 1.2, "fii buying": 1, "fiis buy": 1, "rate cut": 1, "upper circuit": 1.5,
    "bullish": 1, "breakout": 0.8, "expansion": 0.5, "turnaround": 1,
}
NEGATIVE = {
    "plunge": 1, "plunges": 1, "crash": 1.5, "crashes": 1.5, "slump": 1, "slumps": 1, "tumble": 1, "tumbles": 1,
    "fall": 0.7, "falls": 0.7, "drops": 0.7, "slips": 0.7, "sinks": 1, "selloff": 1.2, "sell-off": 1.2,
    "52-week low": 1.2, "record low": 1.5, "downgrade": 1.5, "downgrades": 1.5, "downgraded": 1.5,
    "underperform": 1, "sell rating": 1.2, "target cut": 1.2, "cuts target": 1.2, "misses estimates": 1.5,
    "miss estimates": 1.5, "profit falls": 1.2, "profit drops": 1.2, "profit slumps": 1.5, "profit down": 1,
    "net loss": 1.2, "weak results": 1.2, "fraud": 2, "scam": 2, "probe": 1.2, "raid": 1.5, "raids": 1.5,
    "sebi bars": 2, "sebi ban": 2, "sebi order": 1.2, "penalty": 1, "fine": 0.6, "default": 2, "defaults": 2,
    "insolvency": 2, "bankruptcy": 2, "resigns": 1, "resignation": 1, "pledge": 1, "pledged": 1, "lawsuit": 1,
    "recall": 1, "usfda warning": 1.5, "warning letter": 1.5, "fii selling": 1, "fiis sell": 1, "rate hike": 1,
    "lower circuit": 1.5, "bearish": 1, "layoffs": 0.8, "block deal sale": 0.8, "stake sale": 0.6, "war": 1,
    "tariff": 0.8, "tariffs": 0.8,
}
HARD_NEGATIVE = ("fraud", "scam", "sebi bars", "sebi ban", "default", "defaults", "insolvency", "bankruptcy",
                 "raid", "raids", "downgrade", "downgrades", "downgraded", "usfda warning", "warning letter",
                 "lower circuit", "misses estimates", "miss estimates")
HARD_POSITIVE = ("upgrade", "upgrades", "upgraded", "order win", "wins order", "bags order", "secures order",
                 "buyback", "beats estimates", "beat estimates", "upper circuit", "usfda nod")

# Headline keyword -> docs/sector_map.json sector name (yfinance sectors).
SECTOR_KEYWORDS = {
    "Financial Services": ("bank", "banks", "banking", "nbfc", "nbfcs", "lender", "lenders", "insurer", "insurers",
                           "insurance", "rbi", "psu bank", "psu banks", "bank nifty", "financials"),
    "Technology": ("it stocks", "it sector", "it firms", "software", "tech stocks", "nifty it", "it services"),
    "Healthcare": ("pharma", "pharmaceutical", "drugmaker", "drugmakers", "hospital", "hospitals", "healthcare",
                   "usfda"),
    "Consumer Cyclical": ("auto", "autos", "automobile", "automaker", "automakers", "two-wheeler", "ev makers",
                          "retail", "retailers", "hotel", "hotels", "nifty auto"),
    "Consumer Defensive": ("fmcg", "consumer staples", "nifty fmcg"),
    "Basic Materials": ("metal", "metals", "steel", "cement", "chemical", "chemicals", "aluminium", "copper",
                        "nifty metal", "mining"),
    "Energy": ("oil", "crude", "refiner", "refiners", "omc", "omcs", "gas", "coal", "energy stocks"),
    "Industrials": ("infra", "infrastructure", "capital goods", "defence", "defense", "railway", "railways",
                    "engineering", "shipbuilder", "shipbuilders", "logistics"),
    "Utilities": ("power", "utilities", "discom", "discoms", "renewable", "renewables"),
    "Real Estate": ("realty", "real estate", "developer", "developers", "housing"),
    "Communication Services": ("telecom", "telco", "telcos", "media", "5g"),
}
MARKET_KEYWORDS = ("nifty", "sensex", "market", "markets", "d-street", "dalal street", "fii", "fiis", "dii",
                   "diis", "rupee", "gift nifty", "indices", "equities", "stocks")

_WORD = r"(?<![a-z0-9]){}(?![a-z0-9])"


def _compile(d):
    return [(re.compile(_WORD.format(re.escape(k))), k, w) for k, w in sorted(d.items(), key=lambda kv: -len(kv[0]))]


_POS, _NEG = _compile(POSITIVE), _compile(NEGATIVE)
_SECTOR_RE = {s: re.compile("|".join(_WORD.format(re.escape(k)) for k in sorted(ks, key=len, reverse=True)))
              for s, ks in SECTOR_KEYWORDS.items()}
_FOREIGN_RE = re.compile(r"(?<![a-z])(wall street|nasdaq|dow jones|s&p 500|asian (?:stocks|markets|shares)|european|us stocks|kospi|nikkei|hang seng)(?![a-z])")
_MARKET_RE = re.compile("|".join(_WORD.format(re.escape(k)) for k in sorted(MARKET_KEYWORDS, key=len, reverse=True)))


def score_headline(title: str) -> dict:
    """Lexicon score of one headline: {"score": -1..1, "hard_neg": [...], "hard_pos": [...], "hits": n}."""
    t = " " + re.sub(r"\s+", " ", (title or "").lower()) + " "
    hits = []  # (phrase, signed weight)
    for rx_list, sign in ((_NEG, -1.0), (_POS, 1.0)):
        for rx, phrase, w in rx_list:
            if rx.search(t):
                hits.append((phrase, sign * w))
                t = rx.sub(" _ ", t)  # consume, so a shorter phrase inside it is not counted again
    pos = sum(w for _, w in hits if w > 0)
    neg = -sum(w for _, w in hits if w < 0)
    score = (pos - neg) / (pos + neg) if (pos + neg) > 0 else 0.0
    return {"score": round(score, 3), "hits": len(hits),
            "hard_neg": [p for p, w in hits if w < 0 and p in HARD_NEGATIVE],
            "hard_pos": [p for p, w in hits if w > 0 and p in HARD_POSITIVE]}


def parse_rss(xml_text: str, default_source: str = "") -> list:
    """RSS 2.0 -> [{"title", "ts" (epoch seconds or None), "source", "link"}]. Bad or hostile XML -> []."""
    if not xml_text or "<!ENTITY" in xml_text or len(xml_text) > MAX_FEED_BYTES:
        return []
    try:
        root = ET.fromstring(xml_text.strip())
    except Exception:
        return []
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        ts = None
        try:
            ts = email.utils.parsedate_to_datetime((it.findtext("pubDate") or "").strip()).timestamp()
        except Exception:
            pass
        src = it.find("source")
        source = ((src.text or "") + " " + (src.get("url") or "")).strip() if src is not None else default_source
        out.append({"title": title, "ts": ts, "source": source or default_source, "link": (it.findtext("link") or "").strip()})
    return out


def _source_weight(source: str) -> float:
    s = (source or "").lower()
    return 1.0 if any(p in s for p in TRUSTED_PUBLISHERS) else UNTRUSTED_WEIGHT


def publisher_of(source: str):
    """Canonical trusted publisher name for a source string, or None for an untrusted one."""
    s = (source or "").lower()
    return next((v for k, v in _PUBLISHER_ALIAS.items() if k in s), None)


def confirmation(stock: dict, direction: str) -> dict:
    """Is the stock news against a trade in `direction` CONFIRMED (>= CONFIRM_MIN_PUBLISHERS different trusted
    publishers report a hard event against it) and CONFIDENT (score at least CONFIDENT_SCORE against it and no hard
    event in the trade's favour)? Only actionable=True may ever change a real order."""
    short = direction == "short"
    against = (stock.get("hard_pos") if short else stock.get("hard_neg")) or []
    favour = (stock.get("hard_neg") if short else stock.get("hard_pos")) or []
    pubs = sorted({h[2] for h in against if len(h) > 2 and h[2]})
    confirmed = len(pubs) >= CONFIRM_MIN_PUBLISHERS
    confident = bool(against) and not favour and (1.0 if short else -1.0) * float(stock.get("score") or 0) >= CONFIDENT_SCORE
    return {"confirmed": confirmed, "confident": confident, "actionable": confirmed and confident, "publishers": pubs,
            "event": against[0][0] if against else None, "headline": against[0][1] if against else None}


def aggregate(items: list, now: float = None) -> dict:
    """Recency-weighted score over headlines. Undated items count as 6h old; items older than MAX_AGE_HOURS drop.
    Shrinkage (+1 in the denominator) keeps one lone headline from reading as +/-1."""
    now = time.time() if now is None else now
    num = den = 0.0
    n = 0
    hard_neg, hard_pos, top = [], [], []
    for it in items:
        age_h = 6.0 if it.get("ts") is None else max(0.0, (now - it["ts"]) / 3600.0)
        if age_h > MAX_AGE_HOURS:
            continue
        sc = score_headline(it["title"])
        w = _source_weight(it.get("source")) * 0.5 ** (age_h / HALF_LIFE_HOURS)
        n += 1
        num += w * sc["score"]
        den += w
        if sc["hits"]:
            top.append((abs(w * sc["score"]), {"title": it["title"], "score": sc["score"], "age_h": round(age_h, 1),
                                              "source": (it.get("source") or "")[:40]}))
        if _source_weight(it.get("source")) >= 1.0:  # a hard event counts only from a trusted publisher
            pub = publisher_of(it.get("source"))
            hard_neg += [(p, it["title"], pub) for p in sc["hard_neg"]]
            hard_pos += [(p, it["title"], pub) for p in sc["hard_pos"]]
    top.sort(key=lambda x: -x[0])
    return {"score": round(num / (den + 1.0), 3) if n else 0.0, "n": n,
            "hard_neg": hard_neg[:12], "hard_pos": hard_pos[:12], "top": [t for _, t in top[:5]]}


_cache: dict = {}
_lock = threading.Lock()


def _fetch(url: str) -> str:
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=10, stream=True)
        if r.status_code != 200:
            return ""
        return r.raw.read(MAX_FEED_BYTES + 1, decode_content=True).decode(r.encoding or "utf-8", "replace")
    except Exception:
        return ""


def _cached(key, loader):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    val = loader()
    with _lock:
        _cache[key] = (now, val)
    return val


def market_items() -> list:
    def load():
        seen, out = set(), []
        for src, url in MARKET_FEEDS:
            for it in parse_rss(_fetch(url), src):
                k = it["title"].lower()
                if k not in seen:
                    seen.add(k)
                    out.append(it)
        return out
    return _cached("market", load)


_names_cache = None
_NAME_NOISE = re.compile(r"\b(limited|ltd\.?|the|company|co\.?|corporation|corp\.?|\(india\)|india|industries|enterprises|holdings)\b", re.I)


def company_name(symbol: str):
    """Short company name from docs/company_names.json (NSE EQUITY_L.csv, built by scripts/build_company_names.py);
    None when the file or the symbol is missing (the ticker alone is then used)."""
    global _names_cache
    if _names_cache is None:
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "company_names.json")) as fh:
                _names_cache = json.load(fh).get("names", {})
        except Exception:
            _names_cache = {}
    raw = _names_cache.get(symbol)
    if not raw:
        return None
    short = re.sub(r"\s+", " ", _NAME_NOISE.sub(" ", raw)).strip(" .,&-")
    return short or raw


def stock_query(symbol: str, name: str = None) -> str:
    base = symbol.split(".")[0]
    who = f'("{name}" OR "{base}")' if name and name.lower() != base.lower() else f'"{base}"'
    return f"{who} (share OR stock OR shares) when:2d"


def is_relevant(title: str, symbol: str, name: str = None) -> bool:
    """A stock headline counts only if it names the stock: the ticker as a whole word, or the short company name."""
    t = " " + (title or "").lower() + " "
    keys = [symbol.split(".")[0].lower()] + ([name.lower()] if name else [])
    return any(re.search(_WORD.format(re.escape(k)), t) for k in keys if len(k) >= 3)


def stock_items(symbol: str, name: str = None) -> list:
    name = name or company_name(symbol)

    def load():
        return [it for it in parse_rss(_fetch(_gn(stock_query(symbol, name))), "google-news") if is_relevant(it["title"], symbol, name)]
    return _cached(("stock", symbol), load)


def market_and_sector_scores(items: list = None, now: float = None) -> dict:
    items = market_items() if items is None else items
    mk = [it for it in items if _MARKET_RE.search(" " + it["title"].lower() + " ")]
    sectors = {}
    for sec, rx in _SECTOR_RE.items():
        sub = [it for it in items if rx.search(" " + it["title"].lower() + " ")
               and not _FOREIGN_RE.search(it["title"].lower())]  # overseas headlines never score an Indian sector
        if sub:
            sectors[sec] = aggregate(sub, now)
    return {"market": aggregate(mk, now), "sectors": sectors, "headlines": len(items)}


STOCK_AVOID_SCORE = 0.5   # |stock score| at or beyond this, against the trade direction, with >= 2 headlines
STOCK_AVOID_MIN_N = 2


def entry_verdict(symbol: str, direction: str, sector: str = None, stock: dict = None, ms: dict = None) -> dict:
    """SHADOW verdict for a NEW entry. action: "allow" | "avoid" (stock-level news against the direction) |
    "caution" (sector or market against it; never an avoid on its own). No data -> "allow"."""
    try:
        stock = aggregate(stock_items(symbol)) if stock is None else stock
        ms = market_and_sector_scores() if ms is None else ms
    except Exception as e:
        return {"action": "allow", "reason": f"news unavailable ({e}); fail-open"}
    sign = -1.0 if direction == "short" else 1.0
    against = stock["hard_neg"] if sign > 0 else stock["hard_pos"]
    sec = (ms.get("sectors") or {}).get(sector) if sector else None
    out = {"action": "allow", "reason": "no adverse news", "stock": stock, "sector": sec, "market": ms.get("market")}
    if against:
        out.update(action="avoid", reason=f"hard {'negative' if sign > 0 else 'positive'} stock news: {against[0][0]!r} - {against[0][1][:90]}")
    elif stock["n"] >= STOCK_AVOID_MIN_N and sign * stock["score"] <= -STOCK_AVOID_SCORE:
        out.update(action="avoid", reason=f"stock news score {stock['score']} over {stock['n']} headlines is against a {direction}")
    elif sec and sec["n"] >= 3 and sign * sec["score"] <= -0.4:
        out.update(action="caution", reason=f"sector {sector!r} news score {sec['score']} over {sec['n']} headlines")
    elif out["market"] and out["market"]["n"] >= 5 and sign * out["market"]["score"] <= -0.4:
        out.update(action="caution", reason=f"market news score {out['market']['score']} over {out['market']['n']} headlines")
    return out


def exit_verdict(symbol: str, direction: str, stock: dict = None) -> dict:
    """SHADOW verdict for an OPEN position. action: "hold" | "tighten" (hard adverse stock event: raise the
    stop / book profit sooner). Never loosens a stop and never exits by itself. No data -> "hold"."""
    try:
        stock = aggregate(stock_items(symbol)) if stock is None else stock
    except Exception as e:
        return {"action": "hold", "reason": f"news unavailable ({e}); fail-open"}
    against = stock["hard_pos"] if direction == "short" else stock["hard_neg"]
    if against:
        return {"action": "tighten", "reason": f"hard adverse stock news: {against[0][0]!r} - {against[0][1][:90]}", "stock": stock}
    return {"action": "hold", "reason": "no hard adverse news", "stock": stock}


if __name__ == "__main__":  # live probe: python3 news_signals.py RELIANCE.NS TCS.NS
    import json
    import sys
    for src, url in MARKET_FEEDS:
        print(f"feed {src:14s} items={len(parse_rss(_fetch(url), src)):3d} {url}")
    ms_ = market_and_sector_scores()
    print(json.dumps({"market": ms_["market"], "sectors": {k: (v["score"], v["n"]) for k, v in ms_["sectors"].items()}}, indent=1))
    for sym in sys.argv[1:]:
        print(sym, json.dumps(entry_verdict(sym, "long", ms=ms_), indent=1)[:1500])
