"""The MIDASTOUCH XAUUSD prop layer — venue rules, sizing/legality, paper fills.

This is the program's non-MT5 arithmetic. Everything here is gold-program code:

* :mod:`midas_prop.risk.upcomers_rules` — the venue's rules and costs, as
  arithmetic (3% daily, 6% trailing shield, 20% Best Day, commission per class).
* :mod:`midas_prop.execution.prop_execution` — sizing, legality and the arming
  switch: turns a risk budget into a lot size the broker accepts, or refuses with
  reasons.
* :mod:`midas_prop.execution.paper_broker` — the simulated broker behind the paper
  trader, matching the research harness's exit semantics.

RENAMED 2026-09-20. This package was called ``synthetic_trader`` — the name of the
Deriv synthetic-indices program this one replaced. The code was already gold code,
so the name was the only thing lying; it was renamed rather than explained. If you
meet ``synthetic_trader`` in a dated document or an older log, it is this package
under its old name. **The sibling checkout still provides a real
``synthetic_trader`` package**, so an import written against the old name does not
fail — it silently loads another repository's code. That is why
``tests/test_local_imports.py`` fails on any import of the retired name.

WHY THE ``__init__.py`` MARKERS ARE LOAD-BEARING. A *complete* checkout of the
original project is installed **editable** on this machine, so its ``src/`` is on
``sys.path`` from interpreter start-up. The name collision is gone, but the rule
that made it dangerous is not: a *regular* package found later on the path beats a
*namespace* portion found earlier, so a package here without an ``__init__.py`` can
still be shadowed by any other checkout that does have one. These markers keep this
checkout a regular package; the path order in ``tests/conftest.py`` puts it first;
``tests/test_local_imports.py`` asserts the result.
"""
