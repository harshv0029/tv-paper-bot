"""Exit-family research (backlog B-529, B-538, B-493, B-740).

ENTRIES come from the REAL, unmodified live swing entry functions in main.py
(order_block_entry_signal, volume_profile_poc_entry_signal, gap_and_go_entry_signal and its short
mirror gap_and_go_entry_signal_short), evaluated on every daily bar of every symbol (trailing
150-bar window, same as the live-validation replays). The SAME entry set is then replayed under
different exit families, so the exit effect is isolated (entries identical by construction):

  exitfixed   fixed ATR stop (atr 1.5 / 2.5 / 3.5)                      - baseline for B-529
  exitstruct  structural swing-low (swing-high for shorts) stop, fixed   - B-529 (Douglas); entry
              REJECTED when no structural stop exists below entry
  exitchand   chandelier trail (3x / 6x ATR) on top of a 2.5 ATR stop    - trail-only baseline for B-538
  exitoneil   trailing stop ratcheted to each confirmed swing low        - B-493 (O'Neil defensive stop)
  exitexhaust chandelier 6x + exhaustion exit (RSI reversal / ROC reversal / volume climax)
                                                                         - B-538 (Douglas)
  exittime    2.5 ATR stop + pure time exit (5 / 10 / 20 bars)
  exitinval   signal-invalidation exit (weekly EMA13 turn / weekly MACD-H turn / Elder-ray bear)
              with a 2.5 ATR stop or a wide 6.0 ATR catastrophic stop - B-740 (Elder)

EVERY trade carries a stop (SL-on-every-trade rule); there is no stop-less cell. Short orientation
is produced by negating prices (h' = -l, l' = -h, c' = -c) so long and short run the SAME core and
can never drift. Net of main.ROUND_TRIP_COST_PCT (0.8%). Equal-notional per-trade returns:
PFnet = sum(net wins) / |sum(net losses)|. Overlapping signals are allowed (each signal replayed
independently; >= MIN_SIGNAL_GAP bars apart per symbol per entry set). A trade whose full hold
window runs past the end of data is dropped (no truncated-exit bias).

B-1416 (2026-10-29): the legacy settings above (overlapping signals, equal-notional 0.8% cost, truncated
trades dropped; run 38140914889, tags __v1) inflated OB / VP exitinval to 1.166 / 1.268 vs 1.074 / 1.089
in the main.py replay (swing-ob-vp-main-replay.yml, run 40820614764). The DEFAULT is now
MATCH_MAIN_REPLAY=True, which reproduces that replay's book-keeping: one position per symbol per cell
(a signal is taken only once the previous trade has exited; re-entry allowed on the exit bar), every
signal bar collected (no 5-bar gap), 1%-risk sizing on a Rs 4 lakh / CAPITAL_TRANCHES slice
(qty = floor(min(risk / stop distance, slice / price)), skipped when qty is 0 or notional < Rs 100),
itemized Kotak costs + DP charge (REPLAY_COST), and a trade still open at the end of data is force-closed
at the last close instead of dropped. Tags in this mode end in __v2 (new tags; the __v1 numbers stay
registered). `run --legacy-sim` restores the old behaviour and the __v1 tags.
See docs/B1416_SIM_VS_REPLAY_ROOT_CAUSE.md.

Owed / not covered (flagged, not skipped silently): candle-size sweep (this is 1d only; yfinance
caps intraday history, 4h needs a 1h resample); order_block / volume_profile short mirrors (no
live short entry function exists in main.py, so no honest short entry source).

CLI:  python scripts/exit_family_research.py run --shard 0 --shards 4 --out out/shard0.json
      python scripts/exit_family_research.py merge --dir out --out docs/exit_family_results.json
"""
import argparse
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

WINDOW_BARS = 150
MIN_SIGNAL_GAP = 5
MAX_HOLD = 30
MIN_BARS = 160
PAD_ATR = 0.1
TF = "1d"

# B-1416: True = match the main.py replay (swing-ob-vp-main-replay.yml) book-keeping; False = legacy sim.
MATCH_MAIN_REPLAY = True
REPLAY_CAPITAL = 400000.0
REPLAY_RISK_PCT = 1.0
# same itemized cost model as swing-ob-vp-main-replay.yml (per side, fraction of notional)
REPLAY_COST = {"brokerage_pct": 0.0020, "exchange_txn_pct": 0.0000297, "sebi_fee_pct": 0.000001,
               "stamp_duty_buy_pct": 0.00015, "stt_buy_pct": 0.001, "stt_sell_pct": 0.001,
               "gst_pct": 0.18, "slippage_pct": 0.0005, "dp_charge_flat": 15.93}

# entry set key -> (tag family, direction)
ENTRY_SETS = {
    "ob_long": ("order_block_delta", "long"),
    "vp_long": ("volume_profile_poc", "long"),
    "gg_long": ("gap_and_go", "long"),
    "gg_short": ("gap_and_go", "short"),
}


def _cells():
    cells = []
    for k in (1.5, 2.5, 3.5):
        cells.append({"kind": "fixed", "variant": "exitfixed", "atr": k, "hold": MAX_HOLD})
    for n in (5, 10, 20):
        cells.append({"kind": "struct", "variant": "exitstruct", "sw": n, "hold": MAX_HOLD})
    for m in (3.0, 6.0):
        cells.append({"kind": "chand", "variant": "exitchand", "atr": 2.5, "trail": m, "hold": MAX_HOLD})
    for w in (1, 2):
        cells.append({"kind": "oneil", "variant": "exitoneil", "atr": 2.5, "w": w, "hold": MAX_HOLD})
    for x in ("rsi", "roc", "volclimax"):
        cells.append({"kind": "exhaust", "variant": "exitexhaust", "atr": 2.5, "trail": 6.0, "x": x, "hold": MAX_HOLD})
    for t in (5, 10, 20):
        cells.append({"kind": "time", "variant": "exittime", "atr": 2.5, "hold": t})
    for s in ("ema13w", "macdhw", "elder"):
        for k in (2.5, 6.0):
            cells.append({"kind": "inval", "variant": "exitinval", "atr": k, "sig": s, "hold": MAX_HOLD})
    return cells


CELLS = _cells()


def _fmt(v):
    if isinstance(v, float):
        return str(v).replace(".", "d")
    return str(v)


def cell_tag(entry_key, cell, version=None):
    """<family>__<variant>__<dir>__<tf>__<params>__v<N> ; params = alphabetical key+value.
    v1 = legacy overlapping sim (run 38140914889); v2 = main.py-replay-matching sim (B-1416)."""
    fam, d = ENTRY_SETS[entry_key]
    skip = {"kind", "variant"}
    params = "_".join(f"{k}{_fmt(cell[k])}" for k in sorted(cell) if k not in skip)
    if version is None:
        version = 2 if MATCH_MAIN_REPLAY else 1
    return f"{fam}__{cell['variant']}__{d}__{TF}__{params}__v{version}"


# ----------------------------------------------------------------------------- indicators
def _ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1 / n, adjust=False).mean()
    dn = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    out[(dn == 0) & (up > 0)] = 100.0
    return out.fillna(50.0).to_numpy()


def _weekly_down_flags(index, c):
    """Per-day booleans using only COMPLETED weeks (no lookahead): weekly EMA13 turned down,
    weekly MACD histogram turned down. `c` = oriented closes."""
    n = len(c)
    ema_dn = np.zeros(n, bool)
    macd_dn = np.zeros(n, bool)
    try:
        per = pd.DatetimeIndex(index).to_period("W-FRI")
    except Exception:
        return ema_dn, macd_dn
    codes, _ = pd.factorize(per, sort=True)
    nw = int(codes.max()) + 1
    if nw < 30:
        return ema_dn, macd_dn
    wc = pd.Series(c).groupby(codes).last().to_numpy()
    e13 = _ema(wc, 13)
    hist = _ema(wc, 12) - _ema(wc, 26)
    hist = hist - _ema(hist, 9)
    w_e = np.zeros(nw, bool)
    w_m = np.zeros(nw, bool)
    w_e[1:] = e13[1:] < e13[:-1]
    w_m[1:] = hist[1:] < hist[:-1]
    prev = np.clip(codes - 1, 0, None)  # day in week w sees the last COMPLETED week w-1
    ema_dn = np.where(codes >= 1, w_e[prev], False)
    macd_dn = np.where(codes >= 1, w_m[prev], False)
    return ema_dn, macd_dn


def prepare(df, sign):
    """Oriented (sign=+1 long, -1 short) arrays + indicators. df: DatetimeIndex + OHLCV."""
    import main as m
    o = df["Open"].to_numpy(float)
    h = df["High"].to_numpy(float)
    l = df["Low"].to_numpy(float)
    c = df["Close"].to_numpy(float)
    v = df["Volume"].to_numpy(float)
    atr = m._atr_array(h, l, c, 14)  # always from raw prices
    if sign > 0:
        oo, hh, ll, cc = o, h, l, c
    else:
        oo, hh, ll, cc = -o, -l, -h, -c
    ema13 = _ema(cc, 13)
    ema_dn_w, macd_dn_w = _weekly_down_flags(df.index, cc)
    roc = np.full(len(cc), np.nan)
    roc[10:] = (cc[10:] - cc[:-10]) / np.abs(cc[:-10])
    va = pd.Series(v).rolling(20).mean().shift(1).to_numpy()
    elder_bear = np.r_[False, ema13[1:] < ema13[:-1]] & (hh < ema13)
    return {
        "o": oo, "h": hh, "l": ll, "c": cc, "v": v, "atr": atr, "rsi": _rsi(cc), "roc": roc, "vavg": va,
        "inval": {"ema13w": ema_dn_w, "macdhw": macd_dn_w, "elder": elder_bear},
    }


# ----------------------------------------------------------------------------- exit simulation
def _res(entry, exit_px, held, reason):
    return ((exit_px - entry) / abs(entry), held, reason)


def initial_stop(S, i0, cell):
    """Oriented initial stop for an entry at the close of bar i0; "rejected" when a structural
    stop does not sit below entry; None when ATR is unusable."""
    atr = S["atr"][i0]
    if not np.isfinite(atr) or atr <= 0:
        return None
    entry = S["c"][i0]
    if cell["kind"] == "struct":
        lo = float(np.min(S["l"][max(0, i0 - cell["sw"] + 1): i0 + 1]))
        stop = lo - PAD_ATR * atr
        return stop if stop < entry else "rejected"
    return entry - cell["atr"] * atr


def simulate(S, i0, cell, force_close_at_end=False):
    """Replay one entry (at close of bar i0) under one exit cell.
    Returns (gross_return, hold_bars, reason), "rejected", or None (unusable).
    force_close_at_end=False (legacy): a trade whose hold window runs past the data is dropped (None).
    True (main.py replay): it runs to the last bar and is closed there as data_end_forced_close."""
    o, h, l, c = S["o"], S["h"], S["l"], S["c"]
    n = len(c)
    atr = S["atr"][i0]
    if not np.isfinite(atr) or atr <= 0:
        return None
    entry = c[i0]
    kind = cell["kind"]
    hold = cell["hold"]
    if i0 + hold > n - 1 and not (force_close_at_end and i0 < n - 1):
        return None
    stop = initial_stop(S, i0, cell)
    if stop == "rejected":
        return "rejected"
    init = stop
    runmax = entry
    w = cell.get("w", 1)
    for j in range(i0 + 1, min(i0 + hold, n - 1) + 1):
        if o[j] <= stop:
            return _res(entry, o[j], j - i0, "stop_hit" if stop == init else "trail_stop_hit")
        if l[j] <= stop:
            return _res(entry, stop, j - i0, "stop_hit" if stop == init else "trail_stop_hit")
        runmax = max(runmax, c[j])
        if kind in ("chand", "exhaust"):
            stop = max(stop, runmax - cell["trail"] * atr)
        elif kind == "oneil":
            s = j - w
            if s > i0 and l[s] < np.min(l[s - w:s]) and l[s] < np.min(l[s + 1:j + 1]):
                cand = l[s] - PAD_ATR * atr
                if cand < c[j]:
                    stop = max(stop, cand)
        if kind == "exhaust" and c[j] > entry:
            x = cell["x"]
            if x == "rsi":
                hit = np.max(S["rsi"][j - 3:j]) >= 70 and S["rsi"][j] < 70
            elif x == "roc":
                r = S["roc"]
                hit = bool(np.isfinite(r[j - 5:j + 1]).all() and r[j - 1] >= 0.15
                           and r[j - 1] >= np.max(r[j - 5:j]) and r[j] < r[j - 1])
            else:
                va = S["vavg"][j]
                hit = bool(np.isfinite(va) and va > 0 and S["v"][j] >= 3 * va and c[j] < o[j])
            if hit:
                return _res(entry, c[j], j - i0, "exhaustion_exit")
        elif kind == "inval":
            f = S["inval"][cell["sig"]]
            if f[j] and not f[j - 1]:
                return _res(entry, c[j], j - i0, "signal_invalidation")
        if j - i0 >= hold:
            return _res(entry, c[j], j - i0, "time_stop" if kind == "time" else "max_hold_timeout")
    if force_close_at_end:
        return _res(entry, c[n - 1], n - 1 - i0, "data_end_forced_close")
    return None


def replay_leg_cost(qty, px, buy):
    """One side's itemized cost in INR, identical to swing-ob-vp-main-replay.yml's cost()."""
    cm = REPLAY_COST
    notional = qty * px
    b = notional * cm["brokerage_pct"]
    e = notional * cm["exchange_txn_pct"]
    s = notional * cm["sebi_fee_pct"]
    tax = notional * (cm["stt_buy_pct"] if buy else cm["stt_sell_pct"]) + (notional * cm["stamp_duty_buy_pct"] if buy else 0)
    return b + e + s + tax + (b + e + s) * cm["gst_pct"] + notional * cm["slippage_pct"]


def replay_qty(entry_px, stop_dist, tranches):
    """1%-risk sizing of the main.py replay: slice = capital / tranches; qty = floor(min(slice x
    risk% / stop distance, slice / price)); 0 when it cannot be sized (the replay then takes no trade)."""
    if not (stop_dist > 0 and entry_px > 0):
        return 0
    cap = min(REPLAY_CAPITAL, REPLAY_CAPITAL / tranches)
    qty = int(np.floor(min(cap * REPLAY_RISK_PCT / 100 / stop_dist, cap / entry_px)))
    return qty if qty > 0 and qty * entry_px >= 100 else 0


def replay_trade_inr(entry_px, gross_ret, qty, sign):
    """(gross_inr, cost_inr) for one trade under the replay cost model (DP charge per trade, as the
    replay's fin() applies it)."""
    exit_px = entry_px * (1 + sign * gross_ret)
    gross = gross_ret * entry_px * qty
    cost = (replay_leg_cost(qty, entry_px, sign > 0) + replay_leg_cost(qty, exit_px, sign < 0)
            + REPLAY_COST["dp_charge_flat"] * (1 + REPLAY_COST["gst_pct"]))
    return gross, cost


# ----------------------------------------------------------------------------- accumulation
def new_acc():
    return {"n": 0, "wins": 0, "rejected": 0, "gw": 0.0, "gl": 0.0, "nw": 0.0, "nl": 0.0,
            "hold_sum": 0, "reasons": {}}


def add_trade(acc, gross, held, reason, cost):
    net = gross - cost
    acc["n"] += 1
    acc["hold_sum"] += held
    r = acc["reasons"].setdefault(reason, {"n": 0, "wins": 0, "nw": 0.0, "nl": 0.0})
    r["n"] += 1
    if gross > 0:
        acc["gw"] += gross
    else:
        acc["gl"] += -gross
    if net > 0:
        acc["wins"] += 1
        acc["nw"] += net
        r["wins"] += 1
        r["nw"] += net
    else:
        acc["nl"] += -net
        r["nl"] += -net


def _pf(w, l):
    if l > 0:
        return round(w / l, 4)
    return None if w == 0 else float("inf")


def summarize(acc):
    n = acc["n"]
    return {
        "n": n, "rejected": acc["rejected"],
        "pfnet": _pf(acc["nw"], acc["nl"]), "pfgross": _pf(acc["gw"], acc["gl"]),
        "win_pct": round(100 * acc["wins"] / n, 2) if n else None,
        "avg_hold_bars": round(acc["hold_sum"] / n, 2) if n else None,
        "net_return_sum_pct": round(100 * (acc["nw"] - acc["nl"]), 2),
        "exit_reasons": {k: {"n": v["n"], "pct": round(100 * v["n"] / n, 1) if n else None,
                             "win_pct": round(100 * v["wins"] / v["n"], 1) if v["n"] else None,
                             "pfnet": _pf(v["nw"], v["nl"])} for k, v in sorted(acc["reasons"].items())},
    }


def merge_acc(a, b):
    for k in ("n", "wins", "rejected", "gw", "gl", "nw", "nl", "hold_sum"):
        a[k] += b[k]
    for r, v in b["reasons"].items():
        t = a["reasons"].setdefault(r, {"n": 0, "wins": 0, "nw": 0.0, "nl": 0.0})
        for k in t:
            t[k] += v[k]


# ----------------------------------------------------------------------------- signals
def collect_signals(df, key, min_gap=None):
    """Call the REAL live entry function on every bar's trailing window. The prefilters only skip
    bars where the real function provably returns None (necessary conditions). min_gap defaults to
    1 (every signal bar; the per-cell one-position filter decides) when MATCH_MAIN_REPLAY, else the
    legacy MIN_SIGNAL_GAP."""
    import main as m
    if min_gap is None:
        min_gap = 1 if MATCH_MAIN_REPLAY else MIN_SIGNAL_GAP
    fn = {"ob_long": m.order_block_entry_signal, "vp_long": m.volume_profile_poc_entry_signal,
          "gg_long": m.gap_and_go_entry_signal, "gg_short": m.gap_and_go_entry_signal_short}[key]
    c = df["Close"].to_numpy(float)
    o = df["Open"].to_numpy(float)
    n = len(df)
    ret = np.r_[np.nan, (c[1:] / c[:-1] - 1) * 100]
    out = []
    last = -10 ** 9
    for i in range(60, n - 1):
        if i - last < min_gap:
            continue
        if key == "gg_long" and not (o[i] / c[i - 1] - 1) * 100 >= m.SWING_GAP_PCT_THRESHOLD:
            continue
        if key == "gg_short" and not (1 - o[i] / c[i - 1]) * 100 >= m.SWING_GAP_PCT_THRESHOLD:
            continue
        if key == "ob_long":
            lo = max(1, i - m.ORDER_BLOCK_RETEST_MAX_DAYS)
            if not np.nanmax(ret[lo:i]) >= m.ORDER_BLOCK_IMPULSE_RETURN_PCT:
                continue
        window = df.iloc[max(0, i - WINDOW_BARS + 1): i + 1]
        try:
            sig = fn(window)
        except Exception:
            sig = None
        if sig:
            out.append(i)
            last = i
    return out


def process_symbol(df, accs, cost, sigfn=collect_signals, match=None):
    """df: DatetimeIndex + Open/High/Low/Close/Volume (+ optional Date col). Runs all entry sets x
    all exit cells for one symbol, adding into accs[tag].
    match (default MATCH_MAIN_REPLAY): one position per symbol per cell, force-close at data end,
    1%-risk INR sizing + itemized replay costs (`cost` unused). Legacy (match=False): overlapping
    trades, equal-notional returns net of the flat `cost` fraction."""
    if match is None:
        match = MATCH_MAIN_REPLAY
    tranches = None
    if match:
        import main as m
        tranches = m.CAPITAL_TRANCHES
    prepared = {}
    for key, (_fam, d) in ENTRY_SETS.items():
        idxs = sigfn(df, key)
        if not idxs:
            continue
        sign = 1 if d == "long" else -1
        if sign not in prepared:
            prepared[sign] = prepare(df, sign)
        S = prepared[sign]
        for cell in CELLS:
            acc = accs.setdefault(cell_tag(key, cell, version=2 if match else 1), new_acc())
            free_at = -1  # first bar a new position may open (match mode)
            for i in idxs:
                if match and i < free_at:
                    continue  # still holding the previous trade: the replay never sees this signal
                r = simulate(S, i, cell, force_close_at_end=match)
                if r == "rejected":
                    acc["rejected"] += 1
                elif r is not None:
                    if not match:
                        add_trade(acc, r[0], r[1], r[2], cost)
                        continue
                    entry_px = abs(float(S["c"][i]))
                    qty = replay_qty(entry_px, float(S["c"][i] - initial_stop(S, i, cell)), tranches)
                    if qty <= 0:
                        continue  # the replay cannot size it, so it never opens
                    g, tc = replay_trade_inr(entry_px, r[0], qty, sign)
                    add_trade(acc, g, r[1], r[2], tc)
                    free_at = i + r[1]  # exit is checked before entry on a bar: re-entry allowed on it


# ----------------------------------------------------------------------------- driver
def clean_bars(df, max_move=0.35):
    o, h, l, c = df["Open"], df["High"], df["Low"], df["Close"]
    ok = (o <= h * 1.001) & (o >= l * 0.999) & (c <= h * 1.001) & (c >= l * 0.999) & (l > 0) & ((h / l) < 1.6)
    jump = (c / c.shift(1) - 1).abs() > max_move
    return df[ok & ~jump.fillna(False)]


def shard_symbols(symbols, shard, shards):
    syms = sorted(set(symbols))
    return [s for k, s in enumerate(syms) if k % shards == shard]


def run(shard, shards, out, limit=None):
    import yfinance as yf
    import main as m
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    syms = [s for s in m._load_nse_universe_from_file() if s not in m.ETF_SYMBOLS]  # FULL universe
    total = len(syms)
    syms = shard_symbols(syms, shard, shards)
    if limit:
        syms = syms[:limit]
    accs, done = {}, 0
    for b0 in range(0, len(syms), 50):
        batch = syms[b0:b0 + 50]
        try:
            d = yf.download(batch, period="5y", interval="1d", group_by="ticker", auto_adjust=True,
                            progress=False, threads=True)
        except Exception as ex:
            print("batch fail", ex, flush=True)
            continue
        for s in batch:
            try:
                df = d[s] if len(batch) > 1 else d
                df = clean_bars(df[["Open", "High", "Low", "Close", "Volume"]].dropna())
                if len(df) < MIN_BARS:
                    continue
                df.index = pd.DatetimeIndex(df.index).tz_localize(None)
                process_symbol(df, accs, cost)
                done += 1
            except Exception as ex:
                print("symbol fail", s, ex, flush=True)
        print(f"shard {shard}: {b0 + len(batch)}/{len(syms)} symbols, {done} processed", flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as f:
        json.dump({"shard": shard, "shards": shards, "universe_total": total, "symbols_processed": done,
                   "sim_mode": "match_main_replay" if MATCH_MAIN_REPLAY else "legacy", "accs": accs}, f)
    print("wrote", out)


def merge(dirpath, out):
    accs, done, total, modes = {}, 0, 0, set()
    for p in sorted(glob.glob(os.path.join(dirpath, "**", "*.json"), recursive=True)):
        with open(p) as fh:
            j = json.load(fh)
        if "accs" not in j:
            continue
        done += j["symbols_processed"]
        modes.add(j.get("sim_mode", "legacy"))
        total = j["universe_total"]
        for tag, a in j["accs"].items():
            merge_acc(accs.setdefault(tag, new_acc()), a)
    res = {t: summarize(a) for t, a in sorted(accs.items())}
    doc = {"universe": "full NSE (main._load_nse_universe_from_file)", "universe_total": total,
           "symbols_processed": done, "tf": TF, "cost_round_trip_pct": 0.8, "sim_mode": sorted(modes),
           "backlog": ["B-529", "B-538", "B-493", "B-740"],
           "owed": ["candle-size sweep (1d only)",
                    "order_block/volume_profile short mirrors (no live short entry fn)"],
           "cells": res}
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as fh:
        json.dump(doc, fh, indent=1)
    print(f"{'tag':100s} {'n':>7s} {'pfnet':>7s} {'win%':>6s} {'hold':>5s} rej")
    for t, r in res.items():
        print(f"{t:100s} {r['n']:7d} {str(r['pfnet']):>7s} {str(r['win_pct']):>6s} "
              f"{str(r['avg_hold_bars']):>5s} {r['rejected']}")
        print("     exits:", {k: (v['n'], v['pfnet']) for k, v in r['exit_reasons'].items()})
    return doc


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--shard", type=int, required=True)
    r.add_argument("--shards", type=int, default=4)
    r.add_argument("--out", required=True)
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--legacy-sim", action="store_true",
                   help="legacy overlapping / equal-notional 0.8%% sim (run 38140914889, __v1 tags)")
    g = sub.add_parser("merge")
    g.add_argument("--dir", required=True)
    g.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "run":
        if a.legacy_sim:
            MATCH_MAIN_REPLAY = False
        run(a.shard, a.shards, a.out, a.limit)
    else:
        merge(a.dir, a.out)
