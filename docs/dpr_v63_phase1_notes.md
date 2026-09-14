# AI Trading Platform Bible V63.0 — implementation notes

Source document: `AI_Trading_Platform_V66_0_Institutional_Wealth_AI_Operating_System_DPR.docx`
(uploaded 2026-09-14; body calls itself "BIBLE VERSION 63.0" despite the V66.0
filename — an inconsistency in the source itself, noted to the user before
implementation started).

## What this document actually is

~70,000 lines / 11.8MB of text spanning three drafting passes (V61 → V62 →
V63 addenda), with heavy template duplication — most modules repeat an
identical 6-line "Validation and error handling" / "Concurrency and
idempotency" paragraph verbatim with only the module name changed — plus a
single ~50,000-line "corner-case verification library" (source section 78,
lines 10508–60912 of the extracted text) and two full "COMPLETE PRODUCTION
main.py" appendices, one explicitly marked "SUPERSEDED BY V63 SECTION 104"
but left in the document anyway. Treated per the user's explicit instruction
as authoritative content to implement, but NOT as a literal line-by-line
build order — the unique substance (state names, transition tables,
formulas, table/endpoint names, service contracts) is what's being built;
repeated boilerplate paragraphs and the corner-case library are reference
material, consulted per-module rather than transcribed.

## Standing conflicts resolved with the user (2026-09-14)

1. **Database engine.** The DPR fixes PostgreSQL as the persistence layer;
   production (`main.py`) runs SQLite. User decision: adapt the DPR's tables
   to SQLite, no Postgres migration. Consequences applied throughout:
   UUID primary keys → `TEXT`; `TIMESTAMPTZ` → float unix timestamp
   (matches `main.py`'s own convention); `SELECT ... FOR UPDATE` →
   `BEGIN IMMEDIATE` write-lock (SQLite has no row-level FOR UPDATE);
   "transactional outbox" → a plain append-only table in the same DB,
   since there is no message broker anywhere in this codebase to integrate
   with.
2. **Real trading.** `REAL_TRADING_ENABLED` (a Render env var, set manually
   by the user, deliberately isolated from code pushes — see `main.py:5365`)
   is the user's own switch. Nothing built under `app/` changes that
   isolation or wires into it without a separate, explicit go-ahead.
3. **Wiring.** Everything under `app/` is new and additive. It is NOT wired
   into `main.py`'s live webhook/order-placement path. Per CLAUDE.md's
   standing real-money discipline, no entry/exit/sizing-affecting module
   gets wired into the live path without its own unit tests + full pytest
   green + full 52-symbol/60-day replay validation + explicit user
   go-ahead — same bar as any other production change to this repo.

## Phasing

The DPR describes ~9-plus engines (Modules 478–487, plus the V62/V63
capital/ledger/learning/governance engines from sections 47–96+). Building
all of it is a multi-session effort. Order follows the DPR's own dependency
shape — the state machine and risk/sizing engines are what everything else
plugs into:

- [x] **Phase 1 — Module 478, State Transition Governance Engine**
      (`app/orchestrator/state_machine.py`, `app/core/enums.py`). 13 unit
      tests, all green. Not wired anywhere yet.
- [x] **Phase 2 — Module 480 (Risk Budget Management Engine) + Module 481
      (Position Sizing Production Engine)** (`app/risk/risk_budget.py`,
      `app/risk/position_sizing.py`). Module 481 transcribes Section 22's
      exact `size_position()` algorithm verbatim (SOURCE). Module 480 has
      no exact formula in the source — the allocation formula
      (`nominal = requested * confidence`, then reduced by
      `(1-correlation_factor)*(1-drawdown_factor)`, then capped to
      remaining portfolio capacity) is an IMPLEMENTATION ASSUMPTION derived
      from its three primary rules and AC-480-01/02/03; documented in the
      module docstring. 33 new unit tests, all green. **These two directly
      touch entry/exit/sizing — still not wired into `main.py`. Wiring
      requires the full replay-validation gate + explicit go-ahead, same
      as any other production sizing change, not done here.**
- [x] **Phase 3 — Module 482, Live Capital Guard Engine**
      (`app/risk/capital_guard.py`). Section 23's severity/action table and
      `capital_guard()` pseudocode transcribed as SOURCE; the
      per-dimension breach logic it calls (`evaluate_all_dimensions`) isn't
      defined anywhere in the source, so it's an IMPLEMENTATION ASSUMPTION
      (3-threshold-per-dimension model, documented in the module
      docstring) — same treatment as Module 480's formula in Phase 2. The
      "protection mode is durable" primary rule is a latch requiring an
      explicit `clear_protection()` (privileged actor + checklist id,
      mirroring Module 478's override-resume gate). 14 new unit tests, all
      green. Not wired into `main.py`.
- [ ] Phase 4 — Module 479 (Research Reproducibility Engine).
- [ ] Phase 5+ — remaining modules, prioritized with the user as each
      prior phase lands.

## Known pre-existing issue found while validating this phase (unrelated)

`tests/test_trend_weakened_range_exclusion.py` has 2 failing tests
(`test_trend_weakened_still_closes_a_trend_regime_position`,
`test_trend_weakened_still_closes_a_position_with_unknown_regime`) on the
branch tip **before** any of this session's changes (confirmed via
`git stash`) — unrelated to `app/`, touches only `main.py`'s existing
`trend_weakened` exit logic. Flagging per CLAUDE.md's disclosure rule
rather than silently working around it; not yet root-caused.
