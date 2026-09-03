# Price-action research — 2026-09-03

## What this run did

Picked a genuinely new price-action candidate (per the standing research ask):
**bullish engulfing candlestick pattern** — enter long on a bullish engulfing
candle, exit on the next bearish engulfing candle.

Sourced win-rate context via web search before building it:
- Standalone bullish engulfing: ~53-55% win rate in isolation.
- With a trend/context filter + volume confirmation: ~55-65% win rate.
- Sources: [liberatedstocktrader.com](https://www.liberatedstocktrader.com/bullish-engulfing-candle/),
  [tradingrush.net](https://tradingrush.net/bearish-engulfing-pattern-vs-bullish-engulfing-taking-100-trades-to-find-the-reliability/).

So it was built with two optional params rather than as a bare pattern:
`trend_sma` (0 = off; only take signals when `Close > SMA(trend_sma)`) and
`volume_confirm` (require above-average volume on the entry candle).

## What was implemented (commit `5302645`)

- `main.py`: new `bullish_engulfing` branch in `add_strategy_signal()`, plus
  full param wiring through `/backtest` and `/sweep` (`trend_sma`,
  `volume_confirm`), matching the existing `rsi_reversal` enter/exit-loop
  style. Syntax-checked (`py_compile`), not yet exercised against real data.
- `.github/workflows/entry-trigger-research.yml`: added a
  `run_price_action_research` input and two new steps — sweep
  `bullish_engulfing` on NIFTY/BANKNIFTY/SENSEX (no volume filter, since
  indices report 0 volume) and on AAPL/SPY/QQQ with `volume_confirm` on.
  Piggybacked a re-test of `vwap_reclaim`/`orb_volume` on those same
  real-volume stocks, since the 2026-09-02 research flagged both as
  untestable on zero-volume index data.
- Checked `state/open_positions.json` (synced today, empty) before pushing,
  per the standing rule to check for open positions before a push that
  redeploys Render.

## Blocker: could not actually run the backtest

Triggering the workflow requires GitHub Actions `workflow_dispatch` access.
From this session:
- No GitHub Actions MCP tool was available (checked via tool search).
- A direct REST API call (`POST .../actions/workflows/entry-trigger-research.yml/dispatches`)
  using this environment's own `GITHUB_TOKEN` was rejected by GitHub with
  `403 Resource not accessible by integration` — the token isn't scoped for
  Actions dispatch on this repo.
- Did not attempt further workarounds (e.g. extracting the git push
  credential for API use) — that would misuse a credential outside its
  intended scope.

**Result: no real backtest/sweep numbers exist yet for `bullish_engulfing`
(or the AAPL/SPY/QQQ re-test of `vwap_reclaim`/`orb_volume`).** Per this
project's ground rule (no strategy_log row without real evidence, reputation
is a reason to test not adopt), nothing was added to
`docs/strategy_log.xlsx` this run, and there is no adoption recommendation.

## Next steps (need one of)

1. Someone with Actions-dispatch access runs "Entry Trigger Research
   (backtest candidates)" manually from the GitHub UI with
   `run_price_action_research=true`, and the output gets fed back into a
   future research pass so it can be logged properly.
2. This session/environment gets a token or MCP tool actually scoped for
   `workflow_dispatch` on this repo, so future daily runs aren't blocked the
   same way.
