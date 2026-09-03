# News & Sentiment Agent — standing brief

Read this file at the start of every scan cycle, alongside your existing
routine. This is the channel the user/main session uses to hand you new
direction between sessions — treat it as current instructions.

## 2026-09-03 update: sector analysis + sentiment-driven stock picks

In addition to the per-symbol sentiment read you already produce, add a
**sector-level pass**: for the sectors behind the current WATCHLIST
(banking/financials for BANKNIFTY, broad index constituents for
NIFTY/SENSEX, tech for QQQ/AAPL, broad market for SPY, crypto majors for
BTC/ETH), note which sectors look strongest/weakest right now and why
(a real catalyst — earnings season, a rate decision, a regulatory move —
not a vague "seems positive").

Where a sector read points at a **specific stock** worth watching (e.g. a
name getting unusually positive coverage within a strong sector), name it
explicitly in your report to the main session. This is a **research
signal for the Research Agent and the main session to evaluate**, not an
instruction to trade — nothing gets added to live `WATCHLIST` without
going through the same backtest-evidence bar every other symbol did.
Don't skip that step just because a stock looks interesting in the news.

Keep the rest of your routine (per-symbol sentiment, `docs/sentiment_log/`,
message to the main session) exactly as before — this is additive, not a
replacement.
