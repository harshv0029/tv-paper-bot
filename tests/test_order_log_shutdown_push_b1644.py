"""B-1644: a graceful shutdown pushes the git-tier order log once, bounded in time, and never raises."""
import time
from unittest.mock import patch

import main


def test_shutdown_hook_pushes_order_log():
    with patch("main._flush_pending_kotak_sends", return_value=0), \
            patch("main._git_tier_push_side_branch", return_value=True) as push:
        main._flush_kotak_sends_on_shutdown()
    push.assert_called_once_with("real_order_events")


def test_push_is_bounded_and_never_raises():
    with patch("main._git_tier_push_side_branch", side_effect=lambda n: time.sleep(2)):
        t0 = time.time()
        assert main._push_order_log_on_shutdown(timeout_s=0.2) is False
        assert time.time() - t0 < 1.5
    with patch("main._git_tier_push_side_branch", side_effect=RuntimeError("github down")):
        assert main._push_order_log_on_shutdown(timeout_s=1) is False
