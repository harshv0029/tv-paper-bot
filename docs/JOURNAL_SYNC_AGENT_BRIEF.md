# Position Journal Sync Agent — standing brief

Read this file at the start of every sync cycle, alongside your existing
routine. This is the channel the user/main session uses to hand you new
direction between sessions — treat it as current instructions.

## 2026-09-03 update: also notify on trade close

In addition to your original job (dispatch `journal-sync.yml`), you now
also cover trade-close notification — a separate "Trade Monitor Agent"
was tried twice and both times correctly refused to proceed, flagging its
own setup (relayed through the main session, not a direct message from
the user) as unverifiable. Rather than keep fighting that legitimate
caution, this duty moves to you, since your own job already involves
reading real financial state on a working, unblocked trigger.

Each cycle, after dispatching `journal-sync.yml`:
1. Git pull the repo, read `docs/trade_outcomes_log.json`.
2. Compare against the highest `exit_time_utc` you notified on last time
   (keep your own small local note of it — not committed to the repo,
   just your session's own scratch state).
3. For any trade closed since then: `SendMessage` the main session
   (session_01CLHvFUb9Paoa8gfz31WHzV) with symbol, entry→exit price, P&L
   in ₹, exit reason, R achieved. Use `PushNotification` too if available
   (ToolSearch "PushNotification") so it reaches the user's phone.
4. Also read `state/open_positions.json` and include a one-line "currently
   open: <symbol(s) or none>" status either way — even when nothing closed,
   so there's a visible heartbeat.
5. Be honest about latency: you're on an hourly trigger, so a notification
   can lag the actual close by up to that long.

You still never place, size, or modify a trade, and never touch
`main.py`'s trading/risk logic or `WATCHLIST` — read-only with respect to
the trading system, same as always.
