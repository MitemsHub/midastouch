#!/usr/bin/env python3
"""Rename this project folder so the name describes what the repo actually is.

WHY THIS IS A SCRIPT AND NOT A ONE-OFF `mv`. The folder is `Synthetic Indices Bot`
while its remote is `mitemshub-indices` and its contents are the Upcomers venue and
methodology layer. The name has been wrong since the synthetic program closed, and a
wrong name is how someone eventually reopens the wrong thread.

WHY IT IS ORDERED THE WAY IT IS. The move happens FIRST and the reference rewrite
second, against the *new* absolute paths. If the move fails — which on Windows it does
whenever any process holds the directory open, and this app does — then nothing has been
rewritten and the repo is still self-consistent. Rewriting first would leave instructions
pointing at a folder that does not exist, which is the worse of the two failure modes.

WHAT IT DELIBERATELY DOES NOT DO. It does not touch the git remote. Renaming a GitHub
repository is two steps (rename on GitHub, *then* `git remote set-url`), and pointing the
remote at a name that does not exist yet breaks `git push` silently. It prints both
commands instead. It also leaves dated historical documents alone: the phase plans under
`docs/superpowers/plans/` say "Synthetic Indices Bot" because that is what the folder was
called on 2026-07-04, and a record rewritten to match the present is no longer a record.

    python scripts/rename_project.py            # dry run: show the plan
    python scripts/rename_project.py --apply     # move the folder, then rewrite refs
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

OLD_NAME = "Synthetic Indices Bot"
NEW_NAME = "Upcomers-Venue"

#: Live instructions only. Dated historical documents are records, not instructions,
#: and are intentionally absent from this list.
LIVE_REFERENCE_FILES = (
    "README.md",
    "docs/DEPLOYMENT_RUNBOOK.md",
    "docs/MIDASTOUCH_HEALTH_GUIDE.md",
)


def plan(root: Path, new_name: str) -> tuple[Path, list[tuple[Path, int]]]:
    """Where the folder would go and which live files name the old path."""
    target = root.parent / new_name
    hits: list[tuple[Path, int]] = []
    for rel in LIVE_REFERENCE_FILES:
        p = root / rel
        if not p.is_file():
            continue
        n = p.read_text(encoding="utf-8", errors="replace").count(OLD_NAME)
        if n:
            hits.append((p, n))
    return target, hits


TASK_NAME = "MIDASTOUCH Arm Supervisor"
#: The task this installer REPLACES (2026-09-22): the predecessor was paper-scoped in name
#: and interactive-logon-only in fact, so it is probed too -- a checkout still carrying
#: only the legacy registration is exactly the case this re-point must not miss.
LEGACY_TASK_NAMES = ("MitemshubPaperSupervisor",)


def refresh_scheduled_task(target: Path) -> None:
    """Re-point the paper supervisor's scheduled task at the new folder.

    WHY THIS IS PART OF THE RENAME AND NOT A FOOTNOTE. A Task Scheduler action stores an
    ABSOLUTE path. After the move the task still fires every 20 minutes, still fails, and
    still writes nothing — because a task that cannot start produces no log line. The
    supervisor would be dead and the only symptom would be an absence: exactly the
    failure mode this repo keeps auditing (a marker asserting an arrangement that has
    ended). The installer derives its own paths from `$PSScriptRoot`, so re-running it
    from the new location is the whole fix; refusing to guess if it is not there is the
    rest of it.
    """
    installer = target / "scripts" / "install_paper_task.ps1"
    if not installer.is_file():
        print(f"\nNOTE: {installer} not found — no scheduled task was refreshed.")
        return
    # The probe must be able to say NO. An earlier version ended the PowerShell command
    # with a bare `exit 0`, which forced success and made this branch unreachable: an
    # absent task would have been silently RE-INSTALLED, undoing a deliberate removal.
    # The exit code has to come from the query itself.
    names = ", ".join(f"'{n}'" for n in (TASK_NAME, *LEGACY_TASK_NAMES))
    probe = (f"$n = {names}; "
             "$t = $n | ForEach-Object { Get-ScheduledTask -TaskName $_ -ErrorAction "
             "SilentlyContinue }; if ($t) { exit 0 } else { exit 3 }")
    try:
        q = subprocess.run(["powershell", "-NoProfile", "-Command", probe],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"\nNOTE: could not query the scheduled task ({exc}).")
        return
    if q.returncode != 0:
        print(f"\nno scheduled task named {TASK_NAME} "
              f"(or {', '.join(LEGACY_TASK_NAMES)}) is registered; nothing to "
              f"re-point (it will not be installed behind your back).")
        return
    print(f"\nre-pointing scheduled task {TASK_NAME} at the new location "
          f"(re-running the installer also replaces the legacy interactive task, if any)...")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-File", str(installer), "-Apply"],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  FAILED to re-run the installer ({exc}). The task still points at the "
              f"OLD path and will fail silently — re-run it by hand:")
        print(f"    powershell -NoProfile -File \"{installer}\" -Apply")
        return
    tail = [ln for ln in (r.stdout or "").splitlines() if ln.strip()][-6:]
    for ln in tail:
        print(f"  {ln}")
    if r.returncode != 0:
        print(f"  installer exited {r.returncode}; VERIFY the task target by hand.")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--to", default=NEW_NAME,
                    help=f"new folder name (default {NEW_NAME!r})")
    ap.add_argument("--apply", action="store_true",
                    help="perform the move; without it this is a dry run")
    a = ap.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    if root.name != OLD_NAME:
        print(f"nothing to do: this script lives in {root.name!r}, not {OLD_NAME!r}.")
        print("(If the folder was already renamed, this is the expected outcome.)")
        return 0

    target, hits = plan(root, a.to)
    print(f"source  {root}")
    print(f"target  {target}")
    print(f"live files naming the old path ({len(hits)}):")
    for p, n in hits:
        print(f"  {n:>2}x  {p.relative_to(root)}")

    if target.exists():
        print(f"\nREFUSING: {target} already exists. Move or remove it first — this "
              f"script will not merge two directories by guessing.")
        return 2

    if not a.apply:
        print("\ndry run. Re-run with --apply to perform the move.")
        print("NOTE the move needs the directory to be free: close this session, "
              "the editor, and any terminal whose cwd is inside it.")
        return 0

    try:
        os.rename(root, target)
    except OSError as exc:
        print(f"\nREFUSING: could not move the directory: {exc}")
        print("Nothing was changed — the reference files were not touched. A process "
              "still holds the folder open (an editor, a terminal, or the app running "
              "this agent). Close them and retry.")
        return 3

    print(f"\nmoved -> {target}")
    for p, _n in hits:
        newp = target / p.relative_to(root)
        txt = newp.read_text(encoding="utf-8")
        newp.write_text(txt.replace(OLD_NAME, a.to), encoding="utf-8")
        print(f"  rewrote {newp.relative_to(target)}")

    refresh_scheduled_task(target)

    print(
        "\nnext, if you also want the REMOTE renamed (not done here on purpose):\n"
        "  gh repo rename <new-name> --repo MitemsHub/mitemshub-indices\n"
        "  git remote set-url origin https://github.com/MitemsHub/<new-name>.git\n"
        "Run them in that order — setting the URL before the repo exists breaks push."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
