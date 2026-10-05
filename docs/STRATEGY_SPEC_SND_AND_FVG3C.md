# Spec: Supply & Demand zones (B-33) and FVG 3rd-candle classification (B-32)

Gap-filling research, 2026-10-05, for two user-supplied strategies whose sources
omit every quantitative parameter. **Everything below is a CANDIDATE SWEEP GRID,
not a validated setting.** Values come from common open-source TradingView
implementations and Sam Seiden's published method; none has been backtested on
this universe. Per CLAUDE.md: no blind picks, full-universe validation calling the
real `main.py` functions, both directions, every variant its own tag
(`<family>__<variant>__<dir>__<tf>__<params>__v<N>`), register pass or fail.

Sources: [TradingView S&D scripts](https://www.tradingview.com/scripts/supply-and-demand/),
[Svopex S&D Scan](https://www.tradingview.com/script/Jywsoivw-Svopex-S-D-Scan/),
[LuxAlgo S&D zones](https://www.luxalgo.com/library/concept/supply-and-demand-zones/),
[Sam Seiden odds enhancers](https://forums.babypips.com/t/odd-enhancers-sam-seiden/39321),
[FVG Signals (Kodexius)](https://www.tradingview.com/script/R7DRiW77-Fair-Value-Gap-Signals-Kodexius),
[FVG Trade Entries](https://www.tradingview.com/script/QyK1xxgo-FVG-Trade-Entries/).

## B-33 Supply & Demand (family `snd_zone`)

Variants: `demand_retest` (long) and `supply_retest` (short); a mirror is a
separate strategy, never a flag.

Definitions (from the user's text + the sources):
- **Base**: 1..N consecutive candles with small body and wicks larger than body
  (user's rule) - formalised as body <= `bb` x ATR(14) AND wick_total > body.
- **Explosive leg**: the candle right after the base, body >= `ex` x ATR(14), in the
  zone's direction (up for demand, down for supply).
- **Zone**: high/low of the base candles; proximal edge = the edge nearest price,
  distal = the far edge.
- **Seiden formations**: demand = rally-base-rally or drop-base-rally; supply =
  drop-base-drop or rally-base-drop. Test formation as a split axis (continuation
  vs reversal) rather than pooling.
- **Freshness / confirmation**: zone becomes active only after price has left it
  for `cf` bars without re-entering; `rt` = max retests before expiry (1 = fresh only).
- **Invalidation**: close beyond the distal edge (below demand / above supply).
- **Strength score** (optional filter): body/ATR x (volume / 20-bar avg volume).

| Axis | Candidate values |
|---|---|
| base candles N | 1, 2, 3 |
| base body `bb` (x ATR14) | 0.3, 0.5, 0.7 |
| explosive body `ex` (x ATR14) | 1.0, 1.5, 2.0 |
| volume surge on explosive leg | off, >= 1.0x, >= 1.5x of 20-bar avg |
| confirm bars away `cf` | 1, 3, 5 |
| retests allowed `rt` | 1, 2, 3 |
| entry | limit at proximal edge; close-confirm inside zone |
| stop | distal edge + {0, 0.25, 0.5} x ATR |
| target | fixed R {1.5, 2, 3}; ATR trailing (reuse repo chandelier); time stop |
| formation | continuation, reversal, pooled-as-separate-rows |
| timeframe | 5m, 15m, 1h, 4h, 1d |

Tractability: the full cross-product is large. Stage 1 = coarse sweep on
{N, bb, ex, entry, stop} at fixed defaults for the rest; Stage 2 = refine around
Stage-1 winners. Any narrowing is reported plainly, never silent.
Preference among viable results: shorter average hold (faster turnover).

## B-32 FVG 3rd-candle classification (family `fvg3c`)

Variants (each its own strategy, each both directions): `breakaway`,
`rejection`, `valid_retest`. Video logic is bearish; the bullish mirror is tested
as its own `long` strategy.

Definitions:
- **FVG (bearish)**: candle3.high < candle1.low; gap = [candle3.high, candle1.low].
  (bullish: candle3.low > candle1.high; gap = [candle1.high, candle3.low]).
- **Breakaway**: candle3 BODY closes outside candle2's high-low range -> no retest expected.
- **Rejection**: candle3 is a strong candle against the trade side (video: strong
  bearish) -> gap invalidated for the retest trade.
- **Valid**: candle3 body closes inside candle2's range, then consolidation, then
  retest of the gap, then confirmation trigger.
- **Lifecycle** (from the sources): fresh -> testing -> tested/rejected.

| Axis | Candidate values |
|---|---|
| min gap size | 0.1, 0.25, 0.5 x ATR14 |
| strong candle3: body / range | 0.6, 0.7, 0.8 |
| candle3 body > candle2 body | on / off |
| consolidation after candle3: bars | 2, 3, 5 |
| consolidation max range | 1.0, 1.5 x ATR14 |
| max bars to wait for retest | 10, 20, 50 |
| entry level | gap proximal edge; gap midpoint (50%) |
| confirmation trigger | rejection wick > body; bearish engulfing; close back below gap midpoint |
| stop | beyond gap distal edge + {0, 0.25} x ATR |
| target | fixed R {1.5, 2, 3}; ATR trailing; time stop |
| timeframe | 5m, 15m, 1h, 4h, 1d |

Same staged tractability rule as above. `breakaway` is tested as a continuation
trade (enter on momentum in the gap direction), since its premise is "no retest".
