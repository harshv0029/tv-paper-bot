# Research pass — 2026-09-15

## Note on the gap: 2026-09-11 through 2026-09-14 had no research pass

The daily trigger fired all four days but this session was idle until
now — all 5 notifications (09-11 through 09-15) arrived queued together
on wake-up. As with the earlier 09-06/09-07 gap, this pass covers it
with one solid new candidate rather than backfilling placeholder days.

## First: pushed last cycle's held commit

`rsi_divergence` (2026-09-10) was committed locally but deliberately not
pushed at the time — real Kotak orders were open and a push redeploys
Render. Checked `state/real_positions.json` on wake-up: `open_real_positions: []`
(clear). Pushed that commit first, before starting today's new work.

## Also noticed: heightened real-money discipline (CLAUDE.md)

The repo now carries a `CLAUDE.md` documenting a 2026-09-14 incident
(a validated real-money exit-logic fix was silently discarded via a
careless branch reset) and standing rules — no merge to `main` without
explicit user go-ahead for entry/exit/sizing changes, full validation
replay required, etc. This doesn't change my mandate (backtest-engine
additions only, never touching `WATCHLIST` or live entry/exit/sizing
logic), but worth recording that I read it and it reinforces the
existing caution around pushes.

**Also worth flagging:** the full test suite now has **12 pre-existing
failures** (up from 7 on 09-10), all in `tests/test_review_bugfixes.py`
(real stop-loss retry / partial-exit reconciliation) and
`tests/test_trend_weakened_range_exclusion.py` (regime-exit logic).
Confirmed unrelated to my changes (same failures before/after). Given
the 09-14 incident was about exactly this class of bug (exit-logic
correctness), this seemed worth surfacing explicitly rather than only
noting in passing.

## Candidate: Stochastic oscillator (oversold/overbought + crossover)

Third classic oscillator alongside `rsi_reversal`/`rsi_divergence`,
very widely used by Indian retail traders. %K/%D crossover gated to the
oversold zone for entry, overbought zone for exit — not a bare
crossover.

Sources:
- [quantifiedstrategies.com](https://www.quantifiedstrategies.com/stochastic-indicator-strategy/):
  a naive %K/%D crossover anywhere tested worse than gating it to the
  oversold/overbought zones — hence the gating rather than a bare
  crossover.
- One NSE-specific study (Nifty 50) found CCI outperformed both
  Stochastic and RSI. Noted as a follow-up candidate for a future
  cycle rather than a reason to skip Stochastic — it still deserves
  its own real evidence given how commonly it's used.

## Implemented (commit `e4414a8`)

- `main.py`: new `stochastic_oversold_reversal` branch in
  `add_strategy_signal()` (params: `k_period`, `d_period`, `oversold`,
  `overbought` — the latter two reuse existing params from
  `rsi_reversal`), wired through `/backtest` and `/sweep`.
  - Verified locally against a synthetic decline → oversold-bounce →
    overbought-reversal series: entry and exit fired exactly where
    expected.
- `.github/workflows/entry-trigger-research.yml`: two new steps —
  `run_rsi_divergence_research` (covering last cycle's candidate, which
  hadn't gotten a workflow step yet) and `run_stochastic_research` —
  both sweeping on the 3 NSE indices + 15 NSE large-caps.
- Checked `state/real_positions.json` (empty) before pushing; one paper
  position (GENCON.NS, `orb-universal-score` strategy) was open at
  research-pass time — judged low financial risk to redeploy through
  since no real capital is involved.

## Status

`strategy_log.xlsx` unchanged at 28 rows since 2026-09-03. Six
candidates now sourced, coded, and sweep-ready pending real dispatch:
`bollinger_mean_reversion`, `supertrend`, `pin_bar_reversal`,
`inside_bar_breakout`, `rsi_divergence`, `stochastic_oversold_reversal`.
Separately, the live system has clearly moved toward a more
sophisticated `universal_score` / regime-router architecture (per
`CLAUDE.md` and the open GENCON.NS position's strategy tag) — my simple
single-indicator candidates may matter less to production than they did
in early September, but sourcing/testing them is still the explicit
standing instruction, so continuing as briefed.
