# Trading Constraints (standing rules)

These are the hard limits the live paper-trading engine (`_auto_signal_core`
in `main.py`) enforces on every check, for every market. They are the
canonical reference — if a future change conflicts with this file, the
change is the bug.

| Constraint | Value | Enforced by |
|---|---|---|
| **Capital** | ₹2,00,000, one shared pool across every market (NSE, crypto, US) | `capital` param, default across all WATCHLIST entries |
| **Max loss per day** | **2% of capital (₹4,000)** — resets at IST midnight, every calendar day, automatically | `daily_risk_pct=2.0` + `ist_midnight_epoch()` in `today_realized_pnl()` |
| **Max risk per trade** | 2% of capital (₹4,000) | `risk_per_trade_pct=2.0` |
| **Per-trade stop-loss cap** | 2% of that trade's value max (tighter of this or the strategy's own ORB-low level) | `stop_pct=2.0` |
| **Risk:Reward target** | 1:2 (target = entry + 2 × stop distance) | `rr=2.0` |
| **Capital deployed cap** | Total notional across all open positions never exceeds ₹2,00,000 | `deployed_notional()` capital check in the entry path |

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
