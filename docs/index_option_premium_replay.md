# Index option premium-proxy replay (B-1746 step 3), 2026-10-01 to 2026-11-26 IST

**PROXY_NOT_REAL_MONEY_EVIDENCE**: Black-Scholes proxy, IV = india_vix_prev_close, 1 ATM lot, single leg, quick exit (<=15:10 IST).
Decision metric: PFnet after the 0.8% cost model, IS and OOS both > 1.00, >= 5 OOS trades.

Cells tested: 900. Pass both IS and OOS: **236**.

Top 25 by OOS PFnet(0.8%):

| Sym | TF | Dir | Trigger | Exit | Hold min | n | IS PF | OOS PF | OOS n | OOS avg % | INR/lot (proxy) | Pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ^NSEI | 15m | long | rsi_thrust | s10_a5_t5 | 60 | 12 | 3.012 | 114.586 | 4 | 11.36 | 8970.0 | no |
| ^NSEI | 15m | long | rsi_thrust | s15_a10_t10 | 60 | 12 | 1.744 | 49.919 | 4 | 4.89 | 4884.0 | no |
| ^NSEI | 15m | long | rsi_thrust | s20_a10_t10 | 60 | 12 | 1.232 | 49.919 | 4 | 4.89 | 1937.0 | no |
| ^NSEI | 15m | long | rsi_thrust | s30_a15_t15 | 60 | 12 | 1.107 | 49.919 | 4 | 4.89 | 1217.0 | no |
| ^NSEI | 15m | long | live_orb_trend_novol | s20_a10_t10 | 30 | 19 | 2.658 | 42.944 | 7 | 8.61 | 6752.0 | yes |
| ^NSEI | 15m | long | live_orb_trend_novol | s30_a15_t15 | 30 | 19 | 2.658 | 42.944 | 7 | 8.61 | 6752.0 | yes |
| ^NSEBANK | 15m | long | atr_range_break | s20_a10_t10 | 375 | 23 | 0.274 | 33.262 | 10 | 36.38 | 53799.0 | no |
| ^NSEBANK | 15m | long | atr_range_break | s30_a15_t15 | 375 | 23 | 0.261 | 30.2 | 10 | 37.34 | 57242.0 | no |
| ^NSEI | 15m | long | ema_cross | s10_a5_t5 | 375 | 17 | 0.916 | 25.485 | 5 | 19.62 | 14795.0 | no |
| ^NSEBANK | 5m | long | atr_range_break | s30_a15_t15 | 375 | 31 | 0.706 | 23.215 | 13 | 30.62 | 80399.0 | no |
| ^NSEBANK | 5m | long | atr_range_break | s20_a10_t10 | 375 | 36 | 0.866 | 23.147 | 15 | 20.88 | 67214.0 | no |
| ^NSEI | 15m | long | live_orb_trend_novol | s20_a10_t10 | 375 | 19 | 4.792 | 21.097 | 7 | 33.69 | 27447.0 | yes |
| ^BSESN | 15m | long | live_orb_trend_novol | s3_a1_t1 | 60 | 18 | 1.863 | 20.768 | 7 | 48.04 | 8796.0 | yes |
| ^BSESN | 15m | long | orb | s3_a1_t1 | 60 | 23 | 1.33 | 15.198 | 8 | 63.46 | 8027.0 | yes |
| ^BSESN | 5m | long | live_orb_trend_novol | s30_a15_t15 | 375 | 20 | 1.934 | 14.125 | 7 | 59.03 | 27928.0 | yes |
| ^NSEI | 15m | long | ema_cross | s3_a1_t1 | 375 | 17 | 0.998 | 13.761 | 5 | 10.22 | 10071.0 | no |
| ^BSESN | 15m | long | live_orb_trend_novol | s3_a1_t1 | 375 | 18 | 1.827 | 13.186 | 7 | 29.62 | 6040.0 | yes |
| ^BSESN | 15m | long | rsi_thrust | s30_a15_t15 | 375 | 13 | 4.839 | 12.527 | 5 | 83.34 | 17911.0 | yes |
| ^BSESN | 15m | long | orb | s3_a1_t1 | 375 | 23 | 1.33 | 11.591 | 8 | 47.34 | 5624.0 | yes |
| ^BSESN | 5m | long | live_orb_trend_novol | s30_a15_t15 | 60 | 20 | 2.091 | 11.406 | 7 | 53.51 | 7928.0 | yes |
| ^NSEI | 5m | long | live_orb_trend_novol | s30_a15_t15 | 375 | 21 | 0.312 | 11.271 | 7 | 36.48 | 13095.0 | no |
| ^BSESN | 15m | long | live_orb_trend_novol | s3_a1_t1 | 30 | 18 | 1.752 | 10.66 | 7 | 17.21 | 6145.0 | yes |
| ^NSEBANK | 5m | long | atr_range_break | s15_a10_t10 | 375 | 38 | 0.822 | 10.479 | 16 | 18.4 | 58970.0 | no |
| ^NSEI | 15m | long | atr_range_break | s10_a5_t5 | 30 | 28 | 3.304 | 10.323 | 11 | 11.28 | 16629.0 | yes |
| ^NSEI | 15m | long | atr_range_break | s15_a10_t10 | 30 | 28 | 3.769 | 10.323 | 11 | 11.28 | 17306.0 | yes |

Pooled over all 3 indices and both TFs (house wiring rule: pooled PFnet > 1.00), top 15 by OOS:

| Dir | Trigger | Exit | Hold min | IS n | IS PF | OOS n | OOS PF | Pass |
|---|---|---|---|---|---|---|---|---|
| long | live_orb_trend_novol | s30_a15_t15 | 375 | 74 | 1.85 | 52 | 6.79 | yes |
| long | live_orb_trend_novol | s20_a10_t10 | 375 | 74 | 2.08 | 52 | 4.74 | yes |
| long | live_orb_trend_novol | s15_a10_t10 | 375 | 74 | 2.27 | 52 | 4.41 | yes |
| long | atr_range_break | s20_a10_t10 | 375 | 113 | 3.33 | 78 | 4.11 | yes |
| long | atr_range_break | s30_a15_t15 | 375 | 104 | 3.25 | 72 | 4.02 | yes |
| long | live_orb_trend_novol | s30_a15_t15 | 60 | 74 | 1.70 | 52 | 3.89 | yes |
| long | atr_range_break | s15_a10_t10 | 375 | 114 | 3.63 | 81 | 3.83 | yes |
| long | orb | s30_a15_t15 | 375 | 89 | 1.88 | 61 | 3.59 | yes |
| long | orb | s20_a10_t10 | 375 | 89 | 2.47 | 61 | 3.06 | yes |
| long | atr_range_break | s10_a5_t5 | 375 | 123 | 3.54 | 92 | 2.95 | yes |
| long | orb | s3_a1_t1 | 60 | 89 | 2.90 | 61 | 2.94 | yes |
| long | live_orb_trend_novol | s20_a10_t10 | 60 | 74 | 1.80 | 52 | 2.92 | yes |
| long | rsi_thrust | s30_a15_t15 | 375 | 74 | 1.86 | 41 | 2.80 | yes |
| long | atr_range_break | s30_a15_t15 | 60 | 128 | 3.04 | 96 | 2.74 | yes |
| long | live_orb_trend_novol | s15_a10_t10 | 60 | 74 | 1.98 | 52 | 2.74 | yes |

Pooled combos passing IS and OOS: **70** of 150. 900 single cells were tested, so single-cell passes include multiple-testing luck.
