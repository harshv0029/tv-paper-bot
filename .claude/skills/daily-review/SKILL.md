---
name: daily-review
description: Daily post-market auto-heal and process-improvement review of the live trading bot. Covers every incident since the last review (cursor in docs/daily_review_state.json; 50 h if missing, capped at 7 days), says what went right/wrong, fixes what it safely can on the working branch, and logs everything. Use when the scheduled 15:40 IST review fires or the user says "run the daily review".
---

# daily-review (B-1548)

Read CLAUDE.md first; every rule there applies. This is a real-money bot.

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

## 2. Analyse
For each finding: what happened (IST, symbol, category), Kotak vs app, root cause from code, INR impact.
Sections: Went right / Went wrong / Incidents / Improvements (ranked by estimated net-profit impact).
Check every category (buy, short, swing, swing-short, news, futures, options, MCX) per the per-category rule.

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
