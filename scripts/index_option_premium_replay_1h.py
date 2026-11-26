"""B-1746 step 3b: the premium-proxy replay on 1h candles over ~2 years (rising AND falling regimes), because the
60-day 5m/15m window (Oct-Nov 2026) was one strong NIFTY rally (+13.8% in a month). Research only."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("TFS", "1h")
os.environ.setdefault("FROM", "2024-12-01")
os.environ.setdefault("TO", "2026-11-26")
os.environ.setdefault("OUT_STEM", "index_option_premium_replay_1h")
import index_option_premium_replay as X  # noqa: E402

if __name__ == "__main__":
    X.main_cli()
