"""
Options pricing, contract selection, and the options-structure backtest
engine - Black-Scholes primitives, real-chain contract selection (via
yfinance), and the model-estimate multi-leg backtest.

Extracted from main.py as part of the docs/PROJECT_STRUCTURE_PLAN.md Phase 1
module split - pure code motion (bodies/docstrings unchanged from their
original main.py definitions), not a logic change. Every function here is
self-contained (no DB access, no FastAPI dependency) - verified by tracing
each one's actual dependencies before moving it, not assumed.
"""
import datetime as dt
import math

import numpy as np
import pandas as pd
import yfinance as yf

from constants import (
    OPTIONS_MIN_DTE, OPTIONS_MAX_DTE, OPTIONS_MAX_SPREAD_PCT,
    OPTIONS_TARGET_DELTA, OPTIONS_MAX_IV_VS_ATM,
)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Black-Scholes European option price. Falls back to intrinsic value at/after
    expiry or for degenerate (zero) vol."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0) if option_type == "C" else max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option_type == "C":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def parse_legs(legs_str: str) -> list[dict]:
    """Parses 'TYPE:ACTION:OFFSET,...' e.g. 'C:buy:0.0,C:sell:0.03'.
    TYPE: C=call, P=put, U=underlying (long only). OFFSET: strike = spot*(1+OFFSET)."""
    legs = []
    for part in legs_str.split(","):
        typ, action, offset = part.split(":")
        legs.append({"type": typ.strip().upper(), "action": action.strip().lower(), "offset": float(offset)})
    return legs


def run_options_backtest(
    df: pd.DataFrame, legs: list[dict], expiry_days: int, iv_mode: str, r: float, step_days: int
) -> dict:
    """Rolling-window backtest: every `step_days` trading days, opens the given
    multi-leg structure priced via Black-Scholes at that day's spot/vol, holds to
    `expiry_days` later, settles at intrinsic value against the actual historical
    close. This is a MODEL ESTIMATE (no historical options-chain data source is
    wired in) - useful for comparing strategy structures against real underlying
    price history, not a substitute for real fill/IV data."""
    closes = df["Close"].to_numpy(dtype=float)
    dates = df["Date"].apply(lambda d: d.isoformat()).to_numpy()
    n = len(closes)
    log_ret = np.diff(np.log(closes))
    T = expiry_days / 365.0

    def leg_strike(spot: float, leg: dict) -> float:
        return spot * (1 + leg["offset"])

    def classify_risk() -> str:
        has_underlying = any(l["type"] == "U" for l in legs)
        call_sells = [l for l in legs if l["type"] == "C" and l["action"] == "sell"]
        call_buys = [l for l in legs if l["type"] == "C" and l["action"] == "buy"]
        put_sells = [l for l in legs if l["type"] == "P" and l["action"] == "sell"]
        put_buys = [l for l in legs if l["type"] == "P" and l["action"] == "buy"]
        naked_calls = call_sells and not call_buys and not has_underlying
        naked_puts = put_sells and not put_buys
        covered_calls = call_sells and not call_buys and has_underlying and not put_buys
        if naked_calls or naked_puts:
            return "large/undefined (naked short exposure)"
        if covered_calls:
            return "large (covered by underlying - same downside as holding it outright)"
        return "defined/capped"

    def structure_pnl(spot_entry: float, spot_exit: float, sigma: float, entry_cf: float) -> float:
        expiry_cf, underlying_pnl = 0.0, 0.0
        for leg in legs:
            if leg["type"] == "U":
                underlying_pnl += spot_exit - spot_entry
                continue
            K = leg_strike(spot_entry, leg)
            payoff = max(spot_exit - K, 0.0) if leg["type"] == "C" else max(K - spot_exit, 0.0)
            expiry_cf += -payoff if leg["action"] == "sell" else payoff
        return entry_cf + expiry_cf + underlying_pnl

    trades = []
    i = 60
    while i + expiry_days < n:
        S0 = float(closes[i])
        if iv_mode == "realized":
            window = log_ret[max(0, i - 20): i]
            sigma = float(np.std(window) * math.sqrt(252)) if len(window) > 5 else 0.14
            sigma = max(sigma, 0.05)
        else:
            sigma = 0.14

        entry_cf = 0.0
        for leg in legs:
            if leg["type"] == "U":
                continue
            K = leg_strike(S0, leg)
            premium = bs_price(S0, K, T, r, sigma, leg["type"])
            entry_cf += premium if leg["action"] == "sell" else -premium

        ST = float(closes[i + expiry_days])
        pnl = structure_pnl(S0, ST, sigma, entry_cf)
        trades.append({
            "entry_date": str(dates[i]),
            "entry_spot": round(S0, 2),
            "expiry_date": str(dates[i + expiry_days]),
            "expiry_spot": round(ST, 2),
            "iv_used_pct": round(sigma * 100, 2),
            "pnl_points": round(pnl, 2),
        })
        i += step_days

    if not trades:
        return {"trades": [], "summary": None}

    pnls = np.array([t["pnl_points"] for t in trades])
    equity = np.cumsum(pnls)
    max_dd = float((equity - np.maximum.accumulate(equity)).min())

    # Crude worst-case risk proxy: reprice the same structure at the last entry
    # spot/flat-IV and evaluate payoff at extreme moves (halved / doubled spot).
    S0_ref = float(closes[max(i - step_days, 0)])
    entry_cf_ref = 0.0
    for leg in legs:
        if leg["type"] == "U":
            continue
        K = leg_strike(S0_ref, leg)
        entry_cf_ref += bs_price(S0_ref, K, T, r, 0.14, leg["type"]) * (1 if leg["action"] == "sell" else -1)
    worst = min(
        structure_pnl(S0_ref, S0_ref * 0.5, 0.14, entry_cf_ref),
        structure_pnl(S0_ref, S0_ref * 2.0, 0.14, entry_cf_ref),
    )

    summary = {
        "trades_count": len(trades),
        "win_rate_pct": round(100 * float((pnls > 0).mean()), 1),
        "avg_pnl_points": round(float(pnls.mean()), 2),
        "total_pnl_points": round(float(pnls.sum()), 2),
        "max_drawdown_points": round(max_dd, 2),
        "best_trade_points": round(float(pnls.max()), 2),
        "worst_trade_points": round(float(pnls.min()), 2),
        "max_loss_proxy_points": round(float(worst), 2),
        "risk": classify_risk(),
    }
    return {"trades": trades[-3:], "summary": summary}


def _bs_delta(spot: float, strike: float, iv: float, dte_years: float, right: str, r: float = 0.05):
    """Black-Scholes delta from the chain's own quoted IV - yfinance doesn't
    return delta directly, and this is the standard way to derive it (no
    scipy dependency needed; math.erf gives the normal CDF)."""
    if spot <= 0 or strike <= 0 or iv <= 0 or dte_years <= 0:
        return None
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * dte_years) / (iv * math.sqrt(dte_years))
    nd1 = _norm_cdf(d1)
    return nd1 if right == "call" else nd1 - 1.0


def select_option_contract(underlying: str, spot: float, right: str):
    """Picks one real, currently-quoted contract from yfinance's live chain.
    See the module docstring above for the strike/expiry/IV rules. Returns
    (contract_dict, None) on success or (None, reason_str) - never invents a
    contract; a chain fetch failure or no qualifying line is reported, not
    silently defaulted."""
    try:
        t = yf.Ticker(underlying)
        expiries = t.options
    except Exception as e:
        return None, f"options_chain_error: {e}"
    if not expiries:
        return None, "no_expiries_listed"

    now = dt.datetime.utcnow()
    in_range = []
    all_dtes = []
    for exp in expiries:
        dte = (dt.datetime.strptime(exp, "%Y-%m-%d") - now).days
        all_dtes.append((exp, dte))
        if OPTIONS_MIN_DTE <= dte <= OPTIONS_MAX_DTE:
            in_range.append((exp, dte))
    if in_range:
        expiry, dte = min(in_range, key=lambda c: c[1])
    else:
        # No expiry in the preferred window - fall back to the nearest one
        # that's still past OPTIONS_MIN_DTE (never 0-1 DTE) rather than
        # refusing to trade a symbol just because this week's calendar is odd.
        beyond = [c for c in all_dtes if c[1] >= OPTIONS_MIN_DTE]
        if not beyond:
            return None, "no_expiry_beyond_min_dte"
        expiry, dte = min(beyond, key=lambda c: c[1])
    dte_years = max(dte, 1) / 365.0

    try:
        chain = t.option_chain(expiry)
    except Exception as e:
        return None, f"chain_fetch_error: {e}"
    book = chain.calls if right == "call" else chain.puts
    if book is None or book.empty:
        return None, "empty_chain"

    book = book.copy()
    book["dist_to_atm"] = (book["strike"] - spot).abs()
    atm_row = book.loc[book["dist_to_atm"].idxmin()]
    atm_iv = float(atm_row["impliedVolatility"]) if atm_row["impliedVolatility"] and atm_row["impliedVolatility"] > 0 else None

    best = None  # (delta_dist, row, iv, delta)
    for _, row in book.iterrows():
        iv = float(row["impliedVolatility"]) if row["impliedVolatility"] else 0.0
        bid = float(row["bid"]) if row["bid"] else 0.0
        ask = float(row["ask"]) if row["ask"] else 0.0
        if iv <= 0 or bid <= 0 or ask <= 0:
            continue
        if (ask - bid) / ask * 100 > OPTIONS_MAX_SPREAD_PCT:
            continue
        delta = _bs_delta(spot, float(row["strike"]), iv, dte_years, right)
        if delta is None:
            continue
        delta_dist = abs(abs(delta) - OPTIONS_TARGET_DELTA)
        if best is None or delta_dist < best[0]:
            best = (delta_dist, row, iv, delta)

    if best is None:
        return None, "no_liquid_contract_near_target_delta"

    _, row, iv, delta = best
    if atm_iv and iv > atm_iv * OPTIONS_MAX_IV_VS_ATM:
        return None, f"iv_too_rich_vs_atm ({iv:.2f} vs atm {atm_iv:.2f})"

    mid = (float(row["bid"]) + float(row["ask"])) / 2.0
    return {
        "underlying": underlying, "right": right, "expiry": expiry, "dte": dte,
        "strike": float(row["strike"]), "premium": round(mid, 4),
        "bid": float(row["bid"]), "ask": float(row["ask"]),
        "iv": round(iv, 4), "atm_iv": round(atm_iv, 4) if atm_iv else None,
        "delta": round(delta, 3), "open_interest": int(row.get("openInterest") or 0),
        "volume": int(row.get("volume") or 0),
    }, None


def _requote_contract(underlying: str, expiry: str, strike: float, right: str):
    """Re-fetches the live bid/ask for one already-open contract, to mark an
    open option position to a real quote (not the entry price) when checking
    stop/target. Returns mid price or None if the chain can't be fetched or
    the strike is no longer listed (e.g. past expiry)."""
    try:
        t = yf.Ticker(underlying)
        chain = t.option_chain(expiry)
    except Exception:
        return None
    book = chain.calls if right == "call" else chain.puts
    if book is None or book.empty:
        return None
    match = book[(book["strike"] - strike).abs() < 0.01]
    if match.empty:
        return None
    row = match.iloc[0]
    bid, ask = float(row["bid"] or 0), float(row["ask"] or 0)
    if bid <= 0 or ask <= 0:
        return None
    return round((bid + ask) / 2.0, 4)
