"""Shared test fixtures for the synthetic_trader test suite.

Clears module-level assembler caches between tests to prevent state
pollution — the GARCH forecaster, session filter, and fingerprint
detector caches in ``assembler.py`` retain mutable state from previous
``run_ticks`` / ``build_snapshot`` calls which can poison subsequent
WFO folds or backtest runs.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _hermetic_lv_broker_snapshot(monkeypatch, tmp_path):
    """VPS-era hermeticity (2026-09-18): the operator's real LV broker
    snapshot (artifacts/midas_lv_broker_state.json) must never leak into a
    test run. Point morning_status at a nonexistent temp path unless a test
    writes its own fixture file there."""
    import morning_status as _ms

    monkeypatch.setattr(
        _ms, "LV_BROKER_STATE_PATH", str(tmp_path / "lv_broker_state.json"))
    yield


@pytest.fixture(autouse=True)
def _clear_assembler_caches():
    """Auto-clear assembler caches before every test."""
    from synthetic_trader.features.assembler import clear_assembler_caches

    clear_assembler_caches()
    yield
    clear_assembler_caches()
