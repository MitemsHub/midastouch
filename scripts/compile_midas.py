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
  python scripts/compile_midas.py [--target PATH.mq5 ...] [--deploy] [--keep]

  * `--deploy` copies a VERIFIED .ex5 to the two places it can be attached from: the
    repo (`mql5/MIDASTOUCH/MidastouchAI.ex5`) and the terminal's own Experts tree
    (`<data folder>\\MQL5\\Experts\\MIDASTOUCH\\`). Without it a successful compile
    leaves nothing behind — the    scratch folder is deleted — so a chart keeps loading
    the previous build and the source can silently outrun the binary. Each copy is
    read back and hash-compared, and the line prints `source=… ex5=…` because the
    compiler is not bit-reproducible: provenance is the recorded pair, not a mismatch.

  * the REGISTERED deploy for the paper arms remains `scripts/midas_deploy_v118.py`:
    stop -> copy -> sha256 verify -> relaunch, gated on the cert chain. `--deploy` here
    is the manual-attach equivalent (no chain gate) and MT5 re-initialises whatever
    chart is running the EA, so it is not a substitute for that sequence mid-cert.

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
    """The live terminal's MQL5 folder, resolved by ACCOUNT IDENTITY.

    Was `v28_sweep_runner.data_folder_for_terminal()`, which located the V75
    TESTER terminal by matching its install directory against a pinned exe path.
    That is the wrong terminal for this program twice over: it is the indices
    tester, not the Upcomers install, and the pin spoke for an era that has
    ended. It was also the last live dependency on the indices engine —
    `scripts/audit_program_surface.py` reported it as the one place where a
    current entry point still reached into dead code.

    "Which terminal are we compiling for" is an identity question, because an
    install that merely BOOTED also has a fresh journal, and a compile into the
    wrong tree yields an .ex5 that never runs. `mt5_terminals.resolve_terminal()`
    answers it from the account named in the journals and REFUSES when nothing
    qualifies rather than defaulting to whatever was touched last.
    """
    import mt5_terminals as term
    try:
        td, why = term.resolve_terminal()
    except term.TerminalNotFound as exc:
        raise SystemExit(f"cannot locate the live terminal to compile into:\n{exc}")
    mql5 = Path(td) / "MQL5"
    if not mql5.is_dir():
        raise SystemExit(
            f"resolved terminal has no MQL5 tree: {mql5}\n(chosen by {why})"
        )
    return mql5


def deploy_paths(mq5: Path, mql5_dir: Path) -> list[Path]:
    """Every place a verified .ex5 must live to be attachable.

    Two destinations, because they answer different questions: the repo copy is the
    record of what was built, and the terminal copy is what a chart actually loads. The
    terminal path is `<data folder>\\MQL5\\Experts\\<source folder>\\<stem>.ex5` — MT5
    attaches from the Experts tree, under a folder named after the source's own folder,
    so the derivation is mechanical rather than remembered.
    """
    name = mq5.with_suffix(".ex5").name
    return [mq5.with_suffix(".ex5"),
            mql5_dir / "Experts" / mq5.parent.name / name]


def sha256_of(p: Path) -> str:
    import hashlib
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def build_fingerprint(mq5: Path, ex5: Path) -> str:
    """`source -> binary`, both truncated, for the deploy line.

    MEASURED, 2026-09-20: MetaEditor is **not bit-reproducible**. Two compiles of one
    unchanged source produced 94,780B and 95,012B. So a binary can never be shown to
    belong to a source by recompiling and comparing hashes — the only honest provenance
    is the pair recorded at the moment the artifact was produced and copied. That is what
    this line prints, and why it is printed at all.

    Call it INSIDE `compile_one`: the scratch folder (the only copy of the binary) is
    removed in that function's `finally`, so a fingerprint taken later raises rather than
    printing. That failure is not hypothetical — it was the first version of this call.
    """
    return f"source={sha256_of(mq5)[:8]} ex5={sha256_of(ex5)[:8]}"


def deploy_ex5(ex5: Path, mq5: Path, mql5_dir: Path) -> list[str]:
    """Copy a VERIFIED .ex5 to every attachable location. Never called on a failure.

    MEASURED GAP, 2026-09-20: this script verified compiles and then DELETED the binary
    with its scratch folder, so the attachable `.ex5` could not follow the source. The
    terminal held a 20:17 build while the 23:02 source compiled clean at a different
    size — a chart would have loaded a binary that no longer matched the pin tests.
    Verification that cannot be attached is not a deploy.

    Each copy is read back and hash-compared against the scratch artifact: a truncated or
    locked-destination copy fails loudly here rather than becoming a chart's silent build.
    """
    fresh = sha256_of(ex5)
    out: list[str] = []
    for dest in deploy_paths(mq5, mql5_dir):
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ex5, dest)
        if sha256_of(dest) != fresh:
            raise RuntimeError(f"deploy copy does not match the compiled artifact: {dest}")
        out.append(str(dest))
    return out


def compile_one(editor: Path, mq5: Path, mql5_dir: Path,
                keep: bool = False, deploy: bool = False) -> dict:
    """Compile `mq5` from an in-tree scratch folder; verify 0/0 + .ex5, then deploy."""
    if not mq5.exists():
        return {"target": str(mq5), "ok": False, "errors": None,
                "warnings": None, "ex5": None, "deployed": [], "fingerprint": "",
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
                    "warnings": None, "ex5": None, "deployed": [], "fingerprint": "",
                    "detail": "no compile log — editor silently skipped "
                              "(source must live under the terminal MQL5 tree)"}
        text = log.read_text(encoding="utf-16-le", errors="replace")
        m = RESULT_RE.search(text)
        if not m:
            return {"target": mq5.name, "ok": False, "errors": None,
                    "warnings": None, "ex5": None, "deployed": [], "fingerprint": "",
                    "detail": "log lacks a Result line — failure"}
        errors, warnings = int(m.group(1)), int(m.group(2))
        ok = errors == 0 and warnings == 0 and ex5.exists()
        detail = (f"ex5={ex5.stat().st_size}B" if ex5.exists()
                  else "0/0 log but no .ex5")
        # Deploy and fingerprint INSIDE the try: the scratch folder (and the only copy
        # of the binary) is removed in the finally block below unless --keep was passed.
        deployed = deploy_ex5(ex5, mq5, mql5_dir) if ok and deploy else []
        return {"target": mq5.name, "ok": ok, "errors": errors,
                "warnings": warnings,
                "ex5": str(ex5) if ex5.exists() else None,
                "deployed": deployed,
                "fingerprint": build_fingerprint(mq5, ex5) if ok else "",
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
    ap.add_argument("--deploy", action="store_true",
                    help="after 0/0, copy the verified .ex5 to the repo and to the "
                         "terminal's Experts tree (default: verified only, and the "
                         "binary is discarded with the scratch folder)")
    args = ap.parse_args()
    editor = find_metaeditor(args.editor)
    mql5_dir = terminal_mql5_dir()
    targets = [Path(t) if Path(t).is_absolute() else REPO / t
               for t in args.target] or DEFAULT_TARGETS
    failed = 0
    for t in targets:
        r = compile_one(editor, t, mql5_dir, keep=args.keep, deploy=args.deploy)
        tag = "OK" if r["ok"] else "FAIL"
        print(f"  {tag} {r['target']}: errors={r['errors']} "
              f"warnings={r['warnings']} ({r['detail']})")
        if r["ok"] and r.get("deployed"):
            fp = r.get("fingerprint") or ""
            for p in r["deployed"]:
                print(f"      deployed ({fp}) -> {p}")
        elif r["ok"]:
            dest = deploy_paths(t, mql5_dir)[1]
            print(f"      NOT deployed — a chart still loads whatever is at {dest}; "
                  f"re-run with --deploy to copy this build there")
        failed += 0 if r["ok"] else 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
