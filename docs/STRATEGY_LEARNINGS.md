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

## 2026-10-11 — B-417: swing signals also buy a single-strike call (in addition to shares)
- **Mechanism:** a viable swing entry on an F&O stock buys one ATM call beside the shares via `_real_fo_buy_contract` (initial SL plus trailing SL, margin check, 5-min backcheck); the swing exit closes it, and the existing force-close-before-expiry handles physical-settlement risk.
- **Fit to this system:** stock options are monthly and wide-spread; the option doubles exposure per signal (user chose that knowingly). Only legs tagged `single_leg_swing_call` are closed by the swing engine (engine ownership).
- **Surprise:** `nse_fo_chain` already covered 210 stock underlyings; B-418 is mostly liquidity/lot-size review, not new plumbing.
- **Profit-booking / exit takeaway:** the swing exit signal OR the trailing premium SL closes the call, whichever fires first; judge real fills before sizing up.

## 2026-10-11 — B-419: swing round robin and SL rule per legacy tag
- **Mechanism:** the swing scan now repeats every 15 min while NSE is open on completed daily bars only (today's forming bar is dropped), skips symbols already entered or exited today (`swing_done_today`), and persists scan counts (`strategy_scan_counts`, Upstash-mirrored) so a restart no longer zeroes them.
- **Fit to this system:** signals are backtested on completed daily bars, so repeat passes must not see the forming bar; the same-day guard stops an exit then re-entry flip on the same bar.
- **Surprise:** legacy tags (power_play, gap_and_go, VCP) had no ATR multiple in their registry names, so SL % showed n/a; their stop rules now come from the live entry/exit functions (`_SWING_SL_RULES`).
- **Profit-booking / exit takeaway:** power_play and VCP exit on a chandelier trail (2xATR below peak close) and OB/VP on 6xATR, so profit is booked by trail, not a target; gap_and_go has a frozen stop and a 30-day max hold.

## 2026-10-11 — Trend-confidence entry gate (B-406 → B-421)
- **Mechanism:** `_trend_confidence` is a one-tailed normal-CDF z-score of the fast/slow MA gap against price noise; only the intraday engines compute it today.
- **Fit:** swing, MCX and option-strike cells were validated without any confidence filter. Adding a gate to them changes a validated PFnet blind, which breaks the never-tune-blind rule, so they stay exempt until measured.
- **Owner decision:** the threshold may be lowered until PFnet clears the live floor (currently 1.1, may change); choose by sweep, per category and direction.
- **Reuse:** read the floor from `PFNET_LIVE_FLOOR`, never hard-code it.
- **Profit-booking / exit takeaway:** none new; an entry filter only helps if the measured gated PFnet beats ungated, otherwise it just removes winners.

## 2026-10-11 — Stock-option liquidity screen (B-418)
- **Mechanism:** a swing share entry on an F&O stock also buys one ATM call (B-417). Stock options are often illiquid (wide spread, thin OI), so a screen rejects any contract failing named limits in `nse_fo_chain.py` (`STOCK_OPT_*`: min premium 2.0, max spread 5%, OI >= 100 lots, volume >= 20 lots, lot notional <= Rs 2,00,000), failing CLOSED on any missing field.
- **Fit:** the 0.8% cost model plus a wide spread eats the edge before the trailing SL can work; the no-trade-without-SL rule also needs a stop that can actually fill, which thin books do not give. Screen is an additional skip only; SL and trailing SL untouched.
- **Surprise:** `select_nse_option_contract` only returns LTP, lot size, strike, expiry and DTE (quotes called with quote_type="ltp"); bid/ask, OI and volume were NOT in chain data. They need a new quotes call whose response shape is unverified live, so until confirmed the screen will skip (fail closed) rather than trade blind.
- **Reuse:** verify the live quotes response keys (`parse_option_liquidity` tries several), then tune limits from real skip logs (`skipped_illiquid_stock_option`), not blind.
- **Profit-booking / exit takeaway:** a spread above the limit is a guaranteed round-trip cost at exit too, so skipping illiquid options protects profit at both entry and the trailing-SL exit.

## 2026-10-11 — B-422: analytic slippage stress of the viable set
- **Mechanism:** re-price each viable tag's PFnet at 1.2% and 1.6% round-trip cost (base 0.8%) from registry metrics only (`scripts/slippage_stress_viable.py`, output `docs/SLIPPAGE_STRESS_VIABLE.md`). Method A is exact algebra from PFgross and win %; Method B (needed for 276 of 286, since PFgross is stored as 0.0 = not recorded) assumes a 3% average losing trade.
- **Fit:** the flat 0.8% cost model hides slippage and spread, which are largest on full-NSE small caps, MCX proxies and ETFs. Result: 77 of 285 scorable viable tags keep PFnet >= 1.1 at 1.2%, only 29 at 1.6%. MCX proxy holds up best (31/49 at 1.2%), index (1/7) and full_nse (11/65) worst.
- **Surprise:** most viable margins over the 1.1 floor are thin; a 0.4 point rise in cost removes about three quarters of them. Missing PFgross blocks exact stress for almost the whole registry: future runs must record PFgross, win % and average loss size.
- **Reuse:** treat the survivors as the priority list for real wiring and the empirical stressed replay; prefer high-PFnet, large-n cells. Method B depends on an assumption, so do not use it for a go/no-go alone.
- **Profit-booking / exit takeaway:** thin edges are eaten by costs per round trip, so fewer, larger-move exits (trail rather than frequent small profit-takes) and avoiding illiquid names protect net profit more than tighter targets.

## 2026-10-11 Book 3: Ernest Chan, Algorithmic Trading (extraction, no backtest yet)
- **Mechanism summary:** two families fit this system: (a) intraday/open-effect mean reversion (Buy-on-Gap, Short-on-Gap, cross-sectional open-to-close reversion) and z-scored gap continuation (gap vs prior high/low, z 0.1 of 90d std); (b) 25-day/12-month momentum. Pairs, index arb, calendar spreads, FX, VIX futures and HFT need legs or feeds Kotak does not give; parked with reasons (B-424..B-459).
- **Fit to THIS system:** book results are gross, no costs; at the 0.8% round trip the open-to-close ideas (Sharpe 4.7 gross) likely do not survive, so run gross and net. Scaling-in and constant leverage conflict with the no-trade-without-SL rule. Shorts only intraday (MIS).
- **Lessons to apply now:** survivorship inflates long MR PFnet and understates short mirrors; short replays must be limited to shortable names; add significance tests (Gaussian stat, random-entry permutation) and a decay haircut for thin-n viable tags; clean bad ticks before trusting MR PFnet; stop for MR should sit wider than worst backtest adverse excursion, momentum uses time/opposite-signal exits; India VIX gate must be per strategy and direction (hurts momentum gap rules when high, not MR); Kelly (half) per strategy is the unvalidated sizing gap; per-symbol half-life/Hurst/ADF is the regime gate for every MR row.
- **Already tried (do not repeat blindly):** bollinger_mean_reversion (PFnet 0.03-1.09, thin), sector_rotation momentum_n200 (PFnet 0.74-0.83), gap_and_go swing (1.31-1.47), gap_up_fade (0.38-0.44), gap_and_go_short_fade (0.557).
- **Result:** none yet; 36 backlog rows B-424..B-459 queue the tests.
- **Profit-booking / exit takeaway:** gap and open-to-close edges are exit-at-close trades whose gross edge is small versus 0.8% costs, so only the higher-conviction ranked entries with ATR stops and no scaling in are worth running; momentum should be exited by trail/time or opposite signal, never averaged down.

## 2026-10-11 Book 4: William O'Neil, How to Make Money in Stocks (extraction, no backtest yet)
- Mechanism: CAN SLIM. Technical half is testable on daily OHLCV: pivot breakout on volume >= +50% of 50-day avg, base patterns (cup/saucer with handle, double bottom, flat base, high tight flag), RS rank >= 80 vs the universe, 7-8% stop, +20% target, many named exits (10-week MA, 200DMA extension, climax, distribution), and an index-level follow-through / distribution-day gate. Fundamental half (EPS, ownership, float) has no feed here and is parked.
- Fit with THIS system: the entry is swing (CNC, daily) and fits the swing engine; shorts only via MIS or F&O (no delivery short on NSE). The 7-8% stop is wide against our 0.8% round-trip cost, so edge depends on few trades with big winners: win rate 33-40% is the book's own claim, which our PFnet >= 1.1 gate will test honestly. Book results are gross, anecdotal and survivorship-prone.
- Highest-value ideas for profit: (1) index regime / follow-through / distribution-day gate, which can be applied to every existing viable tag and may lift PFnet without a new entry; (2) the exit family compared on one fixed entry, since exits decided the outcome of our OB/VP strategies too; (3) RS rank as a filter on existing breakout tags.
- Conflicts noted: pyramid adds vs SL-on-every-trade (test with combined-risk stop); book's long-dated options advice vs our <=5-day trailing-SL option rule (repo rule wins); 'do not day trade' vs our intraday engines.
- Reuse next time: test all exit rules on the same entry set so differences are exits, not entries; gate tests are cheap (index data only).
- Profit-booking / exit takeaway: book says cut at 7-8%, take +20%, but hold winners at least 8 weeks if +20% arrives in under 8 weeks; the contrast with our faster-turnover rule must be settled by data (PFnet per day held), not by the book.

## 2026-10-11 Book 6: Mark Douglas, Trading in the Zone (extraction, no backtest yet)
- **Mechanism:** almost pure psychology; no price-pattern strategy. The automatable core is process and risk rules: fixed-fractional sizing, predefined stop that only ratchets in the trade's favour, scale-out ladder, expectancy and sample-size gate (judge a strategy on 20+ trades, not one), last-20-trade live check, drawdown size ladder, no-discretion execution, audits.
- **Fit:** these are overlays on strategies already viable, so they are cheap to test on stored trade lists (B-527..B-563). Any rule that pauses trading must go through the existing viability gate; no new kill switch. The streak-pause idea needs the user's yes before wiring.
- **Reuse:** test each overlay as an A/B on PFnet and drawdown across the viable tags; register results as separate tags.
- **Profit-booking / exit takeaway:** predefined stops and a monotonic ratchet plus a scale-out ladder decide how profit is booked; settle ladder fractions by data (sweep), not by the book's philosophy.

## 2026-10-11 Book 5: Alexander Elder, Trading for a Living (extraction, no backtest yet)
- **Mechanism:** the richest indicator book so far. Triple Screen (weekly MACD-Histogram slope sets direction, daily oscillator pullback sets timing, trailing stop-entry sets the fill), Elder-ray, Force Index, EMA13 gate, Directional/ADX, MACD-H divergence and seasons, Stochastic, RSI, Williams %R, RoC, OBV/AD, gaps, chart patterns, envelope/channel fade, Parabolic stop, breadth (NH-NL, TRIN, A/D), plus money rules (2% per trade, 6% monthly cap, breakeven and 50% profit-protect stops, pyramiding). Rows B-564..B-748 (185); only truly identical duplicates were merged.
- **Fit:** every row needs only NSE OHLCV(+volume) and has a stop, so all fit the no-trade-without-SL rule. Blocked on data: open interest, sentiment and COT rows (parked P3). Several oscillator parameters were missing from the scanned text, so they are sweeps, not book values. The monthly loss cap is a pause mechanism: backtest only; live use needs the user's yes (one-kill-switch rule). The book favours fewer trades, which conflicts with faster turnover, so judge PFnet per unit time.
- **Reuse:** the Triple Screen with each screen ablated (to see which adds value), and the Elder-ray and Force Index entries, are the highest-value tests. The Parabolic and 50% profit-protect trails are exit candidates for existing viable entries.
- **Profit-booking / exit takeaway:** Elder books profit by oscillator take-profit (Force Index flip, Stochastic at 70), a breakeven stop once price moves one average range, a 50% profit-protect trail and a Parabolic trail; compare these as an exit family on a fixed entry, by data.

## 2026-10-11 Elder page-image re-read (addendum to Book 5)
- OCR missed nothing structural: the figures add no numeric rule beyond captions. Corrected facts: ADX smoothing 13 with NO fixed 20/25 level; Stochastic slow 5-3, zones 20/80 (30/70 inside Triple Screen); %R lines 10/90; RSI 7-9 with 30/70, judged too slow for Triple Screen; MACD 12/26/9. The "6% rule" is really a 6-8% monthly loss limit (p.260), not an open-risk rule. Rows B-759..B-770 correct or add.
- **Profit-booking / exit takeaway:** break-even after one average daily range, then a 50% profit trail; short-term exit on Force Index sign flip or Stochastic at 70; long-term exit on weekly trend reversal.

## Monthly loss cap (Elder 6% rule) backtest, 2026-10-11 IST
- Mechanism: stop new entries for the rest of the month once realized month-to-date loss reaches 4/6/8% of month-start equity. Elder's real rule is a 6-8% monthly loss limit, not an open-risk rule.
- Fit here: tested on swing order-block/volume-profile longs (run 38130747915), with a portfolio limit of 5/10/20 concurrent positions. The first run (38129170722) had no concurrency limit and was invalid (returns below -100%); always cap concurrent positions in any equity-curve overlay.
- Result: no consistent PFnet or drawdown gain from any cap. The cap skips winners and losers about equally (loss avoided ~= profit forgone). At 20 positions and 2% risk every cap was worse than none.
- Reuse: judge a cap by drawdown at fixed risk with a realistic position limit, not by pooled returns; sample is small (~500-1000 trades taken).
- Profit-booking / exit takeaway: a monthly halt did not improve net profit on this strategy set; protect capital with per-trade SL and position sizing instead.


## Exit-family comparison (run 38140914889), 2026-10-11 IST
- Mechanism: same real main.py entries (order block, volume profile POC, gap-and-go long and short), swapped across 22 exit cells in 7 families (fixed ATR, swing-low structure, chandelier, exhaustion, O'Neil swing-low trail, signal invalidation, time stop). Daily, 5y, full universe, 0.8% cost, equal notional, every cell has a stop.
- Result: 26 of 88 tags at PFnet >= 1.1, all long. Best: exitinval VP 1.2675 (39.6% win, 20.9d hold), fixed ATR VP 1.2591, exhaust gap-and-go ROC 1.2429 (11.0d), time-stop gap-and-go hold5 1.1484 (4.8d, fastest). O'Neil trail 0 viable (best 1.045). Gap-and-go shorts 0.51-0.65. No gap-and-go variant beats the live exit (registry 1.65).
- Surprised: the exit choice moved OB from 1.06 to 1.17 and VP from 1.03 to 1.27 with the same entries, so exit is worth more than entry tuning on these two.
- Reuse: sim exits are not a main.py replay; fills at the stop price, equal notional vs risk-based live sizing. Replay owed before trusting live P&L.
- Profit-booking / exit takeaway: a weekly-trend invalidation exit with a wide 6xATR safety stop beat tight stops and O'Neil trails; for fast turnover a 5-day time stop on gap-and-go still cleared 1.1 in under 5 days.

## Elder indicators batch 1 (run 38144283116) and O'Neil patterns (run 38143823565), 2026-10-11 IST
- **Elder (258 tags, daily, both directions):** 0 tags reach PFnet 1.1. Best is adx_bell ring_bell long 0.890 (win 31%, n~20.7k, ~18d hold); best short is elder_ray exit_div 0.675. Elder's indicators alone, on this cost model, do not clear the floor. Gross PFnet was not printed (artifact `elder_results.json` has it; fetch owed). Universe not labelled in the log.
- **O'Neil (84 viable cells printed of 756):** 93/378 (1d) and 145/378 (1w) cells >= 1.1; best 1d rsscreen top h60 rs90 2.193, best 1w rsscreen top h26 rs90 3.639. Short-hold winners: 1d h20 rs90 1.775 (17d), 1w h8 rs90 2.523 (7.6d). Caveats: the top cells use "avgdown" (adding to losers; stop+avgdown trades average -11.6% at 1d, -21.6% at 1w), 1w PFnet comes mostly from timeouts, universe not confirmed (shards ran 1-1.5 min, so likely not the full ~2,680). Re-run on the confirmed full universe and replay through main.py before any wiring; avgdown cells need a per-position risk cap before they can satisfy the no-trade-without-SL rule.
- **Reuse:** merge logs only print top cells; make research scripts emit the full tag table (with gross PFnet and universe size) so no result has to be recovered from artifacts.
- **Profit-booking / exit takeaway:** timeout exits (patient 26-week holds) carry the O'Neil edge while stops lose; prefer the shorter-hold variants (h8/h12/h20) at similar PFnet for capital turnover, and do not book early on the winners.

## Elder MACD / directional system / gaps (run 38145684388), 2026-10-11 IST
- 120 tags, daily. Only 5 reach PFnet 1.1, all `gaps` long fades: exhaust_fade atr3_nb5 1.246 (win 34.8%, n=4,404, hold 3.7d), exhaust_fade atr2 1.228, atr1d5 1.218, common_fade atr3 1.121, atr2 1.101. MACD best 0.929, directional system best 0.798. Every short is below 1.0 (best gaps common_fade short 0.970).
- Why it matters: 3-4 day holds at 1.1-1.25 give fast capital turnover, the preferred profile; but margins over the floor are thin and gaps are rule-exit dominated (few timeouts). Gross PFnet not printed; universe not labelled.
- Next: full-universe confirmation with gross PFnet, then replay through main.py before any wiring; a stop is always attached (ATR stop), so the SL rule is satisfiable.
- **Profit-booking / exit takeaway:** the gap-fade edge is in quick rule exits within ~4 days; do not hold these past the rule exit, and keep the ATR stop on every entry.

## Elder batch 2 extension (run 38145685996, 582 tags: williams_r, ad_line, volume, force_index, rsi, stoch_slow, macdh, parabolic, profit_protect, channel)
- Result: none at PFnet >= 1.1; best `rsi__levels__long__1d__atr3_band25_n14__v1` 1.026 (n=11138, 24d hold). Universe was NIFTY200 + 182 ETFs, NOT full NSE; pfnet_gross not printed (stored NA).
- Lesson: classic oscillator signals (RSI levels/divergence, stochastic, force index) do not clear 1.1 on daily NSE; none worth wiring. Registered research-only with real metrics.
- Profit-booking / exit takeaway: best cells win only via ~3 ATR trails with 20+ day holds; short-hold variants stay below 1.0, so no early-profit-booking edge here.

## O'Neil extension (run 38147513010) and Chan extension (run 38147514850), 2026-10-11 IST
- Mechanism: O'Neil pivot/tightness/leaders/flag/hft weekly+daily setups; Chan kalman-band, shape, tsm, xsmom across 5m/15m/1h/1d. Logs printed only top-N slices (Artifact download 403), so 419 tags registered, not every cell.
- Result: 185 of 419 tags PFnet >= 1.1. O'Neil 1d best oneil_pivot x tightness pr1 2.92 (n=355); 1w oneil_leaders firsthigh 2.77 (n=2173). Chan kalman band long/short 5m 1.68/1.67 (n 6190/1030), 15m ~1.29, 1h best 1.099 (just under floor); 1d pooled kalman 1.36.
- Surprises: Chan 5m/15m gross PFnet 2.6-4.7 vs net 1.2-1.7, so the 0.8% cost eats most of the edge; Chan 1d used a NIFTY200+ETF mixed universe (not full); many 1d tags are year/VIX slices, not comparable to pooled tags; O'Neil universes were 1953-2166 symbols, not 2680.
- Reuse: avg_hold units are unlabelled by the harness (assumed days/bars, flagged in the registry); stops of 12-25% on O'Neil need a sizing check against the SL-on-every-trade rule; every viable cell still needs a main.py replay before wiring.
- Profit-booking / exit takeaway: state-exit kalman exits win (avg +0.8 to +1.9%) while hard stops lose -4.7 to -6%; for O'Neil, timeouts carry the profit (+14 to +19%) and stops lose -6%, so wider trails/longer holds drive the edge, not early profit booking.

### O'Neil replay (run 38149046190, 2026-10-11 IST)
Mechanism: weekly flat-base/pivot/new-high breakouts, ATR3 stop, 26-week max hold, cost 0.8%. Replay (bar-by-bar port, 1955 syms) confirms 6/7 tags >=1.1 incl. ex-top-5: newhigh n=9114 PFnet 2.49, pivot n=10710 PFnet 2.18; flat-base long n~115 PFnet 3.4-5.1 (thin, trust ex-top5 2.1-3.6). Flat-base short mirror FAILS (n=10, ex-top5 0.0). 341 crosscheck diffs vs research code (mostly off-by-one n) must be reviewed before exact numbers are trusted. Fit: stops are wide (12-25%), so sizing must cap risk; swing engine only. Surprise: profit comes almost entirely from timeout exits (+26..+60 avg) while stops lose -20..-28, same pattern as OB/VP.
Profit-booking / exit takeaway: do not tighten exits or trail early; the edge is in letting survivors run to max hold, trl1 variant converts to trail exits at +3.7 avg and gives PFnet 3.4 vs 3.9 untrailed.
## 2026-10-11 Elder rows B-632..B-702 status reconciliation (slice 04)
- **Mechanism:** no new strategy; harnesses already existed (elder_trend_context_research.py, elder_batch3_research.py and the earlier elder_* scripts). 24 rows whose patch said "HARNESS BUILT" still carried PENDING; flipped to HARNESS-BUILT-AWAITING-RUN so the queue shows what truly needs a dispatch. B-639/B-640 (hand-drawn preliminary trendline, protractor ranking) parked as BLOCKED with reasoning: no mechanical spec, algorithmic cover in tl_break (B-621). B-634 is covered by the batch3 breadth family (B-680..B-683).
- **Why it matters here:** a stale PENDING label hides that only a dispatch (interval=1d, period=5y) is missing, and a stale label can cause duplicate harness work.
- **Result:** none yet; runs owed via elder-batch3-research.yml and elder-trend-context-research.yml (interval 1d, period 5y).
- **Profit-booking / exit takeaway:** none new; keep the Elder exit-family comparison (Force Index flip, Stochastic 70, breakeven, 50% protect, Parabolic) on a fixed entry once runs return.
## Max-positions (diversification) sweep, B-746, 2026-10-11 IST
- Mechanism: Elder diversification rule tested as concurrency cap K (3/5/10/20/40) in the dated portfolio ledger of portfolio_overlay_research.py (EMA13 dip-buy and 20-bar breakout, both directions, 1% risk, 0.8% cost).
- Fit: the "no dated ledger" blocker on B-743/B-746 was stale; the chronological simulator already existed. Correlation screen and worst-first liquidation remain unbuilt.
- Result: not yet run (harness-built; dispatch portfolio-overlay-research.yml).
- Reuse: check existing simulators before declaring a ledger missing.
- Profit-booking / exit takeaway: none yet; judge by final_mult vs max_dd across maxpos cells once run.
## 2026-10-11 slice_01: Kelly / CPPI / significance table over the whole registry (B-453, B-454, B-455)
- Mechanism: per registry tag, Kelly f=m/s^2 and half-Kelly from PFnet/win%/n, a CPPI sub-account wind-down Monte Carlo, and a Gaussian t-stat with a t/2 expected-decay haircut. Output docs/kelly_significance_table.json from scripts/kelly_significance_table.py (no network needed).
- Fit: sizing and confidence only; it does not create entries, so SL-on-every-trade and the 0.8% cost model are untouched. Derived at read time from stored metrics, consistent with the keep-all-data rule.
- Result: 14,607 scorable tags; 595 viable (PFnet>=1.1): 505 significant at p<.05, 416 after the haircut, 72 thin-n. About 30% of viable tags do not survive an honest decay haircut.
- Surprise: the largest half-Kelly values sit on thin-n tags (n 17-20 MCX cells), so Kelly ranks must be read together with the thin_n flag.
- Reuse: use sig_p05_after_haircut, not raw PFnet, as a tie-break among viable tags; never size from Kelly on thin_n tags.
- Profit-booking / exit takeaway: unchanged by this; the highest t-stat tags are the O'Neil weekly timeout-driven cells, so profit comes from letting winners run, not early booking.
## Elder S/R stop-tighten (B-607) and measured-move target (B-623), harness only, 2026-10-11 IST
- Mechanism: B-607 tightens the protective stop to a 1-ATR trail off the extreme once price is within 0.5/1.0 ATR of the congestion top edge (support-bounce longs and mirrored shorts). B-623 exits at a measured-move target after a close-valid trendline break (line at break + 0.5/1.0 x max vertical distance from the line to the lows).
- Fit here: both keep an ATR stop on every trade (no-trade-without-SL rule holds); both are bar-count/ATR based so candle-size sweep is meaningful. Simulator additions are additive (optional sig keys), so existing tags are unchanged.
- Result: none yet; run elder-patterns-research.yml (consol and trendline families) and compare against plain edge_bounce / tl_break tags.
- Reuse: price-target and stop-tighten overlays belong in the shared simulate(); detectors only supply per-entry level arrays and the mirror un-flips them (1/x).
- Profit-booking / exit takeaway: prior runs show timeout survivors carry the edge and tight stops lose; expect a target at ~1x measured move to cut hold time but also cap winners, so judge by PFnet per bar held.
## 2026-10-11 SL governance audit (B-506, B-530, B-550)
- Mechanism: audit of live stop handling against O'Neil execution rule and Douglas monotonic-stop rule.
- Fit: exits are MKT; stops are trigger-gated SL (limit) because SL-M is blocked on this Kotak account; intraday long/short sync only ratchets in the trade's favour; swing sync only places missing SLs; the 5-min backcheck is category-agnostic (net-qty sign) so swing and option holdings are covered.
- Result: no code defect found; locked by tests/test_sl_governance_audits.py. No backtest (not applicable).
- Surprises: O'Neil "SL-M" advice cannot be followed literally here; SL limit with zero buffer is the accepted substitute.
- Reuse: owed from the coordinator: loosen-event counter and per-position time-limit check (main.py).
- Profit-booking / exit takeaway: exits at market preserve fills in falling stocks; a stop-limit can miss on gaps, which is what the 09:15 protect pass and emergency MKT escalation backstop.

## Elder pyramiding and Vince portfolio rules (B-742, B-743), 2026-10-11 (slice_05b)
- Mechanism: pyramiding adds units to a winning trend position only when the position is at breakeven or better (stop at or beyond average cost) and total open risk stays within 2% of equity; Vince rules: never average down, exit rather than meet a margin call, liquidate the worst position first when lightening up.
- Fit here: every existing simulator is single-unit per trade, so adds need a unit ledger, not a signal variant. The no-trade-without-SL rule maps naturally: each add carries a stop and locked-in profit is not counted as risk. NSE MIS squares off at 15:15 IST and the 0.8% cost model is charged per unit, so adds must be costed individually.
- Built: scripts/portfolio_ledger_research.py (`pyramid_position`, `liquidate_worst_first`), long and short, 5 tests green. No backtest result yet; both rows are PARTIAL until the collect stage emits per-trade bar paths.
- Surprise/reuse: the stop-moves-only-in-profit-direction clamp and the average-down rejection are what make an add safe; reuse them in any future live pyramiding path. Costs of extra units may erase the edge on thin strategies, so test adds vs no-add after costs.
- Profit-booking / exit takeaway: adds raise exposure to the same trend, so the stop must move to breakeven first; exit the whole stack on the first stop hit and cut the worst mark-to-market position first when freeing margin.


## 2026-10-11 slice_03: Douglas B-556..B-563 and Elder B-564..B-631 status reconciliation
- **Mechanism:** no new strategy. Douglas rows (edge-based sizing, walk-forward, execution audits) and Elder rows (EMA13, MACD, Directional System, gaps, patterns, trendlines, volume, MA systems) already had harnesses (portfolio_overlay_research.py, douglas_trade_mgmt_research.py, elder_trend_context_research.py, elder_patterns_research.py, elder_macd_dirgap_research.py, elder_indicators_research*.py) but many rows still read PENDING. 44 rows relabelled HARNESS_BUILT_RUN_PENDING (dispatch interval=1d period=5y first, then 1h/15m/5m), 19 relabelled PARTIAL (16 with a daily run already registered, plus B-568, B-606 and B-573 notes) (runs 38144283116 and 38145684388).
- **Fit here:** every harness keeps an ATR stop on every trade, uses the 0.8% cost model and both directions, so the no-trade-without-SL rule holds. B-558/559/560/562 (signal shadow log, plan-vs-execution diff, pre-session plan, rule-version tag) need main.py/journal changes and stay OPEN_PARKED for the coordinator; B-563/575-578 stay BLOCKED (not mechanical); B-627 BLOCKED on a peer lead-lag simulator.
- **Result (daily, already registered):** only gap fades clear 1.1: gaps__exhaust_fade__long__1d__atr3_nb5 1.246 (n=4404, ~3.7d hold) and common_fade 1.121; continuation 1.058, breakaway 0.997. MACD best 0.929 (hist_exhaust), Directional System best 0.798 (the ADX-rising and dull-market gates and overheat exit all LOWER PFnet vs the ungated cross: 0.711/0.635/0.651), ADX ring-the-bell 0.890, EMA13 dip 0.614, volume rules best 0.824, divergences 0.74-0.95. Every short mirror is below 1.0.
- **Surprises / lesson:** Elder-style filters (ADX rising, dull gate, overheat exit) cut trades but did not raise net PFnet on daily NSE; the only cleared edge is a fast mean-reversion fade. Stale PENDING labels hid that daily runs existed, risking duplicate harness work.
- **Reuse:** gross PFnet and universe label were not printed by those runs; before any wiring, re-run gap fades with gross PFnet and replay through main.py. B-606 stop-offset sweep still owed.
- **Profit-booking / exit takeaway:** the profitable Elder cell is a 3-4 day rule-exit fade, so book it quickly at the rule exit with the ATR stop attached; trend-follow filters here give no early-booking edge.

## 2026-10-11 Elder chart-pattern family, full merge table (run 38148955837, B-600..B-624, B-788/B-789)
- Mechanism: 228 tags over island reversal, triangles (asc/desc/sym), H&S/hound, double top/bottom, Sperandeo 1-2-3, tails, trendline break/channel, rectangle, breakout fade and bar-shape/weekday filters, each long AND short (short is the 1/x mirror), ATR stop 1.5/2/3, 30-bar max hold, 1d bars, 0.8% cost.
- Fit here: all ATR-stop daily swing cells, so SL-on-every-trade holds; none wired. Harness universe printed 10752 listed / 9400 with data, bigger than the NSE file universe quoted elsewhere, so treat n as including ETFs/duplicates until confirmed.
- Result: only 16 of 228 tags >= 1.1 and just two families with n>=100: island long (PFnet 1.51-1.57, n~8.8k, win 33%, hold ~7.5d) and tri_desc long (1.12-1.27, n 313). Shorts are uniformly weak (best n>=100 short about 0.78). Bar-shape filters (weekday, close-location) sit at 0.55-1.0 with huge n: a pure bar filter is not an edge after 0.8% costs.
- Surprise: the top PFnets (2.3, 1.7, 1.58) all have n 5-20 and are noise; the island short mirror (0.669) is far below its long (1.57), so the gap is direction-specific (up-trend drift), not a pattern symmetry.
- Reuse: always read n before PFnet; gate candidates on n>=100; the 1/x mirror gives honest shorts for free and shows long-bias in 1d NSE data.
- Profit-booking / exit takeaway: island cells win mostly through rule_exit (about 93% of exits) with few stops at atr3, while atr1d5 stops out 21% of trades and lowers PFnet 1.57->1.51; wider stop plus rule exit beats early booking.
## 2026-10-11 Minervini ATR-trail sweep, long and short (run 38147956271, B-790/B-791)
- Mechanism: real main.minervini_vcp_entry_signal and its short mirror, structural stop plus ATR trail swept 1.5/2/3/4, max hold 60 bars, 1d, 6y, 0.8% cost.
- Fit here: swing-category, ATR trail is the stop so SL-on-every-trade holds; the live minervini_vcp tag (0.908) sits just under the floor.
- Result: long PFnet 0.908/1.025/1.181/1.342 for atr 1.5/2/3/4 (n 3845, win 32/35/39/42%, hold 8/12/22/30 bars). Short mirror 0.60-0.65 for every ATR (n 3367): fails in every cell.
- Surprise: PFnet climbs monotonically with trail width, i.e. the edge is the long hold of survivors (matches the earlier OB/VP and O'Neil finding that trail stops lose); the 30-bar-hold atr4 cell clears 1.1 only by tying capital up about 4x longer than atr1d5.
- Reuse: sweep the trail multiplier on every trend-following entry, but compare PFnet per day held and require a main.py replay before widening a live trail.
- Profit-booking / exit takeaway: tight trails book small wins early and lose to costs; wide trails raise PFnet but slow turnover, so prefer atr3 (1.181, 22d) over atr4 unless atr4 is replay-confirmed.

## Class A: Minervini lab exit variants on the real entry fn (run 38149302930, 2026-10-11 IST)
- Mechanism: real `minervini_vcp_entry_signal` entries, 25 exit/filter variants (breakeven_after_1r, climax_sell, gap_dn_exit, ma200_break, rr2/rr3, pct8_hard plus entry filters), 1d, 60-bar max hold.
- Fit here: swing category, stop_hit exit keeps SL-on-every-trade; hold 28-45 bars means capital is tied up, but the 30-day rule treats it as viable.
- Result: PFnet 1.39-1.76 on n 536-3394 (full NSE, 0.8% cost). Best: tight_closes5 filter 1.760 (n1552, 42.8% win), gap_dn_exit 1.678, climax_sell 1.669, breakeven_after_1r 1.643 vs base pct8_hard 1.475. Entry filters that cut n (dryup n536, ext_le3 n563) did not raise PFnet.
- Surprise: max_hold_timeout trades carry the edge (PFnet 4.6 in climax_sell) while stop_hit loses 100%; climax_sell exit alone books 649 trades at 96% win, so exiting into strength beats waiting for timeout.
- Reuse: always add a climax/gap-down exit to a wide-trail trend entry; the lab exits are not in main.py, so wiring needs a port + replay.
- Profit-booking / exit takeaway: book into climax strength (climax_sell) and cut on gap-down; both raise PFnet and shorten hold versus pure timeout.

## Elder batch 3: oscillator/structure/ORB/sizing (run 38169625565, 2026-10-12 IST)
- Mechanism: 282 daily oscillator/structure cells (stoch/RSI/MACD-histogram reversals, divergence classes, ROC peak exits, SAR, minor stops, MTF) plus 5m opening-range breakout and position-sizing methods.
- Fit here: ORB with ATR stops fails the 0.8% cost model outright; sizing cannot rescue negative-edge entries.
- Result: 3/282 viable, all MACD-histogram divergence with Keltner class (PFnet 1.14-1.27, n~1290, 17-25 bars). 5m ORB PFnet 0.13-0.19 in all 24 cells; every sizing method lost money.
- Surprise: raw divergence on RSI or on wide classes (ka/kb) sits at 0.92-0.99; only the strictest class (kc) with MACD-histogram lifts above 1.1; fewer trades (1.3k vs 25k) carried the edge.
- Reuse: always gate divergence by a strict class; sizing studies need a positive-edge entry first; collector caps hid half the data once (raised to 900k chars).
- Profit-booking / exit takeaway: atr3 beats atr1.5 on the one family that works (1.267 vs 1.14), consistent with letting divergence winners run to 25 bars; tight stops on 5m ORB book small losses repeatedly.

## Douglas/Elder trade management: breakout with min reward:risk target (run 38174269343, 2026-10-12 IST)
- Mechanism: 480 cells (228 entry variants, 252 exit variants); the winning family is a 20-bar breakout entry (brk20) with an ATR stop and a minimum reward:risk target (rr 2.5-4), mirrored short.
- Fit here: fits the no-trade-without-SL rule natively (ATR stop is in the cell); 12-day hold sits well inside the 30-day rule; trades on the broadest universe so far (4699 symbols with data).
- Result: 6 viable, short atr3_rr4 PFnet 2.468 (n275, win 43.6%), long atr3_rr4 1.762 (n422). No entry-side variation cleared 1.1; the edge is in the exit (a distant RR target on a wide ATR stop).
- Surprise: the short mirror beats the long (2.47 vs 1.76), unusual here; MFE averages 2.25R but about half of losers reach 0.5R first, so partial profit-taking at 1R would cut give-backs.
- Reuse: sweep rr target and ATR stop together on every breakout entry; always register the short mirror; treat n<300 as needing neighbours-in-parameter-space to confirm.
- Profit-booking / exit takeaway: a 4R target with a 3-ATR stop lets winners run to ~12 days; 49.7% of losers touched +0.5R and 26% touched +1R, so test a breakeven-after-1R stop on this family before wiring.

## Breakeven-at-1R on swing longs/shorts (B-412 / B-799, run 38169623485, 2026-10-12 IST)
Mechanism: after price reaches +1R, move the stop to entry. Result on ~2200 symbols, 0.8% cost: gap_long 1.177->1.187, minervini_long 1.474->1.475, ob_long 1.102->1.094, vp_long 1.124->1.099; shorts unchanged below 1 (gap 0.40, minervini 0.77). Why neutral: edge sits in 30-day max-hold survivors; breakeven converts many would-be-recoveries into zero-gain stops (gap_long stop_hit 963->2136) and offsets any saved losses. Surprise: Minervini lab baseline_ma200_break reaches 1.701 (n3370). Reuse: do not add breakeven stops to these swing strategies; keep the wide trail/stop and let survivors run.
Profit-booking / exit takeaway: early breakeven does not improve net profit on 30-day swing edges; it only trades recoveries for zero-gain exits.

## Portfolio overlay slices of brk20 (B-800/B-801, run 38176399634, 2026-10-12 IST)
Mechanism: one base entry (20-bar breakout, ATR stop) sliced by year, month, price bucket, turnover quartile, index regime gate, walk-forward halves, risk-per-trade and position cap. Base fails (0.82, CI95 0.79-0.85); 26 of 744 cells clear 1.1 but nearly all are post-hoc calendar slices (2021, March/April/Nov) so the pick is selection bias, not edge. Honest candidates: low-price bucket (<=20) 1.31-1.44, n~3.5k. Trades are autocorrelated (ac1 0.43), so a single-pass PFnet overstates independence; the CI95 is wide-ish only in small slices. Cost sensitivity is stored per cell (0.4/0.8/1.2%). Reuse: never wire a calendar-slice cell; require out-of-sample replay of any slice, and judge gates only through walk-forward train/test pairs.
Profit-booking / exit takeaway: no exit improvement here; the lesson is selection discipline - slices found by looking at results are not exits or edges, and clustered losing runs (max losing run 134) argue for sizing caps over exit tweaks.

## Completing viable-table backtest cells (B-803, 2026-10-12 IST)
Lesson: a dashboard cell shows a dash when a registered result lacks a field the run did not print (hold, gross PFnet, universe). Re-running the same workflow reproduced the 4 O'Neil weekly flatbase rows exactly (n=116/118, PFnet 5.165/3.934/3.447/3.422), so the gaps were filled without changing any stored number; 62 of 84 O'Neil rows did NOT reproduce (the harness samples ~1/3 of the universe per shard and the earlier run used a different sample), so those were left alone. Flatbase weekly hold is 11-22 weekly bars (~55-110 trading days, beyond the 30-day viability rule) so these cells are judged separately. Reuse: every research workflow must print n, PFnet net+gross, win %, avg hold and the universe size in its artifact so no cell is ever blank.
Profit-booking / exit takeaway: the weekly flatbase cells with timeout h12 (hold 11 bars) and h26 (22 bars) show a shorter hold keeps most of the edge (3.45 vs 5.17 at lower hold); prefer the shorter hold per the turnover rule when the longer one exceeds 30 trading days.

## Gross PFnet fill attempt (B-804, 2026-10-12 IST)
Lesson: of 371 viable rows missing gross PFnet, none could be filled by exact reproduction; stored artifacts either do not exist, have an empty gross column, or came from a re-run whose n differs by 1-3 (data drift), so they are a different sample and must not be merged. Gross PFnet needs the run to print it; research workflows must emit pfgross going forward.
Profit-booking / exit takeaway: none for exits; the lesson is data hygiene - keep every measured field at run time, because backfilling later is not possible once the sample drifts.

## brk20_min_rr main.py port and replay harness (B-798, 2026-10-12 IST)
Lesson: the research used a Wilder EWM ATR, while main._atr_series is a rolling mean, so the port carries its own ATR to keep numbers identical (parity-tested against the research simulator, long and short). Stop is always attached, satisfying no-trade-without-SL. Bar-count constants mean hours/quarter-hours on 1h/15m, so intraday cells are not comparable to 1d. No result yet; replay is slow per-bar, hence sharding.
Profit-booking / exit takeaway: the breakeven-at-1R ratchet and EMA13 rule exit are swept as cells; prefer whichever keeps PFnet with the shorter hold once the replay lands.

## Intraday flatten re-run harness (B-792, 2026-10-12 IST)
Lesson: of 38 short-hold viable cells only 35 are truly intraday; 3 hold 16-23h by design so a 15:15 flatten would change the strategy (classed swing). Flatten re-runs are new tags (`_fl1515__v2`), old numbers untouched; entries on the last bar before the cut are dropped. Cost kept at 0.8% for comparability (real MIS is lower, conservative). atrnone cells cannot be wired live (no-SL rule).
Result (run 38185672296): 152 cells re-run, 42 stay PFnet >= 1.1 after the forced flatten (best chan_kalman band long 5m 1.78, short 5m 1.67), so the edge largely survives without overnight carry; the best survivors are 5m wide-ATR cells.
Profit-booking / exit takeaway: forcing the exit at 15:15 tests whether the edge survives without overnight carry; only variants that keep PFnet >= floor under the flatten may be wired as intraday.

## Chan (Algorithmic Trading) cells, run 38183172728 (B-805, 2026-10-12 IST)
Lesson: 258 cells (tsm, gapmom, ema_regime, zmr, alexander, shape, updays, kl, gap, xs_o2c) at 1d and 1h; 10 clear PFnet 1.1, led by time-series-momentum 1h (1.55) and short-on-gap 1d (1.27-1.30, n=1127). Hourly tsm shows n up to 300k from overlapping signals, so PFnet is not a portfolio number until re-run with non-overlap; most 1d cells sit below 1 (tsm 1d long 0.65, short 0.68). Short-on-gap is the cleanest candidate (small n, real stop, short mirror).
Profit-booking / exit takeaway: hold25 at 1h beats shorter holds on tsm, i.e. the edge is in letting winners run to the max hold; test a breakeven ratchet and non-overlap before wiring.

## Portfolio-overlay out-of-sample harness (B-801, 2026-10-12 IST)
Lesson: B-800's best overlay cells (pricebucket hi20_lo0 PFnet 1.44, passtrade4_k10 2.93 n=635) were picked after seeing the full 5y sample, so their numbers are in-sample by construction. Harness `scripts/portfolio_overlay_oos.py` re-uses the overlay collect streams and splits by ENTRY DATE (first 60% of distinct days vs last 40%), re-simulating passtrade4 from a fresh book in each window, both directions, every ATR, tags `pfoos__brk20_<overlay>_<full|is60|oos60>__...`. Reuse: a candidate only counts if the OOS window alone clears the floor with a usable n; passtrade4 shrinks n a lot (635 total), so the OOS slice may be thin and its CI must be read, not just the point estimate. Not yet run; trades entering before the cut but exiting after it are kept in-sample (approximation). A pass still needs a main.py-port replay before any wiring.
Profit-booking / exit takeaway: the 2.93 comes from the 4%-stop filter plus a wide ATR3 trail letting survivors run; if OOS holds, the exit (ATR3 trail) is the edge to port, and if OOS collapses the gain was a selection artifact, not a profit-booking rule.
## Chan non-overlap harness (B-807, 2026-10-12 IST)
Lesson: the registry note said n was overlapping signals, but chan_research.simulate() already jumps to exit+1 after each trade, so per-symbol time-series cells may already be non-overlapping; the harness generates every signal trade independently and applies a strict FIFO filter, so the run settles it either way (strict FIFO re-enters the bar after an exit; simulate ignores the exit-bar signal, equal to gap=1, and a test asserts that equivalence). One-bar cross-sectional cells cannot overlap within a symbol and are not re-run. Shards emit sums/counts, not trade lists, so the artifact stays small. New cells are separate tags (`__nonovl__v2`); the old v1 numbers stay registered. Wiring needs these numbers, not the v1 ones, and a stop is already on every trade.
Profit-booking / exit takeaway: if PFnet holds under FIFO the max-hold exits are real portfolio edge; if it collapses, the v1 figures were inflated by stacked signals and nothing should be wired.
## MACD divergence full-universe re-run, short mirror and candle sweep (B-808/B-809/B-810, harness built 2026-10-12 IST)
Mechanism: regular divergence on confirmed close pivots (half-width w): price makes a lower low while the MACD histogram (or line) makes a shallower low = long; mirror = higher high with a lower indicator high = short. Fires w bars after the pivot, so there is no look-ahead. Fit for this system: stop on every trade (ATR 1.5/2/3), 0.8% cost, daily/hourly NSE bars work with yfinance; divergences are rare and pivot-lagged, so entry is late and cost bites at 15m. Prior result (run 38145684388, universe unlabelled, 1d only): long 0.783/0.832/0.904, short 0.583-0.590, none viable; PFnet rose with the wider stop, hinting the edge is in long holds not the signal. No result yet from this harness; it exists to put those cells on the full universe, add 15m/1h, and separate the zero-side filter and the histogram-vs-line source as their own tags. It is a faithful port (no main.py equivalent), parity-tested against the original; new family `macddiv` so v1 `macd__hist_div` tags stay untouched. Reuse: label the universe in every run so a re-run is not needed later; bar-count constants (w, 30-bar hold, 12/26/9) change meaning per candle size.
Profit-booking / exit takeaway: PFnet climbing with ATR 3 on the 1d cells suggests exits, not entries, drive it; compare the hold-to-timeout share per cell and test a trailing exit before blaming the signal.

## O'Neil / Chan keep-all-data re-run prep, 4h Kalman and replay plan (B-783..B-786, built 2026-10-12 IST)
Mechanism: no new signal; this is data hygiene around existing O'Neil (pivot, flat base, new-high, extensions) and Chan (Kalman band, VWMA band, ts-momentum) cells. Fit for this system: the definition of viable changes over time, so every cell must survive in full. Finding: `finalize()` defaulted to `min_n=30` and the merges printed only top-N, so thin cells (and anything beyond the log head) were silently lost, and the artifact download 403s in the sandbox. Fix: `scripts/cell_tsv.py` writes AND prints the whole per-cell table (min_n=1, all fields, explicit hold unit); Chan gains a 4h candle via a per-session 1h resample (windows 09:15-13:15 and 13:15-close, no look-ahead). Surprise to remember: O'Neil stops are 12-25% wide, so equal-weight sizing would risk several times a 3% stop trade; size by stop width before any wiring. main.py has no O'Neil or Kalman function, so replays are ports and a registry PFnet is only as good as the port; O'Neil 1h/4h is not a resample job because every bar-count constant is day/week-defined. Reuse: any new research merge should call `cell_tsv.emit_full` instead of printing a top-N. Numbers: none yet (sandbox has no network).
Profit-booking / exit takeaway: O'Neil's edge sits on 26-week survivors with wide stops, so booking profit sooner via trailing/belock exits must be judged on the full table (all cells, hold in weeks) before wiring; do not wire a 12-25% stop on equal-weight size.
## Research-viable wiring plan, gap-fade confirm, ledger primitives (B-776/B-778/B-779b/B-742/B-743/B-746, 2026-10-12 IST)
Lesson: viability is derived at read time, so a wiring plan is just a query over the registry: 291 research-only viable tags pass n>=300 and hold<=30d, and 346 are excluded with a stated reason (hold>30d, atrnone, n<300, avg1 negative controls). The top ranks are 5m chan_kalman cells, while the O'Neil tags have no main.py function, so their replay stays a documented port. The gap-fade confirm harness reuses the Elder simulator (one position per symbol, stop on every trade) but emits v2 tags with gross and net PFnet, leaving v1 untouched. Ledger additions: `margin_call_exit` (never meet a call, close worst first) and `correlation_screen` (reject entries correlated with held names), both pure and tested; dated mark-to-market integration is still owed.
Profit-booking / exit takeaway: rank candidates by PFnet per day held so faster turnover wins ties, and wire only cells whose live path always attaches a stop; the 30-day max-hold survivors drive most O'Neil edge, so test the shorter holds (h8/h12/h20) before wiring any of them.
## Elder stop placement: structural offset and round numbers (B-606, harness built 2026-10-12 IST)
Mechanism: Elder puts the stop beyond the congestion edge and at a non-round price (89.75 not 90) because stops cluster on round numbers and get hunted. Fit for this system: the stop must exist on every trade, so the test is only about WHERE; a structural stop (10-bar swing +/- 0.25-1.0 ATR) is clamped to the ATR multiple so it is never wider than the existing ATR stop, and a round-number arm compares snapping the ATR stop to the nearest round level vs placing it just beyond it. Gap-throughs fill at the open either way, so any benefit can only show in intraday noise stops. No result yet; the same two base entries (EMA13 dip, 20-bar breakout) are used in every cell so only the stop moves. Reuse: bar-count constants (10-bar swing, 30-bar hold) change meaning with candle size; label the universe size in the artifact.
Profit-booking / exit takeaway: a tighter structural stop raises win size per unit risk only if noise does not hit it; read the stop_loss share of exits per offset before preferring any cell, and prefer the shorter-hold cell at equal PFnet.

## Elder pyramiding with the 2% risk rule (B-742, harness built 2026-10-12 IST)
Mechanism: add to a winner only when the stop is already at breakeven (existing risk locked at zero) and total open risk after the add stays within 2% of equity; triggers are the Bear/Bull Power tick or the Force Index 2 flip. Fit: it compounds winners without adding to a loser, and the unit ledger enforces never-average-down plus a stop on every unit. Cost bites: every added unit pays the 0.8% round trip on its own notional, so adds must earn more than they cost. Each arm shares identical management (breakeven at +1R, ATR trail) so only the adds differ; the noadd arm is the control and rejection counts (avg-down, not-breakeven, risk-cap) show how often the rule binds. No result yet. The Vince margin-call / worst-first liquidation part of B-743 remains owed (needs mark-to-market across concurrent positions).
Profit-booking / exit takeaway: with a trail at breakeven or better, an add only risks profit already banked by the trail; compare add arms to noadd on PFnet and avg hold, and keep an add only if net return per bar held rises.

## Elder signal-invalidation exit on generic entries, all candle sizes (B-740, harness built 2026-10-12 IST)
Mechanism: note at entry which signals flagged the trade (EMA13 rising, MACD-H rising) and exit when they fail, or when the opposite Elder-ray signal appears, instead of waiting for the stop. The earlier test (run 38140914889) covered only order-block and volume-profile long entries on daily bars; this harness runs two generic entries in both directions on the trade's own candle, with a 6 ATR catastrophic stop arm so the invalidation exit is the real exit, against stoponly controls. A stop stays on every trade. No result yet. Reuse: a signal that flips every few bars on 15m exits almost immediately, so read avg hold and the share of signal_invalidated exits before judging PFnet; the 0.8% cost dominates quick exits.
Profit-booking / exit takeaway: invalidation exits book profit earlier than a trail; they help only if the shorter hold keeps PFnet at or above the stop-only cell, since faster turnover is the tie-break.


## Edge-stat derivation at read time (B-539/B-540, 2026-10-12 IST)
- Mechanism: expectancy and a bootstrap CI on PFnet are derived from stored Metrics (strategy_edge_stats.py), never stored as flags.
- Fit: with aggregates only, expectancy>0 is equivalent to PFnet>1; the CI uses a two-point win/loss model, so it measures sample-size noise, not tail shape. A tag with PFnet 1.15 at n=150 lands in 'hold' (CI spans the 1.1 floor).
- Reuse: wire into gen_strategy_results_log columns once per-trade lists are emitted by runs.
- Profit-booking / exit takeaway: none directly; it stops promoting or demoting strategies on noise, protecting real money from thin-sample decisions.

## Chan time-series non-overlap re-run (B-807, run 38187474707, 2026-10-12 IST)
- Mechanism: same Chan time-series cells as run 38183172728, but each symbol holds at most one position per cell (strict FIFO), so n is a real trade count (~50k-260k) instead of overlapping signals.
- Result: 240 cells, best PFnet 1.084 (chan_tsm lookback_sign long 1d atr4d0 hold25 lb120), none >= 1.1. The overlapping run's four viable 1h long cells (best 1.549) were an artifact of counting the same move many times.
- Surprise: overlap inflated PFnet by 0.3-0.5 on 1h; always demand a FIFO re-run before trusting a high PFnet on a signal-per-bar harness.
- Reuse: harnesses that open a trade on every signal bar must ship a non-overlap mode from the start; registry n far above trading-days x symbols is the tell.
- Profit-booking / exit takeaway: widest stop (atr4d0) with the longest hold (25 bars) was best, i.e. these trend cells only pay when winners are left to run; tight stops and short holds (atr1d5, hold5) sit at PFnet 0.66.

## MACD divergence, 15m/1h/1d long+short (B-808/809/810, run 38188472624, 2026-10-12 IST)
Mechanism: price/MACD (histogram or line) pivot divergence, ATR stop, max-hold. 108 cells registered as `macddiv__<variant>__<dir>__<tf>__...__v1`. Fit: sweep-wide, SL in every cell; cost 0.8%. Result: 1d long best 0.973, all shorts <=0.63, 15m all ~0.27 (cost-dominated). Only 1h long line_any cells (1.40-1.46) and hist_any atr3_w5 (1.125) clear 1.1, but trades are overlapping signals (n 58k-100k), the same inflation that sank Chan 1h (1.549 -> <1.1 under FIFO). Surprise: wider ATR stops (atr3) beat tight ones, and 15m is pure cost drag. Reuse: always run the non-overlap FIFO variant before believing an intraday cell; B-812 owes it.
Profit-booking / exit takeaway: stop_loss dominates exits (~50-70%) while max_hold survivors carry the profit, so wider stops and letting winners run to the hold limit beat tight stops; do not wire until the FIFO result holds.

## Portfolio-overlay out-of-sample split (B-801, run 38187692191, 2026-10-12 IST)
Mechanism: re-ran the B-800 brk20 overlays (price bucket, pass-trade k10) with a 60/40 time split (IS entries before ~2024-10, OOS after) on 2351 fetched symbols, 1d, cost 0.8%. Fit: tests whether the filters are real edge or in-sample selection. Result: every long cell that looked viable full-sample (pricebucket 1.32-1.44, passtrade4_k10 1.32-2.91) is 1.9-5.0 in-sample but 0.22-0.56 out-of-sample; shorts stay 0.37-0.68 OOS. The filter was fitted to the in-sample window. What surprised: the highest full-sample PFnet (passtrade4 atr3, 2.91, n=635) had the largest IS-to-OOS collapse and OOS win% of 12%. Reuse: any overlay/filter claim needs an OOS split before it is trusted or wired; thin-n high-PFnet cells are the least reliable. Wire nothing from B-800.
Profit-booking / exit takeaway: wide-stop long holds looked good only in the IS window; OOS the stop still loses and the max-hold survivors do not carry, so do not size up or book on these overlays.

## brk20_min_rr (20-bar breakout, ATR stop, min reward:risk) - run 38185670883 (2026-10-12 IST)
- Mechanism: enter on 20-bar breakout, ATR stop always attached, target at RR x risk, optional breakeven at 1R. Replay calls the real main.brk20_min_rr_entry_signal/exit_reason, full universe, 0.8% cost.
- Result: 72 cells, 34 with PFnet >= 1.1, all on 1d (long + short) and 1h long. Best: 1d short atr4_be1_rr4 PFnet 4.21 n=115 win 52%; 1d short atr4 rr3d5 3.09 n=185; 1h long atr4_rr3 1.42 n=2100. 15m is all below 1.1 (costs eat 15m edges).
- Surprises: wider ATR (4) and bigger RR beat atr3; breakeven-at-1R helps modestly on 1d shorts (4.21 vs 3.95) but is identical to no-BE in 5 groups (BE rarely triggers when stop is wide).
- Reuse: sweep ATR above 3 for breakouts; 15m breakouts are not worth testing again at 0.8% cost; thin-n high-PFnet shorts need IS/OOS before wiring.
- Profit-booking / exit takeaway: fixed RR targets of 3.5-4R with a wide ATR stop plus a breakeven shift at 1R captured the edge; max_hold survivors still drive much of the PFnet, so do not shorten the hold without re-testing.
## Vince/Elder portfolio rules: marked ledger, worst-first liquidation, loss-cap sides (B-743/B-773/B-778/B-779, 2026-10-12 IST)
Mechanism: Vince rules (never average down, never meet a margin call, liquidate the worst position first) and Elder's monthly loss cap, expressed as a dated mark-to-market ledger (`simulate_marked_ledger`, long and short) plus a `--side` filter on the loss-cap overlay. Fit: pure offline research code; every simulated trade must carry a stop (no-trade-without-SL), so no-stop trades are refused. Never-average-down is structural (no add path); a winner is never closed to make room for a new entry, only a loser. Result: unit-tested only; no PFnet yet, because the collect stage does not emit per-trade daily mark paths and the full-universe Actions run is owed (B-743). Earlier evidence (B-773 long swing) shows loss caps give no consistent benefit and a halt would be a second kill switch, so the short/intraday cap test is for completeness, not for wiring. Surprised: a margin check run after same-day exits hides the call, so ordering (exit, mark, margin, then entries) matters. Reuse: the B-779 wiring plan ranks 291 research viables by PFnet per day held; replay through main.py before wiring any.
Profit-booking / exit takeaway: when capacity or margin binds, close the worst loser first and never a winner; the stop stays on every trade, and no overlay is wired until it beats the uncapped baseline out of sample.

## Mark Douglas guards: monotonic stop, shadow log, rolling expectancy (2026-10-12 IST)
- Mechanism: stop only ratchets in trade's favour; log every signal taken/skipped with reason (hard gate vs discretionary); alert when last-20 expectancy < 0 or PFnet < 1.0.
- Fit: existing long/short SL sync already refused loosening (now counted); swing sync only places missing SL. Shadow log lets skipped-vs-taken PFnet be measured later. Rolling monitor is alert-only until user signs off auto-pause.
- Result: no backtest yet (overlay replay B-541/B-530 owed).
- Profit-booking / exit takeaway: a never-loosening stop protects booked gains; a pause on negative rolling expectancy limits drawdown from a decayed edge.
## Island reversal validation harness (B-789, built 2026-10-12 IST, run pending)
- Mechanism: gap down then gap up above the gap-down bar's high within 8 bars; long = island bottom, short = mirror on reciprocal prices. The Elder merge printed PFnet 1.571 on n 8837 (hold 7.7d) for the long.
- Fit: a pattern that rare should not give ~1 trade per symbol; the likely cause is stale-print gaps in illiquid names, which cannot be traded at the printed prices. The harness adds px>=20, 20d median turnover >= 1 crore and gap >= 0.5 ATR filters, ex-top-5, per-year PFnet and gross next to net.
- Reuse: any gap-based pattern needs a liquidity and gap-size filter before its PFnet is believed; compare n to the number of tradeable events, not just PFnet.
- Profit-booking / exit takeaway: previous Elder cells earned in max-hold survivors while stops lost; check the exit mix of the island cells before any wiring, and prefer the filter variant that keeps PFnet with shorter hold.

## O'Neil replay follow-up (B-787, reviewed 2026-10-12 IST)
- Mechanism: pivot breakout and new-high entries on 1w bars with 12-25% stops, bar-by-bar port, 6 of 7 tags above 1.1 and ex-top-5 above 1.1.
- Fit: swing category only; the 341 crosscheck diffs between the port and research code are still unclassified, so the numbers are good but not yet trusted for wiring; flatbase short (n=10) fails and stays registered.
- Reuse: always fetch and classify crosscheck diffs in the same session as the result; a diff list left in an artifact is how a result stays unverified.
- Profit-booking / exit takeaway: profit sits in max-hold exits and stop exits lose 20-28%, so the stop-size sweep (not an earlier target) is the lever to test in the wiring replay.

## Minervini sweep reading aid (B-791, 2026-10-12 IST)
- Mechanism: atr4_h60 PFnet 1.342 at 29.6d hold vs the live-style atr1d5 trail 0.908 at 8.3d; atr3 1.181 at 21.6d.
- Fit: the lab already emits exit breakdown and universe size; the gap was only that the artifact was never read. `scripts/minervini_sweep_compare.py` prints them plus (PF-1) per held bar.
- Reuse: when a TSV says "not fetched", fetch it the same day.
- Profit-booking / exit takeaway: the wider trail wins only because winners are held to the max-hold limit; compare (PF-1)/bar and exit shares before widening the live trail, and do not widen on one sweep.

## Gross-PF backfill limits (B-804, 2026-10-12 IST)
- Mechanism: pfgross is filled only on exact artifact reproductions; 0 of 371 viable rows qualified.
- Fit: viability is PFnet-based, so gross is diagnostic only; do not infer gross from net and an assumed cost.
- Reuse: every research script must print gross next to net from the start.
- Profit-booking / exit takeaway: none directly; gross vs net gap shows how much of an edge the 0.8% cost eats, which matters for short-hold cells.

## Chan overlap verdict (B-805, reconciled 2026-10-12 IST)
- Mechanism: overlapping-signal Chan cells showed four viable 1h long cells (best 1.549); the FIFO re-run (B-807) tops out at 1.084.
- Fit: do not wire any chan_tsm cell; overlap counted the same move many times.
- Reuse: n far above trading days x symbols is the tell.
- Profit-booking / exit takeaway: only the widest stop with the longest hold stayed near 1.0, so trend-following cells need winners left to run.

## Confidence gate on the intraday engines (B-421, 2026-10-12 IST)
- Mechanism: min_entry_confidence_pct gates only the ORB path in `_auto_signal_core`; the universal_score engine does not read it.
- Fit: a sweep of that knob on the live universal_score engine would measure nothing, so the intraday half needs its own bar-by-bar driver through the real signal cores; the swing half is in confidence_threshold_sweep.py.
- Reuse: before sweeping a parameter, grep that the engine under test actually reads it.
- Profit-booking / exit takeaway: a stricter entry gate cuts trade count, so judge it by PFnet and by net profit per bar held, not PFnet alone.

## Intraday flatten wiring spec (B-792c, 2026-10-12 IST)
- Mechanism: 42 cells survive a forced 15:15 flatten at PFnet >= 1.1 (best chan_kalman band long 5m 1.78 n=5722).
- Fit: main.py has no kalman band code, so wiring needs a verbatim port, a replay through real functions, an ATR stop on every entry and MIS costs; none started.
- Reuse: confirm the live code exists before calling a cell wiring-ready.
- Profit-booking / exit takeaway: the forced 15:15 flatten removed most cells, so overnight carry was part of the edge; a same-day exit rule must be in the backtest before the numbers are trusted.

## Chan 4h cell and marked-ledger mark paths (B-811, B-743, 2026-10-12 IST)
- Mechanism: B-811 fetches 1h and resamples to session 4h bars (09:15-13:15, 13:15-close) so every Chan family gets a 4h cell; B-743 makes the collect stage store each trade's daily close path so a dated ledger can mark open positions to market, apply Vince's margin-call exit and close the worst loser first.
- Fit: bar-count constants (lookbacks, holds) mean 4h bars, about 2 per NSE session, so cells are not comparable to 1h by number alone; the ledger needs a stop per trade (refused otherwise), matching the no-trade-without-SL rule. Collect marks are bar closes and entry is the collect row's entry close, so results are approximate.
- Result: harness and tests only, nothing run yet; no PFnet to report.
- Reuse: before assuming a harness lacks a candle size, grep its sibling (chan_ext_research.py already had 4h); keep new output flags default-off so old artifacts stay byte-identical.
- Profit-booking / exit takeaway: closing the worst mark-to-market loser first, and never topping up a margin call, frees capital from losers rather than winners; judge it by net profit per bar held once the run exists.
## Subagent s08 status pass (B-791/B-775/B-804, 2026-10-12 IST)
- Mechanism: B-791 artifact (run 38147956271) is not in data/run-artifacts, so the Minervini exit breakdown stays unread; B-775 has 154 viable tags with hold<=5d but SL<=2% is unmeasurable (0 stop-% values); B-804 gross is now present on 770 of 771 viable rows.
- Fit: counts derived from strategy_registry at read time; nothing guessed or stored as a flag.
- Reuse: re-count the registry before trusting a backlog figure; it had gone stale (371 vs 1).
- Profit-booking / exit takeaway: no new exit lesson; the Minervini wider-trail question still needs its exit-reason shares before any trail change.
## Wiring specs: flatten, research-only labelling, Kotak audit (B-792c/B-779/B-369, 2026-10-12 IST)
- Mechanism: three spec docs (INTRADAY_FLATTEN_WIRING_SPEC, VIABLE_TABLE_RESEARCH_ONLY_SPEC, KOTAK_AUDIT_CHECKLIST_MON); no code changed.
- Fit: a resting SL cannot cover the 15:15 IST exchange cancel, so an intraday cell must be flattened by the bot's own market exit before 15:15 with a stop from entry; wiring is blocked first by the missing main.py port and replay.
- Reuse: the viable table already shows Wired/Not wired (B-780); label research-only rows as unable to trade so a high PFnet in the list is not read as a live edge.
- Profit-booking / exit takeaway: flatten at 15:10-15:14 with a retry ladder, never leave an intraday position to the next 09:15 protect pass; compare each day's Kotak realised P&L with the tag's registry PFnet.
## O'Neil crosscheck and universe audit (B-787/B-776, 2026-10-12 IST)
- Mechanism: audit of the O'Neil replay (run 38149046190) against the research code: universe size and the 341 crosscheck diffs.
- Result: universe confirmed. docs/nse_universe.json has 2688 symbols; replay loaded 1955 and the research rerun (38183170721) loaded 1954 with weekly history. The 341 diffs could NOT be classified: run 38149046190 artifacts were never stored on data/run-artifacts, so B-787 stays open. Independent research rerun agrees with the replay (newhigh h26 PFnet 3.54, pivot chase10 h26 3.13, stops about -20%, timeouts carry profit).
- Fit: swing only; no wiring before the diffs are classified and the stop-size sweep is replayed.
- Surprises: the artifact needed for verification was not persisted, so verification was blocked a day later.
- Reuse: persist every run's artifacts to data/run-artifacts in the same session as the result, and classify crosscheck diffs then.
- Profit-booking / exit takeaway: both code paths show the edge in max-hold timeouts and ~-20% stop losses, so test stop width and sizing, not earlier profit targets.

## Elder patterns re-run: measured-move target and tight S/R bounce (B-623, B-607, run 38190581834, 2026-10-12 IST)
- Mechanism: re-run of the Elder pattern harness (1d, 0.8% cost, 9399 symbols with data) added 24 tags: trendline break with measured-move target (trendline__tl_break_mm, mult 0.5 and 1) and congestion-edge bounce with tight S/R stop (consol__edge_bounce_srtight), long and short. The other 228 tags matched run 38148955837 and were skipped as duplicates.
- Result: all 24 new tags fail (PFnet 0.51-0.74, n 56k-207k); 0 of 252 tags in the run are newly viable. Best new: tl_break_mm short atr3 mult1 0.74, win 43%.
- Fit: n far exceeds days x symbols, so signals overlap and counts are inflated; a rule firing this often has a weak filter. Only 1d was run; 15m/1h/4h are owed, plus a non-overlap re-run.
- Reuse: a measured-move target caps winners at a fixed distance; test the uncapped rule exit beside it before adding fixed targets to trend-break rules.
- Profit-booking / exit takeaway: the measured-move cells (PFnet 0.60-0.74) scored below the same family with rule exits (e.g. tl_break long atr3 0.886), so capping profit early did not beat letting winners run to the rule exit.
## 2026-10-12 backfill: families with registry results but no earlier entry (docs-only, numbers copied from docs/STRATEGY_RESULTS_LOG.md and backlog rows; nothing re-run)

Source of every figure below: the generated results log (cost model 0.8%, PFnet net, viable = PFnet >= 1.1 derived at read time). Counts of viable cells are counts of registered tags, not independent strategies (neighbouring ATR/hold cells share trades).

### lunar (full moon / new moon rule), pattern lab, 2026-10-10 IST
- Mechanism: calendar rule, buy at full moon and sell at new moon (long), mirrored as a short, swept over ATR stop and hold. Registry: 176 tags, 20 viable, all in one slice.
- Fit: needs no data feed beyond candles, so costs and SL-on-every-trade are simple (an ATR stop exists as `atr2d5/atr4/atr6` cells; `atrnone` cells could not be wired without a stop).
- Result: best `lunar__full_new__short__15m__atrnone_h25__v1` PFnet 1.682, win 57.2%, n=404 (n200 swing watchlist); stopped `atr6` 1.582. Long best `lunar__full_new__long__1h__atrnone_h30__v1` 1.180, n=6731, win 50.6%. Flatten re-runs (`..._fl1515__v2`) on the FULL universe, n=4965: 15m short `atrnone` 1.411, `atr6` 1.325, `atr4` 1.254, `atr2d5` 1.164; 5m short h75 `atrnone` 1.488 (n=4972), `atr6` 1.285, `atr4` 1.179. The same cells on n200 (n=404) read lower, 1.175 to 1.247.
- Surprise and honest conflict: backlog B-112 records the 2026-10-10 decision "long 0.89, short 0.53, fails", yet the registry holds short cells at 1.2 to 1.7. Not resolved here; the registry numbers are the stored raw data and B-112's text is the older, shorter read. Treat the family as unreconciled, not as validated. A lunar effect has no stated mechanism, so a 404-trade n200 result is a data-mining risk; the full-universe n=4965 flatten figures (1.16 to 1.41) are the number to trust, and even those need the B-112 conflict explained before real money.
- Reuse: for any calendar rule, require the full-universe flatten run and an every-bar baseline (the same lab shows long h20 baseline 1.04 to 1.16 = market beta, so long cells barely above 1.1 are beta).
- Profit-booking / exit takeaway: stops did not rescue it, every stopped cell scored below its no-stop twin (1.68 vs 1.58 vs 1.46 vs 1.31 as the stop tightened); a tighter stop gave up edge, so any live use would run the widest stop that still keeps PFnet >= 1.1 and exit on the calendar date.

### MCX single-symbol indicator cells: supertrend, donchian_breakout, sma_crossover, rsi_reversal, bollinger_mean_reversion (run 38068186964, 2026-10-10 IST)
- Mechanism: textbook indicator rules (Supertrend flip, Donchian channel break, SMA crossover, RSI reversal, Bollinger mean reversion) run through `scripts/mcx_strategy_sweep.py` on yfinance GC/SI/CL/NG/HG proxies (US futures proxies for MCX gold, silver, crude, natural gas, copper), long and short, 5m/15m/1h/1d, ATR stop or none. Each family 120 tags, category futures.
- Fit: MCX/Kotak is the target venue, but the data is a proxy and each cell is ONE symbol, so n is tiny: viable cells have n=14 to 33. The 0.8% cost model is applied. Cells with `atrnone` have no stop, which the 2026-10-11 no-trade-without-SL rule forbids; they only fit where the live path attaches the option premium trailing SL.
- Results (best per family, all 1d): `rsi_reversal__si__long__1d__atrnone__v1` 4.098, win 76.5%, n=17 (11 of 120 viable); `bollinger_mean_reversion__si__long__1d__atrnone__v1` 3.659, win 70.6%, n=17 (13 viable), stopped `atr2d5` 2.043; `supertrend__gc__long__1d__atr2d5__v1` 2.286, win 50.0%, n=18 (10 viable); `donchian_breakout__ng__short__1d__atrnone__v1` 2.423, win 50.0%, n=16 (6 viable); `sma_crossover__gc__long__1d__atrnone__v1` 2.139, win 39.4%, n=33 (4 viable). Worst cells in each family are about 0.0.
- Surprise: the high PFnet is a small-sample artefact as much as an edge (n 14 to 33), and the B-361 re-run showed only 8 of 27 no-stop cells above 1.0 stayed at or above 1.1 once ATR-stopped (see the MCX daily cells entry above). Short-horizon cells (5m/15m/1h) were mostly not viable.
- Reuse: treat n < 100 PFnet as a lead, never a pass; wire an MCX cell only if every stopped variant of it clears the floor.
- Profit-booking / exit takeaway: the best cells hold about 80 to 256 hours (days), and the no-stop twin beat the stopped one every time (Bollinger SI 3.66 vs 2.04), so the stop costs edge; accept that cost, because no trade without SL is not negotiable, and book profit at the signal-reversal exit rather than a fixed target.

### donchian 8-week fade, pattern lab (2026-10-10 IST)
- Mechanism: fade a Donchian channel extreme (an 8-week-extreme reversal), long and short, h20 hold, ATR stop sweep; 768 tags, 7 viable.
- Fit: daily bars on the n200 swing watchlist and an ETF universe; swing engine, shares need an SL (the `atr6` variants carry one).
- Result: `donchian__8wk_fade_etf__long__1d__atrnone_h20__v1` 1.391, win 51.6%, n=884; `donchian__8wk_fade__long__1d__atrnone_h20__v1` 1.367, win 53.2%, n=2469, avg hold 125 hours. Worst cell 0.169.
- Surprise: both viable winners are long and sit near the market-beta band (the lab's every-bar long h20 baseline is 1.04 to 1.16), so the margin over beta is small.
- Reuse: always compare to the every-bar baseline in the same lab before calling a long daily fade an edge.
- Profit-booking / exit takeaway: it holds the full 20 bars; with only about 0.2 PFnet above beta, shortening the hold is the lever to test next, not widening the stop.

### Point and Figure box2pct, pattern lab (B-12, 2026-10-10 IST)
- Mechanism: 3-box-reversal double-top/double-bottom signals at 1% and 2% boxes (Murphy ch.11). 256 tags, 4 viable.
- Fit: daily bars on n200 swing; a signal-only test, so count targets, 45-degree lines and P&F averages were not built (they refine exits/filters of a signal without edge).
- Result: best `pnf__box2pct__long__1d__atrnone_h20__v1` 1.154, win 51.2%, n=3589; `atr6` 1.136, n=3591. Per B-12, long 1.13 to 1.15 and short 0.43 to 0.46. Worst 0.131.
- Surprise: the long result equals the beta baseline (1.04 to 1.16); short is clearly negative.
- Reuse: signals that only reproduce the long baseline are market beta, skip their exit refinements.
- Profit-booking / exit takeaway: no exit tested rescued the short side; do not spend effort on P&F targets until the entry beats the baseline.

### Candlestick pattern lab: tasuki gap and the other candle families, pattern lab (2026-10-10 IST)
- Mechanism: Nison-style patterns run as entry rules with short holds on 1d/1h/15m. `tasuki` 124 tags, 4 viable. Other candle families mostly peaked in the baseline band: engulfing best 1.049, hammer 1.068, harami 1.096, piercing 0.997, soldiers 1.088; `kicking` (best 1.14), `dragonfly` (1.269) and `belt` (1.167) had 2 to 3 viable cells each.
- Result: `tasuki__gap_etf__short__1d__atr6_h3__v1` PFnet 2.079, win 58.0%, n=81, avg hold 18.75 h (ETF universe; `atrnone` identical 2.079).
- Surprise: the one standout is a short, ETF-only, n=81, too small to wire; the large-n pattern cells (thousands of trades) land near beta, about 1.0 to 1.1.
- Reuse: candle patterns alone carry no robust edge here; use them only as filters on a higher-PFnet trigger.
- Profit-booking / exit takeaway: the h3 hold (under one day) is the strength, fast turnover; if a pattern ever gets wired, keep the 3-bar exit.

### Parabolic SAR and Box Theory (bidirectional 5m, runs 37408733557 and 37408735190, 2026-10-06)
- Mechanism: Parabolic SAR reversal (acceleration init 0.01 to 0.02, max 0.1 to 0.2) and Box Theory zone-touch (tolerance 15/20, wick), both pooled long+short, 5m over 60 days, FULL universe (2642 of 2688 fetched), research-stage reimplementation.
- Result: both fail hard. `box_theory__zone_touch__bidirectional__5m__tol15_wick1d5__v1` 0.138, win 10.6%, n=233145; best SAR cell 0.114, win 12.0%, n=488066. Worst 0.129 and 0.063. Daily PSAR flip on swing is better but still below the floor: `psar__flip__long__1d__atrnone_h20__v1` 1.092, n=6812.
- Surprise: win rates of 10 to 12% at about 2.2 hours held means constant trading, and the 0.8% round-trip cost destroys it; huge n makes this a decisive, not noisy, fail.
- Reuse: any 5m always-in-market flip system is dead on arrival under 0.8% costs; check trade count against cost before running.
- Profit-booking / exit takeaway: exits are not the issue, trade frequency is; fewer, longer trades (psar 1d h20 at 1.09) get close but not past the floor.

### Chan (Algorithmic Trading) sub-families: chan_shape, chan_alexander, chan_updays, chan_ema_regime and neighbours
- Mechanism: variants extracted from Ernest Chan's book (see the Book 3 entry) and run in the Chan cells and extension runs: shape/gap/updays/EMA-regime filters and the Alexander filter.
- Result (registry, best per family): `chan_shape` 3.656 (53 tags, 3 viable); `chan_alexander` 1.774 (61 tags, 6 viable); `chan_ema_regime` 1.676 (80, 4 viable); `chan_updays` 1.436 (52, 2 viable); `chan_gap` 1.445 (6 of 6 viable); `chan_xsmom` 1.396 (6 of 9 viable); `chan_zmr` 1.172 (81, 2 viable); `chan_mrgate` 0.631, `chan_gapmom` 0.177, `chan_lateday` 0.126, `chan_kl` 0.516 all fail.
- Surprise and caveat: the Chan overlap verdict (B-805/B-807, entries above) found overlapping holding windows inflate these counts; the non-overlap re-run is the number to read. Families that pass are small slices of a large grid, so multiple-testing inflation applies.
- Reuse: read the Chan non-overlap entry before trusting any `chan_*` PFnet above.
- Profit-booking / exit takeaway: the failing late-day and gap-momentum cells show holding into the close or chasing the gap loses, so exit at the first sign of the signal reverting.

### Trade management cells: trademgmt_entry and trademgmt_exit (Douglas/Elder, 2026-10-12)
- Mechanism: 480 tags (228 entry, 252 exit) on the entry/exit management family; see the Douglas/Elder trade management entry above for the harness.
- Result: `trademgmt_exit` best PFnet 2.468 with 6 of 252 tags viable; `trademgmt_entry` best 1.001 with 0 viable of 228.
- Surprise: all the gain is in exits, none in entries; entry management alone does not clear the floor.
- Reuse: tune exits, not entries, when a family's entry is already fixed.
- Profit-booking / exit takeaway: only 6 of 252 exit variants cleared 1.1, so most exit styles are neutral to harmful.
## brk20_min_rr IS/OOS harness and wiring spec (B-798, 2026-10-12 IST)
- Mechanism: 20-bar close breakout with ATR stop and a minimum reward:risk room check; 34 of 72 pooled cells clear 1.1 (1d long/short, 1h long), best 1d short atr4_be1_rr4 4.21 n=115, holds ~12-14 bars.
- Fit: the pooled run cannot separate a real edge from a fitted cell or a favourable regime; `scripts/brk20_isoos.py` buckets each trade by entry date (same real main.py fns, same cells) so a filter/overlay claim (breakeven ratchet, 1h long) must hold OOS with n>=30 before any wiring. Swing engine for long, short engine for short, ATR stop is the resting SL on every trade.
- Surprised: be1 vs no-ratchet was identical in 5 of 36 groups, so a ratchet claim is weak until OOS says otherwise; 1h cells carry overnight, so the 15:15 flatten lesson (B-792c) may erase them.
- Reuse: any new pooled result gets an IS/OOS rerun through the same harness before wiring; entry-date bucketing keeps IS+OOS exactly equal to the pooled sums.
- Profit-booking / exit takeaway: the edge sits in winners held ~12-14 bars to the 4R-ish target, so the breakeven ratchet is only worth keeping if OOS PFnet beats the no-ratchet twin; do not tighten exits on pooled numbers alone.

## brk20_min_rr IS/OOS result (B-798, run 38247769897, 2026-10-12 IST)
- Mechanism: the 72 pooled brk20_min_rr cells (20-bar breakout, ATR stop, min reward:risk) re-run through the same real main.py functions, split by entry date at 2026-09-18 over 730d, 0.8% cost; 144 research-only tags (`main_replay_is` / `main_replay_oos`).
- Fit here: 1d is the only timeframe with a real edge. SHORT 1d holds OOS in all 12 cells (OOS PFnet 1.71-10.26, n 39-216; atr3 cells 1.71-2.20 with n 94-216). LONG 1d holds for rr3d5/rr4 and atr4 cells (OOS 1.31-1.73, n 108-257) but atr3 rr3 fails (0.90).
- Surprised: 1h long looked best pooled (IS 1.2-2.1) yet OOS is 0.55-0.80 in every cell, and 15m collapses likewise (IS 0.2-0.6, OOS 0.14-0.92); tiny-n 1h short atr4 cells show OOS 1.04-4.29 with IS 0.5, which is noise, not edge. The breakeven ratchet (be1) did not beat its no-ratchet twin OOS.
- Reuse: always read the OOS half with n>=30 before wiring; only 1d short (all cells) and 1d long (rr3d5/rr4, atr4) survive. Wiring needs the user's go-ahead and a live short-swing path with BUY protective SL, which does not exist (short engine is intraday). Tags are new, old pooled tags untouched.
- Profit-booking / exit takeaway: the profit is in winners held to the wide-stop target/timeout on 1d; the wider atr4 and larger rr cells keep or raise OOS PFnet, so do not tighten the target, and skip the breakeven ratchet.

## macddiv 1h long, strict-FIFO non-overlap (B-812, run 38192366174, 2026-10-12 IST)
- Mechanism: MACD line/histogram divergence (pivot half-width 5), long, 1h, ATR stop, 0.8% cost, one position per symbol per cell, 2483 symbols.
- Result: line_any atr3_w5 PFnet 1.462 (n 58015, win 34.6%, avg hold 23.7 bars); atr2_w5 1.416; atr1d5_w5 1.400; hist_any atr3_w5 1.138. Tags `macddiv__<variant>__long__1h__<atr>_w5__nonovl__v2`. All four clear 1.1 and survive the overlap removal (raw 69777 -> 58015 for line_any).
- Surprise: PFnet barely fell versus the overlapping run, so the edge is not an overlap artefact. Wider stops (atr3) win more: max_hold_timeout exits (about 57%) carry the profit, stop_loss exits (41%) lose.
- Reuse: no IS/OOS split yet and no live 1h entry path; do both before any wiring. Short mirror already registered separately.
- Profit-booking / exit takeaway: let trades run to the max-hold bar with a wide ATR3 stop; tighter stops raise the stop-out share and lower PFnet.

## Island reversal validation, 1d (B-789, run 38192367677, 2026-10-12 IST)
- Mechanism: island reversal (gap-isolated cluster) entries, 1d, ATR stop (1.5/2/3) plus rule exit, 30 cells = 5 filters (none, gap05, px20, turn1cr, liq_gap) x long/short; full universe (2351 symbols with data), 0.8% cost.
- Result: LONG cells are strong: none PFnet 1.50-1.56 (n~8.9k), gap05 1.93-1.98 (n~3.2k, ex-top5 1.77-1.82), px20 1.31-1.36, turn1cr 1.27, liq_gap 0.93-0.96 (below floor). SHORT mirrors all fail: 0.64-0.76. 15 long cells viable by PFnet. Hold ~7-8 bars.
- Surprise/caveat: by-year PFnet decays, gap05 long 6.1 (2021) to 1.2 (2025) to 0.23 (2026, n=528), so the headline is dominated by older years; overlapping signals not yet removed. Wider ATR3 stop cuts stop-outs from 27% to 7% and lifts PFnet, with rule_exit carrying profit.
- Reuse: do not wire on the headline: need non-overlap FIFO and an IS/OOS split with the 2026 decay explained (regime or crowding) first. Shorts of the same pattern do not work, so the bidirectional rule is satisfied with a registered fail.
- Profit-booking / exit takeaway: rule_exit (gap-fill style) books most profit within ~7 bars; a wide ATR3 stop avoids premature stop-outs without hurting that exit.
## IS/OOS + strict-FIFO harness for island long and macddiv 1h long (B-815/B-814, 2026-10-12 IST)
- Mechanism: no new signal. The island (gap-down then gap-up inside 8 bars) long cells >=1.1 and the macddiv 1h long cells are re-run with independent per-signal trades, a strict FIFO one-position-per-symbol filter, then bucketed by ENTRY date into in-sample / out-of-sample (split_date, else 60% of each symbol's time span).
- Fit: a pooled PFnet cannot tell a real edge from a fitted cell or one regime; both lines are viable only on pooled numbers so far and neither has a live SL-attached path. Every trade keeps the ATR stop and the 0.8% cost.
- Result: pending dispatch. Tags `<old minus __v1>__nonovl__v2`, `__segis__v2`/`__segoos__v2` (island) and `<old minus __v1>_nonovl_segis__v2`/`_segoos__v2` (macddiv); IS+OOS sums must equal the nonovl pooled cell exactly.
- Surprise to check: er.simulate already enforces one position per symbol, so non-overlap should barely move PFnet; the real test is whether OOS PFnet stays >=1.1. Per-symbol fractional splits are approximate, an explicit split_date is the clean version.
- Reuse: any pooled winner gets this nonovl + IS/OOS pass through the shared helpers (macddiv_nonoverlap.split_ts/segment_trades) before wiring.
- Profit-booking / exit takeaway: unchanged until OOS is known; if OOS holds, the edge sits in long holds to max-hold with wide stops, so do not tighten exits.

## O'Neil cup-and-handle / base family, 1d and 1w (oneil-research.yml run 38193479637, 2026-10-12 IST)
- Mechanism: O'Neil base patterns (cup-with-handle, cup-no-handle, saucer, double bottom, flat base, pivot, new-high, RS screen) bought on breakout with chase 5/10%, RS filters (none/qual1/rs80), ATR stop 2/3, optional average-down (avg1) and trailing (trl1), max-hold 12-26 weeks (1w) or 20-60 days (1d), both directions, 0.8% cost, full universe. 1218 cells per timeframe, tags in naming grammar; raw TSV/JSON kept in docs/backtest_data/oneil_{1d,1w}_run_38193479637.*.
- Fit: swing long engine, SL on every trade (ATR stop). Longer max-hold with avg-down at atr3 gives the highest PFnet: on 1d cup_handle h60 avg1 rs80/rsnone ~2.3-2.55 (n 220-290 rs80, n>1000 rsnone); on 1w cup_handle h26 avg1 ~3.4-3.56 (n 600-930, win ~59%, avg hold ~112 trading days). Small-n flatbase 1w cells (PFnet 6-8.7, n~31) are noise-prone, do not rank on them.
- Result: many cells >=1.1 (see STRATEGY_RESULTS_LOG); every registered research-only (entry_fn=None). Stops lose about -8..-10% per trade while timeouts win +5..+16%, so the profit is carried by survivors held to max-hold, as in OB/VP and Minervini. 1w cells hold ~100+ trading days, far above the 30-day hold the viability rule covers, so they are judged separately.
- Surprise: 84 of the 1d and 1w tags were already registered from the earlier partial run (kept as is, not overwritten). Overlapping signals inflate n; PFnet may differ under one-position-per-symbol FIFO.
- Reuse: run strict non-overlap FIFO and IS/OOS (macddiv_nonoverlap helpers) on the top 1d cells with n>=250 before any wiring; prefer the 1d h60 cells (hold ~40 days) over 1w only after checking the hold-limit rule.
- Profit-booking / exit takeaway: do not tighten exits or trail early; stop-outs lose 8-10% and the edge is the long-hold timeout winners, so let winners run to max-hold with a wide atr3 stop (avg-down helps) and judge shorter-turnover variants only on equal PFnet.

## Portfolio overlay harness, pfovl__ cells (portfolio-overlay-research.yml run 38193834873, 2026-10-12 IST)
- Mechanism: brk20 and dip signals with portfolio-level overlays (index-regime gates, risk-per-trade and position caps, loss-streak and pass-trade throttles, drawdown ladders) plus calendar slices (year/month/price bucket/turnover quartile/bootstrap DD) over the full universe plus ETFs, 1d, 0.8% cost, 792 rows.
- Fit: overlays are portfolio-sizing ideas, not entries. The harness uses overlapping signals, and calendar-slice cells (year/month/passtrade) are data-mined, so a high cell like brk20_passtrade4 (PFnet 2.95) or dip_month m4 (1.83, n 13.8k) is a selection artefact until proven on strict non-overlap FIFO plus IS/OOS.
- Result: 26 of 792 rows >=1.1, all calendar-slice type; the base brk20 cell is 0.82. 744 tags were already registered from run 38176399634 (same tags, universe 2351 vs 2348 fetched, near-identical numbers); only the 48 new tags (corr30/k10 cells, all PFnet < 0.1) were added, raw file kept in full. Registered research-only so the real-money gate stays closed.
- Surprise: the shorts mirror the longs on month slices (dip_month short m2 1.75), a sign of slicing noise rather than a directional edge.
- Reuse: never wire a slice cell; re-test only the top few with non-overlap FIFO and an IS/OOS split on a date cut.
- Profit-booking / exit takeaway: overlays that throttle entries do not change the exit edge; base brk20 rule exits lose, so no profit-booking change follows from this run.
## O'Neil extension grid, full 1d + 1w cell sets (run 38207070547, 2026-10-12 IST)
- Mechanism: 564 cells (282 per timeframe, 141 long + 141 short each) across the O'Neil families (pivot breakout/exit, tightness combos, leaders first-high, tight area, pullback, RS-line new high, head-and-shoulders, base-on-base, abnormal strength, volume percentile, trendline, triple, shakeout, flag, handle-from-top), swept over ATR 2/3 stop, hold 8-130 bars. Raw TSV/JSON kept under `docs/backtest_data/oneil_ext_{1d,1w}_*`; 437 new tags registered research-only (127 were already registered from the run 38147513010 log slice, skipped, never overwritten) by `strategy_registry_oneilext2.py`.
- Fit: swing-style, SL-attached ATR stop on every trade, so the no-trade-without-SL rule is satisfiable; the 0.8% cost is small against multi-week holds. The problem is evidence quality, not cost: cells re-enter on every qualifying bar with no strict-FIFO non-overlap and no IS/OOS split (n up to 50,615), so serially correlated trades inflate both n and PFnet.
- Result: long 1d 68/141 cells >=1.1 (60 with n>=250, best pivot-breakout x tightness-range 2.955 n=355; leaders first-high 2.03 n=1598); long 1w 137/141 >=1.1 (best 3.13 n=498, leaders 2.77 n=2175, tightarea 2.74 n=3889). Short: 1d 0/141 >=1.1 (max 0.908); 1w only 2 (shakeout plus3 pm2 h8, 1.26/1.24 n=883, hold ~7 weeks). Sub-250-n cells (flag, handle-from-top; 20 cells >=1.1) are anecdotes.
- Surprise: 137 of 141 weekly long cells clearing 1.1 is a regime/overlap signature (a rising-market sample), not 137 independent edges; the opposite direction fails almost everywhere, which fits a long-biased sample. Weekly holds average 10-22 weeks, far above 30 trading days for most cells, so the 30-day viability rule does not cover them anyway.
- Reuse: before wiring any cell, rerun with strict-FIFO non-overlap plus IS/OOS split (macddiv_nonoverlap helpers), check across a down-market window, and prefer the shortest-hold cell that clears the floor (1d pivot x tightness and leaders h40 hold 25-32 days).
- Profit-booking / exit takeaway: the good cells are max-hold survivors with wide ATR3 stops (trail/stop exits average -9 to -13%), so profit comes from letting winners run to the time exit; do not tighten stops or book early on these, and prefer the h40 1d variants over h130 for turnover.

## Douglas/Elder trade-management re-run, 1d (douglas-trade-mgmt-research.yml run 38207068830, 2026-10-12 IST)
- Mechanism: same 480 cells as run 38174269343 (entry variants limit/wk-gate/adx/mom/cooldown/chase, exit variants min reward:risk, scale-out, breakeven ratchet, time stop; long+short; ATR 1.5/2/3), 1d, 0.8% cost, 5376 listed / 4700 fetched (one more symbol fetched than before). Raw: docs/backtest_data/douglas_trademgmt_run_38207068830.json + _table.txt.
- Fit: swing engine, ATR stop in every cell, so SL-on-every-trade holds. Only 6 of 480 cells clear 1.1, all `brk20_min_rr` with a minimum reward:risk target (n>=250 for all): short atr3_rr4 2.468 (n 275, win 43.6%, hold 12.4d), long atr3_rr4 1.761 (n 422), short atr3_rr3 1.707 (n 587), long atr3_rr3 1.38 (n 912), short atr2_rr4 1.308 (n 867), short atr3_rr2d5 1.22 (n 1086). Every other family (scale-out, ratchet, time stop, entry gates) sits at 0.8-1.05.
- Result: all 480 tags were already registered from run 38174269343, so nothing new was added (never overwritten). Reproduction: no cell crossed the 1.1 line either way; mean |dPFnet| 0.046, max 0.236 (short limit-entry atr3_nb5 0.648 -> 0.412 on n 46449 -> 46467). Large moves come from huge-n overlapping-signal cells where one extra symbol shifts a few big trades; high-PFnet small-n cells reproduced within 0.03.
- Surprise: the min_rr cells that look best have small n relative to universe (275-1517 trades from ~4700 symbols) because the minimum reward:risk filter discards most breakouts, and their profit still comes from rule_exit/timeouts with ~14% stop-loss share. Signals overlap per symbol, so n and PFnet are inflated versus one-position-per-symbol FIFO.
- Reuse: before wiring any min_rr cell run strict non-overlap FIFO plus IS/OOS on the 6 cells (B-840); the short mirror (atr3_rr4) beating the long is a bidirectional finding to carry into the swing short path; scale-out (dip/brk20 scale_atr/scale_struct, ~0.93 vs 0.875 baseline) helps a little but stays below 1.1, and breakeven ratchets are neutral to negative (0.835-0.872 vs 0.852-0.875), so neither is worth wiring on its own.
- Profit-booking / exit takeaway: a fixed minimum reward:risk target of 3-4R with a wide atr3 stop is the only profit-booking rule here that lifted PFnet above 1.1; partial scale-out lifted brk20 only from 0.875 to ~0.93 and breakeven ratchets did not help (0.835-0.872), so book at a 3-4R target rather than in pieces or by locking breakeven.

## Elder MACD / directional system / gaps re-run, 1d (elder-macd-dirgap-research.yml run 38208431466, 2026-10-12 IST)
- Mechanism: 120 cells across Elder's MACD cross/histogram tick/exhaustion/divergence, Directional System (+DI/-DI/ADX with adx-rising, dull-gate, overheat variants) and gap families (breakaway, continuation, exhaustion fade, common fade), long and short each, ATR 1.5/2/3 stops, 1d, 0.8% round-trip cost, 7059 symbols fetched summed over families. Re-run of 38177547622 (7049).
- Fit: swing engine with an ATR stop in every cell, so SL-on-every-trade is satisfiable. The gap fades hold only 3.4-3.7 days (fast turnover, preferred by the turnover rule); MACD cells hold 6-25 days. The danger is evidence quality: macd and dirsys cells print n of 70k-250k from overlapping per-symbol signals.
- Result: all 120 tags already registered (from 38177547622), so nothing new added and nothing overwritten. 6 of 120 cells clear 1.1, all long: gaps exhaust_fade atr3_nb5 1.252 (n 4412, win 34.8%), atr2_nb5 1.234, atr1d5_nb5 1.223; macd hist_exhaust atr3_zf1 1.157 (n 96207); gaps common_fade atr3_nb5 1.122 and atr2_nb5 1.10 (n 5425). Every short cell is below 1.0 (best gaps common_fade short 0.96). Reproduction: mean |dPFnet| 0.017, max 0.228, no cell crossed the line.
- Surprise: the best gap-fade longs win only ~35% yet clear 1.1 because ~95% exit by rule_exit with a small fraction stopped; the short mirror of the same logic fails, which fits a rising-market sample rather than a symmetric edge. macd hist_exhaust long degrades with tighter ATR stops (stop_loss share 20% at atr3, 34% at atr2).
- Reuse: before wiring any of the 6 cells run strict non-overlap FIFO plus IS/OOS and a down-market window (B-850, B-852); run the intraday candle sweep for macd and dirsys (owed); the best cell in every family is an ATR3 one.
- Profit-booking / exit takeaway: the winning gap-fade cells book profit through the strategy's own rule exit after ~3.7 days with a wide ATR3 stop rarely hit (176 of 4412), so let the rule exit book the gain rather than tightening the stop, which cut PFnet 1.252 -> 1.223 at atr1.5.

## Option premium backtest: durable candles and a BS proxy (B-860, 2026-10-12 IST)
- Mechanism: the live options engine (`_run_fo_strike_setup_scan`, `FO_OPTION_*` trailing SL: 3% initial stop, arm at +1%, trail 1%) trades option premium, but the only real premium history is `fo_option_candles`, built tick by tick by `kotak_fo_candle_feed.py` (5m bars). Kotak serves no historical option candles and `nse_fo_chain.py` only gives point-in-time chain snapshots, so history exists only if we keep what we record.
- Fit: finding was that `fo_option_candles` sat on Render's ephemeral disk and was explicitly skipped by the generic Upstash mirror, so every restart erased it and no history could ever accumulate. Fixed with `fo_candle_journal.py` (per-IST-day Upstash entries, restored at startup, pushed per tick, a wiped local DB can never shrink the remote copy). Individual contracts also have short, discontinuous lives (weekly expiry), so even durable data will cover few full lifecycles for a while.
- Result: no backtest yet. `option_premium_proxy.py` gives a Black-Scholes premium (ATM/OTM, delta, theta, round-trip cost, a trailing-SL trade simulator) from index candles plus an assumed IV and days to expiry. It ignores skew, IV change, spread width and liquidity, so it is labelled PROXY and must never support viability or open the PFnet gate.
- Surprise: a flat market already loses money on a long option from theta plus spread plus fixed brokerage, and a 1% trail on a 5m premium series is tight relative to bar noise, so the proxy shows stop-outs dominate unless the underlying trends; real bars are needed to see if that holds.
- Reuse: screen ideas on the proxy only to discard clear losers; judge anything that survives on accumulated real bars, with the proxy IV calibrated against them; keep the journal running from the first day, never as a follow-up.
- Profit-booking / exit takeaway: with a 1% trailing stop on a decaying premium the exit is decided by noise and theta, so test wider trail and a time/expiry exit on real bars before trusting any trailing profit-booking setting.
## Options entry diagnosis (GET /fo-entry-diagnosis, 2026-10-12 IST)
- Mechanism: not a strategy; a read-only view that explains why the per-strike setup scan (_run_fo_strike_setup_scan) places no index call/put buys. It combines the real F&O and master switches, the 09:20-15:00 IST entry window, per-tag viability (PFnet floor, switch ignored), the in-memory strike monitor status counts, held sides and today's skipped_* codes from real_fo_trades, and names one primary blocker per underlying.
- Fit: respects no-token and no-account-data (no balances, capital or order ids). A strike needs 30 five-minute candles that only accumulate forward, so after any restart every strike sits in warming_up_need_30_candles for about 2.5 hours; combined with the 09:20 window start this can silently mean no trades for most of a session.
- Result: tests only (5 passing); live reading owed after deploy (B-853).
- Surprise: the monitor is in-memory, so a Render restart resets the warm-up clock, a likely hidden cause of zero option buys.
- Reuse: when a category shows no trades, ship a blocker-priority diagnosis endpoint before touching strategy parameters.
- Profit-booking / exit takeaway: none from this item; it only unblocks entries, and every option entry already carries a trailing SL (max 3% of premium) that books profit as the premium ratchets up.
## Index option triggers: swing entry functions on index underlyings (B-853, harness built, not yet run, 2026-10-12 IST)
- Mechanism: no option-premium history exists, so the options category cannot be backtested on premium. Instead the real main.py swing entries (power_play, primary_base, minervini_vcp_livermore, order_block_delta, gap_and_go) are run on ^NSEI/^NSEBANK/^BSESN candles at 5m/15m/1h/1d; a LONG signal maps to buying a call and the reciprocal-price mirrored SHORT signal to buying a put, with an ATR chandelier trail (2/3/4.5/6, stop always attached), strict non-overlap FIFO and an IS/OOS split.
- Fit: a trailing SL on every single-strike option is already the rule, so the exit shape matches the live path. The cost model does not transfer: 0.8% round trip on the underlying is harsh for an index (small moves) yet option leverage amplifies the move, so the harness prints PFnet gross and at 0.8% and 0.1%; none of them is premium P&L. Index volume from yfinance is frequently 0, which silently disables every volume-gated entry; primary_base's IPO-recency proxy (history <= 756 bars) will rarely fire on an index.
- Result: harness only. A synthetic random-walk dry run confirmed the plumbing (signals fire for primary_base and minervini_vcp_livermore, FIFO and JSON output work); no real-data PFnet exists, nothing registered.
- Surprise: the dry run showed most volume-gated entries are rare even with synthetic volume, so expect small n on indexes (3 indexes, one position at a time); judge by OOS and the pooled cell, not a single index.
- Reuse: always emit volume availability next to a zero-trade cell; pass full history (not a truncated window) to any function whose rule depends on history length; keep the trigger test separate from a premium model, which still needs a Black-Scholes/IV or live-chain recording before any real option entry is wired.
- Profit-booking / exit takeaway: for a weekly option the underlying trail (wide ATR, 30-bar cap) is only a proxy; the real exit must trail the option premium itself and book before the ~5-day expiry decay, so treat any underlying-trail PFnet as an upper bound on premium booking, not an estimate.

## Elder trend / regime / MA-system / context (run 38209280422, B-862, 2026-10-12 IST)
- Mechanism: 20 Elder-derived cells in three families on daily bars, both directions via reciprocal-price mirror, ATR stop 1.5/2/3 on every trade, 0.8% round-trip cost, 30-bar max hold: ma (4-step MA system, whipsaw margins, Donchian 4/9/18 triple), regime (flat-EMA filter, trend-vs-range switch, ensemble vote, weekly alignment, never-buck-the-trend, signal cooldown), osc (MACD-H triple divergence and 63-bar record, ADX exit, RSI trendline break, gap time-stop, opening-gap fade).
- Fit: these are trend/context filters on a single-name daily entry; at the 0.8% cost model they gain little because gross PF stays near 1.0-1.2 (best gross 1.435 for open_gap_fade short, but 123k trades at 2.1-bar holds eat it in costs). Every cell keeps its SL, so no "no trade without SL" conflict.
- Result: 210 tags, 8064 universe / 7053 fetched, none clears PFnet 1.1. Best per family (ATR3): gap_timestop long nb5 0.984 (n=20555, win 33.7%, 18.2 bars), wk_align_aligned long 0.965 (n=27805, 11.4 bars), ensemble need3 veto0 0.933 (n=66389), open_gap_fade short thr0.02 0.903 (win 51.9%, 2.1 bars), ma_whipsaw_margin 0.871, donchian_triple 0.835. The weekly-aligned cell beats its counter-trend control (0.965 vs 0.785), and the gated never-buck cell beats its against-trend control (0.778 vs 0.702): the weekly-trend filter helps, but not enough to cover costs.
- Surprise: wider stops (ATR 3) won in every family, again; stop_loss exits at ATR 1.5 were 2-5x more frequent with lower PFnet. adx_exit_hard and adx_exit_soft printed identical results (same as flat_off/flat_on-style no-effect cells, PFnet 0.6), which suggests the exit condition rarely binds and should be checked before reading it as "no edge". open_gap_fade has the highest win rate (50%+) yet PFnet under 1: many tiny wins, costs dominate.
- Reuse: filters that raise gross PF only matter if n shrinks less than cost drag; test the filter on top of an already-viable trigger (not as a standalone) and prefer the aligned-weekly filter. Run open_gap_fade LONG mirror and other candle sizes before closing the idea.
- Profit-booking / exit takeaway: the rule_exit share is large in the high-win cells but the stop_loss share drives PFnet; at 2-day holds with 50% wins the cost per trade is the binding constraint, so book fewer, larger moves (wider ATR, longer holds) rather than frequent small gap-fade wins.

## Elder batch 3 rerun (run 38211452647, B-863, 2026-10-12 IST)
- Mechanism: same 492 osc/struct/breadth/chan (1d) and ORB (5m) cells as run 38169625565, ATR stop sweep, 0.8% round-trip cost, both directions; universe NIFTY200 + 182 ETFs, not the full universe.
- Fit: the daily divergence class (osc__div_class, kb_oscrsi / kb_oscmacdh) prints PFnet 2.43 / 2.40 on n~10.7k, win 38%, 24.8-bar holds, mostly max_hold_timeout winners with stop_loss losers; it keeps an ATR stop so it would satisfy no-trade-without-SL, but it is unvalidated beyond this restricted universe.
- Result: 20 of 492 tags >= 1.1 PFnet. The same cells printed 0.958 / 0.954 in the first run (n differs by ~15-20 trades), so a 2.5x PFnet move came from a small data-window shift: the number is fragile or an artifact, not an edge until explained. breadth cells have n=1-6 (PFnet 3-16 is noise). 9 cells had PFnet undefined (no losing trade, n=1-2).
- Surprise: identical code and universe gave very different PFnet two runs apart; trust a result only after it reproduces on a second window and on the full universe. PFnet gross can be None in the raw output, so loaders must tolerate it.
- Reuse: always register a rerun under a new tag (run-id suffix) instead of overwriting; compare reruns of the same cells as a stability test before any wiring.
- Profit-booking / exit takeaway: the profit sits in 30-bar max_hold_timeout survivors while stops take the losers (6581 timeouts vs 3860 stops for kb_oscrsi); until a reproducible run confirms it, do not bank on holding to timeout, and prefer a faster exit variant only if it keeps PFnet >= 1.1 on the full universe.

## Index option triggers, non-volume rerun harness (B-866, 2026-10-12 IST)
- Mechanism: run 38214076382 showed 0 trades at 5m/15m/1h because yfinance index bars have zero volume and every swing trigger is volume-gated. Added four price-only triggers on index underlyings: ATR-range expansion breakout (range >= 1.2x prior ATR and close above the prior 20-bar high), opening-range break (first 3 bars of session, first break per day), EMA 9/21 cross-up, RSI thrust (cross up through 60 after dipping under 45). Short = reciprocal-price mirror (put proxy), each direction its own tag; ATR trail 2/3/4.5/6 with an initial stop on every trade; intervals 5m/15m/1h/4h (1h resample, 4+3 bars per day) and 1d.
- Fit: no volume dependence, so cells can trade on ^NSEI/^NSEBANK/^BSESN; every trade has a stop (no-trade-without-SL). Still an underlying-move proxy, not option premium P&L; 0.8% cost is harsh for index moves so 0.1% is also printed. ORB cannot fire on 1d by design.
- Result: harness and 6 unit tests only (zero-volume data fires all triggers, no look-ahead via prefix-stability test, 4h resample correct); real-data PFnet owed from the workflow run.
- Surprise: none yet; expect many more trades than the volume-gated set, so n>=30 pooled cells should exist, and the earlier finding that wider ATR wins may repeat.
- Reuse: when a data field is structurally zero (index volume), check every gate for that field before concluding a strategy has no edge; test no-look-ahead by comparing signals on a truncated prefix.
- Profit-booking / exit takeaway: the underlying trail is only a proxy for the option premium trail; judge a trigger by OOS pooled cells and treat any PFnet as an upper bound on weekly-option booking.
## B-864 verdict: osc__div_class kb_oscrsi/kb_oscmacdh 2.43 was a data-glitch artifact (2026-10-12 IST)
- Mechanism of the discrepancy: not a code change (elder_batch3_research.py has one commit, e50d4ea, before both runs), not a universe change (symbols_fetched 14381 vs 14392 across families, same 16128 slots), not nondeterminism in the signals (n 10655 vs 10676, win 38.20 vs 38.24, avg hold 24.84 vs 24.83, exit mix within 0.5%). The tell is avg_net_ret_pct: -0.213 vs +7.337 with essentially the same trades. PFnet = win_sum/loss_sum of net returns, so 7.55 pct-points x 10676 trades = ~806 return-units (about +80,600%) came from the ~21 extra trades, i.e. one (or very few) trade(s) with a ~+800x return. Run 1: loss_sum ~540, win_sum ~517 (PFnet 0.958); run 2: loss_sum ~546, win_sum ~1330 (2.433). Same artifact in kb_oscmacdh (avg ret -0.238 vs +7.199, 0.954 vs 2.398), and in other long cells (chan pivot_tl_break 0.995 -> 1.35, osc reversal rsi 0.883 -> 1.784).
- Mirror evidence: the SHORT mirrors of the same cells fell (osc div_class short kb_oscrsi 0.582 -> 0.243, chan sigma_squeeze short 0.58 -> 0.25, tri_descending short 0.78 -> 0.31): a short that rides the same corrupt price series books a huge LOSS (short loss is unbounded), so loss_sum jumped. A real edge cannot raise longs and crater shorts by the same bar.
- Root cause: a corrupt/unadjusted yfinance bar (entry Open or later Close ~1/800 or 800x neighbours) present in the second fetch only (yfinance data drift between runs). sim2 had no sanity guard (only px > 0), and the aggregate is a sum of returns, so one trade dominates. The first-run 0.958 / 0.954 (below the 1.1 floor) is the credible number; these cells are NOT viable. The raw per-trade data is not stored, so the exact symbol could not be named offline (no yfinance access from the agent sandbox): owed on the next real run, log the top-5 trades per tag.
- Fix: scripts/elder_batch3_research.py sim2 now drops any trade whose entry bar or any bar in the hold window has Open or Close outside [0.5x, 2x] of the prior Close (bad_bar_mask), tested in tests/test_elder_batch3_research.py. Note er.simulate (elder_indicators_research.py, used by the sizing family and older harnesses) has no such guard either: owed.
- Reuse: for any sum-of-returns metric, always report a trimmed PFnet (drop top-N winners) and the max single-trade return next to it; avg_net_ret_pct far above (win% x typical win - loss%) is a tell. A PFnet jump with unchanged n and win% is an outlier, never an edge. Registered rerun tags `_rn38211452647` for these cells should be read as artifact-contaminated.
- Profit-booking / exit takeaway: the "hold to 30-bar timeout" profit claim for these cells rested on one corrupt print; with it removed PFnet is 0.95 (below 1.1), so there is no evidence yet that holding to timeout beats stops for the divergence class. Do not size or wire on an untrimmed PFnet.

## B-865 F&O candle feed: why strike scans stay empty after a restart (code audit, 2026-10-12 IST)
- Mechanism: option-strike strategies read only completed 5m bars built from Kotak websocket ticks (kotak_fo_candle_feed), persisted to fo_option_candles, mirrored per IST day to Upstash and restored on startup. The scan needs 30 bars per strike, so after any restart there is a resolve (up to 10 min) plus 2.5h of live bars unless history is restored.
- Fit: Kotak has no option history, so this journal is the only data source; with 0.8% costs and no-trade-without-SL, a missed 3h of signals is pure lost opportunity, not a safety gain.
- Result: no backtest; code audit found 4 real bugs (restore order and commit granularity inside a 15s budget, no universe refresh while connected, 4h cache of an index-less universe, stale connected=True) fixed with tests, plus unverified hypotheses (TOTP/session conflict between feeds, nse_fo/bse_fo token collisions, Upstash size, event-loop blocking by per-tick sqlite and boundary commits) now covered by diagnostics only.
- Surprise: the 4h refresh and expiry-roll logic existed and was tested but sat at the top of a loop a healthy socket never re-enters; "tested function" was not "reachable path".
- Reuse: for any restart-sensitive data path, check (a) restore order vs the startup time budget, (b) whether periodic refresh logic is reachable while the connection is healthy, (c) whether a partial cached result can pin a degraded state for hours.
- Profit-booking / exit takeaway: option exits depend on the same candle stream; a dead or stale feed also blinds the trailing-SL logic's signal side, so the Kotak-resting premium trail must stay the real exit and never rely on feed-derived candles.

## B-320 single-strike option entry: SL-or-unwind (audit, 2026-10-12 IST)
- Mechanism: real long CE/PE buy on a viable setup, trailing premium SL placed with the entry, ticked every 30s against Kotak positions and order book.
- Fit: weekly options live at most about 5 days, so a trailing SL is the only sensible exit; the no-trade-without-SL rule means a failed SL placement must end in an exit, not a grace period.
- Result: no backtest (entries reuse viable setups); code audit found the whole path present except an immediate unwind when the first SL placement fails (previously up to 180s naked). Fixed with tests.
- Surprise: the "fresh_entry_awaiting_position" state (fill not yet in Kotak positions) is a residual naked window that cannot be closed from the app side.
- Reuse: any new entry path should treat "SL placement failed" as an exit trigger at the call site, and a restart-wipe test for its table.
- Profit-booking / exit takeaway: the premium trail is the only exit, so SL placement success is what protects booked profit; losing it for even minutes on a decaying option risks the whole premium.
## B-868 (2026-10-12): "available vs need" on every blocked signal
- Mechanism: a blocked or not-ready signal now states the money gap (Kotak Net available vs 1 unit/contract/lot notional) next to its blocker, so "insufficient_capital" vs "budget_too_small" vs a real strategy block can be told apart at a glance.
- Fit: Kotak limits() Net is the only truth for available cash (Kotak-wins rule); need comes from the same notional the sizing code uses, not a second formula. Option need is 1 lot x lot size x premium, the minimum order that could be placed.
- Result: display feature, no backtest. Surprise: two of the three sizing sites reported only available, never need, so the gap could not be shown until `need_inr` was recorded at the source.
- Reuse: record the number the decision used on the result dict at the decision site; keep account figures off diagnostic endpoints that are documented as account-free.
- Profit-booking / exit takeaway: knowing the exact shortfall shows when cash, not the strategy, is blocking entries, and frees capital decisions (book profit sooner to fund a qualified setup) to be made on facts.
## B-831 / B-833 (2026-10-12): O'Neil extension cells under strict FIFO + IS/OOS
- Mechanism: re-run the O'Neil extension cells >= 1.1 (1d pivot x tightness pr1/pr1d5/pr2, leaders firsthigh, pivot exit xmsix125, 1w short shakeout plus3 pm2 h8) by simulating the trade each signal bar would open alone, then keeping only trades whose signal bar follows the previous kept exit (one position per symbol per cell), split in/out of sample by entry bar.
- Fit: the n=50,615 cells re-entered on every qualifying bar; an unchecked overlap or one regime can fake a PFnet above 1.1 that costs real money once wired. The harness reuses the unchanged detectors and exit engine so the only variable is the filter and the split; adds top-5 trades and PFnet ex top-5 as a bad-bar guard.
- Result: harness and tests only; results owed (dispatch recorded on B-831/B-833). Surprise: building it showed simulate_x already skips overlapping signals, but its convention (next signal bar must be after the exit bar) is one bar stricter than the macddiv FIFO (entry after exit), so the independent filter was aligned to simulate_x to be comparable instead of mixing conventions.
- Reuse: always state the overlap convention, and print raw vs kept counts; check a cell's lead over its IS/OOS halves and its ex-top-5 PFnet before believing a thin edge that sits on a few long-hold survivors.
- Profit-booking / exit takeaway: these cells earn on rare long-hold survivors, so a PFnet that collapses ex top-5 or in OOS means booking profit earlier would not rescue it; do not wire until the nonovl OOS number holds above the floor.

## Elder Directional System remainder: DI13, smoothing, trailing stop, candle sweep (B-588 harness, not yet run, 2026-10-12 IST)
- Mechanism: Wilder +DI/-DI/ADX with Elder's 13-period setting; buy when +DI crosses above -DI (short mirror), optionally only while ADX rises (trend building), stand aside in a "dull" market (ADX below both DIs), exit on opposite cross or when ADX above both DIs turns down (overheat).
- Fit: swing-style, ATR stop on every trade so SL-on-every-trade holds. Audit of the 1d runs found the earlier dirsys cells used period 14 (er.adx_di default), so Elder's actual 13 was never tested, smoothing type was never swept, and only fixed stops were used. Best 1d results were weak (long best 0.80, short 0.47-0.58, all below 1.1) and n of 100k from overlapping per-symbol signals is weak evidence.
- Result: no new PFnet yet. Harness `dirsys13` (192 tags per candle size: n 13/8/21, Wilder vs EMA, fixed vs trailing stop, ATR 1.5/2/3, both directions, 4 variants) plus bad-bar guard, 30% OOS split, and 4h from 1h resample. Dispatch 1d, 1h, 15m, 5m, 4h, 1m one at a time after merge.
- Surprise: a "tested" family can silently differ from the book's definition through a helper default (14 vs 13); and the shared simulator lacked the bad-bar guard the batch3 harness got after B-864, so older daily cells are unguarded.
- Reuse: read the helper's default parameters before calling a run "the book's indicator"; log period and smoothing in the tag; emit OOS and dropped-bad-bar counts with every cell; expect the cross to be late on intraday bars, where 0.8% cost likely dominates.
- Profit-booking / exit takeaway: DI crosses lag, so the opposite-cross exit gives back much of the move; the trailing-stop (BE at +1 ATR, lock 50%) cells test whether booking earlier beats waiting for the cross, and the ts0 vs ts1 PFnet gap per cell is the answer to read first.

## B-841/B-851 research universe pinning (2026-10-12 IST)
- Mechanism: yfinance fetch flakiness changes which symbols a full-universe run actually uses (7049 vs 7059); on huge-n cells one extra symbol moved PFnet 0.648 -> 0.412. scripts/universe_pin.py records every shard's fetched symbols, merges them into `fetched_symbols`, and a rerun with --pin-file / PIN_FILE iterates exactly that set, aborting if more than 0.2% of pinned symbols fail to fetch.
- Fit: the viability line (PFnet 1.1) is narrow enough that universe drift alone can cross it; a comparison between runs is only evidence about logic when the universe is identical.
- Result: tooling, no new strategy tag. Unit test with a simulated flaky fetch shows identical symbol set and sums on a pinned rerun. A real pinned rerun is still owed before closing the rows.
- Surprise: pinning the symbol set does not pin bar content (B-864: a corrupt print appeared in one fetch only), so pair it with trimmed PFnet and max single-trade checks.
- Reuse: any new research script should call select_universe/shard_meta/merge_fetched and publish fetched_symbols in its merged JSON.
- Profit-booking / exit takeaway: do not promote or demote a strategy on a PFnet gap between two runs unless the universe was pinned; otherwise a 0.2 swing may be noise that wrongly opens or closes real-money entry or a profit-booking rule.

## B-841/B-851 research universe pinning (2026-10-12 IST)
- Mechanism: yfinance fetch flakiness changes which symbols a full-universe run actually uses (7049 vs 7059); on huge-n cells one extra symbol moved PFnet 0.648 -> 0.412. scripts/universe_pin.py records every shard's fetched symbols, merges them into `fetched_symbols`, and a rerun with --pin-file / PIN_FILE iterates exactly that set, aborting if more than 0.2% of pinned symbols fail to fetch.
- Fit: the viability line (PFnet 1.1) is narrow enough that universe drift alone can cross it; a comparison between runs is only evidence about logic when the universe is identical.
- Result: tooling, no new strategy tag. Unit test with a simulated flaky fetch shows identical symbol set and sums on a pinned rerun. A real pinned rerun is still owed before closing the rows.
- Surprise: pinning the symbol set does not pin bar content (B-864: a corrupt print appeared in one fetch only), so pair it with trimmed PFnet and max single-trade checks.
- Reuse: any new research script should call select_universe/shard_meta/merge_fetched and publish fetched_symbols in its merged JSON.
- Profit-booking / exit takeaway: do not promote or demote a strategy on a PFnet gap between two runs unless the universe was pinned; otherwise a 0.2 swing may be noise that wrongly opens or closes real-money entry or a profit-booking rule.

## B-842 minimum reward:risk exit on the other swing entries (built 2026-10-12 IST, results pending)

Mechanism: brk20_min_rr (gate: room to the prior 60-bar extreme >= rr x risk) was the best B-797 cell, short atr3_rr4 PFnet 2.468 (n275), long 1.762. B-842 asks whether the same overlay lifts gap_and_go, minervini_vcp, order_block, volume_profile, and whether a resting target (rr x risk) beside the stop works as well as the gate.
Fit to this system: the live swing engine is long only and Kotak cash shorts are MIS (forced same-day square-off), so a multi-day swing short cannot be carried in cash equity; it needs stock futures (NRML) or SLB, neither with a real order path. The long side is easy: a resting SELL limit via `place_real_target` next to the SL, with cancel-on-fill. The 0.8% cost model punishes low-rr targets, so expect small-rr targets to lose to the gate.
Method notes: real main.py functions confirm every signal behind a necessary-condition prefilter; order_block and volume_profile have no native short, so their short is a reciprocal-price mirror (say so when reporting); one ATR stop replaces each entry's native stop so only the exit overlay differs; strict non-overlap, the bad-bar guard (B-864) and PFnet ex-top5 are built in because earlier brk20 and kb_oscrsi lessons showed a few outliers can carry a cell.
Result: pending dispatch (swing-min-rr-research.yml). Fill in tags/PFnet/n here when the run lands, failures included.
Reuse next time: build the overlay as cells on a shared entry signal so only the exit differs; check live instrument feasibility (product type, overnight carry) BEFORE chasing a short-side number.
Profit-booking / exit takeaway: a resting target only helps if the winners that reach rr x risk are not the trades that would otherwise run to the 30-bar timeout (B-797 showed timeout survivors carry the PFnet); compare target cells against base on ex-top5 PFnet and hold time before changing any live exit.

## B-45 gap-and-go is swing-only; guard and B-798 status (2026-10-12 IST)
- Mechanism: gap_and_go PFnet 1.65 (52 symbols; 1.31-1.47 full universe) comes from 1d bars with up to 30-day holds, driven by max-hold survivors.
- Fit to this system: an intraday BUY engine with a 15:15 flatten cannot reproduce that hold, so the number must not transfer. Registry already keeps gap_and_go in SWING only; tests/test_gap_and_go_not_buy_category.py now enforces it.
- Result: no new backtest. The true-intraday 5m same-day variant (intraday-gap-and-go-research.yml) has no registered result; if run, it is a new tag judged on its own PFnet.
- Surprise: the guard existed only as a docstring, so a registry edit could have silently broken it.
- Reuse: when a metric was measured at one holding horizon, encode the category restriction as a test, not prose.
- B-798 status: brk20_min_rr ports, replay and IS/OOS harness are in place; live wiring waits on the OOS run (n>=30) and the user's go-ahead, because the earlier overlay collapse (IS 1.9-5.0 to OOS 0.22-0.56) shows pooled cells can be fitted.
- Profit-booking / exit takeaway: never book or size an intraday trade off a swing hold-time PFnet; the 30-day survivors, not the stops, earned gap_and_go's edge, so an intraday exit would cut exactly the profit source.
## Stop-% cap and gross PFnet measurement, 2026-10-12, B-775/B-804
- Mechanism: viability questions (PFnet>=1.1, hold<=5d, planned SL<=2%) are derived at read time from stored raw metrics; the registry only holds the ATR multiple, so stop-% = ATR multiple x universe median ATR%/close at the tag's candle size (`scripts/measure_stop_pct.py`, workflow `measure-stop-pct.yml`, read by `scripts/count_sl_cap.py`). `pattern_lab.py` now also emits `pfgross` and per-cell `median_stop_pct`.
- Fit: no new strategy, no live path touched. The universe-median figure is a planned distance, not per-trade; labelled so in `stop_pct_basis.json`. `atrnone` tags have no stop and stay UNKNOWN (and may only be wired where the live path always attaches a stop).
- Result: DONE-PENDING-RUN (Actions only). Before the run the count with SL<=2% is unknown (0 of 154 measurable).
- Surprise/reuse: every research script should emit gross PFnet and stop-% from day one; back-filling later needs a full re-run. A 2% stop on a 5m/15m tag is a wide stop only for large-ATR names, so expect the cap to bind on daily and hourly tags, not intraday ones.
- Profit-booking / exit takeaway: a tight planned stop shrinks loss per trade but lifts stop-out frequency; judge the cap on PFnet of the capped cells (slcap2 re-run only if the measured count is thin), never on stop width alone.
## Execute-every-signal shadow log completion and dated-ledger run inputs (B-547, B-743, 2026-10-12 IST)
- Mechanism: B-547 (Douglas) completes the shadow log with `taken` hooks at the three successful real-entry sites (long, short, swing) beside the existing hard-gate skip hooks, plus `scripts/shadow_log_report.py` that splits taken vs hard-gate skips vs discretionary skips per (tag, direction) and reports PFnet of each when outcomes are supplied. B-743 (Vince/Elder) now has a dispatchable `interval`/`period` input pair on portfolio-overlay-research.yml (1d/5y default, 1h/2y, 15m/60d) so the marked-ledger run can cover the multi-candle rule.
- Fit: every skip in the real-entry path today is a hard gate (PFnet floor, switch, cutoff), so the "execute every signal" guard maps to hard gates by construction; any discretionary skip would show as `hard_gate=0` and be flagged. Observation only, never changes an order, no new kill switch. Cost model unchanged (0.8% round trip).
- Result: no run yet. Skipped-vs-taken PFnet needs live shadow rows (Upstash mirror) joined to Kotak trade-book outcomes; marked-ledger PFnet needs the Actions run (1d, 1h, 15m). Failures will be registered like any other result.
- Surprised: the PFnet-floor hooks existed but without `taken` rows the log could not compute a taken rate, so the report was impossible until these hooks landed. Daily-bar constants change meaning at 1h/15m.
- Reuse: shadow-log a taken row at every confirmed-entry site of any new engine; add input-driven interval to harnesses instead of cloning workflows.
- Profit-booking / exit takeaway: skipping a signal by feel is the leak Douglas names; the report quantifies it. For exits, the worst-first and margin-call primitives only ever close losers, so profit-taking is left to each strategy's own trail; compare liquidation-on vs off on ex-top5 PFnet before wiring.
## B-779 viable table: live-wired vs research-only labelling (built 2026-10-12 IST)
- Mechanism: /strategy-scan-activity rows now carry `status` (`live_wired` / `research_only`), `n_trades`, `win_rate_pct`, and the payload carries `counts` (viable_total, live_wired, research_only), all derived at read time from the registry. trade-view shows a Status column, an All / Live-wired / Research-only filter and a summary line.
- Fit: viability is derived from stored raw metrics, never a stored flag, so a changed floor re-labels every row with no re-run. Research-only tags are absent from `_STRATEGY_TAG_TO_REGISTRY_NAME`, so `_is_strategy_viable_for_real_money` stays False for them: display only, gate untouched, no new kill switch.
- Result: display change, no new strategy tag. Test asserts counts add up, status matches scan_wired, and every research-only tag is refused by the real-money gate. Part (b) of B-779 (replay top picks of docs/WIRING_PLAN_RESEARCH_VIABLES.md through main.py) is still owed on Actions.
- Surprise: "not wired" read as a defect to the user; the honest label is "research-only, cannot place orders". The viable list is mostly (about 310 vs 94) backtest-only evidence.
- Reuse: label evidence tier on any dashboard that mixes backtest and live-capable rows; read WIRING_PLAN exclusions (hold>30d, atrnone, n<300) before picking which research viable to wire.
- Profit-booking / exit takeaway: a research-only viable has no live exit or profit-booking path at all; wiring one must bring an always-attached stop and its backtest exit rule, and the main.py replay PFnet, not the research PFnet, decides whether it earns money.

## B-869 index-option trigger cells registered research-only (2026-10-12 IST)
- Mechanism: index (^NSEI, ^NSEBANK, ^BSESN) triggers from the equity library, executed as long call (long signal) or long put (short signal) on an option-premium proxy, ATR trail stop, 30-bar max hold, 5 candle sizes, IS 70% / OOS 30% split, costs 0.8% and 0.1%. Run 38218867644; 79 of 360 cells have pooled n>=30 and OOS n>=30 and are registered as `strategy_registry_idxopt.py` tags (OPTIONS category, entry_fn=None).
- Fit: NSE/Kotak option premiums carry the 0.8% cost model on a small base, and any live path needs a trailing premium SL on every single-strike option (2026-10-08) and an always-attached SL/SLM (2026-10-11); there is no real option order path today (B-320).
- Result: headline Metrics are OOS at 0.8% cost; 0 of 79 clear the floor (best OOS PFnet 0.77, rsi__thrust__long__1d__atr2d0). At 0.1% cost 10 pass, all 5m/1h shorts whose all-sample 0.8% PFnet is 0.01-0.3, so cost-driven, not edge. IS often looked good (e.g. atr_range long 1d IS 1.38 vs OOS 0.31).
- Surprise: IS-to-OOS collapse is the norm; judging on pooled all-sample would have flagged false positives. Many intraday cells had n=0 (no volume on index data for volume-gated triggers).
- Reuse: register on OOS with IS and gross kept in evidence; check cost sensitivity before reading any thin-edge result; viability is derived at read time.
- Profit-booking / exit takeaway: option-premium costs (0.8%) erase thin index edges; only fat 1d moves survive, so an option trade should book quickly on a trailing premium stop rather than carry toward the 30-bar timeout.
## Research-lab gross PFnet emission and 4h resample helper (built 2026-10-12 IST, B-804/B-870)
- Mechanism: mcx_strategy_sweep and combo_lab now print `pfgross` (PFnet with the 0.8% round-trip cost added back per trade) and `median_stop_pct` (median planned ATR stop as % of entry), as pattern_lab does; `scripts/resample_4h.py` builds NSE session-anchored 4h bars from 1h (09:15-13:15 and 13:15-15:30, two per day, never across days). pattern_lab accepts TF=4h.
- Fit here: gross vs net separates edge that is real before costs from edge that the 0.8% cost model erases; the stop-% shows whether the "no trade without SL" rule can be met at a sensible distance. Clock-hour resampling (pandas "4h") would mis-split the NSE session, so the helper anchors on the open.
- Result: tooling only, no new PFnet. Tests cover bucket times, OHLCV aggregation, tz-naive input, pfgross>pfnet, stop recording. Full re-runs on Actions still owed.
- Surprise/reuse: mcx_strategy_sweep ran its whole sweep at import time, so it could not be tested; wrap research scripts in main_run() so metrics code is unit-testable. 4h bar counts mean different hours (average 3.5 h), so state hours held.
- Profit-booking / exit takeaway: gross-vs-net PFnet tells whether a thin edge is a cost problem (fix by holding longer or fewer, larger-move trades) rather than a signal problem; compare 4h and 1h cells by hours held before judging an exit.
## Reproducibility, pinned universes and the intraday gap-and-go port (B-841/B-851/B-864/B-45, 2026-10-12 IST)
- Mechanism: a research cell is only comparable across runs if the symbol SET and the bar data are the same. yfinance flakiness changes the fetched set (7049 vs 7059), and one extra symbol moved a huge-n cell 0.648 -> 0.412; a single glitch bar (about a +800x trade) turned a 0.958 cell into 2.433. Fixes are mechanical: pin the fetched-symbol list (scripts/universe_pin.py, `pin_run_id` input + .github/actions/resolve-pin), fail loudly when pinned symbols do not fetch, compare two merged results with scripts/pin_compare.py (workflow universe-pin-compare.yml), and report trimmed PFnet and top-5 trades beside every pooled PFnet.
- Fit for THIS system: the 0.8% cost model and the 1.1 floor make thin edges (most cells) sit within the noise of universe drift, so a number that moves 0.2 with one symbol is not evidence. A cell is credible only if pooled, trim1 and OOS all clear 1.1 on a pinned, full-universe run. Pinning fixes the symbol set only; bar content can still differ, so IDENTICAL is a stricter test than we may get, and a DIFFERENT verdict with equal symbol sets is itself the finding (data drift).
- Intraday gap-and-go port: the 2026-09-16 harness was a 52-symbol, 5m, long-only inline script, which breaks four standing rules (full universe, both directions, ATR and candle sweep). It is now scripts/intraday_gap_and_go_research.py: 8 shards, long and gap-down short mirror, ATR 1.5/2/2.5/3, 5m and 15m (1h/4h not applicable to a 30-minute opening drive, flagged), own tags `gap_and_go_intraday__gap_hold__...` that never inherit the swing 1.65. Short costs use sell-side on entry and buy-side on exit with no delivery DP charge; the long keeps the original (conservative) model.
- Result: no new numbers yet; all four items are dispatch-ready with tests (tests/test_pin_dispatch_ready.py). Expected, not assumed: batch3 osc cleaned PFnet near 0.95 (below the floor), intraday gap-and-go thin after 0.8% costs with a mandatory same-day flat.
- Surprise/break: the actual drifting script (Douglas) was never pin-wired although the pin helper existed; "helper built" was not "fixed". Verify the script that produced the drift is the one wired, not a sibling.
- Reuse: every new sharded research script takes `up.select_universe` before sharding and emits `fetched_symbols` at merge; every merge prints trim1 and top5; IS/OOS via a dated split_date chosen before the run; research workflows expose a JSON `families` input so reruns of two families are 8 jobs, not 24.
- Profit-booking / exit takeaway: a same-day gap-and-go has no overnight exit, so booking profit is the 2R target or the 15:20 square-off; the held-to-timeout trades carried the swing version's edge, so expect the intraday version to lose most of it, and judge it on trimmed PFnet after the 0.8% cost, not on one fat winner.


## Elder Directional System DI13 at 1d (B-588, run 38238064228, 2026-10-12 IST)
Mechanism: Elder's DI+/DI- crossover with an ADX regime gate (cross_noadx, cross_dullgate variants), 192 tags across ATR 1.5/2/3, DI period 8/13/21, both directions, full universe (2363 fetched). Result: nothing clears the 1.1 floor; the best pooled cell is cross_noadx long atr3_n21 PFnet 0.807 on n=81839 (win 22.9%, hold 11.5 bars), OOS 0.644. The only OOS standout, cross_dullgate short atr3_n21_ts1, has OOS PFnet 1.355 but pooled 0.771 on n=424, so the OOS edge is not stable. Surprise: huge n with low win-rate means costs (0.8%) eat a thin trend edge; wider ATR stops (3) always beat tighter ones, i.e. these crossovers need room. Reuse: DI crossovers are a trigger, not an edge by themselves; pair with a trend/regime filter before more candle-size sweeps. Profit-booking / exit takeaway: time-stops (ts1) lifted win% to 52% on the dullgate short, so a time exit books profit faster than the trail, but the sample is too small to wire.

## O'Neil non-overlap 1d re-run (B-831, run 38242267159, 2026-10-12 IST)
Strict FIFO (one position per symbol per cell) cut raw signal trades roughly 3:1 and deflated every pooled number relative to the overlapping run. In-sample looked spectacular (tightness pr1 IS 3.84) but OOS collapsed (1.45, ex-top5 0.49): the edge sits in a handful of outlier winners (top-5 trades). Only leaders firsthigh atr3 h40 keeps OOS 1.139, and its trimmed OOS is 1.058, so it stays research-only. Pivot exit with xmsix125 (130-bar hold, 31% win) has pooled 1.74 but OOS 0.66: the long hold only paid in the IS regime. Lesson: always judge O'Neil-style breakout cells on OOS and ex-top5, never pooled. Profit-booking / exit takeaway: the 40-bar leaders exit (avg hold ~31 bars, win 46-57%) books profit about twice as fast as the 130-bar exit and held up better OOS, so prefer the shorter hold.

## Registering Elder DI13 and O'Neil non-overlap 1d tags as research-only (B-588, B-831, 2026-10-12 IST)
Mechanism: both result files were kept raw in git but not in the registry, so the leaderboard and STRATEGY_RESULTS_LOG did not show them. Registered via strategy_registry_dirsys_oneilnonovl.py (entry_fn=None): 192 Elder dirsys13 tags (all passed pooled n>=30 and OOS n>=30) and 18 O'Neil tags (each pooled, _segis and _segoos kept as its own strategy). Fit: research only, nothing wired, viability derived from PFnet at read time. Result: Elder headline is the OOS figure, so a few short cells show OOS PFnet above 1.1 (for example dullgate short atr3_n21_ts1, OOS 1.355) while their pooled PFnet is 0.77, which is exactly why the pooled number is kept in the evidence. Surprise/gotcha: the Elder file has OOS pfnet/win/n but no OOS gross or hold, so Metrics.pfgross and avg hold are pooled values, flagged in notes, and pfgross can sit below pfnet on those rows. Reuse: before treating any OOS-headline Elder cell as viable, read its pooled n and pooled PFnet in the evidence; the viable list is a screen, not a green light. Profit-booking / exit takeaway: cells with a time-stop (ts1) and the 40-bar O'Neil leaders exit book profit faster and held up better out of sample than long holds; prefer them when ranking otherwise comparable cells.
## Verification pass: B-792/B-817/B-417/B-419/B-369 (2026-10-12 IST)
- Mechanism: tests now prove the swing option leg unwinds without a stop and trails the premium up only, the swing pass drops the forming daily bar, and Kotak's BUY fill beats the app entry price in exit remarks.
- Fit: the 42 flatten survivors are chan_kalman (28) and lunar short (14), not month-effect; exit remarks and the Kotak audit only cover SELL fills, so short covers are blind until patched.
- Reuse: verify a row's count from the registry before quoting it; write the test against the real function and mock only Kotak calls.
- Profit-booking / exit takeaway: a 1% premium trail on a swing-held call will cut winners early; compare the option leg's realised P&L from the Kotak trade book with the share leg before trusting that trail.
## B-112 lunar sweep, B-786 replay inputs, B-541 monitor status (built 2026-10-12 IST, runs owed)
- Mechanism: (1) `scripts/lunar_sweep.py` + `lunar-sweep.yml` re-test the full-moon / new-moon rule with a DETERMINISTIC phase calculation (Meeus ch.49, matches 2024 published phases within minutes), as own tags `lunar__{full,new,quarter}__{long,short}__<tf>__atr<k>_hd<days>__v1`, ATR 1.5/2.5/4 x holds 1/3/5/10 trading days x 1d/4h/1h/15m/5m, full universe, stop on every trade, plus a derived pooled `pair` (long at full + short at new). The `quarter` variant is a PLACEBO control. (2) `oneil-replay.yml` gained `interval`/`period` inputs (1w or 1d) and `intraday-flatten-rerun.yml` a `period` input, so O'Neil flat-base/pivot and Chan Kalman 5m/15m can be replayed without cloning workflows. (3) B-541 rolling-20 expectancy monitor stays alert-only.
- Fit here: every stock shares the same phase dates, so pooled n (thousands) is about 60 independent events in 5y of 1d and about 4 in the 60-day 5m/15m window; the merge prints distinct phase events so the sample size is honest. The old registry shorts (15m/5m, PFnet 1.2 to 1.7) sit on that thin base and conflict with the B-112 note "long 0.89, short 0.53, fails" (n200, different holds); this sweep is the reconciliation, judged against the quarter placebo and the every-bar beta (long h20 about 1.04 to 1.16).
- Result: no numbers yet (no network in the build session). main.py has NO O'Neil or Kalman function, so B-786 "through real main.py functions" cannot be done honestly: the replays are documented ports (tests guard that main.py has none; flip the guard when a port lands). Wiring decision recorded, nothing wired before a replay clears PFnet 1.1 on a pinned full-universe run.
- Surprised/broke: a first test assumed a weekday for the 2024-02-24 full moon (a Saturday, so the signal bar is Monday); weekend phase events roll to the next bar by design. Delta-T (about 69 s) is ignored, irrelevant at bar sizes of 5m or more.
- Reuse: for any calendar/astro rule, add a placebo variant and report distinct events, not trade count; compute the astronomy deterministically in code (no ephemeris dependency); expose `interval`/`period` inputs on the existing workflow rather than cloning it.
- Profit-booking / exit takeaway: a calendar rule has no price-based exit, so the hold in trading days is the only profit-booking lever; the sweep (1/3/5/10 days) shows whether the effect pays within a day or needs the half-cycle of about 10 sessions, and a hold over one session on intraday candles is a carry (CNC) trade, never MIS. Prefer the shortest hold whose PFnet beats the placebo.
## Elder gap-fade / MACD hist_exhaust >=1.1 cells: what the stored runs can and cannot prove (B-850 / B-852, 2026-10-12 IST)
- Mechanism: gap fade (exhaust = high-volume gap, common = low-volume gap) buys a gap-down once price makes no new low for nb bars (3-5), exits on the first lower high or the ATR stop; macd hist_exhaust buys a rising histogram tick below zero. Run 38208431466 (1d, 0.8% cost) put six cells at or above 1.1: gap exhaust_fade long atr3/2/1.5 nb5 (1.252/1.234/1.223, n 4412, 3.7d, win 35%), common_fade long atr3/2 nb5 (1.122/1.10, 3.4d), macd hist_exhaust long atr3 (1.157, n 96207, 12d).
- Fit here: a 3-4 day hold with an ATR stop on every entry fits the swing engine, the no-trade-without-SL rule and faster turnover; but the edge is a small net 0.43% per trade on a 35% win rate, so the 0.8% cost is the whole story (gross PFnet 2.0 vs net 1.25). Short mirrors have gross 1.15-1.5 and die on costs (net 0.56-0.96): long-only.
- What surprised: (1) the "signals overlap so n is inflated" worry was wrong for these cells, `er.simulate` already allows one position per symbol; the true risk is instability: macd hist_exhaust long swung 0.929 -> 1.157 between two near-identical reruns (158 extra trades), which is outlier or glitch-bar behaviour (guard added later, B-864). (2) The registry kept pfgross 0.0 for the older v1 tags; completing a stored result means a new `rr1` rerun tag (never overwrite), not editing the old one. (3) Stored artifacts contain only per-tag aggregates, so OOS n, OOS PFnet and ex-top5 cannot be derived later: every harness must emit IS/OOS, trim1/trim5 and raw-vs-kept counts at run time (elder_ge11_validate does).
- Reuse: judge a cell by pooled AND OOS AND trim5 >= floor AND OOS n >= 30, and treat a >0.2 PFnet swing between reruns as disqualifying until a guarded, pinned rerun repeats it; test the long-fade-is-a-rising-market artefact with a per-symbol bull/bear (SMA200) split before trusting it; rank by PFnet per day held (this cell 1.25 over 3.7d beats OB/VP 1.03-1.06 over up to 30d) once confirmed.
- Profit-booking / exit takeaway: this edge is booked fast by the lower-high rule at about 3.7 days (95% of exits are rule_exit; the ATR stop fires on only 4% of trades, timeouts on under 1%), so the cash is made by quick rule exits and small wins, not by letting winners run; widening the stop from 1.5 to 3 ATR barely moves PFnet (1.22 -> 1.25), so keep the stop tight enough for a sensible position size and put the effort into the exit rule and cost control.

## Swing minimum reward:risk at 1d (B-842, run 38245172228, 2026-10-12 IST)
- Mechanism: the same swing entries (minervini_vcp, brk20, volume_profile) re-run with an ATR stop plus a minimum reward:risk requirement, as a gate on the entry (gate), a take-profit target (target), both (gatetarget) or neither (base), ATR 1.5/2/3, RR 1.5 to 4, long and short, 30-bar max hold, full universe (11762 symbols fetched), 0.8% cost. 268 tags, 256 with n>=30, all registered research-only.
- Fit here: all of these are multi-week holds (14 to 25 bars) with an ATR stop on every trade, so they fit the swing engine and the no-trade-without-SL rule, but no live path exists for the gate/target variants. Edge is in longs only: short cells have n<=70 and trimmed PFnet under the floor.
- Result: 17 cells keep PFnet >=1.1 after trimming the top 5 trades. Best on both measures: volume_profile_gatetarget atr3_rr4 long (n=497, 1.437 / exTop5 1.298), minervini_vcp_base atr3 (n=2146, 1.363 / 1.312), brk20_gatetarget atr3_rr4 (n=401, 1.495 / 1.219). Wider stop (atr3) beats tighter in every family. The small-n minervini_vcp_gate cells (headline 2.2 to 2.7) collapse to exTop5 0 to 0.4, so outlier-driven.
- Surprised: adding a target barely moves PFnet versus the base (minervini_vcp target atr3 rr4 1.327 vs base 1.363), and the trade win rate stays 40 to 49%, so the profit comes from max-hold survivors, not from the RR target firing (targets hit on only about 5 to 15% of trades).
- Reuse: always read pfnet_ex_top5 first; compare gate cells against the live OB/VP and brk20 variants on PFnet per day held before any wiring; 1h (730d) and 4h sweeps are still owed per the candle-size rule.
- Profit-booking / exit takeaway: the RR target rarely fires and does not beat base; profit is booked by the 30-bar max hold and the stop does the damage control, so a faster exit only helps if it keeps the winners that run to timeout.
## macddiv 1h IS/OOS + strict-FIFO sweep, long and short (B-814, run 38218870434, 2026-10-12 IST)
- Mechanism: MACD line/histogram regular divergence (variants line_any, hist_any, hist_zero; pivot half-width 3 and 5; ATR stop 1.5/2/3; max-hold), 1h, both directions, one position per symbol per cell, 2488 symbols, 0.8% cost. Each cell gets pooled, in-sample (first 60% of each symbol's span by entry bar) and out-of-sample tags: 108 cells, all kept in docs/backtest_data/macddiv_oos_1h_run_38218870434.json; 104 newly registered research-only (4 pooled tags existed).
- Fit here: the divergence fires late (pivot-lagged) and holds 15-24 hourly bars, so the 0.8% cost is large against a 0.5-1% average move; the ATR stop is attached on every trade so the SL rule is satisfied, but there is no live 1h entry path.
- Result: no viable cell. Pooled >=1.1: line_any long w5 atr1d5/2/3 = 1.404/1.421/1.467 (n 64601/61967/58032), hist_any long w5 atr3 1.139 (n 93063). Their IS is 2.18/2.17/2.21 and 1.53, but OOS is 0.471/0.515/0.562/0.556 (n 25-37k), so the pooled number was the in-sample half. w3 longs and every short (pooled, IS and OOS) sit at 0.30-0.70 (short mirror registered as the bidirectional fail).
- What surprised: huge n (tens of thousands) did not protect against regime/in-sample fit; n>=30 and FIFO are necessary, not sufficient. IS 2.2 -> OOS 0.5 is the strongest overfit signature so far. Missing fields: this harness emits no ex-top5, by-year or trim1, so a decay-by-year view is not available.
- Reuse: always read the OOS tag beside the pooled tag before quoting a pooled PFnet; run OOS in the first pass of any intraday sweep; do not wire macddiv 1h. Owed: 15m/5m/1d reruns, 4h (1h resample).
- Profit-booking / exit takeaway: the in-sample profit came from max-hold survivors (about 30-35% of exits) with a wide stop; out of sample the same exit mix lost, so booking at the timeout is not a durable edge without a regime filter, and tightening the stop only raised the stop-out share.

## O'Neil shakeout short 1w non-overlap + IS/OOS (B-833, run 38245037321, 2026-10-12 IST)
- Mechanism: short mirror of the O'Neil shakeout (plus3 variant) on weekly bars, ATR stop 2 or 3, 8-bar max hold (about 8 weeks), pm2, strict FIFO one position per symbol, 1953 symbols, 0.8% cost, IS/OOS split by entry bar.
- Fit here: an ATR stop is on every trade (satisfies no-trade-without-SL), but there is no live short-swing path and an 8-week hold ties capital up; the 0.8% cost is small against the 2-8% average timeout wins.
- Result: pooled atr2 1.245 (n 885, win 51.0%, ex-top5 1.172), atr3 1.227 (n 885, ex-top5 1.157). IS 1.455/1.418 (n 528) but OOS 0.921/0.924 (n 357, ex-top5 0.814/0.818). No cell has both OOS and ex-top5 >= 1.1, so nothing is viable. Tags registered research-only, each IS/OOS segment its own tag.
- Surprised/broke: the pooled number cleared 1.1 and looked like the only short family that did, yet the later half of the sample fails; non-overlap changed n little (885 vs 883), so the fade is time-regime, not overlap. Top-5 trades add little (no trade above 100%). Missing: mirror=true reruns still owed; no per-year split.
- Reuse: always read the _segoos tag beside the pooled one; a wider stop (atr3) cut stop exits from 189 to 103 but did not rescue OOS.
- Profit-booking / exit takeaway: profit came from timeouts (79% of trades, +4.5 to +6.1% avg) while stops lost 17-24% each, so the stop is the damage, not the exit timing; booking earlier than the 8-bar timeout was not tested and the OOS decay says do not wire this short.

## Option trailing-SL peak from feed candle highs (B-320, 2026-10-12)
- Mechanism: the single-strike option trailing SL ratchets off the running premium peak. The peak used only one polled LTP per 30s tick, so a spike between polls never moved the stop. It now also uses the max high of tick-built fo_option_candles bars since entry (bars starting before entry excluded).
- Fit: weekly options move fast (max ~5 day life); a missed intrabar peak leaves the stop lower than the 10% trail intends, giving back profit. Stop only ever ratchets up, SL on every leg unchanged, 0.8% cost model unaffected.
- Result: behaviour fix, not a backtested strategy; no PFnet claimed (Kotak serves no option history, cannot replay). 3 unit tests.
- Surprised/broke: nothing; caveat that the entry bar itself is excluded so the peak may understate slightly, never overstate.
- Reuse: any trail fed by sparse polling should read the tick-built candle high, not the last tick.
- Profit-booking / exit takeaway: trail from the true intrabar premium high so a spike-and-reverse locks in gains at the intended giveback instead of the lower polled peak; live verification after deploy.

## Swing minimum reward:risk at 1h/730d (B-842, run 38249384880, 2026-10-12 IST)
- Mechanism: brk20, order_block and volume_profile swing entries with ATR stop (1.5/2/3) and a minimum reward:risk as gate, target, both or neither, long and short, 1h bars, 30-bar max hold (about 4 days), 7464 symbols, 0.8% cost, pooled over 730 days.
- Fit here: an ATR stop is on every trade (no-trade-without-SL holds) and the hold is short (about 23 hourly bars), which suits faster turnover; but no live 1h swing entry path and no live short-swing path exist, so nothing can be wired.
- Result: 162 tags registered research-only. Three cells clear 1.1 on pooled and exTop5: brk20_gate short atr3_rr4 1.702 / 1.662 (n 2267, win 48.7%), brk20_gatetarget short 1.561 / 1.536 (n 2293), brk20_gate long 1.141 / 1.101 (n 2036, win 33%). order_block and volume_profile cells mostly fall under 1.1 on exTop5.
- Surprised: the short mirror beats the long again (as at 1d) with huge n and a tiny top-5 effect, so it is not outlier-driven; but the long needs only 33% wins and sits barely over the line. Profit again comes from max-hold survivors (about 60% of short exits), while stops (about 40%) lose.
- Reuse: no IS/OOS split was run, and macddiv 1h showed pooled 1.4 collapsing to OOS 0.5; run IS/OOS (and strict FIFO) on these three before any wiring. 4h, 15m, 5m still owed.
- Profit-booking / exit takeaway: the RR gate with a wide ATR3 stop lets trades run to the 30-bar timeout where the profit is booked; adding a target (gatetarget) did not beat gate-only, so do not cut winners early with a target.

## brk20_min_rr LONG 1d atr4_rr4 wired live, B-798 (2026-10-12)
- Mechanism: close above the prior 20-bar high, taken only if the room to the prior 60-bar high is at least 4x the risk, ATR(Wilder) x 4 stop always attached, exit on close < falling EMA13 or 30-bar timeout.
- Fit here: stop is a real resting Kotak SL from the entry (no-trade-without-SL holds), it is a swing (1d) long so the swing engine owns it, hold about 88 hours-equivalent (about 11 days), shares the swing kill switch, gate is the registry PFnet.
- Result: pooled tag `brk20_min_rr__main_replay__long__1d__atr4_rr4__v1` PFnet 2.659 n=218 win 35.8%; IS 3.43 n=114, OOS 1.72 n=108 (run 38247769897); calls the real main.py functions (run 38185670883). 15m and 1h fail OOS and are not wired. 1d shorts hold OOS but there is no short-swing path, so B-871.
- Surprised: the live scan records the entry on the signal day at the close while the replay fills at the next open; the exit adapter therefore defines the fill bar as the first bar after the entry day so the timeout and rule exit line up with the replay.
- Reuse: when wiring a bar-indexed exit function that checks only the last row, replay every completed bar since the fill so a missed scan day cannot skip an equality test such as the 30-bar timeout; recover the entry price from the frozen stop and stored ATR instead of adding a column.
- Profit-booking / exit takeaway: profit comes from letting winners run to the EMA13 rule exit or the 30-bar timeout, with a wide 4 ATR stop that is never tightened; the be1 ratchet added nothing out of sample, so do not add early profit-locks to this one.

## Planned stop-% per tag, B-775 (2026-10-12)
- Mechanism: planned stop distance per tag = ATR multiple x full-universe median ATR14/close for the tag's candle size (5m 0.301%, 15m 0.574%, 1h 1.269%, 1d 4.076%); run 38247767194, 24325 tags measured, atrnone tags excluded. It is a planned, not per-trade measured, distance.
- Fit here: the no-trade-without-SL rule makes the stop a first-class property, and a 2% cap is only reachable on intraday candles (1d ATR 4% already exceeds it at 1 ATR).
- Result: of viable (PFnet>=1.1, hold<=5 days) tags, 59 pass SL<=2%, 83 are over, 48 unmeasured; passers are chan_kalman 5m/15m (48), lunar (7), macddiv 1h (2), chan_tsm 1h (1), month 15m (1), none on 1d.
- Surprised: the cheap measure answered the question without any re-run; the cap variant (slcap2 tags) is only needed if the user wants the 83 over-cap cells forced under 2%.
- Reuse: keep the stop-% sidecar with every research output so cap questions are a lookup (`scripts/count_sl_cap.py --sidecar`); raw docs/backtest_data/stop_pct_run_38247767194_*.json.
- Profit-booking / exit takeaway: a tight planned stop (<=2%) only coexists with a viable edge on the short-hold intraday mean-reversion cells; those books their profit on the rule exit within a session, so a stop cap costs nothing there but would choke the 1d trend/swing cells that need 3-4 ATR of room.

## Elder gap/MACD >=1.1 cells at 1h, B-850/B-852 (2026-10-12)
- Mechanism: re-run of the 1d gap fade (common/exhaust) and MACD histogram-exhaustion cells at 1h with trimmed-top-5, IS/OOS and bull/bear splits, floor 1.1, cost 0.8%; run 38272885846, 2488 symbols, 210 rows.
- Fit here: the 1d edge came from overnight gap mean reversion; on 1h the bars are intraday and the 0.8% cost eats it.
- Result: 0 of 210 confirmed; best all-sample PFnet 0.532 (gaps common_fade long atr3_nb5 segis), gaps long 0.481 n=49960, macd hist_exhaust long 0.449, shorts best 0.362. Both directions fail at 1h. 4h (run 38273734404) collect, 15m and 5m are owed.
- Surprised: n of 50k to 460k per cell means massive overlap, yet PFnet still sits far below 1.1, so overlap inflation is not what is making it look weak.
- Reuse: a 1d-only edge must not be assumed to carry across candle sizes; do not wire the 1d gap/MACD cells off the 1d number alone.
- Profit-booking / exit takeaway: the 1d gap fade booked profit through the multi-day fade to the prior close, which a 1h bar-count exit cannot reproduce; at 1h every cell is net-negative after cost, so no exit tweak rescues it.

## Island reversal non-overlap and IS/OOS, B-815 (2026-10-12)
- Mechanism: island reversal (gap-isolated cluster closed by an opposite gap) long and short, 1d, ATR stop every trade, 30-bar cap; run 38221645245 with strict-FIFO one position per symbol and an entry-date IS/OOS split, filters none/px20/turn1cr/gap05/liq_gap.
- Fit here: swing engine (1d), stop attached from entry, hold 7-9 days.
- Result: non-overlap leaves the long cells intact (island_none atr3 1.573, n 8829, ex-top5 1.509). OOS long: none 1.19-1.21, px20 1.18-1.19, turn1cr 1.32-1.34 (n~1760, ex-top5 1.23-1.25), gap05 0.97-1.00 (fails). All shorts fail (best OOS 0.937). 72 tags registered research-only.
- Surprised: IS beats OOS (1.79 vs 1.195) and the 2026 year drops to 0.63 (turn1cr 0.80), so the edge is fading even though OOS clears 1.1.
- Reuse: always read the by-year column before trusting a pooled PFnet; a pass on the OOS half can still hide a decaying latest year. Short mirror tested and registered, fails.
- Profit-booking / exit takeaway: most trades exit on the rule (avg 7-9 bars) not the 30-bar timeout, and the wider ATR 3 stop beats ATR 1.5 (fewer stop-outs: 208 vs 865 on gap05) so give the trade room and let the reversal rule book the profit.

## Lunar full/new moon rule 1d, B-112 (2026-10-12)
- Mechanism: buy at full moon, sell at new moon (and the short mirror, plus a quarter-moon placebo and pooled pair), deterministic Meeus phase dates, ATR stop on every trade, hold 1/3/5/10 days; run 38275906669, 1d, full NSE universe, cost 0.8%. 84 cells.
- Fit here: swing engine would host it, but there is no economic mechanism; at a 0.8% round-trip cost any calendar rule needs a large raw edge.
- Result: best cell lunar__full__long__1d__atr4d0_hd5__v1 PFnet 0.869; next 0.845 (full long atr2d5 hd5), 0.844 (new long atr4d0 hd10). Zero cells at or above 1.1. Long cells win about 25-36%; the 10-day long cells lose on stops (avg -6.6%) while max-hold trades make +3.6%, which is market beta, not a lunar effect. Shorts and pairs are lower.
- Surprised: nothing; it confirms the 2026-10-10 'fails' note on the full universe. Only 1d is done; 1h/4h/15m/5m are owed (B-872).
- Reuse: always judge calendar rules against the placebo and the every-bar beta; do not wire. Cheap to re-run at other candle sizes via the same harness.
- Profit-booking / exit takeaway: longer holds (5-10 days) beat 1-day holds (0.31 PFnet) only through drift capture, and wider ATR stops helped slightly; no exit variant lifts a no-edge entry above cost.

## Intraday Gap and Go 5m, both directions, B-45 (2026-10-12)
- Mechanism: same-day opening-drive. Gap >= 2% at the 9:15 print, close holds on the right side of the open and in the strong half of the open-to-extreme range, volume > 1.5x its 20-bar average, entry within the first 30 minutes, ATR stop (1.5/2/2.5/3) on every trade, 2R target, `gap_filled` exit, flat by 15:20 IST. Run 38277225522, 5m, 60d, full NSE universe (2636 fetched), cost 0.8%.
- Fit here: a true BUY-category intraday engine would host it; the 1.65 of the swing `gap_and_go` is a different mechanic (daily bars, 30-day hold) and is never inherited. Stop is attached from entry, so the no-trade-without-SL rule is met by construction.
- Result: LONG n~1700, win ~22.6%, PFnet 0.284 (atr3d0, trim1 0.281, gross 0.503), 0.279 (atr2d0 and atr2d5), 0.264 (atr1d5). Even gross PFnet is only about 0.5, so costs are not the whole story: the signal itself loses. Zero cells near the 1.1 floor. SHORT cells n=0, which is a harness bug and not a result (below).
- Surprised / broke: the short mirror printed n=0 for all four ATR cells. Root cause: the harness used `main._target_move_pct` (long-only, `(target-entry)/entry`) for the economic-viability check, which is negative for a below-entry short target, so every short candidate failed `<= ROUND_TRIP_COST_PCT`. The unit-test fake used `abs()`, which masked it. Fixed with `_target_move_pct_short`; test fake now uses the real signs and fails without the fix. Also: `day_stats` is shared across both directions, so `days_seen` is double counted.
- Reuse: (1) when a mirrored cell prints n=0, suspect a sign or direction bug before concluding "no signals"; days_gapped/days_entered by direction would have shown it. (2) Test fakes of main.py helpers must copy the real signs, never relax them. (3) Keep the n=0 tags registered and rerun under a new tag (B-876). (4) 15m still owed.
- Profit-booking / exit takeaway: wider stops (ATR 3) booked fewer stop-outs (500 vs 1016 at ATR 1.5) and let more trades reach eod_squareoff, giving the marginally best PFnet, but 22% win with gross PFnet 0.5 shows no exit variant rescues an entry with no edge; do not tune exits on this family until the entry shows gross PFnet above 1.

## MACD divergence non-overlap 15m, B-812 (2026-10-12)
- Mechanism: MACD divergence (hist_zero / hist_any / line_any, pivot half-width w3/w5), long and short mirror, strict FIFO one position per symbol per cell, IS/OOS split at 0.7, ATR stop on every trade, 30-bar max hold; run 38277559172, 15m, full NSE universe (2628 fetched), cost 0.8%. 108 cells (pooled + _segis + _segoos), each its own tag.
- Fit here: at 15m a 30-bar hold is about 1 day, so the stop is only about 0.57% x ATR multiple wide and the 0.8% round-trip cost eats most of any edge; FIFO still leaves 20-45k trades per cell, so the numbers are not noise.
- Result: zero cells at or above 1.1. Best pooled cell is short line_any atr3 w3 PFnet 0.432 (n 26517); best of all is a short OOS segment at 0.580 (n 6165). Long cells are lower (atr1d5 line_any long 0.269, win 16%, 27k of 38k exits are stop_loss). Contrast the 1h long cells (non-overlap line_any 1.46 before the IS/OOS collapse): the divergence rule has no edge at 15m after costs.
- Surprised: the overlapping 15m signals were never the inflated part here; the intraday edge simply is not there. Wider stops (atr3) beat tighter ones again but never reach breakeven.
- Reuse: do not wire 15m macddiv; 5m would be worse on cost. 1d non-overlap (and 5m, for completeness per the candle-size rule) still owed under B-812. Judge any divergence rule at 1h or slower where the stop clears the cost.
- Profit-booking / exit takeaway: stop_loss exits dominate (about 70% of 15m long trades) and timeouts make most of the profit, so at 15m the cost-to-stop ratio, not the exit rule, is the limiter; a wider ATR stop helps but cannot rescue a no-edge entry.

## Island reversal 1d long, live swing wiring, B-877 (2026-10-12)
- Mechanism: gap down at bar i, then the FIRST bar j within 8 bars that gaps up (Low[j] > High[j-1]) above the gap-down bar's High; signal on j's close. Wired three variants, each its own live tag (`reversal__island_{none,px20,turn1cr}__long__1d__atr1d5_within8__nonovl__v2`), each live tag IS its own strict-FIFO registry name (pooled 1.518 / 1.336 / 1.276); each variant's own held-out tag (`..__segoos__v2`: 1.194 / 1.182 / 1.319, n 3358 / 2944 / 1766) also clears the 1.1 floor (asserted in a test).
- Fit here: ATR(Wilder 14) x 1.5 stop is attached with the entry (swing engine's real SL path, no trade without SL); exit adapter replays the research order (gap-aware stop, close<EMA13 falling, 30-bar hold) by reusing `brk20_min_rr_exit_reason`, and logs `island_<reason>`. Checked LAST in `_run_swing_scan` (after OB/VP and brk20). No new kill switch (shares `is_real_swing_trading_enabled`).
- Port notes: the research fills at the next bar's open with no no-chase level, so there is no entry gate to port; live fills at the signal close (as brk20 does), a small timing difference vs the replay. `none` is a superset of `px20`, so the entry order is turn1cr, px20, none and the `none` tag only opens signals failing both filters (illiquid or sub-Rs20): its live population is therefore NOT the population its OOS number measured. The research also dropped trades touching corrupt yfinance bars (bad_bar_mask); the live port cannot see the future fill bar so it does not.
- Caveats carried from B-815: edge decays (2026 YTD PFnet 0.63 for island_none atr3, turn1cr 0.80); atr1d5 stops out about 21% of trades. Status PARTIAL: no replay that calls these main.py functions exists yet (B-30 lesson: the port is verbatim but unreplayed).
- Reuse: the scan-activity test forbids a viable registry name that is also a mapping key while mapped to another name, so the live tag must equal its registry name; assert the OOS tag clears the floor in a test; overlapping filter variants need an explicit order and an honest note on which population each tag actually trades.
- Profit-booking / exit takeaway: island cells earn through rule_exit (EMA13 turn-down) and the 30-bar cap, with stops losing; keep the wider-stop plus rule-exit design and do not tighten to book early, and watch the 2026 decay before sizing up.

## Intraday Gap and Go 5m v2, short rerun after sign fix, B-876 (2026-10-12)
- Mechanism: identical to the B-45 entry above (2% gap, hold on the right side of the open, vol 1.5x, 30-min entry window, ATR stop 1.5/2/2.5/3 on every trade, 2R target, gap_filled exit, flat 15:20 IST). Run 38280746427, 5m, 60d, full NSE universe (2636 fetched), cost 0.8%, both directions, after `_target_move_pct_short` replaced the long-only helper for shorts. 8 new `__v2` tags; the n=0 v1 tags stay registered.
- Fit here: a SHORT-category intraday engine would host the mirror, but it does not clear any floor; stop attached from entry so the no-trade-without-SL rule is met by construction.
- Result: SHORT now n=831 (atr1d5 826), win 21.2-22.2%, PFnet 0.169 (atr3d0), 0.168 (atr2d0), 0.165 (atr2d5), 0.155 (atr1d5), gross ~0.35-0.37. LONG n~1686, win ~22.7%, PFnet 0.282/0.281/0.281/0.268, gross ~0.50. Zero cells near 1.1. Shorts are roughly 0.11 PFnet worse than longs at every ATR.
- Surprised: the fix produced a plausible n (half the long count, matching fewer gap-downs), confirming the earlier n=0 was purely the sign bug. Long results reproduced v1 to within 0.003 PFnet, so the harness change did not disturb the long side.
- Reuse: the mirror is weaker than the long, so the gap-down fade is not the missing edge; do not spend more candle sizes on 5m variants (15m still owed under B-45 for the rule). Judge any further gap family on gross PFnet first (needs > 1 before costs matter).
- Profit-booking / exit takeaway: shorts again do best with the widest stop (atr3: fewer stop_hit, 176 vs 453 at atr1d5, more eod_squareoff/gap_filled) but with 21% win and gross PFnet 0.36 no exit variant lifts it; do not tune exits until entry gross PFnet exceeds 1.

## Intraday Gap and Go 15m, v1 and v2, B-45 / B-876 (2026-10-12)
- Mechanism: same rule set as the 5m entries above (2% gap, hold on the right side of the open, vol 1.5x, 30-min entry window = 2 bars at 15m, ATR stop 1.5/2/2.5/3 on every trade, 2R target, gap_filled exit). Runs 38280065474 (v1, short cells pre-fix) and 38285436608 (v2, sign fix), 15m, 60d, full NSE universe (2636 fetched), cost 0.8%. 16 tags, v1 and v2 kept separate.
- Fit here: no-trade-without-SL met by construction (ATR stop on every trade), but nothing clears the floor so nothing is wired.
- Result: LONG v1 n 1185-1186, PFnet 0.291-0.301, win 22.9-23.8%; v2 n 1190-1191, PFnet 0.290-0.305 (same within 0.004). SHORT v1 n=0 (sign bug, zeros kept); SHORT v2 n=580, win 21.4-22.2%, PFnet 0.182-0.189, gross ~0.44-0.45. All far below 1.1.
- Surprised: 15m is only marginally above 5m (long ~0.30 vs 0.28, short ~0.19 vs 0.17), so candle size does not rescue the edge; the dominant exit is data_end_forced_close (long atr3: 616 of 1191, atr1d5: 330), i.e. most trades never reach stop or target and are closed at the end of the session at roughly gross PFnet 0.55.
- Reuse: gross PFnet ~0.55 means the setup has no pre-cost edge to rescue with 0.8% costs; 1h/4h are not applicable to a 30-minute opening-drive (one bar), so the candle-size sweep for this family is complete at 5m and 15m. Do not spend more runs on gap-and-go intraday variants.
- Profit-booking / exit takeaway: widest stop (atr3) again gives the best PFnet because fewer trades are stopped out and more run to session end, while the tight stop (atr1d5) converts 610 of 1190 longs into stop-outs; no exit variant lifts gross PFnet above 1, so do not tune exits until entry gross exceeds 1.
## WIRE-NEXT batch: island gap05/segis/segoos/v1 cells + swingminrr minervini_vcp gate/base (2026-10-12 IST, B-880)
- Mechanism: island reversal 1d long (gap down, gap up above the gap-down high within 8 bars, ATR1.5 stop, EMA13/30-bar exit) with an optional 0.5 ATR gap filter; swingminrr = the real minervini_vcp signal re-stopped at 1.5 ATR, optionally gated on 60-bar room >= rr x risk, exit stop or 30-bar timeout only.
- Fit here: all daily, ATR stop always attached as the Kotak resting SL, shares the swing kill switch, sized by the existing _swing_position_size (risk-per-trade fixed, so a wide stop just cuts qty). No weekly >8% stops in this batch.
- Result: registry PFnets only (gap05 1.94 / 2.27, island v1 1.27-1.51, VCP gate rr4 2.70 n=49, rr3 2.06, rr2 1.26, base 1.16 n=2606). NOT replayed through the main.py ports.
- Surprised/broke: segis/segoos/v1/nonovl are evaluation cells of ONE live rule, so a symbol can only ever hold one of them; the first in order takes the position (kept as separate tags, not merged). VCP gate rr4 is n=49 only: thin.
- Reuse: when wiring cells of one rule, wire the rule once and keep the cell tags mapped; replay the port before trusting thin-n cells. Run a main.py-calling replay (B-30/B-877 style) next.
- Profit-booking / exit takeaway: these cells have no profit target; edge comes from stop-or-30-bar-hold survivors, so do not add early profit-taking without a swept variant.
## Short-swing path for brk20 1d shorts (B-871, 2026-10-12)
- Mechanism: 1d breakdown below the prior 20-bar low with 60-bar room >= rr x risk, BUY-stop at entry + 3/4 x ATR, exit on stop / EMA13 rule / 30-bar timeout (main.py `brk20_min_rr_*` short path), held overnight for days.
- Fit here: a naked NSE cash short cannot be carried overnight on MIS (Kotak auto square-off) and CNC needs delivery shares, so the real leg is gated behind an unconfirmed-product constant; paper runs. The backtest ignores borrow/auction/overnight-product feasibility, a real gap between PFnet and tradable PFnet. SL-on-every-trade is met by placing the BUY-stop right after the fill and unwinding by cover if it fails.
- Result: no new replay; wired cells reuse registry rows (1d short atr3/atr4 plain, PFnet 1.66-3.95, IS/OOS held in run 38247769897). Only brk20 among the 254 B1 tags had a main.py short port; weekly O'Neil, sector_rotation fade and the rest need ports first.
- Surprised: most of the "short-swing missing" tags are not blocked by the engine alone but by missing short entry/exit ports.
- Reuse: confirm instrument/product feasibility at the broker BEFORE queuing wiring for a new direction; build engines with their own tables from day one (ownership, Upstash mirror, 5-min heal).
- Profit-booking / exit takeaway: shorts use the same EMA13 rule exit and 30-bar cap as the long; the wide ATR stop (4x) did best in the replay, so do not tighten stops to book sooner.
## Island reversal short mirror (B-891, 2026-10-13)
- Mechanism: island top = gap up, up to 8 bars of isolation, then gap down below the island low; short at the reclaim close with BUY-stop at entry + 1.5 x ATR, rule exit, 30-bar cap (mirror of the long island bottom).
- Fit here: 1d cash short has the same MIS/CNC overnight problem as brk20 shorts, and research PFnet is 0.636-0.713, below the 1.1 floor, so no live wiring is justified.
- Result: port + 10 tests only (exact reciprocal mirror of the long detector); no main.py replay yet.
- Surprised: the long island edge did not mirror; shorts on NSE lag longs for rare gap patterns.
- Reuse: port the mirror anyway so the replay is cheap; do not wire until a main.py replay clears the floor.
- Profit-booking / exit takeaway: unchanged from the long island, wide stop plus rule exit; no early profit target.
## Swing scan blocked the event loop (B-892, 2026-10-13)
- Mechanism: the daily swing pass is synchronous and heavy (many strategies x 380 symbols x 2y of 1d bars); called straight from the async scheduler tick it froze the web server, so Render showed 502 and the dashboard died.
- Fit here: more swing strategies wired means a longer pass; anything heavy added to the scan lengthens the outage unless it runs off the loop.
- Result: pass moved to a worker thread with its own DB connection; local server answers in 6s instead of never.
- Surprised: tests passed (they never run the live loop); only a real server start exposes it.
- Reuse: after wiring more strategies into the scan, start the app and hit an endpoint during a pass.
- Profit-booking / exit takeaway: a frozen server also freezes SL sync and exits, so keeping the loop free protects open positions.

## chan_kalman__band__short (real main.py replay, 2026-10-13, B-914)
- Mechanism: Kalman filter on log price; short when error exceeds z*sqrtQ; stop entry+k*ATR14; exit on state revert, 40-bar hold, or forced flat at 15:15 IST.
- Fit here: intraday short, MIS-flat before 15:15 so no overnight short problem; SL attached at entry (no-trade-without-SL).
- Result: run 38390561217, full universe ~2610 symbols, cost 0.8%. ve1e-3 z2.0 cells viable (5m atr4 PFnet 1.645 win 59.6 n 1019; 5m atr2.5 1.594; 15m atr4 1.288). ve1e-4 cells all below 1.04 and z1.0 is high-n noise. Replay on real main.py matched research PFnet within ~0.05.
- Surprised: process noise ve is the lever, not the ATR stop; stops are the big loser (avg -4 to -6%) while state_exit earns +2%.
- Reuse: always drive the real main.py functions in replay; check ve before ATR.
- Profit-booking / exit takeaway: state_exit books the profit; wide stops lose most, so prefer the tighter-hold 5m cells; MIS cost model still owed (0.8% assumed).

## chan_kalman short cost sensitivity (2026-10-13, B-914)
- Mechanism/fit: same cells re-run on real main.py at 0.3% round trip instead of 0.8% (run 38394789725).
- Result: every cell clears 1.39; best wiring cell 5m ve1e-3 z2.0 atr4 goes 1.645 -> 2.234 (win 63.3, n 1021). Low-edge ve1e-4 cells turn viable only because cost fell, so they are not trusted.
- Surprised: cost swings PFnet by ~0.6 on high-turnover cells; only cells viable at BOTH costs are robust.
- Reuse: run every intraday cell at 0.8% and 0.3%; wire only cells viable at both.
- Profit-booking / exit takeaway: lower realised cost directly lifts net P&L, so prefer limit-style exits at state_exit where possible; do not rely on cost cuts to admit weak cells.

## chan_kalman band short wiring (B-915, 2026-10-13)
- Mechanism: Kalman error above z*sqrtQ on log price at 5m, short at next open, ATR x4 stop, forced flat before the exchange's 15:15 IST order cancel.
- Fit: the paper short engine already mirrors to real via the PFnet gate, so the wiring is a new entry/exit branch plus a 15:00 entry cutoff and a 15:10 flatten; the exchange cancels resting SLs at 15:15 so the bot must cover itself. Every real entry carries its SL in the same request or is unwound (`entry_sl_failed_unwind`).
- Result: replay through the real main.py functions, PFnet 1.645 at 0.8% round trip (n 1019, win 59.6%, hold 0.71h), all 24 cells 1.39-2.55 at 0.3%.
- Surprise: the two guard tests only allow viable research entries with an allowlisted `source`; new registrations must reuse it.
- Reuse: exits that are stop/state/time based need their own branch ahead of the staged-ladder code; keep the target unreachable instead of editing the shared exit chain.
- Profit-booking / exit takeaway: same-day capital turnover (0.7h hold) is the edge, so a failed flatten is the main risk; it retries every tick until 15:15.

## Lunar full/new moon short, stop-bearing re-test (2026-10-13, B-917)
- Mechanism: Murphy ch.14 lunar rule, Meeus moon phases, shorts around full/new moon; quarter moon is a placebo.
- Fit: only stop-bearing cells can go live (no trade without SL). Earlier registry PFnet 1.2-1.7 came from `atrnone` cells, so they cannot be wired.
- Result (run 38417623298, full universe, 15m/5m): best full short 15m atr4d0_hd10 PFnet 0.773 win 32.7 n 7504; new best 0.555; placebo quarter best 0.657 n 12200. Full beats placebo by 0.12 only; every cell below the stack floor (1.04).
- Surprise: placebo nearly matches the real signal, so the edge is mostly generic short/hold drift, not the moon.
- Reuse: always run a placebo and a stop-bearing cell before trusting an atrnone number.
- Profit-booking / exit takeaway: stops lose about -3% avg while max_hold exits earn about +1 to +3.8%, so the longer-hold cells look best but fail on net after stops.

## chan_kalman band long wiring (B-960, 2026-10-13)
- Mechanism: mirror of the band short: Kalman error below -z*sqrtQ on log price at 5m, long at the close, stop = close - k*ATR14, exit on state revert (err >= 0), 40-bar hold, or 15:10 IST flatten.
- Fit: buy engine, intraday; exchange cancels resting SLs at 15:15 so the bot flattens itself at 15:10; no new entries from 15:00; one chan long per symbol per IST day; an entry whose real SL cannot rest is unwound (`entry_sl_failed_unwind`); no resting target (exits are stop/state/hold/flatten).
- Result (run 38424173222, 0.8% cost, main.py port): 9 of 12 cells viable, best atr4d0 ve10d0e4 z1d0 PFnet 1.827 win 47.2 n 6149 hold 0.49h; ve1d0e4+z1d0 cells fail (0.74-0.82) and are not wired. pfgross was not in the hand-off so it is stored as NaN.
- Surprised: low-win (40-49%) cells still clear 1.3+ because state exits are short and cheap; the z2 ve10 cells have only n~440, thin.
- Reuse: cascade highest PFnet first; re-read the viable stack right before the real order so a stack change flips the next entry.
- Profit-booking / exit takeaway: sub-hour holds recycle capital fast; the unwind-on-SL-failure rule matters more than the target since no target rests.

## sector_rotation fade SHORT 1d (B-963, 2026-10-13)
- Mechanism: fade the strongest-breadth sector (>=60% up, >=5 symbols); short its top-1 by 5-day return; fixed stop entry + k x ATR14; exit at stop (gap-aware) or the close of bar H (5 or 10).
- Fit: all cells hold >=5 days, so on NSE cash they are overnight shorts: MIS squares off at 15:20 and CNC needs shares, so the real leg depends on the unconfirmed NRML check (B-912). Paper runs now; the real leg fails closed. The BUY stop is placed with the entry and the entry is unwound if it cannot rest.
- Result (class-A replay on real main.sector_rotation_fade_short_* fns, 0.8% cost, n~678): registry gap_aware PFnet 1.20-1.34, stop-fill 1.29-1.49, win 50-61%, avg hold 4-10 bars. Wider stops (atr6) win more often (60%) with lower PFnet than atr1d5 (50%).
- Surprised: stop_hit trades are 0 PFnet and timeout trades carry the profit (85% win on atr1d5_h10), the usual fade shape; the stop-fill assumption moves PFnet by ~0.15, so gap_aware is the honest number.
- Reuse: cross-sectional picks must be computed once per scan from the whole universe; live sector breadth on a smaller universe than the replay is a fidelity gap to measure.
- Profit-booking / exit takeaway: the time exit makes the money; tightening the stop only converts winners into 0-PF stop-outs.

## tasuki gap SHORT 1d, ETF universe (B-968, 2026-10-13)
- Mechanism: bearish downside tasuki gap (down bar, gap-down down bar, then an up bar that opens inside bar t-1's body and closes up but stays below bar t-2's low) -> short; stop entry + k x ATR14; exit at stop (gap-aware) or the close of the 3rd bar after the signal.
- Fit: holds 3 days = overnight short, so the real leg waits on the NRML overnight check (B-912/B-967); paper runs now. BUY stop attached with entry, unwound if it cannot be placed. Validated on ETFs only (n=81, PFnet 2.079 atr6, 1.651 atr4/atr2d5); the same rule on the NIFTY-200 equities is 0.69, so it is restricted to ETF_SYMBOLS.
- Result: registry numbers from the pattern lab (not yet a main.py-calling replay); real-money gate closed via REPLAY_OWED_TAGS until one is on file.
- Surprised: atr4 and atr2d5 give identical stats (the stop is rarely the binding exit at h3), and the best cell is the widest stop; the edge is a 3-day time exit, not the stop.
- Reuse: a pattern that works on one asset class can fail on another (ETF vs stock); wire only on the validated universe. Small n (81) is a flag, not a verdict.
- Profit-booking / exit takeaway: the 3-bar time exit books the profit; a wider stop avoids converting those winners into stop-outs.

## swingminrr brk20_gate SHORT 1h atr3_rr4 (B-969, 2026-10-13)
- Mechanism: close below the prior 20-bar low on 1h bars, taken only if the room to the prior 60-bar low is >= 4x the risk (3 x ATR stop, always attached); exit at the stop (gap-aware) or the close 30 bars later. No rule exit.
- Fit: ~30 hourly bars is 4-5 sessions, so it is an overnight short: real leg stays behind the unconfirmed NRML check (B-912/B-967), paper runs now. First 1h consumer of the swing scan, so it needed its own hourly pass, forming-bar drop and a timestamped entry_day (the 1d engine only stores a date).
- Result: registry PFnet 1.702 (n 2267, win 48.7%, exTop5 1.662, full-universe 730d research, not yet a main.py-calling replay); atr3_rr3 1.039 not wired. Real gate closed by REPLAY_OWED_TAGS until the replay is on file.
- Surprised: the exit differs from the 1d brk20_min_rr short cells (those use an EMA13 rule exit); reusing _short_swing_exit_reason would have replayed a different strategy than the one measured.
- Reuse: confirm which exit a registry row was measured with before reusing a sibling family's exit function; 1h bar constants are bars, not days.
- Profit-booking / exit takeaway: profit comes from the 30-bar survivors (~60% of exits) and stops lose, so do not tighten the stop or add a target (gatetarget did not beat gate-only).
## Month effect SHORT (September first bar), 15m (2026-10-13, B-968)
- Mechanism: short the first bar of September, hold 25 or 125 15m bars, ATR stop. Fits the short-swing engine only (overnight hold, NRML unconfirmed).
- Result: registry 15m PFnet 1.70-3.62 (n=202) comes from a single Sept-1 event (60d of 15m data); flatten re-run on the full universe 0.43-0.73. Not an edge until a multi-year 1d replay says so.
- Surprised: n=202 looked like a sample but was one market day across symbols.
- Reuse: check how many DISTINCT dates a calendar-rule backtest covers before reading PFnet.
- Profit-booking / exit takeaway: time exit after ~1 session is the whole strategy; no stop-less (atrnone) cell may go live.
### chan_shape LONG 1d and macddiv LONG 1h live wiring (B-970 / B-971, 2026-10-13)

- Mechanism: chan_shape = Chan hybrid long when close < close[30] and close > close[40], ATR14 stop, 5/10-bar time exit. macddiv = close-pivot MACD (line/hist) bullish divergence on 1h, ATR stop, 30-bar max hold.
- Fit: the registry headline tags that looked wireable (chan_shape _y2021 PFnet 2.32/3.66) are calendar-year slices of the same rule; the pooled non-overlap cells (n 42k-70k) are PFnet 0.64-0.86, so the honest wired tags are the pooled ones and they are gate-closed. macddiv is registered BUY but holds overnight, which the flat-by-15:10 BUY engine cannot carry, and swing would break category ownership.
- Result: no live trade is enabled by this work; both ports are built with ATR stop on every signal, replay workflows call the real main.py functions on the full universe.
- Surprised: a high-PFnet registry tag can name a time slice, not a tradeable rule. Check the tag suffix (_yNNNN, _vixge, _segis/_segoos) before porting.
- Reuse: port the pooled rule first, replay it, and only then read slices as regime hints. Check the product/hold horizon against the engine's flatten time before choosing an engine.
- Profit-booking / exit takeaway: both rules' profit sits in the time exit (max hold) not the stop; a wider ATR stop and the hold bar count are the levers, and 1h holds up to 30 bars cannot be booked intraday.
## brk20_min_rr 1h SHORT (B-968, 2026-10-13): the headline PFnet was an OOS slice, not the strategy
- Mechanism: 20-bar close breakdown + min reward:risk room to the 60-bar low + ATR stop always attached; exit = gap-aware stop, EMA13 rule exit, 30-bar timeout.
- Fit here: 1h bars x 30-bar hold is about 5 sessions, so every trade is overnight; the real leg is blocked by the fail-closed overnight NRML short flag (B-967) and there is no 1h swing scan driver.
- Result: registry shows 4.29 only for the `_oos` slice tag (n=108). Full period atr4_rr4 is PFnet 0.527 (n=1014, win 56%), in-sample 0.492 (n=923). All 12 full-period 1h short cells are 0.53-0.59, below the 1.1 floor. Not wired.
- Surprised: the best-PFnet-by-tag ranking mixes full-period, IS and OOS slice tags; a high number on a slice with small n and a flat full-period number is a regime artifact. Always compare the slice tag against its full-period sibling before building.
- Reuse: when ranking build candidates by PFnet, exclude `_is`/`_oos` slice tags (or require the full-period tag to clear the floor) first.
- Profit-booking / exit takeaway: here the 56% win rate with PFnet 0.5 means winners are small and stop-outs large; the edge was never in the exit, it was a quiet-regime slice.


## macddiv LONG 1h in the swing engine (B-984, 2026-10-13)
- Mechanism: close-pivot MACD-line bullish divergence on 1h (price lower low, MACD higher low), ATR stop always attached, exit at gap-aware stop or the close 30 bars after the fill bar.
- Fit: 30 hourly bars is an overnight CNC long, so the swing engine owns it (category follows the hold, not the registry label BUY). Reused the short 1h pass pattern: hourly fetch, forming-bar drop, timestamped entry_day, fill bar = first bar after entry.
- Result: wired nonovl line cells atr3 1.462, atr2 1.416, atr1d5 1.40 (n 58k-65k); hist 1.138 and slice tags (segis 2.2) not wired. Real gate closed by REPLAY_OWED_TAGS until a main.py-calling replay is on file.
- Surprised: the daily swing pass would have applied the gap_and_go exit to a 1h position by default, so it must explicitly skip 1h cells.
- Reuse: any new swing-table tag needs an explicit skip in the daily pass and its own exit adapter, or it falls into the default exit branch.
- Profit-booking / exit takeaway: money is made by the 30-bar survivors (win 25-35%, stops lose), so keep the stop wide and let the time exit book it.
## pl1d LONG 1d: STARC band fade (full universe) and gap runaway (B-983, 2026-10-13)
- Mechanism: STARC fade = buy when close < SMA6 - 2 x ATR15 (mean reversion to the short band); gap runaway = buy a >1% gap above the prior high that closes above SMA50 and above its open (continuation). Stop entry - k x ATR14 (2.5 / 4.0), exit at the gap-aware stop or the close 20 bars later.
- Fit: both are 1d swing cells with a real stop, so they fit the swing engine and the no-trade-without-SL rule; atrnone variants (higher PFnet, e.g. gap runaway 1.936) are NOT wired because they have no stop. The starc atr6 n200 tags were already live under their own tags; the atr2d5 full-universe tag is a different strategy (tighter stop, 9221 trades) and stays its own row.
- Result: registry only (pattern-lab, 0.8% cost): starc fade_full atr2d5_h20 PFnet 1.191 n 9221 win 44.1%; gap runaway atr4_h20 1.464 n 1087 win 55.7% (n200 only). Neither is replayed through main.py yet, so the real gate is closed by REPLAY_OWED_TAGS.
- Surprised: the margin of starc over the 1.1 floor is thin on 9221 trades while hold 10 (1.096) and 5 (1.042) miss it; the edge sits in 20-bar survivors, stops lose.
- Reuse: port the exact lab rule on the tail window, check which universe a registry row was measured on (full_nse vs n200_swing_watchlist) before reading n, and wire only stop-carrying cells.
- Profit-booking / exit takeaway: profit is the 20-bar time exit; do not tighten the stop or add a target (not yet swept for this port).
## swingminrr gatetarget short 1h and sector-fade extra cells (B-985, 2026-10-13): extra cells are fallbacks, not extra trades
- Mechanism: gatetarget = the brk20 gate (room to the 60-bar low >= 4 x risk) plus a resting BUY target at entry - 4 x risk; sector fade = short the top-1 5-day-return name of the strongest-breadth sector with an ATR stop and a fixed hold.
- Fit here: one row per symbol in signal_state_swing_short and first-viable-cell-wins means a sibling cell on the same signal never trades while an earlier cell is open; it only adds evidence/coverage if it owns the symbol when earlier gates close. Real leg stays behind the overnight-product flag.
- Result: gatetarget 1h short registry 1.561 (n 2293) vs gate-only 1.702, so the target did not add edge; sector cells wired from the class-A main.py replay (gap_aware) at 1.15 to 1.38, below their registry research numbers (h20 1.537 vs 1.384).
- Surprised: 40+ registry sector fade rows clear 1.1 but only the l5_n1 1d-with-stop family has a live driver; l3/n3/4h/atrnone variants need new pick parameters, a 4h driver, or a stop.
- Reuse: before wiring a registry row check the replay file for the live-fill (gap_aware) number, and check the family driver supports its params; wire siblings as ordered fallbacks, not parallel entries.
- Profit-booking / exit takeaway: profit sits in the timeout survivors; the target cell caps winners at 4R, which is why it ranks under gate-only, so keep gate-only first.
## chan_kalman SHORT 15m cells + chan_gap short_on_gap live wiring (B-980 / B-981, 2026-10-13)
- Mechanism: kalman band mean-reversion short on 15m bars (err > 2 sqrtQ, ATR stop, 40-bar hold, flat 15:10). chan_gap short: if the open print gaps above prevHigh*(1+std90) yet stays under MA20, short the 10 largest gaps at the open, ATR 1.5 stop, cover at the close.
- Fit: both are intraday (flat by 15:10), so they belong in the intraday SHORT engine and share its SL-in-request / unwind / flatten path. 15m only needed a cell-to-interval map because the short scan and the tag builder were hard-wired to 5m; the 15m frame is fetched inside the 5m tick (and again for exits), not a second scheduler.
- Result: 15m z2.0 ve10d0e4 cells clear the floor in the main.py-calling replay (1.19-1.29, n 1.2k); the z1.0 and ve1d0e4 15m cells do not (0.62-1.07) and stay unwired. chan_gap short has only the research PFnet (1.297); gate closed until scripts/chan_gap_main_replay.py output is on file.
- Surprised: the daily top-10 ranking needs the whole universe, so the replay cannot shard by symbol; shards emit per-day candidates and the merge ranks them. The live scope (NIFTY 200) is a much thinner cross-section than the research (~2,680), so expect fewer or weaker top-10 days live.
- Reuse: tag grammar fields (tf) should drive the scan interval, not a hard-coded string; for cross-sectional strategies replay in two stages (candidates, then rank).
- Profit-booking / exit takeaway: chan_gap profit is the close-out of a same-day mean reversion (stop rarely the winner); never add a target, keep the 15:10 flatten.
## chan_gap BUY-ON-GAP LONG 1d, intraday buy engine wiring (B-982, 2026-10-13)
- Mechanism: Chan Ex4.1. Open below prev low x (1 - 90d return std) but above MA20, liquid; rank the day's candidates by gap (most negative first), keep 10; ATR14 stop below the open; exit at the stop or the close.
- Fit: same-day trade (avg hold 6.25h), so it belongs to the MIS buy engine, not swing (registry labels it SWING). The cross-sectional rank needs every symbol's open, which the per-symbol round-robin scan cannot supply, so selection is built once per day in a background thread at the first completed 09:15 bar and the scan only consults it.
- Result: registry PFnet 1.364-1.445 (n 1147, 0.8% cost, research harness). Not a main.py-calling replay yet, so REPLAY_OWED_TAGS keeps real money closed; paper runs.
- Surprised: the research enters AT the open; a round-robin scan visits late and enters at a later close. Entry window is capped at 10:15 IST, and the replay models the open entry, so the live paper P&L is the check on that slippage.
- Reuse: for any rank-then-trade-top-N strategy, build the ranking out-of-band and let the scan look it up; ship the replay as shard-emit-candidates plus per-date merge, since top-N is not shardable by symbol.
- Profit-booking / exit takeaway: stop-or-close only; the wide 4 ATR stop wins on registry PFnet (1.445 vs 1.364 at 1.5 ATR), so profit comes from letting the day run to the close, not from tight stops or targets.

## Chan time-series momentum under FIFO, result (B-807 / B-991, 2026-10-13 IST)
Lesson: with strict one-position-per-symbol FIFO (run 38187474707, 240 cells, 0.8% cost) the best chan_tsm cell is long 1d atr4d0 hold25 lb120 at PFnet 1.084 (n 50077); none reach 1.1. The 1h long cells that printed 1.55 on ~220k overlapping signals do not survive. Reuse: any cell whose n is in the hundreds of thousands is a stacked-signal count, so run the FIFO check before reading its PFnet; all 240 cells stay registered with full metrics. 4h still owed (B-991).
Profit-booking / exit takeaway: the apparent edge came from stacked max-hold winners; a hold25 exit only pays if trades are independent, so judge exits on non-overlapping portfolios.
## pl1d SHORT mirrors 1d: STARC band fade up-side and gap runaway down (B-1001, 2026-10-13)
- Mechanism: short when close > SMA6 + 2 x ATR15 (fade the overextended spike) and short a >1% gap below the prior low that closes below SMA50 and below its open (downside continuation). Stop entry + k x ATR14 (2.5 / 4.0), cover at the gap-aware stop on the high or the close 20 bars later.
- Fit: 1d swing-length shorts; a 20-day hold cannot be intraday-MIS, so a live path would need a delivery-short-capable route (Kotak equity shorts are intraday only). Research-only until a replay clears the floor; the stop is attached on every trade so the no-trade-without-SL rule holds in the backtest.
- Result: pending (workflow pl1d-short-main-replay.yml not yet dispatched). Registered with real metrics whatever the outcome.
- Reuse: short mirror is its own tag (dir short), built by reflecting the long rule and exit, with the high/low swapped and gap fills at max(stop, open).
- Profit-booking / exit takeaway: unknown until run; the long cells earned on 20-bar survivors, so check whether the short side repeats that (stops lose, timeout wins) before judging.
## sector_rotation L x N x ATR sweep, 1d + 4h, both directions (B-1002, 2026-10-13, harness built, run owed)
- Mechanism: strongest-breadth sector (>=60% up, >=5 symbols); fade SHORT or momentum LONG its top-N by L-bar return; fixed ATR14 stop; exit at stop or the close of bar H. Grid: L {1,3,5} x N {1,3,5} x ATR {1.5,2.5,4,6} x hold (1d 5/10/20 bars; 4h 2/6/10 bars) x both directions, each cell its own tag.
- Fit: holds are multi-session, so shorts are overnight (NRML question B-967 still gates the real short leg) and 4h cells are 1-5 session swings; atrnone cells are refused by construction (no trade without SL). Prior evidence: n200 momentum PFnet 0.74-0.83 until wide 6-ATR stops (1.5); full-universe l5_n1 was 0.796, so a n200 number must never stand in for the full-universe one.
- Result: none yet (dispatch owed, B-1002); results must be registered pass or fail.
- Design lessons: top-N is a prefix of the sorted pick list, so one real call at N=max serves N=1/3/5 exactly (3x cheaper, tested); 4h bar-count constants change meaning (L and H are 4h bars, 2 per session); the 4h resample must be NSE session-anchored (scripts/resample_4h.py), not a clock resample; yfinance serves 1h only 730d, so 4h has ~2 years vs 5y at 1d (fewer signals, state n).
- Reuse: for any cross-sectional rotation, share the pick computation across direction and N; keep long/short mirrors as separate tags; report the three stop-fill models side by side, because gap-through-stop moves PFnet ~0.15.
- Profit-booking / exit takeaway: earlier sector-rotation evidence says the time exit carries the profit and tight stops only convert winners into 0-PF stop-outs; the sweep tests whether that holds at 4h where holds are 1-5 sessions.

## Correction: chan_kalman ve1e-4 cells (B-1040, 2026-10-13)
- Mechanism/fit: tag token ve1d0e4 = process noise 1.0e-4 (grammar drops the minus); ve10d0e4 = 1.0e-3.
- Result (run 38390561217 stored JSON, 0.8%): the earlier line 've1e-4 cells all below 1.04' is wrong for 5m z2.0: ve1d0e4 z2d0 atr4d0/2d5/1d5 = PFnet 1.408/1.378/1.346, n ~13k, win 46-49%, hold ~0.25h. Only z1.0 (0.74-0.78) and 15m (0.62-1.01) ve1d0e4 cells fail.
- Surprised: summarising a family from memory of the best cells hid viable low-ve cells; read the stored JSON.
- Reuse: when two backlog rows disagree, resolve from docs/backtest_data, never from prose. chan_gap BUY row has no main.py replay stored (B-1041): do not inherit the swing PFnet.
- Profit-booking / exit takeaway: ve1d0e4 cells are high-turnover, low-win, gross 3.7 vs net 1.4, so cost-sensitive; prefer ve10d0e4 z2d0 (1.45-1.65) when both qualify.
## swingminrr gatetarget SHORT candle-size x ATR sweep, 4h/15m/5m (B-1010, 2026-10-13, harness built, run owed)
- Mechanism: close below the prior 20-bar low with room to the prior 60-bar low >= rr x risk; stop = entry + k x ATR; resting BUY target at entry - rr x risk; else close of bar 30. Live cell is 1h atr3 rr4 (registry 1.561).
- Fit: holds of 30 bars are overnight at 4h (15 sessions), about a session at 15m and under half a session at 5m, so the intraday cells would belong to the MIS short engine, the 4h cells to the swing-short route (B-912/B-967 still gate overnight shorts). Stop on every trade, atrnone refused.
- Result: none yet; 12 cells (3 tfs x ATR 2/3/4/6) to register pass or fail after dispatch.
- Design lessons: ATR must be swept via brk20_min_rr_entry_signal directly (the gate wrapper fixes ATR 3.0); a numpy pre-filter (close < prior 20-bar low) skips ~95% of real-fn calls and is exact because it is the fn's own first condition; 5m 60d gives under a session of 60-bar room, so expect that cell to be structurally different, not just noisier.
- Reuse: when sweeping a wrapped cell, call the underlying real fn with the swept parameter and cross-check at the wrapper's own parameter; state that bar constants change wall-clock meaning per candle.
- Profit-booking / exit takeaway: the 1h cell's edge is the resting target plus stop; check at each tf whether target_hit or max_hold_timeout carries the profit before judging a tf.
- B-905 (2026-10-13): registry TradeCategory now has OPTIONS_MULTI ("options_multi", 7 members); key options stays single strike. Adding a category lifts the per-cycle check CEILING (30 -> 35) but an empty category adds no real checks; tests pinning the bound must follow len(TradeCategory). Profit-booking / exit takeaway: none yet, no multi-strike strategy registered.
- B-991 update (2026-10-13): chan_nonoverlap.py now supports INTERVAL=4h (1h fetched, NSE session-resampled, 2 bars/session, ~730d history so fewer signals than 1d; lookback/hold constants are 4h bars). Dispatch chan-nonoverlap.yml with intervals=["4h"], then register `...__4h__...__nonovl__v2`. Expect no wireable cell (1d/1h best 1.084); result still must be registered.
## chan_gap candle-size sweep, short + long, 5m/15m/1h (B-1020, 2026-10-14, harness built, run owed)
- Mechanism: same Chan gap signal (open beyond prev extreme by 90d std, still on the MA20 side), top-10 by gap per day, ATR stop; the sweep changes only the exit resolution: the day is walked in 5m/15m/1h bars, stop checked every bar, flat at the last bar ending by 15:15 IST.
- Fit: signal inputs are daily, so candle size cannot change selection, only whether intraday stop touches and the flatten bar differ from the daily-bar baseline; expect small PFnet deltas, mostly from the flatten price vs the 15:30 close. SL is on every trade by construction.
- Result: none yet (dispatch owed, B-1020). Register all 18 tags pass or fail.
- Design lessons: yfinance limits (5m/15m 60d, 1h 730d) mean n is a few percent of the 5y baseline, so judge on n and never compare PFnet to the 1d number directly; 1m (7d) and 4h are owed; nested f-string quotes are a SyntaxError on Python 3.11 CI.
- Reuse: cross-sectional daily-signal strategies replay as shard-emit-candidates then per-date merge; the same two-frame (daily signal + intraday walk) pattern fits any open-gap strategy.
- Profit-booking / exit takeaway: baseline profit is the close-out, not the stop; if finer bars show stops firing earlier turn winners into losers, that confirms keep wide stops and flatten at the close.
## Holding-period unit hygiene: bars vs hours (B-1030, 2026-10-13)
- Mechanism: a run stored avg hold as bars x 24.0 (calendar hours per 1d bar) while the registry's `avg_held_hrs` means MARKET hours (1d bar = 6.25h, 1h = 1h, 15m = 0.25h). The 10 swing-short main-replay tags showed 284.6h instead of 74.1h, which also distorts the 75h quality hold cap and any PFnet-per-time ranking.
- Reuse: always store the raw bar count (`Metrics.avg_held_bars`) next to the derived hours and compare hours only in market hours; never overwrite the raw field. Quote the run's raw unit in evidence.
- Profit-booking / exit takeaway: hold-time comparisons (faster turnover tie-break) are only valid in one unit; the swing-short cells hold ~12 sessions, not ~47 days-equivalent, so their turnover ranking improves.
## Replay fidelity: glitch-bar cleaning + entry-fill model for sector_rotation and pl1d (B-1110, 2026-10-14)
- Mechanism: not a new strategy; two gaps between research replays and live. The pl1d and sector replays read raw yfinance frames (a bad open print once made +900% trades, PFnet 6.2), and the sector replay filled at the next open while the live paper path fills at the signal close.
- Fit: shared scripts/bar_hygiene.py now cleans frames and records bars_dropped_glitch; sector sweep can run ENTRY=signal_close as separate `_ec1` tags. Gap-through-stop fill models were already reported side by side.
- Result: harness only; effect size unknown until the re-runs (owed in B-1110). Old registered tags keep their uncleaned numbers.
- Surprised: three research labs already had their own copy-pasted clean_bars while these two did not; the copies are identical, so a shared helper is the low-risk fix.
- Reuse: any new replay driver loads frames through bar_hygiene.clean_frames and reports the drop count; when live fills differ from the replay (close vs next open), add the live model as its own tag instead of editing the old one.
- Profit-booking / exit takeaway: cleaning removes fake outsized winners, so expect PFnet to fall slightly, never rise; judge the cleaned number, and size nothing off an uncleaned one.
## pl1d 1h/4h sweep + brk20 4h (B-1150 / B-1151, 2026-10-14, harnesses built, runs owed)
- Mechanism: pl1d = fade a STARC-band spike (close beyond SMA6 +/- 2 ATR15) or ride a >1% gap runaway above SMA50; brk20 = 20-bar breakout with minimum reward:risk. Both are bar-count rules, so a coarser candle changes what a window means (4h hold 10 = ~5 sessions, not 10 days).
- Fit: 4h/1h holds are 1-10 sessions (swing-length at 4h, intraday-to-swing at 1h); every cell keeps an ATR stop. Short legs at multi-session holds still hit the overnight-product question (B-912); research only until a cell clears the floor.
- Result: none yet; register all cells pass or fail.
- Surprised/design lessons: main's date-based exit functions (find first bar with DATE > entry_day) silently skip the rest of the entry day at intraday sizes, so a harness must hand them the post-entry frame and an older entry_day instead of reusing the 1d call; yfinance has no 4h, only the session-anchored 1h resample gives bars that do not span the overnight gap; 730d of 1h gives ~2 years, far fewer signals than the 5y 1d baseline (read n).
- Reuse: for any 1d-built strategy being swept intraday, grep its exit fn for date comparisons first; sweep ATR and hold in the driver off the real signal's atr_at_entry rather than adding tags to main.
- Profit-booking / exit takeaway: 1d evidence says pl1d profit sits in hold-bar closes (stops lose); if 4h stops fire earlier and lose, widen ATR before shortening hold.
## Island reversal short+long and pl1d long+short: candle-size x ATR sweeps (B-1090 / B-1091, 2026-10-14, harnesses built, runs owed)
- Mechanism: island = gap in one direction, then within 8 bars a gap back that stays beyond the first gap; enter at the completion close, ATR stop, EMA13 rule exit or 30-bar hold. pl1d = STARC band fade (close beyond SMA6 +/- 2 x ATR15) and gap runaway (open beyond prior extreme by 1%, with SMA50 and candle direction), ATR14 stop, 20-bar hold. Each is run long AND short at 4h/1h/15m/5m (island also 1d).
- Fit: 4h cells are multi-session swings (overnight; short side still gated by B-912/B-967), 15m/5m cells are intraday and would belong to the MIS engines. Stop on every trade, atrnone refused. Prior evidence: island long 1d is 1.27-1.98 but decays in 2026 and the 1d short mirror is 0.64-0.76, so a short winner would be a surprise, not an expectation.
- Result: none yet; every cell must be registered pass or fail after dispatch.
- Design lessons: (1) where a main.py fn is bound to a registered cell (pl1d), sweep a parameter by registering swept tags in the research process only, never by re-implementing; (2) day-granular exit fns (pl1d str[:10] date compare) silently break on intraday bars, so feed them bar-ordinal dates; (3) island signals do not depend on the ATR multiple, so compute detection once and derive stops with the real brk20_stop_price per k (3x cheaper, exact); (4) a numpy necessary-condition pre-filter keeps a per-bar real-fn call affordable at 5m and is safe because main still decides every signal; (5) 60-day intraday history gives few islands, so read intraday n before PFnet.
- Reuse: tools/tf_sweep_common.py style (string Date column, shard raw sums, exact merge) for any further candle sweep; cross-check a new-tf harness by reproducing an existing 1d registry tag name and number.
- Profit-booking / exit takeaway: unknown until run; island long earned on time exits, so check at each tf whether rule_exit or max_hold_timeout carries profit before tightening stops.

## Envelope 5% fade 1h ported into main.py, unwired (B-1130, 2026-10-14)
- Mechanism: close more than 5% below SMA21 (long) or above (short mirror), mean-reversion fade held 18-30 hourly bars with an ATR14 stop.
- Fit: 30 hourly bars span about 4-5 sessions, so overnight CNC swing engine, never MIS. Only stop-bearing cells are ported; the atrnone cells (best raw PFnet 1.225) can never be wired because every trade needs a stop.
- Result: none from main.py yet; research registry (n200) shows PFnet rising with wider stop and longer hold (atr6_h30 1.145, atr2d5_h30 0.943), i.e. the stop mostly hurts. Short mirror was never registered.
- Surprised: of the B-916..B-959 rows several families (pl1d starc/gap runaway, gap fade nb5, chan_shape, macddiv) were already ported; check main.py before scoping a port.
- Reuse: port the last-bar rule with a bar-by-bar parity test against the research rule function, return the stop always, own tag per direction/ATR/hold.
- Profit-booking / exit takeaway: this edge sits in the long hold (timeout survivors); tight stops convert fades into stop-outs, so judge the replay by the exit-reason split.
## Envelope fade 1h main.py replay harness (B-1160, 2026-10-14)
- Mechanism: replay of the B-1130 port on the full universe, both directions, 12 ATR x hold cells, tags carry all raw metrics.
- Fit: yfinance caps 1h at 730 days, so the full-universe sample is about 2 years; a 5-year 1h claim is impossible, state it instead of resampling.
- Result: none yet (dispatch owed).
- Surprised: a cheap exact prefilter (rule's first test as a numpy mask) cuts real-function calls by an order of magnitude without changing a single trade; keep a brute-force equality test for any prefilter.
- Reuse: copy the pl1d replay skeleton, swap the loader family for the 1h loader, route glitch cleaning through bar_hygiene, sign the PnL by direction in the trade helper.
- Profit-booking / exit takeaway: report the timeout vs stop split per cell; the research edge lived in long holds.
## O'Neil setups ported into main.py for a genuine main-calling replay (B-1070, 2026-10-14)
- Mechanism: flat-base / pivot / new-high breakout on >=1.5x volume, signal at the close, entry at the next open, ATR (or pct) stop on every trade, long and short as separate tags; main.py now holds oneil_signal_at, oneil_stop_price, oneil_trail_stop, oneil_exit_bar (additive, unwired).
- Fit: weekly/daily swing-length holds (8-26 bars) fall to the swing engine; the 0.8% cost matters less at these holds. Nothing is live: the port exists only so the replay exercises real main.py code.
- Result: none yet; v2 replay dispatch owed (1w then 1d). v1 independent-implementation results stay as the cross-check.
- Surprised: a port can be proven equal to the older independent replay by parity tests on synthetic series (long, trailing, pct, target, short mirror) before spending a full-universe run.
- Reuse: port the walk-forward array-level function first (signal_at style) and keep df wrappers thin; keep the negative-control (avg-down) out of main.py; a new main-calling run is a new tag version (v2), never an overwrite of v1.
- Profit-booking / exit takeaway: earlier O'Neil evidence says the timeout survivors carry the profit and trail stops lose; check the v2 exit-reason breakdown before judging a cell.

## Flatten failures at MIS cost, and the 15m bars-as-hours bug (B-1120 / B-1121, 2026-10-14 IST)
- Mechanism: the forced 15:15 flatten re-run priced every cell at the 0.8% flat round trip; real MIS costs are far lower (about 0.12% statutory+brokerage, 0.3% with a slippage stress), so a failed intraday cell may be a cost artifact. The re-test is a new tag per cost (`cst0d12`, `cst0d3`), never an overwrite.
- Fit here: intraday cells with an ATR stop attach to the buy/short engines; month/lunar `atrnone` cells have no stop and can never be wired (no-trade-without-SL).
- Surprise: while filling raw bar counts, 108 15m tags turned out to store bars as hours (4x too long). Holds drive the faster-turnover tie-break and the 75h quality cap, so a unit slip silently reorders rankings. Reuse: store the raw bar count next to derived hours and assert hours == bars x market_hours_per_bar(tf) in a test.
- Result: none yet (matrix built, dispatch owed). A cost-only pass is a candidate, not evidence; it still needs the real-main.py replay.
- Profit-booking / exit takeaway: cost is part of the exit decision at 5m/15m, where trades earn little per round trip; judge any intraday exit tweak at MIS cost, not the 0.8% figure.
## Replay-result hygiene tools: log-to-JSON converter and unregistered-tag report (B-1230 / B-1231, 2026-10-14)
- Mechanism: not a strategy. Two read/convert tools that keep backtest data complete: merge-job console tables become docs/backtest_data rows[].metrics with every field, and a diff of saved result tags against the registry shows what was measured but never registered.
- Fit: the thumb rule that every result is kept in full and viability is derived later needs the data to land in git un-trimmed. Hand-copying a console table is where fields (pfgross, exit breakdown, hold units) get dropped.
- Result: first run of the report found 416 unique tags in 9 saved files that are not in REGISTRY (B-1232), including two whole runs (elder_ge11 1h 210, pfoos 54).
- Design lessons: (1) keep hold units as printed (hold_h vs hold_bars) rather than converting, since bar length differs by candle size; (2) a parser for result logs must refuse a near-miss line loudly, not skip it, otherwise a format drift silently loses rows; (3) saved result files have many shapes (rows, cells, results, tag-keyed dicts), so a grammar-regex walk finds tags without per-file code; (4) the registry is ~41k names loaded from many extension modules, so always diff against the live import, not a grep.
- Reuse: run scripts/missing_registry_tags.py after every result commit; pipe merge logs through scripts/replay_table_to_json.py instead of copying tables.
- Profit-booking / exit takeaway: none directly; unregistered results are invisible to the viable leaderboard, so any viable cell hiding in them is profit not yet considered (check the 416 for PFnet >= 1.1 first).

## chan_gap short_on_gap main.py replay (2026-10-14)
Main.py-calling replay (run 38502123279) holds up: PFnet 1.314 vs research row; close exits PFnet 2.45, stop exits 0 (83 of 1157). Only atr1d5 cell emitted. Profit-booking / exit takeaway: same-day open-to-close hold (1 bar) keeps turnover maximal; the ATR stop loses every time, edge is entirely in close exits.
## Registering the unregistered replay results (B-1232, 2026-10-14 IST)
- Mechanism: a read-only diff of saved result JSONs against the registry found 416 tags "missing"; most were not lost data. 49 were naming variants the diff did not understand (`|full`/`|n200` universe suffix, `_rn<run>` rerun suffix), 10 were sizing simulations without trade metrics, and 366 were real gaps (210 elder gap-fade 1h, 54 portfolio-overlay OOS windows, 81 index-option cells, 12 thin swing min-RR cells, 9 undefined-PFnet cells).
- Why it fits: every result is kept in full so viability can be re-derived when the definition changes; a loader that skips n<30 or PFnet-undefined rows silently drops evidence. Skips belong in the viable-table filter (n>=30, hold cap), not in registration.
- Surprise: two loaders for the same family can use different headline bases (index-option OOS vs ALL-sample when OOS n<30); the basis is written in the universe field so rows are never compared across bases.
- Reuse: after any new result file, run `scripts/missing_registry_tags.py` and expect zero unexplained; extend `EXPLAINED_PREFIX` only with a stated reason.
- Profit-booking / exit takeaway: none of the 366 is a validated edge (many are thin n or in-sample windows); the pfoos oos60 and 1h gap-fade segoos tags are the ones that say whether an exit or overlay survives out of sample.
