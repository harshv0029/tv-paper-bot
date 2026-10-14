# Pre-dispatch QA and recommended dispatch order (B-1200, 2026-10-14 IST)

Checked by `scripts/workflow_qa.py` (static: YAML parses, `inputs.*` declared, `matrix.*` keys exist, dynamic matrices expanded by running
their own plan step with input defaults, artifact names unique, download patterns match replay uploads, referenced scripts exist) and by
`tests/test_workflow_smoke_b1200.py` (SYNTHETIC one-shard run + merge of every driver). Runner-hour figures are ESTIMATES from universe
size (~2,680 symbols), fetch time (~1-1.5 s per symbol per fetch) and bar-loop cost; replace them with actual run history after the first
dispatch of each. The free tier runs ~20 jobs at once (CLAUDE.md: one running + one queued; research matrices last, after any gate/safety run).

| Order | Workflow (dispatch input) | Default jobs | Est. runner-hours | Notes |
|---|---|---|---|---|
| 1 | `envelope-main-replay.yml` | 8 replay + 1 merge | ~4 | BLOCKED until `main.ENVELOPE_1H_CELLS` / `envelope_fade_*` are on the branch (smoke test skips with this reason; the 632684d commit does not carry main.py) |
| 2 | `chan-nonoverlap.yml` (`intervals`=["4h"]) | 3 per interval + merge (default 1d,1h = 7) | ~4 | no SYNTHETIC mode (live yfinance); merge reads `shards/**/chan_nonovl_shard_*.json` |
| 3 | `chan-gap-tf-sweep.yml` (`interval`=15m, then 1h, then 5m) | 24 + 1 per interval | ~6 per interval | two yfinance fetches per symbol (1d + intraday); 5m/15m only 60d |
| 4 | `pl1d-tf-sweep.yml` (`tf`=4h, then 1h) | 16 + 1 per tf | ~7 per tf | |
| 5 | `sector-rotation-sweep.yml` (`entry`=next_open, then signal_close) | 6 (L x tf) | ~12 per entry model | every job loads the whole universe (not sharded by symbol), so each runs 1.5-2.5 h; 4h jobs heavier |
| 6 | `gatetarget-short-sweep-replay.yml` | 49 + 1 | ~20 | |
| 7 | `pl1d-tf-dir-sweep-replay.yml` | 57 + 1 | ~19 | overlaps in intent with `pl1d-tf-sweep.yml`; distinct tags, both stay |
| 8 | `island-tf-dir-sweep-replay.yml` | 61 + 1 | ~25 | |
| 9 | `brk20-min-rr-main-replay.yml` (`intervals`=4h or default 1d,1h,15m) | 36 + 1 (default), 12 for 4h alone | ~36 default | heaviest per job (12 cells per symbol, bar-by-bar loop) |

Rules applied: small single-purpose runs first, big matrices last; never more than one matrix running plus one queued; a matrix over 20
jobs queues behind itself on the free tier, so its wall-clock is about ceil(jobs/20) x the per-job time.

## Defects found

1. `envelope-main-replay.yml` / `scripts/envelope_main_replay.py` need `main.ENVELOPE_1H_CELLS`, which is not in this branch's `main.py`
   (the 632684d commit changes no `main.py`; `tests/test_envelope_main_replay.py` also fails here). Fix = merge the main.py half first. Not
   fixable from a research-only worktree.
2. `scripts/bar_hygiene.py` was added by two commits (ec80b49 and 632684d); the copies are identical, so the second applies cleanly.
3. The QA tool's first pass flagged "download pattern also matches the final result artifact" on five workflows; that is harmless (the
   download step runs before the final upload in the same job), so the check was dropped, not the workflows.
