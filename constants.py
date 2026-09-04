"""
Shared, side-effect-free module-level constants used across main.py's
options-pricing, signal-core, and scheduler concerns.

Extracted from main.py as the first step of the docs/PROJECT_STRUCTURE_PLAN.md
Phase 1 module split - pure code motion (values and comments unchanged from
their original definitions), not a logic change. Pulled into its own module
rather than into e.g. options_pricing.py because these names are read from
many places across the file (DB queries, the scheduler, journal
reconciliation, both signal cores), not just the options-pricing functions -
see PROJECT_STRUCTURE_PLAN.md for the grep evidence behind that call.
"""

ORB_STRATEGY_PREFIX = "orb-"

# Emptied 2026-09-03: rescoped to NSE-only (see the WATCHLIST comment in
# main.py) - every symbol this ever covered was a US underlier, not
# available to trade via Kotak Neo/Zerodha, so the overlay is inert until
# real NSE F&O data exists (same broker-connection gate as NSE cash-market
# data). The strike/IV-selection code itself (select_option_contract,
# _options_signal_core, etc.) is left in place, unused - it's generic
# infrastructure, not US-specific, and is exactly what would drive real
# NSE options once that data source exists.
OPTIONS_ELIGIBLE_SYMBOLS = []
OPTIONS_TARGET_DELTA = 0.35     # moderately OTM: real leverage (bigger % payoff on a win) without
                                 # betting on a near-impossible move - deep ITM has little leverage,
                                 # far OTM is a lottery ticket the IV check below would flag anyway.
OPTIONS_MIN_DTE = 2             # skip 0-1 DTE - gamma/pin risk dominates, not the underlying's trend.
OPTIONS_MAX_DTE = 10            # weekly-ish - long-dated options carry theta we don't need for an
                                 # intraday-signal-driven entry.
OPTIONS_MAX_IV_VS_ATM = 1.6     # IV oversight: reject a strike priced >60% rich vs the chain's own
                                 # ATM IV - a skew/event spike means this specific line is expensive
                                 # relative to the rest of the curve and prone to giving the gain
                                 # straight back to IV crush even if the direction call is right.
OPTIONS_MAX_SPREAD_PCT = 15.0   # liquidity guard: (ask-bid)/ask must be tighter than this, or the
                                 # quote is too thin to trust as a real fill.
OPTIONS_STOP_PCT = 45.0         # premium-based stop - options swing harder than the underlying, so
                                 # this plays the same role stop_pct plays for equities.
OPTIONS_STRATEGY_TAG = f"{ORB_STRATEGY_PREFIX}option"
