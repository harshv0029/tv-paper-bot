"""B-337: build docs/sector_map.json (symbol -> sector/industry) for the full NSE
universe, from yfinance Ticker.info. Unmapped symbols are listed, never guessed."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "sector_map.json")


def _one(sym):
    import yfinance as yf
    for _ in range(2):
        try:
            info = yf.Ticker(sym).info or {}
            if info.get("sector"):
                return sym, {"sector": info.get("sector"), "industry": info.get("industry")}
        except Exception:
            time.sleep(1)
    return sym, None


def main():
    import main as app
    syms = app._load_nse_universe_from_file()
    syms = [s if s.endswith(".NS") else s + ".NS" for s in syms]
    prev = {}
    if os.path.exists(OUT):
        prev = json.load(open(OUT)).get("map", {})
    todo = [s for s in syms if s not in prev]
    with ThreadPoolExecutor(max_workers=16) as ex:
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
    print(f"mapped {len(prev)}/{len(syms)}; sectors={len(sectors)}")


if __name__ == "__main__":
    main()
