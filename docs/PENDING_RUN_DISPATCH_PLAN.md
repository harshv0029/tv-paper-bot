# Pending-run dispatch plan (backlog rows in HARNESS-BUILT / RUN-PENDING state)

Prepared 2026-10-12 IST (docs only, by a subagent; nothing was dispatched). Backlog pointer: B-806.
Dispatch is done only by the coordinator, one running + one queued, small single-job runs first, big matrices last,
never while a Deploy Gate or safety run is queued (CLAUDE.md dispatch-order and two-in-flight rules).

## Reality check on the count

The task brief said "about 44" rows. The backlog actually has **203 rows** whose status is `HARNESS-BUILT-AWAITING-RUN`
(101), `HARNESS_BUILT_RUN_PENDING` (94), `HARNESS-BUILT-RUN-PENDING` (2, B-792/B-798) or
"HARNESS BUILT, full-universe run owed" (6). They collapse into **13 distinct workflow files** (one run closes many rows,
because each family script emits one registry cell per row's variant). The plan is therefore per workflow, not per row.
Status wording in the backlog is inconsistent (hyphen vs underscore, status in column 2 or 3); `scripts/backlog_status.py`
already maps all of them to RUN_PENDING.

## Main-branch check

`git diff origin/main -- .github/workflows/` against the working branch is empty at the time of writing (origin/main
5749258): **all 13 workflow files below already exist on main and are byte-identical to the working branch. No Deploy Gate
is needed before any dispatch.** All are `workflow_dispatch` only, all parse as valid YAML. No workflow is missing or
syntactically broken. (Not verified by a live run: runtime correctness of each script; that is what the first run shows.)

## Duration and capacity notes

- Durations are ESTIMATES, not measured. Hard cap per research job is `timeout-minutes: 340` (some workflows set none, so
  GitHub's 360 default applies). Free-tier Actions runs about 20 jobs at once, so a matrix with N jobs takes about
  ceil(N/20) waves.
- Several results may already be partly in the registry: `docs/STRATEGY_RESULTS_LOG.md` already carries elder, oneil,
  overlay and trademgmt rows from earlier runs. Before dispatching a family, grep the log for its tag prefix
  and the backlog row for a run id; if the cells are already registered, close the row instead of re-running.
- "Profit relevance" is a judgement (H/M/L): H = P1 rows, or a direct line to a wired or wireable viable strategy
  (PFnet >= 1.1, SL on every trade); M = P2 breadth on existing indicator families; L = P3 or low-hit families.

## Ordered dispatch table

Jobs = default-input matrix size including the merge/aggregate job.

| # | Workflow file | On main | Jobs (default) | Est. wall time | Rows closed (B-) | Pri mix | Profit relevance | Dispatch with |
|---|---|---|---|---|---|---|---|---|
| 1 | `oneil-research.yml` | yes | 8 (6 scan + 2 merge) | 1-2 h | 460-466, 473, 483, 488, 489, 491, 502 (13) | P1 x12, P2 x1 | H: O'Neil CAN SLIM/base patterns, mostly P1 | no inputs (defaults; matrix tf 1d,1w x 3 shards) |
| 2 | `portfolio-overlay-research.yml` | yes | 9 (8 collect + 1 merge) | 1-2 h | 504, 507-509, 516-519, 527, 528, 543, 548, 549, 555-557, 564, 565, 569, 746 (20) | P1 x11, P2 x9 | H: sizing/overlay effects apply to every wired strategy | no inputs |
| 3 | `douglas-trade-mgmt-research.yml` | yes | 9 (8 research + 1 merge) | 1-2 h | 501, 532-535, 537, 545, 551-554, 561, 566, 572, 574, 605 (16) | P1 x8, P2 x8 | H: exit/management rules (profit-booking lessons) | `interval=1d period=5y` (defaults) |
| 4 | `oneil-ext-research.yml` | yes | 8 (6 scan + 2 merge) | 1-2 h | 477-480, 484-487, 490, 492, 494-500 (17) | P1 x14, P2 x3 | H: extension of #1; run after #1 so shared tags are not clobbered | no inputs |
| 5 | `elder-macd-dirgap-research.yml` | yes | 13 (12 research + 1 merge) | 2-3 h | 727, 732 (macd, dirsys, gaps; B-760 adx_bell is in #10) | P2 | M | `interval=1d period=5y` |
| 6 | `elder-trend-context-research.yml` | yes | 13 (12 + 1) | 2-3 h | 567, 570, 580, 581, 586, 587, 593, 598, 599, 628-633 (15) | P1 x3, P2 x12 | M | `interval=1d period=5y` |
| 7 | `elder-patterns-research.yml` | yes | 17 (16 + 1) | 2-3 h | 571, 600-603, 607-624 (23) | P2 x21, P1, P3 | M | `interval=1d period=5y` |
| 8 | `intraday-flatten-rerun.yml` | yes | 28 (27 run + 1 merge) | 2-4 h | 792 (1 row, 35 cells) | P1 | H: decides which of the 38 intraday-bar viable cells survive a forced 15:15 IST flatten; gates any intraday wiring | defaults: `families=["chan_kalman","pattern_n200","pattern_full"] intervals=["5m","15m","1h"] maxsym=0` |
| 9 | `elder-batch3-research.yml` | yes | 25 (20 research + 4 orb + 1 merge); 21 with `run_orb=false` | 3-5 h | 634, 641, 644-646, 656, 657, 661, 662, 666, 670, 673, 676-685, 704, 706, 707, 710, 720-722, 728, 731, 733-736, 741, 744, 745, 767 (39) | P2 x27, P1 x8, P3 x4 | M | `interval=1d period=5y run_orb=true` (orb needs intraday data; set false first if capacity is short) |
| 10 | `elder-indicators-research.yml` | yes | 33 (32 + 1) | 3-5 h | 643, 651, 653, 667, 674, 694-696, 700-703, 708, 759, 762 (15); also B-760 (adx_bell) | P1 x14 | H: mostly P1 | `interval=1d period=5y` |
| 11 | `brk20-min-rr-main-replay.yml` | yes | 38 (1 plan + 36 replay + 1 aggregate) | 4-8 h (3 waves, max-parallel 20) | 798 (1 row, 12 cells x 3 TFs x 2 dirs) | P1 | **H+: highest-PFnet short on record with n>=100; main.py-function replay decides wiring** | defaults `intervals=1d,1h,15m directions=long,short atrs=3,4 rrs=3,3.5,4 bes=none,1 nshards=6` |
| 12 | `b412-swing-variants-replay.yml` | yes | about 37 (up to 36 planned by `scripts/b412_plan.py` + aggregate) | 4-8 h | 412 (first row; the 30 minervini lab variants + breakeven-at-1R, 2 rows share the id) | P1 | H: swing engine variants, real main.py entries | check the workflow's own inputs before dispatch (not re-read here); it is not named as pending by a HARNESS status except via B-412 |
| 13 | `elder-indicators-research-ext.yml` | yes | 41 (40 + 1), exceeds the 40-job design note | 5-9 h (3 waves) | 647-650, 652, 654, 655, 658-660, 663-665, 668, 669, 675, 697-699, 705, 709, 716-719, 723-726, 729, 738, 739, 761, 763-766, 769, 770 (38) | P1 x23, P2 x9, P3 x6 | M-H (23 P1 rows) but the biggest matrix: dispatch last, alone | `interval=1d period=5y` |

Rows B-709, B-732, B-760 and B-412 carry no workflow filename in their text; they were mapped by the notes in each row
(B-709 to #13 diverge variants, B-732 to #5 gaps family, B-760 to #10 adx_bell, B-412 to #12).

## Suggested sequencing

1. Waves 1-4 (items 1-4, about 34 jobs total) are the cheap P1 O'Neil/overlay/Douglas runs. Dispatch #1, queue #2; as each
   finishes dispatch the next. Two in flight only.
2. Items 5-7 (13-17 jobs each) once the first four are done.
3. Item 8 (intraday flatten) is the highest direct profit lever among mid-size runs; promote it to slot 2 if the user wants
   intraday viability answered sooner (it is P1 and gates a whole wiring decision).
4. Item 11 (brk20) is the single most valuable big run; if a clear queue window exists, promote it ahead of 9-10, 12, 13.
5. Items 12 and 13 last. Never dispatch a matrix while a Deploy Gate or Kotak safety run is queued.
6. After every run: register all cells in `strategy_registry.py` with full raw metrics, regenerate
   `docs/STRATEGY_RESULTS_LOG.md`, add the `docs/STRATEGY_LEARNINGS.md` entry, and close the rows in the same commit with the run id.

## Blockers and flags

- Count mismatch: 203 rows over 13 workflows, not 44 (see above). No row is dropped.
- No workflow is missing on main; none found broken (YAML parses; inputs and matrices resolve).
- `elder-indicators-research-ext.yml` default matrix is 41 jobs (10 families x 4 shards + merge), over the usual 40 cap.
- `elder-batch3-research.yml` orb job needs intraday history; confirm it runs within yfinance limits before relying on it.
- Possible stale rows: part of these families may already be registered from earlier runs (registry has hundreds of elder,
  oneil, overlay and trademgmt rows). Reconcile against the results log before burning runner time.
- B-412 sits in two rows (HARNESS_BUILT_RUN_PENDING at line 426 and a later PARTIAL row at 430); the second records the
  3R wiring already done. The b412 workflow covers the remainder.
- No dispatch times set: this document does not start anything. Check-ins are the coordinator's job (IST, `send_later`).
