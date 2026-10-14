"""Offline implied-volatility and Greeks calculator (B-756 compute step, B-1170).

Pure functions, no network, no DB, no main.py import. Black-Scholes European model with a stated
risk-free rate assumption of 6.5% (RISK_FREE_RATE); NSE index options are European, stock options
are physically settled and American-style in practice, so stock-option IV here is an approximation
(flagged in the output as model="bs_european"). Cross-check against NSE chain IV is a separate
owed step (needs a runner-side fetch, see docs/DISPATCH_PLAN.md B-754/B-755).

Raw inputs are never mutated; callers store the result beside the premium and derive signals at
read time (CLAUDE.md: keep all data intact).

Usage as a library:
    from scripts.option_greeks import implied_vol, greeks, enrich_row
"""
import math

RISK_FREE_RATE = 0.065  # stated assumption (INR ~ 6.5%); override per call
MODEL = "bs_european"
_IV_LO, _IV_HI = 1e-4, 5.0


def _ncdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1d2(S, K, T, r, sigma):
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    return d1, d1 - sigma * math.sqrt(T)


def bs_price(S, K, T, r, sigma, right):
    """right: 'C' or 'P'. Intrinsic value at/after expiry or zero vol."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0) if right == "C" else max(K - S, 0.0)
    d1, d2 = _d1d2(S, K, T, r, sigma)
    if right == "C":
        return S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d2)
    return K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)


def implied_vol(price, S, K, T, right, r=RISK_FREE_RATE, tol=1e-7):
    """Bisection IV (robust, monotone in sigma). Returns None when the price is outside the
    no-arbitrage band (below intrinsic/discounted-intrinsic or above the upper bound) or inputs
    are degenerate; never guesses a value."""
    if not (price > 0 and S > 0 and K > 0 and T > 0) or right not in ("C", "P"):
        return None
    disc = math.exp(-r * T)
    lower = max(S - K * disc, 0.0) if right == "C" else max(K * disc - S, 0.0)
    upper = S if right == "C" else K * disc
    if price < lower - 1e-9 or price > upper + 1e-9:
        return None
    lo, hi = _IV_LO, _IV_HI
    if price <= bs_price(S, K, T, r, lo, right):
        return None if price < bs_price(S, K, T, r, lo, right) - 1e-9 else lo
    if price >= bs_price(S, K, T, r, hi, right):
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if bs_price(S, K, T, r, mid, right) < price:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)


def greeks(S, K, T, sigma, right, r=RISK_FREE_RATE):
    """delta, gamma, vega (per 1.00 vol), theta (per calendar day). None for degenerate inputs."""
    if not (S > 0 and K > 0 and T > 0 and sigma > 0) or right not in ("C", "P"):
        return None
    d1, d2 = _d1d2(S, K, T, r, sigma)
    sq = math.sqrt(T)
    pdf = _npdf(d1)
    disc = math.exp(-r * T)
    delta = _ncdf(d1) if right == "C" else _ncdf(d1) - 1.0
    gamma = pdf / (S * sigma * sq)
    vega = S * pdf * sq
    base = -S * pdf * sigma / (2.0 * sq)
    theta_y = base - r * K * disc * _ncdf(d2) if right == "C" else base + r * K * disc * _ncdf(-d2)
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta_per_day": theta_y / 365.0}


def enrich_row(row, r=RISK_FREE_RATE):
    """row keys: premium, spot, strike, dte_days, right ('C'/'P'). Returns a NEW dict with iv and
    greeks added (iv None when not solvable); the input is untouched."""
    out = dict(row)
    T = float(row["dte_days"]) / 365.0
    iv = implied_vol(float(row["premium"]), float(row["spot"]), float(row["strike"]), T, row["right"], r)
    out.update({"iv": iv, "rate": r, "model": MODEL})
    g = greeks(float(row["spot"]), float(row["strike"]), T, iv, row["right"], r) if iv else None
    out.update(g if g else {"delta": None, "gamma": None, "vega": None, "theta_per_day": None})
    return out
