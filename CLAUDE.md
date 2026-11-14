# CLAUDE.md (compact rule index)

Live, real-money NSE/MCX bot (Kotak Neo, hosted on Render). Mistakes cost real money.
This file is the short index, loaded every session. The full text, with the dated user
instructions, incidents and rationale, is `docs/CLAUDE_RULES_FULL.md`. Before you change
an area, grep that file for it (`grep -n -A12 "<keyword>" docs/CLAUDE_RULES_FULL.md`).
Every rule there still applies; this index never relaxes one. Where the two disagree, the
full file wins.

## Token discipline (2026-11-14 user: "do something so that token usage gets lower")
- Never read `docs/ACTIONABLES_BACKLOG.md` (~1.5 MB), `docs/STRATEGY_LEARNINGS.md`
  (~0.4 MB), `main.py` or `docs/CLAUDE_RULES_FULL.md` whole. Grep by ID or keyword, then
  read only that line range.
- To pick work, read `docs/BACKLOG_PROGRESS.md` (generated, short), not the backlog itself.
- Test output: run pytest with `-q` to a log file and show only the `tail -3`. Focused
  tests while working; the full suite (~20 min) runs once, in the background, before a commit.
- Edit the backlog and learnings with append, sed or Edit on the exact rows. Never rewrite
  them whole.
- Subagents: at most 2 at once. Each gets a tight brief with file:line pointers and must
  return a patch path plus a report of 15 lines or less. Parallel agents each re-read the
  repo and hit the 5-hour usage limit (2026-11-14: two agents died on it).
- Replies follow the footer below. No step narration, no repeated context, no long pasted output.
- Near 150k context, save state to git and the backlog, then remind the user to /compact.

## Branch, commit, deploy
- Work only on `claude/confident-fermi-mlqbka`. No PRs. Before any reset or force-push,
  run `git log --oneline <branch> ^origin/main` and keep unmerged work (2026-09-14 incident).
- A transfer pack or summary is a claim. Verify against git before relying on it.
- Every commit needs: the full suite green, `ast.parse(main.py)`, and the attribution footer.
  Never edit code while the suite is running.
- Deploy only on the user's explicit "deploy X". Use `deploy-gate.yml` with ref `main` and
  source_ref set to the working branch. Real-exit fixes are shown to the user before deploy.
- A commit to main restarts Render (~8-11 min). Batch merges.
- GitHub Actions: one run in flight and one queued. Order by urgency: gate and safety first,
  small runs next, big matrices last.
- Whenever you wait on a platform, arm a `send_later` check-in at the expected finish time.
  Never sit idle: start the next backlog item meanwhile.
- All times shown to the user are IST, labelled. Convert UTC at the tool boundary.
- Subagents never push, dispatch, deploy, call Kotak or Render, or post to GitHub. The
  coordinator merges their work by patch, runs the suite, and pushes once.

## Real-money safety (never relax without an explicit user ask)
- No trade without an SL or SL-M, in any category.
- The 09:15 IST open: protect every open holding first. The exchange cancels all resting
  orders at 15:15 IST. That is not a bug, and you never re-place an SL after 15:15.
- Every open position, tracked or not, long or short, every category, is checked against
  Kotak every 5 min. Run this in-process (`_scheduler_tick`). The Actions cron is only a
  secondary check. An unprotected position is auto-healed, and the alarm stays loud when
  healing fails.
- Kotak is ground truth. Each governance pass goes in this order: (1) Kotak
  positions/holdings, (2) order book, (3) compare with the DB, (4) act through the owning
  engine. The DB is rewritten from Kotak, never the reverse. Net out T+1 holdings lags.
  Never act on cached order or position fields.
- Engine ownership: a position is entered, managed and exited only by its own category's
  engine.
- Every real order or cancel is logged with `reason=`, mirrored to Upstash, and journaled
  in git.
- No state lives only on Render's disk. A new table or state needs an Upstash mirror plus
  a restore-on-wipe test. A new real-position table also needs the 5-min governance backfill.
- Ask before adding any new kill switch. There are three: equity, F&O and swing. Share one
  of them.
- A rule that blocks or decides real entries is shown to the user before it ships. The
  sector cap is 25% of the whole account.
- A fired trigger is never dropped silently. It is rejected only under the viability, money
  or other-rule flags, with a logged `skipped_*`. The 1-share real minimum applies.
- Single-strike options always use a trailing SL.
- Every resolution is applied to every category it can touch: buy, short, swing,
  bidirectional, futures, options, options_multi, commodity, currency. Add a per-category
  coverage line.

## Strategy research and wiring
- The goal is net profit after the 0.8% cost model. "Better" means more profitable.
  Prefer faster capital turnover (return per day).
- Wiring: pooled PFnet > 1.00 (strict) is the only wiring condition. Wire every variant
  that can enter. The user's View 1 viability definition gates real entry. Order variants
  by return per day. Never store a viability flag; derive it from the raw metrics.
- Every backtest runs on the full NSE universe (`_load_nse_universe_from_file()`, not
  `NSE_FULL_UNIVERSE`). Call the real `main.py` functions. Test both directions, every
  candle size (1m/5m/15m/1h/4h, plus 1d where it fits) and the ATR/param sweep. For fixed
  stops, also test the trailing-stop set.
- Never tune blind off one result. Use structured sweeps instead.
- Name every variant with the grammar `<family>__<variant>__<dir>__<tf>__<params>__v<N>`.
  Tags are immutable and never merged with another name. Register every result, pass or
  fail. Regenerate `docs/STRATEGY_RESULTS_LOG.md` in the same commit.
- Methodology is in `docs/INDICATOR_COMBINATORICS_METHODOLOGY.md`. When the user shares a
  book or resource, try every strategy in it.
- Re-test every registry tag every 6 months (`scripts/retest_due.py`).
- `docs/STRATEGY_LEARNINGS.md`: add an entry for every strategy, result or exit discussion.
  End each entry with a "Profit-booking / exit takeaway" line.

## Backlog and process
- `docs/ACTIONABLES_BACKLOG.md` is the single backlog. Every actionable, new strategy or
  new indicator gets its own row. Close rows with evidence. Never delete a row, and never
  skip an item: park it with a reason instead.
- Decide open questions yourself, as the owner would. Ask only when the choice is
  irreversible, spends money outside the rules, or needs something only the user has.
- Keep working until the backlog is closed. Run each NSE no-entry day check and the daily
  review.
- Categories come from `strategy_registry.TradeCategory` and `CATEGORY_LABELS`. A new
  category ships with its session in `_CATEGORY_SESSIONS`.

## Reply footer (every reply, in this order)
1. Next actionable
2. Completed
3. Decisions
4. Input required
5. Backlog % (closed / total, from `python3 scripts/backlog_progress.py`)
6. Context (approx Xk / 200k)
