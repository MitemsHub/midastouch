#!/usr/bin/env python3
"""Compare the assets the two checkouts share, and refuse to let them drift silently.

WHICH TWO CHECKOUTS. This one (`projects/MIDASTOUCH`, remote `MitemsHub/midastouch`)
and the sibling that owns the venue/methodology layer
(`projects/Upcomers-Venue`, formerly `projects/Synthetic Indices Bot`, remote
`MitemsHub/mitemshub-indices`). They are separate repositories that share a paper
chain, and until 2026-09-20 they even shared a package *name*, which is how this
checkout once ended up importing another repository's modules without noticing.

WHY A LINE-ENDING-AWARE COMPARISON IS THE WHOLE POINT. Measured 2026-09-19: shared
files that are semantically identical diverge in bytes only because one side is LF
and the other CRLF. A plain hash or `cmp` therefore reports a difference on every
one of them, every time, forever — and a check that always cries wolf is worse than
no check, because the operator learns to ignore it and that is the state in which a
REAL divergence (an edit on one side that never reached the other) passes unnoticed.
So the classification is three-way: IDENTICAL, LINE-ENDINGS ONLY (not a divergence),
and DIVERGED (a failure).

TWO POLICIES, BECAUSE THE FILES ARE NOT ALL THE SAME KIND OF THING.

* **vendored** — `src/midas_prop/execution/paper_broker.py` was copied into this repo
  from the sibling's `src/synthetic_trader/execution/paper_broker.py`. A copy that
  nobody re-checks is two files pretending to be one, so these four cases are:
  DIVERGED → **failure and non-zero exit**. This is the pair that matters most: the
  two checkouts' paper fills must agree or the paper record means nothing.
* **forked** — files that exist in both programs *by design* and are expected to
  differ now that both have their own venue (`scripts/paper_weekly.py` and
  `scripts/install_paper_task.ps1`, restored to the sibling by its `fdab02e` as "the
  two shared paper-chain scripts"). Divergence here is the honest state, so it is
  reported with its line count and never fails. What would be a finding is one side
  *vanishing*, which is why the pair stays listed.

Plus a sweep of the two package trees by name, so a file that is copied across later
cannot join the "shared but unchecked" set quietly: every basename present under both
`src/midas_prop/**` and `src/synthetic_trader/**` is classified and printed, and any
same-name file that DIVERGES is named as undeclared — whether it is a defect or a
vendored file that should be declared as one.

WHY IT REFUSES WHEN THE OTHER REPO IS MISSING, OR IS THIS ONE. "No divergences found"
because one side could not be read is not a pass: absence of evidence is reported as
an inability to check, the same rule the terminal resolvers follow. And comparing a
checkout with **itself** is worse than useless — it is a permanent green that looks
like coverage. The old default did exactly that (`--other` resolved to this repo), so
self-comparison is now a refusal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

#: Folder names the sibling checkout is known by, newest first. The sibling staged a
#: rename to `Upcomers-Venue` (`scripts/rename_project.py` there, dry-run by default),
#: so both names are resolved rather than one hardcoded.
SIBLING_DIR_NAMES = ("Upcomers-Venue", "Synthetic Indices Bot")

#: (this repo, the sibling) — VENDORED files. Their content must be identical on both
#: sides; ANY divergence is a failure. The second column exists because the packages
#: are no longer named the same thing, and a mapping is cheaper to read than a
#: filename rule that guesses.
VENDORED: tuple[tuple[str, str], ...] = (
    ("src/midas_prop/execution/paper_broker.py",
     "src/synthetic_trader/execution/paper_broker.py"),
    # The MQL5 gold program moved out of the sibling in the 2026-09-19 boundary
    # purge (the sibling now carries no `.mq5`/`.set` at all), so these report ABSENT
    # THERE. They stay listed on purpose: the same purge was followed by shared
    # scripts being copied BACK into the sibling, and a reappearance should be
    # compared rather than silently ignored.
    ("mql5/MIDASTOUCH/MidastouchAI.mq5", "mql5/MIDASTOUCH/MidastouchAI.mq5"),
    ("mql5/MIDASTOUCH/MidasOffsetProbe.mq5", "mql5/MIDASTOUCH/MidasOffsetProbe.mq5"),
    ("mql5/MIDASTOUCH/MidastouchAI_LV_gold.set", "mql5/MIDASTOUCH/MidastouchAI_LV_gold.set"),
    ("mql5/MIDASTOUCH/MidastouchAI_LV_TP15_M15_gold.set",
     "mql5/MIDASTOUCH/MidastouchAI_LV_TP15_M15_gold.set"),
    ("mql5/MIDASTOUCH/MidastouchAI_LV_TP15_M5_gold.set",
     "mql5/MIDASTOUCH/MidastouchAI_LV_TP15_M5_gold.set"),
    ("mql5/MIDASTOUCH/MidastouchAI_M1_gold.set", "mql5/MIDASTOUCH/MidastouchAI_M1_gold.set"),
    ("mql5/MIDASTOUCH/MidastouchAI_M1m_gold.set", "mql5/MIDASTOUCH/MidastouchAI_M1m_gold.set"),
    ("mql5/MIDASTOUCH/MidastouchAI_M1o_gold.set", "mql5/MIDASTOUCH/MidastouchAI_M1o_gold.set"),
    ("mql5/MIDASTOUCH/MidastouchAI_M1s_gold.set", "mql5/MIDASTOUCH/MidastouchAI_M1s_gold.set"),
    ("mql5/MIDASTOUCH/MidastouchAI_M1t_gold.set", "mql5/MIDASTOUCH/MidastouchAI_M1t_gold.set"),
)

#: (this repo, the sibling) — files both programs keep on purpose, expected to differ.
#: Reported with their line counts; never a failure. A disappearance IS reported.
FORKED: tuple[tuple[str, str], ...] = (
    ("scripts/paper_weekly.py", "scripts/paper_weekly.py"),
    ("scripts/install_paper_task.ps1", "scripts/install_paper_task.ps1"),
)

#: (this repo's package tree, the sibling's package tree) — swept by basename.
PACKAGE_TREES: tuple[tuple[str, str], ...] = (
    ("src/midas_prop", "src/synthetic_trader"),
)

IDENTICAL = "IDENTICAL"
LINE_ENDINGS_ONLY = "LINE-ENDINGS ONLY"
DIVERGED = "DIVERGED"
FORKED_EXPECTED = "FORKED (expected)"
MISSING_HERE = "ABSENT HERE"
MISSING_THERE = "ABSENT THERE"

#: The class names that mean "these two files no longer say the same thing".
DIVERGENT_CLASSES = frozenset({DIVERGED, FORKED_EXPECTED})


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def normalise(b: bytes) -> bytes:
    """Content with line endings and a BOM removed, so only real edits differ."""
    if b.startswith(b"\xef\xbb\xbf"):
        b = b[3:]
    return b.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def classify(mine: Path, theirs: Path) -> tuple[str, dict]:
    if not mine.is_file():
        return MISSING_HERE, {"mine_bytes": None, "their_bytes": None}
    if not theirs.is_file():
        return MISSING_THERE, {"mine_bytes": mine.stat().st_size}
    a, b = mine.read_bytes(), theirs.read_bytes()
    detail = {"mine_bytes": len(a), "their_bytes": len(b),
              "mine_sha": sha(a)[:12], "their_sha": sha(b)[:12]}
    if a == b:
        return IDENTICAL, detail
    if normalise(a) == normalise(b):
        detail["mine_ends"] = "CRLF" if b"\r\n" in a else "LF"
        detail["their_ends"] = "CRLF" if b"\r\n" in b else "LF"
        return LINE_ENDINGS_ONLY, detail
    na, nb = normalise(a).splitlines(), normalise(b).splitlines()
    detail["differing_lines"] = sum(1 for x, y in zip(na, nb) if x != y) + abs(
        len(na) - len(nb))
    detail["mine_lines"] = len(na)
    detail["their_lines"] = len(nb)
    return DIVERGED, detail


def resolve_sibling(explicit: str | None) -> tuple[Path | None, list[str]]:
    """The sibling checkout, or (None, candidates tried).

    Resolution refuses rather than guessing: an unreadable side reported as "no
    divergences" is the false green this tool exists to prevent.
    """
    if explicit:
        return Path(explicit).resolve(), [explicit]
    tried = []
    for name in SIBLING_DIR_NAMES:
        cand = (ROOT.parent / name)
        tried.append(str(cand))
        if cand.is_dir():
            return cand.resolve(), tried
    return None, tried


def tree_index(tree: Path) -> tuple[set[str], dict[str, list[Path]]]:
    """(relative paths, {basename: [paths]}) for every file under `tree`.

    Basenames are collected as LISTS because matching on the basename alone pairs
    files that are not each other: this repo's `risk/__init__.py` would be compared
    against the sibling's *root* `__init__.py` and reported as diverged forever. A
    basename is therefore only usable when it is unambiguous in that tree.
    """
    rels: set[str] = set()
    by_name: dict[str, list[Path]] = {}
    if not tree.is_dir():
        return rels, by_name
    for p in sorted(tree.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            rels.add(p.relative_to(tree).as_posix())
            by_name.setdefault(p.name, []).append(p)
    return rels, by_name


def counterpart(tree: Path, rel: str, by_name: dict[str, list[Path]]) -> Path | None:
    """The sibling file this one corresponds to, or None when that is not decidable.

    Same relative path inside the tree first (a real layout match); failing that, a
    basename that appears exactly once in the sibling tree (a file that moved layout
    while being shared). Anything more ambiguous is left out rather than guessed.
    """
    direct = tree / rel
    if direct.is_file():
        return direct
    same_name = by_name.get(Path(rel).name, [])
    return same_name[0] if len(same_name) == 1 else None


def display(cls: str, policy: str) -> str:
    """A forked pair that differs is the expected state, not a divergence."""
    if policy == "forked" and cls == DIVERGED:
        return FORKED_EXPECTED
    return cls


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--other", default=None,
                    help=f"path to the sibling checkout (default: try "
                         f"{', '.join(SIBLING_DIR_NAMES)} next to this repo)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    other, tried = resolve_sibling(a.other)
    print(f"=== CROSS-REPO DUPLICATION — {ROOT.name}  vs  "
          f"{other.name if other else '(unresolved)'} ===")
    print(f"  this repo: {ROOT}")
    print(f"  other:     {other}")
    if other is None:
        print("\nREFUSING: no sibling checkout found. Tried:\n  "
              + "\n  ".join(tried)
              + "\nReporting 'no divergences' because one side is unreadable would be "
                "a false green. Pass --other explicitly if it lives elsewhere.",
              file=sys.stderr)
        return 3
    if not other.is_dir():
        print(f"\nREFUSING: {other} is not a directory, so nothing can be compared. "
              f"Reporting 'no divergences' because one side is unreadable would be a "
              f"false green.", file=sys.stderr)
        return 3
    if other == ROOT.resolve():
        print(f"\nREFUSING: the sibling resolved to THIS repository ({other}). Comparing "
              f"a checkout with itself passes forever and proves nothing — that is how "
              f"the previous default behaved. Point --other at the other checkout.",
              file=sys.stderr)
        return 3

    results: list[dict] = []
    failures: list[str] = []

    print("\n-- vendored files (content must be identical; any divergence FAILS) --")
    for rel_mine, rel_theirs in VENDORED:
        cls, detail = classify(ROOT / rel_mine, other / rel_theirs)
        shown = display(cls, "vendored")
        results.append({"policy": "vendored", "mine": rel_mine, "theirs": rel_theirs,
                        "class": cls, **detail})
        label = f"[{shown:<16}] {rel_mine}"
        if rel_mine != rel_theirs:
            label += f"  <-> {rel_theirs}"
        if detail.get("differing_lines") is not None:
            label += (f"  ({detail['differing_lines']} of {detail['mine_lines']} "
                      f"lines differ)")
        print("  " + label)
        if cls == DIVERGED:
            failures.append(rel_mine)

    print("\n-- forked files (both programs keep them; differences are expected) --")
    for rel_mine, rel_theirs in FORKED:
        cls, detail = classify(ROOT / rel_mine, other / rel_theirs)
        shown = display(cls, "forked")
        results.append({"policy": "forked", "mine": rel_mine, "theirs": rel_theirs,
                        "class": cls, **detail})
        label = f"[{shown:<16}] {rel_mine}"
        if detail.get("differing_lines") is not None:
            label += (f"  ({detail['differing_lines']} of {detail['mine_lines']} "
                      f"lines differ — expected)")
        print("  " + label)
        if cls in (MISSING_HERE, MISSING_THERE):
            print(f"      NOTE: {shown} — a shared paper-chain file vanished on one "
                  f"side; confirm that was deliberate.")

    print("\n-- same basename under both package trees (nothing shared goes unchecked) --")
    declared = {(m, t) for m, t in VENDORED}
    swept = 0
    undeclared_diverged: list[str] = []
    for tree_mine, tree_theirs in PACKAGE_TREES:
        theirs_root = other / tree_theirs
        rels, by_name = tree_index(theirs_root)
        for p in sorted((ROOT / tree_mine).rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            rel = p.relative_to(ROOT / tree_mine).as_posix()
            mate = counterpart(theirs_root, rel, by_name)
            if mate is None:
                continue                       # nothing to compare, or not decidable
            rel_mine = p.relative_to(ROOT).as_posix()
            rel_theirs = mate.relative_to(other).as_posix()
            if (rel_mine, rel_theirs) in declared:
                continue                       # already reported as vendored
            swept += 1
            cls, detail = classify(p, mate)
            results.append({"policy": "swept", "mine": rel_mine, "theirs": rel_theirs,
                            "class": cls, **detail})
            note = ""
            if cls == DIVERGED:
                note = (f"  ({detail['differing_lines']} of {detail['mine_lines']} "
                        f"lines differ — NOT declared as vendored)")
                undeclared_diverged.append(rel_mine)
            elif cls == IDENTICAL:
                note = "  (identical — declare it in VENDORED if it is meant to stay so)"
            print(f"  [{cls:<16}] {rel:<22} {rel_mine} <-> {rel_theirs}{note}")
    if not swept:
        print("  (no same-named file found on both sides — the sweep proved nothing, "
              "which is itself worth knowing)")

    print()
    for cls in (IDENTICAL, LINE_ENDINGS_ONLY, FORKED_EXPECTED, DIVERGED, MISSING_HERE,
                MISSING_THERE):
        n = sum(1 for r in results if display(r["class"], r["policy"]) == cls)
        if n:
            print(f"  {cls:<18} {n}")
    print()
    if a.json:
        print(json.dumps(results, indent=1))

    if failures:
        print(f"FAIL: {len(failures)} vendored asset(s) have DIVERGED:")
        for f in failures:
            print(f"  - {f}")
        print("\nA vendored file is a copy, and a copy nobody re-checks is two files "
              "pretending to be one. Decide which side is authoritative and say so "
              "-- do not copy blindly over the other side without deciding, and do not "
              "delete this check to silence it.")
        return 1
    if undeclared_diverged:
        print("REVIEW: same-named files differ without being declared. Divergence is "
              "not automatically a defect (the two programs have their own venues), but "
              "it must be a decision rather than an accident. Either declare the file in "
              "VENDORED (content must then match) or in FORKED (differences expected):")
        for f in undeclared_diverged:
            print(f"  - {f}")
    if any(r["class"] in (MISSING_HERE, MISSING_THERE) for r in results):
        print("NOTE: some assets exist on only one side. Expected where a folder is "
              "local to one program, but confirm nothing was deleted by accident.")
    print("OK: no vendored asset has diverged in content. Line-ending differences are "
          "reported above and are not failures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
