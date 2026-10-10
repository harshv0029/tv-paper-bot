"""B-337: build docs/sector_map.json (symbol -> sector/industry) for the full NSE
universe, from yfinance Ticker.info. Unmapped symbols are listed, never guessed."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "sector_map.json")


def _one(sym):
    import yfinance as yf
    for attempt in range(5):
        try:
            info = yf.Ticker(sym).info or {}
            if info.get("sector"):
                return sym, {"sector": info.get("sector"), "industry": info.get("industry")}
            if info.get("quoteType") == "ETF":
                return sym, {"sector": "ETF", "industry": info.get("category") or "ETF"}
            if info.get("quoteType") or info.get("longName"):
                return sym, None  # reached Yahoo, genuinely no sector: do not guess
        except Exception:
            pass
        time.sleep(2 * (attempt + 1))  # rate-limit backoff, then retry
    return sym, None


def main():
    import main as app
    syms = app._load_nse_universe_from_file()
    syms = [s if s.endswith(".NS") else s + ".NS" for s in syms]
    prev = {}
    if os.path.exists(OUT):
        prev = json.load(open(OUT)).get("map", {})
    todo = [s for s in syms if s not in prev]
    with ThreadPoolExecutor(max_workers=6) as ex:
        for sym, v in ex.map(_one, todo):
            if v:
                prev[sym] = v
    unmapped = [s for s in syms if s not in prev]
    sectors = {}
    for v in prev.values():
        sectors[v["sector"]] = sectors.get(v["sector"], 0) + 1
    json.dump({"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "universe_size": len(syms), "mapped": len(prev), "unmapped": unmapped,
               "sector_counts": sectors, "map": prev}, open(OUT, "w"), indent=0)
    small = {k: v for k, v in sectors.items() if v < 5}
    print(f"sectors with <5 symbols (excluded from rotation, never merged): {small}")
    print(f"mapped {len(prev)}/{len(syms)}; sectors={len(sectors)}")


if __name__ == "__main__":
    main()
