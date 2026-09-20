"""Shared test fixtures for the MIDASTOUCH test suite.

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

