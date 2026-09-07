# Research pass — 2026-09-05

## Candidate: Supertrend (ATR-based trend-following)

Standard Supertrend: trailing bands built from `hl2 ± multiplier * ATR(atr_period)`,
sticking in the trend's favor (won't retreat against price) until price
closes through the opposite side, at which point the line flips. Long
while price sits above the (lower) trailing band, flat once it flips.

Chosen specifically because it's one of the most widely used indicators
among Indian retail/algo traders on NSE — directly answers the original
"how do other traders take trades" brief.

Sources:
- [thehonestquant.com](https://thehonestquant.com/strategies/supertrend-strategy),
  [quantifiedstrategies.com](https://www.quantifiedstrategies.com/supertrend-indicator/):
  ~40-55% hit ratio on 5-min NIFTY at standard params (10, 3.0), but
  winners run 2-3x larger than losers since you ride the trend until it
  flips.
- [marketcalls.in](https://www.marketcalls.in/trading-lessons/game-changer-trading-strategy-nifty-based-supertrend.html):
  standard settings are noted as too slow for BANKNIFTY specifically,
  which moves 3-5x more intraday points than a typical NSE large-cap —
  hence sweeping `atr_period` x `multiplier` per symbol rather than
  assuming one setting fits all NSE instruments.

## Implemented (commit `1895115`)

- `main.py`: new `supertrend` branch in `add_strategy_signal()` (params:
  `atr_period`, `multiplier`), wired through `/backtest` and `/sweep`.
  Recursive band logic (loop-based, like the existing indicator
  strategies) rather than vectorized, since the "sticky" band can't be
  expressed as a simple rolling window.
  - Verified locally against a small synthetic OHLC series before
    pushing: produced sparse, plausible trend flips (6 switches over 200
    bars), not noise — the full `tests/test_strategy_logic.py` suite
    (8 tests) still passes.
- `.github/workflows/entry-trigger-research.yml`: new
  `run_supertrend_research` input + step, sweeping `atr_period` x
  `multiplier` on the 3 NSE indices + all 15 NSE large-caps, matching
  the `bollinger_mean_reversion` step added yesterday.
- Checked `state/open_positions.json` and `state/real_positions.json`
  (both empty, synced ~50m prior) before pushing — extra caution now
  that real-money trading (stage 3) is live per the day's other commits.

## Status

No `strategy_log.xlsx` row yet — no real numbers exist until the main
session dispatches the workflow. Did not attempt to dispatch it myself
or retry any GitHub Actions/API workaround, per the confirmed division
of labor in `RESEARCH_AGENT_BRIEF.md`.

## Noticed since yesterday (informational, not acted on)

A lot has landed on `main` since the last cycle: real-money order
placement is now live ("Stage 3", explicit user go-ahead, `real_trading_control.json`
shows `db_switch_enabled: true`), Kotak Neo live tick feed activated,
and several new VWAP-family strategies (`vwap_mean_reversion`,
`vwap_breakout_retest`, `anchored_vwap_continuation`,
`anchored_vwap_reversal`, `vwap_multi_period_reversal`) were added to
`add_strategy_signal()`/`/backtest` by someone else — not yet wired into
`/sweep`'s combo builder or this workflow file. Left those alone; not
my addition to finish unless asked.
