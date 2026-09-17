# Research pass — 2026-09-17

## Flagging first: test suite regression is growing, not stable

Two cycles ago (09-15): 12 pre-existing failures. Yesterday (09-16):
still 12. **Today: 44 failures + 10 collection errors.** Confirmed via
`git stash` that this is entirely pre-existing on `main` — identical
count with and without today's change — so not something I caused, but
the trend itself (12 → 44+10 in about a day of upstream commits) is
worth surfacing plainly rather than only noting "unrelated, moving on."

Breakdown:
- **10 collection errors**: `ModuleNotFoundError: No module named
  'neo_api_client'` — this sandbox doesn't have Kotak Neo's SDK
  installed (not on PyPI under that name; presumably vendored or
  privately distributed). This is an environment gap in *my* session,
  not necessarily a real failure in the main session's environment
  where that package is presumably available — flagging so it's not
  mistaken for 10 new bugs, but I can't rule out that it *is* failing
  in CI too without being able to run it there myself.
- **44 failures**, concentrated in newer real-order/regime-logic test
  files: `test_t1_restricted.py` (6 failures — T1 same-day-sell
  rejection handling), `test_universal_score_engine.py` (3 — staged
  partial-exit booking), `test_trend_weakened_range_exclusion.py` (2,
  same as previous cycles), `test_start_scheduler_concurrent_hydration.py`,
  `test_swing_gap_and_go.py`, plus others not seen in earlier cycles.
  Given `CLAUDE.md`'s own 2026-09-14 incident was about exactly this
  class of thing (a real-money exit-logic regression going unnoticed),
  this seemed important to state clearly rather than bury in a status
  line. Not mine to fix — real-order/exit code is outside my remit —
  but the main session or user should know the number is climbing.

## Candidate: Keltner Channel breakout

ATR-based volatility channel (EMA midline, unlike Bollinger's SMA/
std-dev bands) — genuinely different band construction from
`bollinger_mean_reversion`, and breakout-oriented rather than
mean-reversion. Enter long on a close above the upper band, exit when
price falls back through the EMA midline.

Sources:
- [quantvps.com](https://www.quantvps.com/blog/keltner-channel-trading-strategy),
  [pyquantlab.com](https://pyquantlab.com/article.php?file=Keltner+Channel+Breakout+Strategy+with+Optimization+and+Rolling+Backtest+Analysis.html):
  breakout-variant backtests report ~35-58% win rate depending on
  market/settings.
- An EURUSD/GBPUSD/USDJPY H1 study found EMA(20)+ATR(10)@1.5x
  delivered a 57.8% win rate, 1.33 Sharpe, 12.9% max drawdown — used
  as this candidate's defaults.

## Implemented (commit `9360588`)

- `main.py`: new `keltner_channel_breakout` branch in
  `add_strategy_signal()` (params: `period`, `atr_period`,
  `multiplier` — exposed as `kc_period`/`kc_atr_period`/`kc_multiplier`
  in the query string, to avoid colliding with `supertrend`'s
  same-named-but-differently-defaulted params), wired through
  `/backtest` and `/sweep`.
  - Verified locally against a synthetic flat→breakout→pullback series:
    entered during the rally, held through to the pullback below the
    EMA midline.
- `.github/workflows/entry-trigger-research.yml`: new
  `run_keltner_research` input + step, sweeping `kc_period` x
  `kc_atr_period` x `kc_multiplier` on the 3 NSE indices + 15 NSE
  large-caps.
- Checked `state/real_positions.json` (empty) before pushing; two
  paper positions open (GENCON.NS, GC=F), judged low-risk.

## Status

`strategy_log.xlsx` unchanged at 28 rows. Eight candidates now sourced,
coded, and sweep-ready on this workbook, pending real dispatch:
`bollinger_mean_reversion`, `supertrend`, `pin_bar_reversal`,
`inside_bar_breakout`, `rsi_divergence`, `stochastic_oversold_reversal`,
`cci_breakout`, `keltner_channel_breakout`.
