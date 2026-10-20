# B-779(b) next steps: top research-only viables (prepared, not run)

Source: docs/WIRING_PLAN_RESEARCH_VIABLES.md top 10 (all chan_kalman 5m). Replay workflow:
`.github/workflows/b779b-kalman-top3-main-replay.yml` (full NSE universe, real main.py functions, not dispatched).
Picks were chosen as the highest-ranked rows main.py can already express; #2 and #5 are `__v1` no-flatten twins
(main.py exits always flatten at 15:15 IST), so they are skipped, not dropped (their registry rows stay).

Status check before any wiring: main.py already has a buy-engine cascade for chan long (B-960,
`_CHAN_LONG_CELL_SPECS`, `_chan_long_try_entry`) and a short path (B-915, `_chan_short_try_entry`). Compare the replay
against the registry first; wire or re-gate only from the replay numbers.

| pick | tag | main.py entry / exit fn | live wiring still owed |
|---|---|---|---|
| #1 | `chan_kalman__band__long__5m__atr4d0_hold40_ve10d0e4_z1d0_fl1515__v2` | `chan_kalman_band_long_entry_signal` / `chan_kalman_band_long_exit_reason` | Confirm cell (4.0, 1e-3, 1.0) is first in `_CHAN_LONG_CELL_SPECS` and the replay PFnet >= floor; real entry must place the ATR stop (entry - 4.0 x ATR) in the same request, `entry_sl_failed_unwind` on failure; 15:15 IST flatten retry. |
| #3 | `chan_kalman__band__long__5m__atr2d5_hold40_ve10d0e4_z1d0_fl1515__v2` | same long pair | Same as #1 with ATR x2.5; one chan long per symbol per day, so it only fires when #1's cell does not; confirm replay PFnet and that the buy-engine gate reads this tag. |
| #4 | `chan_kalman__band__short__5m__atr2d5_hold40_ve10d0e4_z2d0_fl1515__v2` | `chan_kalman_band_short_entry_signal` / `chan_kalman_band_short_exit_reason` | Live short wires only the atr4d0 z2d0 cell (`CHAN_SHORT_TAG`, tag family `band_mr`). Owed: a short cell cascade for atr2d5 z2d0 (own tag per grammar, short engine SL via `place_real_short_stop_loss`, buy-to-cover flatten from 15:10 IST), only if the replay clears the floor and the thumb-rule tie-break prefers it over atr4d0. |

Always owed for all picks: replay compared to registry (PFnet gross/net, win %, avg hold, n, exit-reason breakdown),
learnings entry in docs/STRATEGY_LEARNINGS.md, registry row for the replay as its own tag, stop on every trade, no new kill switch.
