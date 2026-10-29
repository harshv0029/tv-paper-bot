"""Live LONG swing families without a reusable replay script: gap_and_go, primary_base, power_play, O'Neil 1w cells
(backlog B-1417). Their earlier validations were inline workflow heredocs (power-play-validation-replay.yml,
primary-base-validation-replay.yml, swing-gap-and-go-live-validation-replay.yml) and O'Neil's replay
(scripts/oneil_replay.py) runs on WEEKLY bars, where a DAILY price band cannot be modelled.

ENTRY and EXIT decisions are the REAL main.py functions the live swing scan (_run_swing_scan_pass) calls:
  power_play   : main.power_play_entry_signal          + main.power_play_exit_reason        (chandelier, close-based)
  primary_base : main.primary_base_entry_signal        + main.minervini_vcp_exit_reason     (chandelier, close-based)
  gap_and_go   : main.gap_and_go_entry_signal          + main.gap_and_go_exit_reason        (frozen stop on the close)
  oneil        : main.oneil_swing_entry_signal(df,tag) + main._oneil_swing_exit_adapter     (tags = main.ONEIL_SWING_CELLS,
                 daily bars, the live 1w cells resampled inside main exactly as live)
The driver only supplies the bar loop, mirroring the live engine: the scan on day i sees the bars up to i (window per
family below), enters at the signal close, checks exits on later days (fill at that day's close; an intraday
'oneil_stop_hit' fills at min(open, stop)), never re-enters on a bar a position was open/closed (live `continue`), an
O'Neil tag re-enters at most once per week (live guard). Each tag is replayed independently. Windows: primary_base and
power_play = full prefix (as their validations; primary_base needs the whole history for its young-stock gate),
gap_and_go = 150 bars (its validation), oneil = 500 bars (the live 2y fetch).

band_cap (scripts/swing_bandcap.py): off (default) = the above unchanged; live = the stop Kotak rests,
main._swing_strategy_stop_level(tag, initial stop, ATR at entry, running max close through yesterday) (the live SL-sync
level), raised to the 10% band floor off yesterday's close, triggered intraday on the low from the day after entry,
filled at min(open, trigger), checked BEFORE the strategy's own exit.
Cost = main.ROUND_TRIP_COST_PCT/100 (0.8%) on the % return. Universe = main._load_nse_universe_from_file() (full, NOT
main.NSE_FULL_UNIVERSE). Daily bars, 5y.

Modes: run (env FAMILY, SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1 smoke, BAND_CAP) -> out/classic_<family>_s<shard>.json
(raw sums, brk20_replay schema); merge <dir> -> <dir>/classic_all.json.
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
import brk20_replay as br  # noqa: E402  (exact-mergeable aggregation helpers + synthetic frames)
import swing_bandcap as bc  # noqa: E402

PERIOD, INTERVAL = "5y", "1d"
FAMILIES = ("power_play", "primary_base", "gap_and_go", "oneil")
WINDOW = {"power_play": None, "primary_base": None, "gap_and_go": 150, "oneil": 500}
ENTRY_FNS = ("power_play_entry_signal", "primary_base_entry_signal", "gap_and_go_entry_signal",
             "oneil_swing_entry_signal")


def tags_for(m, family):
    return list(m.ONEIL_SWING_CELLS) if family == "oneil" else [family]


def min_bars(m, family):
    if family == "power_play":
        return m.POWER_PLAY_LAUNCH_MAX_DAYS + m.POWER_PLAY_CONSOL_MAX_DAYS + 20
    if family == "primary_base":
        return m.MINERVINI_PRIMARY_BASE_MIN_BASE_DAYS + 5
    return {"gap_and_go": 30, "oneil": 60}[family]


def _entry(m, family, tag, win):
    if family == "power_play":
        return m.power_play_entry_signal(win)
    if family == "primary_base":
        return m.primary_base_entry_signal(win)
    if family == "gap_and_go":
        return m.gap_and_go_entry_signal(win)
    return m.oneil_swing_entry_signal(win, tag)


def _exit(m, family, win, pos):
    """(reason, new_running_max) from the real live exit fn."""
    if family == "power_play":
        return m.power_play_exit_reason(win, pos["day"], pos["stop"], pos["atr"], pos["rmc"])
    if family == "primary_base":
        return m.minervini_vcp_exit_reason(win, pos["day"], pos["stop"], pos["atr"], pos["rmc"])
    if family == "gap_and_go":
        return m.gap_and_go_exit_reason(win, pos["day"], pos["stop"], pos["gap_low"]), pos["rmc"]
    return m._oneil_swing_exit_adapter(win, pos["day"], pos["stop"], pos["atr"], pos["rmc"])


def replay_symbol(m, df, family, tag, cost, band_cap="off"):
    """One symbol, one tag. Returns trade dicts {gross, net, held, reason}."""
    df = df.reset_index(drop=True)
    n = len(df)
    mb = min_bars(m, family)
    if n < mb + 3 or "Date" not in df.columns:
        return []
    opens, lows, highs = (df[x].to_numpy(float) for x in ("Open", "Low", "High"))
    closes = df["Close"].to_numpy(float)
    dates = df["Date"].astype(str).str[:10].to_numpy()
    weeks = pd.DatetimeIndex(pd.to_datetime(dates)).to_period("W-FRI").astype(str).to_numpy()
    band = bc.normalize_mode(band_cap) != "off"
    prevc = bc.prev_session_close(df) if band else None
    w = WINDOW[family]
    out, pos, last_entry_week = [], None, None
    for i in range(mb, n):
        win = df.iloc[:i + 1] if w is None else df.iloc[max(0, i + 1 - w):i + 1]
        if pos is not None:
            if band and i > pos["idx"]:
                strat_stop = m._swing_strategy_stop_level(tag, pos["stop"], pos["atr"], pos["rmc"])
                hit = bc.resting_stop_exit(band_cap, "long", strat_stop, prevc[i], opens[i], lows[i], highs[i])
                if hit:
                    out.append(_fin(pos, hit[0], i, hit[1], cost))
                    pos = None
                    continue
            reason, rmc = _exit(m, family, win, pos)
            pos["rmc"] = rmc if rmc is not None else pos["rmc"]
            if reason:
                xp = float(min(opens[i], pos["stop"])) if reason == "oneil_stop_hit" else float(closes[i])
                out.append(_fin(pos, xp, i, reason, cost))
                pos = None
            continue  # live: never also enter the day a position is/was open
        if family == "oneil" and last_entry_week == weeks[i]:
            continue  # live: a stop-out inside the 2-session window must not re-enter the same week's signal
        sig = _entry(m, family, tag, win)
        if not sig:
            continue
        ep, sl = float(sig["entry_price"]), float(sig["stop_loss"])
        if not 0 < sl < ep:
            continue
        pos = {"ep": ep, "stop": sl, "atr": sig.get("atr_at_entry"), "gap_low": sig.get("gap_low"),
               "rmc": ep, "day": dates[i], "idx": i}
        last_entry_week = weeks[i]
    if pos is not None:
        out.append(_fin(pos, float(closes[-1]), n - 1, "data_end_forced_close", cost))
    return out


def _fin(pos, xp, i, reason, cost):
    g = (xp - pos["ep"]) / pos["ep"]
    return {"gross": g, "net": g - cost, "held": i - pos["idx"], "reason": reason}


def load_frames(m, shard, nshards, limit=None):
    if os.environ.get("SYNTHETIC") == "1":
        return {f"SYN{k}": br.synthetic_frame(k) for k in range(limit or 3)}
    syms = sorted(set(m._load_nse_universe_from_file()))[shard::nshards]
    if limit:
        syms = syms[:limit]
    out = {}
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, PERIOD, INTERVAL)
        except Exception:
            continue
        if raw is not None and len(raw) >= 30:
            out[s] = raw.reset_index(drop=True)
    print(f"fetch: {len(syms)} symbols, {len(out)} loaded")
    return out


def run():
    import main as m
    family = os.environ.get("FAMILY", "power_play")
    if family not in FAMILIES:
        raise SystemExit(f"bad family {family}")
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    band_cap = bc.mode_from_env()
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    tags = tags_for(m, family)
    frames = load_frames(m, shard, nshards, limit)
    aggs = {t: br.agg_new() for t in tags}
    for sym, df in frames.items():
        for t in tags:
            try:
                br.agg_add(aggs[t], replay_symbol(m, df, family, t, cost, band_cap))
            except Exception as ex:
                print("ERROR", sym, t, ex)
    res = {"family": family, "interval": INTERVAL, "period": PERIOD, "shard": shard, "nshards": nshards,
           "n_symbols": len(frames), "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT, "band_cap": band_cap,
           "synthetic": os.environ.get("SYNTHETIC") == "1", "direction": "long",
           "cells": {bc.band_tag(t, band_cap): {"raw": a} for t, a in aggs.items()}}
    os.makedirs("out", exist_ok=True)
    path = f"out/classic_{family}_s{shard}.json"
    json.dump(res, open(path, "w"), indent=1)
    for t, a in aggs.items():
        mt = br.agg_metrics(a)
        print(bc.band_tag(t, band_cap), "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    print("wrote", path)


def merge(d):
    tags = {}
    for f in sorted(glob.glob(os.path.join(d, "classic_*_s*.json"))):
        r = json.load(open(f))
        for t, c in r["cells"].items():
            e = tags.setdefault(t, {"agg": br.agg_new(), "n_symbols": 0, "family": r["family"]})
            br.agg_merge(e["agg"], c["raw"])
            e["n_symbols"] += r["n_symbols"]
    rows = [{"tag": t, "family": e["family"], "n_symbols": e["n_symbols"], "metrics": br.agg_metrics(e["agg"])}
            for t, e in sorted(tags.items())]
    json.dump({"rows": rows}, open(os.path.join(d, "classic_all.json"), "w"), indent=1)
    for r in rows:
        mt = r["metrics"]
        print(r["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    return rows


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2])
    else:
        run()
