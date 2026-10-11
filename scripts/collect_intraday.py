"""Intraday candle recorder (B-388): downloads 5m bars for the live NSE watchlist (n200 + ETFs) and merges them into one
gzip CSV per IST trading day at docs/intraday/5m/YYYY-MM-DD.csv.gz (cols sym,ts,o,h,l,c,v; ts = IST ISO). yfinance keeps ~60 days of 5m,
so a run every day (or any run within 60 days of a gap) builds history beyond that cap. Idempotent: merges and de-duplicates (sym,ts).
Env: PERIOD (default: 60d when no history yet, else 5d), MAXSYM. Output dir docs/intraday/5m"""
import os, sys
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DIR = os.path.join(ROOT, "docs", "intraday", "5m")
PERIOD = os.environ.get("PERIOD") or ("5d" if os.path.isdir(DIR) and os.listdir(DIR) else "60d")  # first run backfills 60d


def main_run():
    import yfinance as yf
    import main as app
    syms = sorted(set(app.SWING_WATCHLIST) | set(app.ETF_SYMBOLS))
    cap = int(os.environ.get("MAXSYM", "0") or 0)
    if cap:
        syms = syms[:cap]
    os.makedirs(DIR, exist_ok=True)
    frames = []
    for b0 in range(0, len(syms), 50):
        batch = syms[b0:b0 + 50]
        try:
            d = yf.download(batch, period=PERIOD, interval="5m", group_by="ticker", auto_adjust=False, progress=False, threads=True)
        except Exception as e:
            print("batch fail", b0, e, flush=True); continue
        for s in batch:
            try:
                df = (d[s] if len(batch) > 1 else d).dropna(subset=["Close"])[["Open", "High", "Low", "Close", "Volume"]]
            except Exception:
                continue
            if df.empty:
                continue
            idx = df.index.tz_convert("Asia/Kolkata") if df.index.tz is not None else df.index.tz_localize("Asia/Kolkata")
            f = pd.DataFrame({"sym": s, "ts": [t.strftime("%Y-%m-%dT%H:%M") for t in idx],
                              "o": df["Open"].round(4).to_numpy(), "h": df["High"].round(4).to_numpy(),
                              "l": df["Low"].round(4).to_numpy(), "c": df["Close"].round(4).to_numpy(),
                              "v": df["Volume"].astype("int64").to_numpy()})
            frames.append(f)
        print("batch", b0, len(frames), flush=True)
    if not frames:
        print("no data"); return
    allf = pd.concat(frames, ignore_index=True); allf["day"] = allf["ts"].str[:10]
    n_new = 0
    for day, g in allf.groupby("day"):
        p = os.path.join(DIR, f"{day}.csv.gz")
        g = g.drop(columns="day")
        if os.path.exists(p):
            g = pd.concat([pd.read_csv(p), g], ignore_index=True)
        g = g.drop_duplicates(["sym", "ts"], keep="last").sort_values(["sym", "ts"])
        g.to_csv(p, index=False, compression="gzip"); n_new += 1
        print(day, len(g), "rows", flush=True)
    print("days written", n_new)


if __name__ == "__main__":
    main_run()
