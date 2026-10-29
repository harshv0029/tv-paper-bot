# B-1416: why the research sim and the main.py replay disagree on OB / VP exitinval

Date: 2026-10-29 IST. Read-only root cause by reading both code paths side by side (no new run).

| | Research sim (run 38140914889) | main.py replay (run 40820614764) |
|---|---|---|
| Code | `scripts/exit_family_research.py` (`simulate()` kind `inval`, atr 6.0, sig ema13w) | `.github/workflows/swing-ob-vp-main-replay.yml`, `exit_family=exitinval`, no band cap |
| OB `order_block_delta__exitinval__long__1d__atr6d0_hold30_sigema13w` | PFnet 1.166, n 57,705, win 40.4%, hold 22.1 d | PFnet 1.074 (gross 1.331), n 33,214, win 39.4%, hold 22.3 d |
| VP `volume_profile_poc__exitinval__long__1d__atr6d0_hold30_sigema13w` | PFnet 1.268, n 61,131, win 39.6%, hold 20.9 d | PFnet 1.089 (gross 1.392), n 38,396, win 38.5%, hold 21.5 d |

Sources: `docs/backtest_data/exit_family_run_38140914889.tsv`, `docs/backtest_data/b1413_obvp_live_stop_replays.json`. The replay's per-trade list and exit-reason split were not committed, so the shares below are estimates from code plus the aggregates.

## Every difference (line numbers in the sim are at base commit c330e7f, before this change)

| # | Aspect | Research sim | main.py replay | Effect |
|---|---|---|---|---|
| 1 | Overlap | Every signal is its own trade, even while an earlier one is open (`process_symbol` L335-342). Signals only need to be 5 bars apart (`collect_signals` L302, `MIN_SIGNAL_GAP=5`) | One position per symbol: new entry only when `pos is None` (workflow L125). Exit is checked before entry on the same bar, so re-entry is allowed on the exit bar (L118-126) | **Most of the n gap.** With ~22-day holds, signals inside an open trade are dropped. Same-symbol overlapping trades share one price path, so the sim counts the trending winners (51% of OB trades reach the 30-day timeout, PFnet 3.3) several times |
| 2 | Sizing / weighting | Equal notional: each trade is a % return (`_res` L170-171), PF over summed % | 1%-risk sizing: qty = floor(min(2000 / (6 x ATR), 200000 / price)) (L133-135). INR P&L is weighted by 1/ATR%. Trades with qty 0 or notional < Rs 100 are skipped | Low-volatility names carry more weight, high-volatility max-hold winners less. Lowers PFnet; size unknown without a run |
| 3 | Cost | Flat 0.8% of notional (L361, `add_trade` L240) | Itemized: about 0.40% buy + 0.39% sell (about 0.79%, close to 0.8%) **plus DP Rs 15.93 + GST = Rs 18.8 per trade** (L89-98, `fin` L142-145) | A 6xATR stop on 1% risk gives small positions (about Rs 11-17k for a 2-3% ATR stock), so DP alone adds about 0.11-0.17% per trade. From the replay aggregates (avg net +26.6 / +34.1 INR, net losses about Rs 359 / 383 per trade), removing DP would lift replay PFnet to about 1.13 / 1.14. **About 0.05-0.06 PFnet** |
| 4 | Trades at the end of data | Dropped when the 30-bar window passes the last bar (L185-186) | Force-closed at the last close as `data_end_forced_close` (L138-139) | Replay has about 2-3% more trades; small PF effect |
| 5 | Universe | Full universe minus `ETF_SYMBOLS` (L362); `MIN_BARS=160` (L380) | Full universe including ETFs (L147); needs `min_bars + 20` = 80 / 110 bars (L155) | Replay has a few more symbols (ETFs, young listings). Small, adds to the replay's n |
| 6 | Data cleaning | `yf.download(auto_adjust=True)` in 50-symbol batches, then `clean_bars` drops bad bars and >35% one-day jumps (L346-350, L371, L379) | `data_fetch.fetch_ohlc` one symbol at a time, default `yf.download`, only OHLC NaNs dropped (data_fetch.py L95-107) | The replay keeps split-like spikes that the sim removes. Small, direction unknown |
| 7 | Weekly EMA13 flags | Computed once on the full 5-year series (`prepare` L158) | Recomputed on a trailing 250-row window per bar (workflow L87; main.py `weekly_ema13_down_flags` L7514-7535). Under 150 rows the window has < 30 weeks and every flag is False | Replay trades entered in the first ~150 bars of a symbol (about 5-6%) can never exit on invalidation. **This is a replay artifact, not live behaviour**: the live scan fetches 2y (main.py L23073/L23095), so live always has the flags |
| 8 | ATR | `main._atr_array` (SMA of TR) on the full series (L152) | `_compute_atr_value` (rolling mean of TR) on the window | Same formula, same value |
| 9 | Entry fill | Signal-bar close (`entry = c[i0]`, L182) | Signal-bar close (`sig["entry_price"]` = close) | **No difference.** Neither uses the next open |
| 10 | Stop / exit order | Per bar: open <= stop fills at the open, low <= stop fills at the stop, then invalidation at the close, then the 30-bar timeout (L197-229) | `swing_exitinval_exit_reason` (main.py L7538-7567) has the same order; fill = min(open, stop) (workflow L122-123) | **No difference** |
| 11 | Entry signals | Real `order_block_entry_signal` / `volume_profile_poc_entry_signal` on a 150-row window | Same functions on a 250-row window | Both read only the last ~80 rows, so same signals |

## Which differences drive the gaps

- **n gap (about 40% fewer replay trades): cause 1 explains about 90%+.** If signals arrive at the sim's rate (about 0.022 per symbol-bar) and holds are 21-22 bars, a one-position book keeps about 1/(1 + 0.022 x 22), about 67%, of them. Signals cluster (retests repeat), so the real share kept is lower, about 58-63% observed. Causes 4 and 5 add trades to the replay and partly offset this.
  Cross-check: the replay's VP chandelier run (hold 9.1 d) kept n 58.5k, close to the sim's 61k, while VP exitinval (hold 21.5 d) kept 38.4k. n falls in step with hold length, which is the signature of position blocking.
- **PFnet gap (OB -0.09, VP -0.18):**
  1. Overlap double-counting (cause 1): about 40-60% of the gap (the residual after the cost estimate, shared with cause 2). Same pattern as the Chan non-overlap re-run (B-807), where overlap inflated PFnet by 0.3-0.5.
  2. DP charge on small risk-sized positions (cause 3): about 0.05-0.06, so about 60% of the OB gap and 30% of the VP gap.
  3. Risk weighting (cause 2): the rest. It cannot be split from cause 1 without a run.
  Causes 4-7 are each judged under 0.02.

## Which number to trust for the real-money gate

**The main.py replay.** It calls the live `_swing_exitinval_adapter` and the live entry functions, holds one position per symbol as the live swing engine does, sizes by risk like the live slice, and charges the real per-sell DP fee. The sim's 1.166 / 1.268 count overlapping copies of the same move and leave out a cost Kotak really charges. The gate already reads the stricter band-floor replay rows (OB 0.966, VP 1.006, B-1413). That stays correct, and nothing here argues for loosening it.

## Fix (research-only, implemented)

`scripts/exit_family_research.py` now defaults to `MATCH_MAIN_REPLAY = True`. This mode matches causes 1-4:
- one position per symbol per cell, with re-entry on the exit bar;
- every signal bar is collected;
- 1%-risk qty on the Rs 4 lakh / `CAPITAL_TRANCHES` slice (qty-0 trades skipped);
- the itemized cost model + DP;
- a trade still open at the end of data is force-closed at the last close.

Tags in this mode end in `__v2`, so the registered `__v1` numbers stay untouched (naming immutability). `run --legacy-sim` restores the old sim and the `__v1` tags. Tests: `tests/test_exit_family_research.py` (5 new). Not matched on purpose:
- cause 5 (the sim's ETF exclusion matches the live swing universe better);
- cause 6 (cleaning bad bars is the more honest choice);
- cause 7 (a replay artifact; the follow-up is to give the replay a window of at least 250 rows from bar 0, or full-history flags).

**To confirm:** dispatch `exit-family-research.yml` once (it runs the new default). The OB / VP `exitinval atr6d0 ema13w __v2` cells should land within about ±0.03 of 1.074 / 1.089, with n within a few % of 33k / 38k. A larger miss means some cause above was misjudged.
