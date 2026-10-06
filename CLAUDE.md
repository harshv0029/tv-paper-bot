# CLAUDE.md — read this before doing anything else

This is a **live, real-money** trading bot (NSE/MCX via Kotak Neo), developed
entirely through Claude Code sessions. Mistakes here cost the user real
money. Read this file fully before touching branches, git history, or
entry/exit/sizing logic.

## Incident: a validated real-money fix was silently lost (2026-09-14)

A prior session implemented and fully validated two exit-logic bug fixes
(RANGE regime's degenerate stop-loss; `trend_weakened` misapplied to RANGE
positions) on branch `claude/determined-meitner-3btijk`, and left them
unmerged pending a user decision — correct discipline. A **later** session,
picking up separate NIFTY200-universe work, reused that same branch name
under this repo's "if the PR for your branch already merged, restart the
branch from main" rule. That rule requires keeping/rebasing any unmerged
commits forward — but the later session force-reset the branch without
first checking for them, silently discarding both validated fixes. The next
session's transfer pack reported them as "done, tested, validated, sitting
on branch X, ready to merge" — which was **no longer true**; the code was
never on `main` and production kept running the buggy versions. The gap was
only caught by chance during unrelated work, by diffing git history instead
of trusting the transfer pack's prose.

**Never let this pattern repeat:**

1. **Before reusing, resetting, or force-pushing to any branch**, run
   `git log --oneline <branch> ^origin/main` (or `git diff main
   origin/<branch> --stat`) and actually look at the output. If it shows
   commits/files beyond what you're about to add, STOP — those are someone
   else's unmerged work. Rebase them forward onto the new base; never
   silently discard them, even if the branch's *named PR* already merged
   (a branch can carry unmerged commits stacked after a merged PR).
2. **A transfer pack, session summary, or your own memory of "what's done"
   is a claim, not a fact.** Before relying on "fix X is validated and
   sitting on branch Y ready to merge" (or similar), verify it against
   actual git state (`git log`, `git diff` against current `main`) —
   especially before making a decision that assumes it's true (shipping,
   skipping re-validation, telling the user it's handled). This cost real
   time and left a known bug live in production for over a day.
3. **After any branch reset/rebase, sanity-check that CLAUDE.md loaded and
   the expected fixes are actually present** in the file (e.g. `grep` for
   the function/constant a prior session said it added) before reporting
   status to the user as unchanged from a prior transfer pack.
4. If you discover a gap like this, **say so plainly and immediately** —
   don't quietly patch around it or bury it in a status update. The user
   needs to know a validated fix regressed out of production.

## Standing real-money discipline (do not relax without explicit user ask)

- Never tune score weights/thresholds/regime boundaries/exit ladder/
  position-sizing based on one replay result, blind. A bad result is a
  trigger to root-cause it, not to nudge a parameter.
- Any change to entry/exit/sizing logic: implement → unit test → full
  pytest suite green → full 52-symbol/60-day validation replay via
  `.github/workflows/universal-score-validation-replay.yml` → report
  results honestly (including when a fix doesn't move the numbers).
- **Before trusting a replay result**, verify the replay driver actually
  calls the changed `main.py` code — it's a semi-independent
  reimplementation, not a call into `main.py`'s live functions for every
  piece of logic, and has drifted before (see git history/commit messages
  around 2026-09-14 sizing/RANGE-stop fixes for a concrete example of this
  exact gotcha).
- Never merge to `main` (via `deploy-gate.yml`) without the user's explicit
  go-ahead.
- Every commit: full test suite green, `ast.parse` sanity check on
  `main.py`, Claude attribution footer.
- **Thumb rule (2026-09-28, explicit user instruction): every strategy —
  new or existing — gets checked for BOTH directions, long (buy-to-sell)
  and short-sell, not just long.** When researching, backtesting, or
  building a strategy, always ask "does this mirror into a short, and
  should it?" as a matter of course, not only when short-selling is
  explicitly requested. Applies going forward to every strategy in this
  codebase, not only the one (RANGE-regime VWAP mean reversion) whose
  short mirror was researched first — see
  `.github/workflows/universal-score-range-short-research.yml` for the
  first application of this rule and why a full TREND-side short mirror
  was scoped out of that first pass (a separate, larger undertaking, not
  a rule exception).
- **Thumb rule (2026-09-29, explicit user instruction): every backtest/
  research pass from now on runs on the FULL NSE universe (~2,680 real
  symbols, via `main._load_nse_universe_from_file()`), not a 52-symbol
  or other narrow sample.** A small-sample pilot is fine as a first,
  cheap correctness check, but the result that gets reported/trusted for
  a go/no-go call must be the full-universe number — a 52-symbol sample
  moved PFnet by as much as 0.35 in either direction versus the full
  universe on the same exact strategy (Minervini VCP research,
  2026-09-28/29: 52-symbol PFnet 0.65 vs full-universe PFnet 0.90 on
  n=325 vs n=15 — the small sample wasn't wrong exactly, just too thin to
  trust on its own). **Do not read `main.NSE_FULL_UNIVERSE` for this** -
  by the time a script imports `main`, that name has been reassigned to
  its NIFTY-200 intersection (a separate, live-trading-scope restriction,
  2026-09-14 "trade only in NIFTY 200" instruction) and silently returns
  only ~200 symbols. Call `_load_nse_universe_from_file()` directly for
  research to get the true, unrestricted full universe.
- **Thumb rule (2026-09-29, explicit user instruction): a strategy is not
  confined to one `TradeCategory`.** The same validated strategy can
  independently qualify for, and be ranked in, more than one of
  `strategy_registry.py`'s 5 category leaderboards at once (short_sell,
  buy, swing, futures, options) — categories are independent leaderboards
  a strategy can sit on zero, one, or several of, never a partition that
  forces a single home. `StrategyDef.categories` is a tuple for exactly
  this reason. Adding a strategy to a second category still requires its
  own separately validated `Metrics`/evidence pointer for that category's
  actual entry/exit mechanics — never inherit a PFnet untested there just
  because the strategy already cleared a different category elsewhere.
- **Thumb rule (2026-09-29, explicit user instruction): each category's
  top-5 leaderboard is a standing, ever-growing pool, never a one-time
  snapshot.** Every strategy tried, in every category it qualifies for,
  gets registered with its real metrics (never omitted for looking bad),
  and the top-5 keeps updating to prefer whichever validated strategy is
  actually best the instant a better one clears validation — see
  `strategy_registry.py`'s `leaderboard()`. This bounds live monitoring
  cost by construction, not by registry size: 5 categories × top 5
  strategies each = **25 strategy-checks per stock/asset unit per
  round-robin monitoring cycle**, however many strategies have ever been
  registered or tried historically. Growing the overall registry never
  grows per-stock monitoring cost — only which (up to) 25 checks actually
  run each cycle changes as better strategies displace worse ones.
- **Thumb rule (2026-09-29, explicit user instruction): keep searching for
  better algorithms from a variety of sources, and test every strategy
  across multiple candle sizes, not just parameter nudges on what's
  already in this repo.** Two standing habits, applied whenever research/
  strategy-building work happens here (on request, not as an unattended
  background job — the user explicitly chose "standing discipline, not an
  automated daily Routine" when this was raised):
  1. Candidate strategies should keep coming from outside this repo's own
     trial-and-error too — named/documented approaches from TA literature,
     other markets, web research — not only factor tweaks on strategies
     already tried here.
  2. Every strategy (new or existing) should be tried across multiple
     candle sizes/timeframes as a matter of course — **1m, 5m, 15m, 1h,
     4h**, plus whatever timeframe actually fits its own use case (e.g.
     1d for swing strategies like gap-and-go/Minervini VCP) — not just
     the one timeframe it happened to be built on. A strategy's edge can
     look completely different at another granularity; the RANGE VWAP
     short mirror, the TREND-down short mirror, and the RSI-overbought
     fade were all tested only at 5m this session and have never been
     re-checked at another candle size.
  Every other standing rule here still applies to this: no tuning blind
  off one variant's result, full-universe validation before trusting a
  number, and calling the real `main.py` function (not a reimplementation)
  for anything that will actually inform a go/no-go call.
- **Thumb rule (2026-09-29, explicit user instruction, after a same-day
  revert): ask before creating any new real-trading kill switch.** Never
  add a new `is_real_*_trading_enabled()` / `REAL_*_TRADING_ENABLED`
  env-var gate on your own initiative, even to isolate a newly-wired
  strategy "safely." The user wants exactly **one** switch for manually
  shutting down live trading, not a growing set of category-specific
  switches they can't track on Render — see the incident: a
  `REAL_MINERVINI_VCP_TRADING_ENABLED` switch was built unasked when
  Minervini VCP was wired into the live swing scan, and was reverted the
  same day once flagged ("I just want one switch... not many trading
  switches which I will not able to track"). `is_real_trading_enabled`
  (equity), `is_real_fo_trading_enabled` (F&O), and
  `is_real_swing_trading_enabled` (swing, now shared by both gap_and_go
  and Minervini VCP) already exist from before this rule and are NOT to
  be treated as precedent for adding more — any new strategy needing real-
  order gating shares whichever of these three already fits its asset
  class/timeframe, unless the user explicitly asks for a new one.
- **Thumb rule (2026-09-29, explicit user instruction): whenever the user
  shares a book, PDF, or other resource, extract and try EVERY strategy it
  describes — never skip any, never cherry-pick only the ones that look
  most promising on a first read.** Each one gets the full established
  cycle, no shortcuts: implement (or faithfully reimplement for research)
  → unit test → full-universe validation replay calling the real `main.py`
  functions → test across candle sizes per the 2026-09-29 candle-size
  thumb rule where the strategy's own timeframe isn't obviously fixed →
  report the honest result → add it to `strategy_registry.py`'s pool with
  its real metrics regardless of outcome (a strategy that fails is still
  record-worthy - see this file's own PFNET_LIVE_FLOOR/is_viable()
  discipline). The explicit goal behind this (user's own words): "create
  such universe with time and be profitable as per your hybrid strategy,
  learn from your workings and mistakes" - the strategy pool is meant to
  keep growing from real outside sources (not just this repo's own trial-
  and-error) until a genuinely profitable combination emerges, and every
  documented failure (the short-selling research log, the Minervini VCP
  log) is itself the record of what's already been tried, so the search
  never blindly repeats it.
- **Thumb rule (2026-09-29, explicit user instruction): whenever a
  `strategy_registry.py` change shifts any category's top-5 leaderboard
  ranking, the trade-view dashboard must reflect it automatically post-
  merge - never a separate "go update the dashboard" step.** This is
  already how it's built, and must stay that way: `static/trade-view.html`
  fetches `GET /strategy-leaderboard` fresh on every ~10s poll cycle, and
  that endpoint (`main.strategy_leaderboard()`) calls
  `strategy_registry.leaderboard()` live, straight off the current
  `REGISTRY` - there is no hardcoded snapshot, cached table, or build step
  anywhere in between. The instruction that prompted this rule (after
  `gap_and_go_short_fade`'s registration flipped short_sell's #1 slot,
  2026-09-29): merging a registry change is the ONLY step required for the
  dashboard's Category/Rank/Strategy/PFnet/Win% columns (both per-trade-
  row and the appended full-leaderboard block) to pick up the new
  ranking - the next page load after deploy already shows it. If a future
  change to either file ever breaks this (e.g. caching the leaderboard
  response, hardcoding rows, or gating the fetch behind something that
  isn't "every poll"), that regresses this rule and must be fixed, not
  worked around with a manual re-sync step.
- **Thumb rule (2026-09-30, explicit user instruction, MFSL.NS incident:
  a genuinely bot-placed real position sat open with ZERO stop-loss
  order anywhere at Kotak, unnoticed until a human happened to see it on
  the dashboard - "Make sure that this does not repeat... Do some back
  check during live market or live trades"): a periodic backcheck against
  Kotak's own order book, verifying EVERY currently-open real position
  (tracked or not in this app's own tables, long or short) actually has a
  live resting stop-loss, must keep running at least every 5 minutes
  during market hours, for as long as this bot places real orders - never
  relaxed to a slower cadence, disabled, or narrowed to only
  this-app-tracked positions without an explicit user ask.** This is
  `main._find_unprotected_open_positions` (called from
  `_reconcile_real_positions_core` on every run, deliberately NOT gated
  by `adopt` and NOT filtered by this app's own order tag - an
  unprotected position is unprotected real money whether or not this app
  placed it), `.github/workflows/kotak-reconcile.yml`'s `*/5 3-10 * * 1-5`
  cron (tightened from */15 for exactly this), the persisted
  `real_protection_snapshot` table, the no-token `GET
  /real-protection-status` endpoint, and `static/trade-view.html`'s red
  banner fed by it (shown for a genuinely unprotected position AND for a
  stale/missing check - an old "all clear" must never be read as a
  current one, since that silence is exactly what let MFSL go unnoticed).
  Root cause behind the incident itself: `real_positions`' own tracking
  row for MFSL was lost after entry (a crash/restart between Kotak
  confirming the fill and this app's local INSERT is the leading
  hypothesis - never fully confirmed, since the position was adopted and
  protected before a root-cause investigation could be completed), and
  every OTHER piece of this app's own SL logic (`_maybe_sync_real_stop_loss`,
  the governance-backfill block) only ever manages rows it still has a
  local tracking row for - none of them would have caught this on their
  own, which is exactly why this check deliberately goes straight to
  Kotak's own ground truth instead of trusting any local table. Applies
  going forward to every new real-order code path added to this bot (a
  new asset class, a new order type, a new strategy wired into real
  trading): before shipping it, confirm a position it opens is still
  covered by this SAME backcheck (matched by `kotak_open_by_trdsym`'s own
  long/short net-qty sign, not by strategy or asset-class-specific logic)
  - detection alone is not enough (see the next paragraph on auto-heal).
- **Thumb rule (2026-09-30, explicit user instruction, same MFSL.NS
  incident: "For short positions and all live positions make it auto
  heal"): detection (the backcheck above) is not sufficient on its own -
  a real position with no live stop-loss, long or short, tracked or not,
  must get a protective order placed AUTOMATICALLY, not just flagged for
  a human to fix by hand.** Long positions already had this since
  2026-09-08 (`_reconcile_real_positions_core`'s adopt block +
  governance-backfill loop, which places a real SL synchronously in the
  SAME request rather than waiting for a scheduler tick that a wrapping
  git-push/restart could lose the race against). Shorts did NOT - short
  auto-adopt and the short governance-backfill's synchronous SL placement
  (mirroring the long path exactly: `_kotak_symbol_still_open_short`,
  `_ensure_signal_state_for_real_position_short`,
  `kotak_real_orders.place_real_short_stop_loss` called from
  `_reconcile_real_positions_core`'s own short-specific backfill loop)
  were built this same day to close that asymmetry - this is what "make
  it auto heal" means concretely: not a louder alarm, an actual fix,
  attempted every single reconcile run (every 5 min) for every open
  position this app can safely act on. The one boundary this auto-heal
  deliberately does NOT cross, matching the adopt block's own pre-existing
  safety philosophy (own docstring: "auto-adopting a position this app
  didn't open and doesn't know the intended stop/target... risks the kill
  switch or scheduler later acting on it with no real context"): a
  position's ENTRY gets adopted-and-governed either way (bot-placed or
  manually placed at Kotak directly - explicit 2026-09-08 precedent,
  unchanged), but this app only ever computes/places a stop off ITS OWN
  WATCHLIST risk config applied to the real entry price, never a stop
  level guessed for a position with no derivable risk config at all. A
  case that still can't be auto-healed (no WATCHLIST entry, entry price
  unrecoverable, or the placement itself fails - e.g. margin/T1) still
  surfaces loudly through the backcheck above and must keep doing so -
  auto-heal narrows how often the alarm fires, it does not replace the
  alarm. **Update, same day:** `_maybe_sync_real_stop_loss_short` (the
  30-second-tick trailing-stop/retry/degraded-protection engine, full
  parity with the long side's `_maybe_sync_real_stop_loss`, wired into
  the scheduler tick's own short-scan block) was built the same day this
  rule was written, closing the gap described in the paragraph below -
  a short position's stop now trails and self-heals on the SAME cadence
  as a long's (every tick, not just every 5 min), using
  `_real_held_qty_short`/`_reconcile_real_qty_short`,
  `_place_real_stop_loss_with_retry_short`,
  `_mark_protection_degraded_short`/`_clear_protection_degraded_short`,
  and `kotak_real_orders.cancel_existing_resting_sl_short` alongside the
  already-generic (order-id/symbol/capital-keyed, direction-agnostic)
  `_real_sl_order_is_live`, `_is_t1_restricted`/`_flag_if_t1_restricted`,
  `_protection_degraded_timeout_seconds`, and
  `is_cas_transition_rejection`, which needed no short-specific copies at
  all. Emergency escalation covers (`_maybe_place_real_short_exit`, a
  buy-to-cover) rather than sells - never the long side's exit function
  for a short position. The paragraph immediately below is kept for the
  historical record of the gap and the reasoning that motivated closing
  it, not because the gap is still open.
  rather than assuming it automatically is.
- **Thumb rule (2026-09-30, explicit user instruction, second live
  occurrence of the MFSL.NS pattern - TCS.NS and INDIANB.NS both sat with
  NO live resting stop-loss at Kotak for a real stretch of market time,
  found by the user directly on the Kotak app, not by this app's own
  dashboard): the "unprotected position backcheck every 5 min during
  market hours" rule above must never depend solely on an external
  scheduler's own reliability.** Root cause of this second occurrence:
  the entire guarantee lived in `kotak-reconcile.yml`'s GitHub Actions
  cron (`*/5 3-10 * * 1-5`) - checking that workflow's own `event:
  schedule` run history (not `workflow_dispatch`) showed real gaps of
  5-8+ hours between fires on 2026-09-28/29/30, not the ~5 min the cron
  string calls for. GitHub's own docs warn scheduled workflows "can be
  delayed during periods of high load," and this repo dispatches an
  unusually high volume of other workflow runs - empirically, GitHub was
  not honoring this repo's `*/5` schedule at anywhere near that cadence.
  Fix: `_scheduler_tick` (the in-process ~30s loop already proven
  reliable all session - it's what runs `_maybe_sync_real_stop_loss`/
  `_maybe_sync_real_stop_loss_short` every tick) now ALSO calls
  `_reconcile_real_positions_core(adopt="*")` every
  `_UNPROTECTED_BACKCHECK_EVERY_N_TICKS` ticks (~5 min), so the 5-min
  guarantee is enforced by this process itself, not by any external
  scheduler. `kotak-reconcile.yml`'s cron stays as a secondary check plus
  the durable git-log audit trail (`docs/real_reconcile_log.json`), never
  removed just because the in-process path now covers the primary
  guarantee. Applies going forward: any future "must run periodically"
  real-money safety rule in this file should default to an in-process
  scheduler-tick mechanism first, and treat a GitHub Actions cron as a
  secondary/audit layer only - not the other way around.
- **Thumb rule (2026-09-30, explicit user instruction): every request
  this app sends to Kotak to place, modify, or cancel a real order must
  be based on freshly-fetched live account state, not a trusted local
  cache.** The user's own words: "Before each request in order book, U
  must fetch All live trades taken and All order requested parked at
  trading account side. Based on that and ur logic, U request for next
  order." Concretely: before deciding the next real-order action for a
  symbol, fetch Kotak's own `positions()`/`order_report()` (or reuse a
  same-request fetch no older than that decision) rather than trusting
  this app's own DB columns (`sl_order_id`, `real_positions.qty`, etc.)
  as ground truth for whether a resting order is actually still live.
  This is already the pattern the 2026-09-30 short per-tick engine and
  `_reconcile_real_positions_core` follow (`_real_sl_order_is_live`
  checks the live order_report, not just whether `sl_order_id` is
  non-NULL locally; `_reconcile_real_positions_core` re-fetches
  `order_rows` fresh immediately before its own unprotected-check so a
  position it just healed isn't flagged stale) - this rule makes that
  discipline explicit and standing for every current AND future real-
  order code path, not just the ones that happened to need it so far.
  Never add a new real-order code path that decides its next action off
  a locally-cached order/position field without a live Kotak fetch (or a
  fetch fresh enough within the same request) to confirm it first.
- **Thumb rule (2026-09-30, explicit user instruction, confirmed via
  AskUserQuestion after being shown the actual consequence: "Yes -
  disable non-viable live strategies now"): a NEW real position may only
  ever be opened for a strategy whose strategy_registry.py metrics clear
  PFnet >= PFNET_LIVE_FLOOR (1.0), across every category (buy, short_sell,
  swing, futures, options).** This is `_is_strategy_viable_for_real_money`
  (main.py), wired into the three NEW-entry functions
  (`_maybe_place_real_entry`, `_maybe_place_real_short_entry`,
  `_maybe_place_real_swing_entry`) via `_STRATEGY_TAG_TO_REGISTRY_NAME`'s
  strategy-tag-to-registry-name mapping - fails CLOSED on anything
  unrecognized or unmeasured, since real money should never go where
  there's no evidence of clearing breakeven. It is a PERMANENT, registry-
  driven gate, not a one-time manual disable: if a currently-blocked
  strategy is later re-validated at PFnet >= 1 (or a new one clears it),
  the gate opens automatically the next tick with no code change; a
  currently-live strategy that later degrades below the floor is blocked
  automatically too. Deliberately NOT a new env-var kill switch (this
  file's own "ask before creating any new real-trading kill switch"
  rule, and no new switch was asked for here) - it only ever governs
  whether a brand NEW position opens; it is never referenced from an
  exit/SL-sync/auto-heal function, so a position already open when its
  strategy fails the floor is still fully protected/managed/closeable,
  never orphaned by this gate.
  As of 2026-09-30, this means REAL intraday trading is effectively
  paused on both sides: `universal_score` (the only strategy tag every
  WATCHLIST symbol uses for long intraday, PFnet 0.05) and both short
  engines (`range_short_staged_ladder` 0.21, `trend_down_momentum_short`
  0.09) are all blocked - nothing currently registered replaces them.
  Real swing trading continues for `gap_and_go` (PFnet 1.65, viable) but
  NOT for `minervini_vcp` (PFnet 0.908, just under the floor - confirmed
  via that registry entry's own `source` field pointing at the exact live
  `minervini_vcp_entry_signal`/`minervini_vcp_exit_reason` functions,
  never guessed from the name). Futures/options have no real order-
  placement path at all regardless of this gate. Paper trading (the
  non-real engine) is completely unaffected - this gate only ever
  touches whether a paper signal gets MIRRORED as a real order.
  Companion change, same instruction: the trade-view dashboard's
  `/strategy-leaderboard` now calls `strategy_registry.viable_leaderboard()`
  instead of `leaderboard(top_n=5)` - every strategy per category that
  clears the floor, unbounded, never just a top-5-by-rank view that could
  include a non-viable strategy. Deliberately did NOT touch
  `TOP_N_PER_CATEGORY`/`leaderboard()`/`top_strategies_for_monitoring()`
  themselves (a separate, unrelated live-monitoring-cost-bounding
  mechanism per the 2026-09-29 "25 checks per cycle" thumb rule) or
  `all_strategies_info()`'s own per-trade-row Category/Rank lookup
  (deliberately still shows a non-viable strategy's actual rank, per its
  own 2026-09-30 fix for the "blank cell" bug earlier this session - see
  that function's own docstring for why "viable-only" there would
  regress it).
- **Thumb rule (2026-09-30, explicit user instruction): a single full-
  universe validation replay is a BASELINE, never the last word - every
  strategy backtest from now on also sweeps (a) parameter values, plus/
  minus around the baseline, and (b) candle size where the strategy's own
  design is bar-size-agnostic, before its result is treated as final for
  a viability/go-no-go call.** Prompted by failed_breakout_short's own
  baseline (run 36712440006, PFnet 0.657): its exit-reason breakdown
  showed trail_stop_hit (71% of trades) as a clear net loser (PFnet
  0.138) while trades surviving to the max_hold_timeout were extremely
  profitable (PFnet 47.3) - a specific, data-motivated lever
  (FAILED_BREAKOUT_ATR_STOP_MULT) worth sweeping, not something to notice
  and leave on the table. This is NOT the "never tune blind off one
  result" rule's exception - it's what that rule always meant by the
  sanctioned alternative to blind tuning: a STRUCTURED, HYPOTHESIS-
  DRIVEN sweep across several values, each one independently full-
  universe validated calling the real main.py function (never a
  reimplementation), with every result reported honestly - not eyeballing
  one bad number and nudging a constant. See
  `failed-breakout-short-atr-mult-sweep-research.yml` for the pattern:
  same replay_symbol loop as the baseline replay, the ONE constant being
  swept overridden on the `main` module before the loop runs (so the real
  exit function reads it fresh, unmodified otherwise), matrixed across
  several candidate values in one workflow dispatch.
  Explicit sub-rule on holding period, same instruction: if a sweep or a
  baseline's own exit-reason breakdown shows a specific holding-period
  behavior is what actually drives the good numbers (here: surviving to
  the full 30-day max-hold), and a parameter change can make that
  intrinsic to the strategy's own design (e.g., a wider trail multiplier
  so trades naturally run longer instead of getting stopped early) -
  adopt whichever swept variant genuinely clears PFNET_LIVE_FLOOR and
  register it under strategy_registry.py's viable category for
  implementation, not just as a research curiosity. But prefer a
  SHORTER average holding period over a longer one whenever a swept
  variant achieves comparable-or-better PFnet with less time-in-trade -
  faster capital turnover for the same or better edge is strictly
  preferable, never chase a long hold for its own sake once a shorter,
  equally-or-more-profitable alternative is on the table from the same
  sweep.
  Candle-size sweep is NOT universal - a strategy whose lookback/hold
  constants are expressed in whole trading DAYS via bar-index arithmetic
  (failed_breakout_short's own resistance-lookback/exclude-window/max-
  hold constants, for example) isn't bar-size-agnostic without first
  re-deriving every one of those constants in bar-count terms for the
  new granularity - flag that honestly as a separate, larger piece of
  work rather than silently skipping the sweep or faking it with a
  resample. A strategy built bar-size-agnostically from the start (ATR/
  bar-count based constants, like Gap-Up Fade) can sweep candle size
  directly by just changing the replay's own INTERVAL/PERIOD.
- **Thumb rule (2026-09-30, explicit user instruction: "Multiplying money
  in shorter duration is always preferable... Make it part of thumb rule.
  Always."): faster capital turnover is a standing, ALWAYS-ON preference
  across every strategy decision in this codebase, not just the sweep
  tie-break above.** The sweep-specific "prefer shorter hold over longer
  when PFnet is comparable-or-better" rule immediately above is one
  application of this; this rule generalizes it to every place a choice
  gets made between strategies/variants of otherwise similar quality:
  registering a strategy in `strategy_registry.py`, choosing which
  viable strategy a symbol trades when more than one qualifies, ranking
  within `viable_leaderboard()`/`leaderboard()`, and picking which
  candidate to pursue further in research. The comparison is always
  PFnet (or equivalent risk-adjusted edge) per unit of TIME held, not raw
  PFnet alone - a strategy that turns capital over faster for the same or
  better edge compounds more real money per calendar day and is always
  preferable, all else equal.
  This does NOT override PFNET_LIVE_FLOOR or any other viability gate -
  a faster but non-viable (PFnet < 1) strategy is still non-viable and
  still blocked from real money by `_is_strategy_viable_for_real_money`;
  speed is a tie-breaker/ranking preference among strategies that already
  clear the bar, never a reason to admit one that doesn't. It also does
  NOT excuse skipping full-universe validation or the parameter/candle-
  size sweep discipline above to chase a faster number quickly - "always
  preferable" means always weighed honestly with real validated metrics,
  never estimated or assumed to save time.
- **Override (2026-10-01, explicit user instruction, after being shown the
  conflict and confirming anyway): the 2026-09-21 "no entries 9:15-9:30"
  rule is lifted.** `NO_ENTRY_WINDOW_AFTER_OPEN_MINUTES` (main.py) changed
  15 -> 0 (constant kept, not deleted, for easy reversal). User's stated
  reasoning: "Since you back tested for 9:15 till market closing You can
  take trade for all category... All starting 9:15am." Two things were
  surfaced before this was applied, both still true and worth remembering:
  (1) this gate only ever existed in the long intraday engine
  (`_auto_signal_core`) - short entries (`_short_signal_core`) and swing
  (`_run_swing_scan`) already had no equivalent restriction, so they were
  already effectively "starting at 9:15"; (2) no full-universe replay has
  ever separately broken out the 9:15-9:30 trades' own PFnet from the
  pooled number - the original 2026-09-21 rule was a microstructure
  judgment call (opening-auction imbalance, indicators short on same-
  session data), not something the backtests specifically validated one
  way or the other for that window. The user was shown both points via
  AskUserQuestion and explicitly chose to remove the gate anyway rather
  than shrink it or measure the window's own numbers first - this is a
  deliberate, informed override, not evidence the opening-volatility
  concern was wrong. Futures/options were also named in the same
  instruction but have NO real order-placement path at all (per the
  PFnet-gate rule above) - nothing to change there; this override only
  has any live effect on the long intraday engine, since short/swing
  already behaved this way.
- **Thumb rule (2026-10-05, explicit user instruction): a different
  strategy tag/name is never silently treated as the same strategy as
  another, even when it currently maps to the same registry entry,
  metrics, or outcome - keep every distinctly-named tag as its OWN
  separate row/record. A different name is evidence of a real,
  deliberate variation until shown otherwise; collapsing two names into
  one on the assumption they're duplicates is the mistake this rule
  forbids, not something to do first and ask about later.** Prompted by
  `/strategy-scan-activity`'s first cut (same session): `gap_and_go` and
  `orb-swing-gap-and-go` both resolve to the `gap_and_go_swing` registry
  entry via `_STRATEGY_TAG_TO_REGISTRY_NAME`, so the endpoint deduped them
  into a single row "to avoid showing the same strategy twice" - reverted
  per this instruction into two separate rows, even though
  `orb-swing-gap-and-go` has zero other reference anywhere in `main.py`
  (confirmed by grep) and will read `scans_today=0` forever unless
  something is actually wired to record scans under it. That zero is the
  correct, honest thing to show - "this tag is registered but nothing
  currently uses it" - not a defect to paper over by merging it into a
  same-registry sibling. Applies everywhere in this codebase a tag/name
  comparison could tempt a "these are basically the same thing" shortcut:
  registry entries, dashboard rows, aggregation keys, scan/entry counters,
  leaderboard rows - never fold two differently-named things together
  without the user explicitly confirming they really are one thing wearing
  two names, and even then, say so plainly rather than merging silently.
- **Thumb rule (2026-10-05, explicit user instruction): all strategy
  research from now on follows the combinatorial Indicator Repository
  methodology in `docs/INDICATOR_COMBINATORICS_METHODOLOGY.md` - read
  that file in full before starting any new indicator/strategy research
  pass.** Summary (full spec in that file): build a catalog of every
  indicator this repo has (most already exist as atomic single-indicator
  branches in `main.add_strategy_signal`, e.g. `rsi_reversal`,
  `macd_cross`, `bollinger_mean_reversion`, plus standalone research-stage
  functions like order-block delta and Volume Profile/POC). For each
  indicator, sweep its FULL internal parameter grid (every variant, not a
  handful of eyeballed values) and validate each variant standalone as its
  own strategy. Then combine indicators pairwise (both role orderings -
  which one triggers vs. which one filters - per the user's "5P4
  permutation" framing, not just which variants are paired), then
  triple-wise, across multiple timeframes. When a genuinely new indicator
  is found later (a new book, a new web search), it gets tested standalone
  and then combined with EVERY non-empty subset of the existing indicator
  pool, not just a convenient few - the full power-set recursion, flagged
  honestly as exponential, with any prioritization-for-tractability
  surfaced plainly rather than silently narrowing the rule. Every other
  standing rule above still applies unchanged to every cell of this grid:
  real `main.py` functions over reimplementations, full-universe
  validation, cost-aware sizing, both directions, candle-size sweep, never
  tune blind, register every variant/combo tried with real metrics (pass
  or fail), `PFNET_LIVE_FLOOR` gates real money, faster turnover as
  tie-break, and never silently merge two differently-tagged
  variants/combos (the rule immediately above, now explicitly extended to
  this entire combinatorial search).
- **Incident (2026-10-05): a real swing position's strategy identity and
  stop-loss were both lost to restart amnesia, and nothing closer than a
  once-a-day retry existed to auto-heal it.** Live NYKAA.NS, found by the
  user directly (dashboard showed its own strategy flip from `gap_and_go`
  in the morning to `universal-score` later the same day; Kotak's app
  showed no resting SL at either point). Root cause, confirmed from code:
  `real_positions_swing` (built 2026-09-22) was never added to the Upstash
  Redis durability mirror `real_positions` got 2026-09-08 and
  `real_positions_short` got 2026-09-30 - Render's free tier has no
  persistent disk, so a restart silently wiped NYKAA's own
  `real_positions_swing` row. The next reconcile (`adopt="*"`) could no
  longer tell this was a swing position - the 2026-09-30
  `our_swing_trdsyms` exclusion check (`_reconcile_real_positions_core`)
  only works while that row still exists - and re-adopted NYKAA into the
  WRONG table (`real_positions`, intraday) with a NULL strategy (that
  adopt path's own INSERT never sets one), losing the swing engine's own
  governance in the process. Separately, even without the misadoption:
  the swing engine's OWN SL retry (`_maybe_sync_real_swing_stop_loss`)
  only ever ran once per IST day with no escalation (its own docstring:
  "explicitly deferred, not silently dropped") - a real gap against the
  standing "every open position, long or short, tracked or not, checked
  and auto-healed every 5 minutes" rule above, which intraday long/short
  already had and swing never received. Fixed same day:
  `_sync_real_positions_swing_external`/
  `hydrate_real_positions_swing_from_external` (mirroring the existing
  long/short pattern exactly, wired into every mutation site and startup
  hydration) plus a swing governance-backfill block in
  `_reconcile_real_positions_core` that retries a missing swing SL on
  EVERY reconcile call (now every 5 min), not just once a day. 12 new
  tests (`tests/test_real_positions_swing_external.py`), full suite
  green. Applies going forward: any future new real-position table
  (a new asset class, a new engine) must get BOTH the Upstash durability
  mirror AND a 5-minute governance-backfill entry from the moment it's
  built, never added later as a follow-up once an incident forces it -
  this is the second time that exact sequencing mistake has happened
  (`real_positions_short` 2026-09-30, `real_positions_swing` 2026-10-05).
- **Thumb rule (2026-10-05, explicit user instruction): every variant of any strategy is its OWN strategy, named by the canonical convention below. Never pool, average, alias or reuse a name across variants.** No single worldwide standard for strategy naming exists; this composes established conventions (PEP 8 snake_case, SemVer-style versioning, exchange/TradingView timeframe codes) into one grammar.
  - **Grammar:** `<family>__<variant>__<dir>__<tf>__<params>__v<N>`, fields separated by a double underscore, all lowercase `[a-z0-9_]` so it is safe in filenames, SQL, URLs and workflow matrices.
    - `family`: indicator or pattern (`fvg3c`, `adx_di`, `order_block_delta`, `volume_profile_poc`).
    - `variant`: the rule or state within the family (`valid_retest`, `breakaway`, `rejection`, `cross`).
    - `dir`: `long` or `short`. A mirror is always a separate strategy, never a flag on the original.
    - `tf`: `1m` `5m` `15m` `1h` `4h` `1d`.
    - `params`: every swept parameter as `key` + value, keys in alphabetical order, joined by a single underscore; a decimal point is written `d` (`atr1d5` = ATR multiple 1.5; `p14`; `bt60`).
    - `v<N>`: integer logic version. A parameter change makes a NEW tag at the same `v`. A change to the rule logic bumps `v`. An old version stays registered with its metrics.
  - **Combinations** (INDICATOR_COMBINATORICS_METHODOLOGY.md): `<trigger_tag>__x__<filter_tag>`, trigger first. Both role orderings are separate strategies.
  - **Immutability:** a name is never renamed, reused or deleted. A failed or retired variant stays in `strategy_registry.py` with its real metrics.
  - **Legacy tags** (`gap_and_go`, `minervini_vcp`, `orb-universal-score`, ...) are grandfathered unchanged. The grammar applies to all new work.
  - **Example:** `fvg3c__valid_retest__short__5m__bt60_cb3_bnd13__v1`.
- **Thumb rule (2026-10-05, explicit user instruction): `docs/ACTIONABLES_BACKLOG.md`
  is the single product backlog for every actionable, and nothing may live only
  in chat or a transfer pack.** The instant any actionable surfaces (a pending
  workflow result, an unmerged commit, a follow-up flagged in a workflow header,
  a parked item, a user request not finished this turn), append it as a row there
  with status/priority/notes. Every session starts by reading that table and picks
  its next work from it; items are closed/updated in the same commit as the work
  that moves them (status + date + evidence: run id, commit, URL). Never delete a
  row — close it. Before writing any transfer pack, reconcile it against the table
  so no item is dropped; the pack should reference the table, not replace it.
- **Override (2026-10-05, explicit user instruction, confirmed via AskUserQuestion
  after being shown the gap): `order_block_delta` and `volume_profile_poc` are
  wired into the live swing scan with REAL-money mirroring ON from the first
  deploy, before any replay has called the main.py ports.** User's words:
  "make viable strategies in the live wiring" -> "Port and real money now". What
  was disclosed and chosen anyway: (1) both existed only as research code embedded
  in `order-block-delta-research.yml` / `volume-profile-poc-liquidity-research.yml`;
  main.py's `order_block_entry_signal`/`volume_profile_poc_entry_signal` (+ exit
  fns) are ports whose constants/arithmetic were copied verbatim but have NOT been
  validated by a replay calling them - their registry PFnets (1.062 / 1.025) come
  from the research implementations; (2) both margins over PFNET_LIVE_FLOOR are
  thin and sit entirely on 30-day max-hold survivors (trail stops lose, PFnet
  ~0.3). Owed, tracked as backlog B-30: a full-universe replay that imports and
  calls the main.py functions, results compared to the registry numbers; if it
  lands < 1.0 the registry entries must be corrected (the gate then closes the
  strategies automatically). Checked LAST in `_run_swing_scan`'s entry chain so they
  never crowd out a higher-PFnet setup. Shares `is_real_swing_trading_enabled`;
  no new kill switch.
- **Thumb rule (2026-10-06, explicit user instruction): Render must redeploy only after CI passes, never on a bare push to main.** Render's Auto-Deploy is to be set to "After CI checks pass" (dashboard setting, owner-applied; Claude cannot change it). Until the user confirms it is set, treat every commit to main (Deploy Gate merges included) as an immediate live-bot restart (~8-11 min) and batch merges accordingly. Also (2026-10-06, supersedes the earlier one-at-a-time rule): keep GitHub Actions at exactly TWO in flight - one running and one queued. On every check, if nothing is queued, dispatch the next backlog item into the queue; never exceed one running + one queued, never batch more.
- **Thumb rule (2026-10-06, explicit user instruction: "Make it thumb rule to try bidirectional for each given strategy. It's must for u to backtest both direction"): every strategy, new or existing, is backtested in BOTH directions before it is called finished, and the opposite-direction result is registered with real metrics whether it passes or fails.** A long-only strategy gets a short mirror run, a short-only strategy gets a long mirror run, each as its own tag per the naming grammar (never a flag on the original), and a natively two-sided one (Box Theory, Parabolic SAR) is registered both pooled (`bidirectional`) and, when the run can print them, per side. A strategy with only one direction on record is an open backlog row, not a completed one. Dashboard side: `/strategy-leaderboard` shows every registered `bidirectional` strategy (viable or flagged "below floor"), because the viable-only view left that category blank; the PFnet real-money gate is unchanged. Extends the 2026-09-28 both-directions rule: that rule asked the question, this one makes the backtest mandatory.
- **Thumb rule (2026-10-06, explicit user instruction: "Everything on render must be attached to some memory so that no data is lost while restart of render"): no state may live only on Render's ephemeral disk.** Render's free tier has no persistent disk, so every restart wipes SQLite. Any table, cache or setting that this bot reads back later (positions, trades, signal state, kill switches, logs, cursors, settings) must be mirrored to Upstash Redis (or another durable store) and restored at startup BEFORE the git-journal reconciles. A new table or state added to `init_db()` or in-memory-only state is not finished until it is either in `_GENERIC_MIRROR_TABLES` (main.py) or has its own `_sync_*_external`/`hydrate_*_from_external` pair, with a test that a simulated wipe restores it. Safety rules of the generic mirror stand: never push a table before its restore reached Upstash once; the kill-switch tables always restore; only pure re-fetchable caches and recomputed-fresh snapshots (fo_chain_snapshot, fo_option_candles, real_protection_snapshot) may be skipped, and skipping must be stated. Complements the 2026-10-05 rule that new real-position tables need an Upstash mirror plus a 5-minute governance backfill.

- **Thumb rule (2026-10-06, explicit user instruction: "Doing better means being more profitable. Make it a thumb rule. Make more money out of this whole system. No exception"): the measure of "better" for every change, analysis, fix or research pass in this system is net real-money profitability, with no exception.** Every proposal states its expected effect on net P&L (after costs) and is judged on that, ahead of elegance, coverage or tidiness. Every audit of losses ends in concrete profit-improving actions, ranked by estimated INR impact, using real data (Kotak trade/order book, yfinance), never guessed. Where a change cannot be shown to improve or protect net profit, it is deprioritised or dropped. This does NOT relax any safety rule here: PFNET_LIVE_FLOOR, stop-loss protection, fresh-Kotak-state and the kill-switch limits still bound how profit is pursued. Profit is the objective; those rules are the constraints.
- **Thumb rule (2026-10-06, explicit user instruction, after a 140-job sweep starved a Deploy Gate): dispatch order on GitHub Actions is by urgency, never first-come.** Free-tier Actions runs about 20 jobs at once, so one big matrix occupies every runner and anything dispatched after it waits for it. Order: (1) Deploy Gate and anything on the real-money safety or profit path (merges, Kotak audits/reconcile, fixes) first; (2) small single-job runs next; (3) big research matrices (sweeps, full-universe replays) last, and only when no gate or safety run is queued or running. Before dispatching a matrix, check that nothing urgent is queued; if a gate is needed soon, hold the matrix until the gate has started. Matrix runs may be cancelled and re-dispatched to let a gate through. This works with the one-running-plus-one-queued rule above: that count is of runs, and matrix size counts too.
