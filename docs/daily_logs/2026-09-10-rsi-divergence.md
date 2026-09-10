# Research pass — 2026-09-10

## Candidate: RSI divergence

Named as a candidate in the original research brief, distinct from the
simple threshold-crossing `rsi_reversal` already in the engine. Regular
bullish divergence: price makes a LOWER low over a lookback window while
RSI makes a HIGHER low over the same window (momentum improving even as
price falls further) — enter long on that signal, exit on the mirror
bearish divergence.

Sources:
- [forexbee.co](https://forexbee.co/rsi-divergence-indicator-guide/),
  [ezalgo.ai](https://www.ezalgo.ai/blog/rsi-divergence-trading-strategy):
  55-65% win rate when combined with confirmation (candlestick pattern,
  trendline break, or MA cross), dropping below 40% traded on the raw
  divergence signal alone. Noted as a caveat rather than baked in as
  another filter, to keep this candidate testable as the "raw" version
  first — a fair comparison point before deciding whether it needs a
  confirmation filter the way `bullish_engulfing` needed `trend_sma`.

## Implemented, NOT pushed (real positions open)

- `main.py`: new `rsi_divergence` branch in `add_strategy_signal()`
  (params: `rsi_period`, `lookback`), wired through `/backtest` and
  `/sweep` (as `divergence_lookback` in the query string, mapped to
  `lookback` internally — `rsi_period` reuses the existing param).
  - Verified locally against a synthetic series with a deliberately
    slower second decline to a lower low (shallower RSI drop): the
    divergence condition fired as expected.
  - Full test suite: **7 pre-existing failures** in
    `tests/test_review_bugfixes.py` (real stop-loss retry / partial-exit
    reconciliation tests) — confirmed via `git stash` that these fail
    identically on `main` before my change, so not something I
    introduced. Flagging since real money is live and a "Deploy gate"
    workflow exists that's presumably meant to catch this; not mine to
    fix (real-order-placement code, outside my remit) but worth the
    main session's attention.

**Committed locally (commit pending push) but deliberately NOT pushed
to `main` this cycle.** `state/open_positions.json` and
`state/real_positions.json` both show open positions right now —
3 real Kotak orders (JSWINFRA.NS, MIDCAPADD.NS, PAISALO.NS, with live
`sl_order_id`s) plus a paper HINDALCO.NS position. A push redeploys
Render; per the standing safety rule, I don't push while real capital
is in open trades. Will push next cycle once positions are confirmed
clear, or sooner if explicitly asked.

## Status

`strategy_log.xlsx` unchanged at 28 rows. Five candidates now sourced,
coded, and sweep-ready pending real dispatch: `bollinger_mean_reversion`,
`supertrend`, `pin_bar_reversal`, `inside_bar_breakout`, and now
`rsi_divergence` (workflow step for this one not yet added, held with
the code push).
