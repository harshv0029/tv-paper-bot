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
| 38 | VSA No Demand / No Supply Bar Filter | Applies to entry/exit timing on any directional strategy already in this log | A single bar's spread (range) + volume + close-position tells whether a move is genuine or hollow: an up bar with narrow spread and low volume ("no demand") warns a rally lacks real buying, especially at resistance; a down bar with narrow spread and low volume ("no supply") warns a decline has run out of sellers, especially at support | **Tried — inconclusive** | Real-world VSA research, 2026-09-08; implemented + backtested 2026-09-08 | **Approximable with OHLCV** — pure per-bar spread/volume/close-position math, no new data source. A filter, not a standalone entry, same role #33 plays for SMC: gates a trigger bar that itself shows "No Demand" characteristics. *(Correction: the original note above named "No Supply" as the bar to skip on — backwards under standard VSA convention, where No Supply reads bullish (absence of selling) and would make no sense to filter out of a long entry; No Demand, a weak UP bar, is the correct one to gate a long trigger on.)* **Implemented** as an opt-in `vsa_filter` param (default False, zero change to live behavior) on `orb_breakout`/`orb_volume`, unit-tested against a hand-verified fixture, then run via live `/backtest` on RELIANCE.NS and TCS.NS (7d/1m, same fixtures as the ma_type test): RELIANCE.NS unaffected (no trigger bar was ever a No Demand bar in this window, identical 4-trade/75%-win/+₹12.4 result with or without the filter); TCS.NS showed the filter DID activate — same 3 losing trades, but one entry shifted ~1 minute later at a marginally better price (total -₹100.3 vs -₹102.4 unfiltered) — proving the filter correctly detects and suppresses a No Demand trigger bar, but the sample is too small (1 affected trade) to say whether it meaningfully helps |
| 39 | VSA Stopping Volume / Climax Reversal | Directional, underlying only (not options) | An extended decline (or rally) ends on an extreme volume spike with a wide spread but a close well off the bar's extreme (a struggle, not a clean continuation) — professional absorption of the crowd's capitulation | **Tried — not robust** | Real-world VSA research, 2026-09-08; implemented + backtested 2026-09-08 | **Approximable with OHLCV**: same climactic-volume fingerprint as Wyckoff's Selling/Buying Climax inside #35/#36's full schematic, but usable standalone as a faster (and noisier) reversal signal without waiting for the rest of the range to confirm — trades the SC/BC event itself rather than the full Phase A-E sequence. Cross-references #22 (Liquidity Void Breakout), which reads volume expansion the opposite way (continuation through thin liquidity) — the distinguishing tell here is the close landing away from the bar's extreme (struggle/absorption) vs. near it (clean continuation). **Implemented** as a new standalone `vsa_climax_reversal` strategy in `add_strategy_signal()` (stateful hold from the climax bar until price closes back below that bar's own low), unit-tested against a hand-verified fixture, then run via live `/backtest` on RELIANCE.NS/TCS.NS/ICICIBANK.NS (60d/5m): **0% win rate on all 3 symbols** (11, 25, and 4 closed trades respectively — 40 losing trades total, combined -₹603.7). Not just "no edge" like #35/#37 — this is a consistently WRONG signal across every symbol tested. The invalidation exit (close below the climax bar's own low) is likely too tight for a genuine reversal to ever confirm before stopping out, or the climax detection itself is catching failed bounces rather than real absorption. **Do not pursue further without a fundamentally different exit rule** (e.g. a time-based or trailing exit instead of the tight low-based invalidation) |
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

## Universal multi-factor entry-confidence engine (2026-09-09) - full architecture revamp

Explicit user instruction: "revamp all of the strategy architecture from
beginning." This log's own 43 rows above are exactly the gap that
prompted it - each strategy fires on its own single rule in isolation,
never combined into one scored decision. Full detail (weights, rejection
filters, target-cluster/staged-exit mechanics, and what was explicitly
declined - a deeper probabilistic expected-value framework proposed the
same session, "ignore feedback then") lives in
`docs/TRADING_CONSTRAINTS.md`'s own "Universal multi-factor entry-
confidence engine" section, not duplicated here. Short version: replaces
`orb_breakout`/`bullish_engulfing` as the live entry trigger for every
WATCHLIST symbol (not deleted - `/backtest`/`/sweep` still use them for
standalone research) with one 8-factor weighted score (`_compute_
universal_entry_score`), a target CLUSTER instead of a single rr*R number
(`_compute_target_cluster`), and a staged 25/25/25/trail profit-booking
ladder (`_split_exit_legs`) wired into both paper and REAL order
placement immediately (this session's own real-money go-ahead). NOT yet
backtest-tuned against real NSE data - same "proposed, not yet swept"
status as every other row in this log, flagged as an explicit exception
since it went live before that sweep per direct user instruction rather
than after.

## From-scratch entry signal redesign session (2026-09-15) - `universal_score` found unfixable, 5 new signals tried, none clear a profitability bar yet

Context: `universal_score` (the live default entry since 2026-09-09, `main.py:8990`)
was found unfixable via config/exit tuning after 4 separate rigorous
cost-adjusted tests (margin sweep, timeframe sweep, gross-edge breakdown,
early-exit counterfactual - all dead ends, see the session's transfer
pack for full numbers). Per explicit user instruction, redesigned the
entry signal from scratch instead of continuing to tune it. All tests
below use the same harness: 52-symbol (NIFTY200-restricted, evidenced +
sampled) / 60-day / 5m replay, real cost model (~0.8% round-trip:
brokerage/STT/exchange/SEBI/stamp/GST/slippage/DP), ₹400,000 capital,
read-only GitHub Actions workflows under `.github/workflows/*-research.yml`
that import `main.py` for data/cost plumbing only - none of this is wired
into `main.py`'s live strategy dispatch. **Baseline for comparison:**
`universal_score` itself: n=1278, win 10.4%, PFgross 1.12, PFnet 0.05,
cost drag 169.8%.

| # | signal | workflow file | n | win% | PFgross | PFnet | cost drag | verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | VWAP band-cross reversal (2.5σ, target=VWAP frozen, stop=signal-bar low, 45min timebox) | `vwap-reversal-signal-research.yml` | 286 | 2.8% | 0.84 | 0.01 | 285.4% | **Dead end** — PFgross <1, losing pre-cost. 54.5% of trades were `stop_hit` at 0% win (band-cross alone ≠ reversal confirmation). |
| 2 | VWAP reclaim-confirmed (same, but waits for a close above the capitulation bar's high before entering, 30min confirm window) | `vwap-reclaim-confirmation-research.yml` | 110 | 2.7% | 0.86 | 0.01 | 209.2% | **Dead end, same as #1.** Confirmation cut stop_hit share 54.5%→28.2% as designed, but shrank winners equally (reversion_timebox PFgross 8.97→3.05) — a wash. Entry near VWAP (the fixed target) mechanically shrinks the move available before the cost gate. **Do not re-try the VWAP-reversion family without a genuinely different target/stop mechanic** - two independent tests converged on PFgross <1. |
| 3 | Range breakout momentum (30min OR, close>OR_high, close>VWAP, vol>1.5x avg, target=1.0x measured move, stop=OR_low, 60min timebox) | `range-breakout-momentum-research.yml` | 674 | 6.5% | **1.05** | 0.03 | 261.1% | First signal with PFgross >1 pre-cost, broad-based across ~20/52 symbols. `breakout_failed` (entering right on the breakout candle, then fading) was 42.1% of trades, 0% win, avgGross -₹487 - the dominant drag. |
| 4 | Breakout-retest continuation (#3's candidate filters, but WAITS for a pullback+reclaim retest within 45min instead of entering on the breakout bar) | `breakout-retest-continuation-research.yml` | 291 | 4.1% | 0.90 | 0.01 | 300.3% | **Made it worse, not better** - `breakout_failed` share went UP (42.1%→52.6%). A level that's already been broken-then-retested reads as exhaustion, not renewed strength, at 5m resolution. **Do not re-try a waiting/confirmation-stage fix on this signal family** - both waiting-stage attempts this session (#2 and #4) shrank the sample and made the targeted bucket the same or worse. |
| 5 | Range breakout, tightened filters (#3 unchanged except vol surge 1.5x→2.0x and a new 0.15% minimum clearance above OR_high — single-bar, no waiting stage) | `range-breakout-tightened-filters-research.yml` | 528 | 7.4% | **1.11** | 0.03 | 235.7% | **Best result of the session so far.** `breakout_failed` share nearly halved (42.1%→22.9%) just from raising single-bar conviction thresholds - confirms lighter-touch filter tightening beats a second confirmation stage for this family. avgGross per trade more than doubled (+₹16→+₹36). Still PFnet 0.03 — cost drag (235.7%) still consumes the whole gross edge. **Most promising thread to keep pulling; not yet near the pool bar.** |

**Pool bar for going anywhere near production** (agreed with user 2026-09-15,
applies to all future signal candidates, not just these): PFnet ≥1.3,
n≥100 trades, on this same real-cost validation replay. Then, and only
then: implement as real `main.py` code → unit tests → full pytest green →
re-validate the replay actually calls the implemented function (see this
file's/CLAUDE.md's own drift warning) → report honestly → explicit user
go-ahead **per strategy** before it touches `main.py`'s live dispatch or
any WATCHLIST config. Nothing above has cleared this bar. Win rate alone
(even >50%) is explicitly NOT the bar - a high-win-rate/negative-
expectancy strategy (tight target, wide stop) is exactly the failure mode
this criterion is designed to catch; PFnet is the actual money test.

**Open thread for a future session:** #5 (tightened-filter range breakout)
is the only non-dead-end signal from this batch. Next reasoned step (not
yet tried): the surviving `breakout_failed` trades in #5 are now fewer
but individually worse (avgGross -₹799 vs -₹487 in #3) - a tighter
stop or reduced size specifically for that residual failure mode is a
plausible next lever, not another new architecture from scratch.

## Range breakout follow-up: invalidation tightening (wash) + target-distance axis (2026-09-15)

Two more iterations on #5 above (`range-breakout-tightened-filters-research.yml`,
run 34927061777, PFgross 1.11/PFnet 0.03/n=528 - the pool's reference
point for this family), same 52-symbol/60-day/5m/real-cost harness.

**Invalidation tightening (`range-breakout-tight-invalidation-research.yml`,
run 34927912381) - a wash, not an improvement.** Moved the
`breakout_failed` invalidation trigger from `close<or_high` to the
tighter `close<breakout_level` (the entry's own buffered threshold), to
cut losses on fakeouts faster. Result: n unchanged (528), avgGross per
failed trade improved (-799→-477) but the failure bucket's share nearly
doubled (121→206/39.0%) because the tighter trigger also caught trades
that wobbled then recovered - PFgross flat (1.11→1.10), cost drag
**worse** (235.7%→265.0%). **Do not re-try tightening this specific
invalidation rule** - it trades loss size for loss frequency with no net
gain, same shape as the breakout-retest wash (#4 above).

**Target-distance axis (`range-breakout-nearer-target-research.yml` /
`-v2`, runs 34928561203 / 34929024597) - the best lever found this
session, capped at 3 points on purpose.** Evidence: in run 34927061777,
`breakout_timebox` was the largest bucket (281/528, 53%) with *positive*
avgGross (+299) - trades working but timing out before the full 1.0x
opening-range measured-move target, while the tiny `target_hit` bucket
(18 trades) averaged +2582. Hypothesis: a nearer target converts more of
that already-working bucket into actual hits.

| MEASURED_MOVE_MULT | n | win% | PFgross | PFnet | cost drag |
|---|---|---|---|---|---|
| 1.0x (run 34927061777) | 528 | 7.4% | 1.11 | 0.03 | 235.7% |
| 0.6x (run 34928561203) | 156 | 10.3% | 1.35 | 0.04 | 218.2% |
| 0.5x (run 34929024597) | 97 | 11.3% | **1.62** | **0.05** | 213.2% |

Every metric improved monotonically as the target moved closer - but n
shrank in lockstep (528→156→97) because a nearer target more often fails
the `ROUND_TRIP_COST_PCT` economic-viability gate outright (fewer trades
recorded at all, not the same trades cut short). This is the textbook
shape of curve-following into an ever-smaller, noisier sample, not
necessarily a genuinely strengthening edge - the 0.5x number in
particular should be read with that caveat, not taken at face value.

**Logged ceiling: 0.6x (run 34928561203)** - the strongest point that
still clears the n≥100 threshold agreed as part of the pool-entry bar.
PFgross 1.35 is the best pre-cost signal quality found all session
(above even the `universal_score` baseline's 1.12); PFnet 0.04 is still
far short of the ≥1.3 pool bar. **This axis is capped here per the
standing rule against repeated blind tuning - three points (1.0x, 0.6x,
0.5x) is enough to establish the direction and its overfitting risk; do
not keep pushing MEASURED_MOVE_MULT lower chasing a better single-run
number.** The 0.5x result is recorded for reference, not as the
recommended parameter.

**Recommendation for a future session:** this family (range breakout
momentum, tightened filters + or_high invalidation + 0.6x target) is the
strongest candidate from all of 2026-09-15's research, but still ~30x
short of the PFnet pool bar via exit/target tuning alone. Further
progress likely needs either (a) a genuinely different lever - e.g. the
cost side itself (segment/instrument choice, trade frequency reduction)
rather than another entry/exit rule variant on this family, since every
rule-level lever tried this session (entry filters, invalidation,
target distance) caps out in the same PFnet 0.03-0.05 band, or (b)
accepting NSE intraday cash-equity scalping at this cost structure may
not clear the bar at all and revisiting swing/multi-day horizons, which
pay round-trip costs far less often.

## Swing/daily-bar time horizon: cost mechanism confirmed, entry quality still unresolved (2026-09-15)

Following the recommendation above, tested a genuinely different time
horizon instead of another intraday rule variant: daily bars, multi-day
holds, chandelier trailing stop instead of a fixed target. Same
52-symbol universe, same cost model, same position-sizing formula as
every intraday test, but 2 years of daily bars instead of 60 days of 5m
bars.

**Swing breakout continuation** (`swing-breakout-continuation-research.yml`,
run 34929783550): 20-day Donchian breakout + rising-50-day-SMA trend
filter + 1.5x volume surge, tighter-of-(10-day-low, 2xATR) stop,
chandelier trail (running max close - 2xATR-at-entry, ratchets up only),
60-day max hold. Result: n=195, win 25.1%, **PFgross 0.72, PFnet 0.51**,
**cost drag 18.6%** (vs 200-550% on every 5m intraday test this session -
the cost-side hypothesis is confirmed: holding for weeks instead of
minutes means the ~0.8% round-trip is paid once against a much larger
targeted move, not repeatedly against thin 5-minute swings). 96.9% of
trades exited via the trailing stop at 23.8% win (chasing a fresh
breakout whipsaws most of the time - PFgross <1, still losing pre-cost).
The 3 trades that ran the full 60-day hold averaged +₹4,048 gross but
were too rare to carry the rest.

**Swing pullback continuation** (`swing-pullback-continuation-research.yml`,
run 34930361984) - same exit machinery, entry changed to buy a pullback
inside an established uptrend (trend filter unchanged + recent 20-day
high made within the last 10 days + close below the 20-day EMA +
green reversal day + volume ≥ average) instead of chasing a new high.
Result: n=59, win 25.4%, PFgross 0.81 (slightly better), **PFnet 0.42
(worse)**, cost drag 36.4% (worse, vs 18.6%) - the stricter filter found
marginally higher-quality setups but on a much smaller sample (59 vs
195) with a shorter average hold (12.2d vs 17.7d), so cost ate more of
a smaller edge. **Net conclusion: no improvement - the breakout entry
(run 34929783550) remains the better of the two swing results.** Do not
re-try this specific pullback filter unchanged; if revisited, the
sample-size/hold-time tradeoff needs addressing, not just the entry
condition.

**Where this leaves the swing-horizon thread:** the cost mechanism is
proven (18.6% is achievable, an order of magnitude better than any
intraday result this session), but neither entry tested clears PFgross 1
(pre-cost breakeven) with a comfortable sample. This is genuinely
unresolved, not a dead end like the VWAP family - the next reasoned step
is a swing entry with a real, evidenced trend-following edge (e.g. a
longer/slower Donchian window per the "Turtle" convention to reduce
whipsaws, or requiring a higher-timeframe/index-relative-strength
filter) rather than another quick variant, since two entries have now
been tried on this exit architecture without clearing PFgross 1.

## Swing breakout, slower Donchian window (2026-09-15) - best PFnet of the session, still short of the bar

Follow-up to the recommendation above:
`swing-breakout-slow-donchian-research.yml` (run 34930930995) - single,
isolated change from `swing-breakout-continuation-research.yml` (run
34929783550): the Donchian breakout lookback moved from 20 trading days
to 55 (Turtle Trading System 2 convention - trades less often, only on
much more established trends). The SMA-rising trend-filter's own
comparison window was deliberately kept at a separate, unchanged 20-day
constant, so this is a true single-variable isolation.

| Donchian window | n | win% | PFgross | PFnet | cost drag | avg held |
|---|---|---|---|---|---|---|
| 20-day (run 34929783550) | 195 | 25.1% | 0.72 | 0.51 | 18.6% | 17.7d |
| 55-day (run 34930930995) | 163 | 25.2% | **0.77** | **0.55** | 18.1% | 18.2d |

Every metric moved the right direction (whipsaw share via `trail_stop_hit`
dropped slightly, 96.9%→95.7%) - confirms the hypothesis, and **0.55 is
the best PFnet of every strategy tested this session** (11 total,
including the `universal_score` baseline at 0.05). Still PFgross <1
(losing pre-cost) and far short of the PFnet≥1.3 pool bar - a real,
modest improvement, not a breakthrough. Standing discipline note: no
strategy from this session has cleared the pool bar, so nothing has been
wired into `main.py` or the live WATCHLIST despite this being the
session's best result - see this log's "Pool bar for going anywhere near
production" entry above, which still applies unchanged.

**Open thread:** the dominant remaining problem is unchanged from the
20-day version - `trail_stop_hit` is still >95% of trades at ~24% win.
Next reasoned step (not yet tried): a higher-timeframe or index-
relative-strength filter (only take breakouts in stocks outperforming
NIFTY over the same lookback), which targets *which* stocks to trade
rather than *when* to enter one - a different axis from both the entry
timing changes tried so far (fresh breakout vs pullback vs slow
breakout).

## Swing Fibonacci retracement (2026-09-15) - best win rate, not the best money result

Explicit user request to try a genuinely different technical method
(not another Donchian/EMA-pullback variant). `swing-fibonacci-
retracement-research.yml` (run 34931590052): buys the 38.2%-61.8%
"golden pocket" retracement of a recent significant swing (40-day
lookback, min 3% swing size) in an established uptrend (same 50-day
rising-SMA filter as every prior swing test), confirmed by a green
reversal day and volume participation; stop at the 78.6% retracement
level or 2xATR, whichever tighter. Same proven exit machinery
(chandelier trailing stop, 60-day max hold) as the Donchian tests.

| signal | n | win% | PFgross | PFnet | cost drag |
|---|---|---|---|---|---|
| 55-day Donchian breakout (34930930995, current best) | 163 | 25.2% | 0.77 | **0.55** | 18.1% |
| Fibonacci golden-pocket retracement (34931590052) | 41 | **34.1%** | 0.69 | 0.45 | 22.6% |

Fibonacci found real support more often (34.1% win rate - the best of
any swing test this session) but the wins weren't proportionally large
enough relative to losses to beat Donchian on PFgross/PFnet, and the
much smaller sample (41 vs 163 trades - the golden-pocket condition is
a rare, narrow setup) makes this read less reliable regardless.
**Verdict: does not beat the 55-day Donchian breakout - that remains
the swing family's best result (PFnet 0.55).** Not a dead end (a real,
different edge is visible in the win-rate number), but not yet
competitive on the metric that matters. If revisited, the open question
is whether the golden-pocket win rate can be paired with a
proportionally larger target/trail (the entry is finding real turns,
the exit isn't capturing enough of the subsequent move relative to the
losers) - a different lever than anything tried on this entry so far.

## Swing breakout + index relative-strength filter (2026-09-15) - null result, filter redundant with existing entry

Per the "different axis" recommendation above: layered a classic index
relative-strength filter (stock's trailing 60-day return > NIFTY 50's
own trailing 60-day return) onto the swing family's best entry (55-day
Donchian breakout, run 34930930995) - `swing-breakout-relative-
strength-research.yml`, run 34933815366.

**RS filter funnel: 166 candidates -> 157 passed -> only 9 rejected
(5.4%).** Almost every 55-day-breakout-in-a-rising-uptrend candidate
already outperforms NIFTY over a similar window - the two filters
overlap heavily, so this is a near-null result, not a failed
implementation.

| | no RS filter (34930930995) | + RS filter (34933815366) |
|---|---|---|
| n | 163 | 157 |
| PFgross | 0.77 | 0.78 |
| PFnet | 0.55 | 0.56 |
| cost drag | 18.1% | 18.0% |

Essentially unchanged (6 trades differ between the two runs; the same
top performers - VEDL.NS, POLYCAB.NS, MARUTI.NS - appear in both).
**Verdict: a binary vs-index relative-strength check adds nothing on
top of an already-strong trend/breakout/volume entry filter - do not
re-try this exact check.** If the "which stocks" axis is revisited, it
needs a genuinely independent signal from the entry timing filters
already in place - e.g. RS *ranking* across the whole universe (trade
only the top decile by RS, not just "beats the index at all") or a
sector-relative-strength angle, not another binary threshold that a
strong breakout entry already implies.

## Swing Fibonacci retracement, wide trail (2026-09-15) - closed most of the gap to the swing champion

Follow-up to `swing-fibonacci-retracement-research.yml` (run
34931590052: win 34.1%, PFgross 0.69, PFnet 0.45 - best win rate of any
swing test, but the exit wasn't capturing enough of the subsequent move
relative to the losers, per this log's own diagnosis). Single, isolated
change (`swing-fibonacci-wide-trail-research.yml`, run 34934362142):
`ATR_STOP_MULT` 2.0x -> 3.0x, applied identically to both the initial
stop and the chandelier trailing stop - same convention as every other
swing test, not cherry-picked to only widen one side.

| | 2.0x ATR trail (34931590052) | 3.0x ATR trail (34934362142) | swing champion (55-day Donchian, 34930930995) |
|---|---|---|---|
| n | 41 | 40 | 163 |
| win% | 34.1% | **40.0%** | 25.2% |
| PFgross | 0.69 | 0.76 | 0.77 |
| PFnet | 0.45 | **0.53** | 0.55 |
| cost drag | 22.6% | 19.2% | 18.1% |
| avg held | 19.3d | 27.9d | 18.2d |

`max_hold_timeout` jumped from 1 trade to 7 (all 100% win, avgGross
+3,233) - the wider trail let positions that would have been stopped
early survive to the 60-day cap as full winners instead of getting cut
off mid-move. Confirms the diagnosis directly: the entry was finding
real turns, the tighter trail was the bottleneck, not the entry. **This
is now the second-best PFnet of all 14 strategies tested this session,
essentially tied with the swing family's Donchian-breakout champion**
(0.53 vs 0.55) - still short of the PFnet>=1.3 pool bar, nothing
patched into `main.py` or the live system.

**Open thread:** the swing family now has two independently-discovered,
near-tied best results (55-day Donchian breakout, Fibonacci golden-
pocket + wide trail) both landing around PFnet 0.53-0.55. Worth testing
whether the wide-trail (3.0x ATR) change also helps the Donchian
breakout entry, since it was only tried on Fibonacci so far - if it's a
generically better exit for this whole family (not specific to
Fibonacci), that's a cleaner, more valuable finding than either entry
alone.

## Swing RSI(2) mean reversion - Larry Connors' published system, out-of-sample on NSE (2026-09-15)

Explicit user instruction: search the web for well-documented, published
strategies and validate them, rather than only inventing new ones from
reasoning. Found Larry Connors' 2-period RSI mean reversion (published
backtests on US equities/indices report 75-79% win rates over 10+
years - StockCharts ChartSchool, QuantifiedStrategies.com, Connors'
own research). Implemented faithfully to the canonical rules: close >
200-day SMA, entry when RSI(2) closes < 10, exit when RSI(2) closes >
70. Two disclosed additions NOT in the published system (which has no
hard stop): a 2.0x ATR protective stop and a 10-day max-hold backstop.
`swing-rsi2-mean-reversion-research.yml`, run 34935693401 - this is a
genuine out-of-sample test, Connors' own research is entirely US
large-cap data, never NSE.

**Result: n=454, overall win 51.5% (highest of any strategy tested this
session), PFgross 1.04, PFnet 0.45, cost drag 37.4%, avg held 4.6d.**

By exit reason - this is the real story:

| reason | n | %total | win% | PFgross | avgGross |
|---|---|---|---|---|---|
| rsi_reverted (intended exit) | 348 | 76.7% | **67.0%** | 13.94 | +837 |
| stop_hit (our added stop, not Connors') | 76 | 16.7% | 0.0% | 0.00 | **-3,241** |
| max_hold_timeout | 19 | 4.2% | 5.3% | 0.01 | -1,344 |
| data_end_forced_close | 11 | 2.4% | 0.0% | 0.00 | -796 |

**When the reversion completes as designed (76.7% of trades), win rate
is 67.0%** - below the published 75-79% but a real, substantial
transfer of the edge to NSE on a solid sample (n=348), not noise. The
PFnet shortfall vs the session's other swing leaders (0.45 vs Donchian's
0.55, Fibonacci-wide-trail's 0.53) comes from the stop_hit tail: our own
added protective stop fires on 16.7% of trades and loses ~4x the size of
a typical win when it does - the classic mean-reversion risk shape
(frequent small wins, rare large losses), compounded by high cost drag
(37.4%, since ~4.6-day holds mean the fixed round-trip cost eats more of
a smaller average gross move than the multi-week trend trades).

**Open thread:** the stop is our own disclosed addition, not part of
Connors' published system - refining it is not re-litigating a
validated strategy. Worth testing a tighter stop (e.g. 1.0-1.5x ATR
instead of 2.0x) to cut the large-loss tail while the 67% reversion win
rate stays intact - a plausible path to a better PFnet than either
current swing leader, since the entry itself is already the strongest,
most literature-supported edge found all session.

## RSI(2) mean reversion, tighter stop 1.5x ATR (2026-09-15)

Follow-up to the open thread above: tightened the RSI(2) protective stop
from 2.0x ATR(14) to 1.5x ATR(14), everything else unchanged (canonical
Connors entry/exit, 10-day max-hold, 52-symbol universe, cost model).
`swing-rsi2-tighter-stop-research.yml`, run 35011175664.

| metric | 2.0x ATR (baseline) | 1.5x ATR (this test) |
|---|---|---|
| n | 454 | 467 |
| win% | 51.5% | 51.0% |
| PFgross | 1.04 | 1.06 |
| PFnet | 0.45 | **0.46** |
| cost drag | 37.4% | 37.8% |

By exit reason (1.5x ATR run): `rsi_reverted` n=337, 70.0% win, PFgross
28.69, avgGross +1,218 (both win rate and avgGross improved vs the 2.0x
run's 67.0%/+837 - the tighter stop does cut some losers before they
revert). `stop_hit` n=112 (up from 76 at 2.0x), 0% win, avgGross -3,266
(essentially the same size loss as before, -3,241). `max_hold_timeout`
n=10, `data_end_forced_close` n=8.

**Verdict: marginal, not a fix.** PFnet moved 0.45 -> 0.46, within noise.
Tightening the stop converted more trades into stop-outs (76 -> 112, a
47% increase) without shrinking the average loss size when it does hit
(-3,241 -> -3,266, essentially unchanged) - so the large-loss tail this
test was meant to fix is just as large and now hits more often, offset
almost exactly by the improved win rate/avgGross on the surviving
`rsi_reverted` trades. Does not beat either session champion (Donchian
0.55, Fibonacci-wide-trail 0.53). Not worth pushing further on the stop
axis alone; the RSI(2) entry's edge is real but this exit architecture
caps it around PFnet ~0.45-0.46 regardless of stop width in the
1.5x-2.0x range tested.

## Supertrend flip - implementation bug caught and fixed (2026-09-15)

Per user request to search for a strategy popularized by trading
YouTubers (as a genuinely different source from the academic/published
research used for the Donchian, Fibonacci, and Connors RSI(2) tests),
found the Supertrend indicator flip strategy (ATR period 10, multiplier
3.0) - one of the most widely taught retail swing-trading signals on
YouTube. Canonical rules: close>200SMA trend filter, entry on bullish
Supertrend flip, exit on bearish flip (the indicator's own line is the
trailing stop), plus a disclosed 60-day max-hold backstop (not part of
the canonical indicator, added for real-money discipline as with every
other swing test this session).

**First implementation run (35011610436) reported 0/0 trades across all
52 symbols** - correctly treated as a suspicious/degenerate result per
CLAUDE.md's standing instruction to verify replay correctness rather
than trust a result at face value, not logged as a "no signal" finding.

**Root cause**: the Supertrend "sticky" final_upper/final_lower band
recursion was seeded from `atr[0]`, which is NaN (index 0 has no
previous close, so true range at index 0 is undefined). At `i==0` the
code wrote this NaN into `final_upper[0]`/`final_lower[0]`. Every
subsequent iteration's sticky-band update compares the current basic
band against the *previous* final band
(`basic_lower[i] > final_lower[i-1]`) - but any comparison against NaN
in numpy evaluates `False`, so the update always fell through to `else
final_lower[i-1]`, which was itself NaN. The NaN silently propagated
through the entire recursion for the rest of the series, `direction`
never flipped from its initial seed value, and no entry/exit condition
ever fired for any symbol.

**Fix** (commit `90859a8`): treat a NaN previous final_upper/final_lower
as an additional reset condition (alongside `i==0` and `np.isnan(atr[i])`),
so the recursion re-seeds from the fresh basic bands as soon as ATR
becomes valid. Verified locally on synthetic OHLC data before re-running
live: direction flipped 10 times over 500 bars post-fix vs 0 times
pre-fix. Re-ran on `main` after merge (run 35012311949) and got a
non-degenerate result (see next entry) - confirms the fix, not a
coincidental pass.

**Why this matters beyond this one test**: this is the exact failure
mode CLAUDE.md's incident-prevention section warns about in a different
form - a broken/drifted implementation silently producing a result that
looks like a real finding (here, "0 trades" could easily have been
mis-logged as "strategy has zero edge on NSE" instead of "the code is
broken"). Caught by treating an all-zero/degenerate result as suspicious
rather than trusting it, not by luck.

## Supertrend flip, corrected result (2026-09-15)

`swing-supertrend-flip-research.yml`, run 35012311949 (post-bugfix).

| metric | value |
|---|---|
| n | 135 |
| win% | 38.5% |
| PFgross | 1.01 |
| PFnet | **0.77** |
| cost drag | 13.7% |
| avg held | 32.8 days |

By exit reason:

| reason | n | win% | PFnet | PFgross | avgGross | avg held |
|---|---|---|---|---|---|---|
| max_hold_timeout | 22 | 100.0% | inf | inf | +4,223 | 60.0d |
| supertrend_flip_bearish (intended exit) | 109 | 25.7% | 0.23 | 0.33 | -868 | 27.3d |
| data_end_forced_close | 4 | 50.0% | 1.71 | 2.51 | +690 | 32.8d |

**New session-best PFnet (0.77), beating both prior champions** (Donchian
breakout 0.55, Fibonacci-wide-trail 0.53) **and clearing n>=100** (135
trades) - but still well short of the 1.3 pool bar, so this does not
change anything about production candidacy (nothing has cleared the
bar; nothing is wired into `main.py` or the live WATCHLIST).

The interesting structural finding is in the exit-reason split: the
**intended exit (Supertrend flip) is a net loser** (PFnet 0.23, 81% of
trades) - most flips happen after the trend has already given back most
of its gains, since the indicator only exits after price closes back
below the trailing line. All of the strategy's positive expectancy comes
from the **60-day max-hold backstop** (n=22, 100% win rate, PFnet inf,
avgGross +4,223) - trades still open and profitable at the 60-day mark
get forced closed while still winning, effectively capturing the
still-in-progress strong trends before the (lagging) flip exit can give
them back. This is the same "wide trail wins" pattern seen in the
Fibonacci-retracement test (#2 vs #5 in the leaderboard), now showing up
independently in a completely different indicator family - suggestive
that trailing-stop *distance*, not entry signal choice, may be the
larger lever across this session's trend-following swing tests. Low cost
drag (13.7%, the lowest of any swing test) is a direct consequence of
the long 32.8-day average hold: fewer round-trips per unit of time held,
so the fixed per-trade cost eats a smaller share of a larger average
gross move.

**Open thread**: worth testing whether widening the max-hold backstop
further (or removing it and instead trailing looser, e.g. a lower
Supertrend multiplier that flips less eagerly) pushes more trades into
the profitable "still running" bucket instead of the lagging flip-exit
bucket - directly testable without re-litigating the entry signal, which
already clears this session's decisively-not-a-dead-end bar (session
new-best PFnet on a real out-of-sample structural mechanism).

## Supertrend wide-trail 4.0x ATR - hypothesis tested, refuted (2026-09-15)

Follow-up to the corrected Supertrend flip result's open thread: widened
the ATR multiplier 3.0 -> 4.0 (everything else unchanged: ATR period 10,
close>200SMA filter, 60-day max-hold, universe, cost model), to test
whether a looser trail pushes more trades into the profitable
"still-running" state the max-hold backstop was capturing at 3.0x.
`swing-supertrend-wide-trail-research.yml`, run 35013216418.

| metric | 3.0x ATR (current champion) | 4.0x ATR (this test) |
|---|---|---|
| n | 135 | 89 |
| win% | 38.5% | 38.2% |
| PFgross | 1.01 | 0.92 |
| PFnet | **0.77** | 0.71 |
| cost drag | 13.7% | 13.1% |
| avg held | 32.8d | 40.2d |

By exit reason (4.0x run): `max_hold_timeout` n=27 (up from 22), win%
dropped to 85.2% (from 100%), avgGross +2,332 (down from +4,223).
`supertrend_flip_bearish` n=56 (down from 109, as expected - wider band
flips less often), win% dropped further to 14.3% (from 25.7%), avgGross
worsened to -1,312 (from -868). `data_end_forced_close` n=6, avgGross
+647.

**Verdict: hypothesis refuted, PFnet got worse (0.77 -> 0.71), not
better.** Widening the trail cuts both ways and the downside dominates:
yes, fewer trades reach the flip exit (109 -> 56), but the wider band
also lets losing trades bleed further before that already-lagging exit
finally fires, so each flip-exit loss got bigger (-868 -> -1,312) even
as win rate on that bucket fell (25.7% -> 14.3%). It also diluted the
max-hold bucket's quality (100% win/+4,223 avgGross -> 85.2% win/+2,332
avgGross) - some of the extra 60-day-timeout trades are marginal
positions that a tighter trail would have exited earlier as flat/small
losses, not the clean strong-trend winners the 3.0x version was
selecting for. Net: the trail-width axis does not have more room to the
wide side; 3.0x (the canonical setting, also the current session
champion at PFnet 0.77) stays the leader on this entry family.

**Do not push further wide on this axis** (5.0x+ ATR) - the direction is
already shown to be net negative, this is the second data point after
3.0x baseline confirming it, not a single-result judgment call. The
actual defect (the flip exit itself lags and gives back gains) is
structural to how Supertrend's own line trails, not fixable by widening
the same mechanism further. A different fix shape (e.g. a partial-profit
take once a trade is deep in gain, decoupled from the trailing exit
entirely) is a bigger design change than a parameter nudge and would be
a new test, not a variant of this one.

## How to use this log going forward

1. On a new setup/pattern read, compare it against the **Best-fit condition** column — pick the
   closest match instead of designing from scratch.
2. If nothing fits, add a new row with legs, condition, and `status: Proposed`.
3. Before paper/live use, run it through `/sweep` on the Render server and flip `status` to
   `Tried — robust` or `Tried — not robust` with the result noted.
4. Never skip straight to "live" — paper-trade first per the project's standing rule (see the
   session Transfer Pack: paper-trading only until explicit go-ahead).
