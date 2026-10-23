# Regression guards: incidents that must not repeat

Each row: what broke, what now stops it, and the test or check that fails if it comes back.
Add a row the same day as any new incident fix. Read this before touching Upstash sync, memory, or the order log.

## Thumb rule (2026-10-23, explicit user instruction: "Do something to not repeat such events again. Make this thumb rule")

Kept here because CLAUDE.md is not edited from sessions; it has the same standing as a CLAUDE.md thumb rule.

1. **Nothing safety-critical rides the scan tick or a GitHub cron.** The stop-loss backcheck, the order-log push and any future must-run job get their own wall-clock thread (single-flight, never raises). A scan tick can take minutes; a cron can skip hours.
2. **A record is not on record until it is durable.** Every real-order reason reaches git within seconds of being written, not on a timer. A new real-money table ships with its durable path and a test that a restart cannot lose it.
3. **Every restart must explain itself.** The watchdog thread logs loop lag, memory and each thread's running code before Render kills the bot. /health shows `loop_lag_s`, `watchdog_alarms`, `order_log_git_push_age_s`.
4. **Every incident gets a row below the same day:** what broke, the guard, and the test that fails if it returns. Fixing without a guard test is not done.
5. **Daily check (coordinator, during market hours):** run the checklist at the end of this file. Anything red becomes a P0 backlog row.

| Incident (IST) | Guard now in place | Fails if it regresses |
|---|---|---|
| 22-Oct: Upstash free DB suspended at the 10 GB monthly bandwidth cap (whole tables + 2-4 MB scan blob re-pushed every 30-60 s) (B-1341) | zlib scan blobs, skip-if-unchanged, 300 s throttle on non-critical writers, per-family byte meter | `tests/test_upstash_bandwidth_budget.py` |
| Same: no warning before the cap (B-1342) | Daily budget 330 MB / 16k cmds; conserve at 60%, pause non-critical at 90%; `upstash-usage-check.yml` 16:10 and 22:55 IST emails on non-ok; dashboard banner | `tests/test_upstash_daily_guard.py`; the workflow itself |
| Render memory near the 2 GB limit (B-1288, B-1351) | `/health` rss_pct + memory_level; trim caches at 75%; alarm log above RSS_ALARM_PCT; malloc_trim each memory tick | `tests/test_rss_headroom.py`, `tests/test_memory_pressure.py` |
| 22-23 Oct: CPU starvation froze the event loop, Render answered 502 (B-1340, B-1348) | Kotak reconcile runs in a worker thread | B-1348 tests in the suite |
| 23-Oct: order-log git push stalled after 09:27 IST because it rode the scheduler tick behind an awaited reconcile (B-1349) | Own daemon thread, every 60 s on a wall clock; `/health` shows `order_log_git_push_age_s` | `tests/test_git_tier_side_branch_push.py` |
| 23-Oct: a Kotak cancel/sell with no app reason row (NATIONALUM, B-1350) | Reason row written BEFORE every Kotak cancel/sell in partial-exit and SL-sync | `tests/test_reason_logged_before_kotak_call.py`, `tests/test_real_exit_reason_logged.py` |
| 23-Oct: Deploy Gate merge conflict in docs/tables/*.json | Never dispatch `table-git-sync.yml` on the working branch; Render pushes the order log to `state-sync` itself | Process rule (this file) |
| 23-Oct: in-process unprotected backcheck did not complete for 45+ min (status null) because it ran every 10 scan ticks (B-1354) | Own daemon thread every 300 s, single-flight lock | `tests/test_inprocess_unprotected_backcheck_cadence.py` |
| 23-Oct: NATIONALUM exit reason lost: written 8 s before a restart, git push was every 60 s (B-1350, B-1355) | Every order event wakes the git push thread immediately | `tests/test_git_tier_side_branch_push.py` |
| 23-Oct: Render killed the bot twice (09:22, 13:19 IST) after minutes of silence, with no error in the log (B-1346, B-1356) | Watchdog thread: alarms at >= 15 s loop lag or RSS warn level, prints every thread's app stack, trims the data cache | `tests/test_watchdog.py` |
| 23-Oct: Upstash suspended / Render down but trade-view4 showed no error (B-1357) | Upstash PING probe in /health; view4 System strip polls /health and turns red with the cause; no silent catch on the stop check | `tests/test_upstash_probe_and_view4_health.py` |
| 21-Oct: GitHub cron is unreliable (table-git-sync fired 0-2 times a day) | Every must-run safety job is in-process first; crons are a secondary audit layer only | CLAUDE.md 2026-09-30 in-process-first rule |

## Daily check (coordinator)
- `/health`: memory_level ok, rss_pct < 75, order_log_git_push_age_s < 300 in market hours.
- `/real-protection-status`: stale false in market hours.
- `/health`: upstash_ok true, loop_lag_s < 15, watchdog_alarms not rising; any `[watchdog] ALARM` line in the Render log names the code to fix.
- `/upstash-usage`: status ok. The 16:10 IST workflow must be green.
