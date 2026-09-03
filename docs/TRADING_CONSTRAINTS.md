# Trading Constraints (standing rules)

These are the hard limits the live paper-trading engine (`_auto_signal_core`
in `main.py`) enforces on every check, for every market. They are the
canonical reference — if a future change conflicts with this file, the
change is the bug.

| Constraint | Value | Enforced by |
|---|---|---|
| **Capital** | ₹2,00,000, one shared pool across every market (NSE, crypto, US) | `capital` param, default across all WATCHLIST entries |
| **Max loss per day** | **2% of capital (₹4,000)** — resets at IST midnight, every calendar day, automatically | `daily_risk_pct=2.0` + `ist_midnight_epoch()` in `today_realized_pnl()` |
| **Max risk per trade** | **2% of capital is a CEILING, not a fixed rate** — set lower per symbol where evidence supports it | `risk_per_trade_pct`, per-symbol in `WATCHLIST` |
| **Per-trade stop-loss cap** | Same ceiling logic, tighter of this or the strategy's own ORB-low level | `stop_pct`, per-symbol in `WATCHLIST` |
| **Risk:Reward target** | 1:2 (target = entry + 2 × stop distance) | `rr=2.0` |
| **Capital deployed cap** | Total notional across all open positions never exceeds ₹2,00,000 | `deployed_notional()` capital check in the entry path |

## Per-trade risk: 2% is a ceiling, tuned down by evidence

Current split (as of 2026-09-03):
- **NIFTY, BANKNIFTY, SENSEX: full 2%, strategy `orb_breakout`.** Real
  60-day backtest evidence behind this exact ORB strategy
  (`docs/daily_logs/2026-09-02-entry-trigger-research.md`) — profitable on
  95.8-100% of swept parameter combinations, not a lone lucky spike.
- **AAPL: full 2%, strategy `bullish_engulfing` (trend_sma=20).** Switched
  2026-09-03 from unvalidated `orb_breakout` defaults once real evidence
  existed for a different strategy on this symbol — 100% of 6 swept
  combos profitable (`docs/strategy_log.xlsx`). Live exits still use the
  same bounded-risk framework (stop/target/EOD-squareoff) as every other
  symbol, not the backtest's own open-ended exit — see the docstring on
  `_auto_signal_core` in `main.py`.
- **SPY, QQQ, BTC-USD, ETH-USD: 1% (half the ceiling), strategy
  `orb_breakout`.** No evidence yet that any strategy works on these -
  runs conservative until one earns a track record, the same way
  NIFTY/BANKNIFTY/SENSEX and AAPL did.

Per-symbol `strategy` is set in `main.py`'s `WATCHLIST`; the redundant
GH Actions backstop workflows (`live-signals*.yml`) must pass matching
`strategy`/params for any symbol that isn't plain `orb_breakout`, or the
backstop call and the in-process scheduler will disagree about how that
symbol is being traded.

## The daily loss cap, specifically

- Resets automatically every IST calendar day at midnight — not manually,
  not on a rolling 24h window. This is deliberate: it's the account's "day"
  regardless of which market (NSE/US/crypto) a position is in, since a
  US-session trade spans ~19:00-01:30 IST and needs one consistent day
  boundary for the whole shared pool.
- Once today's realized loss (summed across every symbol/market, converted
  to ₹ via each trade's own `fx_to_inr`) hits ₹4,000: no new entries are
  taken, and any open position is squared off immediately, for the rest of
  that IST calendar day.
- This is a hard numeric check in code (`halted = remaining_budget <= 0`),
  not a judgment call — see the multi-agent architecture doc: Validator-role
  logic like this is deliberately deterministic code, never routed through
  an LLM's discretion.

## Where this is currently duplicated (keep in sync if you change a number)

- `main.py`: `SCHEDULER_DAILY_RISK_PCT`, `SCHEDULER_RISK_PER_TRADE_PCT`,
  `SCHEDULER_STOP_PCT`, `SCHEDULER_RR` (used by the in-process scheduler)
- `.github/workflows/live-signals.yml`, `live-signals-us.yml`,
  `live-signals-crypto.yml` (redundant GH Actions backstop calls)
- `/dry-run-day`, `/trade-view`, `/live` default query params in their own
  fetch calls
