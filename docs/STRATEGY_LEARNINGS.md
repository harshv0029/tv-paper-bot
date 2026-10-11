# Strategy learnings (durable, one entry per strategy or idea discussed)

Rule (CLAUDE.md, 2026-10-11): every new strategy or idea we discuss gets an entry here in the same commit as its backlog row,
with the important items (and a closing "Profit-booking / exit takeaway" line): the mechanism, why it should or should not work in THIS system (NSE/MCX, Kotak, costs, FIFO, no
unstopped trades), what the backtest showed (tags, PFnet, n), what broke or surprised us, and what to reuse next time.

## Overnight anomaly (night vs day), video 2026-10-11, B-363/B-364
- Mechanism: buy close, sell next open (night); short open, cover close (day). Edge is real gross: night long about +0.17% per night on NIFTY 200.
- Lesson: a daily flip pays the round-trip cost every session; at 0.8% it erases any sub-0.5% edge. Check gross edge vs cost before building.
- Result: all four legs fail (PFnet 0.07 to 0.36); stopped day variants identical. Night legs cannot carry a firing stop (market closed).
- Reuse: any high-frequency or tiny-edge idea needs gross edge above about 1% per trade at this cost model.

## Microstructure / pro-rata market making, video 2026-10-11, B-365/B-366
- Mechanism: quote both sides, capture spread, pro-rata fills favour size (CME rate futures).
- Lesson: NSE/MCX are price-time (FIFO); no tick/L2/L3 history; unhedged inventory violates no-trade-without-SL.
- Reuse: order-book imbalance from Kotak depth is the one testable piece (B-366): record snapshots first, backtest later.

## MCX daily cells and the stop question, 2026-10-11, B-355/B-362
- Lesson: a backtest without a stop is not evidence for a stopped live trade. Of 27 no-stop PFnet>1 cells only 8 kept PFnet>=1.1 when ATR-stopped (1.5 and 2.5).
- Rule of thumb: wire a cell only if every stopped variant clears the floor, not just the headline one.

## Option strikes: indicator strategies, 2026-10-11, B-356/B-359
- Lesson: equity-daily PFnet does not transfer to option-premium candles; unmeasured means gated closed. Record shadow signals first, backtest on premium history, then wire.

## Viable floor 1.1, 2026-10-11, B-360
- Lesson: raising the floor from 1.0 to 1.1 closed 117 of 218 wired cells automatically; borderline cells (1.0 to 1.1) are noise-level after costs.

## Standing principle (user, 2026-10-11)
- The only aim of this bot is profit from every trade it takes. Use this file before every strategy, sizing, exit or profit-booking decision.

## Profit-booking / exit takeaways so far
- Overnight anomaly: a 1-bar hold has no room for 0.8% cost; prefer holds where average gross win per trade is several times the cost.
- MCX: exits must be the stop the backtest assumed; no-stop edges did not survive a 1.5 to 2.5 ATR stop for 19 of 27 cells.
- OB/VP history: edge sat on 30-day survivors while trail stops lost; wide stops plus long holds, not tight trails, carried those PFnets.
- Faster turnover is preferred only among equal-edge variants; cost per trade decides whether fast is viable at all.


## Supply & Demand Morning Star + Break of Structure (retest entry), video 2026-10-11, B-370
- Mechanism: downtrend (lower highs/lows) -> star at support -> bullish c3 -> close above last lower high (BOS) -> limit buy on the star-zone retest, SL below star low, TP at supply origin, min R:R 1.5 to 2. Short mirror = evening star + bearish BOS.
- Fit: it is a stopped, limit-entry, target-exit setup, so it satisfies no-trade-without-SL by design and has defined exits. Swing/day-trade candidate on stocks; options variant only after a premium backtest.
- Pattern is strict (few trades per symbol); needs the full universe for a usable n. Bars-based expiry (15 bars) and hold (30 bars) change meaning with candle size, so each size is its own result.
- Profit-booking / exit takeaway: target at structural origin with R:R floor is a defined profit-booking rule; compare its realised R against the trail-stop families when results land.

### Overnight anomaly, full-universe confirmation (2026-10-11)
- 2.4M trades per cell: best leg day short PFnet 0.582, night long 0.449 (avg net -0.41% per trade). The anomaly exists gross but the 0.8% cost is bigger than the whole edge on NSE.
- Profit-booking / exit takeaway: single-bar holds cannot be profit-booked after this cost; only multi-day holds with large average wins survive.

## RSI(10) pullback above SMA200 (daily), user video 2026-10-11
- Mechanism: buy an oversold dip (RSI10<30) only while price is above the 200-day SMA; exit on RSI recovery >40, 10-day time stop, stop under swing low. Classic short-horizon mean reversion (Connors-style).
- Fit here: swing-style and natively carries a stop (passes no-trade-without-SL). Concern: the 0.8% round trip is large against typical 2-4% mean-reversion bounces; a claimed 78% win rate says nothing about PFnet and omits costs. The video's backtest link was dead, so nothing is verified; we rebuilt it.
- Test: scripts/rsi_pullback_sma200.py, both directions, sweep entry/exit RSI and swing lookback. Results pending (B-372).
- Profit-booking / exit takeaway: pending results; an RSI-recovery exit books profit in about 3-5 bars if it works, so turnover is fast (good under the faster-capital rule).

## Intraday liquidity screen + morning Order Block retest scalp, user video 2026-10-11
- Mechanism: pick the highest-RVOL stocks in the first 30 min, trade the direction of the early bias, enter by limit on a retest of the small candle before a volume impulse (the "order block"), exit on a pin bar or SL beyond the block.
- Fit here: has an SL (OK). Core risk: scalps target moves of roughly 0.3-1%, and our 0.8% round trip eats most of it; intraday needs an engine that does not exist yet (B-358). yfinance gives only 60 days of 5m/15m, so n is small and a weak result is thin evidence either way. Related earlier finding: order_block_delta swing cells only work as 30-day holds, not quick exits.
- Test: scripts/intraday_ob_scalp.py (screened vs unscreened to isolate the value of the liquidity screen). Results pending (B-373).
- Profit-booking / exit takeaway: pending; pin-bar exits cut winners short, so expect small average gains against fixed 0.8% cost.

### Update 2026-10-11 IST (results)
- Morning Star + BOS 1d: n200 had <30 trades; full universe long retest PFnet 1.22 (trim1 1.08, win 27.5%, n=51). Very rare setup, low win rate, profit comes from 1.5-2R winners, so one outlier moves it; not wired. Rarity is the lesson: strict multi-condition SMC patterns yield too few trades to trust.
- RSI10 pullback n200 (long, stop under 5-10 bar swing low): PFnet 0.58-0.85 (30% win, n=1574 at RSI<30). The video's 78% win rate does not survive a real stop plus 0.8% cost; tight swing-low stops get hit before the bounce. Short mirror 0.58-0.93. Full-universe run pending.
- Profit-booking / exit takeaway: tight structural stops on mean-reversion dips lower the win rate sharply; if revisited, test the stop at 2-3 ATR or time-stop only (still needs an SL on the order).

## Six prompt strategies (screenshots, 2026-10-11): Silver Bullet, ORB, 9/21 EMA, Gap Fill, Order Block Retest, FVG Fill
- Mechanisms: Silver Bullet = liquidity sweep of prior-day extreme then FVG limit at midpoint, target opposite liquidity. ORB = first-15-min breakout, half off at 1x range, trail the rest. 9/21 EMA = trend cross with swing stop and breakeven at 1R. Gap Fill = fade >=0.5% gap to prior close. OB retest = limit at last opposing candle after a swing break. FVG fill = retrace into a trend-aligned gap, half at swing.
- Fit here: all have stops (OK) but five are intraday scalps; we have no intraday engine (B-358) and 0.8% round trip is large against intraday targets of 0.3-1%. Prompts are written for NQ/ES/EURUSD/GBPUSD (futures/forex, session times in NY/London), so sessions, tick sizes ("6 points") and cost are not transferable and had to be re-derived for NSE (adaptations in backlog rows B-375..B-380). yfinance limits 5m/15m to 60 days, so n is modest; weak results are thin evidence, strong results are suspect.
- Results: pending.
- Profit-booking / exit takeaway: pending; scale-out (ORB/FVG) halves fixed cost impact only if the first target clears 0.8% by a wide margin.

### Update 2026-10-11 IST (RSI10 full, intraday OB scalp)
- RSI10 pullback full universe: best PFnet 0.95 (long) / 0.92 (short); stop-under-swing-low plus 0.8% cost kills it. Not viable.
- Intraday liquidity-screen + OB scalp 5m n200: PFnet 0.06, win 9%, avg -0.79% per trade, i.e. almost exactly the round-trip cost: the pin-bar exit earns ~0 gross, so cost is the whole loss. Lesson: intraday scalps with sub-1% gross targets cannot clear 0.8% costs on NSE equities; any intraday idea must show gross edge well above 1% per trade first.
- Profit-booking / exit takeaway: when average net is about minus the cost, exits are not the problem, edge is absent; don't tune exits.

## VWAP "Return to Value" failed discovery, user video 2026-10-11
- Mechanism: trade the confirmed failure of a move outside VWAP +/-1.5 sigma (>=2 closes outside, then close back inside); target VWAP, or the opposite band; stop at the excursion extreme; RR>=1.5 filter.
- Fit here: has a stop (OK); intraday so needs engine B-358; related to our earlier RANGE-regime VWAP mean-reversion (failed at 5m, PFnet < 1). A VWAP target is typically 0.3-0.8% away, close to the 0.8% cost, so only the tp2 (opposite band) variant has room. Model B (retest limit) can miss fills in fast reversals; backtest assumes fill at the band.
- Results: pending (B-382).
- Profit-booking / exit takeaway: pending; the RR>=1.5 gate selects wide-stop setups, check whether average winner clears cost.

### Update 2026-10-11 IST (six prompt strategies, 5m/15m NIFTY 200 results)
- All ten cells fail: PFnet 0.00-0.11, average net about -0.8% = the round-trip cost, so GROSS edge is about zero (ORB +0.02%, Silver Bullet short +0.06%, Gap Fill -0.1% gross). This is not a cost-model artifact: even at a 0.2% cost none would reach 1.0. Win rates of 1-19% come from stops/pin exits that sit within noise of entry.
- Lesson: futures/forex-pitched ICT/SMC prompts (Silver Bullet, FVG, OB) show no edge on NSE equities at 5-15m. They rely on session liquidity and index-futures microstructure; NSE stocks have different opening auction behaviour. Before building anything intraday, require positive GROSS expectancy first.
- Profit-booking / exit takeaway: scale-outs (ORB half at 1x range) did not rescue a zero-gross-edge entry; exits cannot create edge.

## Exhaustion Mean Theory (EMT), user video 2026-10-11
- Mechanism: fade a stretch from VWAP and EMA9 after a long-wick exhaustion candle, entering only when the next bar breaks the exhaustion bar's extreme (confirmation), stop beyond the wick, target VWAP.
- Fit here: has a stop (OK). The stretch filter (>=0.5-1% from VWAP) makes the VWAP target at least as large as the 0.8% cost only at the 1% setting, so expect few trades at the loose setting and cost drag. Intraday, so needs engine B-358; related to the earlier failed RANGE-VWAP short and B-382.
- Results: pending (B-384).
- Profit-booking / exit takeaway: pending; target at VWAP caps the winner, the stop at the wick is small, so check average winner vs cost.

### Update 2026-10-11 IST (9/21 EMA crossover, 1h NIFTY 200)
- Long PFnet 0.71 / short 0.44 over 20k trades each: trend-cross whipsaws, 77% of trades lose, average net -0.45% long. Classic moving-average crosses have no edge after the 0.8% cost on NSE equities; the short mirror is worse (equities drift up). Breakeven-at-1R and cross-back exits did not fix it.
- Profit-booking / exit takeaway: breakeven moves convert many trades to near-zero-minus-cost losses; they cost more in fees than they save when the underlying edge is absent.

### Update 2026-10-11 IST (EMT 5m, VWAP return-to-value 15m)
- EMT 5m: PFnet 0.04-0.22; avg net about -0.8% again, so VWAP-stretch fades have no gross edge on NSE equities at 5m. The stricter 1% stretch only produced 32-44 trades and still fails. VWAP return-to-value 15m: PFnet 0.01-0.03, win 2-8%; the VWAP target (tp1) was worse than the opposite-band target (tp2) as the move to VWAP is smaller than cost.
- Pattern across today's 9 intraday ideas: every cell ends near gross zero. Stop testing intraday NSE-equity mean-reversion/SMC variants at 5-15m; the evidence is now broad (hundreds of thousands of trades). Remaining profit comes from swing/daily cells and MCX/options with trailing SL.
- Profit-booking / exit takeaway: targets nearer than ~1% from entry cannot pay the 0.8% cost; require target distance >= 2x cost before testing an exit design.

### Update 2026-10-11 IST (VWAP RTV 5m, EMT 15m)
- Same result at every candle size: VWAP return-to-value 5m PFnet <= 0.04; EMT 15m best 0.29 on 36 trades. Candle size does not rescue a zero-gross-edge fade. Do not re-test VWAP/EMA-stretch fades on NSE equities.
- Profit-booking / exit takeaway: unchanged: targets within ~1% of entry cannot clear the 0.8% cost.

### Update 2026-10-11 IST (Morning Star + BOS 1h n200)
- 1h n200 produced <30 trades (empty), like 1d n200. The pattern is too rare on 200 stocks at coarse candles; only the full universe (1d, n=51) gave a usable sample. 15m/5m n200 dispatched (run 38111708043 for 15m).

## Intraday data recorder (B-389, 2026-10-11 IST)
- Why: all intraday tests are capped at yfinance's 60 days (one regime), so a weak or strong result is thin evidence. Recording 5m candles daily builds a private history beyond that cap; after ~6 months an intraday test can span regimes. Not a strategy; it improves every later intraday verdict.
- Fit: research data only, no orders, no kill switch, writes to git branch not Render disk. Learned: GitHub schedules only fire from the default branch, so the cron needs a main merge; the run is idempotent so gaps self-heal within 60 days.
- Profit-booking / exit takeaway: none yet; revisit intraday exits only after >=3 months of recorded data shows a positive gross edge.

## Fibonacci Golden Zone (0.618-0.79) + FVG, user video 2026-10-11
- Mechanism: in an uptrend, buy a rejection candle when price retraces to the 61.8-79% zone of the last up-leg, ideally where an FVG from the leg overlaps; stop under the swing low, target the swing high.
- Fit here: native stop (OK), swing hold up to 30 bars (viable under the 30-day rule). Reward is only 0.21-0.38 of the leg when entered at 0.618-0.79 versus risk of 0.62-0.79 of the leg, so winners are smaller than losers and need a win rate above about 70% to pay; plus 0.8% cost, so legs <6% are excluded. Swing anchors are hindsight-prone: pivots are used only after PV bars of confirmation.
- Results: pending (B-390).
- Profit-booking / exit takeaway: pending; TP at swing high gives reward/risk below 1 at deep retraces, expect profit from high hit rate only.

### Update 2026-10-11 IST (Fibonacci golden zone + FVG, daily full universe)
- Long PFnet 0.87 (FVG-confirmed) / 0.84 (all setups); short 0.76 / 0.73; n 24k-43k per cell, win 40-45%. FVG confluence barely matters (+0.02). Average losses (-0.65%) show the reward/risk problem: entering at 0.618-0.79 of the leg with a target at the swing high pays 0.26-0.62 of the leg against a stop of the full retracement, so a 40% hit rate cannot pay after 0.8% cost.
- Do not revisit Fibonacci retracement entries with swing-low stops; a tighter structural stop (e.g. under the rejection candle) is the only variant with room, and is not specified in the video.
- Profit-booking / exit takeaway: TP at the prior swing high gives reward/risk < 1 for deep retracements; a partial at 0.5R plus trail is untested.

## 2026-10-11 - Why only ~93 of 287 viable tags are wired (B-403 audit)
- Mechanism: a tag is "wired" iff it is a key in `_STRATEGY_TAG_TO_REGISTRY_NAME`; generic cell lists (`docs/pattern_live_cells.json`, `docs/mcx_live_cells.json`) add tags without main.py edits, then the PFnet >= 1.1 gate applies.
- Most unwired viable cells are `atrnone` (no stop in the backtest). They cannot be wired under "no trade without SL"; the fix is to re-test them with an ATR stop, not to relax the rule.
- The 30 minervini lab variants and a few starc/intermarket/keltner cells have stops but no main.py signal port: porting + main.py-function replay is the real work.
- Profit-booking / exit takeaway: a backtest edge that only exists without a stop is not tradable edge here; always sweep a stopped variant first, since the stop is what the live exit will actually be.

## 2026-10-11 - Minervini lab variants share one signal (B-412)
- The 30 viable lab cells are exit/filter variants of ONE entry signal (`minervini_vcp_entry_signal`). The swing engine holds one position per symbol, so variants are alternatives, not additions: wire the single best real-function-validated exit (3R breakeven, PFnet 1.153), not all 30.
- Lab numbers (breakeven_after_1r 1.382, ma200_break 1.354, rr3 1.332) come from a reimplementation; only the breakeven 2R/3R exits were validated through the real main.py function. Prefer validated over higher-but-unvalidated until a replay confirms.
- Filter subsets (n 52-63) picked after the fact from one sample are overfit risk.
- Profit-booking / exit takeaway: moving the stop to breakeven after 3R lets winners run while capping the downside; the chandelier trail on the same entries lost (PFnet 0.908).

## 2026-10-11 — B-413: which viable cells to wire, and metric provenance
- **Mechanism:** a registry cell is only worth wiring if it has a live signal fn, a real stop, and n large enough to trust. Of the leftovers: dominated variants (order_block 4.5x vs wired 6.0x) and thin cells (n=25/33) are skipped; starc fade_full (n=9221) is the only real candidate and needs a main.py port + replay.
- **Fit to this system:** a 52-symbol PFnet (gap_and_go 1.65) overstated the full-universe number (1.31 at the live 30-day hold). The gate should read the full-universe figure; it also carries win % and hold time, which the old row never had.
- **Surprise:** the dashboard showed "no registry entry" because the 7.8 MB all-strategies payload (29k tags) timed out, not because the entry was missing. Ship only what the page needs.
- **Profit-booking / exit takeaway:** gap_and_go earns its PFnet from the 30-day max-hold survivors (win 80%) while gap-fill and stop exits all lose; booking early would cut the edge, so keep the full hold and the frozen stop.

## 2026-10-11 — Keep every backtest field; viability is derived, not stored
- **Mechanism:** the PFnet floor has moved 1.0 -> 1.1 and may move again (hold limits, win rate, sample size). If only a pass/fail flag were kept, each change would force re-running backtests.
- **Fit to this system:** registry metrics plus `is_viable()` already derive viability at read time; gaps are entries missing win % or avg hold (gap_and_go 52-symbol entry showed dashes).
- **Surprise:** missing fields, not wrong ones, caused the dashboard dashes and the 'no registry entry' confusion.
- **Reuse:** every research run must emit all measured fields; never drop or overwrite an old tag.
- **Profit-booking / exit takeaway:** keep exit-reason breakdowns (trail vs max-hold) per tag, since they decide later which exit style books profit.

## 2026-10-11 — Option coverage: indexes + MCX only; swing and stock F&O owed
- **Mechanism:** real option legs are single-strike longs with initial SL and trailing SL on premium.
- **Fit to this system:** coverage is index underlyings, SENSEX, NATGASMINI and MCX cells; stock F&O (TCS etc.) and swing-signal feeds do not exist yet (B-417, B-418). Stock options have wide spreads, so a liquidity filter is needed before wiring.
- **Profit-booking / exit takeaway:** a stock-measured PFnet does not capture premium decay; a trailing premium SL is the only exit, so judge these on real option fills.
