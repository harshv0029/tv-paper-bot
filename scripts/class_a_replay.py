"""Class-A replay harness: viable-but-unwired strategies that reuse EXISTING main.py functions with
variant parameters. One script, three modes (env MODE), all on the FULL universe
(main._load_nse_universe_from_file()), round-trip cost main.ROUND_TRIP_COST_PCT (0.8%), a stop-loss
on EVERY trade (cells registered as 'atrnone' are refused: the no-trade-without-SL rule), and every
metric printed + written to out/class_a_<mode>_<name>.json (nothing trimmed; viability is derived
later from these raw fields, never stored as a flag).

  MODE=plan         print the job matrix (JSON), derived from strategy_registry at dispatch time:
                    viable (PFnet >= PFNET_LIVE_FLOOR) AND not scan-wired (tag absent from
                    main._STRATEGY_TAG_TO_REGISTRY_NAME values) sector_rotation fade-short 1d cells and
                    minervini_vcp variants. Never a stored flag.
  MODE=sector_short sector_rotation fade SHORT mirror. Picks = REAL main.sector_rotation_picks with
                    SECTOR_ROT_L / SECTOR_ROT_N overridden on the main module (strongest-breadth sector's
                    top-N by L-day return; the fade SHORT shorts exactly those names, see
                    scripts/sector_rotation_backtest.py FADE=1). Sector map = docs/sector_map.json (what
                    main reads). ATR = REAL main._atr_series(df, 14). The short EXIT is NOT in main.py
                    (main.sector_rotation_exit_reason is long-only, close-based): the harness simulates
                    the backtest's fixed ATR stop above entry + time exit and reports THREE stop-fill
                    models side by side: 'stop' (fills at the stop price = how the registry numbers were
                    produced), 'gap_aware' (fills at max(stop, open) on a gap through it) and 'close'
                    (stop evaluated on the close, the way main's live exit fn would). Env CELLS =
                    "atr1d5_h20_l5_n1,atr2d5_h10_l3_n1" (naming-grammar params), TF=1d only (4h/intraday owed).
  MODE=minervini_be REAL main.minervini_vcp_entry_signal + REAL main.minervini_vcp_exit_reason_breakeven
                    with breakeven_r_multiple = env BE_R (2 or 3). RS gate skipped (None), as b412 does.
  MODE=minervini_lab one of the viable minervini_vcp lab variants (env VARIANT), delegated to
                    scripts/b412_replay.run_lab (entries real, native stops ported: not in main.py).

Env: SYMBOL_LIMIT (smoke), SYNTHETIC=1 (offline generated frames; NOT a result).
Convention shared with the other replays: signal at close of bar t, entry at bar t+1 open (sector) /
signal close (minervini), one open position per symbol (minervini); sector signals are independent
overlapping trades (PF is per trade), same as the registry run.
"""
import json
import os
import re
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import b412_helpers as H  # noqa: E402

SECTOR_TAG_RE = re.compile(r"^sector_rotation__fade__short__(?P<tf>[a-z0-9]+)__atr(?P<atr>[a-z0-9]+)_h(?P<h>\d+)_l(?P<l>\d+)_n(?P<n>\d+)__v1$")
STOP_FILLS = ("stop", "gap_aware", "close")


# ------------------------------------------------------------------ pure helpers (tested offline)
def parse_atr(tok):
    """Naming grammar: '1d5' -> 1.5, '6d0' -> 6.0, 'none' -> None."""
    return None if tok == "none" else float(tok.replace("d", "."))


def parse_sector_tag(tag):
    m = SECTOR_TAG_RE.match(tag)
    if not m:
        return None
    return {"tf": m["tf"], "atr": parse_atr(m["atr"]), "atr_tok": m["atr"], "hold": int(m["h"]),
            "L": int(m["l"]), "N": int(m["n"]), "tag": tag}


def cell_token(c):
    return f"atr{c['atr_tok']}_h{c['hold']}_l{c['L']}_n{c['N']}"


def parse_cells(spec):
    """'atr1d5_h20_l5_n1,atr2d5_h10_l3_n1' -> cell dicts. Refuses atrnone (no trade without a stop)."""
    cells = []
    for tok in [t for t in spec.split(",") if t.strip()]:
        c = parse_sector_tag(f"sector_rotation__fade__short__1d__{tok.strip()}__v1")
        if c is None:
            raise ValueError(f"bad cell {tok!r}")
        if c["atr"] is None:
            raise ValueError(f"cell {tok!r} has no stop (atrnone): refused, no trade without SL")
        cells.append(c)
    return cells


def short_trade(O, H_, L_, C, e, ent, stop, hold, fill):
    """Simulate one SHORT from entry bar e (open price ent) with a fixed stop ABOVE entry and a time
    exit at the close of bar e+hold-1. Returns (exit_price, held_bars, reason) or None if the window
    runs past the data. fill in STOP_FILLS."""
    if e + hold > len(C):
        return None
    for q in range(hold):
        t = e + q
        if fill == "close":
            if C[t] >= stop:
                return C[t], q + 1, "stop_hit"
        elif H_[t] >= stop:
            px = stop if fill == "stop" else max(stop, O[t])
            return px, q + 1, "stop_hit"
    px = C[e + hold - 1]
    return (px, hold, "max_hold_timeout") if not np.isnan(px) else None


def trade_record(ent, px, held, reason, cost, direction="short"):
    g = (1 - px / ent) if direction == "short" else (px / ent - 1)
    return {"gross": g, "net": g - cost, "held": held, "reason": reason}


class _Col:
    __slots__ = ("a",)

    def __init__(self, a):
        self.a = a

    def to_numpy(self, dtype=float):
        return self.a


class _View:
    """Cheap stand-in for a DataFrame prefix: main.sector_rotation_picks only needs len(df) and
    df['Close'].to_numpy(). Lets the REAL function run on every day without re-slicing 1900 frames."""
    __slots__ = ("c",)

    def __init__(self, c):
        self.c = c

    def __len__(self):
        return len(self.c)

    def __getitem__(self, k):
        assert k == "Close"
        return _Col(self.c)


def synthetic_frame(seed, n=700):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0006, 0.017, n)
    c = 100 * np.exp(np.cumsum(r))
    o = c * (1 + rng.normal(0, 0.004, n))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.006, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.006, n)))
    v = rng.integers(1e5, 1e6, n).astype(float)
    d = pd.bdate_range("2021-01-01", periods=n)
    return pd.DataFrame({"Date": d.strftime("%Y-%m-%d"), "Open": o, "High": hi, "Low": lo, "Close": c, "Volume": v})


# ------------------------------------------------------------------ plan
def build_plan(registry, wired_names):
    """Matrix from the registry: viable now (derived), not wired. Sector cells with a stop on 1d are
    grouped per (L, N) so one job computes the real picks once. Skipped cells are listed, not dropped."""
    groups, skipped = {}, []
    inc = []
    for s in registry:
        n = s.name
        if s.is_viable() is not True or n in wired_names:
            continue
        if n.startswith("sector_rotation__fade__short__"):
            c = parse_sector_tag(n)
            if c is None or c["tf"] != "1d" or c["atr"] is None:
                skipped.append({"tag": n, "why": "non-1d (resample/intraday owed)" if c and c["tf"] != "1d" else "no stop (atrnone) or unparsable"})
                continue
            groups.setdefault((c["L"], c["N"]), []).append(cell_token(c))
        elif n.startswith("minervini_vcp__") and n.endswith("__long__1d__h60__v1"):
            inc.append({"mode": "minervini_lab", "name": n[len("minervini_vcp__"):-len("__long__1d__h60__v1")]})
        elif n == "minervini_vcp_breakeven_2r":
            inc.append({"mode": "minervini_be", "name": "2"})
    for (L, N), toks in sorted(groups.items()):
        inc.insert(0, {"mode": "sector_short", "name": f"l{L}_n{N}", "cells": ",".join(sorted(toks))})
    return {"include": inc, "skipped": skipped}


# ------------------------------------------------------------------ data
def load_frames(m, limit=None):
    if os.environ.get("SYNTHETIC") == "1":
        return {f"SYN{k}": synthetic_frame(k) for k in range(limit or 8)}
    syms = sorted(set(m._load_nse_universe_from_file()))
    if limit:
        syms = syms[:limit]
    out = {}
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, "5y", "1d")
        except Exception:
            continue
        if raw is None or len(raw) < 260:
            continue
        out[s] = raw.reset_index(drop=True)
    return out


# ------------------------------------------------------------------ sector short
def build_panel(m, frames):
    """Union-date panels (T x S) of O/H/L/C and ATR14 from the real main._atr_series per symbol."""
    syms = sorted(frames)
    dates = sorted(set().union(*[set(f["Date"].astype(str)) for f in frames.values()]))
    ix = {d: i for i, d in enumerate(dates)}
    T, S = len(dates), len(syms)
    P = {k: np.full((T, S), np.nan) for k in ("O", "H", "L", "C", "ATR")}
    for j, s in enumerate(syms):
        f = frames[s]
        rows = np.array([ix[d] for d in f["Date"].astype(str)])
        for k, col in (("O", "Open"), ("H", "High"), ("L", "Low"), ("C", "Close")):
            P[k][rows, j] = f[col].to_numpy(float)
        P["ATR"][rows, j] = m._atr_series(f, 14).to_numpy(float)
    return syms, dates, P


def run_sector_short(m, frames, cells):
    sector_map = m._sector_of_symbol()
    frames = {s: f for s, f in frames.items() if sector_map.get(s)}
    syms, dates, P = build_panel(m, frames)
    O, H_, L_, C, ATR = P["O"], P["H"], P["L"], P["C"], P["ATR"]
    T = len(dates)
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    by_ln = {}
    for c in cells:
        by_ln.setdefault((c["L"], c["N"]), []).append(c)
    saved = (m.SECTOR_ROT_L, m.SECTOR_ROT_N)
    results = {}
    try:
        for (L, N), group in by_ln.items():
            m.SECTOR_ROT_L, m.SECTOR_ROT_N = L, N  # override on the module: the real function reads them fresh
            sigs = []
            for t in range(L + 15, T - 2):
                dfs = {s: _View(C[:t + 1, j]) for j, s in enumerate(syms)}
                for s in m.sector_rotation_fade_short_picks(dfs, L, N):
                    sigs.append((t, syms.index(s)))
            for c in group:
                per_fill = {f: [] for f in STOP_FILLS}
                for t, j in sigs:
                    e = t + 1
                    ent, a = O[e, j], ATR[t, j]
                    if np.isnan(ent) or np.isnan(a) or ent <= 0:
                        continue
                    stop = m.sector_rotation_fade_short_stop(ent, a, c["atr"])  # REAL main stop; None = no entry (SL on every trade)
                    if stop is None or e + c["hold"] > T:
                        continue
                    win = pd.DataFrame({"Open": O[e:e + c["hold"], j], "High": H_[e:e + c["hold"], j],
                                        "Close": C[e:e + c["hold"], j]})
                    for f in STOP_FILLS:
                        r = m.sector_rotation_fade_short_exit_reason(win, stop, c["hold"], f)  # REAL main exit
                        r = (r[1], r[2], r[0]) if r else None
                        if r:
                            per_fill[f].append(trade_record(ent, r[0], r[1], r[2], cost))
                results[c["tag"]] = {"cell": cell_token(c), "n_signals": len(sigs),
                                     "by_stop_fill": {f: H.metrics(per_fill[f]) for f in STOP_FILLS}}
    finally:
        m.SECTOR_ROT_L, m.SECTOR_ROT_N = saved
    return {"mode": "sector_short", "cells": results, "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT,
            "universe_size": len(frames), "universe_requested": "main._load_nse_universe_from_file()",
            "bars": T, "tf": "1d", "picks_source": "main.sector_rotation_fade_short_picks (real)",
            "atr_source": "main._atr_series (real)",
            "exit_source": "main.sector_rotation_fade_short_exit_reason + sector_rotation_fade_short_stop (real)"}


# ------------------------------------------------------------------ minervini breakeven (real fns)
def replay_minervini_be(m, df, be_r, cost):
    df = df.reset_index(drop=True)
    n = len(df)
    closes = df["Close"].to_numpy(float)
    dates = df["Date"].astype(str).to_numpy()
    out, pos = [], None
    for i in range(260, n):
        sub = df.iloc[:i + 1]
        if pos is not None:
            reason, pos["rmc"] = m.minervini_vcp_exit_reason_breakeven(
                sub, pos["day"], pos["stop0"], pos["atr"], pos["rmc"], pos["ep"], be_r)
            if reason:
                out.append(trade_record(pos["ep"], closes[i], i - pos["idx"], reason, cost, "long"))
                pos = None
        if pos is None:
            sig = m.minervini_vcp_entry_signal(sub, None)
            if sig and sig["entry_price"] > sig["stop_loss"] > 0:  # SL on every trade
                pos = {"ep": sig["entry_price"], "stop0": sig["stop_loss"], "day": dates[i], "idx": i,
                       "atr": sig.get("atr_at_entry") or 0.0, "rmc": sig["entry_price"]}
    if pos is not None:
        out.append(trade_record(pos["ep"], closes[-1], n - 1 - pos["idx"], "data_end_forced_close", cost, "long"))
    return out


def run_minervini_be(m, frames, be_r):
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    trades = []
    for s, df in frames.items():
        if len(df) < 280:
            continue
        try:
            trades.extend(replay_minervini_be(m, df, be_r, cost))
        except Exception as ex:
            print("ERROR", s, ex)
    return {"mode": "minervini_be", "be_r": be_r, "metrics": H.metrics(trades),
            "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT, "universe_size": len(frames),
            "entry_source": "main.minervini_vcp_entry_signal (real, RS gate skipped)",
            "exit_source": "main.minervini_vcp_exit_reason_breakeven (real)",
            "constants": {"MINERVINI_MAX_HOLD_DAYS": m.MINERVINI_MAX_HOLD_DAYS}}


def main_run():
    mode = os.environ["MODE"]
    if mode == "plan":
        import main as m
        import strategy_registry as r
        plan = build_plan(r.REGISTRY, set(m._STRATEGY_TAG_TO_REGISTRY_NAME.values()))
        print(f"skipped (listed, not dropped): {json.dumps(plan['skipped'])}", file=sys.stderr)
        print(json.dumps({"include": plan["include"]}))
        return
    import main as m
    lim = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    frames = load_frames(m, lim)
    print(f"{mode}: {len(frames)} symbols (requested universe = main._load_nse_universe_from_file())")
    if mode == "sector_short":
        res = run_sector_short(m, frames, parse_cells(os.environ["CELLS"]))
        name = os.environ.get("NAME", "sector")
    elif mode == "minervini_be":
        res = run_minervini_be(m, frames, float(os.environ["BE_R"]))
        name = f"be{os.environ['BE_R']}"
    elif mode == "minervini_lab":
        import b412_replay
        res, name = b412_replay.run_lab(m, os.environ["VARIANT"], frames), os.environ["VARIANT"]
    else:
        raise SystemExit(f"unknown MODE {mode}")
    res["synthetic"] = os.environ.get("SYNTHETIC") == "1"
    os.makedirs("out", exist_ok=True)
    json.dump(res, open(f"out/class_a_{mode}_{name}.json", "w"), indent=1, default=str)
    print(json.dumps(res, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main_run()
