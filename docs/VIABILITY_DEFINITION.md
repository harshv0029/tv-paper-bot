# Viability definition (thumb rule, user 2026-10-13)

"Viable" is defined by exactly three factors, all read from the NEWEST entry of the explorer viable stack
(`strategy_viable_stack`, label `pfnet(lo-hi), min(n), maxhold(h|any)`) and applied to each strategy's STORED backtest metrics:

1. PFnet range (lo <= PFnet <= hi)
2. Minimum number of backtested trades (n_trades >= min)
3. Maximum average hold in market hours (avg_held_hrs <= maxhold; a strategy with no recorded hold fails a limit)

Rules:
- Always fetch the newest stack entry first (`/strategy-viable-stack?full=1`, `main._load_viable_overrides()`); never use a remembered or hardcoded floor.
- Derived at read time from raw metrics, so a new backtest result qualifies (or a changed one drops out) with no re-save; raw metrics are never trimmed.
- Used by: the real-money entry gate, `is_viable`, `is_quality_viable`, `viable_leaderboard`, `/strategy-leaderboard`, `/strategy-viable-buckets`, `/strategy-scan-activity`, `/entry-funnel`.
- A legacy entry whose label has no parseable definition falls back to its saved name list. With no stack at all, the PFnet floor in `strategy_registry.py` is only a fallback.
- Pushing a new definition from the explorer ("Make this set viable") saves the three factors in the label; the categories filter is display-only.
