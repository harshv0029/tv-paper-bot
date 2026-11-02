# B-775: count of tags with PFnet >= 1.1, hold <= 5 trading days, planned SL <= 2%

Measured 2026-11-02 IST at branch base 39bc1e98 (registry: 41,869 tags). Everything here is derived at read time from
data already in the repo. No backtest was re-run and no number was guessed.

Reproduce:

    python3 scripts/count_sl_cap.py --floor 1.1      # the user's question (1.1 floor)
    python3 scripts/count_sl_cap.py                  # registry floor (PFNET_LIVE_FLOOR, currently 1.0)

## Answer

| Floor | Hold <= 5d | SL <= 2% (pass) | SL > 2% | Stop unknown | Unknown share |
|---|---|---|---|---|---|
| PFnet >= 1.1 (user question) | 244 | **92** | 129 | 23 | 9.4% |
| PFnet >= 1.0 (current live floor) | 355 | 103 | 210 | 42 | 11.8% |

No tag has an unrecorded hold. `strategy_registry.PFNET_LIVE_FLOOR` is 1.0 since 2026-10-14 (the user's instruction
superseded the 1.1 floor), so the 1.1 figure is reported with `--floor 1.1`.

The 92 passers at 1.1, by family and candle size: chan_kalman 5m 57, chan_kalman 15m 22, macddiv 1h 4, lunar 5m 4,
lunar 15m 3, month 15m 1, chan_tsm 1h 1. None are on 1d. The 129 over the cap are mostly 1h/1d families (brk20_min_rr
1h 26, sector_rotation 1d 17, gaps 1d 14, chan_kalman 15m 12, chan_gap 1d 10, macddiv 1h 10, and others).

## Basis (what "stop-%" means here)

`docs/backtest_data/stop_pct.json` = {tag: planned stop-%}. Basis (`docs/backtest_data/stop_pct_basis.json`):
- ATR tags: the tag's ATR multiple x the full-universe median ATR14/close at the tag's candle size
  (`docs/backtest_data/atr_pct_by_tf.json`: 5m 0.300, 15m 0.572, 1h 1.267, 1d 4.075, 1w 9.138; no 4h row yet).
  This is a universe-median PLANNED stop, not a per-trade measurement.
- `pct<N>` tags: exactly N%. O'Neil `tgt` mode: fixed 8%.

This pass re-derived the sidecar from the stored ATR table with `python3 scripts/measure_stop_pct.py` (no fetch).
That added 1,800 tags registered since the last measuring run and dropped none, which cut the unknowns at the 1.0 floor
from 110 to 42.

## Unknown stop-% at PFnet >= 1.1 (23 tags), by research workflow/script

| Source | Tags | Why unknown | What would measure it |
|---|---|---|---|
| scripts/pattern_lab.py | 11 | `atrnone`: no stop in the backtest (starc 1d 2, tasuki 1d 1, envelope 1h 2, base 1h 1, lunar 1h 1, month 15m 2, lunar 15m 1) | No planned stop exists. Under the no-trade-without-SL rule these need a stopped re-run (their own tags) |
| scripts/sector_rotation_backtest.py | 7 | 4 `atrnone` (1d); 3 are ATR tags at **4h** (`atr2d5`), and the ATR table has no 4h row | `measure_stop_pct.py --fetch --tfs 4h` (1h resampled; Actions, owed) measures the 3 ATR ones |
| scripts/intraday_flatten_rerun.py | 4 | `atrnone` lunar v2 15m/5m (`|full`, `|n200`) | Same as atrnone above |
| scripts/chan_gap_long_main_replay.py | 2 | `atr4d0cap5` / `fit5`: the stop is capped at `REAL_INTRADAY_MAX_STOP_PCT` (5%). That is an upper bound, not a value, and the exact % is not stored | The replay should emit per-trade stop-% (now supported by the shared emitter, below) |

## Emitters now carrying stop-%

- `scripts/pattern_lab.py` and `scripts/combo_lab.py`: per-cell `median_stop_pct` (already present).
- `scripts/research_hold_summary.py` (the shared B-420 summary used by the validation-replay workflows): `summarize()`
  now emits `median_stop_pct`, the median per-trade planned stop distance. It uses the trade's `stop_pct` if set, else
  |entry_price - initial_stop (or stop)| / entry_price. It is None when no trade carries a stop. It is also a column
  in summary.tsv.
