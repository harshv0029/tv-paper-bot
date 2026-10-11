import dataclasses
import json

import strategy_registry as sr
import strategy_registry_grossfill as gf


def test_fills_exact_only_and_never_overwrites(tmp_path, monkeypatch):
    base = next(s for s in sr.REGISTRY if s.metrics)

    def mk(nm, n, pf, g=0.0):
        return dataclasses.replace(base, name=nm, metrics=dataclasses.replace(base.metrics, n_trades=n, pfnet=pf, pfgross=g))

    rows = [mk("t_exact__x", 100, 1.2), mk("t_near__x", 100, 1.2), mk("t_has__x", 100, 1.2, 1.5), mk("t_none__x", 5, 1.2)]
    (tmp_path / "a.json").write_text(json.dumps({"rows": [
        {"tag": "t_exact__x", "n": 100, "pfnet": 1.205, "pfgross": 1.8},
        {"tag": "t_near__x", "n": 101, "pfnet": 1.2, "pfgross": 1.9},
        {"tag": "t_has__x", "n": 100, "pfnet": 1.2, "pfgross": 9.9}]}))
    monkeypatch.setattr(sr, "REGISTRY", rows)
    assert gf.apply(str(tmp_path)) == 1
    g = {s.name: s.metrics.pfgross for s in sr.REGISTRY}
    assert g == {"t_exact__x": 1.8, "t_near__x": 0.0, "t_has__x": 1.5, "t_none__x": 0.0}


def test_apply_on_real_registry_is_safe():
    before = sum(1 for s in sr.REGISTRY if s.metrics and not s.metrics.pfgross)
    gf.apply()
    assert sum(1 for s in sr.REGISTRY if s.metrics and not s.metrics.pfgross) <= before
