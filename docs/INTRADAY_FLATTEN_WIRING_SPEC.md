# Intraday flatten wiring spec (B-792c) - 2026-10-12 IST

Status: SPEC ONLY, nothing wired. Coordinator implements. Net-profit framing: only 42 of 152 flatten cells survive PFnet >= 1.1 with a forced 15:15 IST exit (best: chan_kalman band long 5m atr4d0, PFnet 1.78, n=5722; short 5m atr4d0 z2d0, 1.67, n=988). Raw data: `docs/backtest_data/flatten_rerun_run_38185672296.json`, registry `strategy_registry_flatten.py` (tags `<old>_fl1515__v2`).

## Hard constraints (from CLAUDE.md)
1. The exchange cancels ALL resting orders at 15:15 IST. A resting SL placed at entry is therefore gone at 15:15; the bot must be flat BEFORE that, by its own market exit, not rely on the SL.
2. No trade without SL/SLM: entry is refused (or unwound) if the stop cannot be placed. Cells are ATR-stop cells (atr*mult at the signal bar); no `atrnone` cell may be wired.
3. Kotak-first governance order: positions/holdings, then order book, then DB, then act. Local rows are rewritten from Kotak.
4. Engine ownership: long cells enter/exit ONLY via the intraday buy engine (`_maybe_place_real_entry` / `_maybe_place_real_exit`); short cells ONLY via the short engine (`_maybe_place_real_short_entry` / `_maybe_place_real_short_exit`). Never swing tables.
5. Gate: `_is_strategy_viable_for_real_money` (PFnet >= 1.1) unchanged; no new kill switch. Reuse the existing `is_real_trading_enabled` switch only.
6. Every order logged with `reason=` (new reasons: `flatten_1515`, `entry_sl_failed_unwind`, `flatten_failed_escalate`). `tests/test_real_exit_reason_logged.py` must stay green.

## Prerequisite: the strategy code does not exist in main.py
No kalman-band entry/exit is in main.py. Steps, in order:
1. Verbatim port of the entry + exit from `scripts/chan_research.py` into main.py as `chan_kalman_band_entry_signal(...)` / `chan_kalman_band_exit_reason(...)` (long and short as separate functions/tags per the naming grammar).
2. Replay harness that imports and calls those main.py functions (B-30 pattern) with the flatten rule; compare to the registry numbers. If a cell lands < 1.1, correct the registry (the gate closes automatically). Do not wire before this passes.
3. MIS cost model (not the flat 0.8%) in the replay; re-register as new tags if numbers move.
4. Candle-size sweep owed: 4h (1h resample) not yet built; flag it, do not skip silently.
5. Month/lunar calendar cells (n200 swing watchlist, n~202) are calendar effects, not intraday-engine material until validated universe-wide.

## main.py edit points
| Function | Change |
|---|---|
| `_STRATEGY_TAG_TO_REGISTRY_NAME` (~10777) | one entry per wired `_fl1515__v2` tag (never alias two tags) |
| `_auto_signal_core` (~8756) / `_short_signal_core` (~9858) | call the new entry fn when the symbol's strategy tag is a kalman-band tag; stop = atr*mult at signal bar; existing `eod_squareoff` at squareoff_min=914 (3:14pm) already flattens paper |
| `_maybe_place_real_entry` (~11779) / `_maybe_place_real_short_entry` (~11532) | after fill, place the resting SL in the same request; if placement fails after retries, market-unwind with `reason=entry_sl_failed_unwind`. No new entries from 15:00 IST (must match the cell's backtest entry window) |
| `_maybe_place_real_exit` (~12694) / `_maybe_place_real_short_exit` (~11715) | accept `reason="flatten_1515"`; cancel resting SL first (fresh order book), then market exit; verify the fill from Kotak positions |
| `_scheduler_tick` (~19560) | flatten pass 15:10-15:14 IST every tick: fetch Kotak positions + order book fresh, for each intraday-owned open position still open call its own category exit; at 15:15+ any still-open one is a loud alarm via `_find_unprotected_open_positions` (~22019) |
| `_reconcile_real_positions_core` (~22063) | no new logic; confirm kalman positions are covered by the same long/short net-qty-sign backcheck and the 09:15 protect-first rule (an overnight one means flatten failed) |

## Flatten failure ladder
Market exit rejected (T1, margin, circuit, API error): retry every tick until 15:14:50; then dashboard alarm and leave to the next-day 09:15 protect-first rule. Log each attempt with its reason.

## Tests needed (new file tests/test_intraday_flatten_wiring.py)
- entry unwound when SL placement fails (event logged with reason).
- flatten pass exits every open intraday long and short at 15:10-15:14 using a fresh Kotak fetch (mock), not the DB; swing-owned symbols untouched (ownership).
- no new entry after the cutoff.
- registry gate: PFnet < 1.1 blocks entry, >= 1.1 opens.
- port parity: main.py function output equals the research function on a fixed fixture.
- reason present on every flatten path (extends test_real_exit_reason_logged).
- full pytest green, `ast.parse(main.py)`.

## Expected P&L effect
Adds up to 42 intraday cells (PFnet 1.1-1.78) with same-day capital turnover (preferred by the turnover rule). Risk: MIS costs, slippage at 5m, thin edges on several cells; the step-2 replay decides which survive. Ship only via Deploy Gate on the user's go-ahead.
