# Known Issues

## GitHub Actions `schedule:` cron is not reliable at 5-minute granularity

**Found:** 2026-09-02, NSE session.

`live-signals.yml` was configured to poll `/auto-signal` every 5 minutes,
9:15 AM-3:30 PM IST (`cron: "*/5 3-10 * * 1-5"`). Expected ~75 firings over
the session. **Only 1 actually fired** (13:33 IST). GitHub's own docs say
scheduled workflow timing/frequency is not guaranteed under load - in
practice, short-interval crons on a low-traffic repo appear to get silently
dropped, not just delayed.

**Impact:** the engine was effectively only checking the market once during
the session it should have polled continuously. Any breakout that occurred
and reversed between checks would have been missed entirely.

**Fix direction (not yet built):** move the actual polling/signal-check loop
*inside* the Render server itself (an in-process scheduler - e.g. `asyncio`
background task or APScheduler - triggered on a real timer, not dependent on
an external cron firing reliably). GitHub Actions' schedule can still serve
as a periodic "keep-alive" ping (Render free tier sleeps when idle) since
that doesn't need precise timing, only the actual signal-check cadence does.
