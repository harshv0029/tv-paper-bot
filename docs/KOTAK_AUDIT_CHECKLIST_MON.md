# Post-close Kotak audit checklist (B-369) - Monday 2026-10-12, run after 15:30 IST

Purpose: ground truth from Kotak's own trade book and order book (never app tables alone), then turn what the day's real trades taught into docs/STRATEGY_LEARNINGS.md and ranked INR-impact actions. Public repo: never paste raw rows, account ids or holdings.

## Run (coordinator only; subagents have no network)
1. Dispatch `.github/workflows/kotak-pnl-audit.yml` (workflow_dispatch) after 15:30 IST. Check nothing urgent is queued (Deploy Gate/safety first); keep one running plus one queued. Set a `send_later` check-in about 5 min out (state the time in IST).
2. Optionally `kotak-sl-snapshot.yml` and `kotak-holdings-probe.yml`. The exchange cancelled all resting orders at 15:15 IST, so an empty SL list after close is expected, not a bug.

## Read, in this order (governance sequence)
1. Trade book: every fill today (symbol, side, qty, price, time).
2. Order book: every order incl. rejected/cancelled; tally by status; note rejection messages.
3. Positions/holdings, net of today's sells (B-303 lag).
4. Only then the app DB (`real_order_events` reasons, `real_positions*`, `signal_state*`) and compare.

## Per-trade questions
- Which engine/category entered it and which exited it? A cross-engine exit is a bug (ownership rule).
- Was an SL/SLM placed with the entry? Time gap entry-to-SL. A trade without a stop is an incident.
- Exit reason: stop, target, trail, eod_squareoff, manual. Does it match `real_order_events` `reason:` text? UNSTATED is a bug.
- Fill vs signal price (slippage); real charges vs the 0.8% model.
- Rejections (T1, margin, price band): cause, and did auto-heal retry?
- 09:15 IST: were overnight holdings protected first? Time to first SL (B-315).
- Any app-vs-Kotak mismatch (qty, SL id, open/closed)? Root-cause it; rewrite the app row to Kotak.

## Outputs
1. Realised net P&L per strategy tag and category (after costs), win %, avg hold; compare with the registry PFnet for the tag and flag divergence.
2. Dated entry in `docs/STRATEGY_LEARNINGS.md` ending with a "Profit-booking / exit takeaway" line (trail vs target vs timeout).
3. Ranked action list by estimated INR impact, each as a backlog row.
4. Update B-369 in `docs/ACTIONABLES_BACKLOG.md` with run id, IST date and evidence; never delete the row. Commit with attribution footer; full pytest and `ast.parse(main.py)` if code changed.
5. Keep raw tallies in full under `docs/backtest_data/` or the audit log; trim nothing.

## Stop conditions
Any unprotected open position, Kotak-rejected-but-recorded-placed order, or cross-engine exit: report immediately and alone, before the rest of the audit.
