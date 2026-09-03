# Research Agent — standing brief

Read this file at the start of every research cycle, alongside
`docs/strategy_log.xlsx` and `docs/TRADING_CONSTRAINTS.md`. This is the
channel the user/main session uses to hand you new direction between
sessions — treat it as current instructions, not a one-time note.

## Structural constraint: you cannot dispatch GitHub Actions yourself

Confirmed 2026-09-03: your session has no GitHub Actions MCP tool, and
direct HTTP to the live server (curl, WebFetch) is blocked by this
environment's network egress policy (`EGRESS_BLOCKED`) — this is not a
bug to work around, it's how this environment is configured. **You can
still write and push backtest-engine code** (new strategies in
`add_strategy_signal()`, new workflow steps in
`entry-trigger-research.yml`) — but when you need it actually *run*
against real data, log the blocker plainly (as you already did for
`bullish_engulfing`) and stop there. The main session has the GitHub
Actions access you don't and will dispatch it and log the real results —
this is the expected division of labor, not something to keep retrying
workarounds for.

## 2026-09-03 update: strategy is asset-class-agnostic — include gold + forex

The user's framing: "strategy is strategy irrespective of market... gold
trade or currency trade which are live 24x7." Since every strategy here
only needs candlestick data, extend your test universe beyond the current
8 WATCHLIST symbols to include: **gold futures (`GC=F`)** and **forex
(`EURUSD=X`, `USDINR=X`)** — all fetchable via `yfinance` the same way as
everything else, no new data source needed. These trade far closer to
24x7 than equities (forex ~24x5, gold futures ~23x5) - note in the
strategy log if that changes anything about which strategy/params work
(e.g. no natural "opening range" on a market with no real open). The main
session kicked off an initial sweep on these on 2026-09-03
(`entry-trigger-research.yml`'s new `run_new_asset_research` input) - read
its results in `docs/strategy_log.xlsx` before re-testing the same ground.
Same rules apply as any other symbol: logging bar >50% combo
profitability, live-adoption bar ~90-100%, no live `WATCHLIST` change
without that evidence.

## 2026-09-03 update: log liberally, adopt strictly, source widely

**Two different bars — don't conflate them.** The user has explicitly
authorized the main session to move a strategy to live `WATCHLIST` params
without asking again each time, *when it's genuinely backtested* — but
that only means candidates meeting the SAME robustness bar the current
live params already meet (NIFTY/BANKNIFTY/SENSEX ORB, AAPL
bullish_engulfing: all ~90-100% of swept parameter combos profitable, not
a lone spike). That is a materially higher bar than what gets **logged**.

**Logging bar: log anything with more than 50% swept-combo profitability**
(`pct_profitable_combos > 0.5` in the strategy log's own terms) — i.e. more
likely than not to have real edge, even if not yet adoption-grade. Keep
logging losers and mixed results too, as already practiced — the log's
value is the honest full picture, not a highlight reel.

**Source widely — there are thousands of documented strategies, not just
the two or three checked so far.** Keep pulling from trading-education
sites, backtest write-ups, competition/prop-trading strategy discussions,
not just re-testing the same couple of sources. Breadth matters here as
much as depth — the point is to build up real coverage over many daily
cycles, not to over-polish one candidate.

## 2026-09-03 update: scope across markets, use real historical outcomes, options/futures where legitimately available

**Test across every WATCHLIST market, not just NSE.** The user's own framing:
"we just need candlestick chart for our strategy — the asset class is not
needed here." The ORB+trend-filter strategy (and any new candidate you
test) is candlestick-data-based, not NSE-specific — a candidate should be
backtested across NIFTY/BANKNIFTY/SENSEX **and** BTC-USD/ETH-USD **and**
SPY/QQQ/AAPL where the data supports it, not just the Indian indices. If a
candidate only works on one market, say so explicitly in the strategy log
rather than presenting it as generally adopted.

**Maintain real historical probabilities — don't estimate, count.**
`docs/trade_outcomes_log.json` is a durable, append-only record of every
closed auto-signal trade (symbol, entry/exit price, P&L, exit reason,
R achieved) — kept current by `.github/workflows/journal-sync.yml` on every
sync, surviving Render redeploys the same way the position journal does.
As it grows, use it for real questions like "of trades that got most of
the way to target, what fraction actually hit it vs. reversed?" instead of
asserting a confidence number. Right now it's still thin (paper trading
only started recently) — note in the strategy log when a claim needs a
larger sample before it's trustworthy, rather than overfitting to a
handful of trades.

**Options and futures signals — legitimately available now for SPY/QQQ/AAPL, NOT for NSE.**
`yfinance` provides real, free options-chain data (`Ticker.options` for
expiries, `Ticker.option_chain(date)` for calls/puts — open interest,
volume, implied vol) and correlated futures series (e.g. `ES=F` for
S&P 500 futures) for US-listed names, no broker required. You may research
and backtest whether option-chain-derived signals (put/call ratio, OI
skew, IV) or futures basis add real edge on top of price action for
SPY/QQQ/AAPL specifically — with the same rigor as everything else here:
real data, a parameter sweep, robustness across combos, logged either way.

**NSE/BSE futures, options, and tick data stay off-limits — do not build
around a workaround.** This was explicitly discussed and agreed earlier in
this project: real NSE/BSE derivatives and tick-by-tick data require a
proper broker feed (Kotak Neo), not scraped or synthetic substitutes.
`yfinance` does not provide legitimate NSE F&O data, so don't reach for
scraping or unofficial sources to fill that gap — this stays queued behind
the Kotak Neo integration. Nothing about today's update changes that.
