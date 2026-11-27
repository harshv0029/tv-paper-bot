# Index option premium-proxy replay (B-1746 step 3), 2024-12-01 to 2026-11-26 IST

**PROXY_NOT_REAL_MONEY_EVIDENCE**: Black-Scholes proxy, IV = india_vix_prev_close, 1 ATM lot, single leg, quick exit (<=15:10 IST).
Decision metric: PFnet after the 0.8% cost model, IS and OOS both > 1.00, >= 5 OOS trades.

Cells tested: 450. Pass both IS and OOS: **182**.

Top 25 by OOS PFnet(0.8%):

| Sym | TF | Dir | Trigger | Exit | Hold min | n | IS PF | OOS PF | OOS n | OOS avg % | INR/lot (proxy) | Pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ^NSEI | 1h | long | rsi_thrust | s3_a1_t1 | 30 | 40 | 0.875 | 8.053 | 14 | 10.08 | 12748.0 | no |
| ^NSEI | 1h | long | rsi_thrust | s3_a1_t1 | 60 | 40 | 0.875 | 8.053 | 14 | 10.08 | 12748.0 | no |
| ^NSEI | 1h | long | rsi_thrust | s10_a5_t5 | 30 | 40 | 0.875 | 8.053 | 14 | 10.08 | 12748.0 | no |
| ^NSEI | 1h | long | rsi_thrust | s10_a5_t5 | 60 | 40 | 0.875 | 8.053 | 14 | 10.08 | 12748.0 | no |
| ^NSEI | 1h | long | rsi_thrust | s15_a10_t10 | 30 | 40 | 0.875 | 8.053 | 14 | 10.08 | 12748.0 | no |
| ^NSEI | 1h | long | rsi_thrust | s15_a10_t10 | 60 | 40 | 0.875 | 8.053 | 14 | 10.08 | 12748.0 | no |
| ^NSEI | 1h | long | rsi_thrust | s20_a10_t10 | 30 | 40 | 0.875 | 8.053 | 14 | 10.08 | 12748.0 | no |
| ^NSEI | 1h | long | rsi_thrust | s20_a10_t10 | 60 | 40 | 0.875 | 8.053 | 14 | 10.08 | 12748.0 | no |
| ^NSEI | 1h | long | rsi_thrust | s30_a15_t15 | 30 | 40 | 0.875 | 8.053 | 14 | 10.08 | 12748.0 | no |
| ^NSEI | 1h | long | rsi_thrust | s30_a15_t15 | 60 | 40 | 0.875 | 8.053 | 14 | 10.08 | 12748.0 | no |
| ^BSESN | 1h | short | rsi_thrust | s20_a10_t10 | 375 | 43 | 1.268 | 5.567 | 17 | 75.38 | 36027.0 | yes |
| ^BSESN | 1h | short | rsi_thrust | s30_a15_t15 | 375 | 43 | 1.105 | 5.412 | 17 | 74.91 | 31217.0 | yes |
| ^BSESN | 1h | short | ema_cross | s3_a1_t1 | 375 | 58 | 1.129 | 5.305 | 25 | 68.67 | 20829.0 | yes |
| ^BSESN | 1h | short | ema_cross | s15_a10_t10 | 375 | 57 | 1.408 | 5.142 | 25 | 84.13 | 29867.0 | yes |
| ^BSESN | 1h | long | rsi_thrust | s3_a1_t1 | 30 | 39 | 0.324 | 4.963 | 16 | 31.42 | 12600.0 | no |
| ^BSESN | 1h | long | rsi_thrust | s3_a1_t1 | 60 | 39 | 0.324 | 4.963 | 16 | 31.42 | 12600.0 | no |
| ^BSESN | 1h | long | rsi_thrust | s10_a5_t5 | 30 | 39 | 0.324 | 4.963 | 16 | 31.42 | 12600.0 | no |
| ^BSESN | 1h | long | rsi_thrust | s10_a5_t5 | 60 | 39 | 0.324 | 4.963 | 16 | 31.42 | 12600.0 | no |
| ^BSESN | 1h | long | rsi_thrust | s15_a10_t10 | 30 | 39 | 0.324 | 4.963 | 16 | 31.42 | 12600.0 | no |
| ^BSESN | 1h | long | rsi_thrust | s15_a10_t10 | 60 | 39 | 0.324 | 4.963 | 16 | 31.42 | 12600.0 | no |
| ^BSESN | 1h | long | rsi_thrust | s20_a10_t10 | 30 | 39 | 0.324 | 4.963 | 16 | 31.42 | 12600.0 | no |
| ^BSESN | 1h | long | rsi_thrust | s20_a10_t10 | 60 | 39 | 0.324 | 4.963 | 16 | 31.42 | 12600.0 | no |
| ^BSESN | 1h | long | rsi_thrust | s30_a15_t15 | 30 | 39 | 0.324 | 4.963 | 16 | 31.42 | 12600.0 | no |
| ^BSESN | 1h | long | rsi_thrust | s30_a15_t15 | 60 | 39 | 0.324 | 4.963 | 16 | 31.42 | 12600.0 | no |
| ^BSESN | 1h | short | ema_cross | s20_a10_t10 | 375 | 57 | 1.408 | 4.941 | 25 | 83.3 | 27841.0 | yes |

Pooled over all 3 indices and both TFs (house wiring rule: pooled PFnet > 1.00), top 15 by OOS:

| Dir | Trigger | Exit | Hold min | IS n | IS PF | OOS n | OOS PF | Pass |
|---|---|---|---|---|---|---|---|---|
| short | rsi_thrust | s20_a10_t10 | 375 | 83 | 1.17 | 50 | 4.08 | yes |
| long | rsi_thrust | s3_a1_t1 | 30 | 83 | 0.65 | 48 | 4.08 | no |
| long | rsi_thrust | s3_a1_t1 | 60 | 83 | 0.65 | 48 | 4.08 | no |
| long | rsi_thrust | s10_a5_t5 | 30 | 83 | 0.65 | 48 | 4.08 | no |
| long | rsi_thrust | s10_a5_t5 | 60 | 83 | 0.65 | 48 | 4.08 | no |
| long | rsi_thrust | s15_a10_t10 | 30 | 83 | 0.65 | 48 | 4.08 | no |
| long | rsi_thrust | s15_a10_t10 | 60 | 83 | 0.65 | 48 | 4.08 | no |
| long | rsi_thrust | s20_a10_t10 | 30 | 83 | 0.65 | 48 | 4.08 | no |
| long | rsi_thrust | s20_a10_t10 | 60 | 83 | 0.65 | 48 | 4.08 | no |
| long | rsi_thrust | s30_a15_t15 | 30 | 83 | 0.65 | 48 | 4.08 | no |
| long | rsi_thrust | s30_a15_t15 | 60 | 83 | 0.65 | 48 | 4.08 | no |
| short | rsi_thrust | s30_a15_t15 | 375 | 83 | 1.10 | 49 | 4.02 | yes |
| short | ema_cross | s20_a10_t10 | 375 | 98 | 1.78 | 72 | 4.01 | yes |
| short | ema_cross | s15_a10_t10 | 375 | 98 | 1.81 | 73 | 4.00 | yes |
| short | ema_cross | s3_a1_t1 | 375 | 99 | 1.66 | 73 | 3.82 | yes |

Pooled combos passing IS and OOS: **94** of 150. 450 single cells were tested, so single-cell passes include multiple-testing luck.
