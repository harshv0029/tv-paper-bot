"""B-412 replay driver. Two modes (env MODE):

  be1r : breakeven-at-1R stop variants of the viable swing strategies. ENTRY and EXIT decisions come from
         the REAL main.py functions (entry signal + exit_reason fn); the only addition is the ratchet: the
         `stop` argument handed to the real exit fn is b412_helpers.ratcheted_stop(...) (max(stop0, entry)
         once the peak close >= entry + BE_R * R; mirrored for shorts). Each job also replays the SAME
         strategy with no ratchet (baseline) so the two are directly comparable.
         STRAT in: minervini_long, minervini_short, ob_long, vp_long, gap_long, gap_short.
  lab  : one of the 30 viable minervini_vcp lab variants (env VARIANT, e.g. pct8_hard,
         pct8_hard_f_ext_le5_on). Entries = REAL main.minervini_vcp_entry_signal (RS gate skipped, as the
         lab did); exits/native stops = scripts/b412_helpers.simulate_lab_exit, a faithful port of the lab
         (these stops do NOT exist in main.py, so they cannot be called from it; B-412 porting is still owed).

Universe = main._load_nse_universe_from_file() (full). Output out/<name>.json with every metric.
Costs: main.ROUND_TRIP_COST_PCT/100 per trade (same as the lab) for both modes.
Env: SYMBOL_LIMIT (smoke test), SYNTHETIC=1 (offline smoke test on generated frames, NOT a result).
"""
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import b412_helpers as H  # noqa: E402

BE_R = 1.0


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


def load_frames(m, limit=None):
    if os.environ.get("SYNTHETIC") == "1":
        return {f"SYN{k}": synthetic_frame(k) for k in range(limit or 5)}
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


# ---------------------------------------------------------------- be1r mode
def strat_spec(m, name):
    """-> dict(direction, entry, exit, kind, min_bars, win, extra_key)."""
    if name == "minervini_long":
        return dict(direction="long", entry=lambda d: m.minervini_vcp_entry_signal(d, None), exit=m.minervini_vcp_exit_reason,
                    kind="trail", min_bars=260, win=None, family="minervini_vcp", variant="swing")
    if name == "minervini_short":
        return dict(direction="short", entry=m.minervini_vcp_entry_signal_short, exit=m.minervini_vcp_exit_reason_short,
                    kind="trail", min_bars=260, win=None, family="minervini_vcp", variant="swing")
    if name == "ob_long":
        return dict(direction="long", entry=m.order_block_entry_signal, exit=m.order_block_exit_reason, kind="trail",
                    min_bars=m.ORDER_BLOCK_MIN_LOOKBACK_DAYS, win=150, family="order_block_delta", variant="retest")
    if name == "vp_long":
        return dict(direction="long", entry=m.volume_profile_poc_entry_signal, exit=m.volume_profile_poc_exit_reason,
                    kind="trail", min_bars=m.VP_MIN_LOOKBACK_DAYS, win=150, family="volume_profile_poc", variant="swing")
    if name == "gap_long":
        return dict(direction="long", entry=m.gap_and_go_entry_signal, exit=m.gap_and_go_exit_reason, kind="gap_long",
                    min_bars=40, win=None, family="gap_and_go", variant="swing")
    if name == "gap_short":
        return dict(direction="short", entry=m.gap_and_go_entry_signal_short, exit=m.gap_and_go_exit_reason_short,
                    kind="gap_short", min_bars=40, win=None, family="gap_and_go", variant="swing")
    raise ValueError(name)


def replay_be(spec, df, cost, be_r):
    """One symbol, one position at a time, entry at signal close, exit at the close of the exit bar
    (same convention as the existing validation replays). be_r=None -> baseline (no ratchet)."""
    long_ = spec["direction"] == "long"
    df = df.reset_index(drop=True)
    n = len(df)
    closes = df["Close"].to_numpy(float)
    dates = df["Date"].astype(str).to_numpy()
    out, pos = [], None
    for i in range(spec["min_bars"], n):
        sub = df.iloc[max(0, i + 1 - spec["win"]):i + 1] if spec["win"] else df.iloc[:i + 1]
        if pos is not None:
            stop = pos["stop0"] if be_r is None else H.ratcheted_stop(
                pos["ep"], pos["stop0"], pos["ext"], be_r, spec["direction"])
            if spec["kind"] == "trail":
                reason, pos["ext"] = spec["exit"](sub, pos["day"], stop, pos["atr"], pos["ext"])
            else:
                reason = spec["exit"](sub, pos["day"], stop, pos["gap"])
                pos["ext"] = max(pos["ext"], closes[i]) if long_ else min(pos["ext"], closes[i])
            if reason:
                g = (closes[i] / pos["ep"] - 1) if long_ else (1 - closes[i] / pos["ep"])
                out.append({"gross": g, "net": g - cost, "held": i - pos["idx"], "reason": reason})
                pos = None
        if pos is None:
            sig = spec["entry"](sub)
            if sig and abs(sig["entry_price"] - sig["stop_loss"]) > 0 and (
                    (sig["entry_price"] > sig["stop_loss"]) == long_):
                pos = {"ep": sig["entry_price"], "stop0": sig["stop_loss"], "day": dates[i], "idx": i,
                       "ext": sig["entry_price"], "atr": sig.get("atr_at_entry"),
                       "gap": sig.get("gap_low", sig.get("gap_high"))}
    if pos is not None:
        g = (closes[-1] / pos["ep"] - 1) if long_ else (1 - closes[-1] / pos["ep"])
        out.append({"gross": g, "net": g - cost, "held": (n - 1) - pos["idx"], "reason": "data_end_forced_close"})
    return out


def run_be(m, name, frames):
    spec = strat_spec(m, name)
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    res = {}
    for label, be in (("baseline", None), ("be", BE_R)):
        trades = []
        for s, df in frames.items():
            if len(df) < spec["min_bars"] + 20:
                continue
            try:
                trades.extend(replay_be(spec, df, cost, be))
            except Exception as ex:
                print("ERROR", s, ex)
        res[label] = H.metrics(trades)
    tag_be = H.be_tag(spec["family"], spec["variant"], spec["direction"], BE_R)
    tag_base = f"{spec['family']}__{spec['variant']}__{spec['direction']}__1d__benone__v1"
    return {"strat": name, "direction": spec["direction"], "tag_be": tag_be, "tag_baseline": tag_base,
            "baseline": res["baseline"], "be": res["be"], "be_r": BE_R,
            "constants": {k: getattr(m, k) for k in ("ORDER_BLOCK_ATR_TRAIL_MULT", "VP_ATR_TRAIL_MULT",
                                                     "MINERVINI_ATR_STOP_MULT", "MINERVINI_MAX_HOLD_DAYS") if hasattr(m, k)},
            "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT, "n_symbols": len(frames),
            "synthetic": os.environ.get("SYNTHETIC") == "1"}


# ---------------------------------------------------------------- lab mode
def lab_signals(m, df):
    c = df["Close"].to_numpy(float)
    ma50 = H.sma(c, 50)
    out, last = [], -10
    for i in range(210, len(df) - 2):
        if not (c[i] > ma50[i]) or i - last < 5:
            continue
        try:
            sig = m.minervini_vcp_entry_signal(df.iloc[:i + 1], None)
        except Exception:
            sig = None
        if sig:
            out.append((i, sig["entry_price"], sig["stop_loss"], sig["atr_at_entry"]))
            last = i
    return out


def run_lab(m, variant, frames):
    import minervini_lab as lab  # features() lives in the lab; imported, not copied
    ex, feat, flag = H.parse_lab_variant(variant)
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    idx_close = None
    rs_rank = None
    nhnl_ok = None
    if feat:
        closes = pd.DataFrame({s: f.set_index(pd.DatetimeIndex(f["Date"]))["Close"] for s, f in frames.items()})
        highs = pd.DataFrame({s: f.set_index(pd.DatetimeIndex(f["Date"]))["High"] for s, f in frames.items()})
        lows = pd.DataFrame({s: f.set_index(pd.DatetimeIndex(f["Date"]))["Low"] for s, f in frames.items()})
        blend = (0.4 * (closes / closes.shift(63) - 1) + 0.2 * (closes / closes.shift(126) - 1)
                 + 0.2 * (closes / closes.shift(189) - 1) + 0.2 * (closes / closes.shift(252) - 1))
        rs_rank = blend.rank(axis=1, pct=True) * 100
        nh = (highs >= highs.rolling(252, min_periods=200).max()).sum(axis=1)
        nl = (lows <= lows.rolling(252, min_periods=200).min()).sum(axis=1)
        nhnl_ok = ((nh / (nh + nl).replace(0, np.nan)) >= 0.6).fillna(False)
        if os.environ.get("SYNTHETIC") != "1":
            import yfinance as yf
            ix = yf.download("^NSEI", period="6y", interval="1d", auto_adjust=True, progress=False)
            if isinstance(ix.columns, pd.MultiIndex):
                ix.columns = ix.columns.get_level_values(0)
            idx_close = ix["Close"].dropna()
            idx_close.index = pd.DatetimeIndex(idx_close.index).tz_localize(None)
        else:
            idx_close = closes.mean(axis=1)
    trades = []
    for s, df in frames.items():
        df = df.copy()
        df.index = pd.DatetimeIndex(df["Date"])
        sigs = lab_signals(m, df)
        if not sigs:
            continue
        o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
        if feat:
            idx_arr = idx_close.reindex(df.index, method="ffill").to_numpy(float)
            rs_arr = rs_rank[s].reindex(df.index).to_numpy(float)
            nn_arr = nhnl_ok.reindex(df.index).fillna(False).to_numpy(bool)
        for sg in sigs:
            if feat:
                i = sg[0]
                try:
                    ft = lab.features(df, i, idx_arr, None if np.isnan(rs_arr[i]) else rs_arr[i], nn_arr[i])
                except Exception:
                    continue
                if feat not in ft or (bool(ft[feat]) != (flag == "on")):
                    continue
            r = H.simulate_lab_exit(ex, o, h, l, c, sg, cost, lab.MAXH)
            if r:
                trades.append({"gross": r[0] + cost, "net": r[0], "held": r[1], "reason": r[2]})
    return {"variant": variant, "tag_lab_v1": H.lab_tag(variant), "tag_replay_v2": H.lab_tag_replay(variant),
            "metrics": H.metrics(trades), "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT, "n_symbols": len(frames),
            "exit_source": "ported from scripts/minervini_lab.py (not in main.py)",
            "entry_source": "main.minervini_vcp_entry_signal (real)", "synthetic": os.environ.get("SYNTHETIC") == "1"}


def main_run():
    import main as m
    mode = os.environ["MODE"]
    lim = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    frames = load_frames(m, lim)
    print(f"{mode}: {len(frames)} symbols")
    if mode == "be1r":
        res, name = run_be(m, os.environ["STRAT"], frames), os.environ["STRAT"]
    else:
        res, name = run_lab(m, os.environ["VARIANT"], frames), os.environ["VARIANT"]
    os.makedirs("out", exist_ok=True)
    json.dump(res, open(f"out/{mode}_{name}.json", "w"), indent=1)
    print(json.dumps(res, indent=1)[:1500])


if __name__ == "__main__":
    main_run()
