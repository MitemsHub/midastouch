#!/usr/bin/env python3
"""Fail when a file belonging to the OTHER trading program appears in either repo.

WHY THIS EXISTS. The two programs share a history and a desktop, so "keep them
apart" was a rule written in prose — and prose does not fail a build. It was
already violated twice by accident:

  * this repository carries a commit, ``904fb1c`` "Purge all non-MIDASTOUCH
    content from the repository (operator directive)", which is the boundary
    being *decided*: the ``MitemshubAI`` program and its ``mql5/MITEMSHUB_AI/``
    tree were removed because they do not belong to ``MidastouchAI``;
  * after that purge, ``mql5/MITEMSHUB_AI/presets/upcomers/README.md`` — a
    document that describes the *other* EA — was copied back in. Nothing failed,
    because nothing was checking.

A boundary that is only documented is a boundary that is only remembered. This
tool makes it mechanical: it scans each checkout for the other program's files
and **exits non-zero** when it finds one.

TWO CLASSES OF FILE, DELIBERATELY TREATED DIFFERENTLY:

* **Program files** — EA source, headers, compiled binaries and presets
  (``.mq5``/``.mqh``/``.ex5``/``.set``). These are ``FAIL``: the whole point of
  the separation is that you can never build or deploy the wrong program by
  mistake, and a stray preset is exactly how that happens.
* **Stray documents** — anything else under the other program's folder. These
  are ``WARN``: they cannot be compiled or attached to a chart, but they still
  mislead a reader, so they are named rather than hidden.

Usage:
    python scripts/program_boundary.py                 # this repo vs its sibling
    python scripts/program_boundary.py --other <path>  # an explicit sibling
    python scripts/program_boundary.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Suffixes that make a file *executable* in a trading sense: an EA you can
#: compile, a binary you can attach, a preset you can load. A stray one of these
#: is how the wrong program gets run.
PROGRAM_SUFFIXES = (".mq5", ".mqh", ".ex5", ".set")

#: The two programs, by the markers that identify their files. Kept as data so a
#: third program is a dict entry, not a rewrite.
PROGRAMS = {
    "midastouch": {
        "dirs": ("mql5/MIDASTOUCH",),
        "name_prefixes": ("MidastouchAI", "MidasOffsetProbe"),
        "set_aliases": (),
        "script_prefixes": ("midas_", "gold_"),
    },
    "itemshub": {
        "dirs": ("mql5/MITEMSHUB_AI",),
        "name_prefixes": ("MitemshubAI",),
        # A preset whose name carries the other program's instrument is that
        # program's, wherever it sits. Scoped to this program on purpose: applied
        # while scanning *for* midastouch it would flag the sibling's own presets.
        "set_aliases": ("VOL75", "Volatility_75", "Volatility_100"),
        "script_prefixes": (),
    },
}

#: Which program each checkout IS. The sibling folder name is the discriminator
#: (both were renamed, so the name is the only reliable label on disk).
REPO_PROGRAM = {"MIDASTOUCH": "midastouch", "Synthetic Indices Bot": "itemshub"}

#: Candidate sibling names, if --other is not given.
SIBLING_CANDIDATES = ("Synthetic Indices Bot", "MIDASTOUCH")

DEFAULT_SIBLING = "Synthetic Indices Bot"


def program_of(path: Path) -> str | None:
    """Which program does this checkout hold, from its folder name?"""
    return REPO_PROGRAM.get(path.name)


def _skip(rel: str) -> bool:
    """Directories that are not part of either program's shipped surface."""
    parts = Path(rel).parts
    return any(p in {".git", "__pycache__", "artifacts", ".pytest_cache"} for p in parts)


def scan(root: Path, foreign: dict) -> dict[str, list[str]]:
    """Files in `root` that belong to the program described by `foreign`.

    Returns ``{"program": [...], "document": [...]}`` where each entry is a
    repo-relative path. Program files are the failure; documents are the warning.
    """
    out: dict[str, list[str]] = {"program": [], "document": []}
    if not root.is_dir():
        return out
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if _skip(rel):
            continue
        in_foreign_dir = any(rel.startswith(d + "/") for d in foreign["dirs"])
        named = (path.name.startswith(foreign["name_prefixes"])
                 or (path.suffix.lower() == ".set"
                     and any(tok in path.name for tok in foreign["set_aliases"])))
        scriptish = (path.parent.name == "scripts"
                     and any(path.name.startswith(p) for p in foreign["script_prefixes"]))
        if not (in_foreign_dir or named or scriptish):
            continue
        bucket = "program" if path.suffix.lower() in PROGRAM_SUFFIXES else "document"
        out[bucket].append(rel)
    for bucket in out:
        out[bucket].sort()
    return out


def _find_sibling(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    for name in SIBLING_CANDIDATES:
        cand = ROOT.parent / name
        if cand.is_dir() and cand.resolve() != ROOT.resolve():
            return cand
    return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--other", default=None,
                    help=f"sibling checkout to scan (default: discover one of "
                         f"{', '.join(SIBLING_CANDIDATES)}; falls back to "
                         f"{DEFAULT_SIBLING!r})")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    here = program_of(ROOT)
    if here is None:
        print(f"REFUSING: this checkout is named {ROOT.name!r}, which is not a known "
              f"program ({', '.join(REPO_PROGRAM)}). A boundary check that cannot say "
              f"which side it is on cannot say what is foreign.", file=sys.stderr)
        return 3
    other_path = _find_sibling(a.other)
    report: dict = {"this_repo": {"path": str(ROOT), "program": here, "findings": None},
                    "other_repo": None}
    bad = 0

    mine = scan(ROOT, PROGRAMS[next(p for p in PROGRAMS if p != here)])
    report["this_repo"]["findings"] = mine
    print(f"=== PROGRAM BOUNDARY — {ROOT.name} is '{here}' ===")
    print(f"  this repo: {ROOT}")
    for rel in mine["program"]:
        print(f"  FAIL  foreign program file : {rel}")
    for rel in mine["document"]:
        print(f"  warn  foreign document     : {rel}")
    if not mine["program"] and not mine["document"]:
        print("  clean: no file belonging to the other program is present")
    bad += len(mine["program"])

    if other_path is None or not other_path.is_dir():
        print(f"\n  sibling: not found ({other_path}) — checked this repo only. A missing "
              f"sibling is not a pass; re-run with --other to check the other side.",
              file=sys.stderr)
    else:
        other_program = program_of(other_path)
        print(f"\n  other repo: {other_path}  (program {other_program!r})")
        if other_program is None:
            print(f"  note: {other_path.name!r} is not a known program name, so only the "
                  f"known foreign markers are scanned")
        theirs = scan(other_path, PROGRAMS[here])
        report["other_repo"] = {"path": str(other_path), "program": other_program,
                                "findings": theirs}
        for rel in theirs["program"]:
            print(f"  FAIL  foreign program file : {rel}")
        for rel in theirs["document"]:
            print(f"  warn  foreign document     : {rel}")
        if not theirs["program"] and not theirs["document"]:
            print("  clean: no '{here}' file is present there")
        bad += len(theirs["program"])

    print()
    if bad:
        print(f"BOUNDARY VIOLATED: {bad} program file(s) belong to the other program. "
              f"These can be compiled, attached or loaded by mistake — move them to their "
              f"own repository, or delete them.")
    else:
        print("OK: no program file crosses the boundary. (Documents, if any, are listed "
              "above as warnings — they mislead a reader but cannot be built or deployed.)")
    if a.json:
        print(json.dumps(report, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
