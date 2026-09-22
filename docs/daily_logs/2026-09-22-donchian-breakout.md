# Research pass — 2026-09-22

## Note on the gap: 2026-09-18 through 2026-09-21 had no research pass

The daily trigger fired all four days while this session was idle — all
5 notifications (09-18 through 09-22) arrived queued together on
wake-up. As with earlier gaps, covering it with one solid new candidate
today rather than backfilling placeholder days.

## Test suite: 65 failed / 12 errors (up from 44 failed / 10 errors on 09-17)

Confirmed via a full pytest run before and after today's change that
the counts are identical (65 failed, 254 passed, 12 errors) — my
`donchian_breakout` addition introduces no regression. The pre-existing
count itself has grown again since the last check (09-17: 44 failed +
10 errors → today: 65 failed + 12 errors). Not re-investigating the
breakdown in detail this cycle since it was already covered thoroughly
on 09-17 (real order/exit-logic tests, plus a `neo_api_client` SDK
missing in this sandbox) — the trend is the same, just larger. Still
outside my remit; still worth the main session/user knowing the number
keeps climbing.

## Candidate: Donchian Channel breakout (Turtle Trading System)

Classic Dennis/Eckhardt entry: long on a close above the
`entry_period`-bar rolling high, exit on a close below the shorter
`exit_period`-bar rolling low (original: 20-bar entry, 10-bar exit).
The defining feature — an *asymmetric* dual-channel (different
lookback for entry vs. exit) — is genuinely distinct from every
breakout candidate already in the engine (`orb_breakout`, `supertrend`,
`keltner_channel_breakout`, `cci_breakout` all use a single
window/level for both).

Sources: sub-50% win rate is the signature, expected profile of this
style, not a red flag — one backtest reported a 36% win rate on BTC
with +36.5% total return over 25 trades. It never misses a major trend
and pays for that guarantee with many small losses, offset by a few
large trend captures.

## Implemented (commit `ef6f425`)

- `main.py`: new `donchian_breakout` branch in `add_strategy_signal()`
  (params: `entry_period`, `exit_period` — exposed as
  `donchian_entry_period`/`donchian_exit_period` in the query string),
  wired through `/backtest` and `/sweep`. Rolling windows shifted by
  one bar to avoid lookahead.
  - Verified locally against a synthetic flat→breakout→pullback series:
    entered during the rally, exited when price fell through the exit
    channel.
- `.github/workflows/entry-trigger-research.yml`: new
  `run_donchian_research` input + step, sweeping
  `donchian_entry_period` x `donchian_exit_period` (constrained to
  exit < entry) on the 3 NSE indices + 15 NSE large-caps.
- Checked `state/real_positions.json` (empty) before pushing; one
  paper position (GENCON.NS, unchanged since 09-16 — possibly an
  orphaned position, given a new `test_orphaned_open_position_still_managed.py`
  appeared in the pulled commits) still open, judged low-risk.

## Status

`strategy_log.xlsx` unchanged at 28 rows. Nine candidates now sourced,
coded, and sweep-ready on this workbook, pending real dispatch:
`bollinger_mean_reversion`, `supertrend`, `pin_bar_reversal`,
`inside_bar_breakout`, `rsi_divergence`, `stochastic_oversold_reversal`,
`cci_breakout`, `keltner_channel_breakout`, `donchian_breakout`.
