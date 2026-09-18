#!/usr/bin/env python3
"""Compile the MIDASTOUCH EAs with MetaEditor and VERIFY the result.

Conventions (2026-09-18 — replaces ad-hoc shell compiles):
  * the source is compiled from a scratch folder INSIDE the terminal's
    MQL5 tree — MetaEditor silently no-ops (rc=0, no log, no .ex5) on
    sources outside it, which is the trap the ad-hoc compiles hid;
  * MetaEditor64 is invoked with an EXPLICIT /log path; the log is read
    (UTF-16LE), parsed for `Result: N errors, N warnings`, and the run
    fails unless errors == 0 AND warnings == 0 AND an .ex5 exists;
  * a compile whose log cannot be produced is a failure — "probably
    compiled" is not a state this repo accepts. The stray repo-root
    compile_log.txt debris this replaces is never recreated.

Usage:
  python scripts/compile_midas.py [--target PATH.mq5 ...] [--keep]

Default targets: mql5/MIDASTOUCH/MidastouchAI.mq5,
mql5/MIDASTOUCH/MidasOffsetProbe.mq5. Prints the produced .ex5 paths.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

DEFAULT_TARGETS = [
    REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5",
    REPO / "mql5" / "MIDASTOUCH" / "MidasOffsetProbe.mq5",
]

METAEDITOR_CANDIDATES = [
    Path(r"C:\Program Files\MetaTrader 5 Terminal\MetaEditor64.exe"),
    Path(r"C:\Program Files\MetaTrader 5\metaeditor64.exe"),
]

RESULT_RE = re.compile(
    r"Result:\s*(\d+)\s*errors?,\s*(\d+)\s*warnings?", re.I)

SCRATCH_ROOT = "MIDASTOUCH_compile"   # under <data folder>\MQL5\Experts


def find_metaeditor(explicit: str | None = None) -> Path:
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
        raise SystemExit(f"--editor path not found: {p}")
    for p in METAEDITOR_CANDIDATES:
        if p.exists():
            return p
    raise SystemExit(
        "MetaEditor64.exe not found in the known install locations — "
        "pass --editor explicitly")


def terminal_mql5_dir() -> Path:
    """The 49E0 terminal's MQL5 folder, via the harness's own locator."""
    import v28_sweep_runner as R
    data = R.data_folder_for_terminal()
    if not data:
        raise SystemExit("terminal data folder not locatable (origin.txt)")
    return Path(data) / "MQL5"


def compile_one(editor: Path, mq5: Path, mql5_dir: Path,
                keep: bool = False) -> dict:
    """Compile `mq5` from an in-tree scratch folder; verify 0/0 + .ex5."""
    if not mq5.exists():
        return {"target": str(mq5), "ok": False, "errors": None,
                "warnings": None, "ex5": None,
                "detail": "source file missing"}
    scratch = mql5_dir / "Experts" / SCRATCH_ROOT / mq5.stem
    scratch.mkdir(parents=True, exist_ok=True)
    dst = scratch / mq5.name
    dst.write_bytes(mq5.read_bytes())
    log = scratch / (mq5.stem + "_compile.log")
    subprocess.run([str(editor), f"/compile:{dst}", f"/log:{log}"],
                   capture_output=True, timeout=180)
    ex5 = dst.with_suffix(".ex5")
    try:
        if not log.exists():
            return {"target": mq5.name, "ok": False, "errors": None,
                    "warnings": None, "ex5": None,
                    "detail": "no compile log — editor silently skipped "
                              "(source must live under the terminal MQL5 tree)"}
        text = log.read_text(encoding="utf-16-le", errors="replace")
        m = RESULT_RE.search(text)
        if not m:
            return {"target": mq5.name, "ok": False, "errors": None,
                    "warnings": None, "ex5": None,
                    "detail": "log lacks a Result line — failure"}
        errors, warnings = int(m.group(1)), int(m.group(2))
        ok = errors == 0 and warnings == 0 and ex5.exists()
        detail = (f"ex5={ex5.stat().st_size}B" if ex5.exists()
                  else "0/0 log but no .ex5")
        return {"target": mq5.name, "ok": ok, "errors": errors,
                "warnings": warnings,
                "ex5": str(ex5) if ex5.exists() else None,
                "detail": detail}
    finally:
        if not keep:
            shutil.rmtree(scratch.parent / mq5.stem, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", action="append", default=[],
                    help="mq5 path (repeatable; defaults to the MIDASTOUCH pair)")
    ap.add_argument("--editor", default=None, help="MetaEditor64.exe path")
    ap.add_argument("--keep", action="store_true",
                    help="keep the in-tree scratch folder (default: removed)")
    args = ap.parse_args()
    editor = find_metaeditor(args.editor)
    mql5_dir = terminal_mql5_dir()
    targets = [Path(t) if Path(t).is_absolute() else REPO / t
               for t in args.target] or DEFAULT_TARGETS
    failed = 0
    for t in targets:
        r = compile_one(editor, t, mql5_dir, keep=args.keep)
        tag = "OK" if r["ok"] else "FAIL"
        print(f"  {tag} {r['target']}: errors={r['errors']} "
              f"warnings={r['warnings']} ({r['detail']})")
        failed += 0 if r["ok"] else 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
