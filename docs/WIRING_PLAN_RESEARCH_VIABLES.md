# Wiring plan: research-only viable strategies (B-779b)

Derived from `strategy_registry.REGISTRY`; regenerate with `python3 scripts/research_wiring_plan.py`.
Gate: viable (PFnet >= floor), n >= 300, hold <= 30 trading days. Rank = PFnet per day held.
Each needs a main.py-calling replay (B-776) and a live entry path that always attaches a stop before any real order.

Candidates: 291; excluded (reason kept): 346

| # | tag | PFnet | win % | n | hold d | PFnet/day | categories |
|---|---|---|---|---|---|---|---|
| 1 | `chan_kalman__band__long__5m__atr4d0_hold40_ve10d0e4_z1d0_fl1515__v2` | 1.780 | 46.8 | 5722 | 0.1 | 17.80 | buy |
| 2 | `chan_kalman__band__long__5m__atr4d0_hold40_ve10d0e4_z1d0__v1` | 1.682 | 46.1 | 6190 | 0.1 | 16.82 | buy |
| 3 | `chan_kalman__band__long__5m__atr2d5_hold40_ve10d0e4_z1d0_fl1515__v2` | 1.625 | 46.1 | 5792 | 0.1 | 16.25 | buy |
| 4 | `chan_kalman__band__short__5m__atr2d5_hold40_ve10d0e4_z2d0_fl1515__v2` | 1.616 | 57.3 | 1014 | 0.1 | 16.16 | short_sell |
| 5 | `chan_kalman__band__short__5m__atr2d5_hold40_ve10d0e4_z2d0__v1` | 1.611 | 56.9 | 1057 | 0.1 | 16.11 | short_sell |
| 6 | `chan_kalman__band__long__5m__atr2d5_hold40_ve10d0e4_z1d0__v1` | 1.542 | 45.5 | 6270 | 0.1 | 15.42 | buy |
| 7 | `chan_kalman__band__short__5m__atr4d0_hold40_ve10d0e4_z2d0__v1` | 1.671 | 59.8 | 1030 | 0.1 | 15.34 | short_sell |
| 8 | `chan_kalman__band__long__5m__atr1d5_hold40_ve10d0e4_z1d0_fl1515__v2` | 1.533 | 44.3 | 5903 | 0.1 | 15.33 | buy |
| 9 | `chan_kalman__band__short__5m__atr4d0_hold40_ve10d0e4_z2d0_fl1515__v2` | 1.671 | 60.2 | 988 | 0.1 | 15.05 | short_sell |
| 10 | `chan_kalman__band__short__5m__atr1d5_hold40_ve10d0e4_z2d0__v1` | 1.468 | 49.5 | 1081 | 0.1 | 14.68 | short_sell |
| 11 | `chan_kalman__band__long__5m__atr1d5_hold40_ve10d0e4_z1d0__v1` | 1.467 | 43.6 | 6385 | 0.1 | 14.67 | buy |
| 12 | `chan_kalman__band__short__5m__atr1d5_hold40_ve10d0e4_z2d0_fl1515__v2` | 1.466 | 49.7 | 1038 | 0.1 | 14.66 | short_sell |
| 13 | `chan_kalman__band__long__5m__atr1d5_hold40_ve10d0e4_z2d0_fl1515__v2` | 1.426 | 44.1 | 442 | 0.1 | 14.26 | buy |
| 14 | `chan_kalman__band__short__5m__atr4d0_hold40_ve10d0e4_z1d0_fl1515__v2` | 1.415 | 57.0 | 8365 | 0.1 | 14.15 | short_sell |
| 15 | `chan_kalman__band__short__5m__atr4d0_hold40_ve10d0e4_z1d0__v1` | 1.414 | 56.7 | 8917 | 0.1 | 14.14 | short_sell |
| 16 | `chan_kalman__band__long__5m__atr1d5_hold40_ve10d0e4_z2d0__v1` | 1.411 | 44.1 | 467 | 0.1 | 14.11 | buy |
| 17 | `chan_kalman__band__long__5m__atr2d5_hold40_ve10d0e4_z2d0__v1` | 1.547 | 48.7 | 460 | 0.1 | 13.93 | buy |
| 18 | `chan_kalman__band__long__5m__atr2d5_hold40_ve10d0e4_z2d0_fl1515__v2` | 1.582 | 48.7 | 435 | 0.1 | 13.79 | buy |
| 19 | `chan_kalman__band__long__5m__atr4d0_hold40_ve1d0e4_z2d0_fl1515__v2` | 1.376 | 41.2 | 8345 | 0.1 | 13.76 | buy |
| 20 | `chan_kalman__band__short__5m__atr2d5_hold40_ve10d0e4_z1d0_fl1515__v2` | 1.350 | 55.0 | 8634 | 0.1 | 13.50 | short_sell |
| 21 | `chan_kalman__band__short__5m__atr2d5_hold40_ve10d0e4_z1d0__v1` | 1.346 | 54.8 | 9193 | 0.1 | 13.46 | short_sell |
| 22 | `chan_kalman__band__long__5m__atr4d0_hold40_ve10d0e4_z2d0_fl1515__v2` | 1.599 | 50.0 | 426 | 0.1 | 13.40 | buy |
| 23 | `chan_kalman__band__long__5m__atr4d0_hold40_ve10d0e4_z2d0__v1` | 1.539 | 49.9 | 451 | 0.1 | 13.31 | buy |
| 24 | `chan_kalman__band__long__5m__atr4d0_hold40_ve1d0e4_z2d0__v1` | 1.318 | 40.8 | 9058 | 0.1 | 13.18 | buy |
| 25 | `chan_kalman__band__long__5m__atr2d5_hold40_ve1d0e4_z2d0_fl1515__v2` | 1.293 | 40.9 | 8386 | 0.1 | 12.93 | buy |
| 26 | `chan_kalman__band__short__5m__atr4d0_hold40_ve1d0e4_z2d0__v1` | 1.280 | 48.5 | 12245 | 0.1 | 12.80 | short_sell |
| 27 | `chan_kalman__band__short__5m__atr1d5_hold40_ve10d0e4_z1d0_fl1515__v2` | 1.280 | 50.7 | 8953 | 0.1 | 12.80 | short_sell |
| 28 | `chan_kalman__band__short__5m__atr4d0_hold40_ve1d0e4_z2d0_fl1515__v2` | 1.277 | 48.6 | 11382 | 0.1 | 12.77 | short_sell |
| 29 | `chan_kalman__band__short__5m__atr1d5_hold40_ve10d0e4_z1d0__v1` | 1.273 | 50.4 | 9522 | 0.1 | 12.73 | short_sell |
| 30 | `chan_kalman__band__short__5m__atr2d5_hold40_ve1d0e4_z2d0__v1` | 1.255 | 47.6 | 12343 | 0.1 | 12.55 | short_sell |
| 31 | `chan_kalman__band__short__5m__atr2d5_hold40_ve1d0e4_z2d0_fl1515__v2` | 1.251 | 47.7 | 11478 | 0.1 | 12.51 | short_sell |
| 32 | `chan_kalman__band__long__5m__atr2d5_hold40_ve1d0e4_z2d0__v1` | 1.247 | 40.4 | 9101 | 0.1 | 12.47 | buy |
| 33 | `chan_kalman__band__short__5m__atr1d5_hold40_ve1d0e4_z2d0_fl1515__v2` | 1.230 | 45.7 | 11577 | 0.1 | 12.30 | short_sell |
| 34 | `chan_kalman__band__long__5m__atr1d5_hold40_ve1d0e4_z2d0_fl1515__v2` | 1.225 | 39.8 | 8437 | 0.1 | 12.25 | buy |
| 35 | `chan_kalman__band__short__5m__atr1d5_hold40_ve1d0e4_z2d0__v1` | 1.224 | 45.5 | 12449 | 0.1 | 12.24 | short_sell |
| 36 | `chan_kalman__band__long__5m__atr1d5_hold40_ve1d0e4_z2d0__v1` | 1.183 | 39.4 | 9157 | 0.1 | 11.83 | buy |
| 37 | `chan_kalman__band__long__15m__atr4d0_hold40_ve1d0e4_z2d0_fl1515__v2` | 1.128 | 41.6 | 6497 | 0.1 | 8.15 | buy |
| 38 | `chan_kalman__band__long__15m__atr1d5_hold40_ve10d0e4_z1d0_fl1515__v2` | 1.188 | 43.7 | 5108 | 0.2 | 5.54 | buy |
| 39 | `chan_kalman__band__long__15m__atr4d0_hold40_ve10d0e4_z1d0_fl1515__v2` | 1.392 | 47.1 | 4899 | 0.3 | 5.42 | buy |
| 40 | `chan_kalman__band__long__15m__atr1d5_hold40_ve10d0e4_z1d0__v1` | 1.108 | 42.6 | 5581 | 0.2 | 5.41 | buy |

## Excluded (reason counts)

- hold above 30 trading days: 165
- backtest had no stop; wire only with an always-on protective stop: 83
- n below 300: 54
- avg1 negative control (never average down): 44

## O'Neil tags for oneil-replay.yml `tags` input (B-776; avg1 cells excluded, short-hold h8/h12/h20 first)

```
oneil_leaders__firsthigh__long__1d__atr2_h20__v1,oneil_leaders__firsthigh__long__1d__atr3_h20__v1,oneil_rsline__newhigh__long__1d__atr3_h20__v1,oneil_pullback__buy__long__1d__atr3_h20__v1,oneil_rsscreen__top__long__1w__h26_pct7_rs90__v1,oneil_newhigh__first__long__1w__h26_pct7_rs80__v1,oneil_rsscreen__top__long__1w__h26_pct8_rs90__v1,oneil_newhigh__first__long__1w__h26_pct8_rs80__v1,oneil_rsscreen__top__long__1w__atr3_h26_rs90_trl1__v1,oneil_rsscreen__top__long__1w__atr2_h26_rs90__v1,oneil_newhigh__first__long__1w__atr2_h26_rs80__v1,oneil_newhigh__first__long__1w__atr3_h26_rs80_trl1__v1,oneil_newhigh__first__long__1w__atr3_h26_rsnone_trl1__v1,oneil_newhigh__first__long__1w__atr2_h26_rsnone__v1,oneil_rsscreen__top__long__1w__atr3_h26_rs90__v1,oneil_pivot__breakout__long__1w__atr2_chase10_h26_rs80__v1,oneil_pivot__breakout__long__1d__atr3_chase10_h40__v1__x__oneil_tightness__range__long__1d__pr1__v1,oneil_newhigh__first__long__1w__atr3_h26_rs80__v1,oneil_pivot__breakout__long__1w__atr2_chase5_h26_rs80__v1,oneil_newhigh__first__long__1w__atr3_h26_rsnone__v1,oneil_pivot__breakout__long__1w__atr3_chase10_h26_rs80__v1,oneil_pivot__breakout__long__1w__atr3_chase5_h26_rs80__v1,oneil_pivot__breakout__long__1w__atr3_chase10_h26_rsnone__v1,oneil_pivot__breakout__long__1w__atr3_chase5_h26_rsnone__v1
```
