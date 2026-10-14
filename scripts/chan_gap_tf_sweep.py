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

  run    env: DIRECTION long|short, INTERVAL 5m|15m|1h, SHARD, NSHARDS, SYMBOL_LIMIT, ATRS="1.5,2.5,4.0", SYNTHETIC=1 (smoke, NOT a result)
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

PERIOD_BY_INTERVAL = {"5m": "60d", "15m": "60d", "1h": "730d"}
BAR_MIN = {"5m": 5, "15m": 15, "1h": 60}
NEED = 92  # CHAN_GAP_STD_WINDOW + 2 completed daily bars
LOOKBACK = 110
HOURS_PER_SESSION = 6.25
DEFAULT_ATRS = (1.5, 2.5, 4.0)
NAMES = {"long": "buy_on_gap__long", "short": "short_on_gap__short"}


def tag_for(direction, interval, mult):
    k = ("%.1f" % mult).replace(".", "d")
    return f"chan_gap__{NAMES[direction]}__{interval}__atr{k}_top10__v1"


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
    for d in sorted(days):
        bars = days[d]
        k = int(np.searchsorted(ddates, d, side="left"))  # completed daily bars strictly before d
        if k < NEED or bars.empty:
            continue
        o = float(bars["Open"].iloc[0])
        hist = daily.iloc[max(0, k - LOOKBACK):k]
        sig = m.chan_gap_entry_signal(hist, o, direction, atrs[0])
        if not sig:
            continue
        res = {}
        for mult in atrs:
            sg = m.chan_gap_entry_signal(hist, o, direction, mult)
            if not sg:
                continue
            res[tag_for(direction, interval, mult)] = list(day_walk(m, bars, o, sg["stop_loss"], direction, interval))
        out.append((d, {k2: sig[k2] for k2 in ("entry_price", "score", "gap")}, res))
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
            daily = m.fetch_ohlc(s, "5y", "1d")
            intr = m.fetch_ohlc(s, PERIOD_BY_INTERVAL[interval], interval)
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
               "period": PERIOD_BY_INTERVAL[interval], "shard": shard, "nshards": nshards, "n_symbols": len(pairs),
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
        for date in sorted(g["by_date"]):
            day = g["by_date"][date]
            for s in m.chan_gap_select_top({s: c["sig"] for s, c in day.items()}, direction, g["meta"]["top_n"]):
                ep = day[s]["sig"]["entry_price"]
                for t, v in day[s]["res"].items():
                    gross = (v[1] - ep) / ep if direction == "long" else (ep - v[1]) / ep
                    br.agg_add(aggs[t], [{"gross": gross, "net": gross - cost, "held": 1, "reason": v[0]}])
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
