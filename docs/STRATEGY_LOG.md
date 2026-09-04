# Strategy Log — Options Strategy Lab

Living record of every hedge/options strategy this project has defined, tried, or evaluated.
**Process:** when a new setup or market read comes in, scan this table first — match market
condition to a listed strategy before inventing a new one. Add a row for anything new; update
`status`/`notes` after any backtest or paper-trade result.

## Catalog

| # | Strategy | Legs | Best-fit condition | Status | Source / date | Notes |
|---|---|---|---|---|---|---|
| 1 | Bull Call Spread | Buy ATM call, sell call +2 strikes | Moderately bullish, defined risk | Template (untested) | Options Strategy Lab v1 | Default dashboard template |
| 2 | Bear Put Spread | Buy ATM put, sell put −2 strikes | Moderately bearish, defined risk | Template (untested) | Options Strategy Lab v1 | Default dashboard template |
| 3 | Long Straddle | Buy ATM call + buy ATM put | Expect big move, direction unknown (vol expansion) | Template (untested) | Options Strategy Lab v1 | Net debit, unlimited upside/large downside gain, loss capped at premium |
| 4 | Short Strangle | Sell call +3 strikes, sell put −3 strikes | Range-bound, high/rich IV, expect contraction | Template (untested) | Options Strategy Lab v1 | Unlimited risk both sides — dashboard's `computeMetrics()` must show "Unlimited", not a capped number |
| 5 | Iron Condor | Buy put −4 / sell put −2 / sell call +2 / buy call +4 | Range-bound, defined risk, collect theta | Template (untested) | Options Strategy Lab v1 | Symmetric wings by default; see #9–10 for asymmetric live variants |
| 6 | Protective Put | Long underlying + buy put −1 strike | Hold underlying, hedge downside | Template (untested) | Options Strategy Lab v1 | |
| 7 | Covered Call | Long underlying + sell call +2 strikes | Hold underlying, mildly bullish/neutral, harvest premium | Template (untested) | Options Strategy Lab v1 | |
| 8 | Collar | Long underlying + buy put −2 + sell call +2 | Hold underlying, cheap/free downside hedge, cap upside | Template (untested) | Options Strategy Lab v1 | |
| 9 | SMA Crossover (fast 5 / slow 20) | Directional, underlying only (not options) | Trending intraday move | **Tried — not robust** | `/backtest`+`/sweep`, NIFTY 1-min/7-day | Explicitly flagged: results did not hold up across the sweep grid — do not deploy live as-is |
| 10 | NIFTY Iron Condor (live-tuned) | Short 24700CE/23700PE, long 24900CE/23500PE, ~2–3wk expiry | Vol squeeze: realized vol < assumed IV, range-bound (coil) | Proposed — pending `/sweep` backtest | Multi-timeframe scan, 2026-09-01 | Strikes set from Jun–Aug swing high/low (24774/23606); realized vol 10.6% ann. vs 14% assumed IV |
| 11 | SENSEX Iron Condor (wider wings) | Short 78700CE/76200PE, long 79500CE/75400PE | Same vol-squeeze edge as #10, weaker weekly trend structure (below both weekly MAs) → wider wings for breakout risk | Proposed — pending `/sweep` backtest | Multi-timeframe scan, 2026-09-01 | Realized vol 11.0% ann. vs 14% assumed IV |
| 12 | BANKNIFTY Bull Put Spread | Sell 57000PE, buy 56000PE | Pullback-to-support inside an intact uptrend; premium-selling edge weaker (realized vol ≈ assumed IV) | Proposed — pending `/sweep` backtest | Multi-timeframe scan, 2026-09-01 | Strongest 60-day trend of the three indices (+5.35%); defined-risk "buy the dip" |
| 13 | VWAP Mean Reversion | Directional, underlying only (not options) | Price extended 1–2 SD away from session VWAP; expect reversion | Proposed — untested | Real-world VWAP strategy research, 2026-09-04 | Fade the extension, target back to VWAP itself; 1-SD bands = more/weaker signals, 2-SD = fewer/stronger |
| 14 | VWAP Trend Filter | Directional, underlying only (not options) | Trending session; price sits clearly on one side of VWAP | Proposed — untested | Real-world VWAP strategy research, 2026-09-04 | Long only while price > VWAP, short only while price < VWAP — VWAP used purely as a directional filter, not the entry trigger itself; conceptually closest to this project's existing SMA-fast/SMA-slow trend filter |
| 15 | VWAP Breakout + Retest | Directional, underlying only (not options) | Momentum break through a VWAP deviation band on volume, then a retest of VWAP itself as new support/resistance | Proposed — untested | Real-world VWAP strategy research, 2026-09-04 | Entry on the retest HOLDING, not on the initial break — filters fakeout breaks that don't get institutional follow-through |
| 16 | Anchored VWAP — Trend Continuation | Directional, underlying only (not options) | AVWAP anchored at the breakout candle or a swing low; price holds above it making higher highs/lows | Proposed — untested | Real-world VWAP strategy research, 2026-09-04 | Dips back to the AVWAP line within an intact uptrend are the buy-the-dip entry |
| 17 | Anchored VWAP — Trend Reversal | Directional, underlying only (not options) | AVWAP anchored at a swing high or major news candle; price repeatedly rejected from below it | Proposed — untested | Real-world VWAP strategy research, 2026-09-04 | Mirror read of #16 — repeated rejection (not reclaim) signals sustained selling pressure / a topping structure |
| 18 | VWAP Multi-Period Reversal | Directional, underlying only (not options) | Price has sat on one side of VWAP for several consecutive periods, then crosses to the other side | Proposed — untested | Real-world VWAP strategy research, 2026-09-04 | The cross event itself is the trigger (not the distance from VWAP) — distinct from #13's "extended-then-fade" read |

## VWAP strategies (2026-09-04) — explicit user instruction to research and catalog

Rows #13–18 above cover the standard, real-world directional VWAP strategies
(verified via research, not invented): mean reversion off deviation bands,
VWAP as a pure trend filter, breakout-then-retest, and anchored-VWAP
continuation/reversal reads. Sources: [Tradervue's VWAP guide](https://www.tradervue.com/blog/vwap-indicator),
[TrendSpider's anchored VWAP guide](https://trendspider.com/learning-center/anchored-vwap-trading-strategies/),
[CrossTrade's VWAP reversion writeup](https://crosstrade.io/learn/trading-strategies/vwap-reversion),
[ChartsWatcher's VWAP strategies roundup](https://chartswatcher.com/pages/blog/6-powerful-vwap-trading-strategies-for-2025).

One distinct, non-directional use of VWAP worth flagging separately (not a
catalog row, since it isn't a signal strategy at all): institutions also use
VWAP as an **execution benchmark** - an algorithm slices a large order across
the session to average close to VWAP and minimize market impact, rather than
to predict direction. Not applicable to this project's paper/real-money
entries (those are always small, single-order fills, never sliced), but
worth knowing the term also means this in the wild.

None of #13–18 are wired into `_auto_signal_core`'s `strategy` param yet
(currently only `orb_breakout` and `bullish_engulfing` are implemented) -
per this log's own standing process, these stay `Proposed — untested` until
actually backtested, same as the options rows above.

## Cross-strategy read (2026-09-01)

All three indices (NIFTY, BANKNIFTY, SENSEX) were coiling: short-term pullback below daily
20/50-SMA, inside a stalling-but-still-intact weekly uptrend, with ATR **contracting** on both
daily and weekly timeframes across the board — a classic pre-breakout squeeze. NIFTY/SENSEX
realized vol ran below the dashboard's flat 14% IV assumption (favors premium-selling, #10/#11);
BANKNIFTY's realized vol sat close to that assumption (favors a directional defined-risk play
riding its stronger trend, #12) over pure theta harvesting.

## How to use this log going forward

1. On a new setup/pattern read, compare it against the **Best-fit condition** column — pick the
   closest match instead of designing from scratch.
2. If nothing fits, add a new row with legs, condition, and `status: Proposed`.
3. Before paper/live use, run it through `/sweep` on the Render server and flip `status` to
   `Tried — robust` or `Tried — not robust` with the result noted.
4. Never skip straight to "live" — paper-trade first per the project's standing rule (see the
   session Transfer Pack: paper-trading only until explicit go-ahead).
