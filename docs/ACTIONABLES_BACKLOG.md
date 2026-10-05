# Actionables Backlog (product backlog — single source of truth)

Rule (CLAUDE.md thumb rule, 2026-10-05): every actionable that surfaces in any
session is appended HERE the moment it's identified; every session picks its
next work FROM here; items are closed/updated here as they move. Nothing lives
only in chat or a transfer pack. Status: TODO / IN-PROGRESS / BLOCKED / DONE / PARKED.
Never delete a row — close it with a date and evidence (run id, commit, URL).

| ID | Item | Status | Priority | Notes / evidence / blocker | Added | Closed |
|----|------|--------|----------|----------------------------|-------|--------|
| B-01 | Merge Box Theory (`bdf7c13`) + BIDIRECTIONAL category/Parabolic SAR (`2713d4f`) to `main` via deploy-gate (`source_ref=claude/relaxed-sagan-fcrt6u`) | IN-PROGRESS | High | User approved 2026-10-05; gate re-dispatched, queued. Verify via `git log origin/main` | 2026-10-05 | |
| B-02 | Pull + report Order Block Delta research results | TODO | High | Run id 37358050173 completed success, results unread | 2026-10-05 | |
| B-03 | Pull + report Volume Profile/POC results | TODO | High | Was in_progress | 2026-10-05 | |
| B-04 | Pull + report RSI Reversal variant sweep results | TODO | High | Was in_progress | 2026-10-05 | |
| B-05 | Pull + report Pin Bar Reversal validation results | TODO | High | Was queued | 2026-10-05 | |
| B-06 | Pull + report Fair Value Gap validation results | TODO | High | Was queued | 2026-10-05 | |
| B-07 | Pull + report Gap-Up Fade Short ATR-mult sweep (re-run) results | TODO | High | 3 prior attempts cancelled/failed | 2026-10-05 | |
| B-08 | Dispatch Box Theory variant sweep + report | BLOCKED | High | Needs B-01 | 2026-10-05 | |
| B-09 | Dispatch Parabolic SAR variant sweep + report | BLOCKED | High | Needs B-01 | 2026-10-05 | |
| B-10 | Register every variant tried (pass or fail) in `strategy_registry.py` with real metrics; Box Theory/SAR under BIDIRECTIONAL only after real full-universe numbers | TODO | High | Never register placeholder metrics | 2026-10-05 | |
| B-11 | Book 2 (Murphy): Directional Movement/ADX — full implement→test→validate→report cycle | TODO | Medium | Same chapter as SAR | 2026-10-05 | |
| B-12 | Book 2: Point & Figure | TODO | Medium | | 2026-10-05 | |
| B-13 | Book 2: Elliott Wave (confirm chapter exists first) | TODO | Medium | | 2026-10-05 | |
| B-14 | Book 2: classic chart patterns (H&S, triangles, flags/pennants, double/triple tops, wedges, rectangles) | TODO | Medium | One strategy at a time | 2026-10-05 | |
| B-15 | Book 2: remaining TOC items not yet confirmed (Time Cycles, Money Mgmt/trading tactics, Volume/OI) — extract every strategy | TODO | Medium | Per "extract EVERY strategy" rule | 2026-10-05 | |
| B-16 | Candle-size sweeps (1m/5m/15m/1h/4h + natural) for Order Block, FVG, Pin Bar, Volume Profile, Box Theory, Parabolic SAR, RSI Reversal; also RANGE-short/TREND-down short/RSI fade/Gap-Up Fade | TODO | Medium | Step-1 passes only did 5m | 2026-10-05 | |
| B-17 | Long/short mirror check for Order Block, FVG, Pin Bar, Volume Profile | TODO | Medium | Both-directions thumb rule | 2026-10-05 | |
| B-18 | Indicator Combinatorics: Step 2+ (pairs both role orderings, triples, ... multi-timeframe) after Step-1 results land | TODO | Medium | docs/INDICATOR_COMBINATORICS_METHODOLOGY.md | 2026-10-05 | |
| B-19 | NYKAA.NS: confirm SL status fresh, pull Journal Sync SL-rejection reason, heal | PARKED | High | User: leave until 8am 6 Oct 2026. Suspected T1/settlement rejection (unconfirmed) | 2026-10-05 | |
| B-20 | Verify `kotak_live_feed.py` vs Kotak 5-Oct-2026 WebSocket deprecation; migrate if needed | TODO | Low | Read-only display feed, isolated; no doc access last session | 2026-10-05 | |
| B-21 | Pre-existing failing test `tests/test_nse_fo_chain_sensex_strike_chain.py::test_strike_chain_includes_put_side_when_requested` (sandbox/network dependent) | TODO | Low | Confirmed unrelated to session changes | 2026-10-05 | |
| B-22 | Repo is PUBLIC on GitHub — user decision on making private | TODO | Low | Flagged, user's call | 2026-10-05 | |
| B-23 | GitHub App "Claude" permissions-update email — user review | TODO | Low | User's own call | 2026-10-05 | |
| B-24 | Volume-Profile proxy disclosure: keep as proxy, don't "fix" to literal CoinGlass port without re-reading disclosure | DONE | Info | Standing note, no action | 2026-10-05 | 2026-10-05 |
