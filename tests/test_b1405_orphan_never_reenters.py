"""B-1405 (NHPC 28 Oct 2026): a swing_rerouted_orphan paper row is an adopted holding, never an entry signal. After its
real row closed, the retry loop kept re-trying a real buy (9 share + 9 option-leg attempts, stopped only by the PFnet
gate). The entry function must return before any order path for that tag."""
from unittest.mock import MagicMock, patch

import main


def test_orphan_tag_never_reaches_an_order_path():
    conn = MagicMock()
    with patch.object(main, "is_real_swing_trading_enabled", return_value=True), \
         patch.object(main, "_swing_real_entry_session_open", return_value=True), \
         patch.object(main, "_maybe_place_swing_option_leg") as opt, \
         patch.object(main, "_log_real_attempt") as log, \
         patch.object(main, "_is_strategy_viable_for_real_money", return_value=True):
        main._maybe_place_real_swing_entry(conn, "NHPC.NS", 1, 72.74, 68.29, main.ORPHAN_SWING_STRATEGY_TAG)
    opt.assert_not_called()
    log.assert_not_called()
    conn.execute.assert_not_called()


def test_real_strategy_still_proceeds_past_the_guard():
    conn = MagicMock()
    with patch.object(main, "is_real_swing_trading_enabled", return_value=True), \
         patch.object(main, "_swing_real_entry_session_open", return_value=True), \
         patch.object(main, "_maybe_place_swing_option_leg") as opt:
        conn.execute.return_value.fetchone.return_value = (1,)  # already open -> stops right after the option leg
        main._maybe_place_real_swing_entry(conn, "NHPC.NS", 1, 72.74, 68.29, "gap_and_go")
    opt.assert_called_once()
