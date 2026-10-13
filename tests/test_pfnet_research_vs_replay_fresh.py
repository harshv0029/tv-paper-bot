import subprocess
import sys


def test_research_vs_replay_doc_is_fresh():
    r = subprocess.run([sys.executable, "scripts/gen_pfnet_research_vs_replay.py", "--check"])
    assert r.returncode == 0, "run: python3 scripts/gen_pfnet_research_vs_replay.py"
