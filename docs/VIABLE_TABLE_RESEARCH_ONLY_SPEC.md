# Viable table: research-only vs scan-wired (B-779) - 2026-10-12 IST

Goal: trade-view shows every registry tag with PFnet >= 1.1 (~310 research-only plus 94 scan-wired), each clearly labelled, WITHOUT enabling any real money. The real-money gate (`_is_strategy_viable_for_real_money`, via `_STRATEGY_TAG_TO_REGISTRY_NAME`) is untouched: a research-only tag has no live entry path and no mapping entry, so it cannot trade.

## Current state (verified in tree at 394dc31)
- `strategy_scan_activity(include_unwired=False)` (main.py ~20542): wired rows carry `scan_wired=True` (~20709); research rows are appended at ~20731 only when `include_unwired` (default wired-only, per user 2026-10-11).
- `static/trade-view.html` already requests `/strategy-scan-activity?include_unwired=true` (~2079) and has a Wired?/Not wired column (header ~368, cell ~960) with sort. So part (a) of B-779 is done (B-780).
- Remaining gap: wording and clarity. "Not wired" does not say "research-only, cannot trade"; no counts; wired and unwired rows share one ranked list with no filter.

## Design
1. Server adds `status` to every row: `"live_wired"` or `"research_only"` (derived from `scan_wired`; keep `scan_wired`). Add `"counts": {"viable_total", "live_wired", "research_only"}` next to `strategies`. All derived at read time from the registry; no stored flag.
2. Rows also expose `n_trades`, `win_rate_pct` (and existing `avg_held_hrs`) from the stored `Metrics`; no field dropped.
3. Page: label "Research-only (no live path, cannot place orders)" in grey instead of the orange "Not wired"; wired rows stay green "Live-wired". Summary line "Viable: N total, 94 live-wired, M research-only" from `counts`. Three-way filter All / Live-wired / Research-only (default All). Default sort unchanged (PFnet desc).
4. Tooltip on research-only rows: "Passes PFnet >= 1.1 in backtest only; real orders are blocked until a live entry path exists and a main.py replay confirms the number (see WIRING_PLAN_RESEARCH_VIABLES.md)."
5. No change to `_is_strategy_viable_for_real_money`, `PFNET_LIVE_FLOOR`, `_STRATEGY_TAG_TO_REGISTRY_NAME` or any kill switch. Never alias or merge tags.

## Exact edit points for the coordinator
main.py:
- ~20709 wired row dict: add `"status": "live_wired"`, `n_trades`, `win_rate_pct` from `strat.metrics`.
- ~20744-20749 research row dict: add `"status": "research_only"` and the same metric fields.
- ~20760 final return: add `counts` computed from `rows`.

static/trade-view.html:
- ~368 header "Wired?" -> "Status".
- ~960 cell: switch on `r.status` (fallback to `scan_wired` for old payloads).
- ~2079 fetch handler: write `counts` to a summary element; add the filter select beside the existing viable-table filter.
- ~963-965: replace the "not wired" cell text with a dash (the row label already says research-only); keep the title tooltip.

Tests: extend the existing strategy-scan-activity test (grep tests/ for `strategy_scan_activity`): every row has `status`; `counts` sum equals len(rows); research-only tags are absent from `_STRATEGY_TAG_TO_REGISTRY_NAME`; a research-only tag is rejected by `_is_strategy_viable_for_real_money`. Keep the fetch on the 10 s poll, no caching (dashboard-follows-registry rule).

## Net-profit effect
None directly (display). Indirect: the user sees which research viables merit wiring; the ranked plan `docs/WIRING_PLAN_RESEARCH_VIABLES.md` (291 candidates by PFnet per day held) drives part (b). B-779 stays OPEN until top picks are replayed through main.py.
