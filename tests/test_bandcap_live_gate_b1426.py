"""B-1426: band_cap=live (Kotak resting-stop model) results below PFNET_LIVE_FLOOR close the real-money ENTRY gate through
the existing REPLAY_FAILED_TAGS mechanism (no new switch); exits/SL management are not gated by it."""
import inspect

import main
import strategy_registry as sr

CLOSED = (
    "base__cup_cheat_3c__long__1h__atr6_h30__v1",       # off 1.003 -> live 0.994
    "envelope__0d05_fade__long__1h__atr2d5_h30__v1",    # off 1.021 -> live 0.977
    "envelope__0d05_fade__long__1h__atr6_h18__v1",      # off 1.006 -> live 0.935
    "swingminrr__brk20_gate__short__1h__atr3_rr4__v1",  # 0.59 both modes
    "swingminrr__brk20_gatetarget__short__1h__atr3_rr4__v1",  # 0.53 both modes
)
STILL_OPEN_BY_BANDCAP = (
    "base__cup_cheat_3c__long__1h__atr2d5_h30__v1",   # live 1.017
    "envelope__0d05_fade__long__1h__atr4_h30__v1",    # live 1.040
    "envelope__0d05_fade__long__1h__atr6_h30__v1",    # live 1.062
)


def test_bandcap_live_below_floor_tags_are_refused(monkeypatch):
    monkeypatch.setattr(main, "REAL_ENTRY_REQUIRES_EXPLORER_STACK", False)
    monkeypatch.setattr(sr, "VIABLE_OVERRIDES", set())
    monkeypatch.setattr(main, "_load_viable_overrides", lambda: None)
    for t in CLOSED:
        assert t in main.REPLAY_FAILED_TAGS, t
        assert main._is_strategy_viable_for_real_money(t, check_switch=False) is False, t
        assert main._viability_verdict(t, check_switch=False)[1] == "replay_below_floor", t


def test_bandcap_live_failures_are_derived_from_the_newest_run():
    failed = main._bandcap_live_failed_tags()
    for t in CLOSED:
        assert t in failed
    for t in STILL_OPEN_BY_BANDCAP:
        assert t not in failed and t not in main.REPLAY_FAILED_TAGS
    # the band_cap=off registry rows are untouched (gate is closed by the live re-measurement, not a metric edit)
    reg = {d.name: d for d in sr.REGISTRY}
    assert reg["envelope__0d05_fade_mr__long__1h__atr2d5_h30__v1"].metrics.pfnet >= sr.PFNET_LIVE_FLOOR


def test_gate_only_touches_entries_not_exits():
    for fn in (main._envelope_long_1h_exit, main._cup_cheat_long_1h_exit):
        src = inspect.getsource(fn)
        assert "REPLAY_FAILED_TAGS" not in src and "_is_strategy_viable_for_real_money" not in src
