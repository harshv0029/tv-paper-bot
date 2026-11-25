# View 6 fast plan (v3): evidence for every rule (B-1725, 2026-11-25)

Data: the repo's 5-min cache `docs/intraday/5m/` covering 89 NSE days, 2026-07-16 to 2026-11-23.
- Index proxies: NIFTYBEES for NIFTY, BANKBEES for BANKNIFTY, FINIETF for FINNIFTY (FINIETF is thin, with 9% zero-volume bars).
- Breadth: the NIFTY 50 stocks, each compared with its previous close.
- India VIX is not in the cache, so the VIX veto was not replayed.
- Script: `scripts/fno_v3_assumption_study.py`. Raw output: `docs/fno_v3_assumption_study.json`.

The study has two parts:
- **Part A** checks what the index does in the 15 minutes after each signal, in the trade's direction.
- **Part B** replays the whole plan on synthetic premiums, using Black-Scholes (`main._bs_price`) with a fixed IV (12/14/13%), an ATM strike, real days to expiry and a 0.8% round-trip cost.

Part B cannot test IV, OI, spreads or IV changes. Literature sources are listed at the end.

| Rule | Current | Evidence | Verdict |
|---|---|---|---|
| Strict day-direction gate | index and NIFTY ≥ ±0.25% on the day, index vs its open, breadth 1.5× | A: CE next 15 min +0.016%, hit rate 53.7% (n=2795); PE about 0. B: removing it drops the profit factor from 0.755 to 0.508. Literature: intraday momentum (Gao, Han, Li, Zhou, JFE 2018) is US only. | **Supported** (the one rule with an edge, and only for CE) |
| Breadth 1.5× | part of the gate | B: removing it lowers the profit factor (0.755 → 0.716; 0.806 → 0.780) | **Weakly supported** |
| 5-min index move ≥ 0.05% | entry | A: −0.0065% over the next 15 min, hit rate 44.3% (n=6609): short-term reversal. Adding it to the strict gate makes the result worse. B: removing it raises the profit factor (0.775 → 0.886 at 5%/15 min; 0.806 → 0.984 at 15%/60 min). | **Contradicted** |
| Time windows 09:30–11:15 and 13:15–14:30 | entry | A: after a 5-min move, the 11:15–13:15 hit rate is 41.5% vs 48.7% in the morning. B: mixed, depending on the exit (no windows: 0.785 vs 0.755, 0.735 vs 0.775, 0.973 vs 0.806). Literature: U-shaped volatility in NIFTY futures, lowest at 11–12 (Singh & Gangwar). | **Partly supported** (skipping midday helps momentum entries; the exact cut-off times are a guess) |
| Premium rising 5 min (0, 10%] and 15 min ≤ 20% | entry | B: mixed (no filter: 1.005 vs 0.755 at 2%; worse elsewhere). In this synthetic model the premium change is just the index move again. | **Unproven** |
| Trail 2% / 5% on the premium | exit | B: avg net −0.46% (2%) and −0.60% (5%) per trade. 96% of 2% exits are stop-outs, and the average peak gain is only 2.25%, so 2% of premium is inside normal 5-min noise. Wider trails do better (best: 25% trail with a 60-min hold, PF 1.006). Literature: under a random walk, stops cut returns (Kaminski & Lo 2014). | **Contradicted** (too tight) |
| 15-min time exit | exit | B: every 15-min variant has PF ≤ 0.81. 60 min or until 15:15 does better: with no trail, holding to 15:15 gives PF 1.105 (n=76), but that breaks the trailing-SL rule. | **Contradicted** (too short) |
| Sentiment-flip exit (loose) | exit | B: removing it changes nothing; the stricter version is worse (0.751 vs 0.755; 0.785 vs 0.806). The 0–0.25% "dead zone" costs nothing. | **Neutral** (keep as is) |
| Delta 0.40–0.60 | entry | Not testable here. In S&P options, ATM straddles lose about 3%/week and puts 8–9%/week, so OTM options are worse for buyers (Coval & Shumway 2001). | **Indirectly supported** (source) |
| IV ≤ 1.25× chain median | entry | Not testable here. Implied vol exceeds realized vol in India (Jain, Varma & Agarwalla 2019). NIFTY sellers' premium is mostly overnight risk (Bhat, Pandey & Rao 2024). Nothing backs the 1.25 figure. | **Direction supported, number assumed** |
| Premium ≥ ₹20 | entry | Tick ₹0.05: one tick is 0.25% at ₹20 vs 5% at ₹1 (NSE circular). No upper cap. | **Supported as a cost floor** |
| CE VIX veto (day change < +5%) | entry | Not replayed (no VIX data). NIFTY returns are negatively related to VIX changes (NSE WP9). | **Direction supported, number assumed; PE missing** |
| OI and theta | recorded only | The price × OI quadrant labels are broker heuristics with no empirical test (Economies 2019 tests only aggregate OI). | **No evidence**; keep for review |
| Base rate | — | SEBI: 91% of individuals lost money in F&O in FY24, and options drove 92% of losses. Option sellers had the only positive median return. | Buying edge must be proven, not assumed |

Caveats:
- 89 days is one market regime.
- The ETFs are proxies for the indices.
- The synthetic premium holds IV fixed and ignores spreads.
- Part A signals overlap from bar to bar, so its significance is overstated by about 2×.
- Nothing here changes a real-money rule.

Sources:
- Singh & Gangwar: https://mpra.ub.uni-muenchen.de/89689/
- Gao, Han, Li & Zhou (2018): https://econpapers.repec.org/RePEc:eee:jfinec:v:129:y:2018:i:2:p:394-414
- Coval & Shumway (2001): https://econpapers.repec.org/RePEc:bla:jfinan:v:56:y:2001:i:3:p:983-1009
- Bakshi & Kapadia (2003): https://econpapers.repec.org/RePEc:oup:rfinst:v:16:y:2003:i:2:p:527-566
- Jain, Varma & Agarwalla (2019): https://www.jrvarma.in/blog/Y2018-19/smile-paper.html
- Bhat, Pandey & Rao (2024): https://ideas.repec.org/a/wly/jfutmk/v44y2024i8p1320-1337.html
- Muravyev & Ni (2020): https://ideas.repec.org/a/eee/jfinec/v136y2020i1p219-238.html
- NSE Working Paper 9: https://nsearchives.nseindia.com/research/content/res_WorkingPaper9.pdf
- Kaminski & Lo (2014): https://dspace.mit.edu/handle/1721.1/114876
- OI and NIFTY returns (Economies 2019): https://mdpi-res.com/d_attachment/economies/economies-07-00024/article_deploy/economies-07-00024.pdf
- SEBI F&O study (Sep 2024): https://www.sebi.gov.in/media-and-notifications/press-releases/sep-2024/updated-sebi-study-reveals-93-of-individual-traders-incurred-losses-in-equity-fando-between-fy22-and-fy24-aggregate-losses-exceed-1-8-lakh-crores-over-three-years_86906.html
- SEBI F&O study (Jul 2025): https://www.sebi.gov.in/sebi_data/attachdocs/jul-2025/1751900271726.pdf
- NSE tick-size circular: https://nsearchives.nseindia.com/content/circulars/FAOP67135.pdf
- SEBI figures came from search summaries, because the SEBI site was not reachable from this session.

## Correction and short-horizon sweep (B-1727, 2026-11-25 16:05 IST)

**Correction.** Part B used to fill a stop exactly at the stop price, even when the next 5-min bar opened through it. Gap-aware fills now use min(stop, bar-open premium). Every trend in the table above still holds; the levels are lower:

| Configuration | Before | After |
|---|---|---|
| Live 2% trail, 15-min hold | PF 0.755 | PF 0.417 (n=387, avg −1.42%) |
| Live 5% trail, 15-min hold | PF 0.775 | PF 0.631 |
| No strict gate (5%, 15 min) | — | PF 0.518 (live 0.631) |
| No breadth | — | PF 0.602 |
| No 5-min index move | — | PF 0.707 (better than live) |
| No windows | — | PF 0.571 (worse than live) |

5-min bars overstate gaps compared with the live 30-s checks, so the true figure lies between the two. Only the recorded 30-s paths from B-1719 can settle it.

**Short-horizon sweep.** The user's constraint: short movement only, quick entry, quick exit, single leg. The sweep covered:
- Holds of 5, 10 and 15 min.
- Trails of 2, 5, 8 and 12%.
- Targets of none, 3, 5, 8 and 12%.
- Three entries: momentum, momentum without the 5-min move, and **pullback**. Pullback means the strict trend-day gate holds and the last 5 min moved at least 0.05% *against* it.

Results:
- 13 of 180 configurations reach PF > 1, and all of them are pullback.
- Best: pullback, 15-min hold, 12% trail, 12% target: PF 1.052 (n=278, avg +0.16%).
- Pullback with a 2% trail and 10-min hold looked like PF 1.705 before the gap fix and is PF 1.023 after it.

The edge is not robust:
- It comes only from FINNIFTY, whose proxy FINIETF is thin and shows stale-price reversals.
- NIFTY gives PF 0.58 and BANKNIFTY 0.74 (2% trail, 10 min).
- It flips between the two halves of the sample (H1 1.23, H2 0.93).

Verdict: no quick-trade configuration shows an edge after the 0.8% cost on NIFTY or BANKNIFTY at 5-min resolution. A pullback entry is the only direction worth a paper trial.
