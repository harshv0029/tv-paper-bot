"""B-1383: automated data-sync commits to main must not redeploy Render.

27 Oct 2026: sync/reconcile commits restarted the live bot three times in 10 min (14:07, 14:09, 14:17 IST),
each time before the F&O candle feed finished resolving its ~210-stock universe, so option trading never
got candles. Render skips the auto-deploy for a commit whose message has "[skip render]"."""
import pathlib
import re

WF = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows"
DATA_ONLY = ["collect-run-artifacts.yml", "intraday-collect.yml", "journal-sync.yml", "kotak-pnl-audit.yml",
             "kotak-reconcile.yml", "kotak-sl-snapshot.yml", "sector-rotation-backtest.yml", "table-git-sync.yml",
             "tracked-union-sync.yml", "viable-stack-sync.yml"]


def test_data_only_sync_commits_skip_render():
    for name in DATA_ONLY:
        lines = [l for l in (WF / name).read_text().splitlines() if re.search(r'git commit -m "', l)]
        assert lines, name
        for l in lines:
            msg = re.search(r'git commit -m "(.*?)"\s*(\|\||$)', l.strip() + " ")
            assert msg and "[skip render]" in msg.group(1), f"{name}: {l.strip()}"


def test_deploy_gate_merge_still_deploys():
    assert "[skip render]" not in (WF / "deploy-gate.yml").read_text()
