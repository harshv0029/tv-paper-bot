# Test suite thumb rules

## 2026-10-28 (user: "divide amongst 4 ... make thumb rule for that, to save time")

The full pre-push suite always runs in parallel, never as one serial run:

    rm -f paper_trades.db && python3 scripts/run_tests_parallel.py --out <scratchpad>

- 4 shards by default (one per CPU in the container; `-n` overrides). Each shard runs in its own tar copy of the repo,
  so shards never share `paper_trades.db` or other files.
- Shards are balanced by each test file's last measured run time (`scripts/test_file_times.json`, rewritten after
  every run; a new file is estimated from its size). Greedy longest-first, so no shard waits on a heavy straggler.
- The push rule is unchanged: every shard must pass (exit 0), then `ast.parse` main.py, then pull and push.
- Parallel PROCESSES, not subagents: a subagent would run the same pytest command after rebuilding its own context, which
  costs time and tokens and adds no speed. Subagents stay for independent build/research work (see CLAUDE.md).
- A test that fails only in one grouping is an isolation bug (state leaking between tests in one process). Fix
  the test's isolation (monkeypatch the shared state); never re-run until it passes.
- Files run alphabetically inside each shard (the order the suite always used); heaviest-first order exposed 15
  order-dependent tests (backlog B-1400).
- Measured 2026-10-28: 4 shards, 170 s wall (about 2:40 each), against about 525 s for the old 2-chunk split.
