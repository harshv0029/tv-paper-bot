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
**Update 2026-09-03:** built - see the in-process scheduler below.

## Free-tier limitations (as of 2026-09-03) - what upgrading would fix

Every piece of this stack is currently the free/no-cost tier of its
service. That's a real constraint on a live-ish trading system, not just a
cost line - listed here plainly since the plan is to move to paid tiers
gradually. Ordered roughly by how much it actually bites today:

1. **Render free web service** (hosts `main.py`)
   - **No persistent disk** - every redeploy wipes the SQLite DB clean,
     including any open position. Mitigated (not eliminated) by the
     git-tracked journal + `reconcile_open_positions_from_journal()`, but a
     position opened in the narrow window between a redeploy and the next
     journal sync can still be lost. A paid plan with a persistent disk (or
     a real hosted DB - Postgres) removes this class of bug entirely.
   - **Sleeps on inactivity, cold-starts on the next request** - causes the
     slow-first-request/timeout pattern journal-sync.yml already works
     around (health-check-first + retry/backoff). An always-on paid
     instance removes the cold start, not just papers over it.
   - **Shared/limited CPU** - the in-process scheduler's per-tick workload
     grows with the watchlist (now 21 equity + 15 options symbols); a small
     free instance is more likely to have a tick's real wall-clock time
     exceed `SCHEDULER_INTERVAL_SECONDS` under load. Mitigated 2026-09-03
     by round-robin batching (see below) but a bigger instance raises the
     ceiling on how much can be checked per tick before that's needed.

2. **Yahoo Finance via `yfinance`** (all price/candle/options-chain data)
   - **Unofficial, reverse-engineered, no SLA** - no guaranteed uptime, no
     official rate limit to design against (just "don't send too much or
     you'll get throttled/blocked"), and the endpoint has changed shape
     before without notice. A paid market-data API (e.g. Polygon.io,
     Alpaca, IEX Cloud, a broker's own data feed) would give predictable
     rate limits and a real support contract instead of best-effort.
   - **Not true real-time** - free-tier quotes can lag by seconds to
     ~15 minutes depending on the exchange/symbol, which matters most for
     the options overlay's IV/strike selection (a stale bid/ask quotes an
     option at the wrong price).
   - **No historical options data** - only the current live chain snapshot
     is available, so options strategies can only be evidenced going
     forward from today, never backtested the way the equity strategies
     were (docs/strategy_log.xlsx). A paid options-data provider would
     unlock real backtesting there too.
   - **This is also why the watchlist is a curated 21 symbols, not
     literally every optionable US stock (~4,000+)** - polling that many
     against a free/unofficial endpoint every cycle would trip rate limits
     long before it added real value (docs/TRADING_CONSTRAINTS.md).

3. **NSE/BSE real tick, options, and futures data** - not available at any
   price through this stack today; needs a real broker connection (Kotak
   Neo, planned but not yet wired up). Until then, NSE symbols trade on
   yfinance's free daily/intraday candles only, and NSE options/futures
   stay off-limits entirely rather than faked.

4. **GitHub Actions minutes** - the redundant backstop workflows
   (`live-signals*.yml`) and the journal-sync/research dispatches all burn
   Actions minutes; a private repo on the free plan has a monthly cap. Not
   yet a problem, but heavy manual dispatching (like today's) burns through
   it faster than the scheduled crons alone would.

### Round-robin scheduling (2026-09-03) - working around the free tier, not just noting it

As the watchlist grew from 9 to 21 equity symbols (+ 15 options overlays)
in one session, scanning *everyone* every single 30s tick started to risk
both (a) the tick's real wall-clock time creeping past 30s on Render's free
CPU, and (b) hammering Yahoo's free endpoint harder than it likely
tolerates. Fix: `_scheduler_loop` now always checks every symbol with an
**open position** (time-critical - stop/target/eod-squareoff can't wait),
and round-robins a bounded batch (`SCHEDULER_ENTRY_SCAN_BATCH_SIZE = 7`)
through the remaining **flat** symbols each tick - a full rotation across
21 symbols takes ~3 ticks (~90s), which comfortably fits inside
`fetch_ohlc`'s own 180s cache TTL, so no real entry-signal opportunity is
lost by not re-scanning a flat symbol every single tick (its candle data
can't have changed meaningfully faster than the cache refreshes anyway).
`/scheduler-attempts`' `checked_at_utc` per symbol now honestly reflects
this - a flat symbol's timestamp only advances on its own round-robin turn,
not every tick.

## `/daily-summary`'s closed_trades undercounts on a day with redeploys

**Found:** 2026-09-03, building /trade-view's trade log.

`/daily-summary`'s `closed_trades` (and `realized_pnl`) are computed from
the live SQLite `trades` table - which, like every other table, gets wiped
clean on every Render redeploy (no persistent disk). Reconciliation on
startup restores any still-*open* position from the journal, but a trade
that already *closed* before the most recent redeploy is never
reconstructed into the fresh DB - it's just gone from `/daily-summary`'s
view, even though it genuinely happened today. On a day with several
redeploys (normal during active development - this session alone had over
a dozen), `/daily-summary`'s "today's P&L" badly undercounts the real day.

**Fix:** `docs/trade_outcomes_log.json` (git-tracked, appended to and
deduped by `journal-sync.yml` every sync, survives every redeploy) was
already the durable record for exactly this reason. Added `GET
/trade-history?days=1`, which reads that file directly instead of the DB,
filters to the IST calendar day, and returns the honest count/net P&L/win
rate. `/trade-view`'s trade log and its "Net P&L today" stat now use this
endpoint for closed trades - `/daily-summary` stays the source for what's
currently *open* (which the live DB tracks correctly via reconciliation)
but is no longer trusted for historical closed-trade totals.
