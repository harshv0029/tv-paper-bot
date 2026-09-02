# Entry-trigger research — 2026-09-02

Backtested against 60 days of real 5-minute NIFTY/BANKNIFTY/SENSEX data
(4,425 bars each), via `entry-trigger-research.yml`.

## Result summary

| Strategy | NIFTY P&L | BANKNIFTY P&L | SENSEX P&L | Verdict |
|---|---|---|---|---|
| `orb_breakout` (default 15/9/21) | +195.90 | +1686.55 | +456.58 | Positive baseline |
| `orb_breakout` (best swept params, per symbol) | **+593.60** | **+3087.90** | **+1823.56** | **Adopted — see below** |
| `macd_cross` (12/26/9) | -164.35 | -1120.00 | -382.51 | Rejected — negative on all 3, win rate 28-36% |
| `vwap_reclaim` | 0 | 0 | 0 | **Untestable** — Yahoo reports 0 volume for index tickers, so VWAP is undefined (division by zero volume) |
| `orb_volume` | 0 (all combos) | 0 (all combos) | 0 (all combos) | **Untestable** — same zero-volume issue |

## Robustness (not just a lucky top result)

`orb_breakout` sweep across 24 combos per symbol:
- NIFTY: 95.8% of combos profitable, median P&L +253.88
- BANKNIFTY: 100% of combos profitable, median P&L +1889.95
- SENSEX: 95.8% of combos profitable, median P&L +479.81

Almost every parameter combination made money, not just the top one — unlike
the earlier SMA-crossover-on-1-min test that was flagged "not robust." This
is real evidence for the ORB+trend-filter *shape* of strategy, not just the
specific numbers.

## Adopted live parameters (per symbol, not one-size-fits-all)

| Symbol | orb_minutes | sma_fast | sma_slow | Backtested P&L (60d) | Win rate |
|---|---|---|---|---|---|
| NIFTY (^NSEI) | 30 | 5 | 50 | +593.60 | 56.2% (32 trades) |
| BANKNIFTY (^NSEBANK) | 5 | 9 | 50 | +3087.90 | 51.6% (31 trades) |
| SENSEX (^BSESN) | 30 | 20 | 50 | +1823.56 | 60.7% (28 trades) |

Notable: BANKNIFTY wants a much *shorter* opening range (5 min) than NIFTY/
SENSEX (30 min) — consistent with BANKNIFTY's higher intraday volatility
establishing a meaningful range faster. All three want a slower trend filter
(SMA 50) than the original default (SMA 21) — a stronger filter cuts
whipsaw entries.

## Caveats

- **In-sample optimization**: these parameters were chosen from the same
  60-day window they're scored on. The high `pct_profitable_combos` is
  reassuring (a narrow lucky spike would look different), but this is not
  out-of-sample validated yet — worth re-checking after a few weeks of live
  paper trading, or backtesting against an earlier 60-day window.
- **Volume-based strategies need real volume data.** `orb_volume` and
  `vwap_reclaim` should be re-tested on individual stocks (which do report
  real volume on Yahoo) rather than indices, before concluding they don't
  work at all.
- 5-minute-candle resolution only; not tested at other candle sizes.
