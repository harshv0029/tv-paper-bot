# Class-A unwired strategies: wiring notes (draft, nothing wired yet)

Source of truth for "viable and not wired": `strategy_registry` (PFnet >= `PFNET_LIVE_FLOOR`, derived at read time)
minus the values of `main._STRATEGY_TAG_TO_REGISTRY_NAME`. Evidence harness: `scripts/class_a_replay.py`,
workflow `.github/workflows/class-a-unwired-replay.yml`. Wire ONLY after the harness's full-universe number
(0.8% cost, stop on every trade) still clears the floor; the registry numbers come from other
implementations (see "Known gaps").

## 1. sector_rotation fade SHORT (swing category, engine = swing)
Cells: `sector_rotation__fade__short__1d__atr{1d5,2d5,4d0,6d0}_h{1,5,10,20}_l{3,5}_n{1,3}__v1` (atrnone cells are
NOT wireable: no stop). Best registry cells: `atr1d5_h20_l5_n1` (1.537, n=683), `atr1d5_h10_l5_n1` (1.523),
`atr1d5_h5_l5_n1` (1.454, 26 h hold: preferred on the faster-turnover tie-break).
- Entry: the SHORT shorts exactly the names `main.sector_rotation_picks` returns (strongest-breadth sector's
  top-N by L-day return). Needs `SECTOR_ROT_L` / `SECTOR_ROT_N` per cell; today they are module constants for the
  long cell (L=1, N=5), so the short needs its own constants (`SECTOR_ROT_SHORT_L/N`) and a `picks(dfs, L, N)`
  parameterisation. Do not change the long cell's behaviour.
- Exit (missing in main.py): `sector_rotation_exit_reason_short(df, entry_day, initial_stop, hold_days)`:
  stop when the high/close reaches `entry + k*ATR14`, time exit after `h` trading days. Stop model matters:
  the harness prints `stop` / `gap_aware` / `close` fills; wire the model the live engine can really execute
  (a resting SL-M above entry = `gap_aware`).
- Stop: `entry + k*ATR14` placed with the entry (no trade without SL). Reuse the swing short real path's SL
  placement; the 5-min Kotak backcheck/auto-heal already covers shorts by net-qty sign.
- Tags: add each wired cell to `_STRATEGY_TAG_TO_REGISTRY_NAME` as tag == registry name (same pattern as
  the long cell `sector_rotation__momentum_n200__long__...`). One entry per cell, never pooled.
- Scan hook: `_run_swing_scan` -> a `_run_sector_rotation_short_entries(conn, dfs, capital, today)` next to
  `_run_sector_rotation_entries`, calling `_record_strategy_scan(tag)`, inserting `signal_state_swing`
  (direction short columns as the swing short path does) and `_maybe_place_real_swing_short_entry` only if that
  function exists; otherwise the short swing real path is itself missing and is the blocker (check first).
  Add the exit branch in the swing exit loop keyed on `pos["strategy"]`.
- Engine ownership: swing engine only (entered, managed, exited in `real_positions_swing`); the intraday
  short engine must refuse these symbols (existing `signal_state_swing` ownership check).
- Gate: `_is_strategy_viable_for_real_money` through the mapping; no new kill switch; shares
  `is_real_swing_trading_enabled`.
- Durability: `signal_state_swing` / `real_positions_swing` already have the Upstash mirror + 5-min backfill.

## 2. minervini_vcp variants
- `minervini_vcp_breakeven_2r` (1.145, only 0.045 over 1.1; n=279): real entry + real
  `minervini_vcp_exit_reason_breakeven(..., MINERVINI_BREAKEVEN_R_2)`. Wiring = exactly how `minervini_vcp_be3r`
  is wired: strategy tag `minervini_vcp_be2r`, mapping `"minervini_vcp_be2r": "minervini_vcp_breakeven_2r"`, an
  `elif pos["strategy"] == "minervini_vcp_be2r"` exit branch, thesis text. Note be3r already holds the same
  entry; running both would double-enter the same setup: choose ONE per symbol (higher PFnet, be3r) unless the
  harness shows 2R is better under 0.8% flat cost.
- Lab variants `minervini_vcp__<variant>__long__1d__h60__v1` (pct8_hard, rr3, ma200_break, ...): entries are the
  real `minervini_vcp_entry_signal`, but their native stops/exits exist ONLY in `scripts/minervini_lab.py` and
  `b412_helpers.simulate_lab_exit` (not main.py). They cannot be wired until each exit is ported into main.py as a
  named function and re-validated calling it (B-412 porting owed). Feature-filter variants (`_f_..._on/off`) also
  need `minervini_lab.features` ported. Registry universe for these is `n200_swing_watchlist`, not full-universe.
  Variant tags must stay distinct per the naming rule; one `_STRATEGY_TAG_TO_REGISTRY_NAME` entry each.
- Many of these variants share the same entry signal: at most one position per symbol (the swing
  `signal_state_swing` PRIMARY key on symbol already enforces it), so rank by PFnet per hold-time and wire the
  top few, not all ~27.

## Known gaps / honest caveats
- Registry sector-rotation numbers came from `scripts/sector_rotation_backtest.py` (vectorised, ATR = plain
  14-bar mean of TR, stop fills AT the stop). The harness uses the real main picks and `main._atr_series`
  and reports three fill models; expect lower PFnet under `gap_aware`/`close`. Wire only if still >= floor.
- `minervini_be` replay skips the RS gate (None), same as b412; earlier registry runs used a rupee-cost model
  and 2y data, so PFnet will differ from the registry number.
- Sector signals are independent overlapping trades (PF per trade), as in the registry run.
- 4h/intraday sector cells are skipped (resample not built); atrnone cells are refused (no-SL rule).
