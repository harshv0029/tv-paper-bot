"""B-1605: pl1d tf/dir sweep BAR0_ONLY=1 keeps only 4h bucket-0 signals under distinct _b0 tags."""
import importlib
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


def _mod():
    return importlib.import_module("pl1d_tf_dir_sweep_replay")


def test_tags_unchanged_without_flag(monkeypatch):
    monkeypatch.delenv("BAR0_ONLY", raising=False)
    specs = _mod().cell_specs("4h", (6.0,), 20)
    assert "starc__fade_full__long__4h__atr6_h20__v1" in specs
    assert not any("_b0" in t for t in specs)


def test_b0_tags_4h_only(monkeypatch):
    monkeypatch.setenv("BAR0_ONLY", "1")
    m = _mod()
    s4 = m.cell_specs("4h", (6.0,), 20)
    assert "starc__fade_full__long__4h__atr6_h20_b0__v1" in s4 and all(sp["b0"] for sp in s4.values())
    assert not any("_b0" in t for t in m.cell_specs("1h", (6.0,), 20))


def test_is_bar0_bucket():
    m = _mod()
    assert m.is_bar0("2026-11-13 09:15:00+05:30")
    assert not m.is_bar0("2026-11-13 13:15:00+05:30")
    assert m.is_bar0("2026-11-13 03:45:00+00:00")  # 09:15 IST
