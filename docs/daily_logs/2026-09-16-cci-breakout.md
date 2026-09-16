# Research pass — 2026-09-16

## Context noticed this cycle

Pulled 116 new commits. Two things worth recording:

1. **A large parallel swing-trading research effort** now exists — 14
   `.github/workflows/swing-*-research.yml` files (RSI(2) mean
   reversion, Donchian breakout, Fibonacci retracement, BB squeeze
   breakout, supertrend flip/partial-profit/wide-trail variants, etc.),
   logging to a *different* workbook, `docs/strategy_backtest_log.xlsx`
   ("Backtest Log" sheet — currently 13 rows, mostly options
   structures: spreads, straddles, iron condors, protective puts).
   This is a separate initiative from mine — I read
   `docs/PROJECT_STRUCTURE_PLAN.md`, which confirms the project is run
   by five coordinating sessions (main, Research Agent [me], Sentiment
   Agent, Journal Sync Agent, Deploy Gate agent), each with its own
   brief file. My mandate stays specifically `docs/strategy_log.xlsx`
   and the intraday `/backtest`+`/sweep` engine — not touching the
   swing workflows or the other log.
2. Confirms my own role description verbatim: "Research Agent — Backtests
   strategy candidates across markets, logs to `docs/strategy_log.xlsx`."
   Consistent with what I've been doing.

## Candidate: CCI breakout (Commodity Channel Index)

Direct follow-up to yesterday's stochastic research note, which
flagged an NSE-specific study (Nifty 50, 2004-2014) finding CCI
outperformed both Stochastic and RSI. Classic Lambert momentum rule:
long while CCI stays above +threshold (default 100) — a trend-momentum
signal, distinct in character from the mean-reversion oscillators
already in the engine.

Sources:
- [liberatedstocktrader.com](https://www.liberatedstocktrader.com/commodity-channel-index/):
  broader backtests (200 stocks, 2015-2024) show modest ~49% win rate
  but a 2.2:1 reward:risk (avg winner 6.8% vs avg loser 3.1%).
- A "quality"/narrower-threshold variant is reported to reach 60-70%
  win rate with far fewer signals — `threshold` is exposed as a
  sweepable param specifically so the sweep can locate that trade-off
  on real NSE data rather than assuming it.

## Implemented (commit `2525ecf`)

- `main.py`: new `cci_breakout` branch in `add_strategy_signal()`
  (params: `period`, `threshold` — exposed as `cci_period`/
  `cci_threshold` in the query string), wired through `/backtest` and
  `/sweep`.
  - Verified locally against a synthetic flat→breakout→flat series:
    entered exactly when CCI crossed +100 during the breakout, stayed
    flat through the range periods.
- `.github/workflows/entry-trigger-research.yml`: new
  `run_cci_research` input + step, sweeping `cci_period` x
  `cci_threshold` on the 3 NSE indices + 15 NSE large-caps.
- Checked `state/real_positions.json` (empty) before pushing; one paper
  position (GENCON.NS) still open, same as yesterday — judged low-risk.

## Status

`strategy_log.xlsx` unchanged at 28 rows. Seven candidates now sourced,
coded, and sweep-ready pending real dispatch on this specific workbook:
`bollinger_mean_reversion`, `supertrend`, `pin_bar_reversal`,
`inside_bar_breakout`, `rsi_divergence`, `stochastic_oversold_reversal`,
`cci_breakout`.
