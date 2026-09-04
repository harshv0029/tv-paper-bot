# Project Structure & Optimization Plan

Explicit user request (2026-09-04): optimize the whole project at both
**design level** (architecture) and **execution level** (code), structured
enough that future work needs less rework, checked for completeness and
accuracy rather than guessed. Every finding below was verified directly
against the repo (line numbers, file sizes, diffs) on 2026-09-04, not
recalled from memory — where a claim needed checking, it was checked.

## 0. How to use this document

This is the reference for "what shape is this project actually in and what
should change." Section 1 is the accurate as-built picture (read this before
assuming how the system works). Section 2 is design-level findings. Section
3 is execution-level (code) findings. Section 4 is the prioritized plan.
Re-read this before starting any large refactor so work doesn't duplicate
what's already flagged here — same principle `docs/STRATEGY_LOG.md` already
runs on for strategies.

---

## 1. Current architecture, as it actually stands

### 1.1 It's a multi-session system, not one agent

This project is run by **five separate Claude sessions coordinating through
git**, not one continuous session with a todo list:

| Agent | Job | Coordination channel |
|---|---|---|
| **Main session** (this one, `tv-paper-bot-a8`) | Owns `main.py`/trading logic, dispatches GitHub Actions, talks to the user | — |
| **Research Agent** | Backtests strategy candidates across markets, logs to `docs/strategy_log.xlsx` | Reads `docs/RESEARCH_AGENT_BRIEF.md` each cycle for standing instructions |
| **Sentiment Agent** | Per-symbol + sector news/sentiment reads | Reads `docs/SENTIMENT_AGENT_BRIEF.md`; writes `docs/sentiment_log/<date>.md` |
| **Journal Sync Agent** | Dispatches `journal-sync.yml`, notifies on trade close | Reads `docs/JOURNAL_SYNC_AGENT_BRIEF.md`; `SendMessage`s the main session |
| **Deploy Gate agent** | Runs `deploy-gate.yml`'s checks before any `staging`→`main` merge | Reads `docs/DEPLOY_GATE_RULES.md` |

The `*_AGENT_BRIEF.md` files are the actual control channel — each agent
reads its brief at the start of every cycle and treats it as live
instructions, not a one-time note. **This means any future architecture
change has to consider all five, not just `main.py`.** A change that only
updates code and not the relevant brief will silently not reach the agent
that needs to know about it.

### 1.2 Runtime system

- **`main.py`** (4,535 lines) — single FastAPI app: DB schema, webhook
  ingestion, paper P&L, OHLC fetch/cache, the technical-strategy library,
  backtest/sweep engine, options pricing (Black-Scholes), live signal cores
  (equity + options), real-order gating, journal reconciliation, an
  in-process scheduler, and ~30 REST endpoints. See §2.1 — this is the
  single biggest structural issue found.
- **`kotak_neo.py`** — read-only Kotak Neo auth/account/market-data calls.
- **`kotak_real_orders.py`** — isolated real order-placement (CNC/MKT/DAY
  only), deliberately separated from `kotak_neo.py` and from paper logic.
- **`kotak_live_feed.py`** — background WebSocket tick consumer.
- **`static/live.html`**, **`static/trade-view.html`** — self-refreshing
  dashboards, pull from the REST API client-side.
- **Render free tier** hosts it — no persistent disk (DB wiped every
  redeploy, mitigated by git-tracked journals + startup reconciliation),
  sleeps on inactivity. Documented at length in `docs/KNOWN_ISSUES.md`.
- **SQLite** is the live DB; **git-tracked JSON files** under `state/` and
  `docs/` are the durable source of truth that survives a redeploy.

### 1.3 Automation backbone — 12 GitHub Actions workflows

`deploy-gate`, `diag-curl`, `entry-trigger-research`, `fetch-chart-data`,
`journal-sync`, `live-signals` (+ `-commodities`, `-us` variants),
`real-trading-control`, `refresh-nse-universe`, `run-backtests`,
`trading-control`, `trailing-stop-threshold-backtest`. Several of these
(`live-signals*`) are a backstop for the in-process scheduler, kept per
`KNOWN_ISSUES.md`'s finding that 5-minute cron isn't reliable at that
granularity on GitHub's free scheduler.

### 1.4 Change pipeline

- Trading-logic changes: `staging` → `deploy-gate.yml` (static safety
  checks + `orb_breakout` backtest regression vs. `docs/deploy_baseline.json`)
  → auto-merge to `main` only if every rule passes (`docs/DEPLOY_GATE_RULES.md`).
- Docs/UI/CI-only changes: go straight to `main` under the project's own
  stated policy. **Session-specific note:** this session's docs commits
  (STRATEGY_LOG.md, this file) went to a harness-designated branch
  (`claude/add-strategy-log-docs-8stbrq`) instead, per this session's own
  external branch requirement — that's a one-session carve-out, not a
  change to the project's actual docs-go-to-main policy.

### 1.5 Money-safety architecture (verified current state)

Two independent gates required for any real order: `REAL_TRADING_ENABLED`
env var (exact string `"YES"`) AND `real_trading_control` DB row. **Checked
`state/real_trading_control.json` directly: `db_switch_enabled: true`
right now.** Today's real spend is ₹0 (`state/real_trades_today.json`) and
there are no open real positions. Stated here plainly because a document
about reducing rework should not bury the one fact where "rework" means
real money, not just wasted time.

---

## 2. Design-level findings

Ordered by how much rework/risk each one actually causes, not by ease of fix.

### 2.1 `main.py` is a 4,535-line single-file monolith — the biggest finding

One file holds: DB layer, HTTP ingestion, paper P&L, data fetch/caching,
the strategy library, the backtest/sweep engine, options pricing, both live
signal cores, real-order gating, journal reconciliation, the scheduler, and
routing for ~30 endpoints. Concretely, in this session alone, every change
— the VWAP strategies, the ORB filter, the real-trading module — required
grepping through this one file to find the right spot, with no structural
boundary stopping an edit in one area from touching an unrelated one. This
is the direct cause of the "time taken for rework" the request named. Full
fix plan in §4 Phase 1.

### 2.2 Three parallel "strategy log" artifacts that don't reference each other

- `docs/STRATEGY_LOG.md` — this session's own log (VWAP/heatmap/VIX rows),
  single-`/backtest`-run methodology.
- `docs/strategy_log.xlsx` — the **Research Agent's** actual working log,
  swept-parameter-combo methodology (`pct_profitable_combos`), the real
  bar that gates live `WATCHLIST` adoption per `RESEARCH_AGENT_BRIEF.md`.
- `docs/strategy_backtest_log.xlsx` — a third file; its role wasn't
  established by anything read this session (worth asking the Research
  Agent or checking its own brief history for origin before assuming it's
  redundant vs. actively used for something distinct).

Verified: `RESEARCH_AGENT_BRIEF.md` never mentions `STRATEGY_LOG.md`, and
nothing in this session's additions to `STRATEGY_LOG.md` cross-references
the xlsx. Real risk: the same strategy idea gets independently reinvented
and tested twice, at two different rigor bars, and whoever reads only one
log gets an incomplete picture of what's actually been tried.

### 2.3 `README.md` describes a system that no longer exists

It documents the original Phase-2 webhook-only prototype: 4 files, a
single `WEBHOOK_SECRET`, explicitly states "no real broker order is ever
sent." It has zero mention of: the in-process scheduler, the 30+ live
endpoints, Kotak Neo, Stage 3 real trading, the multi-agent system, or any
file under `docs/`. Anyone opening this repo cold — including a future
session with no prior context — gets actively misled about what the system
does today.

### 2.4 Unbounded, never-rotated logs

`docs/attempt_log.json` is **34,943 lines** already and grows every
scheduler cycle with no pruning. `docs/sentiment_log/` and
`docs/daily_logs/` accumulate one file per day indefinitely. Not urgent
today, but left alone for months this slows git clone/status and makes
these files unreadable as a whole without tooling.

### 2.5 `docs/TRADING_CONSTRAINTS.md` (1,130 lines) is a changelog, not a lookup reference

It's the real source of truth for every risk %, cap, and standing rule —
but it's structured as a chronological narrative of how each value changed
across sessions. Finding "what is the current real-trading daily cap"
means reading history, not looking up one number. Same underlying problem
as §2.1, in doc form.

### 2.6 A dead, stale dependency file

`requirements_1.txt` still pins the pre-Kotak-v3-migration dependency set
(`uvicorn[standard]`, no `pyotp`, no `kotakneoapi`) — confirmed via direct
diff against `requirements.txt`. Nothing in the repo appears to reference
it (Render's build command uses `requirements.txt`), so it's dead weight
that risks a future `pip install -r requirements_1.txt` typo silently
reinstalling a broken pre-migration environment.

---

## 3. Execution-level findings (code specifics)

### 3.1 Confirmed duplicate function: `_norm_cdf`

Defined twice, byte-identical, at `main.py:1085` and `main.py:1402` (read
both directly to confirm). Harmless today — Python just uses the later
definition — but exactly the kind of copy-paste drift that becomes a real
bug the day a future options-pricing change edits one copy and not the
other. **Fixed as part of this pass — see §4 Phase 0.**

### 3.2 Position-sizing formula duplicated across the two signal cores

`risk_amount_inr = usable_capital_inr * risk_per_trade_pct / 100` appears
near-identically in both `_options_signal_core` (main.py:2054) and
`_auto_signal_core` (main.py:2570). Not wrong, but a future sizing-logic
change (e.g. the VIX throttle proposed in `STRATEGY_LOG.md` #28) has to be
remembered and applied in two places instead of one shared helper.

### 3.3 No automated local test suite

The only test-named file in the repo is `docs/strategy_backtest_log.xlsx`
— not real tests. Every validation this session (VWAP strategies, the ORB
filter) was a live `curl` against the production server dispatched via
GitHub Actions: correct, but slow (workflow queue latency + network
round-trip) and burns Actions minutes (`KNOWN_ISSUES.md` already flags
Actions-minute consumption as a real constraint). Pure-logic pieces
(`add_strategy_signal`, `extract_trades`, `bs_price`) don't need a live
server or network to test — they're straightforward unit-test candidates
once separated from the route layer (§4 Phase 1 makes this practical).

### 3.4 Deploy-gate regression coverage is narrower than the live strategy surface

`deploy-gate.yml`'s backtest regression check replays only `orb_breakout`
across a 12-symbol sample. The 6 VWAP strategies and the liquidity/VIX
proposals added this session have zero regression coverage — if any of
them is ever promoted toward live status, a later change could silently
break them with the gate still reporting green.

---

## 4. The plan — prioritized and sequenced

### Phase 0 — housekeeping (near-zero risk, no behavior change)

- [x] **Done in this pass:** removed the duplicate `_norm_cdf` definition.
- [ ] Delete or archive `requirements_1.txt` — flagged, not deleted yet;
      confirm nothing intentionally keeps it before removing.
- [ ] Add a top-of-file banner to `README.md` pointing at `docs/` for
      current behavior, as a stopgap before the full rewrite in Phase 2.

### Phase 1 — split `main.py` into modules (the core structural fix)

A **behavior-preserving** refactor — pure code motion, not logic changes.
Module boundaries, based on the actual function inventory read this
session:

| New module | Moves from `main.py` | Status |
|---|---|---|
| `constants.py` | `ORB_STRATEGY_PREFIX`, every `OPTIONS_*` constant | **Done, 2026-09-04** |
| `data_fetch.py` | `fetch_ohlc`, `get_fx_to_inr`, `_DATA_CACHE`/`_CACHE_TTL_SECONDS` | **Done, 2026-09-04** |
| `options_pricing.py` | `bs_price`, `_norm_cdf` (once), `_bs_delta`, `select_option_contract`, `_requote_contract`, `parse_legs`, `run_options_backtest` | **Done, 2026-09-04** |
| `db.py` | `get_db`, `init_db`, all `reconcile_*_from_journal` | Not started |
| `strategies.py` | `add_strategy_signal`, `extract_trades`/`extract_trades_fast` | Not started |
| `signal_core.py` | `_auto_signal_core`, `_options_signal_core`, `_detect_direction_signal`, `_trend_confidence`, `_compute_trend`, `_trailing_stop_target` | Not started — highest-risk module (touches DB, real trading, scheduler state) |
| `real_trading.py` | `is_real_trading_enabled`, `_real_today_spent_inr`, `_maybe_place_real_entry`/`_exit`, `_log_real_attempt` (pairs with existing `kotak_real_orders.py`) | Not started |
| `scheduler.py` | `_scheduler_loop` and its helpers | Not started |
| `main.py` (end state) | FastAPI app setup + route wiring only | In progress — 4,535 → 4,246 lines so far |

**Done, 2026-09-04:** the three lowest-risk, most self-contained modules —
each verified by (1) `ast.parse` on every touched/new file, (2) the Phase 3
pytest suite passing unchanged, (3) an identity check confirming
`main.bs_price is options_pricing.bs_price` etc. for every moved name (not
just "a same-named symbol exists somewhere"), (4) a `TestClient` smoke test
against the actually-running app (`/health`, `/watchlist`) confirming
route wiring survives, not just that the file imports. That verification
pass itself caught two real mistakes before they shipped: an inaccurate
comment in an early draft of `constants.py` (rewritten from the real
source, not a paraphrase), and a leftover second definition of
`ORB_STRATEGY_PREFIX` still sitting in `main.py` after the move (harmless
value-wise, but exactly the kind of duplicate-definition drift this
refactor exists to remove) — both fixed before commit, not after.

**Not done in this pass, deliberately:** `signal_core.py` in particular
holds the live trading brain — `_auto_signal_core` alone is ~500 lines
touching DB state, the scheduler, and real-order gating. Moving it needs
either much heavier local fixtures than this session's synthetic-OHLCV
tests, or a real run of `deploy-gate.yml`'s backtest regression against
live market data (the project's own established validation method) before
merging — this session's sandbox has no outbound network access to Yahoo
Finance to run that check locally (confirmed: a live `/backtest` call
here fails on a blocked connection, not a code error). Splitting that
module deserves its own focused pass with that check available, not a
rushed continuation of this one.

Should land as its own `staging` branch, gated the normal way, done in one
focused pass per remaining module rather than interleaved with feature
work (mixing "moved this code" diffs with "changed this logic" diffs is
exactly what makes a future regression hard to bisect).

### Phase 2 — doc consolidation

- **Pick one canonical strategy log.** Given the Research Agent's xlsx
  already has the stricter, swept-combo methodology and is the one
  actually gating live `WATCHLIST` adoption, recommend: `STRATEGY_LOG.md`
  becomes an explicit "first-pass scratch log — promising rows graduate to
  a real `/sweep` in `strategy_log.xlsx` before live adoption," with each
  file linking to the other. Needs your call on origin/purpose of
  `strategy_backtest_log.xlsx` before deciding if it merges or stays.
- **Restructure `TRADING_CONSTRAINTS.md`**: add a short "current values"
  table at the top (the lookup-friendly part), keep the existing
  chronological narrative below as history — don't lose the audit trail,
  just stop making every reader scroll through it for today's number.
- **Rewrite `README.md`** to describe the system as it stands today.

### Phase 3 — test coverage

- Local `pytest` suite for the pure-logic modules created in Phase 1:
  `add_strategy_signal`'s boolean-column output on synthetic OHLCV
  fixtures, `extract_trades`'s P&L math, `bs_price` against known
  reference option prices, the position-sizing formula. Catches a logic
  bug in seconds locally instead of via a live production dispatch.
- Extend `deploy-gate.yml`'s regression check to cover the VWAP strategies
  once any of them moves toward live status (currently `orb_breakout`-only).

### Phase 4 — ongoing hygiene (prevents this list from regrowing)

- Before adding a new strategy: log it in the one canonical place from
  Phase 2, not a new parallel file.
- Before adding a new module-level helper: `grep -n "^def <name>"` first
  — the exact check that would have caught §3.1.
- Rotate/archive `attempt_log.json` and the daily log directories past
  some age (e.g. a monthly rollup) instead of unbounded growth.
- Update `README.md` as part of any change that adds a real capability
  (new agent, new trading stage) — it's clearly drifted before and will
  again without this being a deliberate habit, not an afterthought.

---

## 5. What was fixed immediately vs. what's queued

**Fixed in this pass (2026-09-04, audit turn):** the duplicate `_norm_cdf`
(§3.1) — safe, mechanical, zero behavior change.

**Fixed in this pass (2026-09-04, follow-up "do the best possible way"
turn):** started Phase 1 for real — `constants.py`, `data_fetch.py`,
`options_pricing.py` split out of `main.py` (4,535 → 4,246 lines),
verified via syntax check, the new pytest suite, per-symbol identity
checks, and a live `TestClient` smoke test against the running app. Also
added `tests/test_strategy_logic.py` + `requirements-dev.txt` (Phase 3,
resequenced ahead of finishing Phase 1 on purpose — see §4 Phase 3 — so
the riskier remaining modules have a real regression net to run against).

**Deliberately not done in this pass**, and why:
- The remaining, harder Phase 1 modules (`db.py`, `strategies.py`,
  `signal_core.py`, `real_trading.py`, `scheduler.py`) — `signal_core.py`
  especially touches live money-moving logic and needs the project's real
  `deploy-gate.yml` backtest regression (real market data, real network)
  to validate, not just local unit tests. This session's sandbox has no
  outbound access to Yahoo Finance to run that locally.
- Deploying anything in this pass to production: per the project's own
  `DEPLOY_GATE_RULES.md`, a `main.py` change is trading-logic code and
  must go `staging` → `deploy-gate.yml` → `main`. This session pushed to
  the harness-designated docs branch, not `staging` — the code exists,
  verified, on that branch, but reaching production needs someone to
  carry it onto `staging` and run the gate.
- Deleting `requirements_1.txt` — a one-way action flagged rather than
  taken.
- The doc consolidation in Phase 2 needs your decision on the xlsx files'
  respective roles before it can be done accurately rather than guessed.
