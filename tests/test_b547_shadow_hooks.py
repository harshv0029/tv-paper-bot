import inspect, main


def test_every_viability_gate_shadow_logs():
    for fn in (main._maybe_place_real_entry, main._maybe_place_real_short_entry,
               main._maybe_place_real_swing_entry):
        src = inspect.getsource(fn)
        i = src.index("skipped_strategy_not_viable")
        assert "_log_signal_shadow(" in src[i:i + 600], fn.__name__
        assert "hard_gate=True" in src[i:i + 600]


def test_option_gate_shadow_logs():
    src = inspect.getsource(main)
    i = src.index('skipped_strategy_not_viable", detail=f"strategy_tag=')
    assert "_log_signal_shadow(" in src[i:i + 300]


def test_shadow_log_never_raises():
    class Bad:
        def execute(self, *a):
            raise RuntimeError("x")
    main._log_signal_shadow(Bad(), "t", "S", "long", False, "r")
