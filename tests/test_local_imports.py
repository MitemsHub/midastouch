"""No test may resolve its imports outside this repository.

WHY THIS FILE EXISTS. This program's package was called `synthetic_trader` — the
name of the replacement-era synthetic-indices project — while a *complete* checkout
of that original project sat on `sys.path` via its editable install. Both provided
`synthetic_trader`, and for a while the other one won: this checkout's copy had no
`__init__.py`, so Python treated it as a namespace portion, and a regular package
found later on the path beats a namespace portion found earlier.

The consequence was not cosmetic. `tests/test_paper_broker.py` imported
`synthetic_trader.execution.paper_broker` from **the other repository** and its
fifteen passing tests were evidence about a file that is not in this repo. A green
suite that grades someone else's code is worse than a red one, because nobody
looks.

The package was renamed to `midas_prop` on 2026-09-20, which removes the collision
— but not the hazard, because the sibling still provides `synthetic_trader`. An
import written against the retired name does not fail; it quietly loads the other
repository's code. So the rules are stated as assertions:

1. no file in this repo may import the retired name at all (static check);
2. every module a test imports must live under this repository's root.

`tests/conftest.py` is what makes (2) true; this file is what notices when it stops
being true.
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"

#: The name this package had before 2026-09-20. Still provided by the sibling
#: checkout, so importing it is not an error — it is a silent swap.
RETIRED_PACKAGE_NAME = "synthetic_trader"

#: Top-level names this repository provides under `src/` (a real package, with an
#: `__init__.py`). These are the names that a second checkout on `sys.path` can
#: silently steal.
LOCAL_PACKAGES = tuple(sorted(
    p.name for p in (REPO / "src").iterdir()
    if p.is_dir() and (p / "__init__.py").is_file()
)) if (REPO / "src").is_dir() else ()


def resolves_inside_repo(name: str) -> bool:
    """Does `name` import from a file under this repository's root?"""
    mod = importlib.import_module(name)
    origin = getattr(mod, "__file__", None)
    if origin is None:                       # namespace package: look at its path
        paths = list(getattr(mod, "__path__", []))
        return bool(paths) and all(Path(p).is_relative_to(REPO) for p in paths)
    return Path(origin).resolve().is_relative_to(REPO.resolve())


def _imported_top_levels(path: Path) -> set[str]:
    """Top-level module names a Python file imports (absolute imports only)."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:                   # relative import: already in-repo
                continue
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def test_the_local_package_list_is_not_empty():
    """A guard over an empty set passes vacuously — which is how this class of
    failure hid in the first place."""
    assert LOCAL_PACKAGES, (
        "no package with an __init__.py was found under src/ — either the package "
        "markers were removed (which is what let the other checkout win) or this "
        "test is now vacuous")


@pytest.mark.parametrize("name", LOCAL_PACKAGES)
def test_each_local_package_resolves_inside_this_repo(name: str):
    mod = importlib.import_module(name)
    origin = getattr(mod, "__file__", "") or ""
    assert Path(origin).resolve().is_relative_to(REPO.resolve()), (
        f"`{name}` resolved to {origin!r}, which is OUTSIDE this repository. The "
        f"editable install of the other checkout is winning again; the fix is the "
        f"__init__.py markers under src/ plus the path order in tests/conftest.py")


def test_the_modules_the_suite_actually_uses_resolve_here():
    """The three submodules the tests and scripts import, by name.

    Named explicitly rather than discovered, because these are the ones whose
    theft was observed: `paper_broker` was imported from the other repository and
    its tests passed.
    """
    for name in ("midas_prop",
                 "midas_prop.risk.upcomers_rules",
                 "midas_prop.execution.prop_execution",
                 "midas_prop.execution.paper_broker"):
        assert resolves_inside_repo(name), f"{name} does not resolve into this repo"


def test_no_file_in_this_repo_imports_the_retired_package_name():
    """The rename's own guard, and the realistic way it rots.

    The sibling checkout still provides `synthetic_trader`, so a line copied out of
    a pre-rename doc, log or diff does not raise ImportError — it imports the other
    program's module and the test around it grades the wrong file. That is exactly
    how `test_paper_broker.py` passed while testing code this repo does not contain.
    """
    offenders = []
    for folder in ("tests", "scripts", "src"):
        for path in sorted((REPO / folder).rglob("*.py")):
            if RETIRED_PACKAGE_NAME in _imported_top_levels(path):
                offenders.append(str(path.relative_to(REPO)))
    assert not offenders, (
        f"file(s) import the retired package name `{RETIRED_PACKAGE_NAME}`, which "
        f"this repository no longer provides (it was renamed to `midas_prop` on "
        f"2026-09-20) but the sibling checkout DOES:\n  " + "\n  ".join(offenders) +
        "\n\nImporting it does not fail — it loads another repository's code.")


def test_every_test_module_imports_only_in_repo_copies_of_local_names():
    """The general rule: wherever a test names a local package, it must get ours.

    Walks every test file's absolute imports and, for any top-level name this repo
    provides, asserts the imported module resolves here. A new test that imports a
    local package which is somehow shadowed fails at its first import line.
    """
    checked = 0
    for path in sorted(TESTS.glob("test_*.py")):
        for name in sorted(_imported_top_levels(path) & set(LOCAL_PACKAGES)):
            checked += 1
            assert resolves_inside_repo(name), (
                f"{path.name} imports `{name}`, which resolves outside this repository")
    assert checked, "no test imported a local package — this check proved nothing"


def test_the_predicate_can_actually_fail():
    """Prove the check is not a tautology: a third-party module lives outside."""
    assert not resolves_inside_repo("pytest")
    assert resolves_inside_repo("midas_prop")


def test_no_module_in_the_suite_was_loaded_from_another_checkout():
    """Final sweep over what is actually loaded, catching an import this file's
    source scan could miss (computed names, plugin imports, conftest effects).

    The retired name is watched too: if it is ever loaded, the origin it came from
    is the whole point.
    """
    watched = set(LOCAL_PACKAGES) | {RETIRED_PACKAGE_NAME}
    offenders = []
    for name, mod in sorted(sys.modules.items()):
        if not name or name.startswith("_"):
            continue
        if name.split(".")[0] not in watched:
            continue
        origin = getattr(mod, "__file__", None)
        if not origin:
            continue
        p = Path(origin)
        if not p.resolve().is_relative_to(REPO.resolve()):
            offenders.append(f"{name} -> {origin}")
    assert not offenders, ("modules from another checkout are loaded:\n  "
                           + "\n  ".join(offenders))
