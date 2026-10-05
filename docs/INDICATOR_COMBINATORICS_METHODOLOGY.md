# Indicator Combinatorics Methodology — standing thumb rule (2026-10-05)

Explicit user instruction, verbatim intent preserved here as the working
spec for all future strategy research in this repo. This is a **standing
thumb rule**, not a one-time research pass — CLAUDE.md's own "say so
plainly" / "never tune blind" / "full universe, never a sample" / "check
both directions" / "candle-size sweep" / "never silently merge
differently-named things" disciplines all still apply on top of everything
below; this document is the *shape* of the search, not a replacement for
any of CLAUDE.md's existing real-money rules.

## The core idea, in the user's own words (2026-10-05)

> Collate all indicators at one place and make its repository. Now suppose
> u have 3 indicators a b and c. Now u check for all variants of a by
> changing all variety like all factors inside it back n forth and use
> this as a strategy to backtest. Same do for b and c separately. And if
> any qualify then add to viable list with strategy category.
>
> Now step 2: Combine various variants of A and b to compose new strategy
> like suppose 4 variant of a and 5 variant of b then it tests 5P4
> permutation, and backtest each one. Similarly do for b and c, and a and
> c.
>
> Next step: Combine a b c as combinations in all variants to backtest.
> Multi timeframe should be done and backtest.
>
> Now suppose next time u read next book, a new indicator found, say d.
> Now u check d as standalone indicator and backtest with all its variants
> separately. Then A and d, then B and d, then C and d, then A b d, then A
> c d, then B c d, then A b c d. All these in all variations, in all
> permutations, in all time frames.
>
> So in this way if u get new strategy then backtest it. If u get new
> indicators then make them usable like this and design ur own strategy.

## 1. What "the Indicator Repository" already is in this codebase

This repo does **not** need to start from zero — most of the raw material
already exists as atomic, independently-parameterized single-indicator
branches inside `main.add_strategy_signal(df, strategy, params)`. Each one
takes a `params` dict and is a self-contained indicator signal with its own
internal factors (period, multiplier, threshold, etc.) — exactly the "a, b,
c" units this methodology combines. Confirmed by grep of every distinct
`elif strategy == "..."` branch in `add_strategy_signal` (2026-10-05):

| Indicator (strategy tag) | Internal factors (the "variants" to sweep) |
|---|---|
| `rsi_reversal` | RSI period, overbought/oversold thresholds |
| `rsi_divergence` | RSI period, divergence lookback |
| `macd_cross` | fast/slow/signal periods |
| `bollinger_mean_reversion` | period, std-dev multiplier |
| `supertrend` | ATR period, ATR multiplier |
| `cci_breakout` | CCI period, breakout threshold |
| `stochastic_oversold_reversal` | %K/%D periods, oversold threshold |
| `keltner_channel_breakout` | EMA period, ATR multiplier |
| `donchian_breakout` | channel lookback |
| `vwap_reclaim` / `vwap_mean_reversion` / `vwap_breakout_retest` / `vwap_multi_period_reversal` | VWAP anchor period, deviation tolerance |
| `heikin_ashi_vwap` | smoothing/lookback factors |
| `bullish_engulfing` / `mtf_engulfing` | body/wick ratio thresholds, HTF bucket size |
| `inside_bar_breakout` | lookback bars |
| `pin_bar_reversal` | `pin_ratio`, `sr_lookback`, `sr_tolerance_pct` (already S/R-aware) |
| `fair_value_gap` | `fvg_displacement_atr_mult`, `fvg_volume_mult`, `fvg_expiry_bars` |
| `sweep_engulf_retracement_v1` | sweep/retracement tolerances |
| `vsa_climax_reversal` | volume climax multiplier, spread thresholds |

Plus standalone (outside `add_strategy_signal`) atomic/near-atomic signal
functions built across this session that belong in the same repository
conceptually, each with its own factor grid: `minervini_vcp` family
(pivot/base-tightness constants), `gap_and_go`, `idea4`, `power_play`,
`primary_base`, order-block delta-weighted entry
(`order-block-delta-research.yml`), Volume Profile/POC
(`volume-profile-poc-liquidity-research.yml`), and the short mirrors of
each of the above.

**Going forward, every new indicator (from a book, a web search, a named
TA concept) gets added to this same catalog** — as a real
`add_strategy_signal` branch when it's genuinely a single-indicator signal
reusable by `/backtest`/`/sweep` too, or as a standalone research-stage
function (research workflow first, promoted to `main.py` only once
validated) when it needs bespoke mechanics `add_strategy_signal`'s generic
shape doesn't fit (e.g. order-block delta, volume profile).

## 2. Step 1 — standalone validation (per indicator, every variant)

For each indicator `X` in the catalog:

1. Enumerate `X`'s **full parameter grid** — not two or three eyeballed
   values, every meaningfully distinct combination of its own internal
   factors (within a sane, documented range — e.g. RSI period ∈
   {7,9,14,21}, thresholds ∈ {(20,80),(25,75),(30,70)} is a 12-variant
   grid, not 2-3 cherry-picked points).
2. Wrap **each variant** in this repo's standard cost-aware, risk-sized
   exit management (ATR initial stop + chandelier trail + max-hold
   timeout — the same shape used by every research workflow this session:
   `order-block-delta-research.yml`, `fair-value-gap-full-universe-
   validation.yml`, `pin-bar-reversal-full-universe-validation.yml`,
   `volume-profile-poc-liquidity-research.yml`) — never the generic
   gross-only `extract_trades_fast` pipeline for anything that will inform
   a real go/no-go call.
3. Full-universe validate **each variant separately**
   (`main._load_nse_universe_from_file()`, never a sample) — **both
   directions** (long and the short mirror) per the standing both-
   directions rule, and across the standing candle-size sweep (1m, 5m,
   15m, 1h, 4h, plus the indicator's own natural timeframe e.g. 1d) where
   the indicator's own constants are bar-size-agnostic.
4. **Every variant gets its own distinct tag** — e.g.
   `rsi_reversal__p14_ob70_os30`, `rsi_reversal__p9_ob75_os25` — never
   pooled into one "rsi_reversal" number. This is the 2026-10-05
   no-silent-merge rule applied at combinatorial scale: a different
   parameter set is a different variant until proven redundant, and
   "redundant" is never assumed, only shown.
5. Report every variant's real metrics honestly, pass or fail. Any
   variant clearing `PFNET_LIVE_FLOOR` gets registered in
   `strategy_registry.py` under whichever category(ies) its own validated
   mechanics actually support (per the existing "not confined to one
   `TradeCategory`" rule) — a failing variant is still recorded (per the
   existing "every strategy tried is record-worthy" rule), never omitted
   for looking bad.

## 3. Step 2 — pairwise combination

Once two indicators `A` (with `m` validated variants from Step 1) and `B`
(with `n` variants) both have a Step-1 record (passing or not — a
combination can unlock an edge neither shows alone, so Step-1 failure does
not disqualify an indicator from Step 2):

- The user's "5P4 permutation" framing means **role matters, not just
  which variants are paired** — e.g. "A triggers, B confirms/filters" is a
  different strategy from "B triggers, A confirms/filters" even with the
  identical variant pair. So Step 2 tests, for every `(A-variant,
  B-variant)` pair in the `m × n` cross product, **both role orderings**:
  - A-variant as entry trigger, B-variant as a confirmation/regime filter
    on that trigger.
  - B-variant as entry trigger, A-variant as the filter.
- Exit management, universe, both-directions, and candle-size sweep rules
  are identical to Step 1, applied to the combined signal.
- Do this for every unordered pair drawn from the current indicator pool
  (A-B, A-C, B-C, …) — not just one arbitrarily chosen pair.
- Tag convention: `combo__A=<A-tag>__B=<B-tag>__trigger=A` (and the
  `trigger=B` mirror) — again, every distinct combo is its own row, never
  merged with a sibling ordering or variant pairing.

## 4. Step 3 through Step N — triple, quadruple, ... all the way to the full pool, multi-timeframe

**Explicit clarification (2026-10-05, explicit user instruction): this
progression is NOT capped at "triple."** For an indicator pool of size
`N`, the methodology runs **Step `k` for every `k` from 1 to `N`** — every
combination SIZE, not just 1 (standalone), 2 (pairwise), and 3 (triple).
Step `k` tests every `k`-sized subset of the current `N`-indicator pool
(`C(N,k)` subsets), each subset tested across its own role-assignment
permutations (which member is the trigger, which members are
confirmation/filter layers — `k` permutations per subset, one per choice
of trigger), each permutation across the full variant cross-product of
its `k` members, each across the standing timeframe sweep. Step `N`
itself — all `N` indicators combined at once — is the final, largest cell
of this grid, not a special case stopped short of.

Concretely, with a 3-indicator pool (`A, B, C`): Step 1 is the 3
standalone indicators (already covered above), Step 2 is the 3 pairs
(`A+B`, `A+C`, `B+C`), and Step 3 — the full pool — is the single triple
`A+B+C` (3 trigger-role permutations: A-triggers, B-triggers, or
C-triggers, each with the other two as filters). With a 4-indicator pool
(after adding `D`, see the growth rule below), Step 3 additionally covers
every triple that includes `D` (`A+B+D`, `A+C+D`, `B+C+D`, alongside the
original `A+B+C`), and a NEW Step 4 appears — the full 4-indicator
combination `A+B+C+D`. Every time the pool grows by one indicator, the
grid gains both new cells within existing steps AND one new top step
(Step `N`) for the newly-larger full combination.

This is where "multi timeframe should be done" applies most concretely at
every step `k >= 2`: a multi-indicator combo is a natural place to let
each layer read its *own* timeframe (e.g. a 1d regime filter + a 1h
trigger + a 5m entry-timing layer) in addition to sweeping all `k`
members at one shared timeframe — both are worth testing and are
honestly different strategies, tagged separately.

## 5. Growth rule — adding a new indicator to an existing pool

When a new indicator `D` is found (new book, new PDF, new research), it
is **never** tested only against the strategies that happen to be
convenient — it is run through the full recursive pipeline against the
**entire existing pool**, at every step size `k`, not stopped at triples:

1. `D` standalone, all its own variants (Step 1).
2. `D` paired with **every existing individual indicator**: `A+D`,
   `B+D`, `C+D` (Step 2, both role orderings each).
3. `D` added to **every existing validated pair**, forming every triple
   that includes `D`: `A+B+D`, `A+C+D`, `B+C+D` (Step 3) — alongside the
   pre-existing `A+B+C` triple, which was already Step N before `D`
   arrived and now sits one step below the new top.
4. `D` added to the full existing pool: `A+B+C+D` — this becomes the
   new Step N (N=4) now that the pool has grown.

Formalized for a pool of size `N` gaining an `(N+1)`th indicator: the new
indicator must be tested standalone, then combined with **every non-empty
subset of the existing `N`-indicator pool** (its own entry across the
power set recursion) — i.e. `2^N` new combination-strategies get tested
for every single new indicator added to an `N`-indicator pool. This is
exponential by construction and is flagged here explicitly, not hidden:
practical execution will need to **prioritize** which subsets get tested
first (most natural ordering: subsets whose members already cleared
`PFNET_LIVE_FLOOR` individually, before subsets built entirely from
Step-1 failures) rather than mechanically grinding the full power set in
numeric order — any such prioritization is a scoping choice to be
surfaced plainly when made, never a silent narrowing of the rule itself.

## 6. What stays unchanged from existing CLAUDE.md discipline

Every rule already standing in `CLAUDE.md` applies to every variant,
combo, and timeframe cell in this grid, with no exceptions carved out
here:
- Real `main.py`/live functions wherever the mechanic already exists;
  fresh, disclosed research code only for genuinely new mechanics.
- Full NSE universe (`_load_nse_universe_from_file()`), never a sample,
  for any number that will inform a go/no-go call.
- Cost-aware, R-multiple-sized exits — never the generic gross-only
  backtest pipeline for a real viability number.
- Both directions (long + short mirror) checked for every variant/combo.
- Candle-size sweep (1m/5m/15m/1h/4h + natural timeframe) where the
  indicator's constants are bar-size-agnostic; honestly flagged as a
  separate follow-up where they are not (bar-count/day-based constants).
- Never tune blind off one result — a sweep across variants, as specified
  here, *is* the sanctioned structured alternative to blind tuning, not
  an exception to the rule against it.
- Every strategy/variant/combo tried gets registered in
  `strategy_registry.py` with its real metrics, pass or fail.
- `PFNET_LIVE_FLOOR` (1.0) gates any NEW real-money position, permanently
  and automatically, regardless of how a strategy/variant/combo was
  discovered.
- Faster capital turnover is the standing tie-break among
  comparable-or-better variants/combos.
- A different tag/name (variant, role ordering, combo) is never silently
  treated as the same thing as another — the 2026-10-05 no-silent-merge
  rule, now explicitly extended to this entire combinatorial search.

## 7. Where this is tracked

- This file: the standing methodology/spec.
- `strategy_registry.py`: the actual pass/fail record for every
  variant/combo tried, per category, per the existing registry
  discipline.
- `docs/daily_logs/`: narrative research-session notes (existing
  convention), one entry per research pass through this pipeline.
- `.github/workflows/*-research.yml` / `*-validation-replay.yml`: the
  actual dispatchable full-universe validation jobs, one per
  variant-sweep or combo batch, following the existing naming and
  disclosure conventions already established this session.
