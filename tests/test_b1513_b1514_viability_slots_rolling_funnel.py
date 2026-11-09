"""B-1513 (multiple View 1 viability rule slots, OR logic) and B-1514 (rolling-24h entry funnel that survives a
restart). No network: a fake in-memory Upstash replaces the REST helpers.

Run: pytest tests/test_b1513_b1514_viability_slots_rolling_funnel.py -v
"""
import json
import os
import tempfile
import time
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

import main
import strategy_registry as sr

TAG_A, REG_A = "orb-universal-score", "universal_score"                       # PFnet 0.05, hold None
TAG_B, REG_B = "orb-swing-gap-and-go", "gap_and_go__swing__long__1d__hold30__v1"  # PFnet 1.31

SLOT_A = {"name": "low pf", "enabled": True, "pf_min": 0.04, "pf_max": 0.06, "min_trades": 1000, "max_hold_hrs": None}
SLOT_B = {"name": "gap go", "enabled": True, "pf_min": 1.30, "pf_max": 1.32, "min_trades": 11000, "max_hold_hrs": 111}


@pytest.fixture
def remote(monkeypatch):
    store = {}
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "http://fake")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    monkeypatch.setattr(main, "_upstash_set", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(main, "_push_viable_stack_to_git", lambda *a, **k: False)
    main._generic_mirror_hydrated.clear()
    main._generic_mirror_last_hash.clear()
    return store


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    main._VIABLE_OVERRIDES_CACHE.clear()


def _insert_stack(label, names=()):
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO strategy_viable_stack (created_at, label, names) VALUES (?,?,?)",
                  (time.time(), label, json.dumps(list(names))))
        c.commit()


def _client():
    return TestClient(main.app)


# ---------------- B-1513 slots ----------------

def test_legacy_single_rule_migrates_to_slot_1_unchanged():
    _fresh_db()
    lab = "pfnet(1.05-100), min(30), maxhold(37.5)"
    _insert_stack(lab, ["ignored"])
    slots = main._stack_slots(lab)
    assert len(slots) == 1 and slots[0]["name"] == "Slot 1" and slots[0]["enabled"]
    active = main._load_viable_overrides()
    assert active == main._names_meeting_criteria(main._stack_criteria(lab))  # same set as before B-1513
    assert sr.VIABLE_STACK_ACTIVE is True
    assert set(main._VIABLE_ADMIT_SLOT.values()) <= {"Slot 1"}


def test_legacy_name_list_is_one_slot():
    _fresh_db()
    _insert_stack("explorer set", [REG_B])
    assert main._load_viable_overrides() == {REG_B}
    assert main._viability_admit_slot(REG_B) == "Slot 1 (saved list)"


def test_slots_are_or_and_record_the_admitting_slot(remote):
    _fresh_db()
    r = _client().post("/strategy-viable-override", json={"action": "set_slots", "slots": [SLOT_A, SLOT_B]})
    assert r.status_code == 200, r.text
    active = main._load_viable_overrides()
    assert REG_A in active and REG_B in active
    assert main._viability_admit_slot(REG_A) == "low pf"
    assert main._viability_admit_slot(REG_B) == "gap go"
    assert main._viability_verdict(TAG_B, check_switch=False) == (True, "override")
    st = r.json()["stack"][0]
    assert [s["name"] for s in st["slots"]] == ["low pf", "gap go"] and st["enabled_slots"] == 2
    assert st["count"] == len(active)


def test_first_slot_in_order_wins_and_disabled_slot_is_ignored(remote):
    _fresh_db()
    wide = {"name": "wide", "enabled": True, "pf_min": 0, "pf_max": 100, "min_trades": 0, "max_hold_hrs": None}
    off = dict(SLOT_A, name="off", enabled=False, pf_min=1.30, pf_max=1.32, min_trades=11000, max_hold_hrs=111)
    assert _client().post("/strategy-viable-override",
                          json={"action": "set_slots", "slots": [off, SLOT_B, wide]}).status_code == 200
    main._load_viable_overrides()
    assert main._viability_admit_slot(REG_B) == "gap go"   # "off" would match but is disabled
    assert main._viability_admit_slot(REG_A) == "wide"


def test_only_a_disabled_slot_gives_no_admission(remote):
    _fresh_db()
    a_off = dict(SLOT_A, enabled=False)
    assert _client().post("/strategy-viable-override",
                          json={"action": "set_slots", "slots": [a_off, SLOT_B]}).status_code == 200
    main._load_viable_overrides()
    assert REG_A not in sr.VIABLE_OVERRIDES
    assert main._viability_verdict(TAG_A, check_switch=False)[0] is False


def test_zero_enabled_slots_refused_and_fallback_is_no_stack(remote, monkeypatch):
    monkeypatch.setattr(main, "REAL_ENTRY_REQUIRES_EXPLORER_STACK", True)  # the live setting
    _fresh_db()
    r = _client().post("/strategy-viable-override",
                       json={"action": "set_slots", "slots": [dict(SLOT_A, enabled=False)]})
    assert r.status_code == 400
    # hand-edited data with zero enabled slots: same as no definition loaded (today's empty stack), never open
    _insert_stack(main._slots_label([main._slot_from_dict(dict(SLOT_B, enabled=False), 1)]))
    main._load_viable_overrides()
    assert sr.VIABLE_STACK_ACTIVE is False and not sr.VIABLE_OVERRIDES
    assert main._viability_verdict(TAG_B, check_switch=False) == (False, "no_stack")


def test_bad_slot_inputs_rejected(remote):
    _fresh_db()
    c = _client()
    assert c.post("/strategy-viable-override", json={"action": "set_slots", "slots": []}).status_code == 400
    assert c.post("/strategy-viable-override", json={"action": "set_slots",
                  "slots": [dict(SLOT_A, pf_min=2, pf_max=1)]}).status_code == 400
    assert c.post("/strategy-viable-override", json={"action": "set_slots",
                  "slots": [SLOT_A, dict(SLOT_B, name="LOW PF")]}).status_code == 400
    assert c.post("/strategy-viable-override", json={"action": "set_slots",
                  "slots": [SLOT_A] * (main.VIABLE_SLOTS_MAX + 1)}).status_code == 400


def test_slots_survive_a_wipe_via_the_dedicated_upstash_key(remote):
    _fresh_db()
    assert _client().post("/strategy-viable-override",
                          json={"action": "set_slots", "slots": [SLOT_A, SLOT_B]}).status_code == 200
    before = set(main._load_viable_overrides())
    _fresh_db()                                   # simulated Render restart: SQLite wiped
    assert main._restore_viable_stack_direct() >= 1
    main._VIABLE_OVERRIDES_CACHE.clear()
    assert set(main._load_viable_overrides()) == before
    assert main._viability_admit_slot(REG_B) == "gap go"


def test_undo_returns_to_the_previous_single_rule(remote):
    _fresh_db()
    _insert_stack("explorer set", [REG_B])
    c = _client()
    assert c.post("/strategy-viable-override", json={"action": "set_slots", "slots": [SLOT_A]}).status_code == 200
    assert REG_A in main._load_viable_overrides()
    assert c.post("/strategy-viable-override", json={"action": "undo"}).status_code == 200
    assert main._load_viable_overrides() == {REG_B}


def test_placed_entry_is_stamped_with_its_slot_and_counted(remote):
    _fresh_db()
    _client().post("/strategy-viable-override", json={"action": "set_slots", "slots": [SLOT_A, SLOT_B]})
    with closing(main.get_db()) as c:
        main._log_real_attempt(c, "FOO.NS", "B", "confirmed", strategy=TAG_B, detail="ok")
        det = c.execute("SELECT detail FROM real_trades").fetchone()[0]
        ev = c.execute("SELECT kind, slot, n FROM entry_funnel_events").fetchall()
        summary = main._viability_slots_summary(c, {"by_strategy": []})
    assert "viability_slot=gap_go" in det
    assert [tuple(r) for r in ev] == [("placed", "gap go", 1)]
    assert {s["name"]: s["placed_today"] for s in summary} == {"low pf": 0, "gap go": 1}


def test_viability_rejects_counted_per_slot_by_failing_factor(remote):
    _fresh_db()
    _client().post("/strategy-viable-override", json={"action": "set_slots", "slots": [SLOT_A, SLOT_B]})
    with closing(main.get_db()) as c:
        out = main._viability_slots_summary(c, {"by_strategy": [{"strategy": TAG_B, "count": 3}]})
    a = next(s for s in out if s["name"] == "low pf")
    b = next(s for s in out if s["name"] == "gap go")
    assert a["rejects_today"] == 3 and a["rejects_by_factor"].get("pfnet") == 3
    assert b["rejects_today"] == 0   # passes slot B now


# ---------------- B-1514 rolling 24 h ----------------

def _ev(kind, ts, strategy=TAG_B, status="", flag="", side="B", symbol="FOO.NS"):
    with closing(main.get_db()) as c:
        main._record_funnel_event(c, kind, strategy=strategy, side=side, symbol=symbol, status=status, flag=flag, ts=ts)
        c.commit()


def test_rolling_window_counts_last_24h_only_and_prunes_beyond_48h():
    _fresh_db()
    now = time.time()
    main._entry_funnel_last_prune[0] = now  # no prune during the inserts
    _ev("reject", now - 23 * 3600, status="skipped_low_balance", flag="money")
    _ev("reject", now - 23 * 3600, status="skipped_low_balance", flag="money")  # same bucket: n += 1
    _ev("reject", now - 30 * 3600, status="skipped_low_balance", flag="money")   # outside 24 h, kept
    _ev("reject", now - 50 * 3600, status="skipped_low_balance", flag="money")   # beyond 48 h
    w = main._entry_funnel_window(now - 24 * 3600, {TAG_B: ["swing"]})
    sw = w["categories"]["swing"]
    assert sw["blocked"] == 2 and sw["reject_flags"]["money"] == 2 and w["since_ist"].endswith("IST")
    main._entry_funnel_last_prune[0] = 0
    _ev("placed", now, status="confirmed")   # this insert runs the prune
    with closing(main.get_db()) as c:
        olds = c.execute("SELECT COUNT(*) FROM entry_funnel_events WHERE last_ts < ?", (now - 48 * 3600,)).fetchone()[0]
        total = c.execute("SELECT SUM(n) FROM entry_funnel_events").fetchone()[0]
    assert olds == 0 and total == 4   # 2 + 1 kept, 1 pruned, 1 new


def test_log_real_attempt_records_rejects_but_never_exits():
    _fresh_db()
    with closing(main.get_db()) as c:
        main._log_real_attempt(c, "FOO.NS", "B", "skipped_low_balance", strategy=TAG_B)
        main._log_real_attempt(c, "FOO.NS", "S", "confirmed", strategy=TAG_B, leg="exit")
        rows = c.execute("SELECT kind, status, flag FROM entry_funnel_events").fetchall()
    assert [tuple(r) for r in rows] == [("reject", "skipped_low_balance", "money")]


def test_blocked_triggers_are_buffered_then_flushed_as_viability():
    _fresh_db()
    main._FUNNEL_PENDING.clear()
    main._record_blocked_trigger(TAG_B)
    main._record_blocked_trigger(TAG_B)
    assert main._flush_funnel_pending() == 2
    w = main._entry_funnel_window(time.time() - 24 * 3600, {TAG_B: ["swing"]})
    assert w["categories"]["swing"]["blocked_triggers"] == 2
    assert w["categories"]["swing"]["reject_flags"]["viability"] == 2


def test_funnel_events_restored_after_restart(remote):
    _fresh_db()
    main.hydrate_generic_tables_from_external()
    _ev("reject", time.time() - 3600, status="skipped_low_balance", flag="money")
    assert "entry_funnel_events" in main._GENERIC_MIRROR_TABLES
    assert main.sync_generic_tables_external(only=("entry_funnel_events",)) >= 1
    _fresh_db()                                   # simulated Render restart
    main._generic_mirror_hydrated.clear()
    main.hydrate_generic_tables_from_external()
    w = main._entry_funnel_window(time.time() - 24 * 3600, {TAG_B: ["swing"]})
    assert w["categories"]["swing"]["reject_flags"]["money"] == 1


def test_entry_funnel_returns_today_and_rolling_blocks():
    _fresh_db()
    d = _client().get("/entry-funnel").json()
    assert "today" in d and "rolling_24h" in d and d["today"]["day"] == d["day"]
    assert d["rolling_24h"]["window_hours"] == 24 and "categories" in d["rolling_24h"]
    assert set(d["rolling_24h"]["categories"]) == set(d["categories"])
