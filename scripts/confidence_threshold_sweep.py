"""B-421: min_entry_confidence sweep over the REAL main.py swing entry/exit functions.

Research only. Touches no live parameter, table or order path.

Question: if a direction-aware trend-confidence gate were added in front of a
trend/momentum entry (long needs fast MA > slow MA, short needs fast < slow,
both with main._trend_confidence >= threshold), what happens to full-universe
PFnet? threshold 0 is the UNGATED baseline (no filter at all), so each cell is
compared against the validated number it came from.

Design notes
- Entry/exit decisions come from the real main.py functions (never a
  reimplementation). The gate is the only added logic and uses the real
  main._trend_confidence / main._moving_average.
- One job = one strategy x one symbol shard. All thresholds run inside the job
  from a shared per-bar entry-signal cache (the entry signal does not depend on
  the threshold; the gate only decides whether it is taken, and a taken/skipped
  signal changes later position state, so each threshold is simulated
  separately).
- Accumulators are mergeable sums, so shards combine exactly (`merge` command).
- Mean-reversion cells are EXEMPT by design (a trend filter contradicts them):
  see EXEMPT_MEAN_REVERSION. They are listed in the output, not run.
- Intraday (buy/short) engines already take min_entry_confidence_pct as a
  parameter and need a 5m replay driver; that is NOT done here (listed under
  `owed` in the output rather than faked).
- Derived fields (best threshold meeting the floor) are computed at read time
  from the stored raw sums and never replace them; the raw numbers are all kept.

Tag grammar: <family>__confgate__<dir>__1d__cf<thr>_smaf<f>_smas<s>__v1
(params alphabetical, cf0 = ungated baseline).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass

THRESHOLDS = (0, 50, 60, 70, 80, 90, 95)
SMA_FAST = 9
SMA_SLOW = 21
MA_TYPE = "ema"
CAPITAL_INR = 400000.0
PERIOD = "5y"
INTERVAL = "1d"

DEFAULT_COST_MODEL = {
    "brokerage_pct": 0.0020, "brokerage_flat": 0.0,
    "exchange_txn_pct": 0.0000297, "sebi_fee_pct": 0.000001,
    "stamp_duty_buy_pct": 0.00015, "stt_buy_pct": 0.001, "stt_sell_pct": 0.001,
    "gst_pct": 0.18, "slippage_pct": 0.0005, "dp_charge_flat": 15.93,
}


@dataclass(frozen=True)
class StrategySpec:
    key: str            # matrix value
    family: str         # tag family
    direction: str      # long | short
    entry_fn: str       # main.<name>
    exit_fn: str        # main.<name>
    exit_kind: str      # chandelier | simple
    extra_key: str | None = None   # simple exits: entry-signal key passed as 4th arg
    category: str = "swing"


STRATEGIES = {s.key: s for s in (
    StrategySpec("minervini_vcp_long", "minervini_vcp", "long", "minervini_vcp_entry_signal", "minervini_vcp_exit_reason", "chandelier"),
    StrategySpec("minervini_vcp_short", "minervini_vcp", "short", "minervini_vcp_entry_signal_short", "minervini_vcp_exit_reason_short", "chandelier"),
    StrategySpec("power_play_long", "power_play", "long", "power_play_entry_signal", "power_play_exit_reason", "chandelier"),
    StrategySpec("power_play_short", "power_play", "short", "power_play_entry_signal_short", "power_play_exit_reason_short", "chandelier"),
    StrategySpec("gap_and_go_long", "gap_and_go", "long", "gap_and_go_entry_signal", "gap_and_go_exit_reason", "simple", "gap_low"),
    StrategySpec("gap_and_go_short", "gap_and_go", "short", "gap_and_go_entry_signal_short", "gap_and_go_exit_reason_short", "simple", "gap_high"),
    StrategySpec("order_block_long", "order_block_delta", "long", "order_block_entry_signal", "order_block_exit_reason", "chandelier"),
    StrategySpec("volume_profile_poc_long", "volume_profile_poc", "long", "volume_profile_poc_entry_signal", "volume_profile_poc_exit_reason", "chandelier"),
)}

# Mean-reversion / fade cells: a trend-direction filter contradicts them, so they are exempt.
EXEMPT_MEAN_REVERSION = {
    "failed_breakout_short": "fades a failed breakout (reversal)",
    "gap_up_fade_short": "fades a gap-up (mean reversion)",
    "range_vwap_mean_reversion": "RANGE-regime VWAP reversion",
}
# Not run here, flagged honestly.
OWED = {
    "idea4_long_short": "entry needs index_closes input; add once the driver loads the index series",
    "intraday_buy_short": "engines already take min_entry_confidence_pct; needs the 60d/5m replay driver (separate matrix)",
    "mcx_option_cells": "validated without any confidence filter; separate drivers",
    "multi_candle": "this pass is 1d bars only; SMA windows are bar counts, so other candle sizes are a separate sweep",
}


# ----------------------------- pure helpers -----------------------------

def fmt_param(x: float) -> str:
    return str(x).replace(".", "d")


def make_tag(spec: StrategySpec, threshold: int, sma_fast: int = SMA_FAST, sma_slow: int = SMA_SLOW) -> str:
    return (f"{spec.family}__confgate__{spec.direction}__1d__"
            f"cf{fmt_param(threshold)}_smaf{sma_fast}_smas{sma_slow}__v1")


def gate_passes(closes, direction: str, threshold_pct: float, tc, ma,
                sma_fast: int = SMA_FAST, sma_slow: int = SMA_SLOW, ma_type: str = MA_TYPE) -> bool:
    """Direction-aware trend-confidence gate. threshold 0 = no gate at all.
    tc/ma are main._trend_confidence / main._moving_average (injected so tests need no main)."""
    if threshold_pct <= 0:
        return True
    if len(closes) < sma_slow + 2:
        return False
    fast = ma(closes, sma_fast, ma_type)
    slow = ma(closes, sma_slow, ma_type)
    if direction == "long" and not fast > slow:
        return False
    if direction == "short" and not fast < slow:
        return False
    return tc(closes, sma_fast, sma_slow, ma_type) >= threshold_pct / 100.0


def shard_symbols(symbols, shard: int, nshards: int):
    syms = sorted(set(symbols))
    return [s for i, s in enumerate(syms) if i % nshards == shard]


def _zero():
    return {"n": 0, "wins": 0, "gw_net": 0.0, "gl_net": 0.0, "gw_gross": 0.0, "gl_gross": 0.0,
            "net_sum": 0.0, "held_sum": 0.0}


def _add(acc: dict, t: dict):
    acc["n"] += 1
    if t["net_pnl"] > 0:
        acc["wins"] += 1
        acc["gw_net"] += t["net_pnl"]
    else:
        acc["gl_net"] += -t["net_pnl"]
    if t["gross_pnl"] > 0:
        acc["gw_gross"] += t["gross_pnl"]
    else:
        acc["gl_gross"] += -t["gross_pnl"]
    acc["net_sum"] += t["net_pnl"]
    acc["held_sum"] += t["held_days"]


def _merge_acc(a: dict, b: dict):
    for k in a:
        a[k] += b.get(k, 0)


class Acc:
    """Mergeable per-threshold accumulator: pooled sums plus per-exit-reason sums."""

    def __init__(self):
        self.total = _zero()
        self.by_reason: dict[str, dict] = {}

    def add(self, t: dict):
        _add(self.total, t)
        _add(self.by_reason.setdefault(t["exit_reason"], _zero()), t)

    def merge_dict(self, d: dict):
        _merge_acc(self.total, d["total"])
        for r, v in d["by_reason"].items():
            _merge_acc(self.by_reason.setdefault(r, _zero()), v)

    def to_dict(self) -> dict:
        return {"total": self.total, "by_reason": self.by_reason}


def _ratio(num: float, den: float):
    if den > 0:
        return num / den
    return None if num <= 0 else float("inf")


def metrics_from_sums(s: dict) -> dict:
    n = s["n"]
    if not n:
        return {"n": 0, "win_rate_pct": 0.0, "pf_net": None, "pf_gross": None, "avg_net_inr": 0.0, "avg_held_days": 0.0}
    return {
        "n": n, "win_rate_pct": 100.0 * s["wins"] / n,
        "pf_net": _ratio(s["gw_net"], s["gl_net"]), "pf_gross": _ratio(s["gw_gross"], s["gl_gross"]),
        "avg_net_inr": s["net_sum"] / n, "avg_held_days": s["held_sum"] / n,
    }


def best_threshold_meeting_floor(rows: dict, floor: float):
    """rows: {threshold: metrics}. Highest threshold whose pf_net >= floor (derived at read time)."""
    ok = [t for t, m in rows.items() if m["pf_net"] is not None and m["pf_net"] >= floor and m["n"] > 0]
    return max(ok) if ok else None


# ----------------------------- costs / sizing -----------------------------

def _brokerage(notional, cm):
    return cm["brokerage_flat"] if cm["brokerage_pct"] == 0 and cm["brokerage_flat"] else notional * cm["brokerage_pct"]


def entry_cost(qty, price, cm):
    notional = qty * price
    b = _brokerage(notional, cm)
    exch, sebi = notional * cm["exchange_txn_pct"], notional * cm["sebi_fee_pct"]
    return (b + exch + sebi + notional * cm["stamp_duty_buy_pct"] + notional * cm["stt_buy_pct"]
            + (b + exch + sebi) * cm["gst_pct"] + notional * cm["slippage_pct"])


def sell_cost(qty, price, cm):
    notional = qty * price
    b = _brokerage(notional, cm)
    exch, sebi = notional * cm["exchange_txn_pct"], notional * cm["sebi_fee_pct"]
    return b + exch + sebi + notional * cm["stt_sell_pct"] + (b + exch + sebi) * cm["gst_pct"] + notional * cm["slippage_pct"]


def finalize_trade(direction, symbol, entry_price, qty, exit_price, exit_reason, e_cost, held_days, cm):
    gross = (exit_price - entry_price) * qty if direction == "long" else (entry_price - exit_price) * qty
    dp_once = cm["dp_charge_flat"] * (1 + cm["gst_pct"])
    total_cost = e_cost + sell_cost(qty, exit_price, cm) + dp_once
    return {"symbol": symbol, "exit_reason": exit_reason, "gross_pnl": gross,
            "net_pnl": gross - total_cost, "held_days": held_days}


# ----------------------------- replay -----------------------------

def replay_symbol(symbol, df, spec: StrategySpec, thresholds, risk_pct, capital, cm,
                  entry_fn, exit_fn, tc, ma, capital_tranches=2, min_lookback=260,
                  sma_fast=SMA_FAST, sma_slow=SMA_SLOW, ma_type=MA_TYPE):
    """Returns {threshold: [trade, ...]}. entry_fn/exit_fn are the real main.py functions."""
    import numpy as np
    out = {t: [] for t in thresholds}
    df = df.reset_index(drop=True)
    n = len(df)
    if n < min_lookback + 20:
        return out
    closes = df["Close"].to_numpy(dtype=float)
    dates = df["Date"].astype(str).to_numpy()
    sig_cache: dict[int, object] = {}

    def signal_at(i):
        if i not in sig_cache:
            sig_cache[i] = entry_fn(df.iloc[: i + 1])
        return sig_cache[i]

    for thr in thresholds:
        pos = None
        for i in range(min_lookback, n):
            sub = df.iloc[: i + 1]
            if pos is not None:
                if spec.exit_kind == "chandelier":
                    reason, pos["running"] = exit_fn(sub, pos["label"], pos["stop"], pos["atr"], pos["running"])
                else:
                    reason = exit_fn(sub, pos["label"], pos["stop"], pos["extra"])
                if reason:
                    out[thr].append(finalize_trade(spec.direction, symbol, pos["entry"], pos["qty"], closes[i],
                                                   reason, pos["cost"], i - pos["idx"], cm))
                    pos = None
            if pos is None:
                sig = signal_at(i)
                if sig is None:
                    continue
                if not gate_passes(closes[: i + 1], spec.direction, thr, tc, ma, sma_fast, sma_slow, ma_type):
                    continue
                entry, stop = sig["entry_price"], sig["stop_loss"]
                dist = (entry - stop) if spec.direction == "long" else (stop - entry)
                if dist <= 0:
                    continue
                usable = min(capital, capital / capital_tranches)
                qty = int(np.floor(min(usable * risk_pct / 100 / dist, usable / entry)))
                if qty > 0 and qty * entry >= 100:
                    pos = {"entry": entry, "stop": stop, "idx": i, "label": dates[i], "qty": qty,
                           "atr": sig.get("atr_at_entry"), "running": entry,
                           "extra": sig.get(spec.extra_key) if spec.extra_key else None,
                           "cost": entry_cost(qty, entry, cm)}
        if pos is not None:
            out[thr].append(finalize_trade(spec.direction, symbol, pos["entry"], pos["qty"], closes[-1],
                                           "data_end_forced_close", pos["cost"], (n - 1) - pos["idx"], cm))
    return out


def fetch_universe(symbols, period, interval, chunk_size=250):
    import pandas as pd
    import yfinance as yf
    out = {}
    for start in range(0, len(symbols), chunk_size):
        chunk = symbols[start:start + chunk_size]
        raw = yf.download(chunk, period=period, interval=interval, group_by="ticker",
                          threads=True, progress=False, auto_adjust=False)
        if raw.empty:
            continue
        if not isinstance(raw.columns, pd.MultiIndex):
            sub = raw.dropna(subset=["Open", "High", "Low", "Close"])
            if not sub.empty:
                sub = sub.reset_index()
                dc = "Date" if "Date" in sub.columns else "Datetime"
                out[chunk[0]] = sub.rename(columns={dc: "Date"}).reset_index(drop=True)
            continue
        top = set(raw.columns.get_level_values(0))
        for sym in chunk:
            if sym not in top:
                continue
            sub = raw[sym].dropna(subset=["Open", "High", "Low", "Close"])
            if sub.empty:
                continue
            sub = sub.reset_index()
            dc = "Date" if "Date" in sub.columns else "Datetime"
            out[sym] = sub.rename(columns={dc: "Date"}).reset_index(drop=True)
    return out


# ----------------------------- commands -----------------------------

def cmd_run(args):
    sys.path.insert(0, ".")
    import main as m
    spec = STRATEGIES[args.strategy]
    entry_fn, exit_fn = getattr(m, spec.entry_fn), getattr(m, spec.exit_fn)
    symbols = shard_symbols(m._load_nse_universe_from_file(), args.shard, args.nshards)
    if args.limit:
        symbols = symbols[: args.limit]
    print(f"strategy={spec.key} shard={args.shard}/{args.nshards} symbols={len(symbols)}")
    frames = fetch_universe(symbols, PERIOD, INTERVAL)
    frames = {s: d for s, d in frames.items() if len(d) >= 100}
    print(f"fetched {len(frames)}/{len(symbols)}")
    accs = {t: Acc() for t in THRESHOLDS}
    for sym, df in frames.items():
        cfg = m.NSE_STOCK_PARAM_OVERRIDES.get(sym, m.NSE_STOCK_DEFAULT_PARAMS)
        try:
            res = replay_symbol(sym, df, spec, THRESHOLDS, cfg["risk_pct"], CAPITAL_INR, DEFAULT_COST_MODEL,
                                entry_fn, exit_fn, m._trend_confidence, m._moving_average,
                                capital_tranches=m.CAPITAL_TRANCHES)
        except Exception as e:  # keep the shard alive; count errors
            print(f"ERROR {sym}: {e}")
            continue
        for thr, trades in res.items():
            for t in trades:
                accs[thr].add(t)
    payload = {"strategy": spec.key, "shard": args.shard, "nshards": args.nshards,
               "symbols_requested": len(symbols), "symbols_fetched": len(frames),
               "accs": {str(t): a.to_dict() for t, a in accs.items()}}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(payload, f)
    print(f"wrote {args.out}")


def cmd_merge(args):
    floor = None
    try:
        sys.path.insert(0, ".")
        import strategy_registry as sr
        floor = float(sr.PFNET_LIVE_FLOOR)
    except Exception:
        pass
    merged: dict[str, dict] = {}
    for path in args.inputs:
        with open(path) as f:
            p = json.load(f)
        slot = merged.setdefault(p["strategy"], {"accs": {}, "symbols_requested": 0, "symbols_fetched": 0, "shards": 0})
        slot["symbols_requested"] += p["symbols_requested"]
        slot["symbols_fetched"] += p["symbols_fetched"]
        slot["shards"] += 1
        for thr, d in p["accs"].items():
            slot["accs"].setdefault(thr, Acc()).merge_dict(d)
    result = {"cost_model": DEFAULT_COST_MODEL, "capital_inr": CAPITAL_INR, "period": PERIOD,
              "interval": INTERVAL, "sma_fast": SMA_FAST, "sma_slow": SMA_SLOW, "ma_type": MA_TYPE,
              "pfnet_floor_at_run_informational": floor,
              "exempt_mean_reversion": EXEMPT_MEAN_REVERSION, "owed": OWED, "strategies": {}}
    for key, slot in merged.items():
        spec = STRATEGIES[key]
        rows, cells = {}, []
        for thr_s, acc in sorted(slot["accs"].items(), key=lambda kv: int(kv[0])):
            thr = int(thr_s)
            met = metrics_from_sums(acc.total)
            rows[thr] = met
            cells.append({"tag": make_tag(spec, thr), "threshold": thr, **met,
                          "exit_reasons": {r: metrics_from_sums(v) for r, v in acc.by_reason.items()},
                          "raw_sums": acc.total})
        derived = {"best_threshold_meeting_floor": best_threshold_meeting_floor(rows, floor) if floor else None,
                   "baseline_pf_net": rows.get(0, {}).get("pf_net"),
                   "note": "derived at read time; raw sums per cell are the source of truth"}
        result["strategies"][key] = {"direction": spec.direction, "category": spec.category,
                                     "symbols_requested": slot["symbols_requested"],
                                     "symbols_fetched": slot["symbols_fetched"], "shards": slot["shards"],
                                     "cells": cells, "derived": derived}
    with open(args.out, "w") as f:
        json.dump(result, f, indent=1, default=lambda o: None if isinstance(o, float) and math.isinf(o) else str(o))
    print(json.dumps({k: v["derived"] for k, v in result["strategies"].items()}, indent=1))
    for key, v in result["strategies"].items():
        for c in v["cells"]:
            pf = "inf" if c["pf_net"] == float("inf") else (f"{c['pf_net']:.3f}" if c["pf_net"] is not None else "n/a")
            print(f"{c['tag']} n={c['n']} win={c['win_rate_pct']:.1f}% pf_net={pf} avg_hold={c['avg_held_days']:.1f}d")


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--strategy", required=True, choices=sorted(STRATEGIES))
    r.add_argument("--shard", type=int, default=0)
    r.add_argument("--nshards", type=int, default=1)
    r.add_argument("--limit", type=int, default=0, help="debug: cap symbols in this shard")
    r.add_argument("--out", required=True)
    r.set_defaults(fn=cmd_run)
    g = sub.add_parser("merge")
    g.add_argument("--inputs", nargs="+", required=True)
    g.add_argument("--out", required=True)
    g.set_defaults(fn=cmd_merge)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
