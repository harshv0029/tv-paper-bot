"""Black-Scholes option PREMIUM PROXY (backlog B-860). RESEARCH ONLY.

!! PROXY, NOT EVIDENCE. Premiums here are model output from index candles plus
!! an assumed IV, not traded prices. Real NSE option premiums carry skew, IV
!! changes, bid/ask spread and liquidity gaps that this model omits. A result
!! built on this module must NEVER be registered as real-money viability
!! evidence or used to open strategy_registry's PFNET_LIVE_FLOOR gate. Its only
!! job is cheap hypothesis screening and sizing intuition until enough real
!! fo_option_candles history (fo_candle_journal.py) has accumulated.

Pure functions, no I/O, no dependency on main. European BS with zero dividend
and a flat risk-free rate (index options on NSE are European).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

PROXY_LABEL = "PROXY_NOT_REAL_MONEY_EVIDENCE"
TRADING_DAYS_PER_YEAR = 365.0   # calendar-day convention for T (theta bleeds on weekends too)
DEFAULT_RATE = 0.065
DEFAULT_IV = 0.15               # assumption, e.g. NIFTY ~ 12-18%
MIN_T_YEARS = 1.0 / (365.0 * 24 * 12)   # floor at ~5 minutes to avoid div-by-zero at expiry


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _t_years(days_to_expiry: float) -> float:
    return max(float(days_to_expiry) / TRADING_DAYS_PER_YEAR, MIN_T_YEARS)


def bs_price(spot: float, strike: float, days_to_expiry: float, iv: float = DEFAULT_IV,
             right: str = "call", rate: float = DEFAULT_RATE) -> float:
    """BS value of a European call/put (per underlying unit, before lot size)."""
    if spot <= 0 or strike <= 0 or iv <= 0:
        raise ValueError("spot, strike and iv must be positive")
    if right not in ("call", "put"):
        raise ValueError("right must be 'call' or 'put'")
    t = _t_years(days_to_expiry)
    sq = iv * math.sqrt(t)
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * t) / sq
    d2 = d1 - sq
    disc = math.exp(-rate * t)
    if right == "call":
        return spot * _ncdf(d1) - strike * disc * _ncdf(d2)
    return strike * disc * _ncdf(-d2) - spot * _ncdf(-d1)


def bs_delta(spot, strike, days_to_expiry, iv=DEFAULT_IV, right="call", rate=DEFAULT_RATE) -> float:
    t = _t_years(days_to_expiry)
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
    return _ncdf(d1) if right == "call" else _ncdf(d1) - 1.0


def theta_per_day(spot, strike, days_to_expiry, iv=DEFAULT_IV, right="call", rate=DEFAULT_RATE) -> float:
    """Premium lost per calendar day with spot/IV unchanged (negative for a long option)."""
    d = float(days_to_expiry)
    return bs_price(spot, strike, max(d - 1.0, 0.0), iv, right, rate) - bs_price(spot, strike, d, iv, right, rate)


def strike_for(spot: float, strike_step: float, right: str, otm_steps: int = 0) -> float:
    """ATM = nearest step; otm_steps moves away from spot (call up, put down)."""
    atm = round(spot / strike_step) * strike_step
    return atm + otm_steps * strike_step if right == "call" else atm - otm_steps * strike_step


@dataclass(frozen=True)
class CostModel:
    """Round-trip friction assumptions for a premium trade (ASSUMPTIONS, not Kotak data)."""
    half_spread_pct: float = 0.5     # of premium, paid on each side
    brokerage_per_order: float = 20.0
    stt_sell_pct: float = 0.1        # on sell-side premium turnover
    other_pct: float = 0.05          # exchange/GST/stamp lump, of turnover per side


def round_trip_cost(entry_premium: float, exit_premium: float, lot_qty: int, cost: CostModel = CostModel()) -> float:
    """INR cost of one buy + one sell of lot_qty units, excluding the price move itself."""
    entry_t, exit_t = entry_premium * lot_qty, exit_premium * lot_qty
    spread = (cost.half_spread_pct / 100.0) * (entry_t + exit_t)
    other = (cost.other_pct / 100.0) * (entry_t + exit_t)
    stt = (cost.stt_sell_pct / 100.0) * exit_t
    return spread + other + stt + 2 * cost.brokerage_per_order


def premium_series(spots, days_to_expiry_at_start: float, strike: float, right: str = "call",
                   iv: float = DEFAULT_IV, bar_minutes: float = 5.0, rate: float = DEFAULT_RATE) -> list:
    """Premium per bar for fixed strike/IV as expiry approaches (theta decay included)."""
    step_days = bar_minutes / (60.0 * 24.0)
    return [bs_price(s, strike, days_to_expiry_at_start - i * step_days, iv, right, rate)
            for i, s in enumerate(spots)]


def simulate_long_option_trade(spots, days_to_expiry_at_start: float, strike_step: float, right: str = "call",
                               otm_steps: int = 0, iv: float = DEFAULT_IV, lot_qty: int = 1,
                               initial_stop_pct: float = 3.0, trail_arm_pct: float = 1.0, trail_pct: float = 1.0,
                               bar_minutes: float = 5.0, cost: CostModel = CostModel()) -> dict:
    """Enter at bar 0 on the underlying path `spots`; manage with the live engine's trailing-SL SHAPE
    (initial stop below entry, trail arms once up trail_arm_pct, then peak - trail_pct), exit at the
    stop or the last bar. Mirrors main.FO_OPTION_* semantics only as a model; the constants are
    arguments, never read from main, so changing them here cannot touch live logic.
    Returns a dict labelled PROXY_LABEL."""
    if len(spots) < 2:
        raise ValueError("need at least two bars")
    strike = strike_for(spots[0], strike_step, right, otm_steps)
    prem = premium_series(spots, days_to_expiry_at_start, strike, right, iv, bar_minutes)
    half = (cost.half_spread_pct / 100.0)
    entry = prem[0] * (1 + half)             # pay the half spread on the way in
    stop = entry * (1 - initial_stop_pct / 100.0)
    peak = entry
    exit_px, exit_i, reason = prem[-1] * (1 - half), len(prem) - 1, "end_of_path"
    for i in range(1, len(prem)):
        mid = prem[i]
        if mid <= stop:
            exit_px, exit_i, reason = min(stop, mid) * (1 - half), i, "stop"
            break
        peak = max(peak, mid)
        if peak >= entry * (1 + trail_arm_pct / 100.0):
            stop = max(stop, peak * (1 - trail_pct / 100.0))
    gross = (exit_px - entry) * lot_qty
    fees = round_trip_cost(prem[0], exit_px, lot_qty, CostModel(0.0, cost.brokerage_per_order,
                           cost.stt_sell_pct, cost.other_pct))
    return {"label": PROXY_LABEL, "strike": strike, "entry_premium": entry, "exit_premium": exit_px,
            "exit_bar": exit_i, "exit_reason": reason, "gross_pnl": gross, "fees": fees,
            "net_pnl": gross - fees}
