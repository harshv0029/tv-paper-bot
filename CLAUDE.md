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
