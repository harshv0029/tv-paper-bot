# Trading Constraints (standing rules)

## Trade-view sync: closing the "trade vanished" gap (2026-09-03)

User report: trades known to have executed were inconsistently visible on
`/trade-view` - sometimes missing entirely. Root cause: two closed-trade
sources with different freshness, and the page trusted only one of them.

- `/daily-summary`'s `closed_trades` - live SQLite, real-time, wiped on
  every Render redeploy (no persistent disk).
- `/trade-history` - reads `docs/trade_outcomes_log.json`, durable across
  redeploys, but only as fresh as the last `journal-sync.yml` run.
- `trade-view.html` read only the durable file (to dodge the DB-wipe
  undercounting this same file was built to fix - see
  `docs/KNOWN_ISSUES.md`) - so a trade was invisible from the moment it
  closed until the next sync, and if a redeploy hit inside that window,
  gone from BOTH sources permanently (the DB it hadn't been read from yet
  was wiped before the next sync could read it).

**Fix, three parts:**
1. `trade-view.html` now unions both sources client-side (dedup by
   `symbol+exit_time_utc`, same key `journal-sync.yml` dedups on) - a
   trade is visible the instant it closes (from the DB) and stays visible
   after a redeploy wipes the DB (from the file, once synced).
2. `journal-sync.yml` now also triggers on every push to `main`, not just
   the hourly Routine - a push is what actually causes the redeploy that
   wipes the DB, and a push-triggered sync (~10s) finishes well before
   Render's redeploy (1-3 min), catching trades that closed just before
   *my own* pushes - the dominant redeploy cause during active dev.
3. The hourly hosted Routine ("Journal sync - tv-paper-bot") stays as a
   backstop for redeploys not caused by a push here (e.g. Render's
   free-tier inactivity spin-down/cold-start). Confirmed the platform
   won't allow tightening it below hourly.

Residual gap: a redeploy that lands in the few seconds between a trade
closing and the push-triggered sync completing, with no push involved
(pure inactivity spin-down) can still be lost for up to the hourly
Routine's cycle. Not fully closed without a persistent DB (paid Render
tier) - documented as a known, small residual risk, not pretended away.

## Scope: instruments actually tradeable via Kotak Neo/Zerodha (rescoped 2026-09-03)

Explicit user instruction: "currently work on only Indian stock market and
stocks available to Indian trader via Kotak Neo and Zerodha accounts" -
then, on seeing gold drop out entirely: "why only NSE, but keep all those
assets listed in Zerodha." The actual line isn't "NSE-only," it's "would
Kotak Neo/Zerodha actually let a real account trade this":

- **Removed and staying removed**: crypto (BTC-USD, ETH-USD) and US
  mega-caps/ETFs (SPY, QQQ, AAPL, and 12 more) - neither broker offers
  either at all, so paper-trading them had no path to a real trade. The
  US-options overlay built on top of them is correspondingly disabled.
- **NSE/BSE equity** - `^NSEI` (NIFTY 50), `^NSEBANK` (BANK NIFTY),
  `^BSESN` (SENSEX), and the **Nifty 100** (Nifty 50 + Nifty Next 50, ~97
  stocks - NSE's own published index constituent lists, `NSE_STOCK_UNIVERSE`
  in `main.py`) - `.NS` tickers. Expanded from an earlier hand-picked
  15-name list on direct user pushback ("why not u getting whole set of
  assets... use list from public available listing") - a real public
  index is a defensible "whole set," an editorial pick of 15 wasn't. Still
  short of literally every NSE-listed stock (~2,000+, mostly illiquid) -
  scanning that many every 30s against Yahoo's free endpoint would trip
  rate limits for no benefit, since an un-backtested stock trades at the
  same conservative 1% ceiling regardless of how it was found. Round-robin
  batch size raised 7 -> 12 (`SCHEDULER_ENTRY_SCAN_BATCH_SIZE`) to keep the
  full-rotation time reasonable (~4.3 min) at this larger size. Tell me
  specific tickers, or "go to Nifty 200/500," any time.
  - **Tried and abandoned: fetching NSE's true exhaustive equity list
    (~2,000+ symbols) automatically.** Per "Index are also tradable on
    Zerodha. All listing should be exhaustive" - built
    `refresh-nse-universe.yml` to pull NSE's own `EQUITY_L.csv`
    (`SERIES=EQ`) and write `docs/nse_universe.json` for `main.py` to
    load. Confirmed (3 dispatches, 2026-09-03) this doesn't work from
    GitHub Actions: both `archives.nseindia.com` and
    `nsearchives.nseindia.com` return the identical HTML block page in
    ~1.2s regardless of cookies, a real browser-session handshake, or
    browser-like headers - that's NSE's Akamai bot protection
    edge-blocking the runner's datacenter IP before any app logic runs,
    not a fixable header/cookie gap. The workflow is kept
    (`workflow_dispatch`-only, no schedule) in case NSE's posture ever
    changes, but isn't relied on. The Nifty 100 above is the practical
    ceiling until/unless someone downloads `EQUITY_L.csv` from a real
    browser session and commits it by hand for `main.py` to load - true
    automation of "exhaustive" isn't viable against NSE's current bot
    defenses.
- **MCX commodities - restored**: gold (`GC=F`), silver (`SI=F`), crude oil
  (`CL=F`). These ARE real Zerodha/Kotak-Neo-tradable instruments via the
  MCX segment - unlike crypto/US equities, excluding them was overreach.
  yfinance has no free MCX ticker, so these run on the international
  futures contract (COMEX/NYMEX, USD-denominated) as a **price-action
  proxy** - MCX's own INR price differs (import duty, currency, local
  supply/demand) but tracks the same underlying commodity closely enough
  that a candlestick pattern/breakout signal should transfer directionally.
  Gold already has real backtest evidence (100% of 24 swept combos
  profitable - docs/strategy_log.xlsx) - full 2% ceiling; silver/crude are
  unproven - half ceiling (1%) until they earn one.

Tell me specific NSE tickers (or other MCX/currency instruments Zerodha
lists) to add beyond this set any time.

Real NSE options/futures data still requires the same Kotak Neo broker
connection this project has always been gated on (not yet wired up) - the
options overlay's code (`select_option_contract`,
`_options_signal_core`, etc.) is left in place, unused
(`OPTIONS_ELIGIBLE_SYMBOLS = []`), ready for real NSE F&O data once that
connection exists. It is never synthesized as a workaround in the
meantime - same standing rule as NSE cash-market tick data.

The open GC=F and BTC-USD positions at the time of this change were
force-closed via the kill switch (`action=kill`, then `resume`) before the
new `WATCHLIST` deployed, so nothing was orphaned by their removal.

## Kill switch / pause-resume (added 2026-09-03)

Explicit user instruction: "I want to decide when to do trading and when
not." A single master switch, checked by `_auto_signal_core` and
`_options_signal_core` themselves (not just the scheduler, so the
redundant GH Actions backstop calls can't bypass it):

- **`POST /trading-control?action=pause`** - blocks every NEW entry,
  equity and options alike, across every symbol. Does **NOT** stop
  managing an already-open position - stop/target/trend/eod-squareoff all
  keep running exactly as before. A paused account must never mean an
  unwatched open position.
- **`POST /trading-control?action=resume`** - lifts the pause.
- **`POST /trading-control?action=kill`** - the actual kill switch:
  force-closes **every** open position (equity + options) right now at
  the best available current price, regardless of stop/target, tagged
  `exit_reason=manual_kill_switch`, AND pauses (so nothing reopens on the
  very next tick). Standalone code path from the normal exit logic on
  purpose (`_force_close_all_positions`) - an emergency stop should never
  share a code path with, or risk being broken by some future change to,
  the everyday exit logic that protects every other open position.
- **`GET /trading-control`** - current state (`enabled`, who/when/why it
  last changed).
- Survives a Render redeploy the same way an open position's journal does
  - `state/trading_control.json` (written by `journal-sync.yml`,
  restored on startup by `reconcile_trading_control_from_journal`) -
  without this, a pause would silently lift on the next code push.
- Controlled from `/trade-view`'s control bar - a single toggle switch
  (OFF = trading live, ON/red = kill switch: blocks new trades and closes
  everything) - as well as directly via the HTTP endpoints above.

These are the hard limits the live paper-trading engine (`_auto_signal_core`
in `main.py`) enforces on every check, for every market. They are the
canonical reference — if a future change conflicts with this file, the
change is the bug.

| Constraint | Value | Enforced by |
|---|---|---|
| **Capital** | ₹4,00,000 (raised from ₹2,00,000 2026-09-03, per user instruction "for today"), one shared pool across the NSE/BSE watchlist (rescoped to NSE-only 2026-09-03 - see the scope section above) | `capital` param, default across all WATCHLIST entries |
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
- **Gated at 95% confidence (added 2026-09-03).** Direct user instruction:
  a bare SMA-fast-crosses-SMA-slow flip can be one noisy bar, not a real
  reversal - closing a trade on that alone risks getting shaken out and
  missing the recovery. `_trend_confidence()` turns the SMA gap into a
  one-tailed statistical confidence via the normal CDF (`_norm_cdf` -
  same machinery `_bs_delta` already uses for option delta, not a fudged
  number): it standard-errors the gap against recent per-bar price
  volatility (`sigma_price * sqrt(1/sma_fast + 1/sma_slow)`), then reads
  the z-score's confidence off the normal distribution.
  `TREND_WEAKENED_MIN_CONFIDENCE = 0.95` - `trend_weakened` only fires at
  or above that; below it (including whenever there isn't yet enough
  same-day history to size volatility) the trade is left alone and simply
  continues under its existing stop/target/eod-squareoff, exactly per
  instruction ("else it should not close the entered trade").

## Trailing stop loss (added 2026-09-03) - equity engine only for now

Direct user request: a trailing stop for every entered trade, plus rules to
review. **Equity (`_auto_signal_core`) only** - the options overlay has
zero live trades right now (`OPTIONS_ELIGIBLE_SYMBOLS = []`), so there's
nothing to validate a trailing rule against there yet; same treatment is a
natural fast-follow once that overlay is re-enabled. Two-stage rule,
implemented in `_trailing_stop_target()`:

1. **Activation gate - `TRAIL_ACTIVATE_R = 1.0`.** Below 1R of unrealized
   gain (R = entry_price - the ORIGINAL stop at entry, frozen forever in
   the new `signal_state.initial_stop_loss` column so it doesn't move as
   the live stop trails), nothing changes - the trade still runs on its
   plain fixed stop. Rationale: a trade that hasn't even recovered its own
   risk yet shouldn't have its stop tightened on top of normal opening
   noise - that's how a real winner gets shaken out before it ever gets
   going. Industry-standard practice, not specific to this system.
2. **Breakeven lock, then a Chandelier Exit.** At/above 1R, the stop locks
   to breakeven + `TRAIL_BREAKEVEN_BUFFER_PCT` (0.1%, to clear round-trip
   cost) at minimum - the trade can no longer become a real loss. Beyond
   that, it ratchets further via a **Chandelier Exit**: `highest close
   since this trade's own entry - TRAIL_CHANDELIER_K (3.0) * ATR(14)`,
   whichever of that or the breakeven lock is higher. This is a real,
   widely-published technique (Chuck LeBeau's own default k=3,
   period=14), not invented for this project - it adapts the trail's
   width to each stock's OWN actual volatility (a quiet blue-chip and a
   choppy mid-cap get different-width trails automatically) instead of one
   arbitrary fixed percentage applied to everyone alike. ATR is read off
   the multi-day candle history already fetched every tick (not just
   today's bars), so there's a real reading even early in the session.
3. **Only ever ratchets up, never down** - the caller takes
   `max(current_stop, candidate)`; `_trailing_stop_target` itself never
   proposes loosening. Persisted in place (`signal_state.stop_loss` IS the
   live, possibly-trailed value - `stop_hit` needs no separate check), so
   the trade-view UI's existing stop/ladder display already reflects it
   with no separate field.
4. **Never overrides the fixed target.** `target_hit` still exits
   immediately at the planned R-multiple if price gets there first -
   trailing only ever tightens the floor beneath it. Letting a strong
   trend run PAST the original target once trailing has activated (a
   "let winners run" upgrade) is a separate, bigger design decision I've
   deliberately not made unilaterally - say the word if you want that too.
5. **Runs alongside, not instead of, the 95%-confidence `trend_weakened`
   exit above** - both checks run every tick; whichever condition is met
   first exits the trade. Trailing is mechanical/price-based (fires fast
   once price gives back enough); `trend_weakened` is statistical (fires
   only on a real reversal). Together they cover both "the move already
   gave back its gain" and "the setup itself broke."
6. `rr_achieved` on exit is now measured against the ORIGINAL R
   (`initial_stop_loss`), not the trailed stop - otherwise a trade that
   trailed close to its own exit price would report an inflated R-multiple
   off its own shrunken `stop_dist`. The exit payload also carries
   `initial_stop_loss` and a `trailing_active` flag for genuine visibility
   into which trades it actually engaged on.
7. **Survives a redeploy.** `daily_summary()`'s `open_positions` now
   exposes `initial_stop_loss_native` (the frozen entry stop) alongside
   the existing `stop_loss_native` (the live, possibly-trailed one) - both
   round-trip through the journal file, so `initial_stop_loss` is not lost
   across a redeploy and the R-multiple yardstick trailing measures
   against doesn't reset with it. A journal snapshot from before this
   field existed falls back to whatever `stop_loss_native` it has (that
   trade's true original R is a small, honest known-gap for pre-existing
   positions only, not new ones going forward).

**Untested against real market data** - like every new rule in this
system, it's shipped conservative (parameters are widely-published
defaults, not tuned to this specific watchlist) rather than backtested
first, per the same evidence standard the rest of `docs/TRADING_CONSTRAINTS.md`
holds new logic to. Worth a real backtest pass (`entry-trigger-research.yml`'s
pattern) before trusting the exact k=3.0/period=14/activate=1.0R numbers
over the plain fixed stop this replaces.

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

**Disabled 2026-09-03** (`OPTIONS_ELIGIBLE_SYMBOLS = []`) - rescoped to
NSE-only (see the scope section at the top of this file). Every symbol
this ever covered (SPY, QQQ, AAPL, and 12 more) was a US underlier, not
tradeable via Kotak Neo/Zerodha. The mechanics below are left documented
and the code left in place, unused - this is exactly the strike/IV
selection logic real NSE F&O would use once a broker connection (Kotak
Neo) provides real NSE options chain/IV data; **NSE/BSE index and stock
options are NOT covered today** - there is no real chain/IV data for them
without that connection, and this project does not synthesize a fake
options chain as a workaround, the same standing rule as NSE real
tick/futures data.

Every options-eligible symbol also had to be a `WATCHLIST` equity entry
(same `orb_breakout`, 1% ceiling until one earns real evidence the way
AAPL/NIFTY/BANKNIFTY/SENSEX did) - the scheduler needs that entry for
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
