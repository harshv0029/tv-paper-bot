"""B-1737: a trail raise moves the resting SL in place (modify-order); cancel-then-place only as a fallback."""
from unittest.mock import MagicMock, patch

import kotak_real_orders as kro


def _env(resp, status):
    client = MagicMock()
    client.modify_order.return_value = resp
    return [patch("kotak_neo.login", return_value=client),
            patch("kotak_real_orders._before_equity_open", return_value=False),
            patch("kotak_real_orders._in_closing_session", return_value=False),
            patch("kotak_real_orders._tick_size_for", return_value=0.05),
            patch("kotak_real_orders._confirm_order_status", return_value=status),
            patch("instance_lease.order_block_reason", return_value=None)], client


def _run(ps, fn):
    for p in ps:
        p.start()
    try:
        return fn()
    finally:
        for p in ps:
            p.stop()


def test_modify_ok_keeps_same_order():
    ps, client = _env({"stat": "Ok", "nOrdNo": "111"}, {"status": "trigger pending", "row": {"trgPrc": "1150.00"}})
    res = _run(ps, lambda: kro.modify_resting_stop("ZYDUSLIFE-EQ", "111", 1, 1150.0))
    assert res["ok"] and res["order_id"] == "111" and res["action"] == "modified"
    kw = client.modify_order.call_args.kwargs
    assert kw["order_type"] == "SL" and kw["trigger_price"] == "1150.0" and kw["price"] == "1150.0"


def test_modify_on_triggered_order_is_terminal():
    ps, _ = _env({"stat": "Ok"}, {"status": "complete", "row": {}})
    res = _run(ps, lambda: kro.modify_resting_stop("X-EQ", "111", 1, 100.0))
    assert not res["ok"] and res["terminal"]


def test_modify_refused_not_ok():
    ps, _ = _env({"stat": "Not_Ok", "errMsg": "x"}, {"status": "trigger pending", "row": {}})
    res = _run(ps, lambda: kro.modify_resting_stop("X-EQ", "111", 1, 100.0))
    assert not res["ok"] and not res.get("terminal")


def test_no_modify_after_1515():
    with patch("kotak_real_orders._before_equity_open", return_value=False), \
            patch("kotak_real_orders._in_closing_session", return_value=True), \
            patch("instance_lease.order_block_reason", return_value=None), \
            patch("kotak_neo.login") as login:
        assert not kro.modify_resting_stop("X-EQ", "1", 1, 100.0)["ok"]
        login.assert_not_called()


def test_small_step_is_skipped():
    assert kro.trail_step_too_small(1135.10, 1136.00)       # 0.08% < 0.10%
    assert not kro.trail_step_too_small(1135.10, 1140.00)


LIVE = [{"order_id": "111", "trigger": 1100.0, "qty": 1}]


def test_decide_uses_modify_not_cancel():
    with patch("kotak_real_orders._in_closing_session", return_value=False), \
            patch("kotak_real_orders.modify_resting_stop",
                  return_value={"ok": True, "order_id": "111", "trigger_price": 1150.0, "action": "modified"}), \
            patch("kotak_real_orders.cancel_real_order") as cancel, \
            patch("kotak_real_orders.place_real_stop_loss") as place:
        res = kro._ensure_resting_sl_decide("Z-EQ", 1, 1150.0, 1150.0, list(LIVE))
    assert res["action"] == "modified"
    cancel.assert_not_called()
    place.assert_not_called()


def test_decide_falls_back_when_modify_fails():
    with patch("kotak_real_orders._in_closing_session", return_value=False), \
            patch("kotak_real_orders.modify_resting_stop", return_value={"ok": False, "detail": "x"}), \
            patch("kotak_real_orders.cancel_real_order") as cancel, \
            patch("kotak_real_orders.place_real_stop_loss",
                  return_value={"ok": True, "order_id": "222", "trigger_price": 1150.0}):
        res = kro._ensure_resting_sl_decide("Z-EQ", 1, 1150.0, 1150.0, list(LIVE))
    assert res["action"] == "replaced"
    cancel.assert_called_once()


def test_decide_never_stacks_on_triggered_stop():
    with patch("kotak_real_orders._in_closing_session", return_value=False), \
            patch("kotak_real_orders.modify_resting_stop", return_value={"ok": False, "terminal": True}), \
            patch("kotak_real_orders.cancel_real_order") as cancel, \
            patch("kotak_real_orders.place_real_stop_loss") as place:
        res = kro._ensure_resting_sl_decide("Z-EQ", 1, 1150.0, 1150.0, list(LIVE))
    assert res["action"] == "modify_order_not_live"
    cancel.assert_not_called()
    place.assert_not_called()


def test_decide_small_step_keeps_current_stop():
    with patch("kotak_real_orders._in_closing_session", return_value=False), \
            patch("kotak_real_orders.modify_resting_stop") as mod:
        res = kro._ensure_resting_sl_decide("Z-EQ", 1, 1100.5, 1100.5, list(LIVE))
    assert res["action"] == "adopted_small_step" and res["trigger_price"] == 1100.0
    mod.assert_not_called()
