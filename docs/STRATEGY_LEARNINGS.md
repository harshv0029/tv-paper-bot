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
- Fit: respects no-token and no-account-*** (no balances, capital or order ids). A strike needs 30 five-minute candles that only accumulate forward, so after any restart every strike sits in warming_up_need_30_candles for about 2.5 hours; combined with the 09:20 window start this can silently mean no trades for most of a session.
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
- Reuse: record the number the decision used on the result dict at the decision site; keep account figures off diagnostic endpoints that are documented as account-***.
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

## Cup 3C cheat 1h LONG ported into main.py, unwired (B-1190, 2026-10-14)
- Mechanism: Minervini cup (depth 15-35%, low in bars 15-50 of a 60-bar window, right side back to 95% of the left rim, handle range <=12%) then a tight pause at 1/3-1/2 recovery that breaks upward; ATR14 stop, 18-30 hourly bar hold.
- Fit: 30 hourly bars are overnight, so swing engine; only n about 130 on the n200 sample, so the 1.15-1.24 PFnet is thin evidence until a full-universe replay. No short mirror exists in pattern_lab, which breaks the bidirectional rule until one is built.
- Result: none from main.py yet. Registry: PFnet rises with hold (h6 0.29, h18 0.9-0.95, h30 1.15-1.24), the same long-hold pattern as the envelope fade.
- Surprised: the cheat check is nested inside the cup precondition in the research code, so a port must reproduce the nesting, not just the pause test; a parity test needs a hand-built cup because random walks never fire it (assert the synthetic fires, or the test is vacuous).
- Reuse: build a synthetic that triggers the rule, assert fires > 0, then compare every prefix to the research rule function.
- Profit-booking / exit takeaway: edge is in the hold-to-30 survivors; judge by timeout vs stop split.

## Cup 3C cheat 1h replay harness and inverted-cup short design (B-1210, 2026-10-14)
- Mechanism: replay of the B-1190 port on the full universe (long, 9 cells); the short mirror is the same rule on reciprocal prices (a dome with a tight pause below, close under the pause low), stop above entry.
- Fit: swing-length holds; 1h history is capped at 730 days so the sample is about 2 years. A mirror built on reciprocal prices keeps every percentage threshold symmetric, a sign flip would not.
- Result: none yet (dispatch owed); short rule has no PFnet.
- Surprised: the tag-independent rule can be evaluated once per candidate bar and the per-tag entry only where it fires, which cuts calls by the number of tags; an exact necessary-condition mask (close above the prior 6-bar high) is enough.
- Reuse: for any long-only research rule, the mirror is the same function on 1/price, tested by asserting short(recip(x)) equals long(x) bar by bar.
- Profit-booking / exit takeaway: the long cells earned only at hold 30; check the timeout vs stop split before judging the mirror.
## chan_shape and tasuki gap, both directions x candle size x ATR (B-1180 / B-1181, 2026-10-14, harnesses built, runs owed)
- Mechanism: chan_shape = close below its close 30 bars ago but above 40 bars ago (long), mirror short; ATR stop, hold 5/10 bars. Tasuki = three-bar gap continuation failure (downside tasuki gap -> short, upside -> long), ATR stop, 3-bar hold.
- Fit: both rules are bar-count patterns, so each candle size is a different market behaviour; holds of 3-10 bars are intraday at 5m/15m (MIS engines) and multi-session at 4h/1d (swing, overnight short gated by B-912/B-967). Stop on every trade, atrnone refused. Prior evidence: chan_shape 1d long pooled 0.64-0.86 (below floor), tasuki short 2.08 on ETFs but 0.69 on NIFTY-200 equities, so the full-universe cell is the decisive one.
- Result: none yet; every cell registered pass or fail after dispatch.
- Design lessons: (1) a direction main.py does not have can be run through the SAME real functions on a reciprocal-price frame (O,H,L,C -> 1/O,1/L,1/H,1/C): reciprocal is order-reversing, so gap tests, close comparisons, stop touches and gap-aware fills mirror exactly; take ATR from the original frame, map stops/fills back as 1/x. It does NOT work for indicators with smoothing (MACD, EMA-based rules), so macddiv short stays a main.py port job; (2) a swept stop multiple can reuse the signal when the signal does not depend on k; (3) keep tag spelling equal to main's own (atr4d0 for chan_shape) so a 1d cell cross-checks against the registry; (4) the same universe caveat applies to any ETF-validated rule: run etf and full as separate tags.
- Reuse: tf_sweep_common.inverted_frame for exact mirrors of gap/close-comparison rules; month-effect was skipped (one September event per year, 60d intraday cannot test it) and macddiv short needs a real main.py port.
- Profit-booking / exit takeaway: unknown until run; tasuki's edge so far came from a 3-bar time exit with a wide stop, so check at each candle size whether max_hold_timeout still carries the profit before tightening stops.
- B-1100 (2026-10-14): a test that drives a live engine core must stub every registry- or live-feed-dependent early return (chan cascade, live ticks) and restore module globals like DB_PATH, else its outcome depends on registry data or suite order. Fake-clock sweeps (time-machine) showed no time-of-day dependence. Profit-booking / exit takeaway: none; test hygiene only.
## Pre-dispatch QA of research workflows (B-1200, 2026-10-14)
- Mechanism: not a strategy; a gate before spending runner hours. Static check of every workflow plus a SYNTHETIC one-shard run and merge of each driver.
- Fit: the free tier allows one matrix running plus one queued, so a dispatch that dies on a typo or missing main.py symbol wastes a queue slot and hours.
- Result: 9 of 9 workflows pass static QA; 8 of 9 drivers smoke clean; envelope-main-replay would crash (main.ENVELOPE_1H_CELLS absent from the branch).
- Surprised: a research commit can ship a driver that imports main.py symbols from a commit that is not in the same patch; main.py needs cwd=repo root (static mount), so smoke tests symlink static/docs into a scratch dir.
- Reuse: run scripts/workflow_qa.py and tests/test_workflow_smoke_b1200.py before every matrix dispatch; extend SMOKES when a new driver lands. Job counts and runner-hour estimates live in docs/DISPATCH_ORDER_QA.md and should be replaced by measured run times.
- Profit-booking / exit takeaway: none directly; QA protects the research queue that finds profitable cells.
## pl1d LONG cells, main.py replay (B-1233, 2026-10-14)
- Mechanism: gap runaway long (open > prior high x 1.01, close > SMA50, green bar; ATR14 x4 stop, 20-bar hold) and STARC band fade long (close < SMA6 - 2 x ATR15; ATR14 x2.5 stop, 20-bar hold), 1d, swing engine.
- Fit: the stop is always attached (pl1d_stop_loss), so the no-trade-without-SL rule holds; holds up to 20 trading days sit inside the 30-day viable window; entry at the signal close, as every swing port.
- Result (run 38506928246, full universe, main.py functions, cost 0.8%): gap runaway n 12898, PFnet 1.2025 (gross 1.379), win 46.19%, hold 116.5h; starc fade n 9093, PFnet 1.2215 (gross 1.452), win 43.19%, hold 90.4h. Registered as own `_mr` tags; research tags (1.464 / 1.191) kept.
- Surprised: the main.py replay moved gap runaway down 0.26 versus the research run, starc up 0.03; both clear the 1.1 floor only thinly. All profit sits in max_hold_timeout exits (PFnet 2.29 and 8.16); every pl1d_stop_loss exit is a pure loss (PFnet 0.0, 15% and 41% of trades).
- Reuse: always compare the main.py replay to the research number before trusting the margin; for these cells test a wider stop or a stop-free-then-trail variant per the ATR and candle sweep rule.
- Profit-booking / exit takeaway: the edge is the full 20-bar hold, not early exits; do not tighten stops or book early, and the starc stop (41% of trades stopped out at a loss) is the lever to sweep first.
## O'Neil 1w flat-base / new-high / pivot LONG, live swing wiring (B-1243/B-1244, 2026-10-14)
- Mechanism: weekly flat base (7-week range <= 12% after a >= 30% advance, close through the base high on >= 1.5x volume), 52-week new closing high, and 8-week pivot breakout above the 40-week mean; ATR14 x3 stop on weekly bars; exit at the close of weekly bar 26.
- Fit: the live swing scan only holds daily bars, so weekly bars are resampled (W-FRI) and the signal is the last completed week, entered in the first 2 sessions of the next week at the live close (replay entered at that week's open); the stop (3 x weekly ATR, roughly 15-25% of price) is always defined and rests at Kotak, so no-trade-without-SL holds; 26 weeks is longer than the 30-trading-day rule, user waived hold-period vetoes for this wiring.
- Result (run 38517583883, main.py functions, 1w, cost 0.8%): flatbase long PFnet 3.921 (n=115, win 60.0%, hold 21.9 bars), newhigh long 2.484 (n=9164, win 51.8%), pivot long 2.177 (n=10789); avg-down controls 5.149 / 3.477, trl1 3.407, flatbase short 1.399 (n=10, ex-top5 0.0). All registered as own tags.
- Surprised: flatbase profit sits in the 26-bar timeouts (avg +32%) while stops average -20%; the short mirror is carried entirely by its top 5 trades; 339 research-vs-replay n diffs are still unresolved.
- Reuse: weekly strategies need a completed-week signal window plus a re-entry guard; an avg-down variant can print the best PFnet but is excluded by the never-average-down invariant, so judge only the plain cell; check ex-top5 PFnet before trusting a small-n short.
- Profit-booking / exit takeaway: the edge is surviving to the 26-week timeout; stops lose, so do not tighten the 3 x ATR stop or book early; sweep a wider stop and a 12-week hold (faster turnover, h12 avg-down control still 3.48) before changing the live cell.
## Sector-rotation fade SHORT and momentum LONG, stop-fill sweep (B-1248, run 38520502338, 2026-10-14)
- Mechanism: rank sectors by lookback L (1/3/5 bars), short the weakest-sector laggard picks (fade) or buy the leaders (momentum); ATR stop (1.5/2.5/4/6), hold 2-20 bars, N=1/3/5 picks, 1d and 4h, each result under three stop-fill models (stop price, gap-aware, close).
- Fit: the stop is part of the backtest, but no live path attaches an ATR stop to a sector pick yet, so the no-trade-without-SL rule blocks wiring a short-fade cell until one does.
- Result (full NSE file universe, 1860 symbols, next_open entries, cost 0.8%, gap_aware headline, n>=100): 216 cells, 22 at PFnet >= 1.1. Best: fade short 1d atr1d5_h20_l5_n1 PFnet 1.398 (n 671, win 46.4%, hold 12.8 bars); atr1d5_h10_l5_n1 1.348 (hold 7.4); atr6d0_h5_l5_n1 1.302 (win 61%, hold 4.97, the fastest turnover). All best cells are L5, N1.
- Surprised: the winners are the narrowest picks (N1) on the longest lookback (L5); wider N dilutes the edge. Win rate and PFnet do not move together (46% win at 1.40, 61% at 1.30).
- Reuse: all 108 previously unregistered cells are now rows (headline gap_aware, other fills in evidence). Before wiring, build an ATR-stop attach path for sector picks; prefer atr6d0_h5_l5_n1 on turnover.
- Profit-booking / exit takeaway: shorter holds (5 bars) kept PFnet above 1.3 with 61% wins, so book early for this fade; the 20-bar hold adds only 0.1 PFnet at 2.5x the time.
## chan_kalman band SHORT, main.py replay coverage (B-1262, 2026-10-14)
- Mechanism: 1-D Kalman filter on log price; short when the residual exceeds z x sqrtQ, ATR stop, hold 40 bars, forced flat 15:15 IST (main.chan_kalman_band_short_*).
- Fit: intraday MIS short, stop always attached, so it fits the no-trade-without-SL rule; main.py port already replayed full universe at 0.8% and 0.3% for 5m/15m (24 cells each).
- Result: audit shows only the 1h cells (12, research PFnet 0.38-0.81 under flatten) lack a main.py replay; 1m/4h were never tested. Research vs main-replay PFnet differ by under 0.03 on every 5m/15m cell, so the port is faithful.
- Surprised: the replay already existed; the only manual step was converting the merge output to the docs JSON, now scripted, and the registry reads run files by glob so new runs register without code edits.
- Reuse: before building a replay, grep the workflow families and docs/backtest_data run files; check coverage by mapping research `band` tags to `band_mr` main tags.
- Profit-booking / exit takeaway: 5m z2 cells win via the 15:15 flatten (hold under 1h), so book same-session; 1h cells fail, no reason to hold longer.
## envelope 5% fade 1h, main.py replay and live wiring (B-1264, 2026-10-14)
- Mechanism: mean-reversion fade of a 5% stretch from SMA21 on 1h bars (long when close < SMA21 x 0.95, short mirror above 1.05), ATR14 stop, hold up to 18 or 30 bars, exit at the stop or the hold-th close.
- Fit: stop is part of the backtest and always returned (no-trade-without-SL ok); 30-bar hold is overnight CNC, so it rides the swing engine's 1h leg and its real SL path.
- Result (run 38550666361, main.py-calling, full universe, 1h 730d, cost 0.8%): long atr6_h30 PFnet 1.178 (n 42102, win 49.5%, hold 28.2 bars), long atr4_h30 1.127 (n 45800, win 47.6%, 26.0 bars); other long cells 0.91-1.04; all six short mirror cells fail (PFnet 0.59-0.64, gross below 1, so not a cost problem).
- Surprised: the short mirror fails outright; wider stops and the longer hold both help the long side, so only the timeout exits profit and the stop exits lose. Edge exists only if trades are allowed to run to the hold limit.
- Reuse: every cell registered with full metrics (6 SWING, 6 SHORT_SELL); wired by reusing the macddiv 1h pass (one hourly fetch per symbol shared by all 1h cells) instead of adding a new fetch loop; the replay file is flat-row JSON, separate from the `rows[].metrics` shape other loaders read.
- Profit-booking / exit takeaway: stop exits lose and timeouts win, so do not tighten the stop or book early on this fade; prefer the wider-stop 30-bar variant (atr6) and accept the ~28-bar hold, since the 18-bar hold drops PFnet to ~1.03.

## 2026-10-14 Cup 3C cheat 1h long and the wire-at-PFnet>=1 rule (B-1266)
- **Mechanism:** Minervini-style cup with a cheat pause (depth 15-35%, handle, pause near 40% retrace, close above the pause high), 1h bars, ATR14 stop, hold 6/18/30 bars.
- **Fit:** swing engine 1h leg, SL always attached, no new kill switch. Short mirror still owed as its own tag family.
- **Result (main.py replay, run 38553281449, full universe):** atr2d5_h30 PFnet 1.0071 (n 3121, win 41.04%, hold 22.1 bars), atr6_h30 1.0011 (n 3061, win 46.16%, hold 28.6), atr4_h30 0.9943; all h6/h18 cells 0.49-0.90. None reach 1.1.
- **Surprise / reuse:** same pattern as the envelope fade: PFnet rises with hold, timeouts are the only profitable exits. Under the 14 Oct wiring rule the cells with PFnet >= 1 are scanned and counted even while the 1.1 gate blocks the money trade, so the trigger rate is measured live.
- **Profit-booking / exit takeaway:** short holds (h6) lose after costs; the edge sits in letting the trade run to the timeout, so do not tighten the exit on this family.

## Floor change 1.1 -> 1.0 (2026-10-14)
- **Mechanism:** viability is derived from stored metrics, so lowering `PFNET_LIVE_FLOOR` re-decides every strategy instantly; cells in [1.0, 1.1) (OB/VP trail variants, cup atr2d5/atr6, envelope atr2d5_h30/atr6_h18) are viable again.
- **Surprise / reuse:** 14 tests hardcoded 1.1 or the old viable set; write floor-dependent tests relative to `sr.PFNET_LIVE_FLOOR` and use clearly-below cells (0.95) as the closed example, not a value just above the old floor.
- **Profit-booking / exit takeaway:** thin-margin cells (1.0-1.1) sit on max-hold survivors; do not tighten their exits.

## Wiring audit: main.py-replay cells (B-1268, 2026-10-14)
- **Mechanism:** compare every PFnet>=1.0 (n>=30) row in docs/backtest_data/*main_replay*.json to `_STRATEGY_TAG_TO_REGISTRY_NAME`; 117 of 122 were already wired, the gap was 5 chan_kalman 15m short cells (z1.0 and ve1e-4) that were skipped when the floor was 1.1.
- **Result:** wired ve10d0e4_z1d0 atr4/2.5/1.5 (1.070/1.032/1.003) and ve1d0e4_z2d0 atr4/2.5 (1.012/1.000), run 38390561217; cst0d3 (0.3% cost) rows are not comparable to the live 0.8% model so stay unwired.
- **Surprise / reuse:** a floor change silently leaves previously-rejected cells unwired; re-run this audit after every floor change. Research-only PFnet (month_effect, lunar, chan_tsm, pfovl, tasuki, cup 1d) is never enough: each needs its own main.py replay first.
- **Profit-booking / exit takeaway:** these 15m cells hold ~1-2h and flatten by 15:10, so no overnight risk; fallbacks only own a symbol if an earlier cell's gate closes.

## MCX contract roll (B-1269, 2026-10-14)
- **Mechanism:** choosing the earliest non-expired MCX future keeps the bot on a contract on its last day (CRUDEOIL/CRUDEOILM expire 15 Oct 2026); thin expiry-day liquidity and settlement make scan prices and entries unreliable. Now a contract within `MCX_ROLL_DAYS` (2 calendar days, IST) of expiry is skipped and the next is used, in both the live-feed token resolver and `select_nse_future` (MCX FUTCOM only; NSE futures unchanged).
- **Fit / rules:** a constant, not a kill switch. Open positions keep their stored trading symbol for exit and SL, never re-resolved; if no later contract exists the expiring one is still used (fail towards having a price).
- **Surprise / reuse:** two independent resolvers (feed and option-chain module) both had "nearest expiry" logic; any new contract picker must share the roll constant. The replay script wrote only a JSON artifact the sandbox could not download, so results must also go to stdout.
- **Profit-booking / exit takeaway:** never carry or open a position into expiry week of a commodity future; roll earlier so exits happen at normal liquidity, not on expiry day.

## MCX replay through real main (B-1270, 2026-10-14)
- **Mechanism:** the 8 live MCX daily cells were re-run through the real `main._mcx_daily_flags` (run 38582151119) and registered as `_mr` rows; the real-money gate and dashboard now read the replay PFnet, not the research sweep.
- **Result:** replay PFnet / n: sma_crossover gc 2.287/31, supertrend gc 2.346/17, bollinger si 2.496/17, supertrend cl 1.432/11, rsi ng 1.525/13, bollinger ng short 1.881/19, keltner ng short 1.500/22, donchian cl 0.820/16 (research 1.157, below floor so unwired). Samples are 11-31 trades on one proxy symbol each: thin.
- **Surprise / reuse:** a research PFnet just above the floor (1.157) did not survive the real-code replay; always replay through main before wiring. Atrnone cells are safe only because the option premium trailing SL is attached at entry; Kotak's position can lag the fill, so entry now retries the SL a few seconds instead of waiting for the 30s tick.
- **Profit-booking / exit takeaway:** these cells exit on signal drop (daily), the premium trailing SL is the only intraday protection; do not remove it.

## pl1d SHORT mirrors (B-1001, 2026-10-20 IST)
- Mechanism: short mirror of the 1d starc-band fade and gap runaway, stop = entry + k x ATR14 on every trade, 20-bar max hold.
- Result (run 39429939927, full 2680, real main.py functions, 0.8% cost): starc fade short PFnet 0.597 / win 35.3% / n=23845; gap runaway short PFnet 0.522 / win 42.9% / n=9809. Both below the floor, registered RESEARCH.
- What surprised: stop-loss exits have PFnet 0.0 on every trade (starc: 13476 of 23845 trades stopped in about 6 bars); only the 20-bar timeout survivors win (PFnet 13.7 and 1.46). Same shape as the other shorts: the bull-window market punishes shorts early and the edge only shows for those that survive.
- Reuse: sweep the ATR stop multiple wider before judging; do not wire a short whose stops are 55% of trades at PFnet 0.
- Profit-booking / exit takeaway: the profit comes from holding the full 20 bars, not from early exits; a tighter stop destroys it.

## Option bid/ask spread gate (B-1328, 2026-10-21 IST)
- Mechanism: option entries and risk-cut exits are market orders, so the bid/ask spread is paid on both legs on top of the 0.8% cost model; on a strike with few buyers and sellers that alone can exceed the 3% initial stop.
- Fit: every option entry path now goes through `_real_fo_buy_contract`, which skips when Kotak's spread is over 5% of mid. Kotak's `quote_type="all"` field names are not yet confirmed live, so an unread quote does not block; check the confirmed log rows after the next entry.
- Profit-booking / exit takeaway: the spread is a guaranteed loss on every round trip, so a strike that is cheap to enter but wide to exit is a losing trade before the setup plays out; prefer liquid (near-ATM, current-week) strikes.


## Charges in the daily loss cap (B-1315, 2026-10-21)
- Mechanism: Kotak positions() give gross buy/sell amounts only; statutory charges (option STT 0.1% of sell premium, exchange 0.035% of option turnover, stamp, SEBI, GST) never reached the loss cap.
- Size: on a Rs6k option round trip they are ~Rs11, about 8% of a Rs130 daily cap, so a cap read gross lets a day lose more than intended.
- Fix: estimated statutory charges are netted from the real P&L that gates entries; brokerage is left out until the plan rate is confirmed from a contract note.
- Profit-booking / exit takeaway: on thin option premiums, charges are a fixed drag of ~0.2% of turnover per round trip; a target smaller than that books a net loss.


## Chan buy-on-gap stop cap vs stop-fit rule (B-1331, 2026-10-21)
- Mechanism: the atr4d0 cell's stop (4 x daily ATR, 12-16% on volatile names) is outside the NSE price band, so the real stop is capped at 5% below entry. That capped variant had never been backtested.
- Result (run 39599591455, full universe, main.py functions, n 1188): capped-5% `chan_gap__buy_on_gap_mr__long__1d__atr4d0cap5_top10__v1` PFnet 1.411 (85 stop-outs) vs uncapped 1.445. The "pick the cell whose stop fits 5%" rule `..._fit5_top10__v1` was 1.242 on only 353 trades, because it skipped the 70% of days where no stop fits, and those were winners.
- Surprise: a tighter forced stop barely hurt the strategy (the edge is the close-out, not the stop), while filtering on stop width threw away good trades.
- Profit-booking / exit takeaway: on a same-day gap reversal, keep the trade and cap the stop; don't skip entries just because the textbook stop is too wide.

## 2026-10-21 - MCX cells added by the 1.0 floor (B-1333): live-function replay
- Mechanism: daily Donchian breakout gold long, RSI reversal silver long, RSI reversal natural gas short; became wired when the leftover 1.1 MCX threshold was retired.
- Replay (run 39626212667, real `main._mcx_daily_flags`): gold Donchian 1.370 n20 (registry 1.229), silver RSI 3.174 n16 (4.098), NG RSI short 2.605 n14 (2.281). All clear 1.0.
- Surprise: the live function moves PFnet both ways vs research (silver -0.9, gold/NG up), so research numbers are a guide, not a fact. n is thin (14-20 trades in 5y): treat sizes cautiously.
- Profit-booking / exit takeaway: the replay is underlying-only; real trades use the option-premium trailing SL, which is not simulated, so live exits can differ - compare the first live MCX fills against these numbers.

## 2026-10-22: carried-over swing stop fires at the open; sold shares linger in holdings (YESBANK)
- What happened: YESBANK 20 (avg 16.38) carried a trailed stop of 16.22 overnight. The exchange purges resting orders at 15:15, so the bot re-placed it at 09:17; the stock opened below 16.22 on a -1% market day, so the SL fired at once and sold all 20 @ 16.22 (~Rs3 loss before charges).
- What broke: holdings() keeps shares sold today until T+1. The netting of today's sells relied only on positions(); when that call failed, the heal saw "20 held, no SL" and sent 3 SELL SLs on sold shares (Kotak T1 check rejected them).
- Reuse next time: check two Kotak sources for "sold today" (positions() and the order book's complete sells); never act on holdings() alone during market hours. A Kotak call that times out may still have placed the order (WIPRO 09:16), so re-read the order book before any re-send.
- Profit-booking / exit takeaway: a trailed swing stop that sits above the next day's open becomes a market-open exit at the stop price; on a gap-down day that is the intended protection, but a stop trailed to within ~1% of price on a Rs16 stock gives almost no room, so trail width on very low-priced names should be judged in ticks and ATR, not percent alone.

## 2026-10-22: a timed-out Kotak order is not a failed order (WIPRO, B-1338)
- What happened: the 09:16 IST WIPRO SL request timed out after 30 s and was logged "sl failed", but Kotak had placed it (trigger 186.86, trigger pending at 09:16:44).
- Lesson: after any timeout, re-read the order book before reporting a failure or sending again. A blind re-send risks a duplicate stop, which means a double sell.
- Profit-booking / exit takeaway: a stop Kotak already holds is real protection. Adopt it, and never stack a second sell on the same shares.

## 2026-10-22: Kotak will not hold an overnight cash-equity short (B-967)
- Test: a 1-share IDEA-EQ SELL with product NRML at 10:15 IST (run 39724116793, order 261022000219219). Kotak RMS rejected it: "Short selling in NRML is not allowed. Instead, select MIS, CO or BO product type for intraday short selling."
- Fit for this system: a cash-equity short can only be intraday (MIS), and must be covered before the broker's square-off. Every multi-day short swing cell (sector_rotation fade, brk20 short swing) can never trade cash equity at Kotak. `SHORT_SWING_OVERNIGHT_PRODUCT_CONFIRMED` stays False for good.
- Reuse next time: a multi-day short needs a product that allows it, i.e. stock futures, or SLB borrowing. Futures mean lot-size capital and different costs, so the cell must be re-validated on futures before any wiring (B-1339).
- Profit-booking / exit takeaway: an intraday short must book its profit or loss the same day. Never design a short exit that relies on holding it overnight in cash equity.

## 2026-10-22: "no setup fired" can mean "nothing was scanned" (B-1340)
- Symptom: zero entries all day; /entry-funnel said "no setup fired today" in every category.
- Reality: the scheduler logged only 260 symbol checks against 3992 the day before. The 5-minute Kotak reconcile ran inline on the event loop and stalled on Upstash (403), starving the entry scan and freezing the web server (502 at 10:02 IST).
- Lesson: before reading a quiet day as "no setups", compare scan volume with a normal day. Zero signals on a fraction of the normal scans is an outage, not a market verdict. Any blocking I/O in the scheduler tick (Kotak, Upstash, git) belongs in a worker thread with a bounded wait.
- Profit-booking / exit takeaway: a starved scheduler also delays trailing-stop updates and exits, so scan health protects open profit as well as new entries.

## 2026-10-23: the backup store went dark because of our own upload volume (B-1341)
- What happened: Upstash's free database was suspended at its 10 GB/month bandwidth cap after only about 1.1 lakh commands. Since then no state survived a Render restart, and every call to the store returned 403.
- Cause: a dashboard scan-set blob of several MB was re-uploaded uncompressed every 60 seconds whether it had changed or not, alongside other per-tick whole-object pushes.
- Lesson: on a metered store, budget bytes as well as calls. Compress, skip unchanged uploads, throttle anything that isn't safety-critical, and meter usage per key so the next hog shows up before the cap.
- Profit-booking / exit takeaway: losing the store can lose a position's strategy identity and stop context on restart. Protect the safety-critical state's budget so it is never starved by dashboard data.

## 2026-10-23: a free backup store needs a daily budget, not a monthly surprise (B-1342)
- Mechanism: the bot meters every byte and command it sends to Upstash, keeps today's total across restarts, and backs off its own non-critical writes at 60% / pauses them at 90% of 1/30 of the monthly free cap, and slows them 6x outside NSE hours.
- Why it fits this system: the backup exists to protect real-money state through Render restarts; dashboard counters were eating the budget that positions and kill switches need. Tiering the writers keeps the money-critical backups alive.
- What surprised: a monthly cap gives no warning until the store is already dark, so the guard must be daily and must count across restarts.
- Reuse: any free-tier external dependency (Upstash, Render, Actions minutes) gets a metered daily budget, a status endpoint and a failing scheduled check.
- Profit-booking / exit takeaway: no direct trade effect; it protects stops and position records across restarts, which protects booked and open profit.

## 2026-10-23: an option stop inside the market's own noise is not a stop (B-1310)
- Mechanism: JIOFIN 217.5 CE was bought at 2.54 and stopped at 2.51 the same minute. A 3% stop on a 2.54 premium is 0.076, about 1.5 price ticks, and a market BUY fills at the ask, so the first bid print can trigger it.
- Fix: option entries are skipped when the stop is under 3 ticks (0.05 each) or the bid/ask spread is more than half the stop %.
- Why it fits this system: every option entry and risk-cut exit is a market order, so the spread is paid twice, on top of the 0.8% cost model; low-premium strikes turn that into a near-certain loss.
- Not replayable: option backtests carry no bid/ask or tick data, so this is a structural filter, not a tuned parameter.
- Profit-booking / exit takeaway: size the stop from the instrument's tick and spread first; a stop tighter than the noise books a guaranteed small loss instead of protecting a trade.

## B-1339 (2026-10-23 IST): multi-day shorts need futures, and futures need capital

- Mechanism: Kotak rejects NRML cash-equity shorts (B-967), so a short held overnight can only be a stock future (or SLB). The brk20 short 1d signal is strong on cash (registry PFnet 3.9-10.3, n=39-189).
- Fit for this system: one stock-futures lot needs about Rs 1-3 lakh margin, and an ATR4 stop on one lot risks tens of thousands of rupees. The account holds a few thousand rupees, so the live path could never place an order. Not built; revisit at about Rs 2.5 lakh capital.
- Research kept ready: brk20 replay now takes universe=fno and a cost override (own tags, main_replay_fno / costX), so the F&O-only, futures-cost number exists before capital does.
- Reuse next time: check lot-size margin and one-lot stop risk against the account BEFORE building any futures or new-instrument route; a strong signal is worthless if one unit exceeds the loss budget.
- RESULT (runs 39861078873, 39861349630): on the 210 F&O underlyings the same signal loses before costs in all 9 swept cells (PFnet 0.45-0.75, gross 0.52-0.86). The cash edge lives in small caps that have no futures or options. Closed B-1339 and B-1343.
- Surprise: a zero-trade run looked like a broken fetch; it was the rule (16 ATR of room never happens in large caps). Read the entry rule before blaming the data, and keep the harness printing loaded/error counts.
- Reuse next time: before routing any cash-equity edge to F&O, rerun it on the F&O universe first; universe composition can be the whole edge.
- Profit-booking / exit takeaway: a short signal that cannot be held overnight is worth nothing as a swing; and an edge confined to small caps cannot be moved into derivatives, so keep it as research.

## Wiring vs entry are two different gates (2026-10-23 IST, B-1344)
- Mechanism: wiring = monitoring (scan, paper signal, trigger counts) and has ONE condition, registry PFnet >= 1 (net of costs, before income tax). Real entry is the last step and adds the explorer stack (PFnet range, min trades, max hold), replay-owed block and the switch.
- What broke: `is_wired()` had quietly picked up a 30-day hold condition and `_is_strategy_wired()` a replay-owed block, so long-hold PFnet >= 1 cells were never monitored and produced no trigger evidence.
- Reuse: never add an entry-side filter to the wiring function; put it in `_is_strategy_viable_for_real_money`.
- Profit-booking / exit takeaway: monitoring more PFnet >= 1 cells costs nothing in real money and gives trigger counts that show which cells deserve an entry slot.

## Day-trader skill pack, India port (2026-10-23 IST, B-1345)
- Mechanism: 11 chat-side helpers (scan, news, entry/exit timing, sizing, risk check, Monte-Carlo replay, order ticket). Ported to NSE/IST/₹ and Kotak draft tickets; long AND short (MIS).
- Fit: research and manual-check aid only. Its ORB entry (close above/below the 15-min range) is not a registered strategy and has no PFnet here, so it must never drive real money; any idea from it goes through the normal full-universe replay first.
- Reuse: the exit planner's "mirror prices around the entry" trick makes a short plan from long maths with correct rounding; Kotak cash has no OCO bracket, so SL-M and target are separate legs.
- Profit-booking / exit takeaway: the pack's default flat-by was moved to 15:10 IST because the exchange cancels resting orders at 15:15 and the bot squares off at 15:14.

## O'Neil averaging-down "negative control" beat no-averaging (2026-10-23 IST, B-502, run 38193479637)
- Mechanism: the avg1 cells add a second unit after a drop, as a deliberate control expected to lose.
- Result: avg1 beat the matched no-averaging cell in every pairing (median PFnet +0.46 1d long, +0.88 1w long, +0.20/+0.33 short). Most "best" O'Neil cells are avg1 cells (flatbase 1w 8.71 vs 6.70 without; cup_handle 1d 2.55 vs 2.04). Weekly short viability almost disappears without avg1 (only saucer keeps ~26 thin cells, n~33).
- Fit: the engine invariant stays never-average-down. Averaging down raises PFnet by doubling exposure on losers that later recover inside a 30-day hold; it hides tail risk (a stock that keeps falling costs two units) and the per-trade stop no longer bounds the loss. Not wired; any future proposal needs a drawdown/tail measure, not PFnet alone.
- Also: on O'Neil longs, 8% stops (-0.03/-0.31 median PFnet 1d/1w), +20% target (-0.15/-0.29) and the swing-low trail (-0.14/-0.04) all lost to the plain ATR3 stop with timeout.
- Profit-booking / exit takeaway: for O'Neil base breakouts, a wide ATR3 stop held to the timeout books more than an early +20% target or a tight percent stop; quote no-averaging cells when ranking.

## Minervini ATR-trail sweep follow-up: universe, live analog, per-bar edge (2026-10-23 IST, B-791)
- Mechanism: real `minervini_vcp_entry_signal` (long/short), structural stop plus ATR trail 1.5/2/3/4 x entry ATR, 60-bar max hold, 1d, 6y, 0.8% cost (run 38147956271).
- Fit here: universe confirmed from committed files at 2506 symbols (docs/nse_universe.json 2688 minus 182 ETFs); the "nifty200" log line came from main's NSE_FULL_UNIVERSE reassignment, which the lab never reads. Always check what the harness actually calls before calling a universe "unconfirmed".
- Result: long atr2 1.025 (12.5d), atr3 1.181 (21.6d), atr4 1.342 (29.6d); excess PF per held day 0.0020 / 0.0084 / 0.0116, so atr4 wins on both PFnet and turnover-adjusted edge. Shorts 0.60-0.65 at every multiple (fail).
- Surprise / broke: the backlog assumed the live minervini_vcp tag used an atr1.5 trail because both read PFnet 0.908. The live exit trails at 2.0 x ATR on closes; the 0.908 match is a coincidence across different samples (n 3845 vs 327). Match by code constants, never by matching numbers.
- Supporting evidence (fixed-stop proxy, same entry, run 38245172228): widening the stop from 1.5 to 3 ATR moves timeout survivors from 31% to 58% of trades and PFnet from 1.155 to 1.363. The edge again sits in trades that survive to the time exit.
- Reuse: the sweep lab now splits initial_stop vs trail_stop and logs per-reason PFnet, so the next run answers exit questions from the log without fetching an artifact. Replay the atr4 trail through main.minervini_vcp_exit_reason (close-based) before changing the live 2.0 constant.
- Profit-booking / exit takeaway: on Minervini VCP longs, a wider ATR trail (3-4 x) lets winners reach the time exit and earns more per day held; a tight 1.5-2 x trail books small gains too early. Do not tighten it to "lock in" profit.

## NATIONALUM chan_kalman band long, live 2026-10-23 (B-1347)

- **What happened (Kotak order book):** BUY 3 CNC at Rs300.00 at 09:19:46 IST, entered by `chan_kalman__band__long__5m__atr4d0_hold40_ve1d0e4_z2d0_fl1515__v2`. SL trigger Rs293.05 placed 09:19:58 IST. SL cancelled and 3 sold at Rs300.10 at 09:22:27 IST. Gross +Rs0.30, net about -Rs7 after the ~0.8% round-trip cost.
- **Why it matters:** a 2.7-minute round trip on a 5m-bar strategy cannot clear costs. A +0.03% move against a 0.8% cost hurdle is a guaranteed net loss. Also, the exit reached Kotak with no app reason row (B-1350), so we cannot tell whether the strategy's own exit fired inside its first bar.
- **Reuse next time:** for small CNC tickets (Rs900), fixed costs dominate. Any exit path that can fire within the first bar of a 5m strategy should be checked against the cost hurdle in the backtest's exit-reason breakdown.
- **Profit-booking / exit takeaway:** never book a "profit" smaller than the round-trip cost. An exit within minutes at roughly entry price is a cost loss. Treat it as a defect to root-cause (B-1350), not as a scratch trade.

### 2026-10-23: NATIONALUM exit during a frozen process (B-1350)
- What happened: the SL cancel + SELL went out at 09:22:27 IST while the Render process had been silent for 5 min (CPU starved), 8 s before Render restarted it. The reason row was written but lived only in local SQLite and was wiped.
- Lesson: a reason that is not durable within seconds is not a reason on record. Order reasons now push to git on every event (B-1355).
- Profit-booking / exit takeaway: an exit decided by a starved process may act on stale prices; keep the CPU fix (B-1348) and treat any exit while the app log is silent as suspect when auditing P&L.

## 2026-10-26: swing stops were silently lowered (B-1367)

- **What happened:** entry-day stops on 5 swing holdings drifted down over two weeks (BANKINDIA 126.73 -> 120.91 -> stored 115.72; COALINDIA 398.35 -> 373.20). Three paths did it: a heal fallback that recomputed close - 2.5 x ATR on ANY rejection (a 15:21 IST CAS-session reject counts), the align step adopting a lower SL that something else had placed, and the "stop at/above market -> reset 1% under live" rule.
- **Why it matters here:** a lowered stop is a bigger loss than the backtest allowed. The validated exit is "entry stop, ratchet up only"; lowering it is an untested strategy.
- **Rule now:** the entry-day stop is stored once (swing_entry_stop, Upstash-mirrored) and is a floor for every placement. If the price is already at/below it in session, the stop is hit and the holding is sold at market. It is never lowered.
- **Profit-booking / exit takeaway:** honour the stop you entered with; a "rescue" by widening the stop turns a planned -1R into an unplanned larger loss (BANKINDIA would have exited near 126.7 on 23-Oct; it sits at 126.32 with a 115.72 stop).

## 2026-10-26: option entry unwound because its SL could not rest (B-1316)

- **What happened (Kotak):** JIOFIN26OCT217.5CE bought 2350 @2.54 09:52:36 IST, sold @2.51 12 s later (~Rs70 loss); no SL ever rested at Kotak.
- **Root cause from code:** the initial option SL is entry x 0.97, rounded to the 0.05 tick (2.54 -> 2.4638 -> 2.45), i.e. 1-2 ticks under the ENTRY ESTIMATE (the chain premium, not the fill), with the limit 5% under it. At a Rs2.5 premium a 1-2 tick spread puts that trigger at or above the bid/last price right after the market buy, so Kotak rejects the SELL SL (or it fires on the first print); pre-B-1318 the first `sl_failed` unwound the leg at once. Price bands are not the binding limit at this premium; tick granularity and the spread are.
- **Fix:** `kotak_real_fo_orders.option_entry_sl_placeable` replays the SL's own rounding before every option BUY (`_real_fo_buy_contract`, all option paths): trigger at least 1 tick under entry, below the live bid, limit a positive tick under the trigger, above any known band. Otherwise the buy is skipped with `skipped_option_stop_not_placeable`.
- **Reuse:** always validate a stop with the exact rounding the order path applies, against the bid, before the entry; never buy what must be unwound.
- **Profit-booking / exit takeaway:** a stop within one or two ticks of a cheap option's entry is not a stop, it is a guaranteed spread-plus-cost loss; skip the trade instead.

## Swing short min R:R and protective stop audit (B-842, 2026-10-27 IST)

- **Mechanism checked:** the short-swing engine already places a BUY stop with every real short (or unwinds it), heals a missing stop every 5 min from Kotak's own order book, and keeps its rows in Upstash. Min R:R lives as an entry gate (room to the prior 60-bar low >= rr x risk) on the brk20 cells, and as a BUY target = entry - 4R only on the 1h gatetarget cell.
- **Fit:** an overnight NSE cash short still has no confirmed Kotak product (B-912), so the real leg stays closed; paper runs.
- **What surprised:** adding a target to a gate-only cell lowers PFnet (1h: gate 1.702 vs gatetarget 1.561, run 38249384880); the room filter alone captures the R:R edge.
- **Reuse:** treat "min R:R" as a property of the validated variant (gate vs target), never bolt a target onto a cell that was validated without one.
- **Profit-booking / exit takeaway:** for brk20 shorts, let the stop / EMA13 / timeout run rather than booking at a fixed 4R; a fixed target gives up more on the big runners than it saves.

## Chan non-overlap 4h re-run (B-1241 / B-806, run 38510016719, 2026-10-14 09:44 IST)

- **What ran:** 108 Chan (Algorithmic Trading) cells at 4h, strict FIFO with one position per symbol per cell, 0.8% cost, ATR stop in every cell, both directions, families chan_tsm, chan_alexander, chan_zmr, chan_updays, chan_shape, chan_ema_regime. Raw table in `docs/backtest_data/chan_nonoverlap_run_38510016719.json`. All 108 are registered via `strategy_registry_chan.py`; 4h cells go in the swing category because an average hold of 22-26 bars is several days. None is wired.
- **Result:** apart from one outlier, every cell is below 1.0 net. Best credible cells (net/gross/win%/n/avg hold): chan_alexander zigzag long atr4d0_hold30_x0d2 0.984/1.159/43.1/9208/104 h; chan_updays bb_upper long atr4d0_hold10 0.795/1.093; chan_zmr fixed20 long atr4d0_hold40 0.741/1.087 (win 55.7%); chan_shape mom_mr long atr4d0_hold10 0.702/1.012. The best short is chan_tsm lb300 atr4d0_hold25 at 0.749. 34 of 108 cells clear 1.0 gross, and the 0.8% cost model takes every one of them back below 1.0. Like the 1d/1h runs, the long side beats the short side, and the widest stop (atr4d0) wins in almost every family.
- **Outlier, chan_tsm lookback_sign long atr4d0_hold25_lb150 (net 3.03, gross 3.543, n=52451):** registered with its real metrics because of the keep-all-data rule. The raw JSON points to a data artifact rather than an edge. Its exit mix (max_hold 40412 / stop 12039), average hold (22.15 bars) and win rate (38.2%) are almost the same as lb50 (38.9%, 22.27 bars, net 0.80) and lb300 (37.4%, 22.2 bars, net 0.723). Yet its average net per trade is +7.96%, against -0.79% for lb50 and -1.07% for lb300. The five cells around it also lose about 1% a trade: atr1d5 and atr2d5 at the same lb150/hold25 (0.669 and 0.733, -1.08% and -1.00%) and the lb150 short mirror (0.723, -1.11%). Those two long cells use the same entry signal with tighter stops. If lb150 had a real edge, it would show up there too. The same win rate with a per-trade mean nearly 9 points higher means a handful of huge winners, almost certainly bad or unadjusted prices (a split or a bad tick) in one shard that only this stop/hold combination happened to ride. Its notes field is tagged SUSPECTED DATA ARTIFACT. Its PFnet passes the viable floor numerically, but the tag has no `_STRATEGY_TAG_TO_REGISTRY_NAME` mapping, so no scan or real entry can use it. Before it is trusted, re-run this cell alone and dump its top 20 trades by net %.
- **Reuse:** when one cell beats its neighbours by 3-4x while win rate, exit mix and hold match them, compare avg_net_pct and inspect the top trades before believing it. A real edge moves win rate or exit mix too; a jump in the mean alone points to the data.
- **Profit-booking / exit takeaway:** Chan's 4h signals do not survive 0.8% round-trip costs with any stop or hold tried here; no profit-booking change fixes a gross PF of 1.0-1.16. If these families come back, try lower-cost execution or a higher timeframe, not tighter exits.

## macddiv 1h long through the real main.py path (B-1396, run 38550669732, read 2026-10-28 IST)

- **What ran:** the 4 wired `macddiv__*__long__1h__*_w5__nonovl__v2` cells replayed through the live main.py functions on the full NSE universe, 0.8% cost, FIFO non-overlap (file `docs/backtest_data/macddiv_main_replay_run_38550669732.json`).
- **Result (net PF / n):** hist_any atr3 0.681 / 92829; line_any atr1d5 0.644 / 64482; atr2 0.687 / 61797; atr3 0.734 / 57802. Gross PF about 1.01. All below the 1.1 floor, against 1.14-1.46 in the research harness (B-812).
- **What broke:** the research harness's PFnet did not survive the move to the live code path; the gap (about 0.7) is far larger than sampling noise, so the research port and the live port differ (signal timing or exits). This file also stored metrics flat, so the gate never read it and the cells sat as "replay owed" for 2 weeks after the replay was done.
- **Reuse:** trust only the main.py replay for a go/no-go; store replay rows with nested `metrics` (or keep `_replay_rows` reading both shapes); treat a research-vs-live gap above 0.2 PFnet as a port bug to find before any further sweep.
- **Profit-booking / exit takeaway:** gross PF about 1.0 means no exit change rescues these cells at 0.8% cost; leave them closed for real money.

## chan_shape mom_mr long 1d through the real main.py path (B-1396a, run 40572999957, 2026-10-28 IST)

- **What ran:** the 6 wired `chan_shape__mom_mr__long__1d__*__nonovl__v2` cells, live main.py entry/exit, full NSE (2416 symbols with data), 5y daily, 0.8% cost, strict FIFO.
- **Result (net / gross / win% / n / avg hold days):** atr1d5 h10 0.802/1.052/36.5/53997/8.0; atr1d5 h5 0.720/1.045/37.5/68654/4.5; atr2d5 h10 0.848/1.100/40.3/49520/9.3; atr2d5 h5 0.749/1.085/38.9/66639/4.9; atr4d0 h10 0.891/1.162/41.3/48369/9.8; atr4d0 h5 0.770/1.122/39.2/66290/5.0. None clears 1.1.
- **What surprised:** trades that reach the max-hold timeout are profitable (PFnet 1.1-4.5) and every stop-loss exit loses; wider stops and the longer hold improve PFnet steadily, but gross PF of 1.05-1.16 leaves almost nothing after 0.8% cost.
- **Reuse:** the monotone gain with wider ATR and longer hold says the edge is drift, not the shape signal; a hold-20/atr6 sweep is the only lever worth one more run, and only if gross PF moves well above 1.2.
- **Profit-booking / exit takeaway:** do not book early: the timeout exits carry all the profit; the stop is the cost. Stay closed for real money.

## tasuki gap ETF short 1d + swingminrr brk20 short 1h through main.py (B-1396c, run 40575438117, 2026-10-28 IST)

- **Result:** tasuki atr2d5/4/6 h3 on 157 ETFs: net 1.327, gross 2.86, win 43.9%, n 82, all three identical (only 1 stop hit in 82, so the ATR multiple never mattered); registry research said 2.079/1.651. swingminrr brk20 gate short 1h: net 0.592 (n 2174), gatetarget 0.529 (n 2178); research said 1.702/1.561.
- **What broke:** the 1h swingminrr shorts collapse on the live path (gross 0.65-0.72, below 1 even before cost), as macddiv did: research-port PFnets above 1.5 on 1h cells have now failed twice in the real replay. Timeouts carry big profit (PFnet 10-20) but 40% of trades stop out first.
- **Reuse:** treat any 1h research PFnet as unproven until the main.py replay runs; tasuki's edge is small-sample (n 82) and ETF-only, so size it small if it ever goes live.
- **Profit-booking / exit takeaway:** tasuki makes its money by holding the full 3 days (timeout exits PFnet 1.66); the stop is almost never hit, so do not tighten it to "protect" profit.

## month-effect short through main.py (B-1396b, run 40580498404, 2026-10-28 IST)

- **Result:** 15m (2706 symbols, n 2401 per cell): atr6 h25 1.444 (win 61.6%), atr4 h25 1.281, atr2d5 h25 1.058 (all three clear the 1.0 floor), atr6 h125 0.687 (fails). 1d over 5 years (n 10068): 0.36-0.42 in every cell.
- **What broke first:** the live code read bar dates from `df.index`, but `fetch_ohlc` keeps them in a "Date" column, so every bar read as 1970 and the September-1 signal never fired, in the replay AND the live paper engine. Also, 15m requests over 60 days fail silently in yfinance. A replay that reports n=0 must fail the job, never pass as a result.
- **What surprised:** the 15m "pass" is ONE market day (all 2401 trades on Sept 1, highly correlated), while the 5-year daily version loses badly. Treat it as unproven.
- **Reuse:** read bar times through a helper that understands fetch_ohlc's Date column; give every replay an n=0 failure; for calendar effects, count distinct event dates, not trades.
- **Profit-booking / exit takeaway:** on the 15m cells the wider ATR6 stop with a 25-bar exit did best (stops cost, timeouts pay); a 125-bar hold gives the gain back. Keep it paper-only until a second Sept-1 confirms.

### 2026-10-28 - macddiv 1h long: research vs replay, owner keeps View 1 control (B-1398)
- Research PFnet 1.40-1.46 (n 58k-93k) came entirely from the in-sample half (2.17-2.21); out-of-sample 0.47-0.56. The main.py replay (run 38550669732) landed 0.64-0.73, gross PF 1.01-1.09, so costs (0.8%) turn a near-zero gross edge into a ~30% loss per unit risked.
- Lesson: a pooled research PFnet that hides an IS/OOS split of 2.2 vs 0.5 is curve-fit; always read the segoos row before trusting the headline.
- Owner decision: View 1 (VIABLE_OVERRIDES) still decides real money; the explorer now shows "replay failed" so the choice is made with the evidence visible.
- Profit-booking / exit takeaway: with gross PF ~1.05, no exit tweak can clear 0.8% costs; this family needs a better entry, not a better exit.

### 2026-10-28 - gaps fade LONG 1d: main.py replay confirms research (B-1396d)
- Run 40623860743, real main.gapfade_long_entry_signal + _gapfade_exit_adapter, 2,412 symbols, 1d 5y, 0.8% cost: common_fade atr3_nb5 PFnet 1.286 (n 5,241, win 40.4%, hold 3.4 d); exhaust_fade atr3_nb5 PFnet 1.226 (n 4,059, win 37.0%, hold 3.7 d). Research was 1.121 / 1.246, so the port is faithful (unlike macddiv, where replay fell to 0.7).
- Exit mix: the rule exit carries it (PFnet 1.39 / 1.37 on ~97% of trades); stops are 1.5% / 5% of trades; 30-day timeouts are rare but very profitable.
- Lesson: a short-hold daily strategy whose research and replay agree within about 0.15 PFnet is the kind worth wiring; a large IS/OOS gap (macddiv) predicts the replay failing.
- Profit-booking / exit takeaway: book on the rule exit (gap-fill / mean reversion) in about 3-4 days; do not widen the stop, since stops are rare and the edge is the quick reversion.

## B-1401 (2026-10-28): stop scanning non-viable intraday engines
- orb-universal-score (PFnet 0.05), orb-range-short (0.21) and orb-trend-short (0.09) were still evaluated every tick on every symbol only to be rejected by the real-money gate. Scanning now follows the same viability verdict, so CPU goes to engines that can trade, and the View 4 "rejected" list stops filling with them.
- Profit-booking / exit takeaway: exits and stop management for any position already open under these tags are unchanged; only new-entry scanning stops.

## B-1402 (2026-10-28): daily SL-vs-strategy check in View 4
- Each active position now shows whether the Kotak SL trigger matches the strategy's own stop (intraday: paper stop in signal_state/_short; swing: real_positions_swing.stop_loss). A Kotak SL lagging a trailed strategy stop gives back profit the strategy already locked in, so it shows red.
- Profit-booking / exit takeaway: a trailing stop only books profit if the broker-side SL actually follows it; check this column during the session, and any red "behind" row is a missed trail to root-cause.

## B-1405: an adopted (orphan) holding must never be treated as an entry signal (2026-10-28)
- What happened: NHPC's reroute created a paper swing row tagged `swing_rerouted_orphan` dated today. Once the real share was sold, the entry-retry loop saw "paper open, no real row" and kept trying to buy it again (9 share + 9 option-leg attempts). Only the PFnet gate (fails closed on an unregistered tag) stopped a real buy.
- Lesson: a retry/mirror loop must check WHY a paper row exists. Rows created by adoption or reroute describe a holding, not a signal, and must be excluded from any entry path explicitly, not just by luck of a gate.
- Profit-booking / exit takeaway: once a position is closed at Kotak, every leftover local row for it must be inert; a stale row that can re-enter turns a booked exit back into unplanned exposure.

## 2026-10-29 - Overnight swing stops vs the daily price band (BANKINDIA, SUZLON)
- What happened: at the 09:15 IST open, Kotak rejected the strategy stops BANKINDIA 115.72 and SUZLON 28.91 as 'Circuit breach': NSE accepts no order outside the day's band (here prev close +/-10%). The B-1304 retry re-placed them at the band floor (119.97, 33.67), which was accepted.
- Lesson: a stop wider than the daily band cannot rest at the exchange. The real protection is the band floor, tighter than the backtest assumed, so wide-ATR swing strategies (order_block_delta 6xATR) are traded live with a different stop than the one validated. Pre-clamp before sending, and replay with the band-capped stop (B-1413).
- Profit-booking / exit takeaway: on a position whose stop sits beyond the band, the live exit comes sooner than the backtest's; judge its live P&L against a band-capped replay, not the registry PFnet.

## 2026-10-29 - JSWENERGY short stopped out 12 seconds after entry (chan_kalman band short, 1.5x ATR, 5m)
- What happened: the signal's stop was the 5m close + 1.5 x ATR, about 0.5% above. By the time the real order went in, the market was already at that stop: the limit sell at 501.80 filled at 504.15, and the buy-stop at 504.15 fired at once. Flat gross, costs lost.
- Lesson: a tight-ATR intraday stop is only valid relative to the price the order actually fills at. Check the live price against the stop before sending the entry, and refuse an entry whose fill would sit at or past the stop (B-1414). A stale reference price (here about 0.47% off) is enough to erase a 1.5x 5m-ATR stop entirely.
- Profit-booking / exit takeaway: an entry with less stop distance than the round-trip cost cannot book profit; skip it rather than open and immediately pay to close it.

## 2026-10-29 - OB / VP swing under the stop Kotak can actually hold (B-1413)
- Mechanism: the live OB/VP stop is a resting exchange SL. It triggers on the day's Low (not the close), and it cannot sit below the ~10% daily band, so a 6xATR stop is lifted to prev close x 0.9 x 1.003 every morning.
- Result (real main.py fns, full universe, daily/5y; runs 40818729237, 40819741108, 40819738646, 40820614764, 40820611445): trail6d0 close-based backtest 1.105 / 1.076 -> live model 0.958 / 0.811 (OB / VP). exitinval (the live tags since 2026-10-11): main.py replay 1.074 / 1.089 with no band (research sim had 1.166 / 1.268), 0.966 / 1.006 with the band floor. The gate now reads the band-floor rows: OB 0.966 is under PFNET_LIVE_FLOOR 1.0, so new OB entries are closed; VP 1.006 clears it by a hair and stays open.
- Surprise: the band floor alone (resting stop only at the band, strategy stop on the close) still costs about 0.1 PFnet: the max-hold winners that dip 10% intraday and recover are exactly the trades that make these strategies pay. The research simulator and the main.py replay also disagree by about 0.1-0.18 for the same exitinval rule (B-1416).
- Reuse: any swing strategy with a stop wider than ~10% or with an edge concentrated in long-hold survivors must be replayed with band_cap=live before it gets real money (B-1417 covers the rest of the live swing set). VP at 1.006 has no margin: one more cost or slippage point closes it.
- Profit-booking / exit takeaway: for a wide-stop swing strategy, the backtest's close-based stop is not executable at Kotak; the live stop is a tighter, intraday, band-trailing stop that cuts the recovering winners, so judge it on the band-capped number.

## 2026-10-29 - Research sim vs main.py replay gap for OB / VP exitinval (B-1416)
- What disagreed: for the same rule (6xATR frozen stop + weekly EMA13 turn + 30-day hold), `scripts/exit_family_research.py` (run 38140914889) gave PFnet 1.166 / 1.268 on n 57.7k / 61.1k. The main.py replay (run 40820614764) gave 1.074 / 1.089 on n 33.2k / 38.4k.
- What matched: entries (same real main.py functions), fill (signal close in both; neither uses the next open), and stop/exit order (open gap, then intraday low at the stop, then invalidation at the close, then timeout).
- Root cause, by reading the code: (1) the sim let trades overlap (every signal 5+ bars apart is a separate trade, even inside an open position). This explains ~90% of the n gap and an estimated 40-60% of the PFnet gap, because overlapping copies re-count the same trending winners. (2) The replay charges the Rs 18.8 DP fee per trade on small 1%-risk positions (about Rs 11-17k for a 6xATR stop), roughly 0.11-0.17% extra per trade, about 0.05-0.06 PFnet. (3) Its risk weighting (1/ATR%) down-weights the high-volatility max-hold winners. Smaller differences: the sim drops end-of-data trades, excludes ETFs and cleans spikes; the replay's 250-row window disables weekly flags for a symbol's first ~150 bars, a replay artifact that does not happen live.
- Fix: the sim now defaults to MATCH_MAIN_REPLAY (one position per symbol, risk sizing, itemized cost + DP, force-close at data end) and writes new `__v2` tags; `--legacy-sim` keeps the old `__v1` behaviour. Re-run exit-family-research once to confirm that v2 lands near the replay.
- Reuse: any signal-per-bar harness must run non-overlapping, with live sizing and fixed per-trade fees, before its PFnet is quoted. The gate should read the main.py replay (here the band-floor rows 0.966 / 1.006), never an overlapping sim. Small risk-sized swing positions make flat per-trade fees (DP) a real drag; a 0.8% flat cost understates them.
- Profit-booking / exit takeaway: the exitinval edge sits in 30-day max-hold survivors, which an overlapping sim counts several times. Size the live book on the non-overlapping number. On wide-stop swing trades, keep notional large enough (or trades few enough) that the fixed DP fee per sell does not eat the thin margin above the floor.

### B-1417 (2026-10-30 IST): live resting-stop model vs backtest stop, every live swing strategy

- Mechanism: the backtests checked a swing stop on the close (or the low) with no price band, but live a resting SL-M sits at the exchange and fires intraday, and it can only be placed within the 10% price band (band floor = previous close x 0.9). Run 40952500265 replayed every live swing strategy with the real main.py entry/exit functions, with band_cap off and then live (full universe, 0.8% cost).
- Result: every live strategy stays above the 1.0 floor. The cost of the live stop model is larger the higher the PFnet: O'Neil flatbase 2.94 -> 2.08, newhigh 2.20 -> 1.72, pivot 1.84 -> 1.50, primary_base 1.54 -> 1.37, brk20 long 2.50 -> 2.36, gap_and_go 1.148 -> 1.107 (thinnest margin), power_play flat (5.75 -> 5.80). chan_shape and macddiv stay below the floor either way (already gated closed).
- Surprise: the macddiv registry rows (1.14-1.46) come from the research sim; the real-code replay gives 0.68-0.72 even with band_cap off. Research-sim PFnets must never open a gate on their own (same lesson as B-1416).
- Reuse: quote a swing strategy's PFnet under the live stop model (rsbandfloor tag) when sizing or ranking; the ordinary backtest overstates edge by 0.04-0.9 PFnet.
- Profit-booking / exit takeaway: intraday stop fills take away part of the gain from the strategies that let winners run (O'Neil, primary base), and gap_and_go has the least room left (1.107). Watch its live fills first. If live results run below 1.1, tighten its entries before widening its stop.

### B-1426 (2026-10-30 IST): live resting-stop model on the remaining live swing families

- Mechanism: same band_cap off vs live replay as B-1417 (run 40990174070, real main.py entry/exit fns, full NSE, 0.8% cost), on island, gapfade, pl1d, swingminrr (VCP long + brk20 gate short 1h), tasuki ETF short, envelope 1h and cup cheat 1h. Each live-mode result is its own `rsbandfloor` tag (23 rows, strategy_registry_b1417.py RUNS).
- Result: island (1.61-2.89), swingminrr VCP long (1.32-2.90), gapfade (1.21-1.28) and pl1d (1.14-1.21) barely move. tasuki ETF short drops 1.33 -> 1.09 (n=82, thin sample). Three wired 1h longs cross below the 1.0 floor under the live model: cup_cheat atr6_h30 1.003 -> 0.994, envelope atr2d5_h30 1.021 -> 0.977, envelope atr6_h18 1.006 -> 0.935. Their real-money entry gate is now closed through REPLAY_FAILED_TAGS (main._bandcap_live_failed_tags, newest band_cap run per tag decides, derived at read time; exits/SL untouched). envelope atr4_h30 (1.040), atr6_h30 (1.062) and cup_cheat atr2d5_h30 (1.017) stay open with thin margins. swingminrr brk20 gate/gatetarget short 1h are 0.59 / 0.53 either way (already closed as replay_below_floor).
- Surprise: envelope 1h loses almost all of its live-model drop to `band_floor_stop_hit`: about 8k EXTRA trades (n 47-55k -> 54-61k) that exit within ~2.5-3.5 bars at PFnet ~0.01-0.07. At 1h bars the 10% band floor is re-anchored to the previous DAILY close, so on a fresh -5% fade entry the floor can sit just under price and fire on the next intraday dip, recycling the symbol into a new entry. The max-hold survivors still earn 1.6-8.8.
- Reuse: for any 1h (intraday-bar) swing strategy entered after a big down move, check where the band floor sits relative to the entry before trusting a backtest stop; an entry whose band floor is within ~1 ATR of price is effectively a tight-stop trade. Candidate fix to research (not a parameter nudge): skip the entry when price is within X% of today's band floor, or enter only after the band re-anchors next day.
- Profit-booking / exit takeaway: the envelope/cup 1h edge sits entirely in trades that survive to the 18-30 bar max hold; the live band-floor stop cuts the deepest dips within ~3 bars at near-total loss, so judge these cells on the rsbandfloor number and prefer the wider-stop/longer-hold cells (atr6_h30 1.06) that keep the most survivors.

### B-1427 (2026-10-30 IST): gap_and_go entry x alternative exits, main.py replay, xroc exit wired live

- Mechanism: same gap_and_go entry (main.gap_and_go_entry_signal), five exit cells ported to main.py (exitfamily_walk / exitfamily_exit_reason) and replayed on the full NSE universe (run 41013761661, 2678 symbols, 0.8% cost), band_cap off and live, with the live gap_and_go exit as the control in the same run. Raw: docs/backtest_data/gap_and_go_exitfamily_replay_41013761661.json; 10 registry rows (off = `rsintraday` tag, live = `rsbandfloor` tag; the bare v2 tags keep their research-sim numbers).
- Result (PFnet off / live, hold in bars): control gap_and_go 1.136 / 1.097 (17.5 / 15.7). xroc exhaustion 1.225 / 1.209 (11.1 / 10.6), the best live PFnet AND the shortest hold. volclimax 1.208 / 1.188; elder atr2d5 1.155 / 1.152; elder atr6 1.235 / 1.178; ema13w 1.181 / 1.086. Every cell beats the control on the live model.
- Why xroc works: 5906 of 11961 live trades exit on ROC exhaustion (10-day ROC peaks above 15% and turns down, price above entry) at 93.7% win, PFnet ~395, 6.5-bar hold. Losses come from the 2.5 ATR resting stop (3464 trades, PFnet 0.005) and the band-floor stop (1089, PFnet 0.34). Time-outs barely break even (1.05).
- Surprise: the main.py replay ran close to the v2 sim this time (xroc 1.225 vs 1.242), unlike OB/VP in B-1416. The band cap still cuts PFnet in every cell (control band_floor_stop_hit PFnet 0.95), but much less for xroc (-0.016) than for the long-hold exits (ema13w -0.095), because xroc books profit before the long dips that the band floor cuts.
- Wired: new gap_and_go entries open under gap_and_go__exitexhaust__long__1d__atr2d5_hold30_rsbandfloor_trail6d0_xroc__v2 (initial stop entry - 2.5 x ATR14, trail 6 x ATR off the running max close, band floor applied at Kotak placement). Already open gap_and_go positions keep the old exit.
- Parity gap (disclosed): the replay fills exhaustion_exit at the signal bar's close. Live evaluates the same completed daily bar (B-419), but the swing pass runs after that close, so the real SELL fills at the NEXT session (about the 09:15 open). One overnight gap is not in the backtest. Measure it from the Kotak trade book on the first ~20 live xroc exits.
- Reuse: test an exhaustion (profit-taking) exit on every momentum entry before widening its stop. It turns the edge into short, high-win trades, and it holds up best under the live band-stop model.
- Profit-booking / exit takeaway: on gap_and_go, book profit when the 10-day ROC rolls over from a >15% peak instead of waiting for the 30-day hold. Win rate goes from 32% to 54%, PFnet from 1.10 to 1.21 and hold from 15.7 to 10.6 days, which turns capital over faster. The 2.5 ATR stop is still the main loss source, so check whether next-open exit fills keep the exhaustion edge before tightening anything.

### B-1438 (2026-10-30 IST): trailing swing stops re-placed at the trailed level after the 15:15 exchange cancel

- Mechanism: the exchange cancels every resting SL at 15:15 IST; the bot re-places swing SLs from 09:15 IST (per-tick retry, 5-min backfill), both through `_swing_stop_floored`. That used the row's stored INITIAL stop. The daily ratchet (`_sync_swing_resting_sl_to_strategy`) only moves rows that still have a live SL and runs once at the first in-session tick, so after the overnight cancel the trailed level was usually never restored: the real stop sat at the initial stop while the strategy's own exit was trailing higher.
- Fix: `_swing_trail_floor` (old B-1427 name kept as an alias) raises the re-place to `_swing_strategy_stop_level(tag, initial, ATR, running_max_close)` for every trailing long swing tag: minervini_vcp, livermore, primary_base, power_play, legacy order_block_delta / volume_profile_poc, swing_rerouted_orphan, minervini_vcp_be3r (breakeven at entry once the peak gained 3R) and the gap_and_go exitfamily cells. Only raises (max), skipped when the trail is at or above min(last completed close, live LTP), stored stop on missing data; Kotak band pre-clamp unchanged.
- Correction to the backlog premise: pl1d, chan_shape, island, brk20, swingminrr, gapfade, O'Neil, pattern cells, sector rotation, OB/VP exitinval, the 1h long cells and every short swing cell exit off a FROZEN stop, so their stored stop already is their strategy stop. Short swing stores no running-min close, so there is no buy-stop trail to mirror.
- Result: no backtest; this aligns the live resting stop with the stop the backtests already assumed (they rest the trailed level every day). Tests: tests/test_swing_trail_replace_b1438.py.
- Reuse: any stop that the exchange or broker can cancel must be re-placed from the strategy's CURRENT stop, never the entry-time stop; check every "re-place" path, not only the "move" path.
- Profit-booking / exit takeaway: on chandelier-trailed swing holdings, the trailed gain is only locked in if the trailed stop is resting every session; re-placing at the initial stop each morning silently gives back the whole trail on a gap-down day.

## B-1439 - chan_kalman live exit used replay masks on a live frame (2026-11-02 IST)
- What happened: RELIANCE.NS real short 3 @ Rs1217.50 at 09:18:55 IST (chan_kalman band_mr 15m z1.0 cell) was covered at 09:20:59 IST with reason flatten_1515. The paper book churned 19 chan short round trips in 40 minutes (net -Rs379 after the 0.8% cost model) for the same reason. SHANTIGOLD.NS (2026-10-16) had the same 27-minute "flatten".
- Mechanism: chan_flatten_masks marks the last bar of each day that ends by 15:15 as the cut bar. On a replay (full days) that is the 15:00/15:10 bar; on a LIVE partial-day frame it is whatever bar is last, so the exit function saw "cut" on every tick. Entry already used _chan_live_masks; the two manage functions did not.
- Fit to this system: the strategy itself was never tested live; every real chan_kalman trade so far was a 2-minute round trip paying ~0.8% cost for nothing. The fix makes live exits match the replay (state exit, stop, 40-bar hold, 15:10 flatten).
- Reuse: any replay helper that derives "end of day" from the frame's own last bar must be given synthetic/extended bars (or an explicit mask) when called on live data; grep every live caller of a replay function for defaulted mask/window arguments.
- Qty: RELIANCE 3 (B-1430 real-capital formula, risk 2%) and IOC 1 (swing formula 3, consistent with the stop-out-cluster 0.5x halving) - sizing behaved as coded.
- Profit-booking / exit takeaway: an exit that fires minutes after entry with a time-of-day reason is a bug signature, not a market event; check exit reason vs clock on every real round trip shorter than one bar of the strategy's own timeframe.
### B-1440 / B-1441 (2026-11-02 IST): entry-day SL is a hard floor at the Kotak chokepoint; SL type only Trail/Fixed

- Mechanism: WIPRO.NS (real swing row, tag swing_rerouted_orphan, entry Rs188.75 on 21-Oct; paper row macddiv 1h cell, initial stop Rs185.35, R Rs4.55). After the 15:15 IST exchange cancel on 30-Oct (stop then Rs192.89 from the LTP trail), the 02-Nov 09:15 IST backfill re-placed at the stale stored stop Rs175.12, which the band pre-clamp raised to Rs179.01. Four minutes later the LTP trail moved it to Rs194.11 (peak 198.66 - 1R), which was correct.
- Why it happened: the engine's floor and View 4's "entry-day SL" were two different definitions, and the B-1438 trail floor read the paper row's tag (not trailing) instead of the real row's orphan LTP trail. The band clamp only ever raises a long stop, so it was not the cause.
- Fix: one definition (`_real_entry_day_stop`, the most protective of the first entry-day Kotak SL, the strategy initial stop and the swing entry-stop record) is shown in View 4 and enforced in `kotak_real_orders` before every SL send (long, short, swing, swing short). If that floor is already through the market, the stop rests 0.5% inside the last price and a loud log is written, so the position is never left naked. The orphan re-place also uses its persisted LTP peak. View 4's SL type is now only Trail or Fixed, taken from each engine's real stop logic.
- Reuse: any "re-place after cancel" path must start from the best stop the position has already earned, and a UI number the owner reads as a guarantee must be the same function the engine enforces.
- Profit-booking / exit takeaway: a trailed stop protects profit only while it rests. Each morning's re-place must start at the higher of the entry-day stop and the trailed level, never at the entry-time stored stop. WIPRO rested about Rs14/share looser than its earned 192.89 for four minutes after the open.

### B-871 design (2026-11-02 IST): a short edge must exist on a universe that has an overnight short instrument

- Mechanism: brk20_min_rr short 1d (6 plain cells, pooled PFnet 1.66-3.95, OOS 1.72-9.72, cash 0.8%) has no instrument it can actually be held overnight with at Kotak. Cash NRML is rejected (B-967). Futures, puts and SLBM all need F&O-eligible stocks, and on those 210 names the signal is below 1.0 gross (B-1339). Full design: docs/SHORT_SWING_DESIGN.md.
- Fit: the cash short-swing path (tables, Upstash mirror, 5-min heal, SL-with-entry plus unwind) is built and correct, but stays paper-only for good on cash. A futures route is designed, not built: one lot risks about 7x the Rs 9.6k account at an ATR4 stop.
- What surprised: B-1339's F&O check was not like-for-like with the wired cells. It swept rr 1/2/3, so atr3_rr3d5/rr4 were never run on F&O names. Also, the cash run's JSON says period 730d while its IS/OOS split implies about 5y. Universe conclusions need the exact same cells and a verified period before they are final.
- Rolling MIS (re-short every morning) is not a substitute. It pays costs every day (about 12 x 0.8%) and throws away the overnight gaps a 1d short earns.
- Reuse next time: before designing any route for a short edge, intersect the edge's universe with the universe of the instrument (futures/options/SLB eligibility) and re-run the exact cells there. Check that first, then capital, then cost.
- Profit-booking / exit takeaway: a 1d short earns its PFnet by holding through gaps to a 3-4R target over about 12 days. Any route that forces a daily flatten or a 5-day option hold changes the exit and cannot inherit that PFnet.

## chan_shape 1d long main.py replay, run 38553284949 kept as a partial row (B-1265, 2026-11-02)
- **Result:** main.py replay (full NSE, cost 0.8%) best cell atr4d0_hold10 nonovl PFnet 0.907 (n 48019), the other 5 cells 0.73-0.86; the later run 40572999957 re-measured the same cell at 0.891 (n 48369). Registered as `chan_shape__mom_mr_mr__long__1d__atr4d0_hold10_rid38553284949__nonovl__v2` with pfgross/win/hold None (owed from artifact 11887209982, never zero-filled).
- **Lesson / reuse:** two runs of the same cell map to the same `_mr` tag, so a second run of the same cell needs a run-id param (`rid<run>`) to stay its own row; transcribe the full merge table into docs/backtest_data the day the run finishes, because the backlog row alone kept only one cell.
- **Profit-booking / exit takeaway:** as with cup cheat, timeouts are the only profitable exits; the rule stays below the floor at either hold, so no exit tweak rescues it.

## Option trailing SL above LTP: exit at market (B-1459, 2026-11-03)
- **Mechanism:** the option trail is max(previous trigger, peak x (1 - trail %)); when the premium has already fallen to or under that level (often after a feed-high spike between 30 s polls), a SELL SL cannot rest above LTP and Kotak/NSE refuse it. Before, the leg kept its older, lower stop (or none, then waited a grace window).
- **Decision:** the stop has effectively been hit, so `_sync_real_fo_option_sl` now exits at market (`trail_breached_exit`, reasoned order log). Refusals not caused by LTP (bad tick) still keep the live SL.
- **Fit / risk:** weekly options decay fast; holding under the trail adds theta and gap risk for no edge. Cost: a feed-high spike can trigger an exit the 30 s LTP would not; measure how often in live logs (event `trail_breached_exit`).
- **Owed:** an option trail replay comparing "keep old stop" and "exit at market" net PFnet (fo-options-blackscholes-backtest-research.yml does not model the feed-high trail yet).
- **Profit-booking / exit takeaway:** a trail that cannot rest is a hit stop: book it at market, never wait on a lower legacy stop.

## B-1463 wiring audit: viable is not the same as wired (2026-11-04)
- Mechanism: 2,755 registry tags clear PFnet > 1 but only ~310 were mapped to live engines. Most of the gap is research-harness evidence (not a replay calling main.py), so it cannot gate real money.
- Fit: of 570 candidates in families with live code, only 5 qualified (brk20_min_rr long 1d, main replay run 38185670883); the rest were research-only, a 0.3% cost model (live is 0.8%), or duplicate entry signals of a wired cell.
- Surprise: many "unwired viable" tags are IS/OOS splits, be1 breakeven twins or band-cap reruns of the same entry; counting tags overstates real new edges.
- Reuse: to grow the wired set, port the research detector into main.py with parity tests, then run the main-calling non-overlap replay (done for 11 O'Neil ext families, tags ..._srcmain__nonovl__v2).
- Profit-booking / exit takeaway: cascade looser-rr brk20 cells after the tighter one so they only add trades where the higher-PFnet cell stays silent; each keeps its own ATR stop and registry gate.

## B-1463 O'Neil ext families on main.py detectors, strict non-overlap (2026-11-04)
- Result: weekly (1w) beats daily by a wide margin. 1w atr3_h26 long: all 14 cells pooled PFnet 1.46-3.83 and OOS > 1 (runs 41847932950). 1d: 48 pooled > 1 but only 9 OOS > 1 (run 41847222200); daily edges fade in the recent 40% of history.
- Shorts (reciprocal mirror) fail on both candle sizes: daily all <= 1, weekly best 1.24 with OOS <= 1.05. O'Neil base patterns are long-side phenomena on NSE.
- Surprise: RS-rank strategies depend on the ranking population; a rank over the full universe is not the rank over NIFTY 200, so rsscreen was not wired until re-replayed on the live population.
- Reuse: always read the OOS segment tag before wiring; pooled PFnet alone admitted 39 daily cells that fade OOS.
- Profit-booking / exit takeaway: a frozen 3xATR stop with a long (26-week) hold is what carries the weekly edge; in a multi-cell cascade guard re-entry across ALL sibling cells, since each cell was replayed alone.

### B-1468 (2026-11-04 IST): O'Neil RS screen, wired once the RS population matched the live scan

- **Mechanism:** buy when a stock's 12-month return ranks in the top decile (RS >= 90), it is above its long average and within 5% of its 52-week high. The rank is relative, so who it is ranked against changes which stocks qualify.
- **Fit:** the live scan only sees the ~250-symbol swing watchlist. The first replay ranked RS across the full NSE universe, which the live bot cannot reproduce without fetching ~2,680 symbols every pass. Re-running with RS ranked inside the watchlist (rs_universe=n200) gave 1w atr3_h26 PFnet 3.18 (OOS 3.46, n 445) and 1d atr2_h40 PFnet 1.75 (OOS 1.09, n 487).
- **Surprise:** a 2y daily prefetch resamples to ~104 weeks, below the replay's 120-week eligibility rule, so the live weekly population uses a 100-week proxy. The residual mismatch is stocks listed 2.0-2.3 years ago.
- **Reuse:** any cross-sectional (relative) signal must be validated on the population the live path can actually rank, not the research universe.
- **Profit-booking / exit takeaway:** the daily cell's OOS edge (1.09) is thin next to the weekly one (3.46): the weekly cell holds longer and keeps far more of the trend, so it sits high in its cascade while the daily one is only a top-of-list daily filler.

## B-1467 chan_kalman v1 band, main.py replay (2026-11-05)
- Mechanism: Kalman adaptive mean on log close; long when the error drops below -2·sqrtQ, exit when price crosses back to the mean, stop entry - 4×ATR14, max hold 40 bars.
- Result (full NSE universe, run 41881365947, cost 0.8%): LONG 1d atr4 z2 Ve1e-3 PFnet 1.367, OOS 1.105, n 27,328, avg hold 6 bars, wired. Tighter stops fail (atr2.5 1.234/1.000, atr1.5 1.065/0.881). Every SHORT mirror fails (~0.84): fading strength does not pay on NSE daily bars.
- Surprise: the state exit carries the whole edge (PFnet 2.2 on 26k trades); every stop-out is a full loss. A wide stop lets the mean-reversion finish.
- Profit-booking / exit takeaway: on this mean-reversion family, book at the mean (state exit), not at a fixed target, and keep the stop wide (4×ATR); a tight stop turns a winning reversion into a stop-out.

## Minervini lab main-replay LONG (B-1467, 2026-11-05)
- Mechanism: real `main.minervini_vcp_entry_signal` (RS gate skipped) with 79 lab exit/filter variants ported into main.py, full universe 2053 symbols, 1d, max hold 60, cost 0.8%.
- Result: the plain base cell is breakeven (PFnet 1.000, OOS 0.691). Most exit variants lift pooled PFnet to 1.4-1.6 but collapse OOS (< 0.95): the in-sample edge came from the 2021-24 bull run.
- Only 3 cells hold OOS > 1 (early_bull_10_25_on, rs_blend_ge70_off, after_stopout_cluster_off), and all hold 30.6-37.5 bars on average, over the 30-bar wiring bar. Not wired.
- Reuse: for VCP the regime filter (early bull) and the after-stop-out cluster filter are the only things that survive OOS; a shorter max hold (h30/h40) on those three is the next cheap test to bring hold under 30.
- Profit-booking / exit takeaway: VCP winners need long holds; exits that cut them early (ma50 trail, breakeven after 1R) lose OOS, so book profit on time/regime, not tight trails.
- Short mirror (run 41888716565): only after_stopout_cluster_off passes (1.314 / OOS 1.573) and its IS is 0.555. That filter (and the long 2.934 cell) uses the lab's look-ahead cluster rule, so treat any stop-out-cluster number from scripts/minervini_lab.py as contaminated until re-run with the no-look-ahead `_nla_` variant (only trades exited before entry, matching the live `_swing_stopout_cluster`).
- Profit-booking / exit takeaway: a portfolio-state filter (recent stop-outs) must be built from trades already closed at entry time, or it books phantom profit.

## chan_kalman v1 band LONG 1h wired (B-1465, 2026-11-05)
- Same Kalman band rule as the wired 1d cell, on completed 1h bars in the swing engine's 1h long leg. Replay 41886040481: PFnet 1.083, IS 1.127, OOS 1.002 (n 1681), avg hold 8.2 bars. The OOS margin is razor-thin, so the registry gate will close it automatically if a later re-measure lands at or below 1.00.
- Exits: state_exit trades carry the edge (PFnet 2.67, 89% of trades); 4xATR stops are all losers. Same shape as 1d.
- Lesson: check the code before believing a backlog "no live path" note; the 1h long leg existed since B-984.
- Profit-booking / exit takeaway: book on the mean-reversion state exit; do not tighten the 4xATR stop (tighter stops failed on 1d).

## Minervini lab cells wired at h30/h40 (B-1469, 2026-11-05)
- Cutting max hold from 60 to 30/40 bars brought three VCP cells under the 30-bar wiring bar and lifted their OOS (early_bull h40 OOS 1.196 vs h60 1.138). Shorter holds did not hurt pooled PFnet (about 1.30).
- Exit = 8% hard stop (pct8_hard) + time exit; the trailing/MA exits that looked better pooled all failed OOS.
- Profit-booking / exit takeaway: for VCP breakouts, a fixed 8% stop plus a 30-40 bar time exit beats every trailing exit out of sample; book on time, not on a trail.

### 2026-11-05: chan_kalman v1 band intraday (B-1470), wiring check before wiring
- Mechanism: Kalman adaptive mean on close; enter against an err beyond z*sqrtQ, exit on the mean cross, stop 4xATR14, flat by 15:10 IST.
- Result (main.py replay, full NSE universe, 0.8% cost): 5m SHORT atr4 z2 1.730 / OOS 2.171 (n 992); 15m SHORT 1.348 / 1.586; 15m LONG z2 1.332 / 1.338 (n 268), z1 1.180 / 1.031 (n 3529).
- Surprise: the two SHORT cells were already live under the band_mr v2 tags (same signal, same atr/ve/z). The new replay is independent confirmation, not a new strategy to wire; a second tag on the same signal would only act as a fallback behind the first.
- Wired: the two 15m LONG cells (no 15m long scan existed), via the B-980 pattern (15m frame fetched from the 5m tick, 15m cells after every 5m cell).
- Reuse: before wiring a "new" replay row, grep the live cell dicts for the same (signal, atr, ve, z); the family name in the tag (band_srcmain vs band_mr) can differ while the live code is identical.
- Profit-booking / exit takeaway: the 15m long edge sits in the z2 band (fewer, stronger stretches); z1 trades 13x more often for a thinner OOS margin (1.03), so it is cascaded after z2.

### 2026-11-05: brk20_min_rr LONG 1h fails out of sample (B-1465)
- Pooled main replay PFnet up to 1.71 (n 1112), but every 1h long cell's OOS segment sits at 0.63-0.80; the IS half (up to 2.10) carries the whole pooled number.
- Not wired. Lesson: a pooled PFnet far above 1 on 1h with an IS/OOS split this lopsided is regime-specific, not an edge; always read the _oos row before wiring.
- Profit-booking / exit takeaway: the wider rr4 targets are what inflated IS; in OOS they are rarely reached, so the breakout's pay-off depended on a trending sample.

### 2026-11-05: wiring bar moved to pooled PFnet (B-1471, user instruction)
- Rule now: pooled full-universe PFnet > 1.00 decides wiring; the OOS segment is recorded and shown, never a veto. Other bars unchanged (n >= 30, avg hold <= 30 bars daily, live path, no look-ahead, n200 population rule).
- Minervini lab: 25 more cells wired (VCP + one filter each, plus the unfiltered VCP with an MA50 trail last). Together the on/off filter pairs cover nearly every VCP signal, so the live book now trades almost every VCP breakout; the cascade only decides which cell's hold/exit applies. Their OOS segments are mostly 0.6-0.9 (the recent period lost money for most of them), which is the risk accepted with this rule.
- Watch: if the live Kotak trade book for these tags runs below breakeven over a meaningful sample, that is the OOS warning coming true; record it here and re-decide.
- Profit-booking / exit takeaway: the unfiltered VCP entry is best with an MA50 close trail (1.445 pooled), well above the 8% hard stop (1.246); trend-following exits suit VCP breakouts.

## B-1472 (2026-11-05): pooled PFnet from in-sample + symbol-holdout halves
- Mechanism: pattern_validate / combo_validate re-ran each cell on 417-425 non-NIFTY-200 stocks, a disjoint SYMBOL holdout, not a later period. Two disjoint trade sets pool exactly: per side L = n*avg_net/(PF-1), W = PF*L; pooled PF = sum W / sum L. A side with PF ~1.00 (or PF and avg of opposite sign) cannot be decomposed and is skipped, not guessed.
- Fit: user rule 2026-11-05, pooled PFnet > 1.00 decides wiring and OOS never vetoes. Registered as new `_pool` variant tags; old rows keep their holdout-gated numbers (data intact).
- Result: 84 pooled tags, all > 1.00 (e.g. gap__runaway_pool 1.166 n3474 where the holdout alone was 1.019). 22 cells newly wired, 62 renamed to their pooled twin.
- Surprise: the generator rename exposed a latent orphan risk. The pattern exit only managed tags in the current entry list, so any regen that dropped a tag would leave open positions without their pattern exit. Fixed with a persistent exit_only list.
- Caution: the combo in-sample half is best-of-thousands, so a combo pooled number still carries selection inflation; the 5,331 combos with no holdout run stay unregistered.
- Profit-booking / exit takeaway: renaming or re-ranking live cells must never drop an exit path; exits are keyed by the tag a position was opened under, forever.

## B-1478 (2026-11-05): re-test everything, not only what is wired
- Mechanism: the 6-month re-test cycle covers every registry tag, including failed and never-wired ones.
- Why: edges drift with the market. A 0.99 PFnet cell can cross 1.00 on fresh data; a wired 1.05 can decay. Only re-testing the whole pool catches both.
- Profit-booking / exit takeaway: wiring is re-derived from the newest result each cycle, so profit comes from what works now, not what worked once.

## B-1481 (2026-11-05): an empty order book is not an unreadable one
- What broke: a safety rule added the day before (never place an SL when the order book cannot be read) met Kotak's start-of-day reply for an empty book and blocked every 09:15 IST SL for ~2 minutes.
- Lesson: every "refuse when unsure" guard must be tested against the first minute of the trading day, when the book is legitimately empty and no SL can already exist (exchange purge at 15:15 IST).
- Profit-booking / exit takeaway: at the open, protection beats duplicate-avoidance; a duplicate SL is rejected harmlessly by RMS, a naked holding is real money at risk.

## B-1482 (2026-11-05): a chandelier trail is wide by design; frozen-stop cells never trail
- What we checked: the 6xATR order-block chandelier sits ~20 points under the peak close on BANKINDIA/UNIONBANK, below the band-floored resting SL, so "not trailing yet" is correct, not a bug. macddiv 1h and gap_runaway cells were validated with frozen stops plus a max hold, so they never trail.
- Open question: frozen stops give back open gains (IOC +7.8%, UNIONBANK +7.4% today). A trailing or breakeven variant is a separate tag to backtest, never a live change without the pooled-PFnet evidence.
- Profit-booking / exit takeaway: check each position against ITS OWN strategy's stop rule (main._SWING_SL_RULES) before calling a stop stuck; then test whether a trail would have booked more, as its own variant.

## B-1472 b: O'Neil cup-family patterns, main.py replay (2026-11-05 IST)
- Mechanism: cup with handle, cup without handle, saucer, double bottom; 1d breakout above the pivot, chase limit 5% or 10% on the next open, ATR or percent stop, max hold 20/40/60 bars, optional RS >= 80 or 1st/2nd-base (qual1) filter. Run 41958449455: 1,296 cells, full NSE, cost 0.8%, signals from main.py.
- Result: cup_handle is the strongest (best non-rs80 1.541 n1396, robust ex-top5 1.425); cup_nohandle 1.269 n1009; saucer only 1.134 n131 and collapses to 0.796 without its top 5 trades; double_bottom fails everywhere except thin rs80 cells.
- Surprise: the 1st/2nd-base filter (qual1) beat plain cells, and long holds (h60) beat short ones, so the edge is from riding the post-breakout trend, not a quick pop. Stops lose (about -7%), timeouts win (about +7%), the same shape as other swing breakouts here.
- Fit: frozen ATR stop + max hold maps onto the existing ONEIL_DAILY_CELLS path with no new machinery; the chase test needs today's open, so live uses the live price and fails closed without one.
- Reuse: when a replay ranks a cross-sectional factor (RS) per shard, do not wire those cells; re-run with the live population rank first (B-1483).
- Profit-booking / exit takeaway: these winners come from time in the trade (timeout exits), so do not add a tight trail or early target to them without a sweep; watch saucer live, since its edge rests on a few big winners.


## B-1484: trailing-SL overlay on every wired fixed-stop strategy (2026-11-05 IST)
- Mechanism: the user's rule: try trailing stops on each fixed-stop cell; keep the trail only if it beats the fixed stop. Six rules, all in R units of the cell's own initial stop so ATR stops and the 8% Minervini stop are compared alike: chandelier peak close - 1R / 1.5R / 2R / 3R, and net breakeven (entry + 0.8%) after +1R or +2R.
- Fit: it is layered on the live resting-stop model (band floor), and the peak is the previous session's close, the same daily running max the live swing engine stores, so a winning rule maps onto the existing trail path with no new machinery. A trail only ever raises the stop.
- Design note: one shared hook (swing_bandcap.resting_stop_exit) serves 14 families' real main.py replays, so a new stop idea is a one-file change plus one argument per call site. FIFO matters: an earlier trail exit frees the slot, so n can rise against the fixed row.
- Prior evidence to weigh: the O'Neil cup family, gap_and_go and the swing breakouts here earn from timeout exits, not stops (B-1472), so tight trails (1R) may cut winners; wider trails (2-3R) or breakeven are the likely candidates. Results pending (run to be recorded in B-1484).
- Profit-booking / exit takeaway: test a trail before believing it books more profit; a trail that converts timeout winners into early exits can lower PFnet even though it feels safer.

## B-1480: Elder batch 3 (channel pivot-trendline break, oscillator divergence and reversal), main.py replay (2026-11-05 IST)
- Result: run 41966382565, 30 cells, full NSE, cost 0.8%, signals from the real main.py ports: best pooled PFnet 0.961 (chan pivot_tl_break atr3 w3, n52282); the earlier 2.4 PFnet osc divergence cells (run 38211452647, NIFTY200+ETF, pre bad-bar guard) collapsed to 0.92-0.95. Nothing wired; all 30 registered research-only.
- Surprise: gross PF sits near 1.0-1.05, so the 0.8% cost alone sinks them; stops lose, timeouts win (PFnet ~30 on max-hold exits), the same shape as other swing cells here.
- Reuse: a huge research PFnet on a narrow universe before the bad-bar guard is not evidence; always re-run on the full universe with main.py ports before believing it.
- Profit-booking / exit takeaway: the timeout winners suggest a longer hold or a wider stop is the only lever worth a sweep here; a tight trail would cut the only profitable exit.
- B-1484 b addendum (user 11:55 IST): the trail set now includes 0.5R steps and LTP-based trails (peak of completed-bar highs - N x R, the per-tick LTP view the live orphan trail uses). Expect LTP trails to stop out sooner than close trails at the same N because highs run above closes; that only pays if winners give back a lot after an intraday peak.
- Profit-booking / exit takeaway: compare LTP and close trails at the same R before choosing; a tighter-feeling LTP trail is not automatically more profit.

## 2026-11-05: a no-trade day (B-1488)
- On 2026-11-05 the bot made 0 real-entry attempts in every category. Scans ran normally; only the sub-floor chan_shape mom_mr 1d cells fired, and the PFnet gate blocked all 342 of those triggers.
- Lesson: on a quiet day, read /entry-funnel first. "no setup fired" vs "blocked" vs "failed" separates a market with no setups from a bug in seconds.
- Profit-booking / exit takeaway: a day without entries is the PFnet gate doing its job, not missed profit. Do not loosen the floor because of a quiet day.

### 2026-11-05: how often does a no-entry day happen? (B-1489)
- The git order journal (docs/real_order_log.json) shows real entries on only 3 of the last 10 trading days, so a no-entry day is the usual case for a floor-gated system, not a fault.
- Per-tag fire counts reset daily and are not journaled, so a quiet-day comparison across days needs the git order journal, not /entry-funnel.
- Profit-booking / exit takeaway: no entry also means no cost. Never loosen the PFnet floor to "get a trade in" on a quiet day.

## 2026-11-06: trailing SL vs fixed SL on wired swing cells (B-1484, run 41978699531)

- **Mechanism:** 11 trail overlays (close chandelier 0.5/1/1.5/2/3R, peak-LTP = highest completed-bar high - 0.5/1/1.5/2R, net breakeven at 1R/2R) layered on the live resting-stop model (10% band floor, intraday trigger, fill at the worse of open and trigger), full NSE, 0.8% cost, compared with the SAME run's live fixed row.
- **Result:** peak-LTP 0.5R is the only rule that wins broadly: gap_and_go 1.101 -> 1.463 with hold cut 15.6 -> 3.7 days; brk20 long/short atr4_rr4, island gap05, gap runaway all up; vcp_gate rr4 and starc fade best at 1.5R. Close-based chandelier and breakeven ratchets mostly LOSE, often badly (island px20 1.797 -> 1.228, brk20 short rr3d5 3.924 -> 3.121): they exit on noise after the move has already given back.
- **Surprise:** the tight trail lifts PFnet AND trade count (gap_and_go n 11611 -> 12779) because faster exits free the non-overlap slot; the cells whose fixed edge comes from 30-day max-hold survivors (brk20 short rr3/rr3d5, island px20/none) are hurt by any trail.
- **Reuse:** test peak-LTP trails first on any momentum/breakout cell; never assume a trail helps a cell whose winners are long-hold timeouts; check the exit-reason split (max_hold_timeout PFnet) before choosing.
- **Profit-booking / exit takeaway:** on gap/breakout momentum swings, lock profit 0.5R under the best completed-day high; it books gains about 4x faster and earns more per trade than holding to the fixed stop, but leave max-hold-driven cells on their fixed stop.

## 2026-11-06: Yahoo leaves the latest daily close null after the session (B-1489 part 2 / B-1490)

- **Mechanism:** Yahoo's v8 chart (1d) returned the 11-05 bar with open/high/low but close=null at 01:31 IST the next day, while meta.regularMarketPrice had the true close (RELIANCE 1313.4). `data_fetch.fetch_ohlc` drops NaN-close rows, so any after-hours read sees yesterday as the last bar.
- **Fit:** entries run in-session, where the forming bar normally has a close, so live entries are probably unaffected; research or any after-hours scan is silently one day stale. To confirm in-session on 11-06.
- **Profit-booking / exit takeaway:** a stale last bar delays a trail ratchet or exit by a day; any exit or trail logic that reads daily bars after the close must use a filled last close, not drop the bar.

## 2026-11-06: one tag, many rows: a gate that keys on the base tag lets the last row win (B-1484)

- **What broke:** adding 11 trail-overlay rows per tag to a band_cap run made `_bandcap_live_failed_tags` take whichever row came last for each base tag, so a losing trail variant could close a winning fixed cell's real-money gate. Caught by the island wiring test before push.
- **Reuse:** any reader of a results file that keys on `tag` must filter to the row variant it means (`band_cap == "live"`), never assume one row per tag.
- **Profit-booking / exit takeaway:** a research row must never silently decide whether a live cell trades; check every derived gate after adding a new row type to a results file.

## 2026-11-06: gap_and_go back to its original exit plus a peak-LTP 0.5R trail (B-1491)

- **Decision (user "Switch"):** the xroc exhaustion exit (1.209) had replaced the legacy exit (1.101 live fixed); the trail flips the ranking: legacy exit + peak-LTP 0.5R = 1.463 with a 3.7-day hold, beating both.
- **Lesson:** compare a new exit against the old exit WITH each candidate trail before retiring the old one; an exit judged only on its fixed-stop form can lose its best variant.
- **Profit-booking / exit takeaway:** gap_and_go books profit 0.5R under the best completed-day high; expect more, shorter trades (about 4 days) rather than 15-day holds.

## 2026-11-06: balance is a rejection reason of its own (B-1492)

- **What:** an entry the Kotak balance cannot fund (Net below one share, F&O margin check, Kotak funds rejection) was hidden inside the generic "sized to 0" row, so a profitable signal lost for lack of cash looked like a sizing quirk. It is now counted beside the viability rejections on View 4, with the Net and the cheapest rejected 1-share price.
- **Why it matters for profit:** a non-zero low-balance count means viable signals are being turned away for cash, not for edge; the fix there is funding or capital allocation, not loosening the PFnet gate.
- **Profit-booking / exit takeaway:** unchanged exits; capital tied in slow holds directly costs new viable entries, which strengthens the faster-turnover preference.

## 2026-11-06: O'Neil cells under the trailing-stop thumb rule (B-1493/B-1494/B-1495)

- **Result (run 42025478119):** on 17 O'Neil weekly-signal cells, a trail beats the fixed stop on only one, shakeout plus3 pm1 with a peak-LTP 0.5R trail: PFnet 3.181 vs 2.979, and the hold falls from about 83 bars to 20. Every other cell loses with any trail, by 0.03 to 0.53 PFnet; the chandelier 3R trail is the least bad, the tight trails are the worst.
- **Why:** O'Neil base breakouts pay through long runs, so an early trail cuts the winners. The shakeout pattern is a sharp reclaim that pays fast, so locking 0.5R under the peak keeps the edge and frees capital four times faster.
- **Surprise:** three cells produced zero trades in this replay (leaders, rsline, rsscreen); that is a harness gap, not a result.
- **Profit-booking / exit takeaway:** trail the fast-reversal setups (shakeout, gap_and_go, brk20) and keep fixed stops on slow base breakouts; never assume a trail helps.
- B-1493 wired 2026-11-06 IST (user "Deploy 1493"): oneil_shakeout plus3 pm1 now trails at peak-LTP 0.5R off the highest completed daily high; the 1w entry, 3xATR initial stop and 26-week max hold are unchanged. Profit-booking / exit takeaway: on a shakeout (a quick reclaim after a flush) the edge is front-loaded, so a tight 0.5R trail books it in ~4 weeks instead of ~17 and lifts PFnet 2.98 -> 3.18; slow base breakouts keep the fixed stop.

## 2026-11-06: a once-a-day SL ratchet lagged the trail it serves (B-1496, IOC)
- What: IOC (gap runaway, peak-LTP 0.5R trail) sat with Kotak SL Rs136.38 while its trail said Rs141.66. The ratchet ran at 09:15, but the trail peak only takes yesterday's completed bar when the swing scan walks it later, so the 09:15 ratchet used a stale peak and nothing re-ran it.
- Fix: re-run the ratchet after every finished swing scan pass (raise-only, place-new-then-cancel-old).
- Lesson: any stop that depends on state computed by another pass must be re-synced when that pass finishes, not on a fixed clock.
- Profit-booking / exit takeaway: a lagging trail gives back profit for free. IOC would have kept Rs5.28/share less of its gain on a stop-out, which is most of its Rs8.49 open profit.

## 2026-11-06: fixed vs trailing stop is decided by return per day (user rule, B-1498)
- Rule: same strategy, fixed vs trail -> higher (avg net % per trade / avg trading days held) wins; wiring bars still apply.
- O'Neil 1w run 42025478119: shakeout pm1's 0.5R trail wins clearly (0.580 %/day vs 0.213 fixed). On every other O'Neil setup the fixed stop has the higher return per day (e.g. trendline 0.119 fixed vs 0.107 best trail; newhigh 0.081 vs 0.079), because trails cut the long runs that carry these base breakouts.
- Profit-booking / exit takeaway: a trail that books a smaller gain much sooner can still win on return per day (shakeout: 11.4% in 20d beats 17.7% in 83d); judge exits on money per day held, not per trade.
- 2026-11-06 IST addendum: the user ruled PFnet > 1 is the ONLY wiring condition (trade count and hold belong to the View 1 variable definition), so O'Neil hft now trails at 0.5R too (0.778 vs 0.080 %/day on n=25). Profit-booking / exit takeaway: on a high-tight-flag breakout the move is fast; book it with a tight trail in ~3 weeks rather than wait 13.

## 2026-11-06: wire every PFnet > 1 variant; viability controls money (user rule, B-1500)
- Wiring = pooled PFnet > 1.00 only, for every variant that can enter; the View 1 viability definition decides real money. Collisions on one symbol go in return-per-day order, falling through to the next variant when one is gated out.
- Profit-booking / exit takeaway: keeping both the fixed and the trailed variant wired means the faster-booking one takes the entry when it is allowed, and the other still catches the trade if the viability definition rejects the first.

- 2026-11-06 IST build note (B-1500, swing long daily pass): 28 live long tags now carry 234 wired exit variants (fixed, peak-HIGH, peak-CLOSE chandelier, breakeven), each with same-run and registry PFnet > 1.00, ordered by return per day; the first variant whose own registry tag passes the viability definition owns the entry and is stored per position. Best-by-return-per-day is the fixed stop on 16 tags (most O'Neil base breakouts, swingminrr base/rr2/rr3, island none/px20), a trail on 12; the only change versus the B-1486/B-1499 picks for a new entry is STARC (peak-LTP 1R, 0.0849 %/day, over 1.5R, 0.0840). Lesson: a trail's arithmetic must match the replay bar for bar (the chandelier peaks on completed CLOSES, the LTP trail on completed HIGHS, the entry bar never counts), so it is tested against `swing_bandcap.trailed_stop` directly, not re-derived. Profit-booking / exit takeaway: let the variant with the most money per day held book the trade when it is allowed, and keep the slower variants as fallbacks so a viability rule that rejects the fast one does not cost the trade.

### B-1496 verification (2026-11-06 IST): post-deploy ratchet timing

Deployed 14:12 IST; IOC's resting SL stayed at Rs136.38 until the first full swing scan pass ended (14:31:36 IST), then the ratchet moved it to the trail level Rs141.66 (Kotak = strategy). The ratchet keys off the whole pass finishing, and the 1h legs at the end of the pass take ~13 min, so a stop can lag its trail by ~20 min after a restart (B-1506). View 4's "SL updates today" counter missed the trailed replace (B-1505). Profit-booking / exit takeaway: a trail only protects profit once it is resting at Kotak; raise the resting stop as soon as the peak is known, not at the end of unrelated scan work.

### B-1507 (2026-11-06 IST): 3 days with no real entry - capital starvation hidden by a silent paper-size drop
- Mechanism: the swing paper row is the gateway to the real order. Paper sizing subtracted ~Rs4k of paper-only positions (never at Kotak) from Kotak's free Net (Rs5.9k), so 1% risk = Rs19 and qty floored to 0; callers `break` on qty 0 with no log, so nothing reached the real path or any log for 3 days.
- Second gate: the 25% sector cap used free Net as its base, so it tightened as positions opened (Rs1,476 cap on a Rs9.3k account).
- Fix: paper gateway floor 1 share; real size still from Kotak Net (B-1387) with a logged skip; cap base = free Net + open swing cost.
- Reuse: any percentage cap must use the whole account (free + deployed), never free cash; any `qty <= 0` drop on a fired signal must log a reason.
- Profit-booking / exit takeaway: with a ~Rs9k account fully in 6 swings, new entries depend on exits freeing cash; small accounts need a stated 1-share policy (B-1508) or every 6xATR-stop signal sizes to zero.

### B-1509 (2026-11-06 IST): small-account entry rules and the three reject flags
- 1-share real minimum when one share's stop loss <= 1% of free Kotak cash (Rs59 at Net Rs5,904); most 6xATR stops on Rs100-400 stocks fit, Rs1,000+ names with wide stops still reject as money.
- Every non-entry is one of viability / money / other, counted in /entry-funnel reject_flags; a zero-entry day writes a durable no_entry_day row.
- Profit-booking / exit takeaway: on a ~Rs9k account, one share per signal keeps the strategies trading live (real evidence) at a per-trade risk of at most 1% of free cash; exits that free cash matter as much as entries.

### B-1495a (2026-11-07 IST): a replay that is missing a live input reports n=0, not a bad result
- O'Neil leaders firsthigh, rsline newhigh and rsscreen top had n=0 in band_cap run 42025478119 only because the replay did not pass the ^NSEI index, the RS-rank population or the symbol, which the live scan has. With them (run 42232093739, full NSE): n=1363 / 2573 / 247, best pooled PFnet 3.730 / 1.514 / 2.557, every variant > 1.00.
- n=0 on a registered strategy means "the replay cannot see it", never "it does not trade": check the inputs before reading any metric.
- Ops: 8 shards x 2,667 symbols x 12 exit modes ran past the 340-min job timeout and lost every killed shard's output. 24 shards finish in 2-4 h each.
- Profit-booking / exit takeaway: rsscreen's best exit is breakeven-at-2R (trailbe2r); leaders and rsline do best on the plain resting stop. Exit variants stay in return-per-day order per tag, never one exit style for the whole family.

## B-1511 Muhurat special session (2026-11-07 IST)

- **Mechanism:** NSE's Diwali Muhurat session runs on Sunday 2026-11-08, 14:20-15:30 IST (closing-auction stocks stop at 15:15). Trades in it are real and settle normally. The bot had about 17 bare `weekday() >= 5` gates, so it would have sat out the session and left overnight holdings without a resting SL for that hour.
- **Fix:** one table, `NSE_SPECIAL_SESSIONS`, feeds every session gate. The user chose full trading: entries, exits and SL protection.
- **Fit / caveat:** no strategy here has been backtested on a 70-minute evening session.
  - Indicators reading "today's bars" see only the Muhurat bars.
  - Daily-bar swing signals see Friday's completed bar.
  - Expect thin liquidity and wide spreads. The 0.8% cost model understates slippage there.
- **Reuse:** any future special session (Muhurat 2027, a Budget-day Saturday) is one row in `NSE_SPECIAL_SESSIONS`. Never use bare weekday checks in new gates; use `_nse_closed_day`.
- **Profit-booking / exit takeaway:** stops must rest from the session's own open, not 09:15. The 15:15 IST CAS purge and the no-SL-after-15:15 rule still apply. Review Muhurat fills in the Kotak trade book on Monday before trusting any result from the session.

## B-1513 / B-1514 multiple viability slots and a rolling 24 h reject view (2026-11-09 IST)

- **Mechanism:** the View 1 viability definition is now an ordered list of named rule slots (PFnet range, min trades, max avg hold each). Real money may enter a strategy when ANY enabled slot admits it; the first admitting slot is stamped on the entry. View 4 shows rejects and placements over a rolling 24 h window that survives restarts.
- **Fit for this system:** different edges need different gates. A short-hold, high-PFnet intraday cell and a long-hold swing cell with a huge sample cannot share one max-hold or min-trades threshold without either blocking one or loosening the other. Slots let each class of strategy keep its own tight bar. The PFnet floor for wiring, SL on every trade and the ALL TRADING switch are unchanged.
- **Result:** no backtest (infrastructure). Measurement now exists: per slot, View 4 shows real entries admitted today and which factor rejected the rest, so each slot can be judged on its own live outcome.
- **What surprised or broke:** the old day-keyed counters reset at IST midnight and on restart, so a reject pattern seen in the evening was gone by morning. A slot whose label is its definition cannot be "renamed" in place without erasing it, so rename is refused for slot entries.
- **Reuse:** before loosening a single global threshold to admit one strategy, add a narrow slot for that strategy class instead. Check the slot's "placed" vs the Kotak trade book after a week before keeping it.
- **Profit-booking / exit takeaway:** judge each slot by the net P&L of the entries it admitted (Kotak trade book, joined on the `viability_slot=` stamp). Disable a slot whose admitted trades lose money after costs instead of tightening every other slot.
## B-1512 Market-open event and the closed-market trigger queue (2026-11-09 IST)

- **Mechanism:** on 2026-11-09 the swing first pass fired 109 swing + 2 buy triggers before 09:15 IST and every real entry logged `skipped_market_closed`. Those triggers now wait in `pending_open_triggers` (Upstash-mirrored). A market-open event per segment per session (calendar window, or live ticks proving trades) first runs the Kotak-first protection pass for every holding, then replays the queue through the swing engine's own entry function, then writes a durable `market_open_event` row.
- **Tick evidence:** Kotak sends a snapshot on every subscribe, even when closed, so a tick is never proof by itself. Proof = 2+ symbols printing a new trade (volume up or trade time advanced) within 120 s, both prints dated today IST and fresh. The pre-open first print (baseline = yesterday) never counts. Ticks open the gates only on a day the calendar does not know as a regular session, so unlisted Muhurat / Budget Saturday sessions work without a code change.
- **Fit:** every queued trigger is re-validated fresh at the open (PFnet / View 1 viability, sector cap, money, duplicates, live price within 2% of the signal, stop still below the price). A gap through the stop or beyond tolerance is dropped with a logged reason, never chased. No entry ever opens without its SL (the engine attaches it as usual). No new kill switch.
- **Reuse:** any new engine that can skip on "market closed" adds one replayer to `_OPEN_TRIGGER_REPLAYERS`. Never `return` on a closed market without queuing or logging.
- **Profit-booking / exit takeaway:** pre-open signals were the day's biggest lost opportunity. Replaying them at the open keeps the edge, but only within 2% of the signal price: an opening gap is the market already taking that profit, and chasing it lowers the expected return per trade. Protection runs before any new entry, so overnight holdings are never left naked while the bot buys.

## Sizing decision (2026-11-09 21:30 IST, user: "Leave as it is")
- Real size stays at 1% risk of half of Kotak free Net (CAPITAL_TRANCHES=2), with the 1-share floor. On a ~Rs5,900 free balance that means 1 share on most setups (PNB: Rs29.5 / Rs17.63 per share = 1.7, rounded down to 1).
- Not adopted: 2% risk, or 1 tranche.
- **Profit-booking / exit takeaway:** with 1-share lots, the 0.8% round-trip cost dominates small winners. Judge strategies on net PFnet, never gross, until the account grows.

## B-1515 / B-1516 one-share sizing check and order rows lost to a restart (2026-11-09 IST)

- **Mechanism (B-1515):** ZYDUSLIFE (minervini_vcp_livermore) bought 1 share at 12:19:43 IST, @Rs1,207.50, resting stop Rs1,123.70 (Rs83.80 at risk). The 1-share floor compares that with 1% of Kotak's FRESH Net at the decision. Net was Rs7,405.33 until 12:17 IST (11 refusals, limit Rs74.05), then Rs9,239.93 once three max-hold exits freed cash (limit Rs92.40), so the entry was correct.
- **Fit:** the sizing stop is the strategy stop. Every later adjustment (entry-day floor, band floor, stop-below-price) only raises a long stop, so the sized risk always bounds the resting risk. The confirmed entry row now logs the basis (stop, Rs at risk, Net, limit). A post-fill check flags slippage that pushes risk over the limit.
- **Mechanism (B-1516):** a failed boot restore of the git-tier order log was never retried, so the log was not pushed for two days. A restart then wiped the morning's rows, and 20 bot orders were reported as UNLOGGED. The fix retries the restore every minute. A late restore merges on content. If the restore stays down for 5 min, the log is pushed anyway (append-only).
- **What surprised:** the "Net ~Rs5,900" in the question was stale. Kotak Net moves within minutes as exits settle, so a sizing audit must read the Net logged at the decision, never a remembered figure. One unretried startup step stopped a durability mirror for 48 h, and nothing alarmed, because the push function returned False without logging.
- **Reuse:** every durability push gets a retry path for its restore and a visible health flag, never a silent `return False`. Every real-sizing decision logs the numbers it used.
- **Profit-booking / exit takeaway:** cash freed by exits (IRCTC/RECLTD/SAIL max-hold sells) raises the 1-share risk limit within minutes, so the next fired signal can enter at a wider stop. That is intended, but it means wider-stop 1-share entries cluster right after exits. Watch those entries' net P&L in the Kotak trade book before changing REAL_ONE_SHARE_RISK_PCT.


## B-1517 - sector cap charged the paper size, not the real order (2026-11-09)
- The swing sector cap (25% of whole account per sector) was evaluated before real sizing, using the paper qty x paper price. Paper qty is sized off paper capital, so a 1-share real BOSCHLTD order was charged ~Rs52,603 and could be refused as over the cap.
- Fix: check the cap after real sizing on real qty x live price. Open-position exposure already came from real_positions_swing (real qty).
- Lesson: every real-money gate must measure the real order, never the paper mirror; audit other gates for paper-qty inputs.
- Profit-booking / exit takeaway: none for exits; on entries, false sector blocks cost real trades with no risk benefit, so gates must price the actual order.

## B-1518 - every engine reads today's real NSE session, not fixed 09:15-15:30 (2026-11-09)
- Swing signals use the previous session's completed daily bar; that session may be a Friday, a Muhurat Sunday or the day before a holiday. Today's bar counts only after today's session has closed (a pre-open/partial Yahoo bar is never treated as complete).
- Intraday engines take the session's own open, close and square-off (Muhurat 14:20 open, 15:14 square-off). When only live ticks prove the market is open (no calendar close), no new intraday position is opened, because it could not be squared off before an unknown close; protection and exits keep running.
- Lesson: session hours are data per day (special sessions, holidays), never constants in engine code.
- Profit-booking / exit takeaway: an intraday position must always have a known square-off time before entry; on special sessions the square-off moves with the session close.

## B-1519 - no sector cap for intraday (user decision, 2026-11-09)
- The 25%-of-account sector cap stays a swing-long rule only; intraday buy/short and options get none (user: "No sector cap for intra day"). Intraday positions are flat by 15:14 IST, so overnight sector concentration does not build up.
- Profit-booking / exit takeaway: intraday concentration risk is bounded by the same-day square-off and the per-trade 1% stop, not by a sector cap.
## Live stop-loss correctness audit, 3-9 Nov 2026 (B-1438, B-1440, B-1441, B-1459, B-1482)

- Entry-day floor holds live: no SL sent below a position's entry-day stop from 3 to 9 Nov (WIPRO 194.11 >= 185.35; IRCTC 440.21 raised to the 440.25 floor). Trails only rose (IOC 136.38 -> 143.43, TATASTEEL, COLPAL, COCHINSHIP, ZYDUSLIFE, PNB).
- A stop that sits under the lower circuit band rests at the band floor, which moves with each day's previous close (UNIONBANK 169.71 then 168.80). That is exchange-forced and still above the strategy stop; it is not ratcheted, because a higher artifact would exit tighter than the validated strategy.
- A peak-LTP trail can sit close to the opening price after a weekend. On 9 Nov IOC rested no SL for ~11 minutes after 09:15 IST while every other holding was protected; the cause could not be proven because the morning log rows were lost (B-1516). Open as B-1520 (P0).
- Trail backtests on frozen-stop cells (B-1484 run 41978699531): only peak-LTP 0.5R on gap runaway beat the fixed stop (1.160 -> 1.236, hold 17.4 -> 7.7 days); every macddiv 1h trail lost and the 1h cells are below 1.00 under the live resting-stop model.
- Options: when the premium is already at or under the intended trail, exit at market (B-1459). That matches how every trail replay fills, so keeping an older, lower stop would be the untested choice.
- Profit-booking / exit takeaway: a tight peak-LTP trail books profit sooner and shortens the hold on runaway-gap cells, but near the open it must still rest a placeable stop (or exit) immediately, never leave the holding naked while waiting for the price to move away from the trail.
## B-1439 / B-1447 / B-1477 / B-1489 / B-1451 / B-1456 - Group C investigations (2026-11-09)
- RELIANCE 02-Nov short closed 2 minutes after entry by a replay-mask bug (fixed cf3c1c76); IOC qty 1 matches Kotak holdings. New 09-Nov real entries (ZYDUSLIFE, PNB) had their stops ratcheted to near entry within minutes (B-1523), so the trade risked much less than it was sized for and can be stopped out by noise before it works.
- Memory: yfinance's curl_cffi Session holds one Curl handle per THREAD; a fresh thread pool per tick/poll rebuilt handles and TLS sessions every 30 s. Reuse long-lived pools for any network fetch fan-out.
- Charges: Kotak's delivery charges are not in the API; STT appears rounded per contract note (to verify with Kotak lines), so per-trade statutory estimates can over-charge small delivery trades by ~0.1% of value. Small-ticket delivery trades are where rounding matters most.
- SLBM is not reachable via the Neo trade API (no SLB segment/product), so overnight cash shorts stay F&O-only.
- Zero-entry days are normal for this system (3 of 10 days had real entries); diagnose them from the git-tier signal_shadow_log, not memory.
- Profit-booking / exit takeaway: a stop tightened to near entry on the entry day turns a swing trade into a scalp; check that live trail timing matches the backtested exit before trusting live win rates.

## B-1466 / B-1472 / B-1427 / B-1494 / B-1455 / B-1479 / B-1486 - registry evidence hygiene (2026-11-09)
- B-1466: a live tag must gate on the replay that called the real main.py functions when one exists. The swingminrr VCP tags now map to their `_mr` rows (run 38318986997: rr4 2.845 n51, rr3 2.295 n110, rr2 1.589 n327, base 1.351 n2404); the research-sim rows (2.698/2.062/1.263/1.155) stay registered. The main.py replay was HIGHER than the sim here, unlike B-1416 where the sim ran 0.1-0.18 above.
- B-1472: OOS vetoes hide in registry loaders, not only in wiring code. Audit found the Elder dirsys13 loader headlining the OOS slice and dropping OOS n < 30 rows; it now also registers the pooled `_pool` tag (none > 1.00). Combos with no holdout get their pooled number from a new all-cells holdout run (combo-validate-pooled.yml) rather than from the best-of-thousands in-sample number.
- B-1427 / B-1494: under the every-variant wiring rule, an exit change on the same entry is a VARIANT of that entry, ranked by return per day. A replay that does not store avg_net_pct cannot be ranked, so every research output must keep avg net % per trade (data-intact rule). B-1494's be2 ties were already wired by B-1500's live_be2 mode.
- B-1455: a merge step that copies file-level metadata from each shard keeps the LAST shard's value; a multi-interval run must store period per interval. The brk20 run was 1d 5y / 1h 730d / 15m 60d, not 730d.
- B-1479: 86 of 102 "awaiting run" Elder rows had in fact run, but at 1d only; the label said "not run" when the truth was "one candle size". Reconcile against the registry, never against row labels.
- Profit-booking / exit takeaway: exit variants on a proven entry (trail, breakeven, exhaustion) are the cheapest way to add profitable entries, but they must be ranked by return per day from complete data; the gap_and_go peak-LTP 0.5R trail (0.306 %/day) still beats every exit-family exit (PFnet 1.09-1.21 at 10-11 bar holds).

## B-1452 / B-1430 / B-1464 / B-1446 - paper gateway, real sizing and test hygiene (2026-11-09)
- A paper row is the only gateway to a real order. Any paper-side rounding to 0 shares (or a paper-only minimum notional) silently kills the real leg, even when Kotak Net could buy a share. Every real-mirrored chan entry (chan_gap long/short, chan_kalman long/short) now floors its paper qty at 1 share; the real order sizes itself from Kotak Net and logs its own money reject.
- Real sizing must use only real exposure (Kotak Net); paper-only positions never shrink real qty (B-1430, verified on main).
- Flaky tests here came from daemon threads (5-min unprotected backcheck, chan_gap universe build) that an earlier test started and that later acted on another test's DB. Tests must never start process-lifetime threads; loops are tested with a bounded rounds=N.
- Logging every repeated skip on every scan made real_trades grow ~12k rows/day (B-1533): log volume is a cost too (journal size, Upstash payload, memory).
- Profit-booking / exit takeaway: a fired, viable signal that never reaches Kotak is lost profit with no trace; check the paper gateway first whenever a viable strategy shows triggers but no real entries.

## Stop through the market at placement; entry-day chandelier ratchet (B-1520, B-1523, 9 Nov 2026)

- IOC (gap runaway, peak-LTP trail) rested no SL from 09:15 to 09:26 IST. The first stop that rested was exactly its trailed 141.66, so the market had been at or under it. Kotak refuses a SELL SL at/above LTP, often without an order id. The bot kept re-sending the same level, and the never-loosen rules kept every fallback at or above it. Fix: every equity SL send checks a fresh live tick. A stop through the market rests just under the price, so the holding is never naked, and the swing engine then sells at market. That matches the replay, which fills at the open when the open is through the stop.
- The minervini/primary_base chandelier ratchet to entry - 2 x ATR within minutes of entry (ZYDUSLIFE 1159.80, PNB 125.63) is the backtested stop. The replay rests that level from the first bar after the signal bar, which is the live entry day. It is not a live bug.
- Profit-booking / exit takeaway: when the open gaps through a stop, take the exit at market immediately (the backtest fills there). Holding a position with no stop while waiting for a bounce is unmeasured risk that the PFnet never priced in.

## B-1453/1454/1457/1483/1485 - research runs that were "queued" but never ran (2026-11-09)
- Seven B-1485 trail-overlay dispatches, the brk20 short F&O/cash-split replays (B-1453/B-1454) and the O'Neil n200 cup replay (B-1483) were listed as queued in backlog notes, but `gh run list` showed none ran after 11-05. A queue written in a row note is a claim; check the run history before treating a result as pending.
- An Actions run that only uploads an artifact can lose its result: the 4h ATR run 39361657874 succeeded on 10-20, but its artifact cannot be fetched through the session proxy, so the 4h stop-% never reached git. Research workflows should commit their result or print it to the log.
- The "re-run atrnone tags with a stop" item was already done in practice: 180 of 189 viable atrnone tags have stopped siblings from the same sweep. Before dispatching a re-run, check whether the registry already holds the sibling.
- brk20 short: universe=nonfno (full minus F&O names) now exists, so the question of where the short edge lives (cash small caps vs F&O names) is answered by three runs with the same cells and different universes, each with its own tag.
- O'Neil rs80 cells need the RS rank over the live population (RS_UNIVERSE=n200). A per-shard rank uses a different population than the live scan, so a shard-ranked PFnet does not support wiring.
- Profit-booking / exit takeaway: trail-vs-fixed decisions for chan_kalman 1d/1h, Minervini lab cells, brk20 1h and the O'Neil daily cells are still unmeasured; until those runs land, these cells exit on their fixed stops. The B-1484 lesson (peak-LTP 0.5R is the only trail that wins broadly) is the prior to test first.

## B-1533 - first skip only in the real-attempt log (user decision, 2026-11-10)
- A rejected trigger is re-evaluated every scan, so one blocked symbol wrote ~109 identical skip rows a day (11,799 rows on 09-Nov) and grew docs/real_trade_log.json ~8 MB/day toward GitHub's 100 MB file limit.
- Now real_trades keeps the first identical skip per day/symbol/side/status/strategy; entry_funnel_events still counts every repeat, so the "why no entry" evidence is intact and the git journal stays small.
- Profit-booking / exit takeaway: exit and placed/failed rows are never compacted, so every reason an order was or was not executed on the exit side stays fully logged.

## B-1537 - news add-on for entry and exit (market, sector, stock headlines), shadow only (2026-11-10)
- Mechanism: headline lexicon score plus HARD event flags, aggregated per stock / sector / market with a 12h half-life. Stock-level news can say "avoid" an entry or "tighten" an open position's stop; sector and market news only ever say "caution".
- Fit for this system: swing cells hold days, so a fresh fraud / SEBI / downgrade / results-miss headline is a real gap risk the price-only triggers cannot see; it mirrors cleanly for shorts (order win, upgrade, buyback against a short). It is fail-open, so a dead feed never stops trading.
- What broke / surprised: Moneycontrol's public RSS is frozen (newest item Apr 2024) though it returns HTTP 200 - a feed must be judged by item age, never by status code. Session network blocks news hosts, so live checks go through Actions.
- Limits, stated honestly: no historical headline archive exists here, so no backtest PFnet yet; a keyword lexicon misreads negation and sarcasm; headline timing lags price. Evidence must come from a shadow log of verdicts at real triggers before it decides real money.
- Profit-booking / exit takeaway: on a hard adverse stock headline, tighten the stop (never loosen, never a blind market exit); the saved loss on gap-down names is where this add-on can earn its keep.

## B-1539 - measuring the news add-on before it trades (View 5), 2026-11-10
- A news rule cannot be backtested here (no headline archive), so the evidence is built forward: every verdict at a real trigger or open position is logged with the price, then scored one session later. Accuracy and "saved %" per verdict type decide whether a rule goes live.
- Company-name + ticker query with a relevance filter is needed: ticker-only found 0 headlines for YESBANK, name-only pulled other companies' news.
- Profit-booking / exit takeaway: judge "tighten" by the move after the headline on held stocks; only if tighten verdicts are right clearly more often than not, and the saved % beats the cost of being stopped early, should a hard headline raise a real stop.

## B-1540 / B-1541 - news module live rules and the news trade lifecycle (2026-11-10)
- Live rule = confirmed (2+ different trusted publishers report the hard event) + confident (score agrees, no opposing hard event) + a live tick. It blocks a new entry and exits a real holding through that holding's own engine. One publisher, a blog, or no tick never acts.
- News-driven buys / shorts / adds are a NEW strategy with no backtest possible (no headline archive), so they run as paper trades (`news_event__confirmed__long/short__1d__v1`) with a 3% stop, and real money waits for measured PFnet > 1.00.
- Risk to watch: headlines lag price, so a news exit can sell after the gap already happened; View 5 "move after" shows whether the exit saved or cost money.
- Profit-booking / exit takeaway: hold a news trade only while sentiment stays at least half its peak; when it fades or reverses, close - the edge is the news, so no news means no reason to hold.

## B-1542 / B-1543 - news chain in View 5 and the real 1-share news buy (2026-11-10)
- B-1542: every news decision stores the headlines it was read from, so a wrong call can be traced to the exact headline and the lexicon fixed, not guessed at.
- B-1543: by the user's explicit override the news tag skips the PFnet / viability gate and buys 1 real share on confirmed + confident good news with a live tick. There is no backtest (no headline archive), so the 1-share cap is the whole risk control until real results exist; qty rises to risk sizing only when the user affirms.
- It rides the swing engine (CNC, resting SL with the entry, 5-minute Kotak backcheck, Upstash mirror) instead of a new engine or table, so every existing safety rule covers it from day one. Real shorts stay paper: no overnight cash short at Kotak.
- With Kotak Net near Rs 5,900 the 1-share risk floor (stop loss at most 1% of Net, about Rs 59) rejects a 3% stop on any share above about Rs 1,970; those show as money rejects, not silent misses.
- Profit-booking / exit takeaway: the real share is sold the moment the news trade closes - sentiment under half its peak, news reversed, 3% stop, or one week - never held on hope after the news fades.

### B-1544 / B-1545 news trailing stop and stale tick (2026-11-11 IST)
- B-1544: news stop starts 3% from entry, then trails 0.5% of the ENTRY price behind the best price once the price is past entry; never loosens. On a 3% initial stop, 0.5% is very tight: expect quick exits and small wins, not runners.
- B-1545: LENSKART opened on paper at 15:45 IST, after the close, because the feed's last stored tick counted as "live". A cached price is not a live tick: every news action now needs an in-session tick with a trade in the last 5 minutes. With one real attempt per signal, an after-hours open silently loses the real entry.
- Profit-booking / exit takeaway: a trail tighter than the check cadence (5 min) can be crossed between passes, so the real path sells at once when the price is already through the trailed level instead of waiting at the old stop.
- B-1546: a news signal missed because of a stale tick is not lost: if the news is still confirmed in session, re-base the paper row at the live price and buy then, so the stop and trail are set from the real entry, not the stale price.
- B-1547: a background pass that does several jobs must run the money job (open trades, re-base, exits) first and isolate every stage; a slow or failing logging stage silently stopped the Lenskart re-base for an hour. Expose each pass's stage/errors so a stall is visible, not inferred. Profit-booking / exit takeaway: exits and trails on open news trades must never wait behind news logging.
- B-1550: a one-attempt rule protects against chasing, but a skip whose reason is lost (B-1549) leaves a good signal stranded; a user-approved retry must re-check confidence and the live tick at retry time and mark itself durably first. Profit-booking / exit takeaway: the retried entry resets stop and trail to the real fill price, never the old paper price.
- B-1549: a restore that skips a non-empty table is only safe for state that is rewritten whole; for an append-only log it lets the first post-restart write erase history on the next push. Merge logs on restore. Profit-booking / exit takeaway: without the attempt log, a skipped profitable entry cannot be diagnosed, so the review loop loses its evidence.
- B-1551: a news signal decays; entering late is only justified while the market is still pricing it (fresh headline, stock up vs prev close, beating NIFTY, holding above the open, volume above pace). Otherwise the edge is gone and the entry is just a chase. Profit-booking / exit takeaway: a late entry that only passes because the news is still "confirmed" buys after the move; require live price/volume confirmation.
- B-1552: bad news is the short mirror of the news buy, but in the cash market it can only be an intraday MIS short (overnight shorts are unconfirmed at Kotak), so it must be entered early enough to work (cutoff 14:30 IST) and is covered by 15:14. Profit-booking / exit takeaway: a news short books at the trail or the close, never carried; judge it on intraday follow-through.
- B-1554/B-1555/B-1557 (daily review 2026-11-11): broker-side failures repeat a doomed order forever unless the retry reads the broker's own rejection. Kotak states the circuit band in its rejection text; use it instead of a third-party price feed. A stop that has triggered is an exit in progress, not a missing stop: never stack a second sell on it. A whole-session broker outage ("ADAPTER is down") cannot be traded around; retries must back off so the login stays usable for recovery. Profit-booking / exit takeaway: a 0.5R LTP trail on a 2-share ticket booked +1.1% gross but kept only ~Rs1.6 net, so tiny tickets give most of a small win to costs; ticket size, not the exit rule, is the next lever (B-1558).
- B-1559 (COCHINSHIP 2026-11-09/11): a trail that only counts completed bars AFTER the entry day ignores an entry-day run-up entirely: +4.3% intraday (Rs1,240 -> Rs1,293) left the stop at Rs1,203.70, and a gap down two sessions later turned the winner into a ~-3% loss. Updating the trail at 15:10 IST with today's price (entry day included) locks part of that gain before the overnight gap. Caveat: on 11-10 Kotak's order adapter was down all session, so no stop could rest whatever its level; a trail protects only when the broker accepts orders. Profit-booking / exit takeaway: refresh trailing stops before the close every day, because the overnight gap is where swing profits are given back; validate the tighter entry-day peak with a replay (B-1560).
- B-1553: one position per symbol per engine must not let a PAPER row block REAL money; a paper-only owner is handed to the engine that has a real signal, and restored if the real order fails. Profit-booking / exit takeaway: the engine that entered the real share owns its stop, trail and exit end to end.

## B-1556 (2026-11-12 IST): a triggered stop is still protection, everywhere

- Mechanism: when a Kotak SL fires it stays in the order book as a working order with prcTp L, keeping its trigger price. Every scan that filtered on prcTp SL/SL-M read that as "no stop" and could send a second exit (COCHINSHIP 11-11: a second SELL was rejected by RMS, T1 Used 2 / Available 1).
- Fix: one shared predicate (protective side, non-final, prcTp not SL/SL-M, trgPrc > 0) used by the backcheck, heals, ensure-stop paths and pre-exit cancels, long and short.
- Reuse: any new order-book scan that decides "is this position protected" must use the shared predicate, never a bare prcTp filter.
- Profit-booking / exit takeaway: an exit in progress must never be doubled; a doubled sell on intraday MIS could open an unintended short.

## B-1561 (2026-11-12 IST): restarts during market hours lose swing entries

- What happened (11-11): 6 viable swing setups fired on the first scan after each restart, before the Kotak price feed connected, and were refused "no live tick"; the 15-minute pass interval pushed the retry past the 15:14 cutoff.
- Fix: a swing pass waits until the feed has prices, and a no-tick refusal retries in 60 s.
- Reuse: any scan that runs at startup must wait for its data feed; any refusal caused by a transient gap must retry quickly, not at the normal interval.
- Profit-booking / exit takeaway: deploying mid-session costs real entries; prefer deploys before 09:05 or after 15:30 IST.

## B-1563 View 4 'Close now (at live SL)' column (2026-11-12 IST)
- Mechanism: per open real position, (live Kotak SL trigger - entry) x qty (shorts mirrored) = the P&L locked in if the resting stop fills now; shown gross, as % of entry value, and net of the ~0.8% round-trip cost.
- Why it matters: a stop above entry but inside the 0.8% cost band still loses money net; the net figure shows which trailed stops have actually locked in profit.
- Profit-booking / exit takeaway: judge a trailed stop by its net locked-in value, not by SL > entry; a stop under entry + 0.8% has not yet protected any profit.

## B-1564 Realised P&L KPIs were built from one trade (2026-11-12 IST)
- What happened: the Kotak fill ledger behind View 4's closed trades, ROC, CAGR and XIRR started on 11-11 (rows for 11-02..11-10 lost; Upstash-only table), so every KPI came from BANKBARODA alone.
- Fix: Kotak's digitally signed contract notes (one per trading day, in Gmail) are the complete fill record; parsed into docs/kotak_contract_note_fills.json and merged with Kotak-wins precedence. True Nov realised result: 7 exits, +Rs63.69 net (gross +84.66; charges and the flat RELIANCE intraday round trip cost Rs21).
- Profit-booking / exit takeaway: on these small 1-5 share lots, statutory charges eat about a quarter of gross profit, and a flat intraday round trip loses about Rs8; tiny positions need a bigger move to clear costs.

## B-1567 Intraday cell held overnight (2026-11-12 IST)
- BDL from the chan_kalman 15m long buy cell trailed into profit (SL 1053.55 > entry 1044.90) but was not flattened at 15:10; the 15:15 exchange purge then left it naked overnight, and repeated emergency exits placed nothing.
- Profit-booking / exit takeaway: an intraday edge only exists if the position is flat by 15:10; any exit refusal must be logged and alarmed, never a silent print.

## B-1568 Upstash bandwidth: meter is not a fix (2026-11-14 IST)
- What happened: the 10 GB/month Upstash bandwidth limit was crossed again after B-1342 had added a meter, alarms and a throttle. The throttle only touched non-critical writers; the cause (whole-table re-upload on every change and after every restart) stayed, and grew with the tables.
- Fix: upload only changed row-chunks, seed chunk hashes on restore, cache read-mostly keys in-process.
- Lesson: when a resource limit is hit, remove the cost that scales with data size first; monitoring and throttles come after, not instead. Check bytes per family against table growth whenever a new mirrored table is added.
- Profit-booking / exit takeaway: n/a directly; durability of positions, stops and order logs depends on Upstash staying under its limit, so this protects every real exit after a restart.

## B-1569 Commodity, currency and option-leg categories (2026-11-14 IST)
- Categories are pools for leaderboards, viability buckets and views; the real-money gate stays per strategy tag, so re-filing MCX rows from futures to commodity changes no entry.
- A name-only rule over-matches: `intermarket__usdinr_...` are equity swing trades that READ a currency signal. Filing must use what is traded (asset class/universe), not what is read.
- Closed-market days: when no market anywhere is open, slow ticks and slow dashboard writes save CPU, memory and Upstash bandwidth; protection paths keep running.
- Profit-booking / exit takeaway: n/a (no exit rule changed); separate commodity and option-leg pools let each one's PFnet ranking be judged on its own costs and hours.

## 2026-11-14 - Upstash suspended at 10 GB/month; migrations must free what they replace (B-1572/B-1573)

Mechanism: the free Upstash database was suspended once the month's 10 GB of bandwidth was used, because every mirrored table was re-uploaded whole (fixed in B-1568). Reviewing the console also showed storage at 213/250 MB, and the B-1568 migration would have written new chunk keys without deleting the old ones, roughly doubling stored size. Lesson: a storage-format migration must delete the keys it supersedes, but only after the new pointer (meta) is written, and must be checked against BOTH free-tier caps (bandwidth and storage), not just the one that failed. A suspended store must never be answered by restarting the bot (it would start empty); hold deploys until the store is back.
Profit-booking / exit takeaway: no trading-rule change; protects position state (and so stop-loss governance) across restarts, which protects open-position P&L.


## 2026-11-14 - Switching Upstash databases: stale snapshots are worse than empty (B-1574)
- The bot restores real-money state (positions, stops, kill switches, settings) from Upstash on every restart. An old database restores old reality.
- Fix: a stale-DB guard (heartbeat age > 7 days, or data without a heartbeat) makes the bot ignore the old values. The git tier and the 5-min Kotak reconcile rebuild the rest.
- Profit-booking / exit takeaway: after any database switch, check every Kotak holding has a live SL before 09:15 IST, because stop/trail peaks start fresh and stops are re-derived from the entry price.

## 2026-11-14 - Upstash daily pause (B-1576)
- Mechanism: once the day's Upstash budget (1/30 of the free 10 GB/500k-cmd month) is used, non-real-money writes stop until the next IST day; real-money state keeps writing up to 125%.
- Why: one day over budget used to eat the month and suspend the database, which removes the restart backup for real positions for weeks. Losing a day of dashboard counters is far cheaper.
- Profit-booking / exit takeaway: protection of open positions (stops, positions, kill switch) is never traded away for storage savings; only dashboard/research data is.
- B-1577 addendum: the quota is cumulative over the month (day N may use N x daily budget minus what days 1..N-1 used, never past the 10 GB monthly cap), so one heavy day is paid back the next day instead of hiding inside a fresh daily reset.

## 2026-11-14 - Intraday exit refused for a buy-engine position (B-1567)
- Mechanism: the intraday exit refused any symbol that had a paper swing row, so a real buy-engine position (BDL, chan 15m cell) could not be exited and sat overnight with no SL after 15:15, silently.
- Fix: refuse only when the real swing table owns it, or a paper swing row exists and the intraday row has no strategy; every refusal is logged with its reason.
- Coverage: buy: fixed / short: own exit path, no paper-swing check (B-1580 logs its no-row return) / swing: owns its own exits, unchanged / futures, options, MCX, currency: no shared refusal path.
- Profit-booking / exit takeaway: an exit refusal is a money risk, never a silent return; an unexited intraday position after 15:15 is naked overnight.

## 2026-11-14 IST: B-1380 pre-open short SL and B-1549 trade-table restore
- Mechanism: a short SL sent before 09:15 IST is rejected by Kotak and wastes a retry; the short SL placer now returns `skipped_pre_open` and the 09:15 protect pass places it. Separately, trade/fill tables were plain-overwritten on restore, so a restart lost the day's closed trades; they now merge-restore.
- Fit: Kotak-first; no gate loosened; no kill switch.
- Profit-booking / exit takeaway: P&L review and profit-booking lessons depend on complete trade history surviving restarts; never trust a post-restart trade count without the merge-restore.

## 2026-11-14 IST: SLBM on Kotak is dealer-only (B-1456)
Kotak's support page: SLBM orders are placed only through the dealer or customer service, not the app or Neo API. So an overnight cash short via a borrow cannot be automated: the most the bot can do is raise an alert (symbol, qty, max borrow fee) that the user places by phone, then adopt the short and protect it with an SL. The dealer step adds delay and a call charge, both of which the B-1456 backtest must include in its costs. Never lend shares held for a swing trade, because lent shares cannot be sold when the stop is hit.
Profit-booking / exit takeaway: a short reached through the dealer cannot be exited the instant a stop fires unless the cover is a normal market buy. Plan the exit as a regular cash buy-to-cover, with the borrow returned separately, and check this is allowed before any live use.

## 2026-11-14 IST: B-1582 swing prefetch memory growth
- Mechanism: each swing scan pass built a fresh thread pool for daily-bar prefetch; threads and their per-thread buffers piled up across the session, consistent with the 1.8-2.0 GB OOM restarts on 11-Nov. Prefetch now runs on one persistent 8-worker pool; skip/clear handling unchanged in the scan pass.
- Coverage: swing done (the only engine using this prefetch); buy, short, bidirectional, futures, options, options_multi, commodity, currency n/a (no daily prefetch pool).
- Profit-booking / exit takeaway: an OOM restart mid-session delays every exit and SL check by minutes; memory stability is exit safety, so verify the peak after deploy before calling it closed.
### Elder position sizing incl. martingale negative control (B-744 / B-745, recorded 2026-11-14 IST)
Mechanism: the same Elder batch-3 trade stream (1d, ATR 2 stop, proxy R = 2 x median ATR%) replayed per symbol as one account under five sizing policies: fixed 2% risk, optimal-f capped at 2%, optimal-f uncapped, half-f, and martingale (double after each loss) as a negative control. Run 38169625565 (full universe, ~2,290 accounts, both directions; table docs/backtest_data/elder_batch3_merged_run_38169625565_table.txt lines 497-506), confirmed on NIFTY200+ETF run 38211452647. Geo-mean final equity long/short: fixed2pct 0.865/0.901, optf_capped2pct 0.914/0.940, halff 0.889/0.949, optf_uncapped 0.747/0.864, martingale 0.309/0.513 (28.3%/13.6% of accounts ruined, 71%/47% with drawdown > 50%). Sizing policies are not strategies, so they carry no PFnet registry tag; the metrics live in the run table.
Fit for this system: the live bot already sizes by fixed 1% risk off Kotak Net, which sits in the safe group; martingale is confirmed as a ruin path and must never be wired. Capping f at the fixed-risk level never hurt and slightly helped; uncapped f roughly tripled the ruin rate.
Profit-booking / exit takeaway: never add size after a loss to "win it back"; keep risk per trade fixed (or capped f), because loss streaks on a sub-1 PFnet stream turn doubling into account ruin.
### 2026-11-14 IST: Elder osc__adx_exit_hard vs _soft identical numbers explained (B-862c)
- Mechanism: scripts/elder_trend_context_research.py `d_adx_softexit`: hard exit = `~up & close < EMA13`, soft adds `ADX falling 2 bars & close < EMA13`.
- Why identical (PFnet 0.60 long / 0.40 short, n ~228k-245k, run 38209280422): for an EMA, close_t < EMA_t implies close_t < EMA_{t-1}, so EMA_t < EMA_{t-1} and `up` is False. The hard exit is therefore just "close below EMA13", and the soft ADX leg is a strict subset of it: the ADX condition never decides an exit.
- Reuse: an exit filter ANDed with "close below the same EMA" adds nothing; test an ADX-fade exit on its own (no close<EMA clause) if ever revisited. Both cells are far below the floor, so no re-run is owed for this alone.
- Profit-booking / exit takeaway: an EMA13 close-break exit already dominates slower trend-fade exits; adding ADX to it cannot book profit sooner.

## 2026-11-15 IST: batch merge of 45-day backlog sweep (batches 01-14)
- Mechanism: 14 agent batches triaged ~600 rows against origin/main evidence; ~194 closed with run ids or code locations. Research-only patches merged (4h research_interval in Elder ext, ORB bars per candle size, O'Neil by-year PFnet, correction-ratio sweep, gap_and_go exittime cells, pattern-lab workflow, read-only /sl-loosen-attempts, B-1580 skipped_no_real_row log). Two REAL-MONEY fixes (B-313 off-hours short cover skip, B-1557 broker-outage SL backoff) held off the branch until the user approves.
- Notable results: Elder osc div_class cells 0.925/0.948 on a clean main.py replay (earlier 2.4 was a data glitch); martingale sizing ruined 28%/14% of accounts (never wire); capped optimal-f beat fixed 2% (0.914 vs 0.865, DD 11.0% vs 16.7%).
- Coverage: short (B-313, B-1580) done; buy/swing/options SL legs (B-1557) built-held; futures, commodity, currency n/a for this merge.
- Profit-booking / exit takeaway: an exit order sent when the market is closed or the broker is down only burns retries and hides real alarms; gate every emergency exit on market-open and broker-up first, then exit decisively at the open.

## B-1578: intraday buy-engine real entries go MIS, not CNC (2026-11-15 IST)
- Cause: BDL 2026-11-12 intraday buy went CNC; the same-day target LIMIT SELL was rejected 'No Holdings Present' (a CNC buy is not sellable as holdings until T+1 under some RMS paths) and the position was carried overnight.
- Fix: long-side order functions take `product` (default CNC); real_positions records it ('MIS' for new entries, NULL = legacy CNC); every SL/target/exit leg reads it; reconcile corrects it from Kotak's `prod`.
- Side benefit: an MIS long is auto-squared-off by Kotak near 15:20 IST, a broker-side backstop if the bot's own 15:15 flatten fails (B-1567 (b)).
- Coverage: buy (real_positions) done; swing stays CNC by design; short/swing-short already MIS/CNC respectively; futures/options/options_multi/commodity/currency use NRML, n/a.
- Profit-booking / exit takeaway: an exit leg must carry the same product as the entry, or the broker rejects the profit-booking order exactly when it matters; record the product on the position row and derive every exit from it.

### B-1581 (2026-11-15 IST): no new SL on a position already sold or exiting
- NMDC 13-Nov: the rule exit filled at 09:18:57 IST, then a fresh SL went in at 09:19:05 IST and Kotak rejected it ("Check T1 holdings"). Before any SL, `place_real_stop_loss` now nets today's buys and sells from the Kotak order book against holdings, and returns `skipped_position_closed` when nothing is left to protect. `ensure_resting_sl` runs the same check once per pass.
- Profit-booking / exit takeaway: once an exit fills, the position is closed. Protection logic must read Kotak's fills first, so a closing sale is never followed by an orphan SL that a later buy could trigger.

## 2026-11-15 IST: Elder stop-offset (B-606, 1d) and elder-batch3 osc/struct at 1h: all fail
- elder-stop-offset-research.yml run 43666082279 (1d, 5y, 4764 symbols with data, 0.8% cost): 84 tags, none above PFnet 1.00. Best was brk20 structural stop with a 0.5 ATR offset, long at 0.871 (gross 1.069). Every offset from 0.25 to 1.0 ATR gave 0.870-0.871, so where the stop sits past the structure does not matter. The edge is not there before costs either. Shorts were about 0.50. Snapping the stop to a round number was the worst variant.
- elder-batch3-research.yml run 43593142428 (osc and struct families at 1h, 730d): 270 tags, best PFnet 0.867 (struct cycle_gate long, ATR 3). Gross PF reached 1.86 on some cells, but about 6,300 trades at 8 bars each turn that into a net loss after the 0.8% round-trip cost.
- Profit-booking / exit takeaway: fine-tuning the stop offset does not rescue a weak entry. On 1h bars, the cost per round trip uses up the gross edge, so short-hold intraday exits need a gross PF well above 2 to survive. Prefer longer holds or fewer, higher-quality trades.

### 2026-11-15 IST: Douglas trade-management 1h (run 43593152439), 480 cells
- 1h 730d, full NSE universe (5508, 5072 with data), 0.8% cost. 228 entry cells, 252 exit cells. 4 of 480 pass PFnet>1.00,
  all in `trademgmt_exit__brk20_min_rr__long__1h`: atr3_rr4 2.283 (n=2194), atr3_rr3 1.383, atr2_rr4 1.138, atr3_rr2d5 1.051.
- Edge rises with the reward:risk floor (rr4 > rr3 > rr2.5) and with ATR width 3 over 2: the min-RR filter that skips
  breakouts with no room to the 60-bar high carries the edge, the same finding as B-798.
- Harness is a research re-implementation, not the real main.py functions. The main.py replay of atr3_rr4 long 1h gave
  1.393 pooled but OOS 0.687, so the 2.283 here is optimistic. B-1596 replays the 3 non-live neighbours with main.py
  functions before any wiring.
- Profit-booking / exit takeaway: a far fixed target (4R) with a wide 3-ATR stop beats tighter targets on 1h breakouts;
  most exits are rule exits (1603 of 2194), so the trailing/rule exit, not the target, books most of the profit.

### 2026-11-15 IST: Elder patterns 1h (run 43668652845), 249 cells
- 1h 730d, full NSE universe, 0.8% cost; families consol 81, trendline 60, reversal 60, bars 48. 7 pass, all
  `consol__tri_desc`: long atr2_vol0 1.422 (n=150), atr3_vol0 1.412, atr1d5_vol0 1.370, vol1 cells 1.12-1.15 (n=88);
  short atr3_vol0 1.017 (n=85). Every reversal, trendline and bar-pattern cell fails.
- The descending-triangle long passes on BOTH 1d (1.22-1.27, n=313) and 1h, across all ATR multiples: a robust
  family, not one lucky cell. The volume filter (vol1) cuts trades ~40% and lowers PFnet, so it hurts.
- Thin samples (n<=150 at 1h). B-1597 ports it to main.py for a real-function replay before wiring.
- Profit-booking / exit takeaway: most tri_desc exits are rule exits (96 of 150), and a wider 3-ATR stop cuts stop-outs
  38 -> 9 with almost no PFnet loss, so let the rule exit book the profit and keep the stop wide.

### 2026-11-15 IST — Elder patterns 15m/60d (run 43677914631, B-600..B-624, B-1597)
- 246 cells (consol 78, trendline 60, reversal 60, bars 48) on the full NSE universe (10,832 symbols with data), 0.8% cost. **0 pass PFnet>1.00**; best 0.474 (trendline channel short atr3).
- consol__tri_desc, the 1h and 1d winner (1h long 1.37-1.42, 1d long 1.22-1.27), collapses on 15m: long 0.03-0.07, short 0.12-0.21, n=14-45. The 60-day window gives too few triangles, and 15m costs eat the edge. Treat tri_desc as a 1h+ pattern; B-1597's main.py replay should focus on 1d/1h and include 15m only for completeness.
- Profit-booking / exit takeaway: on 15m most exits are rule_exit with tiny average moves, so the 0.8% round trip dominates. Pattern exits need a 1h+ hold to clear costs.

### 2026-11-15 IST — Elder trend-context 1h/730d (run 43681690093)
- 210 regime / MA / oscillator cells, full NSE universe file (7,608 symbols with data), 0.8% cost. **0 pass PFnet>1.00**; best 0.728 (regime__wk_align_counter long atr3_wk13, n=86k). The 1d run 38209280422 also had 0 passes (best 0.984).
- Gross PF 1.2+ on the best cells, but the cost drag is huge at n=86k over 2 years: these rules trade too often on 1h. The weekly-alignment filter is the only family near break-even, on both timeframes.
- Profit-booking / exit takeaway: rule_exit dominates (about 87% of exits), so these context rules cut winners early. A context filter belongs as a gate on a separate entry engine with its own wider exit, not as a standalone trade rule.

### 2026-11-15 IST — B-422 slippage stress replay (run 43666079363)
- 7 top viable tags, replayed with main.py drivers on the full NSE universe at cost 0.8/1.2/1.6% x min daily turnover 0/1/5 Cr (63 cells). **61/63 hold PFnet>1.00.** Every tag survives double cost (1.6%) when no turnover floor is set.
- Weakest: gap_and_go exitexhaust (1.22 control, 1.04 at 1.6%, and 0.93/0.95 once a 1 or 5 Cr turnover floor is added). The turnover floor removes many of its winners, so its edge sits partly in thin names, which is where real slippage is worst. Treat it as the first tag to throttle if live slippage runs high.
- Strongest: the O'Neil weekly cells (newhigh_first 2.01-2.26, pivot 1.69-1.88), almost flat across cost and turnover. The flatbase control reproduced at 3.06, against 3.92 in the registry (n=71), so read that tag's headline number with caution.
- minervini_vcp falls from 1.47 to 1.23-1.25 with a turnover floor. It still passes, but much of its edge is in illiquid names.
- Profit-booking / exit takeaway: the long-hold, trailing-exit weekly families absorb extra cost best; short-hold exits (exitexhaust, about 11 bars) are the most cost-sensitive. Prefer wider or longer exits where slippage is uncertain.

### 2026-11-15 IST — Elder trend-context 15m/60d (run 43684505388)
- 210 cells, full NSE universe file (8,124 symbols with data), 0.8% cost. **0 pass PFnet>1.00**; best 0.418 (osc__open_gap_fade long atr3). This is far below the 1h best (0.728) and the 1d best (0.984): the context rules get steadily worse on shorter candles.
- Profit-booking / exit takeaway: on 15m the average move per trade is smaller than the 0.8% round trip, so no exit design can rescue these rules. Context and regime rules belong on 1d candles, used as a gate in front of an entry engine.

### 2026-11-15 IST — Elder patterns 5m/60d (run 43683612920)
- 246 cells, full NSE universe (10,852 symbols with data), 0.8% cost. **0 pass PFnet>1.00**; best 0.46 (trendline tl_break long, n=80). consol__tri_desc 5m long 0.14-0.23 (n=20-39). Across timeframes the pattern holds on 1d (1.22-1.27) and 1h (1.37-1.42) and fails on 15m and 5m.
- Profit-booking / exit takeaway: chart-pattern exits need room. On 5m the measured target is a fraction of the 0.8% round trip, so intraday pattern trading is not viable under this cost model.

### 2026-11-15 IST — Silent 4h-fetch bug (B-1598)
- Every research_interval 4h run fetched 0 symbols, because the resample ran on fetch_ohlc's RangeIndex instead of its "Date" column. Both elder-trend-context 4h runs came back empty and were not registered. Lesson: a merge that reports "fetched with data: 0" is a harness failure, never a strategy result. Check the fetched count before parsing any run.
- Profit-booking / exit takeaway: none yet. Exits at 4h are still untested for these families until the re-runs land.

### 2026-11-15 IST — Elder trend-context 4h/730d (run 43689022041, the first good 4h run after B-1598)
- 210 cells, 7,131 symbols with data, 0.8% cost. **0 pass PFnet>1.00**; best 0.923 (osc__gap_timestop long atr3_nb2, n=26.8k). By timeframe, the best cell scores 0.984 on 1d, 0.923 on 4h, 0.728 on 1h and 0.418 on 15m. Fewer, longer trades lose less to costs, but no timeframe clears the cost line. The family is now closed across every timeframe.
- Profit-booking / exit takeaway: gap_timestop (time exit after a gap) is the closest to break-even at 4h. A short fixed time-stop after a gap does better than the trend-context rule exits, though still not enough to wire.

### 2026-11-15 IST: Elder patterns 4h (run 43689024308, 730d, first good 4h fetch after B-1598)
252 cells registered (strategy_registry_ep4h.py), 23 clear PFnet>1.00 on the research harness (not main.py functions):
reversal__island long 4h 1.63-1.67 on n~9.9k (strongest and largest sample of the whole Elder patterns family at any
candle size; 1d long was 1.57); consol__tri_desc 4h short 1.11-1.16 (n=97) and long 1.05-1.14 (n=100-148), the only
candle size where tri_desc clears 1.00 (15m 0.03-0.21, 5m and 1h below 1). tri_sym long 3.9 is n=8: noise, not a finding.
Nothing wired: island goes through the main.py sweep (B-1090, workflow plan-job fixed this commit), tri_desc through the
B-1597 replay (blocked on merge to main). 4h island beating 1h/15m/5m says the reversal needs multi-session bars to form.
Profit-booking / exit takeaway: island at 4h held ~a few sessions; keep the ATR stop plus max-hold exit and test the
trailing-stop set (trailltp/chandelier) in the B-1090 main.py sweep before wiring, since a fixed max-hold may give back the gap.

### 2026-11-15 IST: chan_gap 15m candle sweep (B-1020, run 43691279529) and Elder indicators 1h (run 43691359056)
- chan_gap at 15m (real main.py chan_gap_entry_signal / select_top / exit_reason, full universe, 60d, 0.8% cost): 6 tags, 0 pass. Long buy_on_gap 0.877-0.916 (n 65), short short_on_gap 0.763-0.782 (n 157). The 1d baseline (main.py replay PFnet 1.32-1.39) does not carry to a 15m stop check: same-day close exits stay positive for the short (close bucket 1.09-1.49) but the 15m-bar stop hits eat it. n is small (60-day yfinance cap): read as "no edge shown", not "proven negative".
- Elder indicators at 1h (730d, full universe, 8 families, 300 tags): 0 pass. Best adx_bell ring_bell long atr3 0.714 (n 81k), obv 0.658, ema_gate 0.503; every other family under 0.45. At 1h the 0.8% round-trip cost is several times the average move per trade: these 1d swing indicators do not survive at hourly bars.
- Profit-booking / exit takeaway: on chan_gap the money is in the same-day close exit; a tight 1.5 ATR intraday stop cuts the short from 1.49 (close exits) to 0.78 overall, so keep the wider 4 ATR or the 1d-style stop if this is ever re-tried intraday. For Elder 1h, most exits are rule_exit/max_hold before costs are earned back: hold longer (1d bars) rather than tightening exits.

### 2026-11-15 IST: Elder patterns candle sweep complete (1d/1h/15m/5m/4h), 22 source rows closed; flag detector bug (B-617)
- All 42 pattern/direction families now have results at every candle size. Intraday (15m/5m) fails across the board (best 0.47). The only broad, high-n passes are reversal__island long 4h (1.63-1.67, n~9.9k, B-1090) and 1d (1.57), consol__tri_desc long 1h/1d/4h (B-1597), consol__tri_asc long 1d/4h (~1.03-1.09, n~1.5-1.8k) and two marginal 1d cells (quiet_wild 1.014, channel 1.007, n~50k). The tri_sym / tl_break passes have n 5-20: noise until a replay says otherwise. B-1599 tracks the main.py ports.
- The flag detector could never fire (its drift and breakout conditions contradicted each other on the same bar), so "flag has no edge" was never measured. Lesson: a cell with 0 trades at every candle size is a detector bug until proven otherwise; report n=0 families instead of dropping them silently.
- Profit-booking / exit takeaway: the patterns that pass hold for days (1d/4h). The same detectors on 5m/15m bars lose to the 0.8% cost every time, because each trade's move is too small. Book profit on these patterns on swing exits, not intraday targets.

### 2026-11-15 IST: island reversal candle/direction sweep on main.py functions (B-1090, run 43692422951) and chan_gap 1h (B-1020, run 43693114328)
- Island LONG holds up through the real main.py functions: 1d 1.61-2.79, 4h 1.34-1.99, with thousands of trades per cell. It fades at 1h (0.34-1.01) and is dead at 15m/5m (<0.25): within8 and the 30-bar hold measured in intraday bars describe a different, much shorter pattern.
- Island SHORT on the main.py exit (brk20_min_rr_exit_reason) clears 1.00 at 1d for gap05 (1.18-1.19) and px20 (1.08-1.12). The older research harness had all short cells at 0.64-0.71, so the exit and fill rules, not the detector, made the short side look dead. Every other short tf fails.
- chan_gap buy_on_gap LONG at 1h passes (1.08-1.15, n 587), while 15m failed (0.88-0.92): the 1h stop check is coarse enough to survive the open's noise. The short mirror fails at every intraday size (0.52-0.78).
- Profit-booking / exit takeaway: for island the wider stops (2.5-4 ATR) beat 1.5 ATR at every passing cell, by 0.01-0.11 PFnet. The stop should give the reversal room, and the EMA13 rule exit should book the profit. For chan_gap, book same-day: the close exit carries the edge, and 1h bars avoid the whipsaw stops that kill 15m.

## 2026-11-15 IST: Elder indicators 15m and chan_gap 5m (B-579 family, B-1020)
- Elder indicators 15m (run 43693213969, 300 tags, main.py functions, full universe, 60d, 0.8% cost): 0 pass. Family bests: adx_bell long 0.379, obv long 0.339, adx_bell short 0.285. Every family is far weaker at 15m than at 1h (0.714 best). Cost per trade swamps the smaller 15m moves.
- chan_gap 5m (run 43694587564): 0 pass, and the numbers match 15m exactly (long n 65, short n 157). The gap is a daily-open condition, so the candle size changes only the stop granularity, not the entries. chan_gap is now done at every intraday size; only 1h long (1.08-1.15) passes (B-1600 d).
- Profit-booking / exit takeaway: on intraday Elder indicators most exits are rule exits or stops that close before the move covers the 0.8% cost. Shorter candles add trades, not edge, so any exit tuning should start from 1h, not 15m.

## 2026-11-15 IST: Elder indicators 5m (B-579 family)
- Run 43695454674 (elder-indicators-research.yml, 5m, 60d, 0.8% cost, 21704 symbol-fetches): 300 tags, 0 with PFnet > 1.00. Best adx_bell ring_bell long atr3_pts5 0.224 (n 70704).
- Ladder across candle sizes is monotone: 1h best, then 15m (0.379), then 5m (0.224). Each step down to a smaller candle multiplies trade count about 3x while the per-trade edge stays below the 0.8% round-trip cost, so cost eats more of it.
- Not wired (wiring needs pooled PFnet > 1.00). 4h run still owed to finish the candle-size grid.
- Profit-booking / exit takeaway: on 5m, rule_exit (52% of exits) and stop_loss (26%) both close trades well before a move can cover 0.8%; a smaller candle needs a wider or profit-gated exit, not a tighter one.

## 2026-11-15 IST: B-1600 wiring (island short 1d, island long 1d _tfs) and the chan_gap resolution question
- User rule (2026-11-15): PFnet > 1.00 is the only wiring condition; every passing variant is wired.
- Island SHORT 1d through main.py functions (run 43692422951): gap05 1.178-1.192, px20 1.076-1.115. The older research-script run (38221645245, reciprocal-price exit) had 0.651 for the same tag family; the main.py exit (brk20_min_rr_exit_reason short) is what the live bot runs, so the main.py number decides. Island LONG 1d matches across both (2.06-2.95 vs 1.94-2.20), so the gap is in the short exit implementation, not the detector.
- chan_gap long: same trade at every "tf"; only the backtest's stop-check resolution changes. 1d 1.445 and 1h 1.08-1.15 pass, but 5m and 15m fail. A real SL-M fires on ticks, so the finest resolution is the honest one. Re-test owed (B-1602).
- Profit-booking / exit takeaway: a backtest that checks the stop only at the bar close or bar low of a coarse candle books exits a resting SL would have hit earlier. Judge a stop-dependent cell at the finest bar size available, and treat a pass that shows up only at coarse resolution as unproven.

## 2026-11-15 IST: B-1180 chan_shape candle-size x direction sweep (run 43696407370)
- 60 cells (long + reciprocal-price short, 1d/4h/1h/15m/5m, ATR 1.5/2.5/4, hold 5/10), real main.py functions, full universe, 0.8% cost: all fail. Best long 1d atr4 hold10 PFnet 0.901; 4h 0.64-0.72; intraday 0.15-0.4; short never above 0.65.
- PFnet rises with candle size and with the wider stop, so the cost-per-trade drag dominates the shorter candles. The momentum shape has no edge after cost below the daily candle, and not enough on it.
- Profit-booking / exit takeaway: most chan_shape exits are the max-hold timeout (well under 1.0 PFnet) or the stop (0); the shape rarely runs far enough within 10 bars to pay 0.8%. A time exit on a weak signal books the cost, not a profit.

## 2026-11-15 IST: B-1600 (b) island long 4h wiring and the bar-1 problem
- 12 island long 4h cells (PFnet 1.34-1.99, main.py-function sweep 43692422951) wired. NSE 4h bars are session-anchored: bar 0 09:15-13:15, bar 1 13:15-15:30. A bar-1 signal is only known at the 15:30 close, after the exchange cancels resting orders (15:15), so live can trade only bar-0 signals; a bar-0-only replay is owed (B-1603).
- The B-1600 (c) 1d _tfs cells were silently unable to take real entries (unmapped registry name, fail-closed). A wiring test must check the viability path returns a real decision, not only that the tag is in the entry chain.
- Profit-booking / exit takeaway: the 4h exit is the same brk20 long exit (stop, EMA13 rule, 30-bar hold = 15 sessions); a frozen SL from entry means a 4h trade's worst case is fixed at k x 4h-ATR, smaller than the 1d stop for the same k.

## 2026-11-15 IST: B-1181 tasuki gap candle-size x direction x universe sweep (run 43701581391)
- Only the live cell survives: ETF short 1d PFnet 1.203 (n83, lower than the older 1.65-2.08 replay but above the floor). Long mirror, intraday and 4h sizes, and the full universe all fail (full-universe long 4h best at 0.80).
- The edge is specific to ETFs on the daily candle; widening the universe adds trades that lose after cost.
- Profit-booking / exit takeaway: the 3-bar max hold is the dominant exit everywhere; on intraday bars 3 bars is too short for the gap to close, so the timeout books the 0.8% cost on near-flat trades.

## 2026-11-15 IST: B-1596 brk20 1h long re-run (run 43696686802) and B-1602 chan_gap 1d same-window run (43703402682)
- brk20 1h long: atr3_rr4 reproduces (1.393 -> 1.379, n2129) and is wired after atr4_rr4. atr3_rr3 slipped from 1.020 to 0.983 on the re-run: a cell sitting within 0.02 of the floor is not stable, and the strict >1.00 rule keeps it out. Wider stop + more R:R room (atr3/atr4, rr4) is where the 1h edge lives; atr2 and rr2d5 lose everywhere.
- chan_gap same 60-day window: the 1d replay passes (long 1.05-1.14, short 2.55-2.75) while 5m/15m fail (long 0.88-0.92, short 0.76-0.78), yet almost no stop fires at any resolution. So the difference is the exit price, not the stop check: the 1d replay books the 15:30 close, while the intraday replays (and the live bot) flatten at 15:15. The last 15 minutes carry the edge in the 1d numbers.
- Profit-booking / exit takeaway: for a same-day trade, the flatten time is part of the strategy. A backtest must exit when the live bot exits (15:15 here), or it credits the strategy with a closing auction it never trades. Worth a separate test: hold chan_gap longs to a 15:25 market exit, and check the cost of the 15:15 cutoff.

### 2026-11-15 IST - B-1604: chan_gap 1d vs intraday gap is a price-basis artifact, not the exit time
- Paired run 43708230898 (1h, 730d, same candidates, same entry and stop walk) booked each trade twice: flat at 15:15 vs at the 15:30 daily close. Short 0.53-0.54 became 12.6-20.3 (win 89-90%); long 1.12-1.20 became 0.94-0.99.
- Both directions moved toward a LOWER exit price. A 15-minute exit shift cannot do that, but a price-basis mismatch can. data_fetch.fetch_ohlc relies on yfinance's default auto_adjust=True (yfinance 1.8.0). That back-adjusts DAILY bars for dividends but leaves Yahoo intraday bars raw. Over 730d the daily close and history therefore sit below the intraday open.
- The same mismatch biases candidate selection. Raw intraday opens look like gap-ups against adjusted prior closes: n4257 short vs 572 long at 1h. So every intraday chan_gap cell that uses daily history is suspect until the _rawd rerun. The 1d-mode replay (both sides adjusted) is internally consistent.
- Live is fine. Today's open vs yesterday's adjusted close only differs on an ex-date, where the adjustment correctly removes the dividend gap.
- Fix built: RAW_DAILY=1 (auto_adjust=False on daily and intraday, _rawd tags) plus a DOPEN_RATIO diagnostic. The _xd1530 adjusted rows are registered as ARTIFACT and never wired.
- Profit-booking / exit takeaway: never compare exits priced from two data series with different adjustment bases. A win rate near 90% on a 1-session mean-reversion exit is a data bug until proven otherwise. Price both entry and exit from the same unadjusted series.

### 2026-11-15 IST - B-1603 island 4h bar-0 subset + B-1091 pl1d candle sweep
- Island 4h long, bar-0 only (run 43709215753): all four filters stay well above 1.00 on the 09:15-13:15 signals the live 13:15 leg can enter: gap05 2.01-2.08, turn1cr 1.69-1.75, none 1.62-1.65, px20 1.45-1.49. That is at or above the full-day cells, so restricting to bar 0 costs nothing. 4h island short fails on every filter.
- pl1d (STARC full fade, gap runaway), run 43707237249: only 4h long clears 1.00 (starc atr6 1.129, atr4 1.068, runaway atr6 1.015). Every 1h/15m/5m cell and every short cell fails after 0.8% cost. Wider ATR stops help at 4h (atr6 > atr4 > atr2d5), the same pattern as the 1d cells.
- Profit-booking / exit takeaway: the passing 4h exits come from the 20-bar timeout (letting the move run), not from the stop. Wide stops that survive noise plus a fixed time exit beat tight stops on these mean-reversion and runaway entries. On faster candles the 0.8% cost eats the edge.

### 2026-11-15 IST: B-1604 chan_gap 1h on raw (unadjusted) prices, run 43710558361
- Dividend-adjusted daily history pushed prior closes below intraday prices, so the gap-down filter fired far too often for shorts: 4257 short candidates adjusted vs 746 raw.
- On raw prices with the live 15:15 exit: chan_gap SHORT 1h scores 0.71-0.73 (fail). LONG passes at atr2d5 (1.045) and atr4d0 (1.042) and fails narrowly at atr1d5 (0.995).
- Exiting at the 15:30 daily close still scores about 2.0 for shorts even on raw prices. Yahoo's NSE daily Open differs from the first 1h open by more than 0.5% on 40-46% of days, so daily and intraday Yahoo bars are not one price basis. Never mix them inside a single trade.
- The live chan_gap SHORT gate rests on a 1d replay that used adjusted daily bars. That replay needs re-checking on raw prices.
- Profit-booking / exit takeaway: the 15:30-close "edge" is a data artifact. Book chan_gap exits at the live flatten time (15:10-15:15) on one price source. Short gap fades do not survive an honest exit.

### 2026-11-15 IST: B-1604 gate decision, chan_gap cells re-measured on the live basis
- On the user's rule (PFnet > 1.00 strict, "follow the rules set by me till now"), live cells are now re-measured on raw prices with the real flatten-time exit, and the result decides the entry gate: chan_gap SHORT 0.71 closed, long atr1d5 0.995 closed, long atr2d5 1.045 / atr4d0 1.042 kept.
- A replay on dividend-adjusted daily bars can pass a cell that fails on the prices the bot actually trades. The live-basis re-measure supersedes it, and the newest run decides.
- Profit-booking / exit takeaway: judge a same-day cell only by the exit the bot really books (15:10-15:15 market flatten on raw prices). The wider 4x ATR stop keeps the long gap-buy edge because it lets the flatten, not the stop, book the trade.

### 2026-11-15 IST: B-1605 pl1d 4h bar-0 replay and B-1010 gatetarget short candle sweep
- pl1d 4h, signals only on the 09:15 4h bar (run 43714020903): the long edge thins against the all-bar sweep (starc atr6 1.129 -> 1.065, atr4 1.068 -> 1.009, gap atr6 1.015 -> 1.020) and two cells flip (gap atr2d5 now 1.004 passes, starc atr2d5 0.934 fails). Four long cells pass PFnet > 1 and are wired on the 4h leg (entry 13:15-15:00 IST). Every short cell fails hard (0.04-0.72).
- gatetarget short (B-1010, run 43714049928): every intraday and 4h cell fails (0.11-0.48). Gross PF is below 1 at every size, so this is no cost problem: the 1d/1h gatetarget edge does not survive smaller candles.
- Profit-booking / exit takeaway: on pl1d 4h the winning trades are the max-hold timeouts (20 bars, about 10 sessions) and the wider 6x ATR stop does best, so let the trade run to the time exit rather than tightening the stop; the 2.5x stop gives most of the edge back to stop-outs.

### 2026-11-15 IST: B-1607 chan_gap SHORT breakdown (why 1.31 became 0.71)
- One cause at a time, full universe, real main.py functions, 0.8% cost, ATR 1.5 / 2.5 / 4.0:
  - Price basis (1d bars, last 730 days, 15:30 close): adjusted 1.20 / 1.18 / 1.19 (n695, run 43720044302) vs raw 1.22 / 1.19 / 1.20 (n693, run 43720050830). Effect about +0.02: none.
  - Exit time (1h raw bars, same 746 candidates): 15:15 live 0.710 / 0.726 / 0.713 vs 15:30 intraday close 0.711 / 0.725 / 0.712 (run 43721193037, _ic1530). Effect about 0.00: none. The earlier _xd1530 2.0 was the daily-vs-intraday bar mismatch, not the last 15 minutes.
  - Bar size (both raw, both 15:30): 1d 1.22 (n693) vs 1h 0.71 (n746). This is the whole drop. Yahoo's first 1h bar opens >0.5% away from the daily Open on 46% of short candidate days (DOPEN p10 0.965), so the 1h replay enters at a different price and admits a different candidate set (746 vs 693).
  - The old 1.31 (run 38502123279) was a longer history; on the same 730-day window the daily replay is about 1.20.
- Open question, B-1608: which opening price does the live bot actually get, the daily Open or the first-intraday-bar Open? Answering it from the bot's own fills decides which replay is honest.
- Profit-booking / exit takeaway: holding the short from 15:15 to 15:30 adds nothing, so the live 15:10 cover gives up no edge. The loss comes from the entry price, so any fix belongs at entry (fill at the real open), not at the exit.

### 2026-11-15 IST: B-1608 chan_gap SHORT, which open does the live bot get?
- The only live chan_gap fill (DABUR short, 2026-10-30) filled at Rs365.50 at 09:24:45 IST, a market fill about 9 minutes after the open. The 1h replay entered at 369.05 (a stale first bar equal to the prior 15:15 bar) and the adjusted daily open was 366.6, so the real fill was worse for a short than both replays.
- So the 1h replay (PFnet 0.71) is the closer of the two and is still optimistic, and the daily-open replay (1.22) overstates the edge. The short gate stays closed. n=1, and no more fills can come while the short is unwired.
- Profit-booking / exit takeaway: for open-gap fades, judge a cell on the price a market order actually gets a few minutes after the open, not the bar Open; a gap that half-fills before the fill erases most of a fade's edge.

### 2026-11-15 IST: B-1606 chan_gap LONG cap5 / fit5 on the live basis
- Re-measured with raw (unadjusted) daily and 1h bars, the real main.py cap5/fit5 stop rules, and an exit at the last 1h bar ending <= 15:15 IST. Full NSE universe, 730 days, 0.8% cost, run 43728496268.
  - atr4d0cap5 (4 x ATR, capped 5% below entry): PFnet 1.077, n749, win 37.1%. 53 trades stopped, 696 closed at 1.67. It stays wired (> 1.00).
  - fit5 (first ATR cell whose stop fits 5%, else no entry): PFnet 0.438, n191, win 29.3%. Gated off via live_exit_remeasure_run_43728496268.json.
  - The plain ATR cells reproduce run 43710558361 (1.5 / 2.5 / 4.0: 0.997 / 1.047 / 1.044, n749 vs 751).
- The adjusted 1d replays (cap5 1.411, fit5 1.242) overstated both. cap5 keeps about a quarter of that edge; fit5 keeps none. fit5's filter keeps only the tight-ATR days, and on raw intraday prices those are the worst days.
- Profit-booking / exit takeaway: on a gap-buy held for one session, a hard 5% cap on a wide ATR stop helps (1.077 vs 1.044 uncapped) because it cuts the few deep losers while leaving most trades to the 15:15 flatten. Skipping trades whose ATR stop is wider than 5% (fit5) throws away the profitable volatile days.

### 2026-11-15 IST: Douglas / Elder trade management at 15m (run 43728822855)
- 504 entry and exit cells (scale-out, breakeven ratchet, min R:R, time stop, chase cap, cooldown, trend/regime gates, scale-in), both directions, full NSE universe (5362 with data), 60 days of 15m bars, 0.8% cost. Every cell fails; the best is 0.388 (brk20_min_rr short atr3 rr4, n825).
- 5m (run 43730823714, 5368 with data): every cell fails again, best 0.189 (brk20_scale_atr long, n160k). PFnet halves again from 15m to 5m: the result scales with bar size, as a cost effect would.
- The same cells at 1h (run 43593152439) reach 2.28 (brk20_min_rr long atr3 rr4). The rules are not the problem: a 15m bar's move is too small to cover a 0.8% round trip, so cost swamps every exit design.
- Profit-booking / exit takeaway: no scale-out, ratchet or trailing design rescues an entry whose average move is under the round-trip cost. Pick the candle size by move per trade vs cost first, then tune the exit.

### 2026-11-15 IST: B-1600 (e) island turn1cr LONG 1h wired
- Of the three turn1cr 1h cells in run 43692422951, atr4 (1.012) and atr2d5 (1.004) pass the strict PFnet > 1.00 rule and are wired last on the 1h swing leg; atr1d5 (0.962) is not. n3264.
- The margin is thin: about 1% over cost. Unlike the 4h cells (1.34-1.99), these sit near the line where a small fill-price slip (B-1608: a market fill a few minutes after the signal) can turn them below 1.00.
- Profit-booking / exit takeaway: on 1h island longs the wider stop (4 ATR) beats the tight one (1.5 ATR); the tight stop takes too many noise stop-outs before the EMA13 rule exit can book the move.

### 2026-11-15 IST: Elder gap-fade / MACD at 4h, dirsys13 at 1h
- Elder >=1.1 cells at 4h (run 43735471593, 2377 symbols, 1h bars resampled to NSE-session 4h, 0.8% cost): every pooled cell fails, best 0.99 (gaps common_fade long atr3 nb4, n10389). In-sample segments reach 1.34 but out-of-sample falls to 0.67, so the daily edge (1.25) does not carry to 4h, the same as at 1h.
- Elder Directional System DI13 at 1h (run 43735474064, 2513 symbols): all 192 cells fail, pooled best 0.60. The daily dirsys cells already failed OOS; at 1h they lose more to cost.
- At 15m (runs 43736692561 / 43736695008, 2681 symbols) and 5m (runs 43738631635 / 43738634380, 2684) both families fail outright: Elder ge11 pooled best 0.235 / 0.132, dirsys13 best 0.444 / 0.245. PFnet roughly halves with each step down in bar size.
- Profit-booking / exit takeaway: a gap fade on 4h bars holds about 3.5 bars (two sessions), and over that window the 0.8% round trip takes the whole fade. Only the daily version, which holds days, has room for the exit to book a move bigger than cost.

### 2026-11-15 IST: Elder gap-fade 1d, strict-FIFO validation (B-850, run 43739717415)
- One position per symbol per cell, 2361 symbols, 5 years, 0.8% cost. 12 long gap-fade cells keep pooled PFnet > 1.00: exhaust_fade nb5 1.16-1.18 (n4406), common_fade nb5 1.09-1.12 (n5424), nb3 1.04-1.09 (n6949), nb4 1.01-1.05. MACD hist_exhaust and every short fail.
- Out of sample the split widens: exhaust_fade drops to 0.78, while common_fade nb5 holds at 1.05. The common (low-volume) gap is the steadier fade; the high-volume exhaustion gap did its best work in the early years.
- Elder dirsys13 at 4h (run 43739720015) fails too: best 0.747. At 1m (run 43740746026, 7 days only) best 0.199. B-588 is closed: no interval clears 1.00 (1d best 0.807).
- Profit-booking / exit takeaway: the gap fade books its move in about 3.4 days through the rule exit (high below the prior high). Waiting longer for the gap to fill (nb5 vs nb3) raises PFnet, and a wider stop (3 ATR) beats a tight one in every cell.

### 2026-11-15 IST: B-1610 gap-fade LONG 1d, 12 cells on the real main.py functions (run 43742835434)
- Full NSE universe, 5 years, 0.8% cost, FIFO per symbol per cell, fill at the signal close. All 12 cells clear 1.00: common_fade nb3 1.29-1.35 (n6.5k), common nb5 1.22-1.27, common nb4 1.20-1.22, exhaust nb5 1.17-1.21.
- By return per day the waiting period matters most: common nb3 earns 0.19 %/day against 0.14 for the live common nb5 cell, because it enters two days sooner on more setups (6.5k vs 5.2k) and still books its move in about 3.4 days.
- Main replay vs the research harness: the main replay is a little higher on every common cell (nb4 atr1.5: 1.20 vs research 0.999), so judging these by the research row would have dropped a profitable cell.
- Profit-booking / exit takeaway: the rule exit (first day the high fails to exceed the prior high) does nearly all the booking, so a wider ATR stop only adds room: 3 ATR beats 2 and 1.5 in every family. Keep the stop wide and let the high-below-prior-high rule take the profit.

### 2026-11-16 IST: Elder stop-offset and round-number stops, 1h (B-606, run 43769949221)
- 84 tags on 1h bars over 730 days (5,026 NSE symbols with data, 0.8% round-trip cost), both directions, ATR 1.5/2/3. All fail: best PFnet 0.698 (brk20 long, raw 3 ATR stop).
- Stop placement barely moves the result: structural offsets of 0.25-1.0 ATR, round-number snap and just-beyond-round all land within about 0.015 PFnet of the raw ATR stop. Long breakouts 0.65-0.70; dip entries 0.35-0.37; short breakouts 0.23-0.25.
- Gross PF is above 1 for long breakouts (1.16-1.20), so the hourly entries do have an edge before costs, but 0.8% a round trip on 11-bar holds wipes it out. Same verdict as the 1d run (best 0.871).
- Profit-booking / exit takeaway: at 1h the stop's exact position is not the lever; trade frequency against cost is. Hold longer or trade fewer, larger moves (the 1d swing engine's job) rather than refining the stop.

### 2026-11-16 IST: Elder stop-offset and round-number stops, 15m (B-606, run 43775842575)
- 84 tags on 15m bars over 60 days (5,362 NSE symbols with data, 0.8% round-trip cost). All fail: best PFnet 0.265 (brk20 long, just-beyond-round stop). Gross PF is under 1 everywhere (max 0.725), so there is no edge even before costs.
- Every stop variant again lands within about 0.003 PFnet of the raw ATR stop: the stop's position does not change the outcome.
- Profit-booking / exit takeaway: on 15m the ~10-bar holds cannot pay a 0.8% round trip; no stop or exit refinement fixes that. Intraday versions of these entries stay off.

### 2026-11-16 IST: O'Neil extension rerun with full cell tables (B-783, run 43774856917)
- 288 cells each on 1d and 1w (2,181-symbol universe, 0.8% cost), every cell committed as a TSV this time (no top-N truncation). 1d: 86 pass PFnet > 1 (old run 87); 1w: 145 pass (old 143). 12 new tags; 9 cells flipped across the 1.00 line, the rest kept their verdicts.
- Leaders: pivot breakout x tightness pr1 1d (3.17, n 337), leaders first-high 1d atr3 h60 (1.98, n 1611), flag-price breakout 1w (5.27, but n 28) and HFT breakout 1w (3.87, n 124).
- Caveat stays: overlapping signals (no strict-FIFO non-overlap, no IS/OOS), and 2,181 of the 2,723 requested NSE-file symbols had enough daily history (the rest are newer listings). Passing cells still need the non-overlap rerun and a main.py replay before wiring.
- Profit-booking / exit takeaway: the winners all use wide ATR stops (2-3x) with long time exits (40-60 days, 12-26 weeks); tight stops on O'Neil breakouts cut the trend early. Keep the wide-stop/long-hold exit on any version that gets wired.

### 2026-11-16 IST: Elder stop-offset and round-number stops, 5m (B-606, run 43777004230)
- 84 tags on 5m bars over 60 days, 0.8% cost. All fail: best PFnet 0.305 (brk20 long, round-number snap), gross PF at most 0.993. Caveat: only 120 of 5,446 symbols returned 5m data, so this is a thin slice (B-1614 re-runs it wider).
- The stop variants again cluster tightly; nothing in stop placement lifts any cell near 1.
- Profit-booking / exit takeaway: across 1d, 1h, 15m and 5m the stop's exact position is never the lever; cost per trade against hold length decides. Intraday Elder breakout/dip entries stay off whatever the stop.

### 2026-11-16 IST: Chan extension rerun with full cell tables (B-783, run 43777006555)
- 758 cells across 1d (446), 4h (90), 1h (90), 15m (66) and 5m (66), 0.8% cost, every cell committed as a TSV (the old run only printed ~80 per timeframe). Pass PFnet > 1: 1d 47, 4h 2, 1h 1, 15m 14, 5m 18. 469 tags are new to the registry; the rest were already registered from the old log slice and keep those numbers.
- Leaders: chan_tsm lookback-sign long 1d atr2.5 h25 lb20 (2.35, n 943); Kalman band 5m short atr4 h40 z2 (2.01, n 1321); Kalman band 15m long atr4 h40 z2 (1.45, n 660); Kalman band 4h long atr4 z2 (1.24, n 11565).
- Kalman band passes cluster at the widest stop (4 ATR) and the stricter z=2 entry; z=1 cells with 1.5 ATR stops fail on every timeframe.
- Caveat: overlapping signals, no IS/OOS. Passing cells need the non-overlap rerun and a main.py replay before wiring.
- Profit-booking / exit takeaway: mean-reversion bands only pay with a wide stop (4 ATR) that lets the reversion finish; tight stops turn Kalman reversion into a loss on every candle size.

### 2026-11-16 IST: O'Neil base patterns rerun (B-783, run 43770029152)
- Same 1,218 cells on 1d and 1w as run 38193479637 (2026-10-12), on a month more data, 0.8% cost. Pass PFnet > 1: 1d 373 (was 402), 1w 626 (was 703). 113 cells fell below 1.00, 7 rose above. Registry now takes the newest run's numbers (strategy_registry_oneilcup.py newest-run-first).
- 39 of the cells that fell are in the live viable stack (cup-handle, flat-base, saucer, new-high first, pivot, double-bottom). Almost all were marginal before (1.00-1.10) and are 0.89-1.00 now: a thin edge that one more month of data erases.
- Profit-booking / exit takeaway: O'Neil cells within ~0.1 of 1.00 are noise; the robust ones keep a wide ATR stop and a long time exit. The marginal cells' exits (tight pct7/pct8 stops, 20-day holds) are where the edge vanished.

### 2026-11-16 IST: Chan Kalman 1d trailing-stop overlays on the wired cell (B-1485, run 43781409223)
- main.py-function replay of the wired cell chan_kalman__band_srcmain__long__1d__atr4d0_hold40_ve10d0e4_z2d0__v1, 2,238 symbols, 0.8% cost. Idealised no-band baseline (off) PFnet 1.355; live model with Kotak's 10% band-clamped resting stop 1.237 (n 27,741, 5.8-day hold, 0.113% net a day).
- None of the 11 trail overlays beats the fixed live stop. Chandelier 1.5-3R, breakeven 1R/2R and LTP 1.5R/2R are no-ops (identical trades: the mean-reversion state exit closes first). Tight trails hurt: tr0d5 1.133, lt0d5 1.125, lt1 1.225.
- 1,489 trades hit the band-floor stop at PFnet 0.004: the band clamp, not the strategy stop, is what costs 0.12 PFnet against the idealised replay.
- Profit-booking / exit takeaway: Kalman reversion exits on its own state flip within ~6 days; a trailing stop adds nothing and a tight one cuts winners. Keep the fixed 4 ATR stop; no trail wired.

### 2026-11-16 IST: Chan Kalman 1h trailing-stop overlays on the wired cell (B-1485, run 43784674972)
- main.py-function replay of chan_kalman__band_srcmain__long__1h__atr4d0_hold40_ve10d0e4_z2d0__v1, 2,418 symbols, 0.8% cost. Idealised baseline 1.084 (n 5,290); live band-clamped resting stop 1.031 (n 5,802, 5-bar hold): barely above 1.
- No trail beats the fixed live stop. Wide trails are no-ops (1.029-1.032); tight ones push it below 1 (tr0d5 0.992, lt0d5 0.959).
- Profit-booking / exit takeaway: the 1h Kalman edge is thin (1.03 live) and any tight trail erases it; keep the fixed 4 ATR stop. The cell stays wired under the PFnet > 1 rule but ranks low on return per day.

### 2026-11-16 IST: Minervini wired cells, trailing-stop overlays (B-1485, sector-rotation-backtest.yml TF=live_cells)
- main.py-function replay of all 28 wired MINERVINI_LAB_LIVE_CELLS (pct8 hard stop, 40-bar hold) with Kotak's band-clamped resting stop and 11 trail overlays, 0.8% cost; 336 new tags registered. Live fixed PFnet ranges 1.068-1.449.
- A trail beats the fixed live stop on 15 of 28 cells, mostly the wide chandelier trails (tr2/tr3: e.g. updown_vol_pos off 1.309 -> 1.400, pivot_vol2x on 1.316 -> 1.385, ma200_rising off 1.092 -> lt2 1.182) and they also raise return per day. Tight trails (0.5R) never win.
- Profit-booking / exit takeaway: Minervini VCP breakouts are trend trades, so a wide 2-3R chandelier trail locks in runs the fixed pct8 stop gives back; this is the opposite of the Kalman reversion cells, where trails do nothing. Wiring the winning trails changes real exits, so it goes to the user first.

### 2026-11-16 IST - B-1485: trailing stops wired for Minervini lab + Chan Kalman 1d (user OK)
User: "If trailing SL has better results then replace fix SL with TRAILING SL". The two main-replay trail runs were added to the B-1500 exit-variant generator, so each new entry on these 29 tags picks the best PFnet > 1.00 exit variant by return per day (first that passes the viability gate). A trail is now first on 25 of 28 Minervini cells (tr3/tr2/lt2/be1/be2 mostly) and on Chan 1d (tr1, PFnet 1.236 vs fixed 1.237, faster turnover); fixed stays first on 3 Minervini cells (dryup_on h40, held_up_vs_index_off, tight_closes5_on). Open positions are untouched.
Profit-booking / exit takeaway: on breakout swing cells a 2-3R close-based chandelier usually books more per day than the frozen initial stop without giving up PFnet; where it doesn't, the fixed stop stays.

### 2026-11-16 IST - brk20 1h long: trailing stop vs fixed (B-1485, run 43803665426)
brk20-min-rr-main-replay.yml band_cap=trail on the two wired 1h cells (full NSE, real main.py fns, 0.8% cost). Fixed resting stop: atr3_rr4 1.373 (n 2133, hold 13.5 bars), atr4_rr4 1.716 (n 1110, 15.2 bars). Peak-HIGH trail 0.5R (trailltp0d5r): atr3 1.582 (hold 10.0), atr4 2.014 (hold 12.5) - best of every mode on both cells; ltp1r/1.5r/2r next (1.47-1.94); close-based chandelier tr0.5-tr3 and breakeven be1/be2 are at or below fixed. Wired: SWING_1H_PEAK_LTP_TRAIL_CELLS, walked in _brk20_long_1h_exit from the bar after the fill bar, before the strategy exit; peak stored so the Kotak resting stop and the 30 s breach sweep follow it. 26 rows registered (variant main_replay_b1485).
Profit-booking / exit takeaway: on 1h breakouts the tightest high-based trail (0.5R under the highest completed high) wins on both PF and turnover - it converts the many EMA13 rule exits that gave back gains (rule-exit PFnet ~0.9-1.15) into trail exits at PFnet 1.4-2.0; close-based and breakeven trails do not help here.

### 2026-11-16 IST - daily review: swing exit state lost after the Upstash slot switch (B-1615)
After the 14-Nov switch to Upstash slot 1 (stale-DB mask) every deploy restarted on an empty signal_state_swing; 8 real daily holdings kept only their resting SL, with no strategy trail, rule exit or max hold. 1h cells and order_block_delta recovered through their rebuild paths, the rest did not.
Profit-booking / exit takeaway: an exit rule that silently stops running is a profit leak even while the position looks "protected"; every live strategy needs a rebuild path for its exit state, and the daily review must flag retry_refused_no_paper_exit as P0.

## 2026-11-16 IST - B-1566: why replay-firing cells never fired live (three wiring gaps)
- The fire-rate audit (run 43847937784) found 19 cells that fired in the replay on 16-Nov but showed 0 fired / blocked / attempts live.
- Cause 1: the buy engine returned `waiting_for_opening_range` before 09:30 IST ahead of every chan/gap cell, so the 09:15-09:25 signals (TMPV long, KALYANKJIL short) were never evaluated. Only the ORB entry waits now.
- Cause 2: live chan band entries read Yahoo's still-forming bar while the replay fires on the completed signal bar (fill = next open). `_chan_completed_frame` now drops the forming bar.
- Cause 3: triggers on symbols another engine already holds (TMPV, HCLTECH swing) were counted but never shown; /entry-funnel now reports `blocked_by_position`.
- Still open: ZYDUSLIFE macddiv 1h at 11:15. Re-run the audit after deploy.
- Lesson: a replay is only evidence for the live path when live sees the same bars at the same moment. Check early returns and forming-bar handling first.
- Profit-booking / exit takeaway: unchanged here. These fixes affect only which entries fire; exits are untouched (managed on the same frames as before).

## 2026-11-16 IST - B-1485: O'Neil leaders firsthigh 1d trail stops (run 43813215559)
- Full NSE (2182 symbols), strict FIFO, cost 0.8%, rsbandfloor fixed stop vs 11 trail rules.
- Results (PFnet / return per day):
  - wired fixed: 1.577 / 0.1121%
  - rsbandfloor fixed: 1.620 / 0.1195%
  - chandelier 2R (tr2): 1.613 / 0.1207%
  - breakeven at 2R (be2): 1.631 / 0.1206%
  - be2 in-sample / out-of-sample: 2.222 / 1.090, vs 2.214 / 1.079 for rsbandfloor fixed
- Tight trails lose badly: 0.5R peak-LTP 0.837, 0.5R chandelier 0.867. They cut the O'Neil winners that need room.
- 6,048 new tags registered (research). Per-entry variant order now: tr2, be2, fixed, ...
- Profit-booking / exit takeaway: on O'Neil breakouts, trail only after the trade has 2R of room (chandelier 2R or breakeven at 2R). Trails tighter than 1.5R give back the edge.

### B-1615 (2026-11-16 IST): daily swing exit state rebuild after a state loss
A lost signal_state_swing row silently turns a strategy position into a "stop-only" position: the trailing stop, rule exit and max hold stop running, and only the wide entry stop remains (UPL and TATASTEEL were guarded at 4xATR instead of their peak-high minus 0.5R trail). Every strategy family now has a rebuild path (gap_and_go, order_block_delta, 1h/4h cells, and the generic daily one), derived only from the real row, the entry-day stop and completed bars.
Profit-booking / exit takeaway: a trail that is not being computed is a profit giveback; restoring state honestly from bars brings back the strategy's own profit-booking, and the rebuild itself never sells.

### B-1618 (2026-11-17 IST): weekly context review
Skill descriptions are loaded into every turn, the skill bodies only when invoked; long multi-line descriptions on rarely used skills were the cheapest always-on cost to cut (8.9k to 1.9k chars). Unused MCP connectors remain the biggest always-on cost and need the user to disconnect them.
Profit-booking / exit takeaway: none directly; lower context per turn leaves more room for exit and governance checks in long sessions.

### B-1619 (2026-11-17 IST): memory housekeeping keyed to tick count starved on slow ticks
A periodic job scheduled "every N ticks" silently assumes a tick length. Live ticks ran 5-10x slower than assumed, so the memory trim never fired and the process was OOM-killed 8 times in one market session. Housekeeping now has a wall-clock floor and an independent watchdog-thread guard that trims at 55% RSS and clears caches at 75%.
Profit-booking / exit takeaway: every restart mid-session pauses trailing-stop and exit management for minutes; keeping the process alive is a precondition for booking profit on schedule.

### B-1622 (2026-11-17 IST): late cron runs mislabel the daily SL snapshot
GitHub schedules can run hours late; anything that dates its output by the run clock mislabels the day. Date data by its own timestamps.
Profit-booking / exit takeaway: SL history must map to the right trading day, or reviews of stop placement and trail giveback compare the wrong day's exits.

## 2026-11-17 IST - B-1623 Upstash daily hard stop refused real-money mirrors (daily review)
- A day budget is a pacing tool for a monthly quota. Its hard stop must not refuse real-money state while the month
  has headroom: 878 MB on 17-Nov (11 restarts re-reading restore keys) froze the restart heartbeat and refused the
  real_positions mirrors with the month at 15%.
- Restarts cost twice: lost intraday state, plus restore reads that burn the storage budget.
- Profit-booking / exit takeaway: trail and exit state must survive a restart, so the mirrors that carry it are never
  the writes a budget guard cuts first.

## 2026-11-18 IST - B-871/B-967 overnight cash short retest (Kotak rejects both products)
- 1-share IDEA-EQ SELL, market order. NRML: RMS block "SHORT SELLING NOT ALLOWED IN NRML PRODUCT, USE MIS".
  CNC: rejected on the T1 holdings check (a CNC sell is a delivery sale of shares held, not a short).
- Same answer as 20-Oct (B-967): an equity cash short cannot be carried overnight at Kotak. Only MIS (intraday,
  auto-squared) shorts are possible; multi-day shorts need stock futures or puts (B-1339, capital-gated).
- Never use CNC as a "short" product in code: if the name is held, it sells a real holding instead.
- Profit-booking / exit takeaway: 1d short signals (brk20 short, best PFnet on record) can only be booked intraday
  in cash, so their profit stays paper until a futures route is affordable; size research toward MIS-exit variants.

## 2026-11-18 IST - B-1625 swing pattern-cell scan crash loop (4 market-hours OOM restarts)
- A 1d signal on completed bars has one answer per day; recomputing it on every 15-min repeat pass and on every boot
  cost ~950 MB per run and, with the tick prefetch on top, crossed the 2 GB limit every ~40 min.
- Cache day-constant signals by bar identity and mirror the small result so a restart does not redo the heavy work.
- Profit-booking / exit takeaway: every restart drops intraday trail and exit state and leaves UNLOGGED casualties,
  so memory spikes in entry scans directly cost exit quality; heavy entry scans must never share the peak with exits.

### 2026-11-18 daily review: crash loop cost and stops (B-1629)
Render restarted about every 39 min in market hours. The spike is the tick/bar-sweep OHLC prefetch (+747 MB in one run), not a Python object leak (the gc object count was flat). ASHOKLEY's 15m long (chan_kalman) was stopped 74 min after entry; INFY and UPL exited at the open via the entry-day stop and the B-1486 trail. Equity shorts at Kotak: CNC and NRML are both rejected (re-confirmed).
Profit-booking / exit takeaway: exits worked as designed at the open; the bigger profit leak today is scan downtime from restarts, so end the crash loop before tuning exits.

## 2026-11-19 IST - Daily review: time-exit backstop, off-hours real exit, unlogged intraday entry
- B-1637 backstop sold 8 dateless holdings in 3 min at 11:16 IST; every one Kotak-confirmed. Holdings with no strategy
  time stop are now never held open-ended.
- ADANIENSOL: a 1h max-hold timeout evaluated at 00:13 IST sent a real market SELL with the market shut (rejected, no
  LTP). An exit decision made off-hours must wait for the open, not hit the broker.
- HCLTECH: 1h macddiv entry at the open, stopped 56 min later. One day; goes to the exit audit, not a tune.
- Profit-booking / exit takeaway: an exit rule's timing (max-hold clock) must be evaluated against session hours, and a
  profit target that cannot rest at Kotak (ATGL, RMS T1) leaves a winner with only the paper signal to exit it.

## 2026-11-20 IST - Exit timing: deadline timestamp and on-time check (B-1651)
- User asked that positions with their exit due today show an exit timestamp on View 4 and be checked for exiting on
  time. Before B-1651 View 4 showed a swing exit date only, and nothing compared the actual exit time with it.
- Deadline: intraday = square-off or max-hold minute (+5 min grace); swing = 15:10 IST on the expected exit day. Actual
  exit = the app's confirmed exit order time, else the time the position was seen gone from Kotak-aligned tables.
- Profit-booking / exit takeaway: a time exit that slips a day is held risk with no edge left in it; measuring the
  slip per position is how we learn whether the max-hold clock is being honoured before tuning the hold itself.

## 2026-11-20 IST - Daily review: no restarts, slow ticks, unlogged UNIONBANK sell
- First full session with no Render restart since the OOM loop (B-1641 held). Day -Rs24.80 on Rs911 deployed.
- Two intraday chan_kalman entries (APLAPOLLO 5m, VEDL 15m) both exited within ~1 h; APLAPOLLO stopped in 22 min.
- The tick holding each 15-min bar sweep runs ~450 s, so exits and trails can wait ~7.5 min (B-1650).
- Profit-booking / exit takeaway: an exit is only as good as the loop that sends it; a 7-minute scheduler stall can
  turn a planned stop or a 5m exit into a worse fill, so loop latency comes before tuning exit rules.

## 2026-11-21 IST - Account reconcile: DP charges eat small delivery trades (B-1658, B-1659)
- Net deposited since 1 Sep is Rs27,000 (deposits Rs39,849.12 less payouts Rs12,849.12, one of them Kotak's automatic SEBI quarterly settlement). Account value at market Rs26,208.88 -> loss Rs791 (2.9%) in about 11 weeks.
- Kotak's ledger shows Rs424.80 of DP transaction charges to 14-Nov (Rs23.60 per scrip per sell-day out of holdings): over half the loss. The 0.8% cost model never counted it.
- Since the fill ledger began (2-Nov) the bot itself is +Rs21 realised and +Rs394 unrealised before DP charges, so the strategies are roughly break-even; the leak is fixed per-trade costs on tiny (often 1-share) delivery positions.
- Profit-booking / exit takeaway: a delivery exit costs a flat Rs23.60 on top of the % costs, so on a Rs200 position the exit alone needs a +12% move to break even; size delivery trades so the flat charge stays small (about Rs4,700+ for 0.5%), or prefer same-day (MIS) exits for small positions.

## 2026-11-21 IST - Restart dropped buy-engine ownership; exit refused, position rerouted to swing (B-1661, B-1567)
ASHOKLEY (chan_kalman 15m long, entered 18-Nov 09:39 IST) lost its `strategy` tag when Render restarted at 10:16 IST:
both real_positions restore paths re-inserted the row without that column. The 10:33 IST state exit was then refused as
swing-owned and the holding moved to the swing engine, so a 40-bar intraday strategy became an unplanned overnight hold.
Any field an ownership or exit rule reads must survive every restore path; the restore tests now check `strategy`.
Profit-booking / exit takeaway: an exit the strategy wanted but the app refused is an unplanned hold with no edge behind it; ownership tags must survive restarts or the exit plan silently changes owner.

## 2026-11-21 IST - DP charge priced into swing viability (B-1659)
A flat Rs23.60 DP charge per delivery sell is a percentage cost that grows as the position shrinks. Re-pricing each
strategy's pooled PFnet at 0.8% + 23.60/notional (derived exactly from pfgross, pfnet and win rate) gives a break-even
position size per strategy: ~Rs6,900 for macddiv hist 1h (PFnet 1.138), ~Rs200 for O'Neil leaders 1w (PFnet 2.669).
Thin-edge, high-frequency swing cells cannot be traded profitably at 1-share sizes on a ~Rs26k account.
Profit-booking / exit takeaway: every delivery exit pays a fixed Rs23.60, so fewer, larger swing exits beat many 1-share exits; thin-edge cells need a position size that makes the fixed exit cost small.

### B-1581 (2026-11-21 IST): an exit and a stop placement on the same stock must take turns
UPL (18-Nov 09:15) and CANBK (19-Nov 11:16 IST): the exit sweep cancelled the stop and sent a market SELL; a separate
protect pass, working from an order book read a few seconds earlier, saw "no live SL" and sent a new one. Kotak rejected
it ("Check T1 holdings"), which raised a false SL-failure alarm and a T1 flag. Kotak's book lags this process's own
orders by seconds, so the process must remember its own close (in-flight note, 120 s) and serialise close and stop per
symbol, while still deriving "how much is left" from Kotak so a partial close keeps the rest protected.
Profit-booking / exit takeaway: an exit is only clean when nothing re-protects the shares being sold; a stop re-placed on
sold shares is noise at best, and on futures/MCX it could open an unintended short (B-1663).

### 2026-11-21 IST: Kotak "Net" vs ledger (B-1664, closed not-a-bug)
Kotak `limits()['Net']` already deducts the day's unsettled net buy obligation; the Daily Margin Statement ledger does not until T+1. Reconciling account value against the ledger alone double-counts that day's buys (they are already in positions at market). Contract notes 12-20 Nov matched every bot exit qty and value exactly.
Profit-booking / exit takeaway: realised exits are recorded at Kotak's true fill values, so per-trade P&L in View 4 can be trusted for exit-rule research; the overall loss vs deposits is mostly pre-2-Nov history, not recent exits.

### 2026-11-21 IST: Elder indicators at 4h (B-1598 re-run, run 44910415485)
- Full NSE universe, 730d of 4h bars, 0.8% cost, both directions, ATR sweep: 300 tags, 19,640 symbol-fetches with data, 0 pass (pooled PFnet > 1.00). Best adx_bell__ring_bell_ema13__long__4h__atr3_pts3__v1 PFnet 0.803 (n=28,858); top 5 are all ring_bell_ema13 long. Same family led at 1h (0.714), so 4h helps it but not past cost.
- Elder indicators now fail on every candle size tested (5m, 15m, 1h, 4h); the 4h-fetch bug (B-1598) did not hide a winner here.
- Profit-booking / exit takeaway: the longer bar lifts PFnet by about 0.09 because fewer, larger moves absorb the 0.8% cost better, but the max-hold timeout still closes most trades before they reach their target; any further attempt should test a trailing exit on ring_bell_ema13 longs rather than a tighter stop.

### 2026-11-21 IST: Elder batch3 at 4h (run 44912888789)
402 new 4h tags on the full NSE harness universe (15,006 symbols fetched, 730d, 0.8% cost). Only 4 pass, all the RSI 80/20 oscillator reversal: long atr3 PFnet 1.130 (n=7329), long atr2 1.054, long atr1d5 1.013, short atr3 1.012. Structure, channel, sizing, breadth and ORB families all fail at 4h. Wider ATR stops help the reversal edge monotonically (1.5 < 2 < 3), so the edge needs room to work. The 1d breadth "passes" (n=1-13) are not evidence. Port + main.py replay owed (B-1665).
Profit-booking / exit takeaway: the reversal edge grows with a wider stop, so test an ATR-3 trailing exit (not a tight fixed target) on the main.py replay before wiring.

### 2026-11-21 IST: Elder MACD/dirgap and swing min-RR at 4h (runs 44922538831, 44923936618)
Dirgap 4h: 120 tags, none pass (best gaps common_fade long atr3_nb4 0.991, n=10,587); MACD and directional-system cells all fail at 4h as at 1d. Swing min-RR 4h: 162 tags, only brk20 with ATR-3 stop and RR4 passes, short 1.461 (n=450) beats long 1.231 (n=571), the same short-over-long ordering seen at 1d and 1h; order_block and volume_profile fail. The brk20 RR4 edge holds across 1d/1h/4h, so it is the most robust candidate here. Port + main.py replay owed (B-1667). The dirgap harness universe (about 2.8k per family) needs a full-universe check (B-1666).
Profit-booking / exit takeaway: a fixed 4R target only works with a wide ATR-3 stop; tighter stops fail, so on the replay compare the RR4 target against a trail that lets winners run past 4R.

### 2026-11-21 IST: Douglas trade-management and MACD divergence at 4h (runs 44925787905, 44926740738)
Douglas 4h: 504 tags, 6 pass, all brk20 min-RR long: atr3_rr4 3.556 (n=585), rr3 2.087, rr2d5 1.536, rr2 1.225, atr2_rr4 1.195, atr3_rr1d5 1.088 (n=7,288). PFnet rises steadily with the reward:risk target, and only the wide ATR-3 stop survives the smaller targets. This independently confirms the swing min-RR 4h brk20 result. MACD divergence 4h: 36 tags, all fail (0.615-0.77). Harness universes: docs/nse_universe.json is 2,763 symbols, so "summed over families" counts (5,526 / 7,365 / 8,289) are multiples of the full universe, not partial runs (B-1666 closed).
Profit-booking / exit takeaway: the bigger the target, the higher the PFnet, at the cost of fewer trades. On the main.py replay (B-1667), rank RR4 against RR3 and a trail by return per day, not by PFnet alone.

### 2026-11-21 IST: Portfolio overlay, descending triangle and island reversal at 4h (runs 44928192937, 44928195720, 44928797980)
Overlay 4h: 768 tags, 27 pass (brk20_year long y2023 atr3 2.792, dip_month long m4 1.742 at n=15,248). The script stamped __1d__ in tags for a 4h run (fixed: merge --interval). Tri-desc 4h on main.py functions: 33 of 48 pass, but n is only 42-162. Island 4h: 66 of 102 pass, but the strongest in-sample cell (gap05 long ~2.89) drops to 0.93-0.98 out of sample; turn1cr long holds 1.26-1.30 out of sample (n~2,030), so it is the real candidate. In-sample-only strength is not evidence: check the segoos twin first.
Profit-booking / exit takeaway: on tri-desc the 0.5R trail beats wider trails at 4h (1.596 vs 1.476), so take profit early on triangle breakdowns and breakouts at this candle size.

### 2026-11-23 IST - B-1676 fno_mostactive_momo__top3_max_gain__long_opt__5m__trail2__v1 (PAPER forward test, no result yet)
Category: options (Single leg option). Every 5 min 09:30-14:30 IST the top 3 index options by contracts traded per index (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50; NSE most-active lists, View 6) are scanned; the largest positive % change is bought (paper) only when its index and NIFTY 50 agree (CE both up, PE both down, from NSE allIndices percentChange). One position at a time. No backtest exists (NSE gives no history of the most-active ranking), so this is forward paper only; metrics=None in the registry until enough paper trades exist. Risk: chasing the day's biggest % gainer buys premium after the move; a 2% trail on a premium that moves 5-20% in minutes may stop out on noise, and the 0.8% round-trip cost is 40% of the trail width.
Profit-booking / exit takeaway: exits are a 2% trail from peak premium (checked every 30 s tick on a 60 s-cached price), confidence loss (out of its index top 3 or sentiment flip) and a forced 15:15 IST exit; compare the trail exits' net against the confidence-loss exits once n >= 30.

### 2026-11-23 IST: B-1677 strict sentiment variant for the most-active option momentum paper test
- The user asked for a stricter sentiment check. Rather than replace v1, a second immutable tag runs beside it on the same data, so the gate's value is measured, not assumed: same pick, same exits, only the entry filter differs (move >= 0.25%, index beyond its open, NIFTY breadth >= 1.5x, VIX not spiking for CEs).
- Expect fewer trades; the question is whether net % per trade and per day rise enough to offset the lost count.
- Profit-booking / exit takeaway: exits are identical (2% trail from peak, top-3 or sentiment loss, 15:15 IST), so any difference in net comes from entry quality alone; if strict wins mostly through fewer 2% trail stop-outs, the trail is the next thing to test, not the gate.

### 2026-11-23 IST: B-1676 first live paper trades, the 2% trail on an expiry-day premium (B-1679)
- BANKNIFTY 63000 PE (expiry day, +168% on the day) entered 12:07 IST at 169.75 and was next seen at 117.25: -31.73% net on a 2% trail. Re-entered 12:17 IST at 117.60, exited 127.55 on the trail: +7.66%. Today: 2 trades, 1 win, -24.07% summed.
- The paper exit only sees a 60 s-cached, 1-3 min delayed snapshot, so on expiry-day gamma the trail level is gapped through between samples; the paper loss is the observed gap, not what a resting SL-M would fill at (that would slip too, but by less).
- Profit-booking / exit takeaway: a 2% trail only means something with tick-level prices and a resting stop; with minute-level sampling report both the trail-level exit and the observed exit, and test skipping expiry-day contracts, where premiums move 30% between samples.

## 2026-11-23 B-1679 (d): why a "2% trail" printed -31.73%, and the paper fill model (B-1676/B-1677)
- The stop was already 2% under the entry from the first tick (169.75 -> SL 166.36). The loss came from observation, not the
  rule: the paper saw the premium only through NSE's most-active snapshot (1-3 min delayed, cached 60 s), and on an
  expiry-week BANKNIFTY PE with the index -2% the next price it saw was 117.25. A real SL-M resting at the exchange would
  have triggered near 166.
- Fix: the held contract is re-quoted from its own expiry chain every 30 s tick; a trailing_sl exit fills at the resting stop
  level (SL-M model) and the observed price + its net are stored beside it, so both the optimistic and the pessimistic
  number are visible; contracts expiring today are never picked.
- Bias to remember: the stop-level fill is optimistic in a true gap (a real SL-M fills at the market). Judge the variants on
  BOTH net columns before any real-money discussion.
- Profit-booking / exit takeaway: a tight 2% trail only means 2% if the stop rests at the exchange; any exit checked by
  polling must be priced at the observed print, so real options exits must always be resting SL-M orders, never polled.

## 2026-11-23 B-1681: OI + Greeks for option-buying entries (research read + prior rules)
- OI grid (broker/education sources): premium up + OI up = long buildup; premium up + OI down = short covering; down + up =
  short buildup; down + down = long unwinding. Every source warns these are descriptive, not signals, and that intraday and
  expiry-rollover OI moves are noisy. So OI is used only as a filter (skip short covering), never as the trigger.
- Greeks are computed from the premium's own Black-Scholes implied vol (no IV feed needed). For an ATM option theta/premium
  is about 1/(2 x days to expiry), so a theta cap is really a days-to-expiry floor: 15%/day allows ~3.3+ days for ATM and
  rejects most OTM weeklies on their last days, the exact contracts that gapped through the 2% stop today.
- No backtest is possible yet (no free intraday option-premium history); View 6 says so instead of showing a number.
- Profit-booking / exit takeaway: a high-theta contract loses premium every minute it is held, so the entry filter (theta
  cap, delta band) matters as much as the 2% trail; test exits only on contracts the filter would admit.


### B-1684 / B-1685 paper data durability and the rolling 15-min change (2026-11-23 IST)
- The 12:33 BANKNIFTY PE paper row was still open at 19:42 IST: its 15:15 close never reached Upstash, so the 17:44
  reboot restored the 12:33 copy. A paper strategy whose exits are not durable gives a false record, and a false record
  can never justify real-money wiring. Now: no write before the restore, an off-window EOD sweep, and pass health.
- The 15-min change is rolling (now vs exactly 15 min ago), not a fixed 15-min block.
- Profit-booking / exit takeaway: single-leg options move fast, so an exit that silently fails to record (or fire) is the
  costliest loose end; every exit path needs a backstop that runs even when the normal pass did not.

### 2026-11-23 IST: B-1687 (b) View 6 tape for the strict-sentiment + OI/Greeks option backtest
- No free intraday option-premium history exists, so the bot now records its own: one row per minute of the
  top 15 contracts per index (premium, OI, OI change, IV, spot). After ~20 trading days it replays through the
  real `_fno_momo_step`, the only honest 5m backtest of this strategy. Until then, no threshold is tuned.
- Profit-booking / exit takeaway: the tape keeps every minute's premium, so the replay can measure the 2% trail
  against wider trails and peak-vs-exit give-back on real intraday paths, not daily bars.

### 2026-11-23 IST: B-1688 tape widened to ATM +-10 strikes of every index chain, plus India VIX
- The most-active list only shows contracts that already traded heavily, so a replay could never ask "what would a strike two away from ATM have done". Storing the whole ATM +-10 window (CE and PE, nearest expiry) every minute lets the backtest test strike choice (ATM vs 1-3 OTM), not only the top-3-by-volume rule.
- VIX is stored per minute so the strict gate's VIX +5% CE block can be replayed and swept (3/5/8%) instead of taken on faith.
- Profit-booking / exit takeaway: with the full strike ladder per minute, the trailing-SL sweep can be run per moneyness bucket; expect OTM legs to need a wider trail than ATM (higher % noise), so do not carry one trail % across strikes without testing it.

### 2026-11-23 IST: B-1690 Greeks on every tape leg
- Per-minute delta/gamma/theta/vega/IV for the whole ATM +-10 ladder lets the replay look for patterns such as IV expanding while delta rises (momentum with vol bid) vs IV crush, and gamma peaks near expiry.
- Profit-booking / exit takeaway: test exits keyed to Greek changes (e.g. exit when IV drops N points from entry, or when theta per day exceeds X% of the premium) against the flat 2% trail; pick by pooled PFnet, not one day.

### 2026-11-24 IST: B-1691 Upstash month cap blind to untracked days
- A quota guard that only counts days it recorded under-reports the month when tracking starts mid-month; assume the budget was spent on unrecorded days and prefer the provider's own figure.
- Profit-booking / exit takeaway: no direct exit change; exit/SL state is exempt from the pause, so trailing exits keep their Upstash mirror while research writers back off.

### 2026-11-24 IST: B-1692 weekly context review
- One reusable key-extractor for diag logs beats writing a parser per check; unused connectors are the largest remaining always-loaded cost.
- Profit-booking / exit takeaway: none directly; cheaper checks leave more budget for exit research.

### 2026-11-24 IST: B-1693 protection snapshot missed holdings
- A protection report built from positions() alone gives an all-clear for delivery holdings; every holding has to be counted from holdings() too.
- Profit-booking / exit takeaway: an exit can only be trusted if its stop is visible in the status; a hidden naked holding is an unmanaged exit.

### 2026-11-24 IST: B-1695 holiday read as a broker outage
- Before calling a broker error an outage, check the exchange calendar: "ADAPTER is down" on 10-Nov and 24-Nov were both NSE holidays.
- Profit-booking / exit takeaway: exits and SLs must key off the exchange calendar; sending them on a closed day only burns broker rate limits that the next open's protection needs.

### 2026-11-24 IST: B-1697, Upstash writes off on NSE-closed days (Nov 2026)
The user asked that Upstash not be used on NSE-closed days of Nov 2026, to save its monthly quota. The B-1576 daily-pause path already refuses a write by raising, leaving the mirror's change-cache unset so it pushes next time; the closed-day gate reuses it, so no mirror needs its own change. Real-money state stays exempt (MCX trades on some NSE holidays, and a restart must never lose an open position), and reads stay on so a restore after a wipe still works.
Profit-booking / exit takeaway: exits and stops are unaffected; real positions and their SL state keep mirroring every day, so a closed-day restart cannot drop an exit.

### 2026-11-24 IST: B-1698, Upstash spend is reads, and failed writes can cause read loops
On 24-Nov, 97% of Upstash bytes were GETs: the option-candle boot restore (15 days, about 95 MB per boot), a table restore retried every minute without backoff (real_fo_trades, 57 MB), the viable-stack read-back, and a restart-tracker loop where a refused write left a flag unset so it re-read two keys every minute. Budgeting writes alone saves almost nothing. Every retry path needs a backoff, and a refused write must not trigger a re-read loop. Each deploy also costs one boot restore, so batch deploys while quota is tight.
Profit-booking / exit takeaway: exits depend on real-money state, which stays mirrored. Keeping Upstash under its monthly cap is what keeps entries and exits running, so quota is now treated as a trading risk.

### 2026-11-24 IST: daily review, T1 quantity on exit retries (B-1699)
GAIL's timeout exit on 23-Nov was retried 4 times at the close for a quantity Kotak would not release (part of the holding was still T1). Each retry was rejected, so the retries added risk of a late, noisy close and gained nothing. Exit retries must size to Kotak's sellable quantity, not the app's total.
Profit-booking / exit takeaway: on a timeout exit, sell what is sellable now and queue the T1 remainder for the next session's open, under the same exit reason and with its SL kept.

### 2026-11-24 IST: Nov-2026 Kotak P&L vs the cost model (B-1700 to B-1702)
The Kotak statement shows charges of 0.15% round trip: about 0.22% on delivery and about 0.03% on intraday, with brokerage about zero. The 0.8% model assumed 0.20%/side brokerage that is not being charged. Nov net was Rs 66.57 on Rs 129.58 gross, so charges took 49% of gross even at the real rate. The month's profit came almost entirely from one swing winner (Bank of India +Rs 195). Intraday lost money gross; short-term delivery made it.
Profit-booking / exit takeaway: the swing/delivery holds carried the month, so let delivery winners run on the trail rather than cutting them early. Intraday exits lost money even before costs, so intraday needs a better edge, not cheaper costs.

### 2026-11-24 IST: product cost re-score and the 5-loser exit review (B-1700, B-1703, B-1705)
Re-pricing the registry from 0.8% to product costs (intraday 0.10%, delivery 0.35%) admits 1,672 more strategies into View 1. The intraday additions are high-frequency 5m scalps whose profit factor goes from 0.7 to about 3.0 on the cost assumption alone, so slippage must be measured before they trade real money. The DP charge (Rs23.60 per delivery sell) turned November from +Rs66.57 to about -Rs712. Of the 5 biggest losers, 2 gave back real open profit (IRFC +2.4%, Cochin Shipyard +4%) and 2 were stopped and then recovered.
Profit-booking / exit takeaway: once a swing trade is about 2% up, move its stop to at least entry plus cost and DP, so open profit is not handed back. This needs a full-universe replay before any change ships.


### 2026-11-24 IST: B-1700 product cost re-pricing has a performance cost
Re-pricing PFnet per call (effective_pfnet) inside View 1's per-slot loops ran about 3M times per /strategy-viable-stack request (0.4 s -> 4.4 s) and blocked the HTTP loop during a scan. A per-Metrics cache plus a precomputed (strategy, metrics, effective PFnet) table brought it to 0.25 s. Derived metrics used in hot loops must be computed once per registry, not per lookup. The Render views now show "PFnet @ real cost" with the stored 0.8% value alongside, so ranking matches the gate.
Profit-booking / exit takeaway: a cheaper cost model widens what is wired, but exits must still clear the real cost; measure intraday slippage (B-1703) before trusting thin 5m scalps, and keep the breakeven-ratchet research (B-1705) on the swing side.

## 2026-11-24 B-1707: View 4 P&L vs Kotak, DP is the missing cost
- The fill ledger's realised net (+83.72 since 2 Nov) overstated Kotak because Kotak's DP debit (₹23.60 per scrip per delivery-sell day) is billed outside the contract-note charges; November DP was about ₹779, larger than the gross P&L.
- Lot counts must use one unit (Kotak's open set), or the card contradicts itself (21 vs 19).
- Profit-booking / exit takeaway: a delivery exit costs ₹23.60 flat on top of statutory charges, so small-value CNC exits (under ~₹3,000) lose ≥0.8% to DP alone; prefer exiting a scrip's full quantity in one day and favour MIS for small swing sizes where the strategy allows.

## 2026-11-24 B-1709: hard off-hours Upstash block, enforce at the HTTP layer
- The user made off-hours Upstash use strictly zero for Nov 2026. Per-writer throttles (B-1569/B-1576/B-1697/B-1698) never reached zero because ~60 call sites, the lease module and the PING each talk to Upstash directly; one guard on requests.Session.request is the only way to guarantee it.
- Render wipes the disk on restart, so an off-hours boot restores nothing from Upstash. Writes must stay held at the open until the restores re-run, or the first push would overwrite the mirror with the journal-only state.
- Profit-booking / exit takeaway: real exits placed off-hours (MCX/F&O) are not mirrored until 09:00; the exit itself is unaffected (Kotak is ground truth, governance re-reads it every 5 min), but any off-hours exit should be checked against Kotak at the next open.


## 2026-11-25 B-1712: View 6 index chains, a retired fallback hid the real error
- Every index chain fetch failed live (404), but the 404 came from NSE's retired option-chain-indices fallback, not from the v3 call that matters. A fallback to a dead endpoint turns every upstream problem into the same misleading error.
- Rule: name each step in the surfaced error, drop retired endpoints, and skip lapsed expiries (Nov 2026 monthly expiry moved for the 24-Nov holiday).
- Profit-booking / exit takeaway: the paper option strategy's 2% trailing stop reads its premium from these chains when a contract leaves NSE's most-active list; a silent chain outage means the stop runs on stale prices, so chain health must be visible before any option variant is trusted for exits.

## 2026-11-25 B-1713: View 6 adds rolling 5-min and 1-hour premium change
- User asked for 5m and 1h % change beside 15m to raise confidence in option entries. Built as display fields (rolling, base 5:00-6:00 / 60:00-62:00 min old, "warming up" otherwise). 1h samples are thinned to one per 110 s to keep memory small and kept off Upstash (budget spent).
- Lesson: a multi-horizon momentum view (5m > 0, 15m > 0, 1h > 0 all agreeing) is a hypothesis, not an edge, until it is replayed on the per-minute tape with the 0.8% cost model.
- Profit-booking / exit takeaway: a fading 5m change while 15m/1h stay positive is a candidate early-trail signal for option premiums; test it on the tape before it changes any exit.

## 2026-11-25 B-1714: View 6 paper entry plan v2 (OI, Greeks, multi-horizon % change, relative IV)
- Why v1 never entered: it tested ONE contract per scan, the largest day % change. On most days that is a near-expiry strike up hundreds of percent (SENSEX 84000 CE +446%, 1.15 days, theta 29%/day), which fails the theta check, so the whole scan ended. Lesson: rank AFTER filtering, never filter one pre-ranked pick.
- Read-up used for the plan (option buying, intraday):
  - OI: premium up with OI up = long build-up (fresh positions, sturdier move); premium up with OI down = short covering (sharp but short-lived). Only long build-up is bought.
  - Greeks: delta 0.35-0.65 keeps near the money (enough leverage, not a lottery ticket); theta per day vs premium caps time decay; >= 2 days to expiry avoids expiry-eve theta and gamma whipsaw.
  - IV: buying when IV is rich vs the same index's other strikes risks an IV crush even if the index moves the right way; cap at 1.25x the median.
  - % change: day % is the wrong momentum measure for a premium (it reflects yesterday's close and decay); use rolling 5m and 15m rises, require 1h not falling, and skip a >10% 5-min spike (chasing).
  - Market: the strict sentiment gate (index and NIFTY >= 0.25% in direction, beyond the open, breadth >= 1.5x, VIX check) stays.
- All thresholds are stated priors, not tuned; judge on the paper record and a tape replay at >= 30 trades.
- Profit-booking / exit takeaway: a 2% trailing stop on an option premium is inside one minute's normal noise (premiums move 2-5% a minute on active strikes), so most entries will stop out on noise; test a wider or ATR-of-premium trail on the tape before trusting the v2 entry record.

## 2026-11-25 B-1715: fast 5-15 min View 6 paper plan, deduced from research
- User: single-leg option trades exit within 15 min, so a 1-hour input is useless and waiting for it costs entries.
- Research read (abstracts): (1) intraday returns REVERSE most at the 15-min horizon on normal days, CONTINUE on trend/news days and when dealers are short gamma; (2) option momentum clusters in the morning (overnight news digested late) and the afternoon, with a mid-day reversal zone; (3) index option buyers earn intraday and lose overnight; (4) intraday OI repositioning on NIFTY has no robust predictive power; (5) 88-91% of Indian F&O individuals lose, mostly option buyers; spreads 1-3 pts a side decide a scalp.
- Deduction: trade only on trend days (strict sentiment), only in the morning/afternoon windows, require the INDEX itself to be moving now (5-min), buy a fresh 5-min premium rise but not an exhausted 15-min run (> 20%) or a 5-min spike (> 10%), near-ATM delta 0.40-0.60 and premium >= Rs 20 so the spread is a small % of the premium; OI only recorded; hold at most 15 min.
- Profit-booking / exit takeaway: on a 15-min hold the main exit risks are the 15-min reversal and the spread, not theta; a time stop plus a trail is the right shape, but a 2% trail sits inside one minute's noise, so compare 2% vs a wider premium trail on the tape before judging the plan.

## B-1717 (2026-11-25): expiry-day contracts included in the fast View 6 paper plan
User: drop the expiry-day skip, since every trade has a 2% max SL that then trails. New tag `..._alldte__...__v1`, B-1715 tag retired with 0 trades. Risk is capped per trade by the 2% trailing stop, but expiry-day premiums move fastest (gamma highest), so slippage past the stop is likelier and the 15-min time stop matters more. Review at 30 paper trades: split net P&L by expiry-day vs other days.
Profit-booking / exit takeaway: on expiry day the 2% trail is the whole defence; measure gap-through-stop slippage on 0DTE trades before trusting the cap.

## B-1718 (2026-11-25): 2% vs 5% trailing stop, run side by side on the same entries
User asked to test a wider trail along with 2% and see both. Two paper twins share one entry rule (B-1717) and differ only in the trail (2% vs 5% below peak premium). Paired comparison removes entry luck: any P&L difference is the exit alone. Expected trade-off: 2% cuts losers fast but is inside one minute's premium noise, so it is likely stopped out of trades that later win; 5% gives room but each loser costs more. The 15-min time stop caps both.
Profit-booking / exit takeaway: judge the trail on paired trades (same entry), by net P&L per trade and by "2% stopped, 5% later won" count, not by win % alone.

### B-1719 (2026-11-25): keep the full path of every paper option trade
User asked that every entry, exit and detail of single-leg paper option trades be kept for later analysis. Entry and exit fields were already stored and mirrored; missing were the lowest price while open (MAE), the price path, and the setups that were skipped. Without MAE and the path, a trail can only be judged on its exits, not on how close each loser came to recovering or each winner came to being stopped; without the skip log, "would the skipped setup have won?" cannot be answered.
Profit-booking / exit takeaway: with MAE, peak (MFE) and the 30 s path per trade, any trail width (2%, 3%, 5%, ...) can be replayed on the recorded paths without waiting for new live trades.

### 2026-11-25 B-1725: evidence for the View 6 fast-plan rules
An 89-day replay (5-min index proxies, synthetic Black-Scholes premiums, 0.8% cost) plus a literature pass.
- The strict whole-day direction gate is the only entry rule with an edge: CE next-15-min hit rate 53.7%; without the gate PF falls from 0.755 to 0.508.
- The "index moving now" 5-min rule points the wrong way: over 5-15 min, index moves tend to reverse (hit rate 44.3%).
- SEBI: about 91% of individual F&O traders lost money (FY24), mostly option buyers. A buying edge must be shown, not assumed.
Profit-booking / exit takeaway: a 2% trail on an option premium sits inside normal 5-min noise (96% of exits are stop-outs, average peak gain only 2.25%). 15-25% trails with a 60-min hold come close to break-even (PF up to 1.006) where 2-5% with 15 min loses (PF 0.76-0.78). The trail width and hold time are the biggest levers, so test them next on the real recorded paths from B-1719.
Correction (B-1727): with gap-aware stop fills the live 2% plan is PF 0.417. Inside the short-hold constraint (at most 15 min), only a trend-day PULLBACK entry got above PF 1 (best 1.052), and only on the thin FINNIFTY proxy. Quick option trades need an average win well above the 0.8% round-trip cost; momentum chasing on 5-min moves does not provide it.

### 2026-11-25 B-1728: trend-day pullback paper twins built (View 6)
Inside the user's short-trade rule (single leg, quick entry and exit, at most 15 min), the only replay setup above PF 1 was buying the 5-min pullback on a strict trend day. Built as two paper twins (12% and 5% trailing stop, both with a +12% target and the 15-min time stop) beside the fast_v3 2%/5% twins, so all four are judged on the same real 30-s premiums. No real-order path touched.
Profit-booking / exit takeaway: a quick option trade needs room (a wide stop) and a fixed target that pays well over the 0.8% cost; a 2% trailing stop on a premium is inside normal noise and books losses, not profits.

### 2026-11-25 B-1731: every View 6 entry and exit row tested (replay plus literature)
Changing one row at a time shows the strict trend-day mood is the only row that clearly carries profit: removing it is the worst change in all four variants. Near-ATM delta and a 10-15 min hold also hold up for pullback. Rows that fail: the fast_v3 "index moving with the trade" rule (again); allowing expiry-day contracts for pullback (PF 0.27); the morning window for pullback (afternoon is better); and, in the literature, picking from the most-active (attention) list. The IV, VIX, OI and ₹20 rows cannot be tested on synthetic premiums; the 30-s real paths will test them. The pullback edge still comes from the thin FINNIFTY proxy only.
Profit-booking / exit takeaway: hold a pullback trade 10-15 min, not 5 (exits at 5 min give back the bounce before it pays); a 0DTE premium's gamma turns a 12% target into a stop-out, so expiry-day exits lose.


### 2026-11-26 Daily review: 1-share stop-outs and cost drag (25-26 Nov)
Five closed trades had both prices in the data, all net losers: four macddiv 1h longs stopped out (HINDALCO, MAZDOCK, IDEA, ETERNAL, Rs-154.7 net) and one news short (APLAPOLLO) closed +Rs3.40 gross but Rs-8.49 net. 7 of 9 new long entries came from macddiv 1h, so one family carries most of the window's risk. On real Kotak terms the eight 1-share delivery sells paid about Rs189 in DP charges, more than the known gross loss (Rs118).
Profit-booking / exit takeaway: a trail that moves the stop past entry before the open gain exceeds the round-trip cost books a "win" that loses money; on 1-share delivery trades the fixed per-sell charge can outweigh the move, so exits there need room to pay more than the fixed cost.

### B-1744 (2026-11-26): View 6 had no entries, so two wider pullback_v4 paper twins were added
- 26-Nov was the first full live day for the pullback plan and was not a trend day (NIFTY +0.25%, close only 11 pts over its open, breadth 1.16). The strict check blocked every contract, which is correct.
- 90-day replay: dropping only the breadth part gives more trades and a better PF (1.11 vs 1.07, n 358 vs 284). Also removing the midday gap gives many more trades (n 562), but PF falls to 1.02 and the first half is below 1 (0.87).
- Loosening the trend size (0.15%) or removing the trend-day check makes it lose (PF 0.98 / 0.82). The trend-day direction is the edge; breadth is not.
- Profit-booking / exit takeaway: exits were not changed (12% trail, +12% target, 15-min time stop). The extra midday entries in (b) dilute the edge, so if (b) trails (a) on paper, the time window and not the exit is what to drop.

### B-1732 (2026-11-26): pullback_v4 now skips expiry-day contracts (user "Yes implement")
- 90-day replay: skipping contracts that expire today raised PF for every pullback variant (12%: 1.07 to 1.21; 5%: 1.01 to 1.07; no-breadth: 1.11 to 1.25; no-breadth all-window: 1.02 to 1.11) for about 5% fewer trades.
- Expiry-day option premiums swing on gamma and theta, so a 5-min pullback is noise there more than a trend dip.
- fast_v3 keeps expiry-day contracts (B-1717, the user's separate call for that plan).
- Profit-booking / exit takeaway: on expiry day even a 12% trail cannot save a buy, because premium decay is faster than the 15-min hold; not entering is the better exit.
## B-1746 why no strategy has traded NIFTY 50 or SENSEX (2026-11-27 IST)
- Mechanism: index triggers exist in 3 places (WATCHLIST ORB+SMA paper, the gap_and_go index-option scan, View 6), plus 160 researched index-option cells.
- Result: no trade from 3 Sep to 20 Nov. The research cells fail OOS on the premium proxy (best 0.77 at 0.8% cost). The ORB paper path floors to a whole lot, about Rs 15-17 lakh notional, which no budget reaches. The gap_and_go scan is real-only and gated. View 6 is 2 days old.
- Surprise: the one "viable" index row (rsi thrust 1d atr6, PF 1.92) is an underlying-move proxy with OOS n<30. It is not wired, and its premium-proxy twin loses.
- Reuse: an index signal must be expressed as an option (1 lot, small premium), not the future, and judged on the premium proxy, never the underlying move.
- Profit-booking / exit takeaway: index edges that survive 0.8% costs are fat 1d moves; anything wired for index options must book fast on a trailing premium stop, never hold for days.
## B-1746 index triggers are blocked by zero index volume, not by a quiet market (2026-11-27 IST)
- Mechanism: per-day replay of the live ORB rule and 4 non-volume triggers on ^NSEI, ^BSESN and ^NSEBANK, 5m/15m/1h, long and short, 1 Oct to 26 Nov (37 sessions).
- Result: Yahoo index bars have zero volume on every bar. The mandatory, fail-closed volume gate therefore kills every index entry: 0 fires. Without the gate, the same ORB rule fires on 13-21 of 37 days per side (5m), and ORB / EMA / RSI / ATR triggers fire on 20-34 days.
- Surprise: "no signal" for two months looked like a quiet market. It was a data artefact. The attempt log also had no November in-market index snapshots, so it could not show absence.
- Reuse: an index needs a volume source of its own (the near-month future), or volume-free triggers. Check vol_nonzero_bars before reading any "never fired" result.
- Profit-booking / exit takeaway: fires are not profit. Any index trigger has to pass a premium-proxy replay with a trailing premium SL and quick exits before wiring.

## B-1746 index ATM-option premium-proxy replay: long only "passes", inside one rally (2026-11-27 IST)
- Mechanism: index trigger fires (live ORB without the volume gate, ORB, ATR range break, EMA cross, RSI thrust) on NIFTY, SENSEX and BANKNIFTY, 5m and 15m, 1 Oct to 26 Nov. Each fire is bought as 1 ATM option (call for long, put for short) on a Black-Scholes proxy, with IV from the previous day's India VIX, a premium trailing SL, and a quick exit at or before 15:10.
- Result: pooled at 0.8% cost, long passes 70 of 75 combos in both IS and OOS. The best is the live ORB rule with stop 30% / trail 15% held to the end of the day: OOS PF 6.79 on 52 trades. Short passes 0 of 75.
- Surprise: the one-sidedness is the tell. NIFTY rose 13.8% in a month from its 8 Oct 52-week low, so calls won and puts bled. On a random walk with matched IV, the same code passes 0 of 150 pooled combos, so the model is not biased. The window is.
- Reuse: when a direction-symmetric test passes on one side only, check the window's index trend before believing it. Re-run on a multi-regime window (1h over 2 years) before wiring.
- Profit-booking / exit takeaway: wider premium stops with a 15% trail held into the afternoon beat the live 3%/1% trail in a trend, because the live trail stops out on normal premium noise. Re-check this on falling regimes before changing any exit.
