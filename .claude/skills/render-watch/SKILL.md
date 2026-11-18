---
name: render-watch
description: Intraday Render watchdog (B-1627). Hourly market-hours check of the live bot (health, memory, restarts, protection, scheduler) with in-rule mitigation. Use when the scheduled intraday watchdog fires or the user says "check render".
---

# render-watch (B-1627)

Read CLAUDE.md first; every rule applies. Real-money bot. Keep each run short (token discipline): one diag-curl per
endpoint, parse only the needed keys, no long output. Skip entirely if today is not an NSE trading day.

## 1. Check (diag-curl.yml, ref main, input `path`; scratchpad diagwait.sh saves the log)
1. `/real-protection-status`: any unprotected real position is the top priority.
2. `/health`: boot_ist, uptime_min, rss_pct, memory_level, stage_rss (largest deltas), watchdog_alarms_today,
   mirror_auth_alarm, upstash_ok, loop_lag_s.
3. `/restart-history`: restarts today, in market hours, cause_guess, prev_peak_rss_mb (sort events by boot_ts).
4. `/scheduler-status`: last_error, tick age (tick older than 10 min = stalled).
5. Last 2 h of GitHub Actions: failed deploy-gate, kotak-reconcile, journal-sync runs.

## 2. Classify
- RED: unprotected position; scheduler stalled; restart in the last hour in market hours; rss_pct >= 85;
  mirror/Upstash auth alarm; reconcile failing.
- AMBER: rss_pct 70-85 and rising; repeated watchdog alarms; loop_lag_s > 30; a failed Actions run.
- GREEN: none of the above. Then reply in 1-2 lines plus the footer and stop.

## 3. Mitigate (inside the rules only)
- Unprotected position: dispatch the existing reconcile / auto-heal path now (allowed without waiting).
- Restart or memory: find the stage with the big stage_rss delta, root-cause it in code, build the fix with a test,
  run the full suite, ast.parse, commit and push to claude/confident-fermi-mlqbka.
- Any other bug: same as above. Diagnostic and reconcile workflows may be dispatched (1 running + 1 queued).
- NOT allowed without the user's explicit word: Deploy Gate / merge to main, any rule that decides real entries,
  sizing or exits, a new kill switch, tuning off one result. Build, push, and list under "Input required" with
  the evidence and the expected impact, so the user can say "deploy X".

## 4. Record
- One backlog row per new finding (never fold); learnings entry when there is a lesson.
- Re-check later by arming send_later when a fix or heal is in flight.
- Reply: status (GREEN/AMBER/RED), what was found, what was done, IST times, then the 6-item footer.
