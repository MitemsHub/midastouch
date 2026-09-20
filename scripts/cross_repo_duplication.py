#!/usr/bin/env python3
"""Compare the assets this repo shares with `MitemsHub/midastouch`, and fail on divergence.

WHY A LINE-ENDING-AWARE COMPARISON IS THE WHOLE POINT. Measured 2026-09-19: all eight
gold `.set` presets exist in both repos, are **semantically identical** (zero differing
lines once line endings are normalised), and differ in bytes only because this repo's
copies are LF while `midastouch`'s are CRLF. A plain hash or `cmp` therefore reports a
difference on every one of those files, every time, forever.

A divergence check that always cries wolf is worse than no check: the operator learns to
ignore it, which is exactly the state in which a REAL divergence (an edit on one side
that never reached the other) passes unnoticed. So the classification is three-way:

* **IDENTICAL** — byte-for-byte.
* **LINE-ENDINGS ONLY** — not a divergence. Reported, because it is real information
  (a byte-exact splice of a preset produces different bytes depending on the source),
  but explicitly not a failure.
* **DIVERGED** — content differs. **This is a failure and exits non-zero.**

WHY IT REFUSES WHEN THE OTHER REPO IS MISSING. "No divergences found" because one side
could not be read is not a pass. Absence of evidence is reported as an inability to
check, which is the same rule the terminal resolvers follow.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

#: Assets that must be identical in content on both sides. Paths are relative.
SHARED_ASSETS = (
    "mql5/MIDASTOUCH/MidastouchAI.mq5",
    "mql5/MIDASTOUCH/MidasOffsetProbe.mq5",
    "mql5/MIDASTOUCH/MidastouchAI_LV_gold.set",
    "mql5/MIDASTOUCH/MidastouchAI_LV_TP15_M15_gold.set",
    "mql5/MIDASTOUCH/MidastouchAI_LV_TP15_M5_gold.set",
    "mql5/MIDASTOUCH/MidastouchAI_M1_gold.set",
    "mql5/MIDASTOUCH/MidastouchAI_M1m_gold.set",
    "mql5/MIDASTOUCH/MidastouchAI_M1o_gold.set",
    "mql5/MIDASTOUCH/MidastouchAI_M1s_gold.set",
    "mql5/MIDASTOUCH/MidastouchAI_M1t_gold.set",
)

IDENTICAL = "IDENTICAL"
LINE_ENDINGS_ONLY = "LINE-ENDINGS ONLY"
DIVERGED = "DIVERGED"
MISSING_HERE = "ABSENT HERE"
MISSING_THERE = "ABSENT THERE"


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


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--other", default=str(ROOT.parent / "MIDASTOUCH"),
                    help="path to the sibling midastouch checkout")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    other = Path(a.other).resolve()
    print(f"=== CROSS-REPO DUPLICATION — {ROOT.name}  vs  {other.name} ===")
    print(f"  this repo: {ROOT}")
    print(f"  other:     {other}")
    if not other.is_dir():
        print(f"\nREFUSING: {other} is not a directory, so nothing can be compared. "
              f"Reporting 'no divergences' because one side is unreadable would be a "
              f"false green.", file=sys.stderr)
        return 3

    results: dict[str, list] = {}
    diverge: list[str] = []
    for rel in SHARED_ASSETS:
        cls, detail = classify(ROOT / rel, other / rel)
        results.setdefault(cls, []).append({"path": rel, **detail})
        if cls == DIVERGED:
            diverge.append(rel)
        line = f"  [{cls:<16}] {rel}"
        if detail.get("differing_lines") is not None:
            line += (f"  ({detail['differing_lines']} of {detail['mine_lines']} "
                     f"lines differ)")
        print(line)

    print()
    for cls, items in sorted(results.items()):
        print(f"  {cls:<16} {len(items)}")
    print()
    if diverge:
        print(f"FAIL: {len(diverge)} shared asset(s) have genuinely DIVERGED:")
        for d in diverge:
            print(f"  - {d}")
        print("\nThe gold strategy's authoritative home is MitemsHub/midastouch "
              "(see docs/REPO_IDENTITY_AND_CROSS_REPO_STATUS_20260919.md rule 1). An "
              "edit made on this side has reached nobody and has silently forked the "
              "strategy. Reconcile deliberately -- do not copy blindly over the other "
              "side without deciding which change is correct.")
        return 1
    if MISSING_THERE in results or MISSING_HERE in results:
        print("NOTE: some assets exist on only one side. Expected where a folder is "
              "local to one program, but confirm nothing was deleted by accident.")
    print("OK: no shared asset has diverged in content. Line-ending differences are "
          "reported above and are not failures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
