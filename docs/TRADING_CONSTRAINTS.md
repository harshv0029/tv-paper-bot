# Trading Constraints (standing rules)

These are the hard limits the live paper-trading engine (`_auto_signal_core`
in `main.py`) enforces on every check, for every market. They are the
canonical reference — if a future change conflicts with this file, the
change is the bug.

| Constraint | Value | Enforced by |
|---|---|---|
| **Capital** | ₹4,00,000 (raised from ₹2,00,000 2026-09-03, per user instruction "for today"), one shared pool across every market (NSE, crypto, US) | `capital` param, default across all WATCHLIST entries |
| **Max loss per day** | **2% of TOTAL capital at the start of the day (₹8,000 at current capital)** — resets at IST midnight, every calendar day, automatically | `daily_risk_pct=2.0` + `ist_midnight_epoch()` in `today_realized_pnl()` |
| **Max risk per trade** | **2% of the capital actually INVESTED IN THAT TRADE** (the tranche/available-capital-capped amount it can deploy — `usable_capital_inr`), NOT 2% of total account capital — explicit standing policy, clarified 2026-09-03. A CEILING, not a fixed rate — set lower per symbol where evidence supports it. Both this cap and the daily cap apply independently; whichever binds first forces the exit/entry-block | `risk_per_trade_pct` × `usable_capital_inr`, per-symbol in `WATCHLIST` |
| **Per-trade stop-loss cap** | Same ceiling logic, tighter of this or the strategy's own ORB-low level | `stop_pct`, per-symbol in `WATCHLIST` |
| **Risk:Reward minimum** | **1:3** (target = entry + 3 × stop distance) — raised 2026-09-03 from 1:2 per standing user instruction; a trade is only entered if it clears this | `rr=3.0`, `SCHEDULER_RR` |
| **Capital deployed cap** | Total notional across all open positions never exceeds current `capital` | `deployed_notional()` capital check in the entry path |
| **Position sizing** | Fractional units, not integer-floored — a whole-unit floor was silently blocking every BTC-USD/ETH-USD/gold entry (unit price exceeds a ₹2L pool) regardless of signal quality; fixed 2026-09-03 | qty computed as a float in `_auto_signal_core`, min ₹100 notional guard |
| **Trend exit** | An open LONG position exits early (before stop/target/eod) if the short-term trend that justified holding it flips against the trade — checked on every tick, not just at entry | `trend == "down"` (equity) / `_compute_trend()` vs. call-or-put (options) in the position-management branch |

## Trend health is monitored for the life of the trade, not just at entry (added 2026-09-03)

Direct user instruction: entries already required a favorable trend
(`orb_breakout` requires `trend == "up"`; `bullish_engulfing` has an
optional `trend_sma` filter), but an OPEN position was never re-checked
against it — only stop/target/eod-squareoff/daily-halt could close a
trade early. Now every open-position check also asks "is the trend that
justified this trade still intact?":

- **Equity** (`_auto_signal_core`): `sma_fast`/`sma_slow` are already
  recomputed on every check (used for the entry trend filter) - a long
  position now also exits with `trend_weakened` the moment that same
  read flips to `"down"`, regardless of where price sits between stop and
  target. Checked after target/stop (a live price-level hit still takes
  priority for reason-labeling) and before eod-squareoff.
- **Options overlay** (`_options_signal_core`): a **call** (bullish bet)
  exits `trend_weakened` if the underlying's trend flips to `"down"`; a
  **put** (bearish bet) exits if it flips to `"up"`. Uses the same
  `sma_fast`/`sma_slow` read via a shared helper (`_compute_trend`),
  reusing `fetch_ohlc`'s cache so this doesn't add a real extra network
  call when the underlying was already checked elsewhere this tick.
- This is a genuinely new, lower-priority exit trigger, not a replacement
  for the hard stop/target/daily-cap/expiry limits above it in priority -
  the point is to often exit BEFORE the stop is hit (smaller loss, or
  locking in a partial gain) once the setup's own premise has broken,
  rather than mechanically riding every trade all the way to its stop.

## Two independent caps, two different bases (clarified 2026-09-03)

The per-trade cap and the daily cap are measured against **different
amounts of money on purpose** - conflating them was a real bug risk, so
this is spelled out explicitly:

- **Per-trade cap**: `risk_per_trade_pct`% of **that trade's own allocated
  capital** (`usable_capital_inr` = min(capital available right now,
  capital/`CAPITAL_TRANCHES`) - the slice this specific trade can deploy).
  A ₹2,00,000 tranche at the 2% ceiling risks at most ₹4,000 on that one
  trade, not ₹8,000. If the strategy's own stop is tighter than the
  `stop_pct` cap (common - see BTC-USD's live example, where a ~0.65%
  structural stop meant the real risk taken was well under even this),
  the realized risk is smaller still.
- **Daily cap**: `daily_risk_pct`% of **total account capital as of the
  start of the IST day** (`capital`, currently ₹4,00,000 -> ₹8,000/day),
  shared across every open trade and every market.
- Both are hard, independently-enforced exits - hitting either one forces
  the corresponding action (stop-loss exit for the per-trade cap,
  no-new-entries + square-off-everything for the daily cap) regardless of
  the other. A single trade's per-trade cap is always <= the daily cap
  (since a tranche is always a fraction of total capital), so in practice
  the daily cap is the outer bound multiple smaller trades collectively
  respect, and the per-trade cap is what limits any ONE of them.

## Per-trade risk: 2% is a ceiling, tuned down by evidence

Current split (as of 2026-09-03):
- **NIFTY, BANKNIFTY, SENSEX: full 2%, strategy `orb_breakout`.** Real
  60-day backtest evidence behind this exact ORB strategy
  (`docs/daily_logs/2026-09-02-entry-trigger-research.md`) — profitable on
  95.8-100% of swept parameter combinations, not a lone lucky spike.
- **AAPL: full 2%, strategy `bullish_engulfing` (trend_sma=20).** Switched
  2026-09-03 from unvalidated `orb_breakout` defaults once real evidence
  existed for a different strategy on this symbol — 100% of 6 swept
  combos profitable (`docs/strategy_log.xlsx`). Live exits still use the
  same bounded-risk framework (stop/target/EOD-squareoff) as every other
  symbol, not the backtest's own open-ended exit — see the docstring on
  `_auto_signal_core` in `main.py`.
- **SPY, QQQ, BTC-USD, ETH-USD: 1% (half the ceiling), strategy
  `orb_breakout`.** No evidence yet that any strategy works on these -
  runs conservative until one earns a track record, the same way
  NIFTY/BANKNIFTY/SENSEX and AAPL did.

Per-symbol `strategy` is set in `main.py`'s `WATCHLIST`; the redundant
GH Actions backstop workflows (`live-signals*.yml`) must pass matching
`strategy`/params for any symbol that isn't plain `orb_breakout`, or the
backstop call and the in-process scheduler will disagree about how that
symbol is being traded.

## The daily loss cap, specifically

- Resets automatically every IST calendar day at midnight — not manually,
  not on a rolling 24h window. This is deliberate: it's the account's "day"
  regardless of which market (NSE/US/crypto) a position is in, since a
  US-session trade spans ~19:00-01:30 IST and needs one consistent day
  boundary for the whole shared pool.
- Once today's realized loss (summed across every symbol/market, converted
  to ₹ via each trade's own `fx_to_inr`) hits ₹4,000: no new entries are
  taken, and any open position is squared off immediately, for the rest of
  that IST calendar day.
- This is a hard numeric check in code (`halted = remaining_budget <= 0`),
  not a judgment call — see the multi-agent architecture doc: Validator-role
  logic like this is deliberately deterministic code, never routed through
  an LLM's discretion.

## Options overlay (calls/puts) - added 2026-09-03

Real, currently-quoted contracts on **SPY, QQQ, AAPL, MSFT, GOOGL, AMZN,
META, NVDA, TSLA, NFLX, AMD, JPM, V, DIA, IWM** (`OPTIONS_ELIGIBLE_SYMBOLS`
in `main.py`) - 15 of the most heavily-optioned, most liquid US mega-caps/
ETFs, expanded 2026-09-03 from just SPY/QQQ/AAPL per explicit user
instruction not to skip stocks with a real options market. This is a
curated list, not literally every optionable US equity (~4,000+ names via
the OCC) - scanning that whole universe every 30s against Yahoo's free/
unofficial API would trip rate limits and blow past the scheduler's own
cycle time, for no real benefit since an un-backtested symbol trades at the
same conservative ceiling regardless of how it was found. Tell me specific
tickers to add beyond this set any time. **NSE/BSE index and stock options
are NOT covered** - there is no real chain/IV data for them without a
broker connection (Kotak Neo, not yet wired up); this project does not
synthesize a fake options chain as a workaround, the same standing rule as
NSE real tick/futures data.

Every options-eligible symbol is also a `WATCHLIST` equity entry (same
`orb_breakout`, 1% ceiling as SPY/QQQ until one earns real evidence the way
AAPL/NIFTY/BANKNIFTY/SENSEX/GC=F did) - the scheduler needs that entry for
session hours/currency/risk_pct, so an options-eligible symbol missing from
`WATCHLIST` is silently skipped, not an error.

- **Direction -> right**: a bullish signal (ORB breakout with trend, or
  bullish engulfing) buys a **call**; the same patterns' bearish mirror
  (ORB breakdown, bearish engulfing - `_detect_direction_signal` in
  `main.py`) buys a **put**. The equity engine itself stays long-only and
  is untouched by this - direction detection here only decides call vs put.
- **Strike selection - "bigger profit, don't lose sight of IV"**: nearest
  live contract to **0.35 delta** (`OPTIONS_TARGET_DELTA`), computed via
  Black-Scholes from the chain's own quoted IV - moderately OTM for real
  leverage on a win without betting on a near-impossible move. Rejected if
  its IV is more than **1.6x the chain's own ATM IV** (`OPTIONS_MAX_IV_VS_ATM`)
  - a skew/event spike means that strike is priced rich and prone to giving
    the gain back to IV crush even if the direction call is right - or if
  its bid/ask spread is illiquid (>15%, `OPTIONS_MAX_SPREAD_PCT`).
- **Expiry**: nearest with 2-10 days to expiry (`OPTIONS_MIN_DTE`/`MAX_DTE`)
  - skips 0-1 DTE gamma/pin risk and avoids paying for theta on a
    signal-driven intraday entry.
- **Stop/target**: premium-based - stop at **45% below entry premium**
  (`OPTIONS_STOP_PCT`), target at entry + `rr` x that same risk, so the
  standing **1:3 minimum RR still applies**, just to the option's own P&L
  basis instead of the underlying's.
- **Sizing**: same shared capital pool and tranche cap as everything else
  (`deployed_notional` now sums both `signal_state` and `option_state`).
  Contracts = risk budget / risk-per-contract, floored - but never silently
  zeroed by that floor the way un-fixed equity qty once was: if 1 contract's
  own risk still fits inside today's *full* remaining daily-loss budget, it
  takes that 1 contract even if its risk slightly exceeds this one trade's
  own `risk_per_trade_pct` target (the same "one trade can use the whole
  day's budget" ceiling already applied to equities when `risk_per_trade_pct
  == daily_risk_pct`, made explicit for the options case since a 100-share
  multiplier can't size down to a fraction of a contract the way BTC/gold
  size down to a fraction of a unit).
- **Exit**: stop/target/EOD-squareoff exactly like equities, plus a forced
  exit if the contract's own expiry is reached - never held into or past
  expiry.
- Position tracked in `option_state` (DB) + journaled the same way open
  equity positions are (`state/open_positions.json`, restored on every
  Render redeploy via `reconcile_open_positions_from_journal`), and its
  buy/sell legs land in the SAME `trades` table as equities (qty =
  contracts x 100, price = premium/share) tagged `orb-option` - so realized
  P&L, the daily loss cap, and `/daily-summary` automatically include
  options alongside equities as one account, one shared risk budget.

## Where this is currently duplicated (keep in sync if you change a number)

- `main.py`: `SCHEDULER_DAILY_RISK_PCT`, `SCHEDULER_RISK_PER_TRADE_PCT`,
  `SCHEDULER_STOP_PCT`, `SCHEDULER_RR` (used by the in-process scheduler),
  and `OPTIONS_ELIGIBLE_SYMBOLS`/`OPTIONS_TARGET_DELTA`/`OPTIONS_STOP_PCT`/
  `OPTIONS_MAX_IV_VS_ATM` for the options overlay
- `.github/workflows/live-signals.yml`, `live-signals-us.yml`,
  `live-signals-crypto.yml` (redundant GH Actions backstop calls -
  `live-signals-us.yml`'s `OPT_COMMON` block is the options backstop)
- `/dry-run-day`, `/trade-view`, `/live` default query params in their own
  fetch calls
