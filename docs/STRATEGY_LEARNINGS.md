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
