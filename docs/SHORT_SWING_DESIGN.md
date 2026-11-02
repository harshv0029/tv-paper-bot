# Short-swing (1d SHORT) path: design (B-871)

Written 2026-11-02 IST. Design only: nothing here is wired to real money. Sources are cited inline. The
verdict is at the top because it changes what is worth building.

## 0. Verdict in one paragraph

The 1d short edge is real on the cash universe: brk20_min_rr short 1d, 6 plain cells, PFnet 1.66-3.95
pooled and 1.72-9.72 out of sample. But it lives in stocks that **have no overnight short instrument
at Kotak**. Kotak rejects NRML cash shorts (B-967, run 39724116793: "SHORT SELLING NOT ALLOWED IN NRML
PRODUCT"). Futures, puts and SLBM all need an F&O-eligible stock. On the 210 F&O underlyings the same
signal loses **before costs** (B-1339, run 39861349630: gross PF 0.52-0.86, net 0.45-0.75, n 47-1932).
A Rs 9.6k account cannot carry one stock-futures lot either. **Recommendation: build no new real
instrument route now.** Keep the existing cash short-swing path paper-only, as forward evidence. Run
the one owed like-for-like futures-cost replay (section 5). Build the futures route (section 4) only if
that replay clears the floor AND capital reaches about Rs 2.5 lakh.

## 1. Instrument options

| Route | Codebase support today | Capital fit (Rs 9.6k, B-1420) | Signal on its universe | Verdict |
|---|---|---|---|---|
| Cash NRML/CNC short held overnight | `kotak_real_orders.place_real_short_entry/cover/stop_loss(product=...)`; main.py path built (B-871 PARTIAL) | Fits | Strong (full universe) | **Impossible**: Kotak RMS rejects it (B-967) |
| Stock-futures short, NRML | `nse_fo_chain.select_nse_future` (FUTSTK rows, `lot_size`, `instrument_token`, `expiry`, `dte`); `kotak_real_fo_orders.place_real_fo_entry/exit/stop_loss` (NRML default, nse_fo/mcx_fo); `check_margin_affordable` (live margin check, fails closed) | **No**: 1 lot needs about Rs 1-3 lakh margin (B-1339) | **Fails** on the 210 F&O names (gross <1) | Not now |
| Long put (ATM / near month) | `select_nse_option_contract*`, `stock_option_tradable` (OI/volume/lot-notional screen), `ensure_option_trailing_sl` | Partly: one lot premium is often Rs 2-10k, close to the whole account | Same F&O universe, so it fails; theta and spread add more cost | Not now (B-1343 closed-as-explained) |
| SLBM borrow, then CNC sell | **None**: no SLB call anywhere in the repo (grep `slb`, only a research script); Kotak Neo SDK exposure unverified | Fits per share, plus a borrow fee | SLB-eligible list largely overlaps the F&O list (to verify), so likely the same universe problem | Not now; verify with the user before any build |
| Rolling MIS (short at 09:15, cover at 15:15, repeat) | Intraday short engine exists | Fits | Not this signal: it drops the overnight gaps a 1d short earns, and pays costs every day | Rejected: about 12 days x 0.8% model cost = about 9.6% against an average net of 1.9-6.6% per trade |

Notes on the futures and options primitives:

- **Products.** `kotak_real_fo_orders` uses NRML everywhere. Its docstring explicitly refuses SELL-to-open
  ("selling naked is out of scope, not just unwired"). A futures short would therefore need a new
  `place_real_fo_short_entry` primitive and a BUY-side SL. Today `place_real_fo_stop_loss` assumes the
  long side, so it needs a short variant.
- **Physical settlement.** All 210 `STOCK_FO_UNDERLYINGS` settle physically. A short future left past
  expiry becomes a delivery obligation. `nse_fo_chain.must_force_close_before_expiry` (2 trading days
  before expiry) is written and tested but has no caller yet. A futures short engine must call it on
  every tick.
- **Lot-size problem.** Contract value is several lakh per lot (SEBI minimum contract size). An ATR4 stop
  at about 2.5% daily ATR is about 10% of notional, so one lot of Rs 7 lakh risks about Rs 70k. That is
  7x the whole account and far above `_real_loss_budget`. Risk-based sizing (`_real_swing_qty_by_risk`)
  rounds to 0 lots, so the route self-blocks. The only open question is whether to build it before
  capital exists. B-1339 said no; this design agrees.
- **Cost impact.** Futures are cheaper per round trip than the 0.8% cash model. Statutory charges are
  about 0.05% (STT on the futures sell, exchange, stamp), slippage about 0.1%, and one monthly roll about
  0.1-0.15%, giving the 0.3% B-1339 used. That would lift a cash PFnet, but it cannot rescue a gross PF
  below 1. The universe kills it, not the cost.

## 2. Data model (as built on cash; what a futures route adds)

Already in main.py (verified by grep 2026-11-02, not only from the backlog prose):

- Own tables `signal_state_swing_short` and `real_positions_swing_short` (main.py ~1197). Both are in
  `_GENERIC_MIRROR_TABLES` (~20840), so they are Upstash-mirrored and restored at boot. A wipe-restore
  test is in `tests/test_short_swing_path.py`.
- Entry `_maybe_place_real_swing_short_entry` (~25659) runs these gates in order: shared
  `is_real_swing_trading_enabled`, `SHORT_SWING_OVERNIGHT_PRODUCT_CONFIRMED` (False, permanently for cash
  per B-967), a cross-table ownership check over 4 tables, the PFnet gate (plus a B-962 re-check just
  before the order), the 15:14 cutoff, a live tick, the same-day buy cooldown, stop above price, price
  tolerance, risk sizing and the loss budget. It then sends the SELL, places the BUY-stop at once
  (`_ensure_resting_short_sl`), and **unwinds by cover if the SL fails** (no trade without SL).
- Exit `_maybe_place_real_swing_short_exit(reason=...)` (~25785) cancels the SL, covers, and logs the
  reason. It is Kotak-first: a row Kotak no longer shows as short is cleared without sending an order.
- Heal `_heal_real_swing_short_sl` (~25832) runs on every reconcile (5 min). It aligns the row to Kotak,
  then re-places a missing BUY-stop.
- Ownership: the intraday short entry refuses swing-short symbols (~14668). Reconcile adoption routes by
  owning table.

What a futures route would add (only once section 5 passes):

1. Columns `instrument` (`EQ`|`FUT`), `exchange_segment`, `instrument_token`, `lot_size`, `expiry`,
   `lots`. Keep it the **same table**: one engine owns one category (the engine-ownership rule), and
   rows are keyed by underlying symbol.
2. A new tag variant per the naming grammar, `brk20_min_rr__main_replay_fut__short__1d__...`. It is
   never the cash tag with a flag, and it is gated on its own futures-cost metrics.
3. Expiry force-close. On every tick, `must_force_close_before_expiry` leads to a cover with reason
   `physical_settlement_force_close`. There is no auto-roll; a roll is a fresh entry that must
   re-qualify.
4. A BUY SL-M on nse_fo placed with the entry. If it fails, unwind. The 09:15 IST re-protect and the
   5-min backcheck already key on Kotak net-qty sign, so a short future is covered by the same
   `_find_unprotected_open_positions`. Confirm this in a test, because FO trading symbols differ from
   `-EQ`.
5. Align-to-Kotak for `sl_order_id`/`qty` from `positions()` on nse_fo (Kotak-wins rule).

## 3. Which registered short cells qualify

Registry query, 2026-11-02 (`'__short__1d__' in name and pfnet >= 1.1`): 149 tags. Note that
`PFNET_LIVE_FLOOR` in strategy_registry.py is **1.0** (2026-10-14 user override, line 108). CLAUDE.md
still says 1.1. The task asked for 1.1, which every brk20 cell below clears anyway.

- **Wired in code (paper, real leg fail-closed):** the 6 plain cells
  `brk20_min_rr__main_replay__short__1d__atr{3,4}_rr{3,3d5,4}__v1`. Pooled PFnet 1.66 / 2.07 / 2.47 /
  2.58 / 2.97 / 3.95 (n 582 to 115). OOS (run 38247769897) 1.72 / 1.94 / 2.14 / 2.39 / 4.53 / 9.72 (n 216
  to 39). These are in `REPLAY_OWED_TAGS`, so the real gate stays closed even past the floor.
- **Also clear but not wired:** `be1` variants (1.67-4.21; the ratchet needs a Kotak SL modify),
  `_rsbandfloor` (2.18-6.36), `main_replay_mr` (2.27-5.39), `_is`/`_oos` research slices. Families with
  no main.py short port: sector_rotation fade (40 tags), oneil_saucer, tasuki ETF (ETF universe:
  **no F&O, no SLB**), chan_gap, consol, pfovl, dirsys13, MCX `*_ng/_hg/_si/_cl` cells. The MCX cells
  are already futures, so they are not part of this problem; they belong to the F&O engine.
- **Did any of them model futures costs?** No. Every cash cell above is at 0.8% (cash model) on the full
  NSE universe. Only `main_replay_fno` (13 tags) used futures cost (0.3%) on F&O names, and all of them
  are below 1.0. The cost-stress learning (STRATEGY_LEARNINGS ~183) shows small-cap edges also shrink
  at 1.2-1.6%, which matters for the cash cells' true slippage.

## 4. Recommendation and stepwise build plan

**Now (no real-money change):**
1. Keep `SHORT_SWING_OVERNIGHT_PRODUCT_CONFIRMED=False`. Rename nothing. The paper short-swing pass
   keeps logging forward trades for the 6 cells, which is the cheapest OOS evidence available.
2. Run the owed replay (section 5). It decides whether step 3 ever happens.

**Only if section 5 shows an F&O-universe cell with PFnet >= floor at futures cost, n >= 30 OOS, AND
capital can carry one lot within the loss budget:**

3. `kotak_real_fo_orders.place_real_fo_short_entry` + `place_real_fo_short_stop_loss` (BUY SL-M).
   Tests: payload side/product/segment, nOrdNo-confirms-success, never raises.
4. Table columns (section 2.1), with the mirror unchanged. Test: wipe-restore keeps the FUT fields.
5. Entry branch in `_maybe_place_real_swing_short_entry`: `instrument=FUT` comes from
   `select_nse_future`, `lots = floor(risk_budget / (lot_size * stop_dist))`, and it skips when that is
   0. `check_margin_affordable` runs before the order. SL with the entry, unwind on failure. Tests:
   0-lot skip, margin-fail skip, SL-fail unwind, reason logged.
6. Expiry force-close in the short-swing pass. Test: dte <= 2 leads to a cover with reason.
7. Heal/backcheck on nse_fo. Tests: an unprotected short future is flagged and healed at the 5-min and
   09:15 passes, and the ownership check refuses it in the intraday and F&O-option engines.
8. Full suite, `ast.parse(main.py)`, then Deploy Gate only on the user's word.

## 5. Backtest still owed (futures-cost replay)

B-1339's F&O run was not like-for-like with the wired cells. It swept atr 2/3/4 x rr 1/2/3. Of the 6
wired cells it covered only atr3_rr3 and atr4_rr3 (n=1). atr3_rr3d5 and atr3_rr4 were never run on F&O
names, and atr4_rr3d5/rr4 gave n=0. Owed, all through `scripts/brk20_replay.py` (the real main.py
functions):

- **(a)** `universe=fno`, 1d, the exact 6 wired cells plus be1, at cost 0.3% and at 0.8%. Expect low n;
  report it honestly.
- **(b)** A cash complement split: the full universe minus F&O names, same 6 cells, 0.8%. This confirms
  where the edge lives.
- **(c)** Flag a metadata inconsistency. `brk20_run_38185670883.json` says `period 730d`, but its IS/OOS
  cutoff (2024-10-12) with IS n > OOS n implies about 5y of 1d bars, and the script maps 1d to 5y. The
  F&O run used 5y, so the comparison is probably same-period. Fix the label, and confirm it before
  trusting the universe conclusion.
- Futures P&L is still cash-price tracking (no basis or roll gap). State that in every result.
