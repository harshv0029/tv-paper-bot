"""B-1648: only the instance holding the Upstash send lease sends real orders."""
import pytest

import instance_lease as L


class FakeRedis:
    """Upstash REST stand-in: interprets SET/GET and the two Lua scripts by their effect."""
    def __init__(self):
        self.kv, self.fail = {}, False

    def post(self, url, headers=None, json=None, timeout=None):
        if self.fail:
            raise ConnectionError("down")
        cmd, res = json, None
        if cmd[0] == "SET":
            self.kv[cmd[1]] = cmd[2]; res = "OK"
        elif cmd[0] == "GET":
            res = self.kv.get(cmd[1])
        elif cmd[0] == "EVAL" and "pexpire" in cmd[1]:
            key, me = cmd[3], cmd[4]
            if self.kv.get(key) == me: res = 1
            elif key not in self.kv: self.kv[key] = me; res = 2
            else: res = 0
        elif cmd[0] == "EVAL" and "del" in cmd[1]:
            key, me = cmd[3], cmd[4]
            res = 1 if self.kv.get(key) == me and self.kv.pop(key) else 0
        return type("R", (), {"json": lambda self_: {"result": res}})()


@pytest.fixture
def redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(L, "_creds", lambda: ("https://u", "t"))
    monkeypatch.setattr(L.requests, "post", r.post)
    monkeypatch.setattr(L, "_state", {"role": "unknown", "holder": None, "checked_at": 0.0, "error": None, "claims": 0})
    return r


def test_newest_instance_wins_and_old_one_stands_down(redis, monkeypatch):
    redis.kv[L.LEASE_KEY] = "old-instance"
    assert L.claim_at_startup() == "leader" and redis.kv[L.LEASE_KEY] == L.INSTANCE_ID
    assert L.order_block_reason() is None
    redis.kv[L.LEASE_KEY] = "newer-instance"  # a later deploy claims it
    L._state["checked_at"] = 0.0
    reason = L.order_block_reason()
    assert reason and "standby" in reason and "newer-instance" in reason


def test_lapsed_lease_is_reclaimed_and_release_only_deletes_own(redis):
    assert L.refresh() == "leader" and L._state["claims"] == 1  # key absent -> SET NX
    redis.kv[L.LEASE_KEY] = "other"
    assert L.release() is False and redis.kv[L.LEASE_KEY] == "other"
    assert L.role(now=10**12) == "standby"  # released: never reclaims, never sends
    redis.kv.pop(L.LEASE_KEY)
    assert L.role(now=10**12) == "standby"


def test_fail_open_when_upstash_down_or_unset(redis, monkeypatch):
    redis.fail = True
    assert L.refresh() == "unknown" and L.order_block_reason() is None
    monkeypatch.setattr(L, "_creds", lambda: (None, None))
    L._state["checked_at"] = 0.0
    assert L.order_block_reason() is None


def test_standby_blocks_every_send_through_records_send(redis, monkeypatch):
    import kotak_real_orders as kro
    redis.kv[L.LEASE_KEY] = "other"
    sent = []

    @kro._records_send("entry", "test send")
    def fake_send(sym, qty):
        sent.append(sym)
        return {"ok": True}
    res = fake_send("ABC-EQ", 1)
    assert res["ok"] is False and res["standby_instance"] is True and sent == []
    redis.kv[L.LEASE_KEY] = L.INSTANCE_ID
    L._state["checked_at"] = 0.0
    monkeypatch.setattr(kro, "_report_send", lambda *a, **k: None)
    assert fake_send("ABC-EQ", 1)["ok"] is True and sent == ["ABC-EQ"]


def test_scheduler_standby_check_is_fail_open(monkeypatch):
    import main
    monkeypatch.setattr(main.instance_lease, "role", lambda: "standby")
    assert main._lease_standby_now() is True
    monkeypatch.setattr(main.instance_lease, "role", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert main._lease_standby_now() is False


def test_superseded_leader_stops_sending_within_recheck_window(redis, monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(L.time, "time", lambda: t[0])
    assert L.claim_at_startup() == "leader"
    redis.kv[L.LEASE_KEY] = "new-deploy"
    t[0] += L.STANDBY_RECHECK_S + 1  # well inside RENEW_S
    assert L.order_block_reason() is not None
