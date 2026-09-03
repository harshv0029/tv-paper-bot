# Deploy Gate - rules (standing spec, 2026-09-03)

Explicit user request: a dedicated agent that deploys code to production,
but backtests every candidate first - if any rule below is breached, it
flags the user and does NOT push to `main` (Render deploys from `main` on
every push, so not pushing = not deploying); only pushes when every rule
passes. This file is the actual rule set that agent (and the workflow it
runs) is held to - change it here, not in the agent's own judgment, so the
bar stays explicit and auditable rather than vibes-based.

## How it works

1. Trading-logic changes land on the `staging` branch, not `main` directly
   (a real behavior change from this session's earlier pattern of pushing
   straight to `main` - going forward, that's `staging`'s job).
2. `.github/workflows/deploy-gate.yml` is dispatched with `source_ref:
   staging` (or any candidate branch/commit).
3. It runs the checks below against that ref's `main.py`, compares the
   backtest result to `docs/deploy_baseline.json` (the last config that
   passed the gate), and:
   - **All pass** -> merges `source_ref` into `main`, pushes (triggers
     Render's deploy), and updates `deploy_baseline.json` on `main` to the
     new result, so the next gate compares against THIS config, not a
     stale one.
   - **Any breach** -> `main` is left untouched. The job log states
     exactly which rule(s) broke and by how much. The Deploy Gate agent
     relays that to the user and stops - no retry, no partial deploy.

## Rules

### A. Static safety checks (hard invariants, not a backtest)

Read directly off the candidate's `main.py` / `WATCHLIST`, no market data
needed - these should never legitimately fail and catch an obvious bug or
scope slip before it costs anything:

1. Every `WATCHLIST` entry's `risk_pct`/`stop_pct` (or `daily_risk_pct`/
   `risk_per_trade_pct` where used) is <= 2.0 - the standing account-wide
   ceiling (`docs/TRADING_CONSTRAINTS.md`). A number above this is either a
   typo or a policy violation, either way a hard stop.
2. Every `WATCHLIST` symbol is NSE/BSE (`.NS`, `^NSEI`/`^NSEBANK`/`^BSESN`)
   or one of the three approved MCX-proxy commodities (`GC=F`/`SI=F`/
   `CL=F`) - catches an accidental re-add of a delisted symbol (crypto, US
   equities) that a merge conflict or copy-paste could reintroduce.
3. `/trading-control`'s kill switch (pause/resume/kill) is still present
   and wired into both `_auto_signal_core` and `_options_signal_core`'s
   entry gate - a smoke-test import/grep, not a live call. Losing this
   silently would be the worst possible regression.

### B. Backtest regression check (the actual "did this get worse" question)

Same replay method as `trailing-stop-threshold-backtest.yml` - imports the
candidate's `main.py` directly (so it's testing the REAL code, not a
reimplementation) and calls its own live functions, replaying the real
`orb_breakout` entry rule bar-by-bar across ~59 days of 5-min data for the
same 12-symbol sample (3 NSE indices + 10 liquid Nifty 50 names). Compares
the pooled result against `docs/deploy_baseline.json`:

4. **`profit_factor` must not drop by more than 10% relative to baseline**
   (e.g. baseline 0.96 -> floor 0.864). Catches a change that quietly
   makes exits worse (a loosened stop, a broken trailing calc) even if the
   system is still net-losing overall - the point is "did THIS change make
   it worse," not "is it profitable" (it currently isn't, on this sample -
   see TRADING_CONSTRAINTS.md's trailing-stop section - a separate, larger
   issue this gate does not pretend to fix).
5. **`win_rate` must not drop by more than 5 percentage points** relative
   to baseline.
6. **`min_R` (worst single-trade loss, in R) must not be more negative
   than -2.5R** - a hard bound, not relative to baseline. A single trade
   losing more than 2.5x its planned risk means the stop-loss logic itself
   is broken (it should structurally never happen given `stop_pct`
   capping), independent of how the baseline looked.
7. The backtest script itself must run to completion without an
   exception - a crash is an automatic breach, not a silent pass.

## What this does NOT do

- Does not require the system to be profitable to deploy (it isn't, on
  the current 59-day/12-symbol sample - see the trailing-stop backtest
  finding). Deploying a fix for a KNOWN issue should not be blocked by
  the issue it's fixing still being visible in the same backtest window.
- Does not gate non-trading-logic changes (docs, UI, CI workflows) -
  those still go straight to `main` as before; running a market-data
  backtest for a typo fix would be wasteful and could false-flag on
  sample noise unrelated to the change.
- Is not a substitute for a longer/wider backtest before a genuinely new
  strategy or a big parameter change - it's a fast regression net for
  routine changes, not a full research pass (`entry-trigger-research.yml`'s
  job).
