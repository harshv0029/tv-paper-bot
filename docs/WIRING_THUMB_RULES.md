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

## Viability stack is never emptied (user 2026-10-20 IST)
The explorer viability stack (`strategy_viable_stack`) always holds up to 10 conditions (`VIABLE_STACK_SIZE`) and can never be empty after a restart. Recovery order on an empty table: Upstash restore, then the git-synced `docs/viable_stack.json`. The entry gate and explorer call it on every read (throttled 20 s). Undo refuses to remove the last entry, and `viable-stack-sync.yml` never overwrites the git backup with an empty stack. The newest entry stays the live viability definition.

## Reply footer is 8 items (user 2026-10-20 IST)
Item 1 is "Subagents" (one line per subagent, its task and status; "none running" if there are none). Then: (2) New strategies (pfnet >= 1) wired end to end today = x; (3) Completed; (4) Decisions; (5) Next actionables; (6) Input required; (7) Backlog %; (8) Context.

## Read the rejection reason, then change the next order accordingly (user 2026-10-21 IST)
Every rejected real order's reason (Kotak `rejRsn`, surfaced as `detail`) must be read and the NEXT request must be built from it. Re-sending the identical order after a rejection is a bug. Each known reason maps to a specific change: price outside the valid range / circuit breach -> move the price inside the band (B-1304); T1/CAS transition -> the existing T1/market-retry paths; margin/limit -> do not retry blindly, protect another way. An unknown reason is logged with the reason and escalated (alarm), never silently retried unchanged. Incident: UNIONBANK 21 Oct 2026, three identical 159.67 SL requests, all rejected "Circuit breach", position naked from 09:16 IST. Applies to entry, SL, target and exit paths of every category.

## Stop-loss orders: the next order is based ONLY on the rejection reason (user 2026-10-21 IST, restated)
A rejected SL is never resent unchanged and never left unplaced. Read Kotak's own rejection text (order_report, `rejection_reason`/`rmk`), map it to a change, and place the next order from that change only: price band -> trigger moved inside the band; margin/T1 -> flag and take the next risk-cutting action; unknown text -> alarm, no blind retry. Each retry logs the reason it was based on. Also: a real stop is never wider than the cap (`REAL_INTRADAY_MAX_STOP_PCT`, 5% for intraday longs) so it cannot fall outside the band in the first place (CANBK 17%, BANKBARODA 15% on 2026-10-21).
