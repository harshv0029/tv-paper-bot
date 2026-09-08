# Research pass — 2026-09-08

## Note on the gap: 2026-09-06 and 2026-09-07 had no research pass

The daily trigger fired both days but this session was idle/unavailable
until now — all three notifications (09-06, 09-07, 09-08) arrived queued
together on wake-up. Rather than backfill two placeholder days of work,
this pass covers the gap with one solid new candidate today. No strategy
work was silently skipped without a record: this is that record.

## Candidate: Pin bar / hammer reversal at support

Bullish pin bar (hammer: long lower wick, small body, small upper wick)
whose low sits at/near a rolling N-bar low (support zone) — combines a
reversal candle with support/resistance context, both explicitly named
in the original research brief. Exit on the mirror bearish pin bar
(shooting star).

Sources:
- [dailypriceaction.com](https://dailypriceaction.com/blog/forex-pin-bar-trading-strategy/):
  a 10-year backtest on NSE Nifty 50 ranked the hammer #1 among reversal
  patterns at ~63% win rate — directly relevant given NSE-only scope.
- [colibritrader.com](https://www.colibritrader.com/pin-bar-candlestick-2/),
  [innercircletrader.net](https://innercircletrader.net/tutorials/pin-bar-trading-strategy/):
  pin bars at key support/resistance levels showed a 15-20% higher
  success rate than the pattern alone (FXOpen backtest, 2015-2020) —
  hence requiring support proximity rather than testing the bare
  candlestick pattern in isolation.

## Implemented (commit `c7b9005`)

- `main.py`: new `pin_bar_reversal` branch in `add_strategy_signal()`
  (params: `pin_ratio`, `sr_lookback`, `sr_tolerance_pct`), wired through
  `/backtest` and `/sweep`.
  - Verified locally against a synthetic OHLC series with an injected
    hammer at a rolling low: correctly triggered entry, held through the
    subsequent trend. Full `tests/test_strategy_logic.py` suite (8/8)
    still passes.
- `.github/workflows/entry-trigger-research.yml`: new
  `run_pin_bar_research` input + step, sweeping `pin_ratio` x
  `sr_lookback` x `sr_tolerance_pct` on the 3 NSE indices + all 15 NSE
  large-caps.
- Checked `state/open_positions.json` and `state/real_positions.json`
  (both empty, synced ~50m prior) before pushing.

## Status

No `strategy_log.xlsx` row yet for `pin_bar_reversal` — nor, still, for
`bollinger_mean_reversion` or `supertrend` from the last two cycles
(28 rows in the log, unchanged since 2026-09-03). The main session's
attention over the last 3 days went to real-money F&O infrastructure
(Kotak Neo reconciliation, `nse_fo_chain.py`, `sentiment_signals.py`)
rather than dispatching these research candidates — reasonable
prioritization, just noting why the backlog of untested candidates is
growing. Did not attempt to dispatch anything myself, per the
established division of labor.
