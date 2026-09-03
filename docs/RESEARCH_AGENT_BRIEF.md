# Research Agent — standing brief

Read this file at the start of every research cycle, alongside
`docs/strategy_log.xlsx` and `docs/TRADING_CONSTRAINTS.md`. This is the
channel the user/main session uses to hand you new direction between
sessions — treat it as current instructions, not a one-time note.

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
