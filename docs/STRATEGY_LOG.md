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
| 13 | VWAP Mean Reversion | Directional, underlying only (not options) | Price extended 1–2 SD away from session VWAP; expect reversion | **Tried — promising, unswept** | `/backtest`, RELIANCE.NS 5m/60d, 2026-09-04 | 60 trades, 70.0% win rate, total PnL **+62.3**, avg win 4.82 / avg loss −7.79 — only one of the six with a positive single-run result; needs a real `/sweep` across symbols/params before calling it robust |
| 14 | VWAP Trend Filter | Directional, underlying only (not options) | Trending session; price sits clearly on one side of VWAP | **Tried — not robust** | `/backtest` (`vwap_reclaim`), RELIANCE.NS 5m/60d, 2026-09-04 | 55 trades, 41.8% win rate, total PnL **−64.3**, avg win 10.3 / avg loss −9.41 — loses money net of the win/loss split |
| 15 | VWAP Breakout + Retest | Directional, underlying only (not options) | Momentum break through a VWAP deviation band on volume, then a retest of VWAP itself as new support/resistance | **Tried — not robust** | `/backtest`, RELIANCE.NS 5m/60d, 2026-09-04 | 93 trades, 20.4% win rate, total PnL **−26.4** — win rate far too low even with a favorable win/loss ratio (7.51 / −2.28) |
| 16 | Anchored VWAP — Trend Continuation | Directional, underlying only (not options) | AVWAP anchored at the breakout candle or a swing low; price holds above it making higher highs/lows | **Tried — not robust** | `/backtest`, RELIANCE.NS 5m/60d, 2026-09-04 | 277 trades, 27.8% win rate, total PnL **−68.7** — highest trade count of all six (most overtrading, most tax drag) for the worst absolute loss |
| 17 | Anchored VWAP — Trend Reversal | Directional, underlying only (not options) | AVWAP anchored at a swing high or major news candle; price repeatedly rejected from below it | **Tried — not robust** | `/backtest`, RELIANCE.NS 5m/60d, 2026-09-04 | 254 trades, 28.3% win rate, total PnL **−49.9** |
| 18 | VWAP Multi-Period Reversal | Directional, underlying only (not options) | Price has sat on one side of VWAP for several consecutive periods, then crosses to the other side | **Tried — not robust** | `/backtest`, RELIANCE.NS 5m/60d, 2026-09-04 | 68 trades, 22.1% win rate, total PnL **−21.8** |
| 19 | Liquidity Sweep Reversal (Stop Hunt) | Directional, underlying only (not options) | Price sharply wicks through a swing high/low where stop-loss/limit orders cluster (a "liquidity pool"), then reverses fast | Proposed — untested | Real-world liquidity-heatmap research, 2026-09-04 | **Approximable with OHLCV**: wick beyond a recent swing high/low + a volume spike on that bar + close back inside the prior range = the sweep-and-reversal signature. Enter on the reversal confirming, never on the sweep itself — "the best setups come after the stop hunt, not during it" |
| 20 | Liquidity Wall Fade (order-book support/resistance) | Directional, underlying only (not options) | Price approaches a large resting bid/ask wall visible on the DOM/heatmap | Proposed — **blocked, no Level-2 data** | Real-world liquidity-heatmap research, 2026-09-04 | Needs real order-book depth (resting limit-order size per price level), which this project's yfinance OHLCV feed does not carry — not implementable/backtestable here without a Level-2/DOM data source |
| 21 | Absorption Rejection vs. Failed-Absorption Continuation | Directional, underlying only (not options) | Aggressive market-order volume hits a resting wall: price stalls (wall absorbs → trade the rejection) or the wall gives way anyway (absorption fails → trade the continuation) | Proposed — **blocked, no Level-2 data** | Real-world liquidity-heatmap research, 2026-09-04 | Same DOM-dependency gap as #20 — telling absorption from a breakthrough needs to see the resting order size itself, not just price/volume |
| 22 | Liquidity Void Breakout | Directional, underlying only (not options) | A confirmed breakout runs into a thin, low-liquidity zone with little resting supply/demand to slow it — expect a fast, low-resistance move | Proposed — untested | Real-world liquidity-heatmap research, 2026-09-04 | **Approximable with OHLCV** as a volatility-expansion filter layered on `orb_breakout`: a real air-pocket move should show unusually wide-range bars, rising volume, and few pullback wicks vs. a normal breakout |
| 23 | Liquidity Magnet Target (equal highs/lows, round numbers) | Not an entry trigger — a target/exit-setting concept | Untouched liquidity clusters (equal highs/lows, round numbers) act as statistical magnets price is drawn toward | Proposed — untested | Real-world liquidity-heatmap research, 2026-09-04 | **Approximable with OHLCV** by scanning for equal highs/lows within a small tolerance band and using the nearest untouched one as a profit target, not an entry signal — pairs with any of #19/#22 rather than standing alone |
| 24 | Fake Wall / Spoofing Filter | Not a standalone strategy — a risk/validity filter on #20 | A visible wall that vanishes as price approaches was spoofed (placed to bait, then pulled), not real intent — trading it as real S/R gets faded the wrong way | Proposed — **blocked, no Level-2 data** | Real-world liquidity-heatmap research, 2026-09-04 | Needs order-placement/cancellation event data that OHLCV bars can never show; catalogued for completeness only, not implementable here |
| 25 | India VIX Spike Contrarian Buy | Directional, underlying only (not options) | India VIX spikes sharply (fear/capitulation) while NIFTY/BANKNIFTY sells off hard — VIX is strongly inverse-correlated to the index | Proposed — untested | Real-world India VIX strategy research, 2026-09-04 | **Approximable with OHLCV**: `^INDIAVIX` and `^NSEI` are both plain yfinance tickers already used elsewhere in this project (`static/live.html`, `/history`) — no new data source needed. Entry = VIX N% above its own rolling mean AND the index makes a fresh multi-day low on the same session; exit on VIX reverting back toward its mean. Sizing matters more than direction here — "a VIX spike rarely stays elevated more than a week, and the panic trade is usually right, sizing is what kills it" |
| 26 | India VIX Regime Filter (constraint on existing strategies, not standalone) | Applies to any directional strategy already in this log (`orb_breakout`, SMA crossover, VWAP rows, etc.) | VIX regime changes which strategy type actually works: trend-following wants a calm, orderly VIX; mean-reversion/fade setups want an elevated, spiking VIX | Proposed — untested | Real-world India VIX strategy research, 2026-09-04 | **This is the direct answer to "add VIX as a constraint."** Not implemented anywhere yet — `add_strategy_signal()`/`_auto_signal_core` read no VIX input today; `/live` only *displays* `^INDIAVIX`, nothing gates on it. Proposed rule: fetch `^INDIAVIX` alongside the traded symbol, then only take trend/breakout entries (#9, #14, #22) when VIX is inside its normal band, and only take mean-reversion/fade entries (#13, #19, #25) when VIX is elevated above its rolling mean — "match the strategy to the regime" |
| 27 | India VIX-Elevated Premium Selling (timing overlay on #10–#12) | Applies to this log's existing Iron Condor/Bull Put Spread rows | Iron condors/strangles want to be sold when implied vol is rich vs. realized — India VIX **is** the market's own live IV read, more current than the flat 14% IV assumption #10–#12 already use | Proposed — untested | Real-world India VIX strategy research, 2026-09-04 | Refines #10–#12 rather than replacing them: only enter the premium-selling side when `^INDIAVIX` sits above its own N-day average (rich premium), skip/avoid when VIX is compressed near recent lows (poor risk/reward for a seller) — same read as those rows' "realized vol vs. assumed IV" comparison, just using VIX itself instead of a flat assumption |
| 28 | India VIX Spike Position-Size Throttle (risk overlay, not standalone) | Applies to position sizing on any live strategy, paper or real | Position size should shrink as VIX rises, since a higher VIX means wider true price swings for the same rupee stop distance | Proposed — untested | Real-world India VIX strategy research, 2026-09-04 | **Approximable with OHLCV**: scale `risk_per_trade_pct` (already a real param in `_auto_signal_core`, see `TRADING_CONSTRAINTS.md`) down as `^INDIAVIX` rises above its rolling mean, rather than using a flat % regardless of regime — directly answers "VIX as a constraint" from the sizing side, complementing #26's entry-side filter |
| 29 | India VIX Futures Mean Reversion / Term Structure | Long/short India VIX futures directly (NSE weekly-expiry VIX futures, not the index itself — India VIX is a calculated index, not directly tradable) | VIX futures trade rich/cheap to the spot VIX index depending on term structure, and both mean-revert | Proposed — **blocked, no F&O execution** | Real-world India VIX strategy research, 2026-09-04 | `kotak_real_orders.py` only places CNC cash-equity orders — no futures/options order placement exists anywhere in this codebase (the options-lab endpoints are backtest-only, never execute). Would need a real F&O execution module before this is anything but a paper idea |

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

Update, 2026-09-04 (real backtest results): all 6 are now implemented in
`add_strategy_signal()` and backtested via the real `/backtest` endpoint
against real Yahoo Finance data. **First attempt used `^NSEI` (NIFTY index)
and came back `num_trades: 0` for all six** — traced to a real data-source
issue, not a strategy flaw: Yahoo Finance reports `volume: 0` on every bar
for index tickers (`^NSEI`, `^NSEBANK`, etc., since an index itself isn't
traded), and every VWAP calculation here divides by cumulative volume, so
`vwap` is `NaN` all session and every VWAP-based entry condition is
unconditionally false. Re-ran against `RELIANCE.NS` (a real equity, real
volume) and got real, differentiated results — see the Status/Notes columns
above. Only #13 (VWAP Mean Reversion) came back net-positive on this single
run; the other five lost money, with #16 (Anchored VWAP Continuation)
overtrading the worst (277 trades in 60 days on one symbol). **Caveat: this
is one symbol, one 60-day window, default params — a single `/backtest`
run, not a `/sweep`.** None of #13–18 are wired into `_auto_signal_core`'s
live `strategy` param — per this log's own standing process, none should be
until a real `/sweep` across symbols/params confirms #13 holds up, and the
other five should not be pursued further without a materially different
entry read (they lose money net of their own win/loss split).

Practical implication for any VWAP-based strategy going forward: only use
it live on real equities/futures with genuine traded volume, never on a
raw index ticker.

## Liquidity heatmap strategies (2026-09-04) — explicit user instruction to research and catalog

Rows #19–24 cover the standard, real-world liquidity-heatmap/order-flow
strategies (verified via research, not invented): trading the reversal
after a stop-hunt sweep of a liquidity pool, fading or trading through
resting bid/ask walls, reading absorption at those walls, breaking out
through thin liquidity voids, targeting untouched liquidity clusters as
magnets, and filtering out spoofed ("fake") walls before acting on them.
Sources: [ATAS's heatmap trading guide](https://atas.net/blog/heatmap/),
[LuxAlgo's resting liquidity/liquidity-heatmap concept writeup](https://www.luxalgo.com/library/concept/resting-liquidity-liquidity-heatmap/),
[AlphaSignal's order-book liquidity heatmap primer](https://alphasignal.digital/academy/order-book-liquidity-heatmaps),
[Medium: Stop Hunts in Financial Markets](https://medium.com/@yavuzakbay/stop-hunts-in-financial-markets-789a240f64f3),
[Bookmap's complete guide to heatmap trading](https://bookmap.com/blog/heatmap-in-trading-the-complete-guide-to-market-depth-visualization),
[Bookmap on fake liquidity, bait walls, and phantom size](https://bookmap.com/blog/how-price-reacts-around-fake-liquidity-bait-walls-and-phantom-size).

**Important scoping note, unlike the VWAP batch above: half of these
(#20, #21, #24) are not implementable with this project's current data at
all**, not just untested. A liquidity heatmap is fundamentally a
visualization of the **live order book** (Level 2/DOM depth — the size of
resting limit orders waiting at each price level, plus order
placement/cancellation events to catch spoofing). This project's market
data comes from Yahoo Finance OHLCV bars (`fetch_ohlc`/`yf.download`) —
open/high/low/close/volume of *already-executed* trades, with zero
visibility into resting/unfilled orders. There is no order-book endpoint
in this codebase and yfinance does not provide one. Trading a "wall" or
"absorption" or "spoofing" off OHLCV alone would just be guessing dressed
up in heatmap language — flagged **blocked** rather than
`Proposed — untested` so that distinction doesn't get lost.

The other three (#19, #22, #23) are real, common approximations that
don't need order-book depth: a liquidity *sweep* (#19) still leaves an
OHLCV fingerprint (a wick beyond a swing point + a volume spike + a snap
back inside range); a liquidity *void* breakout (#22) is really a
volatility/volume expansion filter on top of the existing `orb_breakout`
logic; and a liquidity *magnet* target (#23) is just equal-highs/lows
detection used for exits, not entries. These three stay
`Proposed — untested` and are legitimate next candidates for
implementation + `/backtest`, same process as the VWAP rows.

One more distinct, adjacent concept worth flagging separately (not a
catalog row): a **liquidation heatmap** (Coinglass/Hyblock-style, popular
in crypto derivatives) shows clusters of leveraged positions that get
force-liquidated at certain price levels — a related but different data
source (aggregated exchange liquidation data, not resting spot-market
limit orders) and out of scope here since this project trades NSE cash
equities/index, not crypto perpetual futures.

## India VIX strategies (2026-09-04) — explicit user instruction: is VIX tracked as a constraint, and catalog its real strategies

Answer to "do we track India VIX for adding as a constraint": **displayed,
not used.** `static/live.html` fetches `^INDIAVIX` for the human-facing
`/live` dashboard only. Confirmed by direct search of `main.py`: no VIX
read anywhere in `add_strategy_signal()`, `_auto_signal_core`, or the
scheduler — every strategy in this log runs the same way regardless of
the day's VIX level. Rows #26 and #28 below are the concrete proposals to
close that gap (entry-side regime filter and sizing throttle,
respectively) — neither is implemented yet, same "proposed, not live"
status as everything else in this log until backtested.

Rows #25–29 cover the standard real-world India VIX strategies (verified
via research, not invented): the classic contrarian buy on a VIX
spike/index-selloff combo, using VIX as a regime filter that decides
whether trend-following or mean-reversion is the right strategy family
for the day, using VIX as a live richness read for the existing
options-premium-selling rows (#10–#12), throttling position size down as
VIX rises, and trading VIX futures directly (blocked here — no F&O
execution). Sources: [5paisa's India VIX strategies guide](https://www.5paisa.com/blog/how-to-trade-using-india-vix-5-proven-strategies),
[5paisa's VIX-extremes mean reversion writeup](https://www.5paisa.com/blog/mean-reversion-strategy-using-india-vix-extremes),
[marketseasy's "match the strategy to the regime" guide](https://marketseasy.in/vix-strategies),
[Finnovate's 2026 India VIX read](https://www.finnovate.in/learn/blog/india-vix-2026-what-fear-index-tells-investors),
[NSE's official India VIX index page](https://www.nseindia.com/static/products-services/indices-indiavix-index)
(source for the "index, not directly tradable; weekly VIX futures exist
since Feb 2014" fact behind #29's blocked status).

Scoping note distinct from the VWAP/heatmap batches: **India VIX itself
is a calculated index (from the NIFTY options order book), not a security
— you cannot buy or sell "VIX" directly.** NSE does list weekly-expiry
India VIX futures, so #29 is a real market instrument, just one this
project has no execution path for (`kotak_real_orders.py` is cash-equity
CNC only, no F&O order placement anywhere in the codebase). Rows #25–28
sidestep that entirely — they use the *index level* as an input/filter
for trades already placed in equities/index/options, not as something
traded on its own, so they need no new execution capability, only a VIX
fetch (already available via the same `yfinance ^INDIAVIX` ticker
`/live` already uses) wired into the signal/sizing logic.

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
