# Dispatch plan for the unmatched waiting rows (B-1140)

Generated 2026-10-14 IST by the B-1140 reconcile. Ordering follows the CLAUDE.md dispatch-urgency rule: Deploy Gate and real-money safety/profit path first, small single-job runs next, big matrices last (one running + one queued, matrix size counts). Rows are never deleted; each row in `docs/ACTIONABLES_BACKLOG.md` carries a matching `Owed (B-1140 plan ...)` line. Close a row only with run id plus registered tags. All times IST.

## Tier 1: safety/live-verification (Deploy Gate + Kotak audits), first (52)

| Row | Workflow / step | Inputs / action | Size |
|---|---|---|---|
| B-46, B-69, B-288, B-289, B-333, B-338, B-360, B-391, B-392, B-393, B-394, B-399, B-400, B-401, B-402, B-404, B-405, B-408, B-409, B-410, B-411, B-415, B-417, B-419, B-816, B-817, B-867 | deploy-gate.yml (user go-ahead 'deploy X' only), then live check | after deploy: open trade-view / scan banners and confirm the behaviour in the row; then close with evidence | 1 job |
| B-292, B-293, B-294, B-302, B-304, B-305, B-306, B-307, B-308, B-312, B-313, B-315, B-321, B-369 | kotak-sl-snapshot.yml + kotak-pnl-audit.yml | no inputs; run after a market session, compare Kotak order/trade book to app rows, then close with the run id | 1 job each |
| B-344, B-345, B-347, B-355, B-362 | deploy-gate.yml then mcx-live-replay.yml | deploy, confirm first MCX daily scan on the live banner; mcx-live-replay.yml (no inputs) compares live cells to the stored mcx_sweep_results | 1 job |
| B-349, B-350, B-352, B-353, B-354, B-356 | deploy-gate.yml, then first daily swing scan | confirm the wired cells open paper trades and the SL appears in kotak-sl-snapshot.yml; cell numbers vs registry via scripts/gen_strategy_results_log.py | 1 job |

## Tier 2: small single jobs, probes and code steps (14)

| Row | Workflow / step | Inputs / action | Size |
|---|---|---|---|
| B-366, B-388 | intraday-collect.yml | scheduled recorder: confirm it stores n200 5m candles and Kotak depth to durable storage; extend recorder in main.py is code work | 1 job + code |
| B-420 | code step: scripts/gen_strategy_results_log.py + docs only | complete missing win%/hold fields for gap_and_go_swing and minervini_trend_template_generic_br* from the run artifacts in docs/backtest_data; no workflow | docs |
| B-456 | code step then chan-research.yml | restrict short replays to the MIS-shortable symbol list (needs a stored list file), then dispatch chan-research.yml | matrix |
| B-536, B-542 | main.py code step (no workflow) | rule-tag enum on every exit (B-536); per-20-trade parameter freeze/versioning (B-542); tests; then Deploy Gate | code |
| B-749, B-756, B-757 | code step in options_pricing.py / main.py (no workflow yet) | compute IV and delta from fetched OI/price (B-755 first), then intraday OI via Kotak quotes; gated by B-752..B-755 | code |
| B-752 | kotak-holdings-probe.yml / kotak-limits-probe.yml (or a new one-off logger) | dump one raw Kotak quotes() payload for an index option strike and check for oi/greeks fields; store as docs/backtest_data sample | 1 job |
| B-753 | fetch-chart-data.yml | symbols=^INDIAVIX,^NSEI interval=1d period=5y; then code step: daily VIX persist table (generic mirror) | 1 job |
| B-754, B-755, B-758 | diag-curl.yml (runner-side URL test), then code step | test the NSE participant OI / UDiFF bhavcopy / option-chain URLs from an Actions runner (sandbox gets 403); on success build a daily fetch job and persist to the generic mirror | 1 job + code |

## Tier 3: research matrices, LAST, only when no gate/safety run is queued (72)

| Row | Workflow / step | Inputs / action | Size |
|---|---|---|---|
| B-357 | fo-futures-backtest-research.yml | short direction, 1d and 1h; blocked until a short cell clears 1.1 | matrix |
| B-358 | elder-patterns-research.yml | interval=1h/730d, 15m/60d; no 1h/15m variant cleared 1.1 yet | matrix |
| B-359 | fo-options-blackscholes-backtest-research.yml | premium-chart backtest per strike once shadow history exists (needs B-366/388 recorder data first) | matrix |
| B-421 | confidence-threshold-sweep-research.yml | sweep min_entry_confidence 0,50,60,70,80,90,95 per category and direction through real main.py entry fns | matrix |
| B-424, B-425 | chan-nonoverlap.yml | intervals=["4h"] (B-991) and a one-bar verify of the gap cells via chan-gap-main-replay.yml / chan-gap-short-main-replay.yml | matrix |
| B-460, B-461, B-462, B-463, B-464, B-465 | oneil-research.yml (also oneil-ext-research.yml) | pattern cells (pivot, base, cup, saucer, double-bottom) 1d+1w full universe, both directions, ATR 1.5/2/3; then oneil-nonoverlap.yml | matrix |
| B-627 | build-sector-map.yml, then elder-batch3-research.yml | sector map first, then related-market catch-up family | 1 job then matrix |
| B-634 | elder-batch3-research.yml | families=["breadth"], interval=1d | matrix |
| B-643 | elder-indicators-research.yml | family=roc; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix 4 shards x family |
| B-647, B-648, B-649, B-725, B-764 | elder-indicators-research-ext.yml | family=williams_r; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix 3 shards x family |
| B-650, B-651, B-652, B-654, B-655, B-724, B-765 | elder-indicators-research-ext.yml | family=stoch_slow; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix 3 shards x family |
| B-653 | elder-indicators-research.yml | family=stoch_filter; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix 4 shards x family |
| B-658, B-659, B-660, B-726 | elder-indicators-research-ext.yml | family=rsi; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix 3 shards x family |
| B-663, B-664, B-665 | elder-indicators-research-ext.yml | family=volume; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix 3 shards x family |
| B-667 | elder-indicators-research.yml | family=obv; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix 4 shards x family |
| B-668, B-669, B-729 | elder-indicators-research-ext.yml | family=ad_line; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix 3 shards x family |
| B-674, B-700, B-701, B-702, B-703, B-759 | elder-indicators-research.yml | family=triple_screen; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix 4 shards x family |
| B-675, B-723, B-769 | elder-indicators-research-ext.yml | family=macdh; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix 3 shards x family |
| B-694, B-695, B-696, B-762 | elder-indicators-research.yml | family=elder_ray; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix 4 shards x family |
| B-697, B-698, B-699, B-763 | elder-indicators-research-ext.yml | family=force_index; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix 3 shards x family |
| B-705 | elder-indicators-research-ext.yml | family=parabolic; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix 3 shards x family |
| B-708 | elder-indicators-research.yml | family=ema13,ema_gate; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix 4 shards x family |
| B-709 | elder-macd-dirgap-research.yml | generic divergence across oscillators; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix |
| B-716, B-717, B-718, B-719, B-766 | elder-indicators-research-ext.yml | family=channel; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix 3 shards x family |
| B-732 | elder-macd-dirgap-research.yml (gaps family) | gap types breakaway/common/continuation/exhaustion/island; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix |
| B-738, B-739, B-770 | elder-indicators-research-ext.yml | family=profit_protect; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix 3 shards x family |
| B-760 | elder-indicators-research.yml (adx_bell) + elder-dirsys-di13-research.yml | family=adx_bell with 13-EMA smoothing; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix |
| B-761 | macd-divergence-research.yml | Class A/B/C + triple divergence; interval=1h period=730d first, then 15m and 5m (period 60d); 4h owed (1h resample) | matrix |
| B-784 | oneil-replay.yml + chan-research.yml | true full universe via _load_nse_universe_from_file(); compare to NIFTY200+ETF mix numbers | matrix |
| B-789 | island-main-replay.yml | after porting the island detector into main.py (code step first); replay via real functions | matrix |

## Tier 4: parked (no runnable test; data or discipline rule) (43)

| Row | Workflow / step | Inputs / action | Size |
|---|---|---|---|
| B-437, B-438, B-446, B-503, B-505, B-511, B-512, B-520, B-521, B-522, B-523, B-524, B-525, B-526, B-563, B-575, B-576, B-577, B-578, B-635, B-636, B-637, B-638, B-639, B-640, B-671, B-672, B-686, B-687, B-688, B-689, B-690, B-691, B-692, B-693, B-711, B-712, B-713, B-714, B-715, B-730, B-747, B-748 | none runnable (data not available / non-mechanical) | PARKED by priority, not dropped: needs a data source or is a discipline rule, not a testable signal; unblock via B-749..B-758 data pipeline where it applies | - |

## closed with evidence (3)

| Row | Workflow / step | Inputs / action | Size |
|---|---|---|---|
| B-19 | closed | row text already records closure 2026-10-11: B-285 diagnosis run 37597298660 shows the SL resting at Kotak; earlier rejection was 'Adapter is Logged Off' (B-302), not T1 | - |
| B-47 | closed | row text: decision part resolved by B-52, Deploy Gate #340 (bf59242) merged; B-52 states 'Closes B-47' | - |
| B-396 | closed | B-399 row states 'Closes B-396' and delivers the same banner items (MCX scan state, ALL TRADING state, 5-min SL backcheck age, strike shadow count, wired vs gated counts); remaining live check is tracked in B-399 | - |
