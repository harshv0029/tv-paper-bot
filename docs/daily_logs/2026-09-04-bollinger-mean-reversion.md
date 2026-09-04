# Research pass — 2026-09-04

## Candidate: Bollinger Band mean-reversion

Enter long when Close closes below the lower Bollinger Band (bb_period,
bb_std), exit when it reverts above the middle band (rolling mean) — not
the upper band, since sourced research says targeting the middle band
gives the higher win rate.

Sources:
- [crosstrade.io](https://crosstrade.io/learn/trading-strategies/bollinger-mean-reversion),
  [quant-signals.com](https://quant-signals.com/bollinger-bands-trading-strategy/):
  ~58-65% win rate in non-trending regimes exiting at the middle band;
  drops toward ~45% without a regime filter (trending days produce
  losing streaks).
- [momentumiq.in](https://www.momentumiq.in/blog/bollinger-walk-nse-trading-strategy-for-beginners):
  explicitly documented as workable on NIFTY 50 and other liquid NSE
  large-caps — directly relevant now that scope is NSE-only.

## Implemented (commit `ccc14b6`)

- `main.py`: new `bollinger_mean_reversion` branch in
  `add_strategy_signal()` (params: `bb_period`, `bb_std`), wired through
  `/backtest` and `/sweep`. Same enter/exit-loop style as `rsi_reversal`.
  Syntax-checked, not yet exercised against real data (see blocker below).
- `.github/workflows/entry-trigger-research.yml`: new
  `run_bollinger_research` input + step, sweeping `bb_period` x `bb_std`
  on the 3 NSE indices + all 15 NSE large-caps now in `WATCHLIST`. Also
  flipped `run_new_asset_research`'s default to `false` (gold/forex are
  out of scope per `RESEARCH_AGENT_BRIEF.md`'s 2026-09-03 update) —
  capability kept, just off by default.
- Checked `state/open_positions.json` (empty, synced ~50m prior) before
  pushing.

## Still can't dispatch/backtest from this session — as expected, not re-litigating

Per `RESEARCH_AGENT_BRIEF.md`'s confirmed 2026-09-03 note: no GitHub
Actions tool available here, and direct HTTP to the live server is
blocked by this environment's egress policy. That's the expected
division of labor (main session dispatches + logs real results), not a
bug to keep re-attempting — did not retry curl/API workarounds this
pass. No `strategy_log.xlsx` row added yet for `bollinger_mean_reversion`
since there's no real data behind it — logging happens once the main
session runs the sweep and the numbers come back.

## Housekeeping

Fixed this routine's own cron (`trig_01LZJwjGaMwMo6R1tgBvaCki`) yesterday
— it was firing hourly (`50 * * * *`) instead of daily; now `50 3 * * *`.
Confirmed today it fired once as expected.
