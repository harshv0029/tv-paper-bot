# Backtesting Methodology — standing rules

Read this before designing any new research/backtest workflow in
`.github/workflows/*-research.yml`. Distilled from the WCTC ideas 1-7
research session (2026-09-22) — each rule below traces to an explicit
user instruction from that session, quoted where useful so intent isn't
lost in paraphrase.

## Timeframe / candle-aggregation rules

1. **Derive coarser candles by resampling data you already fetched —
   don't fight a data source's per-interval lookback limit with a second
   fetch that hits the same ceiling.** yfinance caps 5m *and* 15m
   intraday history at ~60 days regardless of which of the two you ask
   for, so a second native fetch at 15m buys no extra history over
   resampling the 5m data you already have. Fetch the finest available
   granularity once, then resample (pandas: `Open=first, High=max,
   Low=min, Close=last, Volume=sum`) into coarser bars.
   User's own words: *"still you can generate as many cases as you want
   out of those 60 days data only."*

2. **Where a timeframe has a genuinely longer native lookback, use it —
   don't shrink it to match the finest granularity's window.** Hourly
   data goes back further than 5m/15m on Yahoo (~730 days); daily data
   goes back years. Fetch each timeframe's own real longest-available
   history natively (e.g. `fetch_ohlc(sym, "730d", "60m")` for hourly,
   `fetch_ohlc(sym, "5y", "1d")` for daily) rather than reusing the
   60-day window everywhere. A timeframe derived by resampling (e.g. 4h
   from a 730-day hourly fetch) inherits its source fetch's real window,
   not the 5m fetch's.
   User's own words: *"then use different time frames."*

3. **Signal/indicator parameters are bar-count-based, not wall-clock-
   based — treat candles as candles.** EMA(9)/EMA(21), RSI(14), a 20-bar
   structure lookback, an ATR(14) stop multiple, etc. apply UNCHANGED to
   any candle series regardless of what timeframe each bar represents —
   never rescale a lookback period by wall-clock time when moving to a
   coarser or finer timeframe. This is what makes one entry-scoring
   implementation reusable across 5m through daily candles without a
   rewrite per timeframe.
   User's own words: *"treat candles as candles not according to
   timeframes."*

## Judging non-intraday results

4. **A backtest at 4h/daily granularity implies multi-day holds — that's
   a description of what kind of strategy it is, not a reason to
   discount its results.** This repo's live `main.py` is intraday-only
   (EOD-squareoff by design), but a research backtest is never obligated
   to respect that constraint. Judge every timeframe purely on its own
   PF/win-rate/cost-drag numbers. If a coarser timeframe shows real,
   cost-net edge, that is valid evidence for a SEPARATE swing/positional
   strategy — to be designed, approved, and built as its own explicit
   mode (never silently folded into the intraday engine) — not evidence
   to discard because "it doesn't fit how the bot currently runs."
   User's own words: *"if this is only intraday then its wrong
   methodology being applied by you... if this is giving me results over
   4hr candle or daily candle then it must be picked up for non-intraday
   strategies. and can be implemented accordingly for profit making."*

## Standing scope note

None of the above changes the real-money discipline in the repo root
`CLAUDE.md` — these are methodology rules for how a backtest is
*designed*, not an authorization to skip validation, tune blind, or
merge anything live-eligible without the user's explicit go-ahead. A
non-intraday strategy that clears backtest evidence still needs its own
implement → unit test → full replay → honest report cycle, and still
needs explicit sign-off before touching `main.py`.
