# Short-Selling Research Log (2026-09-29)

Full record of the short-selling implementation and research this session,
for future reference. Explicit user mandate throughout: "Implement short
selling in real money" → "Build it properly first" → (after the RANGE
mirror failed validation) "I need at least one strategy for the short
sell... this helps me downward trend of market... it's a must have."

**Bottom line up front: three genuinely distinct short-entry hypotheses
were built and validated against the full NSE universe. All three failed.
None is merged, none is live. See "Final verdict" at the bottom.**

## Branch state

All work described here lives on `claude/relaxed-sagan-fcrt6u`, unmerged.
Per CLAUDE.md's standing discipline, nothing here goes to `main` or goes
live without the user's own explicit go-ahead — this document itself is
not that go-ahead, only a record of what was tried and found.

Workflow files only (no trading-logic changes) were separately merged to
`main` via the branch-isolation technique, purely so they could be
dispatched via the GitHub Actions API: `range-short-validation-replay.yml`,
`trend-short-validation-replay.yml`, `rsi-overbought-short-research.yml`.
The actual short-selling code (new functions, tables, entry/exit logic in
`main.py`) stays on the feature branch only.

## Part 1 — RANGE VWAP-spike mean-reversion short (the original mirror)

### 1a. Initial build

Short mirror of the already-live RANGE-regime long strategy
(`_vwap_mean_reversion_entry`, which fires when price dips below the
lower VWAP/Bollinger band). The short mirror
(`_vwap_mean_reversion_short_entry`) fires on the opposite extreme: price
spikes ABOVE the upper band (z ≥ +2.0 std by construction, i.e.
`_vwap_deviation_z(...) <= -bb_std`, since `z` is defined from the long
side's own perspective).

New `main.py` additions: `signal_state_short`/`real_positions_short`/
`short_trades_closed` tables, `_vwap_mean_reversion_short_entry`,
`_range_regime_short_confidence`, `_range_regime_short_stop_loss`,
`_trailing_stop_target_short`, `_target_move_pct_short`,
`_short_signal_core` (a separate function from `_auto_signal_core`, not a
direction flag threaded through it — kept the live long path untouched to
avoid any regression risk to real-money code), real order placement in
`kotak_real_orders.py` (`place_real_short_entry/cover/stop_loss/target`,
`product="MIS"` since a naked short can't be held overnight). Eligibility
gating and kill-switch: explicit user decisions — no separate NSE
short-sell eligibility gate (rely on broker rejection), and real
short-selling gates on the same `REAL_TRADING_ENABLED` switch as the long
side (no separate kill switch).

Full pytest suite green, `ast.parse` sanity-checked, per CLAUDE.md
discipline, before any validation replay.

### 1b. First full-universe validation — fixed 3R target

`range-short-validation-replay.yml`, matrix-parallelized (10 → 50 → 40
shards over the course of the session, tuned for wall-clock time — see
"Infrastructure notes" below), full 2,680-symbol NSE universe, 60 days of
5-minute bars, calling the real `main.py` short-side functions.

| Metric | Value |
|---|---|
| Trades | 129,898 |
| Win rate | 15.3% |
| PFnet | **0.17** |
| PFgross | 1.36 |
| Avg net/trade | -₹1,222.62 |
| Cost drag | 123.3% |
| Exit mix | 80.5% stop_hit, 7.1% target_hit |

**Root cause found**: the short entry used a plain fixed `last_close -
rr*stop_dist` (3R) target — needs >25% win rate to break even before
costs, only hit target 7.1% of the time.

### 1c. Fix #1 — target cluster (mirrors the long side's architecture)

Added `_compute_target_cluster_short` (median of 2.0R / nearest support /
ATR-projected target, mirroring `_compute_target_cluster`), replacing the
fixed-3R formula. Re-ran the same full-universe replay.

| Metric | Before | After |
|---|---|---|
| Trades | 129,898 | 96,127 |
| Win rate | 15.3% | 22.8% |
| PFnet | 0.17 | **0.26** |
| Cost drag | 123.3% | 98.9% |
| target_hit rate | 7.1% | 18.2% |

Real, measurable improvement — confirmed the hypothesis — but still far
below viability.

### 1d. Fix #2 — staged exit ladder (full architectural mirror)

Explicit user instruction: don't stop at mirroring entry/stop/target
formulas, mirror the long side's staged profit-booking ladder too (long
RANGE positions exit in 25/25/25/trail legs; the short mirror had been
all-or-nothing). Added `exit_legs_json` to `signal_state_short`,
`_execute_staged_leg_exit_short`, wired `_split_exit_legs`/
`_next_unfilled_leg` (both reused as-is — direction-agnostic) into
`_short_signal_core`'s management loop.

| Metric | Fix #1 | Fix #2 |
|---|---|---|
| Trades | 96,127 | 173,120 |
| Win rate | 22.8% | 44.9% |
| PFnet | 0.26 | **0.21** |
| Cost drag | 98.9% | 103.6% |

Win rate nearly doubled (partial leg fills count as their own "wins") but
**PFnet went down, not up** — each staged leg is its own cover order
incurring its own round-trip cost, and the shallow early legs book small
moves that a fixed ~0.8% cost eats disproportionately. The ladder is a
faithful mirror of the live architecture, but doesn't fix the economics.

### 1e. Fix #3 — stricter entry filter (rule out "signal too noisy")

Tested bb_std ∈ {2.0 (live default), 2.5, 3.0} in one fair
multi-variant pass (same fetched data, three thresholds).

| bb_std | Trades | Win% | PFnet | Cost drag |
|---|---|---|---|---|
| 2.0 | 173,334 | 44.9% | 0.21 | 103.6% |
| 2.5 | 96,044 | 45.3% | 0.22 | 99.0% |
| 3.0 | 51,583 | 46.6% | 0.23 | 95.1% |

Barely moves. Trading only the most extreme spikes doesn't fix the core
economics.

**Conclusion on the RANGE family: not viable. PFnet never exceeded 0.26
across 5 variants (2 architectural fixes + 3 entry-strictness levels).**

## Part 2 — TREND-down momentum-continuation short

After the RANGE family was exhausted, the user asked for "at least one"
working short strategy and pushed back correctly when the entry-signal
mirroring was questioned: confirmed via explicit choice that "opposite
setup, same role" (short entry mirrors the long entry's setup; short exit
mirrors the long exit's conditions) was the right architecture, not a
swap of entry/exit roles.

TREND is the one long-side engine in this codebase with genuinely
positive validated evidence (PFnet 0.09–0.13,
`universal-score-entry-floor-research.yml`), unlike RANGE's much weaker
~0.06 blended PFnet. Built a full mirror:

- `_swing_structure_bearish`, `_relative_strength_bearish`,
  `_index_trend_bearish` — direct mirrors of the long side's bullish
  building blocks.
- `_compute_universal_entry_score_short` — the 8-factor bearish mirror of
  `_compute_universal_entry_score`. Every weight/threshold constant
  reused verbatim from the already-validated long side (never re-tuned).
  **One real mirroring bug caught by this build's own unit tests**: RSI
  is a bounded 0–100 oscillator, so the long side's RSI band (55, 70)
  needed to be REFLECTED around 50 (→ 30, 45) for the short mirror, not
  reused as the same absolute numbers — unlike the direction-agnostic
  volume/ATR/VWAP-extension checks, which are correctly identical in both
  directions.
- `_short_signal_core` extended from RANGE-only to a genuine two-regime
  router (mirroring `_auto_signal_core`'s own router): TREND entries use
  the bearish score; stop-loss switches to
  `min(structural_high, stop_loss_cap)` (structure-anchored, matching the
  long TREND side's basis, NOT the RANGE ATR-multiple basis); confidence
  switches to the score_pct itself. Target/staged-ladder machinery stays
  shared between both regimes.

`trend-short-validation-replay.yml`, same full-universe/real-function
discipline, reference index (`^NSEI`) fetched once per shard and sliced
per-bar to avoid lookahead.

| Metric | Value |
|---|---|
| Trades | 1,531 |
| Win rate | 31.4% |
| PFnet | **0.09** |
| PFgross | 1.08 |
| Avg net/trade | -₹581.85 |
| Cost drag | 145.3% |
| Skip breakdown | 7,758,493 not_trend_regime, 1,022,815 score_not_allowed, 267 cost_gate_failed |

Worse than every RANGE variant, and an extremely rare, thin signal (only
1,531 trades total across the full universe over 60 days — most
by-symbol samples n=2-4).

**Working theory for why**: the long side's TREND-continuation edge does
not mirror into a short. NSE names likely have grinding, persistent
uptrends but sharp, short-lived downdrafts (quick reversals,
short-covering, dip-buying) — momentum continuation is a structurally
weaker bet on the downside than the upside. Not something more tuning
fixes; a market-structure asymmetry.

## Part 3 — RSI-overbought mean-reversion fade

Third, genuinely distinct family (explicit user instruction: "RSI is
just one example, use whatever indicator or combination... I want a
successful short sell condition anyhow"). Classic "RSI>threshold →
overbought → short, expect pullback" — same broad category as Part 1
(fading an extreme), different technical trigger, not yet tried.

Research-stage only (`rsi-overbought-short-research.yml`) — the entry
trigger is new/inline research code since no such function exists in
`main.py` yet; everything else (stop-loss, target, staged ladder,
trailing stop, regime gate) reuses the real, already-validated
short-side functions. Gated to RANGE regime (classic theory: in a genuine
uptrend RSI can stay overbought a long time without reverting). Tested 4
thresholds in one fair multi-variant pass.

| RSI threshold | Trades | Win% | PFnet | PFgross | Cost drag |
|---|---|---|---|---|---|
| ≥65 | 239,530 | 44.0% | 0.22 | 1.38 | 100.5% |
| ≥70 | 151,543 | 44.0% | 0.21 | 1.30 | 99.5% |
| ≥75 | 92,159 | 44.1% | 0.21 | 1.25 | 98.6% |
| ≥80 | 52,442 | 44.3% | 0.21 | 1.21 | 97.7% |

Flat at 0.21–0.22 regardless of threshold — the same pattern as the
bb_std filter test in Part 1c: making the trigger rarer doesn't move
PFnet.

## Final verdict — three families, all failed

| Family | Mechanism | Best PFnet |
|---|---|---|
| VWAP mean-reversion (fade a spike) | Part 1 | 0.26 |
| RSI-overbought (fade extreme momentum) | Part 3 | 0.22 |
| TREND-down (ride a breakdown) | Part 2 | 0.09 |

All three cluster well below 1.0 breakeven. The two pure mean-reversion
variants (VWAP-deviation, RSI-extreme) land almost identically — not a
coincidence, the same underlying economics (small moves, cost-heavy
exits). The momentum approach is worse and rarer.

**Recommendation: do not pursue further short-entry variants without a
fundamentally different angle** (not a tuning tweak on any of the above
three). Three structurally different signal families, each tested
rigorously on the full 2,680-symbol universe with real transaction-cost
modeling, all converge on the same conclusion: short-selling via
technical entry signals does not have enough edge to clear NSE's
round-trip cost (~0.8%) on this universe, as currently built. This reads
as a real structural finding about Indian equity market asymmetry, not a
gap in effort or a parameter that needs one more nudge.

## Infrastructure notes (for future validation replays)

- **Matrix shard count**: this account's GitHub Actions concurrent-job
  ceiling is **40** — a 50-shard matrix reliably showed ~39-40 shards
  starting immediately and the rest queued for several minutes with zero
  work happening. 40 shards is the largest matrix that starts every shard
  at once; use that number directly for any future full-universe replay
  rather than re-discovering it.
- **Fair single-fetch-multi-variant pattern**: when testing several
  threshold/parameter variants of the same strategy, fetch each symbol's
  OHLCV data ONCE and replay it under every variant — never re-fetch per
  variant. This repo's own established convention (see also
  `universal-score-range-short-research.yml` from an earlier session).
- **Replay-driver-drift gotcha** (CLAUDE.md's own standing warning,
  reconfirmed twice this session): a validation replay must call the
  REAL, current `main.py` functions, not a separate reimplementation.
  Both times a `main.py` function changed (target-cluster fix, staged
  ladder), the companion workflow file needed an explicit update to call
  the new function — easy to forget, and a stale replay would have
  silently validated old behavior.
- **New workflow files require the isolation-merge technique** to be
  dispatchable via the GitHub Actions API: create a throwaway branch off
  `origin/main`, copy just the one workflow file into it, merge via
  `deploy-gate.yml`, then dispatch the actual workflow with
  `ref=<feature-branch>` so it runs the feature branch's real code.

---
*Written 2026-09-29, session `session_0145E5aZNLfLhKTLWftexiTX`.*
