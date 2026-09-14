"""
Tests for Module 479 - Research Reproducibility Engine
(app/research/reproducibility.py). See that module's docstring for the
DPR source section (13) and implementation assumptions.
"""
import sqlite3
import uuid

import pytest

from app.research.reproducibility import (
    ImmutableManifestError,
    ResearchReproducibilityEngineService,
    ResearchReproducibilityError,
)


@pytest.fixture
def svc():
    conn = sqlite3.connect(":memory:")
    return ResearchReproducibilityEngineService(conn)


def _run_kwargs(svc, **overrides):
    sv_id = svc.register_strategy_version("mtf_engulfing", "v1.0", "codehash-v1")
    ds_id = svc.register_dataset("nse_60d_5m", "datahash-1")
    base = dict(
        strategy_version_id=sv_id,
        dataset_id=ds_id,
        parameters={"sma_fast": 9, "sma_slow": 21},
        execution_assumptions={"slippage_pct": 0.05},
        cost_model={"brokerage_pct": 0.002},
        test_period={"start": "2026-07-01", "end": "2026-08-30"},
        correlation_id=str(uuid.uuid4()),
        idempotency_key=str(uuid.uuid4()),
    )
    base.update(overrides)
    return base


# --- AC-479-01: old and new strategy code versions are separate strategies -

def test_registering_same_name_and_hash_twice_returns_same_id(svc):
    id1 = svc.register_strategy_version("mtf_engulfing", "v1.0", "codehash-v1")
    id2 = svc.register_strategy_version("mtf_engulfing", "v1.0", "codehash-v1")
    assert id1 == id2


def test_same_strategy_name_different_hash_is_a_new_separate_strategy(svc):
    id_old = svc.register_strategy_version("mtf_engulfing", "v1.0", "codehash-v1")
    id_new = svc.register_strategy_version("mtf_engulfing", "v2.0", "codehash-v2")
    assert id_old != id_new

    # the old version's row must be untouched, not overwritten
    row = svc._conn.execute(
        "SELECT code_version FROM strategy_versions WHERE id = ?", (id_old,)
    ).fetchone()
    assert row[0] == "v1.0"


def test_dataset_registration_is_keyed_by_hash(svc):
    id1 = svc.register_dataset("nse_60d_5m", "hash-a")
    id2 = svc.register_dataset("nse_60d_5m_relabel", "hash-a")  # same content, new label
    assert id1 == id2  # hash identity wins, not the label


# --- AC-479-03: all hashes are captured before execution starts ------------

def test_manifest_hash_is_present_immediately_on_creation_while_running(svc):
    run = svc.create_backtest_run(**_run_kwargs(svc))
    assert run.status == "RUNNING"
    assert run.manifest_hash and len(run.manifest_hash) == 64  # sha256 hex


def test_manifest_hash_is_deterministic_for_identical_inputs(svc):
    kwargs = _run_kwargs(svc)
    run1 = svc.create_backtest_run(**kwargs)
    kwargs2 = _run_kwargs(svc, idempotency_key=str(uuid.uuid4()))
    run2 = svc.create_backtest_run(**kwargs2)
    assert run1.manifest_hash == run2.manifest_hash


def test_different_parameters_give_different_manifest_hash(svc):
    run1 = svc.create_backtest_run(**_run_kwargs(svc))
    run2 = svc.create_backtest_run(**_run_kwargs(
        svc, idempotency_key=str(uuid.uuid4()), parameters={"sma_fast": 12, "sma_slow": 26}
    ))
    assert run1.manifest_hash != run2.manifest_hash


def test_unknown_strategy_version_is_rejected(svc):
    with pytest.raises(ResearchReproducibilityError, match="UNKNOWN_STRATEGY_VERSION"):
        svc.create_backtest_run(**_run_kwargs(svc, strategy_version_id="does-not-exist"))


def test_unknown_dataset_is_rejected(svc):
    with pytest.raises(ResearchReproducibilityError, match="UNKNOWN_DATASET"):
        svc.create_backtest_run(**_run_kwargs(svc, dataset_id="does-not-exist"))


# --- AC-479-02: a completed manifest is immutable ---------------------------

def test_completing_a_run_persists_results_and_artifacts(svc):
    run = svc.create_backtest_run(**_run_kwargs(svc))
    completed = svc.complete_backtest_run(
        run.id, results={"pf_net": 1.3, "win_rate": 42.0}, artifact_hashes=["h1", "h2"]
    )
    assert completed.status == "COMPLETED"
    assert completed.results["pf_net"] == 1.3
    assert completed.artifact_hashes == ["h1", "h2"]
    assert completed.completed_at is not None


def test_completing_an_already_completed_run_is_rejected(svc):
    run = svc.create_backtest_run(**_run_kwargs(svc))
    svc.complete_backtest_run(run.id, results={"pf_net": 1.3}, artifact_hashes=["h1"])
    with pytest.raises(ImmutableManifestError):
        svc.complete_backtest_run(run.id, results={"pf_net": 999.0}, artifact_hashes=["tampered"])

    # original results must be untouched
    still = svc.get_decision(run.id)
    assert still.results["pf_net"] == 1.3


def test_completing_unknown_run_is_rejected(svc):
    with pytest.raises(ResearchReproducibilityError, match="RUN_NOT_FOUND"):
        svc.complete_backtest_run("does-not-exist", results={}, artifact_hashes=[])


# --- idempotency -------------------------------------------------------------

def test_duplicate_idempotency_key_returns_original_run_not_a_new_one(svc):
    key = str(uuid.uuid4())
    kwargs1 = _run_kwargs(svc, idempotency_key=key)
    run1 = svc.create_backtest_run(**kwargs1)
    kwargs2 = _run_kwargs(svc, idempotency_key=key, parameters={"sma_fast": 999})
    run2 = svc.create_backtest_run(**kwargs2)
    assert run1.id == run2.id
    assert run2.parameters == run1.parameters  # not the "different" parameters from kwargs2

    count = svc._conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0]
    assert count == 1


# --- reproduce ---------------------------------------------------------------

def test_reproduce_returns_full_pinned_manifest(svc):
    run = svc.create_backtest_run(**_run_kwargs(svc))
    repro = svc.reproduce(run.id)
    assert repro["run_id"] == run.id
    assert repro["strategy_name"] == "mtf_engulfing"
    assert repro["code_hash"] == "codehash-v1"
    assert repro["data_hash"] == "datahash-1"
    assert repro["manifest_hash"] == run.manifest_hash


def test_reproduce_unknown_run_raises(svc):
    with pytest.raises(ResearchReproducibilityError, match="RUN_NOT_FOUND"):
        svc.reproduce("does-not-exist")


def test_get_decision_missing_run_returns_none(svc):
    assert svc.get_decision("does-not-exist") is None


def test_health(svc):
    assert svc.health()["status"] == "OK"
