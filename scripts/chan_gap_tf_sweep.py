"""chan_gap candle-size sweep, SHORT and LONG (backlog B-1020). Research replay driver, wires nothing.

Signal, ranking and exit are the REAL main.py functions, never a reimplementation:
  main.chan_gap_entry_signal(daily_through_yesterday, first_bar_open, direction, atr_mult)   (entry + ATR stop)
  main.chan_gap_select_top(day_candidates, direction)                                         (per-day top-10 across ALL shards)
  main.chan_gap_exit_reason(intraday_bar, entry, stop, direction)                             (called on EVERY intraday bar)
What the candle size changes: the day is walked in INTERVAL bars (5m/15m 60d, 1h 730d, the yfinance limits; 1m is 7d only and 4h needs
a 1h resample, both flagged owed, not run). Entry = the day's first-bar open (the live open print, same as the 1d baseline). Each bar
whose END <= main.CHAN_FLATTEN_CUTOFF_MIN (15:15 IST, the main constant) is checked for the stop; no stop -> flat at the last such bar's
close. Daily history for the signal is 5y of 1d bars strictly before the trade day. Fill model: stop fills at the stop price (not
gap-aware), same as the 1d baseline; the first bar can stop out. Bar-count meaning: ATR/std/MA windows are DAILY bars at every tf;
only the stop/flatten resolution changes. Cost = main.ROUND_TRIP_COST_PCT/100 (0.8%). Universe = main._load_nse_universe_from_file()
(full, NOT main.NSE_FULL_UNIVERSE). SL on every trade (the ATR stop is always set; no atrnone cell exists).
Tags: chan_gap__{buy_on_gap__long|short_on_gap__short}__<tf>__atr<k>_top10__v1 (each cell its own tag, never pooled).

  run    env: DIRECTION long|short, INTERVAL 5m|15m|1h|1d, WINDOW_DAYS (optional, B-1602), SHARD, NSHARDS, SYMBOL_LIMIT, ATRS="1.5,2.5,4.0", SYNTHETIC=1 (smoke, NOT a result)
         -> out/chan_gap_tf_<dir>_<tf>_s<shard>.json
  merge  python3 scripts/chan_gap_tf_sweep.py merge DIR [OUT.json] -> rows[] (schema main._replay_verified_tags reads)
"""
import glob
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brk20_replay as br  # noqa: E402

PERIOD_BY_INTERVAL = {"5m": "60d", "15m": "60d", "1h": "730d", "1d": "5y"}
BAR_MIN = {"5m": 5, "15m": 15, "1h": 60, "1d": 360}  # B-1602: 1d = the day bar itself, stamped 09:15, ends 15:15 (cutoff)
NEED = 92  # CHAN_GAP_STD_WINDOW + 2 completed daily bars
LOOKBACK = 110
HOURS_PER_SESSION = 6.25
DEFAULT_ATRS = (1.5, 2.5, 4.0)
NAMES = {"long": "buy_on_gap__long", "short": "short_on_gap__short"}


def window_days():
    """B-1602: WINDOW_DAYS=N keeps only trade days in the last N calendar days (IST today), so 1d/1h cells can be
    replayed on the same 60d window as the 5m/15m cells (separates period from stop-check resolution)."""
    v = os.environ.get("WINDOW_DAYS", "").strip()
    return int(v) if v else None


def tag_for(direction, interval, mult, window=None, xd=False, raw=False, ic=False):
    k = ("%.1f" % mult).replace(".", "d")
    w = f"_w{window}d" if window else ""
    x = "_xd1530" if xd else ("_ic1530" if ic else "")
    r = "_rawd" if raw else ""
    return f"chan_gap__{NAMES[direction]}__{interval}__atr{k}_top10{w}{r}{x}__v1"


def raw_daily():
    """B-1604: RAW_DAILY=1 fetches daily AND intraday bars with auto_adjust=False (unadjusted exchange prices).
    data_fetch.fetch_ohlc uses yfinance's default auto_adjust=True, which back-adjusts DAILY bars for dividends but
    leaves Yahoo intraday bars unadjusted, so over a 730d window the daily history (gap filter, 15:30 close) sits
    below the intraday open the replay enters at. Tags get _rawd so the adjusted runs stay distinct rows."""
    return os.environ.get("RAW_DAILY", "").strip() == "1"


def fetch_raw(symbol, period, interval):
    """Unadjusted OHLC, same frame shape as data_fetch.fetch_ohlc (Date column, flat columns, NaN rows dropped)."""
    import yfinance as yf
    df = yf.download(symbol, period=period, interval=interval, progress=False, threads=False, auto_adjust=False)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df = df.rename(columns={("Date" if "Date" in df.columns else "Datetime"): "Date"}).drop(columns=["Adj Close"], errors="ignore")
    return df.dropna(subset=["Open", "High", "Low", "Close"]).reset_index(drop=True)


def paired_daily_close():
    """B-1604: PAIRED_DAILY_CLOSE=1 (intraday intervals only) also books every candidate at that day's DAILY close (the
    15:30 bar the 1d replay uses) when the intraday stop did not fire by 15:15. Same candidates, same entry, same stop
    walk: the only difference between the plain tag and its _xd1530 twin is the exit time (15:15 live vs 15:30)."""
    return os.environ.get("PAIRED_DAILY_CLOSE", "").strip() == "1"


def intraday_close_1530():
    """Chan_gap breakdown (user 2026-11-15 "Do the breakdown run"): INTRADAY_CLOSE_1530=1 (intraday intervals only)
    also walks every candidate through the bars ending <= 15:30 (the 15:15 bar included) and books the last intraday
    close. Same candidates, same entry, same price basis: the only difference from the plain tag is the exit time
    (15:15 live vs the 15:30 close), without the daily-vs-intraday Yahoo bar mismatch the _xd1530 twin carries."""
    return os.environ.get("INTRADAY_CLOSE_1530", "").strip() == "1"


IC_CUTOFF_MIN = 15 * 60 + 30


def daily_as_intraday(daily):
    """1d resolution: one 'intraday' bar per day = the day's own OHLC, stamped 09:15 IST (stop checked on the day's
    High/Low, flat at the day close), the same resolution as the 1d baseline."""
    d = daily.copy()
    d["Date"] = (pd.to_datetime(d["Date"]).dt.tz_localize(None).dt.normalize() + pd.Timedelta(hours=9, minutes=15)).dt.tz_localize("Asia/Kolkata")
    return d


def parse_atrs(s=None):
    s = s or os.environ.get("ATRS")
    return tuple(float(x) for x in s.split(",")) if s else DEFAULT_ATRS


def day_walk(m, bars, entry, stop, direction, interval):
    """Walk one day's intraday bars through the real chan_gap_exit_reason. -> (reason, exit_px)."""
    last_close = entry
    for _, bar in bars.iterrows():
        reason, px = m.chan_gap_exit_reason(bar, entry, stop, direction)
        if reason == "stop":
            return "stop", px
        last_close = float(bar["Close"])
    return "close", last_close


def split_days(intr, interval, cutoff):
    """{ist_date_str: bars with END <= cutoff}, in time order."""
    d = pd.to_datetime(intr["Date"])
    if getattr(d.dt, "tz", None) is not None:
        d = d.dt.tz_convert("Asia/Kolkata")
    mins = (d.dt.hour * 60 + d.dt.minute).to_numpy()
    keep = (mins + BAR_MIN[interval]) <= cutoff
    out = {}
    day = d.dt.strftime("%Y-%m-%d").to_numpy()
    for i in np.flatnonzero(keep):
        out.setdefault(day[i], []).append(i)
    return {k: intr.iloc[v] for k, v in out.items()}


def day_candidates(m, daily, intr, direction, interval, atrs):
    """[(date, signal dict, {tag: [reason, exit_px]})] for each intraday day the real entry filter passes."""
    daily = daily.reset_index(drop=True)
    ddates = pd.to_datetime(daily["Date"]).dt.strftime("%Y-%m-%d").to_numpy()
    days = split_days(intr, interval, m.CHAN_FLATTEN_CUTOFF_MIN)
    out = []
    win = window_days()
    pair = paired_daily_close() and interval != "1d"
    ic = intraday_close_1530() and interval != "1d"
    # Yahoo's last NSE bar starts at 15:15 and is shorter than BAR_MIN, so keep every bar that STARTS before 15:30
    days_ic = split_days(intr, interval, IC_CUTOFF_MIN - 1 + BAR_MIN[interval]) if ic else {}
    raw = raw_daily()
    start = (pd.Timestamp.now(tz="Asia/Kolkata").normalize() - pd.Timedelta(days=win)).strftime("%Y-%m-%d") if win else ""
    for d in sorted(days):
        if d < start:
            continue
        bars = days[d]
        k = int(np.searchsorted(ddates, d, side="left"))  # completed daily bars strictly before d
        if k < NEED or bars.empty:
            continue
        o = float(bars["Open"].iloc[0])
        same = k < len(ddates) and ddates[k] == d
        dclose = float(daily["Close"].iloc[k]) if same else None
        dopen_ratio = float(daily["Open"].iloc[k]) / o if same and o > 0 else None  # B-1604 diagnostic: ~1.0 when consistent
        hist = daily.iloc[max(0, k - LOOKBACK):k]
        sig = m.chan_gap_entry_signal(hist, o, direction, atrs[0])
        if not sig:
            continue
        res = {}
        for mult in atrs:
            sg = m.chan_gap_entry_signal(hist, o, direction, mult)
            if not sg:
                continue
            walk = day_walk(m, bars, o, sg["stop_loss"], direction, interval)
            res[tag_for(direction, interval, mult, win, raw=raw)] = list(walk)
            if pair and dclose is not None:  # B-1604: same trade, exit at the 15:30 daily close unless stopped by 15:15
                res[tag_for(direction, interval, mult, win, xd=True, raw=raw)] = list(walk) if walk[0] == "stop" else ["close", dclose]
            if ic and d in days_ic:  # same trade, stop walk continues through the 15:15 bar, flat at its 15:30 close
                res[tag_for(direction, interval, mult, win, raw=raw, ic=True)] = list(day_walk(m, days_ic[d], o, sg["stop_loss"], direction, interval))
        out.append((d, {**{k2: sig[k2] for k2 in ("entry_price", "score", "gap")}, "dopen_ratio": dopen_ratio}, res))
    return out


def synthetic_pair(seed, interval, n_days=400):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, n_days)))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.03, n_days))
    hi = np.maximum(o, c) * 1.005
    lo = np.minimum(o, c) * 0.995
    dd = pd.bdate_range("2023-01-02", periods=n_days)
    daily = pd.DataFrame({"Date": dd.strftime("%Y-%m-%d"), "Open": o, "High": hi, "Low": lo, "Close": c,
                          "Volume": rng.integers(2e6, 9e6, n_days).astype(float)})
    if interval == "1d":
        return daily, daily_as_intraday(daily)
    rows = []
    step = BAR_MIN[interval]
    for i in range(n_days - 30, n_days):
        t0 = pd.Timestamp(dd[i]).tz_localize("Asia/Kolkata") + pd.Timedelta(hours=9, minutes=15)
        nb = 375 // step
        path = np.linspace(o[i], c[i], nb + 1)
        for b in range(nb):
            a, z = path[b], path[b + 1]
            rows.append({"Date": t0 + pd.Timedelta(minutes=step * b), "Open": a, "High": max(a, z) * 1.002,
                         "Low": min(a, z) * 0.998, "Close": z, "Volume": 1e5})
    return daily, pd.DataFrame(rows)


def load_pairs(m, interval, shard, nshards, limit=None):
    if os.environ.get("SYNTHETIC") == "1":
        return {f"SYN{k}": synthetic_pair(k, interval) for k in range(limit or 4)}
    syms = sorted(set(m._load_nse_universe_from_file()))[shard::nshards]
    if limit:
        syms = syms[:limit]
    out = {}
    for s in syms:
        try:
            fetch = fetch_raw if raw_daily() else m.fetch_ohlc
            daily = fetch(s, "5y", "1d")
            intr = daily_as_intraday(daily) if interval == "1d" else fetch(s, PERIOD_BY_INTERVAL[interval], interval)
        except Exception:
            continue
        if daily is None or intr is None or len(daily) < NEED + 3 or len(intr) < 10:
            continue
        out[s] = (daily.reset_index(drop=True), intr.reset_index(drop=True))
    return out


def run():
    import main as m
    direction = os.environ.get("DIRECTION", "short")
    interval = os.environ.get("INTERVAL", "15m")
    if direction not in NAMES or interval not in PERIOD_BY_INTERVAL:
        raise SystemExit(f"bad DIRECTION/INTERVAL {direction}/{interval}")
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    atrs = parse_atrs()
    pairs = load_pairs(m, interval, shard, nshards, limit)
    cands = []
    for sym, (daily, intr) in pairs.items():
        try:
            for d, sig, res in day_candidates(m, daily, intr, direction, interval, atrs):
                cands.append({"date": d, "symbol": sym, "sig": sig, "res": res})
        except Exception as ex:
            print("ERROR", sym, ex)
    os.makedirs("out", exist_ok=True)
    path = f"out/chan_gap_tf_{direction}_{interval}_s{shard}.json"
    json.dump({"family": "chan_gap", "direction": direction, "interval": interval,
               "period": PERIOD_BY_INTERVAL[interval], "window_days": window_days(), "shard": shard, "nshards": nshards, "n_symbols": len(pairs),
               "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT, "top_n": m.CHAN_GAP_TOP_N,
               "synthetic": os.environ.get("SYNTHETIC") == "1", "atrs": list(atrs), "candidates": cands}, open(path, "w"))
    print("wrote", path, "symbols", len(pairs), "candidate-days", len(cands))


def merge(d, out_path=None):
    import main as m
    groups = {}
    for f in sorted(glob.glob(os.path.join(d, "**", "chan_gap_tf_*_s*.json"), recursive=True)):
        r = json.load(open(f))
        g = groups.setdefault((r["direction"], r["interval"]),
                              {"by_date": {}, "nsym": 0, "files": 0, "meta": r, "tags": set()})
        g["nsym"] += r["n_symbols"]
        g["files"] += 1
        for c in r["candidates"]:
            g["by_date"].setdefault(c["date"], {})[c["symbol"]] = c
            g["tags"].update(c["res"])
    rows, meta = [], {}
    for (direction, interval), g in sorted(groups.items()):
        cost = g["meta"]["cost_round_trip_pct"] / 100.0
        aggs = {t: br.agg_new() for t in sorted(g["tags"])}
        ratios = []
        for date in sorted(g["by_date"]):
            day = g["by_date"][date]
            for s in m.chan_gap_select_top({s: c["sig"] for s, c in day.items()}, direction, g["meta"]["top_n"]):
                ep = day[s]["sig"]["entry_price"]
                if day[s]["sig"].get("dopen_ratio"):
                    ratios.append(day[s]["sig"]["dopen_ratio"])
                for t, v in day[s]["res"].items():
                    gross = (v[1] - ep) / ep if direction == "long" else (ep - v[1]) / ep
                    br.agg_add(aggs[t], [{"gross": gross, "net": gross - cost, "held": 1, "reason": v[0]}])
        if ratios:  # B-1604: daily Open / intraday first-bar open on the traded days (1.0 = same price basis)
            rr = np.array(ratios)
            print("DOPEN_RATIO", direction, interval, "n", len(rr), "median", round(float(np.median(rr)), 5),
                  "p10", round(float(np.percentile(rr, 10)), 5), "p90", round(float(np.percentile(rr, 90)), 5),
                  "frac_off_0.5pct", round(float(np.mean(np.abs(rr - 1) > 0.005)), 4))
        for t, a in aggs.items():
            mt = br.agg_metrics(a)
            mt["avg_held_hours"] = round(mt["avg_held_bars"] * HOURS_PER_SESSION, 1)
            rows.append({"tag": t, "direction": direction, "interval": interval, "period": g["meta"]["period"],
                         "n_symbols": g["nsym"], "shards": g["files"], "metrics": mt})
            print(t, "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"], mt["exit_reasons"])
        meta = {k: g["meta"][k] for k in ("cost_round_trip_pct", "synthetic")}
    out = {**meta, "note": "per-day top-10 ranked across shards by the real chan_gap_select_top; entry first-bar open, stop checked on "
           "every intraday bar via the real chan_gap_exit_reason, flat at last bar ending <=15:15 IST; 1m (7d) and 4h (needs 1h "
           "resample) not run; sample is 60d (5m/15m) or 730d (1h), far fewer days than the 5y 1d baseline: read n; schema read by "
           "main._replay_verified_tags", "rows": rows}
    json.dump(out, open(out_path or os.path.join(d, "replay_all.json"), "w"), indent=1)
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        run()
