---
name: daily-review
description: Daily post-market auto-heal and process-improvement review of the live trading bot. Covers every incident since the last review (cursor in docs/daily_review_state.json; 50 h if missing, capped at 7 days), says what went right/wrong, fixes what it safely can on the working branch, and logs everything. Use when the scheduled 15:40 IST review fires or the user says "run the daily review".
---

# daily-review (B-1548)

Read CLAUDE.md first; every rule there applies. This is a real-money bot.

**Primary objective (user 2026-11-11): find what could be done better to make MORE PROFIT.** Every run must answer
"how could this window have made more money, net of the 0.8% cost?" with real numbers, not only list what broke.

## 0. Setup
- `git fetch origin claude/confident-fermi-mlqbka && git checkout claude/confident-fermi-mlqbka && git pull`.
- Window: `docs/daily_review_state.json` -> `last_check_utc`. Missing: now - 50 h. Older than 7 days: cap at 7 days and say so.
  Round up to whole days for `days=` query params. All times shown in IST.

## 1. Gather (Kotak first, then the app)
Live endpoints go through `diag-curl.yml` (input `path`; `with_kotak_token: "true"` for token routes). Keep Actions at
one running + one queued.
- Kotak ground truth: `/real-order-log?days=N` (token), `kotak-pnl-audit.yml` if P&L is in question.
- Protection: `/real-protection-status` (any unprotected position = top priority, fix first).
- Entries: `/entry-funnel` (reject_flags per category), `no_entry_day` rows in the order log.
- News: `/news-monitor?days=N` (pass_state errors/stuck, open news trades).
- Health: `/health`, `/scheduler-status` (last_error, tick timing, watchdog alarms, restarts/uptime).
- GitHub Actions runs since the cursor that failed or were cancelled (deploy-gate, kotak-reconcile, journal-sync, research).
- Git journals: `docs/real_order_log.json`, `docs/real_reconcile_log.json`.
- Open P0/P1 rows in `docs/ACTIONABLES_BACKLOG.md` touched since the cursor.
- Market context (B-1669, NSE official MCP, research only): `mcp__NSE_Bhavcopy__get_market_breadth` / `get_market_mood` for each session in the window; `get_corporate_actions` for any held or traded symbol with a >20% one-day move.

## 2. Analyse
For each finding: what happened (IST, symbol, category), Kotak vs app, root cause from code, INR impact.
Sections: Went right / Went wrong / Incidents / More profit next time / Improvements (ranked by estimated net-profit impact).
Check every category (buy, short, swing, swing-short, news, futures, options, MCX) per the per-category rule.

## 2b. Profit review (required every run)
From Kotak's trade book for the window, per trade and per category/strategy tag:
- Realised and open P&L net of costs; win %, avg win vs avg loss, hold time, return per day.
- Missed profit: fired triggers rejected (by flag), stale/late entries, entries blocked by money or gates that would
  have won (check the later price); exits that left money on the table (peak vs exit, MFE/MAE), stops hit then
  recovered, trails too loose or too tight, positions held to a loss after being in profit.
- Cost drag: brokerage/charges vs gross P&L; trades too small for their costs.
- Idle capital: free Kotak cash unused while viable signals fired.
Output a ranked list "More profit next time" with an estimated INR gain each. Each item is either built (if it
is a bug or within existing rules), or queued as research/backlog with a validation plan (full-universe replay,
real main.py functions, no tuning off one day's result). Rule changes that decide real-money entries, sizing or
exits go to the user as "Input required", never shipped alone. Add a learnings entry with the profit takeaway.

## 2c. News learning (View 5, required every run; user 2026-11-27 "investigate and do daily learning as a part of 3:40pm review")
From `/news-monitor?days=N` and the news rows in the Kotak trade book for the window:
- Every headline the news module acted on (entry, exit, block, skip): IST time, symbol, tag/sentiment, action, and
  the price move 15 min, 60 min and at close after the headline (right or wrong direction, how big).
- Accuracy and value: hit rate by headline type/source, net INR of news-driven trades and of news-blocked or
  news-forced exits (what the position did afterwards), headlines missed (a big mover with news the module skipped).
- pass_state health: errors, stuck passes, stale feeds, latency from publish time to action.
- Write a learnings entry "<date> View 5 news daily learning" (with a "Profit-booking / exit takeaway" line) even on
  a quiet day (state "no news trades, N headlines seen"). Any rule change it suggests goes to "Input required" with
  the evidence; never tune off one day.

## 3. Heal (inside the rules only)
- Allowed: bug fixes with tests on `claude/confident-fermi-mlqbka`, full suite green + `ast.parse`, commit, push;
  dispatching diagnostic / reconcile / audit workflows; backlog + learnings entries.
- NOT allowed without the user's explicit word: Deploy Gate / merge to main, any new or changed rule that decides
  real-money entries, sizing or exits, any new kill switch, parameter tuning off one day's result, PRs.
  Build such items, push them, and list them under "Input required".
- An unprotected real position is the one exception to waiting: follow the existing auto-heal path (reconcile) now.

## 4. Record
- `docs/daily_reviews/<YYYY-MM-DD>.md` (IST date): window, findings, fixes (commits), owed items.
- One backlog row per finding/fix (never fold), learnings entry where a lesson exists, regenerate backlog progress.
- Update `docs/daily_review_state.json` `last_check_utc` to this run's start ONLY after the report is committed.
- Commit + push. Final message: short summary + the 6-item footer from CLAUDE.md.
