"""Memory leak (live 30-Oct-2026: RSS 1.08 GB -> 1.68 GB in 48 min, ~52k Thread objects retained with 26 alive).

Root cause: yf.download() defaults to threads=True, which runs even a single-ticker download through the
`multitasking` package, and multitasking appends every Thread it creates to the module-global config["TASKS"] list
and never removes it. Every Yahoo fetch (scan tick, 5m-bar sweep, prefetch, swing pass) leaked one Thread plus its
Event/Condition/locks/deque for the life of the process.
"""
import collections
import gc
import threading

import multitasking
import pandas as pd
import pytest
import yfinance.multi as ym

import data_fetch


class _FakeTicker:
    def __init__(self, ticker):
        self._price_history = None

    def history(self, **_kw):
        idx = pd.date_range("2026-10-30 09:15", periods=5, freq="5min", tz="Asia/Kolkata")
        return pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1}, index=idx)


def _thread_count():
    gc.collect()
    return sum(1 for o in gc.get_objects() if isinstance(o, threading.Thread))


@pytest.fixture
def offline_yf(monkeypatch):
    monkeypatch.setattr(ym, "Ticker", _FakeTicker)
    monkeypatch.setattr(data_fetch, "_DATA_CACHE", {})
    yield


def test_fetch_ohlc_does_not_retain_thread_objects(offline_yf):
    for i in range(5):  # warm-up
        data_fetch.fetch_ohlc(f"W{i}.NS", "1d", "5m")
    before_threads = _thread_count()
    before_tasks = len(multitasking.config["TASKS"])
    for i in range(200):
        df = data_fetch.fetch_ohlc(f"S{i}.NS", "1d", "5m")
        assert len(df) == 5
    assert _thread_count() - before_threads < 10
    assert len(multitasking.config["TASKS"]) - before_tasks < 10


def test_dead_multitasking_tasks_are_pruned():
    t = threading.Thread(target=lambda: None)
    t.start()
    t.join()
    multitasking.config["TASKS"].append(t)
    data_fetch._prune_multitasking_tasks()
    assert t not in multitasking.config["TASKS"]


def test_main_yf_download_calls_are_single_threaded():
    import ast
    import pathlib
    src = pathlib.Path(__file__).resolve().parent.parent / "main.py"
    tree = ast.parse(src.read_text())
    bad = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "download"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "yf"):
            kw = {k.arg: k.value for k in node.keywords}
            if not (isinstance(kw.get("threads"), ast.Constant) and kw["threads"].value is False):
                bad.append(node.lineno)
    assert not bad, f"yf.download without threads=False leaks a Thread per call (main.py lines {bad})"
