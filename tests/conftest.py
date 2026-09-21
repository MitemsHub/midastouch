"""Shared test fixtures for the MIDASTOUCH test suite.

Also the one place that decides where the suite's imports come from — which
matters more here than in most repositories.

WHY `src/` IS INSERTED FIRST, AND WHY THAT IS STILL LOAD-BEARING. This program's
Python package is `midas_prop`. Until 2026-09-20 it was called `synthetic_trader`,
which is also the name of the package in a *complete* other checkout installed
**editable** on this machine — its `.pth` adds that repository's `src/` to `sys.path`
during interpreter start-up, before any test runs. The rename removed that specific
collision; it did not remove the rule that made it dangerous, and the sibling still
provides `synthetic_trader`, so an import written against the old name loads another
repository's code instead of failing.

Which copy of a package wins is decided by (a) path order and (b) regular-package vs
namespace-portion precedence — and order alone was not enough. With no `__init__.py`
in this checkout's copy, Python treated it as a *namespace* portion, and a *regular*
package found later on the path beats a namespace portion found earlier. The suite
therefore imported the other repository's modules, and `tests/test_paper_broker.py`
passed by exercising a file that is not in this repository.

Three things keep it honest, and all are needed:

1. `__init__.py` files under `src/midas_prop/` (see that package's docstring)
   make this checkout's copy a regular package that cannot be shadowed by a
   namespace portion anywhere else on the path.
2. This file puts `src/` at the front of `sys.path`, so the first regular package
   found is ours.
3. `tests/test_local_imports.py` asserts both, and additionally fails on any import
   of the retired `synthetic_trader` name anywhere in this repo — the way this
   failure would actually come back.
"""

from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.abspath(os.path.join(_HERE, os.pardir))


def _prepend(path: str) -> None:
    """Put `path` first, moving it if something (a `.pth`) already added it."""
    while path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)


# src/ first: this is what makes `midas_prop` resolve to THIS checkout.
_prepend(os.path.join(_PARENT, "src"))
# scripts/ next: the suite imports `midas_*`, `mt5_*`, `gold_*` by bare name.
_prepend(os.path.join(_PARENT, "scripts"))


@pytest.fixture()
def repo_root():
    """Absolute path to the repository root (same for every test module)."""
    return _PARENT
