# Wiring thumb rules (user instructions, kept in docs, not CLAUDE.md)

## 2026-10-14: wiring depends only on PFnet >= 1; the money trade is a separate item
Stated by the user three times in a row on 14 Oct 2026 and made a standing thumb rule ("Make it thumb rule").

1. **End-to-end wiring** (live entry code path, scan loop, scan counters, dashboard row, SL attached) is done for every strategy cell whose backtest through the real `main.py` shows PFnet >= 1. Nothing else is a wiring condition: not hold time, not trade count differences, not the explorer's viable stack.
2. **Scanning is unconditional once wired.** Every wired cell is scanned and its signal computed for every symbol, every pass, whether or not the real-money gate is open.
3. **The real-money viability check happens only when a trigger fires.** At that moment `_is_strategy_viable_for_real_money` (current PFnet floor, the newest viable stack entry incl. max hold, replay-owed tags) decides if a real order may go. If closed, no position opens, the trigger is counted (`blocked_triggers_today`) and the cell stays visible as `wired_gate_closed`.
4. Wiring and money trades are tracked as two separate backlog items. A closed money gate never un-wires a strategy, and never hides its scan counts.
5. No new kill switch; no trade without SL; Kotak-first state; all other rules unchanged.

Code: `_oneil_swing_try_entry` follows this order (scan, signal, gate). Other cell families still gate before scanning; migration tracked in backlog B-1250.

## 2026-10-14: the PFnet floor is 1.0 (user)
`PFNET_LIVE_FLOOR` was changed from 1.1 to 1.0 by the user on 2026-10-14, superseding the 2026-10-11 1.1 rule. A wired cell opens the real-money gate when PFnet >= 1.0 and stays closed below 1.0 (e.g. envelope atr4_h18 0.9963, cup atr4_h30 0.9943). Viability is still derived at read time from stored metrics, so cells in [1.0, 1.1) are viable again with no re-run.
