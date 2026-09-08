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

## Smart Money Concepts / ICT strategies (2026-09-07) — explicit user instruction: catalog SMC strategies

Rows #30–#34 below cover the standard Smart Money Concepts (SMC, also
called ICT after Michael Huddleston's "Inner Circle Trader" material)
retail methodology: reading market structure and price imbalance as a
proxy for institutional order flow, entirely from candlestick data — no
Level-2/order-book depth needed, which is the key difference from the
liquidity-heatmap batch (#19–#24) that mostly needed real order-book
depth this project doesn't have. **#19 (Liquidity Sweep Reversal) already
covers SMC's own "liquidity sweep/stop hunt" concept** — not duplicated
here, cross-referenced instead.

Real-world evidence, not invented: independent SMC backtests report
45–55% win rate with profit factor under 1.5 when only ONE component
(order block, or FVG, or a bare structure break) is traded in isolation;
requiring **confluence** — multiple SMC signals agreeing on the same
trade — pushes reported win rates to 50–65%, per [a 2,600-trade SMC
backtest writeup](https://medium.com/@space.garaa/i-backtested-2-600-trades-using-smart-money-concepts-heres-what-actually-works-bb3c671098c6)
and [FXNX's backtest-evidence review](https://fxnx.com/en/blog/smart-money-concepts-work-backtest-evidence).
Component definitions confirmed against [Strike Money's SMC guide](https://www.strike.money/technical-analysis/smart-money-concepts),
[LuxAlgo's SMC/ICT concept library](https://www.luxalgo.com/library/concept/smart-money-concepts/),
and [TradingWyckoff's SMC guide](https://tradingwyckoff.com/en/smart-money-concepts/)
for order blocks/FVG, and [FluxCharts' BOS](https://www.fluxcharts.com/articles/break-of-structure-bos-explained)/[CHoCH](https://www.fluxcharts.com/articles/change-of-character-choch-explained)
writeups for market-structure terminology.

**Scoping note distinct from the earlier batches**: SMC's own "killzone"
session-timing concept (Asian/London/New York windows, [LuxAlgo's
killzone reference](https://www.luxalgo.com/library/concept/killzones/))
is built for near-24h forex/futures markets and doesn't map onto NSE's
single 9:15–15:30 IST session — this project's existing `orb_breakout`
strategy already captures the "highest-probability window right after
open" idea for a single-session market, so killzone timing isn't added
as its own row; #30–#33 apply within NSE hours generally, same as every
other row in this log.

| # | Strategy | Legs | Best-fit condition | Status | Source / date | Notes |
|---|---|---|---|---|---|---|
| 30 | SMC Order Block Entry | Directional, underlying only (not options) | Price returns to the last opposing candle before a strong impulse move (the "order block") and reacts | Proposed — untested | Real-world SMC strategy research, 2026-09-07 | **Approximable with OHLCV**: an order block is the last down-close candle before a sharp up-move (bullish OB) or last up-close candle before a sharp down-move (bearish OB) — both fully derivable from candle open/close, no volume or L2 needed. Entry on price returning to that candle's range and reacting (wick rejection or a reversal candle), stop beyond the OB's far edge. Standalone reported win rate 45–55%, profit factor <1.5 — weakest of this batch alone, meant to combine with #32/#33 (see #34) |
| 31 | Fair Value Gap (FVG) Fill | Directional, underlying only (not options) | A 3-candle sequence leaves a gap between candle 1's high/low and candle 3's low/high (candle 2 never traded that range) — price often returns to fill it | Proposed — untested | Real-world SMC strategy research, 2026-09-07 | **Approximable with OHLCV**: pure 3-bar high/low comparison, no new data source. Reported to fill ~70% of the time per SMC community backtests (search-cited above) — but "fills" and "is profitably tradeable" are different claims; needs its own `/backtest` run before trusting the 70% figure as an edge, not just a fact about price revisiting the gap. Related to but more precisely defined than #22 (Liquidity Void Breakout), which is a looser "thin zone" read rather than this exact 3-candle gap |
| 32 | Market Structure Shift (BOS/CHoCH) Trend Entry | Directional, underlying only (not options) | A Change of Character (price fails to make the next expected higher-low/lower-high) signals a possible reversal; a following Break of Structure (a new swing high/low in the new direction) confirms it | Proposed — untested | Real-world SMC strategy research, 2026-09-07 | **Approximable with OHLCV**: both are pure swing-high/swing-low sequence logic (rolling pivot detection), same primitive `orb_breakout`'s opening-range high/low already uses, just applied to swing points across the whole session instead of just the opening range. CHoCH alone is the earlier, noisier signal ("structure raising its hand"); BOS after a CHoCH is the stronger, later confirmation ("structure standing up") — enter on BOS, not bare CHoCH, to avoid the higher false-signal rate CHoCH carries alone |
| 33 | Premium/Discount (Optimal Trade Entry) Zone Filter | Applies to entry timing on #30–#32, not standalone | Only take longs when price sits in the "discount" half (below the midpoint) of the current swing range, and shorts only from the "premium" half (above the midpoint) | Proposed — untested | Real-world SMC strategy research, 2026-09-07 | **Approximable with OHLCV**: midpoint of the most recent confirmed swing high/low, no new data. SMC's "Optimal Trade Entry" convention narrows this further to the 62–79% retracement zone of the swing (a Fibonacci-style band) — same computation this project would need to build fresh, no existing helper does this yet. A filter, not a signal on its own — meant to gate #30–#32's entries, not replace them |
| 34 | Full SMC Confluence (BOS/CHoCH + Order Block + FVG + Liquidity Sweep) | Directional, underlying only (not options) | All of #19 (liquidity sweep), #32 (structure shift), #30 (order block), and #31 (FVG) agree on the same directional call within a short window | Proposed — untested | Real-world SMC strategy research, 2026-09-07 | The confluence version is the one with real reported edge (50–65% win rate vs. 45–55% for any single component alone, per the search-cited backtests above) — and the most implementation work: needs #19/#30/#31/#32 all built and passing before this can even be attempted, not a quick win. Flagged as the actual target, not the individual rows, which are mostly scaffolding toward this one |

Cross-cutting caveat for the whole SMC batch, same discipline as every
other row in this log: **"approximable with OHLCV" is not the same claim
as "has a real edge on NSE data."** Every SMC definition above is
computable from the same candle data this project already fetches — but
none of it has been run through `/backtest`/`/sweep` yet. Nothing in this
batch goes live before it clears that bar, same standing rule as
everything else here.

## Wyckoff Accumulation/Manipulation/Distribution + Volume strategies (2026-09-08) — explicit user instruction: catalog all strategies combining volume with accumulation/manipulation/distribution

Rows #35–#43 below cover the standard Wyckoff Method (Richard Wyckoff,
1930s) and its modern volume-reading companion, Volume Spread Analysis
(VSA, Tom Williams) — the original, decades-older source of the
"Accumulation → Manipulation → Distribution" framing popular retail SMC/ICT
content (already cataloged as #30–#34) borrows without attribution.
**#19 (Liquidity Sweep Reversal) already covers the OHLCV fingerprint of
the "Manipulation" phase in isolation** — Wyckoff's own name for that exact
price action is the **Spring** (accumulation side) / **Upthrust After
Distribution, UTAD** (distribution side); #35/#36 below don't duplicate
#19's detection logic, they add the range-context precondition (a genuine
multi-week trading range with prior climax/rally/test structure) #19 alone
doesn't require, same relationship #30-#33 have to #34 in the SMC batch.

**Long-only constraint carries over from every other row in this log**:
`add_strategy_signal()`'s own docstring is explicit — "Long-only,
single-position." Distribution-side rows (#36, and the distribution half of
#40/#41) are therefore cataloged as **exit/avoidance filters on an existing
long**, not short-entry signals, same treatment #33 (Premium/Discount Zone)
got as a filter rather than a standalone trigger.

Sources: [Trader's Notes' Wyckoff schematics writeup](https://medium.com/@tradersnotes/wyckoff-trading-method-part-2-trading-schematics-accumulation-distribution-195bf4fcb55e),
[Capital.com's Wyckoff Method guide](https://capital.com/en-int/learn/technical-analysis/the-wyckoff-method),
[LuxAlgo's Wyckoff Accumulation Schematic concept page](https://www.luxalgo.com/library/concept/wyckoff-accumulation-schematic/),
[Wyckoff Analytics (the method's own institute)](https://www.wyckoffanalytics.com/wyckoff-method/),
[Come Learn Forex's Spring/framework writeup](https://www.comelearnforex.com/strategies/wyckoff-method/)
for the accumulation/distribution schematic (Phase A–E, Spring/UTAD)
definitions; [PyQuantLab's VSA backtesting writeup](https://pyquantlab.medium.com/volume-spread-analysis-vsa-strategy-quantifying-market-action-for-trading-signals-with-rolling-9aa57fb79fe9),
[dotnettutorials' VSA guide](https://dotnettutorials.net/lesson/volume-spread-analysis-in-trading/),
[Kotak Neo's own VSA explainer](https://www.kotakneo.com/investing-guide/share-market/volume-spread-analysis/)
for No Demand/No Supply/Stopping Volume bar definitions; [StockCharts
ChartSchool's OBV page](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv)
and [StockCharts' Accumulation/Distribution Line page](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/accumulation-distribution-line)
for OBV/Chaikin A-D/CMF; [TradingView's Volume Profile primer](https://www.tradingview.com/support/solutions/43000502040-volume-profile-indicators-basic-concepts/)
and [PyQuantLab's POC/Value Area writeup](https://pyquantlab.medium.com/volume-point-of-control-and-value-area-analysis-for-trading-cd545c2e081b)
for POC/Value Area.

| # | Strategy | Legs | Best-fit condition | Status | Source / date | Notes |
|---|---|---|---|---|---|---|
| 35 | Wyckoff Spring Entry (Accumulation Phase C) | Directional, underlying only (not options) | Price has spent weeks inside a defined trading range (Phase A's Selling Climax + Automatic Rally + Secondary Test already printed), then briefly breaks range support on a volume spike and snaps back inside | **Tried — not robust** | Real-world Wyckoff research, 2026-09-08; implemented + backtested 2026-09-08 | **Approximable with OHLCV**: same wick-beyond-support + volume-spike + close-back-inside fingerprint as #19, plus a new precondition this project doesn't compute yet — a prior range (rolling N-bar high/low that's stayed roughly flat, with an already-identified high-volume down bar for the Selling Climax and a snap-back rally off it for the Automatic Rally). A "spring" outside that range context is just #19's plain liquidity sweep; the range context is what makes it specifically Wyckoff's Phase-C entry, historically the highest-conviction of the schematic. **Implemented** in `add_strategy_signal()` (`range_lookback`=60, `range_flatness_pct`=3.0, `spring_pierce_pct`=0.3, `volume_mult`=1.5 defaults), unit-tested against a hand-verified fixture, then run via live `/backtest` against real NSE data: RELIANCE.NS and TCS.NS on 7d/1m (2525 bars), plus RELIANCE.NS/ICICIBANK.NS/INFY.NS on 60d/5m (~4367 bars) — **0 trades in all 6 real symbol/window combinations**. Retuned via a param sweep (`range_lookback`/`range_flatness_pct`/`spring_pierce_pct` exposed as real `/backtest` query params the same day) up to 15% flatness/1.0% pierce/100-bar lookback on RELIANCE.NS/ICICIBANK.NS/INFY.NS — **still 0 trades**, confirming this isn't a rare-but-real setup at slightly looser thresholds. A deliberately extreme sanity check (50% flatness, 0.05% pierce, 1.0x volume, 20-bar lookback — no longer a meaningful "Wyckoff spring" by definition, just to confirm the code path isn't broken) DID fire on RELIANCE.NS: 33 trades, 36.4% win rate, +₹6.1 total — proving the logic works, but that even abandoning the strictness that makes it "Wyckoff" surfaces only a noise-level, not-tradeable edge. **Verdict: genuinely too rare/no edge on these liquid NSE large-caps in this sample** — would need genuinely range-bound or less liquid names, or a fundamentally longer lookback window Yahoo's free intraday data can't supply, to get a fair test; not worth further parameter search on this symbol set |
| 36 | Wyckoff UTAD Exit/Avoidance Filter (Distribution Phase C) | Exit filter on an existing long / avoidance filter on new entries — not a short entry (long-only project) | Price breaks above a topping range's resistance on a volume spike, then snaps back inside — the bearish mirror of #35 | Proposed — untested | Real-world Wyckoff research, 2026-09-08 | **Approximable with OHLCV**, same detection as #35 flipped. Since this project is long-only, a confirmed UTAD is used two ways: (a) close out any open long in that symbol immediately rather than waiting for the paper stop to catch a markdown already underway, (b) block new long entries in that symbol until the range resolves — never as a short trigger |
| 37 | Wyckoff Sign of Strength (SOS) Breakout | Directional, underlying only (not options) | A confirmed Spring (#35) is followed by a genuine breakout above the trading range's resistance on expanding volume | **Tried — not robust** | Real-world Wyckoff research, 2026-09-08; implemented + backtested 2026-09-08 | **Approximable with OHLCV** — structurally this project's own `orb_volume` (volume-confirmed breakout, already implemented and live-gated per the mandatory-volume-constraint work this session) with one addition: requiring a confirmed #35 Spring earlier in the same range, so the breakout is read as "accumulation finished, markup starting" rather than a bare volume-confirmed breakout with no context on what came before it. **Implemented** in `add_strategy_signal()` (requires a #35 spring earlier in the same range before arming the breakout), unit-tested (including a fixture proving a bare breakout with NO prior spring does NOT fire), then run via live `/backtest` alongside #35 on the same 6 real symbol/window combinations (RELIANCE.NS/TCS.NS 7d/1m, RELIANCE.NS/ICICIBANK.NS/INFY.NS 60d/5m) — **0 trades in all 6**, which necessarily follows from #35 never confirming a spring to build on in that same data. Same verdict and same next step as #35: current defaults are too strict for these liquid large-caps in the sampled windows |
| 38 | VSA No Demand / No Supply Bar Filter | Applies to entry/exit timing on any directional strategy already in this log | A single bar's spread (range) + volume + close-position tells whether a move is genuine or hollow: an up bar with narrow spread and low volume ("no demand") warns a rally lacks real buying, especially at resistance; a down bar with narrow spread and low volume ("no supply") warns a decline has run out of sellers, especially at support | Proposed — untested | Real-world VSA research, 2026-09-08 | **Approximable with OHLCV** — pure per-bar spread/volume/close-position math, no new data source. A filter, not a standalone entry, same role #33 plays for SMC: skip/delay an entry that shows a "no supply" bar right at the trigger candle even though price/volume conditions otherwise look ready, and treat a "no demand" bar near an open long's target as an early warning to tighten the stop |
| 39 | VSA Stopping Volume / Climax Reversal | Directional, underlying only (not options) | An extended decline (or rally) ends on an extreme volume spike with a wide spread but a close well off the bar's extreme (a struggle, not a clean continuation) — professional absorption of the crowd's capitulation | Proposed — untested | Real-world VSA research, 2026-09-08 | **Approximable with OHLCV**: same climactic-volume fingerprint as Wyckoff's Selling/Buying Climax inside #35/#36's full schematic, but usable standalone as a faster (and noisier) reversal signal without waiting for the rest of the range to confirm — trades the SC/BC event itself rather than the full Phase A-E sequence. Cross-references #22 (Liquidity Void Breakout), which reads volume expansion the opposite way (continuation through thin liquidity) — the distinguishing tell here is the close landing away from the bar's extreme (struggle/absorption) vs. near it (clean continuation) |
| 40 | On-Balance Volume (OBV) Divergence Filter | Applies to entry timing on any directional strategy already in this log, and to #35/#36 specifically as Phase-B confirmation | OBV (cumulative volume, added on up-closes/subtracted on down-closes) rising while price stays flat or drifts down = quiet accumulation underneath a range; OBV falling while price stays flat or drifts up = quiet distribution | Proposed — untested | Real-world OBV research, 2026-09-08 | **Approximable with OHLCV** — Joseph Granville's original 1963 formula, close-to-close direction times volume, cumulative. A regime/confluence filter like #26 (VIX regime), not a standalone trigger: an OBV uptrend during a #35 range's Phase B is the volume-side confirmation real accumulation happened before the Spring, distinct from a range that's just going nowhere |
| 41 | Chaikin Accumulation/Distribution Line & Chaikin Money Flow (CMF) Divergence | Same role as #40, more precise variant | Chaikin's A/D Line weights each bar's volume by where the close landed within that bar's own high-low range (not just up-close/down-close like OBV), so it reads buying/selling pressure more granularly; CMF is A/D smoothed into an oscillator around zero over N bars | Proposed — untested | Real-world Chaikin research, 2026-09-08 | **Approximable with OHLCV** — Marc Chaikin's published formulas, no new data source. Sustained CMF > 0 through a #35-style range = accumulation bias, sustained CMF < 0 through a #36-style range = distribution bias; more precise than #40 but costs nothing extra to compute alongside it, worth backtesting both and keeping whichever actually discriminates better on real NSE data rather than assuming |
| 42 | Volume Profile POC Mean Reversion / Value Area Breakout | Directional, underlying only (not options) | Price has moved away from the session's (or range's) Point of Control — the price level with the most traded volume — and either reverts toward it (fade, inside the value area) or holds beyond the Value Area High/Low on continued volume (genuine acceptance, breakout) | Proposed — untested | Real-world Volume Profile research, 2026-09-08 | **Approximable with OHLCV, but coarser than real footprint data** — true volume profile bins volume at every traded price within each bar (tick/intrabar data); this project's `fetch_ohlc` only has each bar's Close and total Volume, so POC/Value Area here can only be built by binning each bar's total volume at its Close (or typical price `(H+L+C)/3`), a real but blunter approximation, same "approximable, not blocked" caveat class as #19/#22/#23 rather than the fully-blocked #20/#21/#24 (no live order book needed, just enough bars of history to build the histogram) |
| 43 | Full Wyckoff AMD + Volume Confluence Entry | Directional, underlying only (not options) | #35 (Spring/Manipulation) confirmed by #38/#39 (the Spring bar itself shows absorption/stopping-volume character, not a genuine breakdown) AND #40/#41 (OBV/CMF show real accumulation built through Phase B) AND #37 (the eventual SOS breakout carries expanding volume) all agree within the same range | Proposed — untested | Real-world Wyckoff + VSA + volume-indicator research, 2026-09-08 | **The actual target this batch is scaffolding toward**, same relationship #34 has to #30–#33 in the SMC batch — and the most implementation work, needing a trading-range detector (rolling-range/pivot logic this project doesn't have yet, closest existing primitive is `orb_breakout`'s opening-range high/low, applied here to a much longer multi-week range instead) plus #35/#37/#38/#39/#40/#41 all built and passing individually before attempting the combined version. This is the direct, literal answer to "combination of volume and accumulation+manipulation+distribution" — everything else in this section is a component of it |

Cross-cutting caveat, same discipline as every other batch in this log:
**nothing above is implemented in `add_strategy_signal()` or wired into
`_auto_signal_core` yet, and none of it goes live before a real
`/backtest`/`/sweep` run against actual NSE data**, same standing rule as
the VWAP/liquidity-heatmap/VIX/SMC batches before it. Rows #35/#37 were the
natural first candidates to build (they extend `orb_breakout`/`orb_volume`,
already-live primitives, rather than needing new indicator math from
scratch) — **now built and backtested, see their rows above**; #38–#41 are
cheap, pure-arithmetic filters worth building alongside them next; #42's
range-histogram and #43's full confluence are correctly the last things
attempted, once the range-detector primitive they both depend on exists
and #35–#41 have each cleared their own backtest independently.

### SMA vs EMA research (2026-09-08)

`orb_breakout`/`orb_volume` already had an `ma_type` scalar-trend helper
(`_moving_average`) used elsewhere, but the strategy's own entry-trigger
`fast_ma`/`slow_ma` computation inside `add_strategy_signal()` was
hardcoded to `.rolling(...).mean()` (SMA) regardless of that setting — so
no backtest could ever actually have compared SMA vs EMA for the entry
decision itself. Fixed: `ma_type` ("sma"/"ema") now threads into that
branch (`.ewm(span=..., adjust=False).mean()` for EMA), exposed as a real
`/backtest` query param, unit-tested against pandas' own `.ewm()` output.
Real `/backtest` comparison, `orb_breakout`, 7d/1m: **RELIANCE.NS**
(orb_minutes=15, sma_fast=5, sma_slow=21) — SMA and EMA produced
**identical** results (4 trades, 75% win rate, +₹12.4 total, same 4 trade
timestamps/prices). **TCS.NS** (orb_minutes=10, sma_fast=14, sma_slow=50)
— also **identical** (3 trades, 0% win rate, -₹102.4 total). In both real
symbol/window samples, SMA and EMA agreed on trend direction (fast > slow)
at every single breakout moment, so the smoothing choice made zero
difference to which trades fired. Verdict: **no evidence EMA outperforms
SMA (or vice versa) for this trigger on these 2 symbols/7d** — the
difference the two MA types produce mid-series apparently never landed on
a breakout bar in this sample. Not enough evidence to switch any live
WATCHLIST entry's `ma_type` off the "sma" default; would need a wider
symbol/date sample (or a longer period once available) to find a case
where the two actually diverge before concluding either is better.

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
