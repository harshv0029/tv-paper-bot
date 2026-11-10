"""B-1537: docs/company_names.json (symbol -> NSE "NAME OF COMPANY") from NSE's EQUITY_L.csv. Run on Actions."""
import csv, io, json, os, time
import requests
URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36"}, timeout=30)
r.raise_for_status()
rows = list(csv.DictReader(io.StringIO(r.text)))
names = {f"{(x.get('SYMBOL') or '').strip()}.NS": (x.get("NAME OF COMPANY") or "").strip() for x in rows if (x.get("SYMBOL") or "").strip()}
assert len(names) > 1500, len(names)
p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "company_names.json")
json.dump({"source": URL, "fetched_at_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "count": len(names), "names": names}, open(p, "w"), indent=0, sort_keys=True)
print(len(names), names.get("RELIANCE.NS"), names.get("YESBANK.NS"))
