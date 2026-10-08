"""Liquidity screen for NSE ETFs (B-317). Prints one JSON line per ETF plus a
final ETF_SCREEN_JSON summary. Run from GitHub Actions (Yahoo is blocked in the
dev sandbox). Candidates = every ETF-looking symbol in docs/nse_universe.json."""
import json, re, sys
import yfinance as yf

S = json.load(open("docs/nse_universe.json"))["symbols"]
PAT = re.compile(r"BEES\.NS$|ETF|IETF|GOLD|SILVER|LIQUID|CASE\.NS$|^NIFTY|SENSEX|BETA\.NS$|^N?ETF")
SKIP = {"JETFREIGHT.NS"}
cands = [s for s in S if PAT.search(s) and s not in SKIP]
rows = []
for i in range(0, len(cands), 40):
    chunk = cands[i:i + 40]
    d = yf.download(chunk, period="3mo", interval="1d", progress=False,
                    group_by="ticker", threads=True, auto_adjust=False)
    for s in chunk:
        try:
            x = d[s].dropna()
            if len(x) < 30:
                rows.append({"s": s, "n": len(x)}); continue
            turn = (x.Close * x.Volume) / 1e7
            rng = ((x.High - x.Low) / x.Close * 100)
            rows.append({"s": s, "n": len(x), "turn_cr_avg": round(float(turn.mean()), 2),
                         "turn_cr_med": round(float(turn.median()), 2),
                         "range_pct_med": round(float(rng.median()), 3),
                         "px": round(float(x.Close.iloc[-1]), 2),
                         "zero_vol_days": int((x.Volume == 0).sum())})
        except Exception as e:
            rows.append({"s": s, "err": str(e)[:60]})
ok = sorted([r for r in rows if "turn_cr_med" in r], key=lambda r: -r["turn_cr_med"])
for r in ok[:70]:
    print(json.dumps(r))
print("TOTAL cands", len(cands), "with data", len(ok), "nodata", len(rows) - len(ok))
print("med_turn>=5cr:", sum(1 for r in ok if r["turn_cr_med"] >= 5),
      " >=1cr:", sum(1 for r in ok if r["turn_cr_med"] >= 1))
print("ETF_SCREEN_JSON " + json.dumps(ok))
