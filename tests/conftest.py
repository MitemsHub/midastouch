"""Shared test fixtures for the MIDASTOUCH test suite.

Hermeticity (2026-09-18): the operator's real LV broker snapshot
(artifacts/midas_lv_broker_state.json) must never leak into a test run.
Point morning_status at a nonexistent temp path unless a test writes its
own fixture file there.
"""

from __future__ import annotations

import os
import sys

import pytest

_scripts_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "scripts"))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)


@pytest.fixture(autouse=True)
def _hermetic_lv_broker_snapshot(monkeypatch, tmp_path):
    import morning_status as _ms

    monkeypatch.setattr(
        _ms, "LV_BROKER_STATE_PATH", str(tmp_path / "lv_broker_state.json"))
    yield
