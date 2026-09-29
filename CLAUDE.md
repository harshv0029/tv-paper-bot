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
