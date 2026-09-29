# Minervini Trend Template + VCP — research log

Source: *Trade Like a Stock Market Wizard* (2013), `docs/Trade Like a Stock
Market Wizard  (2013).pdf`. Two components: an 8-criterion "Trend Template"
trend qualifier, and a "Volatility Contraction Pattern" (VCP) base/pivot
detector layered on top of it as the entry trigger.

## Part 1 — original research run (2026-09-28/29)

Workflow: `.github/workflows/swing-minervini-trend-template-vcp-research.yml`.
This was an **inline reimplementation** — the Trend Template check,
`_find_vcp_pivot`, and the chandelier trailing-stop exit were all written
directly in the research script, before any of this logic existed as real
`main.py` functions.

Full NSE universe (`m._load_nse_universe_from_file()`, not the NIFTY-200-
restricted `main.NSE_FULL_UNIVERSE`), 2362/2680 symbols fetched, 2-year daily
bars, cross-sectional RS percentile computed once per date across the whole
fetched universe.

| Variant | n_trades | PFnet |
|---|---|---|
| `tt_generic_breakout` (Donchian breakout variant, never built as a real function) | 1,367 | 0.90 |
| `tt_vcp` (the VCP pivot variant) | 325 | 0.90 |

`max_hold_timeout` exits were 100% win rate in this run — flagged at the
time as a possible sign the timeout was cutting winners short, worth
re-checking once real functions existed.

## Part 2 — why a re-validation was needed

CLAUDE.md's standing discipline: *"before trusting a replay result, verify
the replay driver actually calls the changed main.py code — it's a
semi-independent reimplementation... and has drifted before."* That warning
is not hypothetical in this codebase: the TREND-down short mirror built
this same session had a real bug (the RSI band needed reflecting around 50,
not reusing the long side's band verbatim) that was only caught because a
hand-built unit test exposed it. A hand-written research script and the
"real" function it inspired are two different pieces of code until proven
otherwise.

On 2026-09-29, `_minervini_trend_template_ok`, `_compute_minervini_rs_
percentiles`, `_find_minervini_vcp_pivot`, `minervini_vcp_entry_signal`, and
`minervini_vcp_exit_reason` were implemented as real `main.py` functions
(commit `7274ba4`), unit-tested (16 tests, `tests/test_minervini_vcp.py`),
and full pytest + `ast.parse` passed. But the PFnet 0.90 figure above still
belonged to the *research script*, not to these functions — until this run.

## Part 3 — real-function validation run (2026-09-29)

Workflow: `.github/workflows/minervini-vcp-validation-replay.yml`
(run [36566995254](https://github.com/harshv0029/tv-paper-bot/actions/runs/36566995254)).
Every entry/exit/stop/trail decision in this run calls the real
`m.minervini_vcp_entry_signal` / `m.minervini_vcp_exit_reason` directly —
only the RS-percentile table (a vectorized equivalent of
`_compute_minervini_rs_percentiles`'s own formula, cross-checked against it
on synthetic data before the run) and position bookkeeping/cost accounting
are local to the workflow. Same universe loader, same 2-year daily bars,
same cost model as the original run. Single job (RS percentile needs every
symbol's history in one process, so sharding would mean re-fetching the
full universe per shard) — 2362/2680 symbols fetched, ~15 minutes runtime.

**Result:**

| Metric | Original research (reimplementation) | Real-function validation |
|---|---|---|
| n_trades | 325 | 327 |
| PFnet | 0.90 | **0.908** |
| PFgross | — (not reported) | 1.147 |
| win_rate | — (not reported) | 34.56% |
| avg_net/trade | — (not reported) | -₹73.83 |
| avg_held_days | — (not reported) | 15.2 |

By exit reason (real-function run):

| exit_reason | n | win_rate | PFnet | avg_held_days |
|---|---|---|---|---|
| `trail_stop_hit` | 292 (89%) | 31.16% | 0.757 | 14.5 |
| `data_end_forced_close` | 30 | 56.67% | 3.455 | 14.2 |
| `max_hold_timeout` | 5 | 100.00% | inf | 60.0 |

## Verdict

**The real functions reproduce the original research number almost exactly**
(0.908 vs 0.90, n=327 vs n=325) — no replay-driver-drift bug found this
time; the implementation is a faithful match to what was researched. That's
a genuinely good outcome for trusting the code itself.

**The strategy remains below `PFNET_LIVE_FLOOR` (1.0, real breakeven after
costs)** — this run does not change the go/no-go call. `minervini_trend_
template_vcp` stays `RESEARCH` status in `strategy_registry.py`, `is_viable()
== False`, and is NOT wired into `_run_swing_scan`, the live scheduler, or
real order placement.

Two things worth a closer look before any further work on this strategy,
both visible only once the real functions were in place to inspect trade-
by-trade:

1. **`trail_stop_hit` is 89% of all trades and is itself a net loser**
   (PFnet 0.757) — the chandelier stop (`MINERVINI_ATR_STOP_MULT = 2.0`) is
   the dominant exit path and it's not working. `max_hold_timeout`'s 100%
   win rate (both runs) on a tiny n=5 sample is too thin to read anything
   into on its own, but is consistent with the original run's own flag that
   letting winners run longer than the trail stop allows might matter more
   here than in a typical trend strategy.
2. **`data_end_forced_close`'s PFnet 3.455 is a backtest artifact, not
   a real signal** — those are just the 30 positions still open when the
   2-year data window ended, marked to the last available close. A position
   still open near the end of a lookback window is more likely to be one
   that's been running favorably; this number says nothing about live
   performance and should never be read as "the strategy works if held
   longer."

Per the 2026-09-29 "keep testing across candle sizes/from a variety of
sources" thumb rule, this VCP implementation has only ever been tested at
the 1d candle size it was designed for — untested at any other timeframe.
